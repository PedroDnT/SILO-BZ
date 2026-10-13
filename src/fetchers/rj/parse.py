"""Parsing rules for RJ case pages on administrador judicial websites (#845).

Pure functions over HTML text, so every rule is tested offline against saved
fixtures. Nothing here fetches, and nothing here guesses: a case page with no
CNJ process number yields no case, and a document link always comes from an
anchor on a page that was fetched.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional, Sequence
from urllib.parse import parse_qs, urldefrag, urljoin, urlsplit

from lxml import html as lxml_html

# NNNNNNN-DD.AAAA.J.TR.OOOO, as printed; or the same 20 digits unpunctuated
# right after a "processo" label (some sites print it bare).
_CNJ_PRINTED = re.compile(r"(?<!\d)(\d{7})-(\d{2})\.(\d{4})\.(\d)\.(\d{2})\.(\d{4})(?!\d)")
_CNJ_BARE = re.compile(r"processo[^0-9]{0,30}(?<!\d)(\d{20})(?!\d)", re.I)

# Headings that name a site section, not a debtor.
_SECTION_HEADINGS = {
    "processo", "processos", "contato", "newsletter", "institucional", "links",
    "administracao judicial", "recuperacao judicial", "recuperacoes judiciais",
    "falencia", "falencias", "areas de atuacao", "documentos", "menu",
}


def fold(text: str) -> str:
    """Lower case, no accents, single spaces: the form every rule matches on."""
    norm = unicodedata.normalize("NFKD", text or "")
    norm = "".join(c for c in norm if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", norm).strip().lower()


def cnj_numbers(text: str) -> List[str]:
    """Every CNJ process number in the text, as 20 digits, first seen first."""
    found: List[str] = []
    for m in _CNJ_PRINTED.finditer(text or ""):
        n = "".join(m.groups())
        if n not in found:
            found.append(n)
    for m in _CNJ_BARE.finditer(text or ""):
        if m.group(1) not in found:
            found.append(m.group(1))
    return found


# ---------------------------------------------------------------------------
# Document type from the title. Rules only; the first that matches wins, so
# the specific ones come first. "outros" when nothing matches.
# ---------------------------------------------------------------------------
_TIPO_RULES: Sequence[tuple] = (
    ("aditivo_plano", r"\b(aditivo|aditamento|modificativ\w*|modificacao)\b.*\bplano\b|\bplano\b.*\b(aditivo|aditamento|modificativ\w*)\b"),
    ("ata_agc", r"\bata\b.*\b(assembleia|agc)\b|\b(assembleia|agc)\b.*\bata\b"),
    ("edital_agc", r"\bedital\b.*\b(assembleia|agc|convocacao)\b|\bconvocacao\b.*\b(assembleia|agc)\b"),
    # Art. 7, §2 is the AJ's own list. Art. 7, §1 is only the habilitation
    # deadline, printed inside the debtor's art. 52 edital, so it does not count.
    ("relacao_credores_aj", r"(art(igo|\.)?\s*7o?\W{0,4}(§\s*2|par\.?\s*segundo|paragrafo\s*(2|segundo))|segundo edital|2o edital|relacao de credores do (administrador|aj)|\b(lista|relacao) de credores (do |da )?(aj\b|administrador))"),
    ("relacao_credores_devedor", r"(art\.?\s*52|artigo\s*52|primeiro edital|1o edital|art\.?\s*51|relacao (nominal )?(de )?credores|lista de credores)"),
    ("qgc", r"\b(qgc|quadro geral)\b"),
    ("rma", r"\b(rma|relatorio mensal|relatorios mensais|relatorio de atividades|relatorio mensal de atividades|relatorio inicial de atividades)\b"),
    ("peticao_inicial", r"\b(peticao inicial|pet\.? inicial|inicial)\b|^pedido de recuperacao judicial\b"),
    # Homologating the plan is the decision that grants the recuperação (art. 58).
    ("sentenca_concessao", r"\bhomologacao do plano\b"),
    ("plano", r"\bplano\b|^[\d\W]*prj$"),
    ("decisao_deferimento", r"\b(defer\w*)\b.*\bprocessamento\b|\bprocessamento\b.*\bdefer\w*"
                            r"|\bdefer\w*\s+(d[ao]s?\s+)?(pedido\s+(d[ea]\s+)?)?(recuperacao judicial|rj)\b"
                            r"|\bdecisao de processamento d[ao] (rj|recuperacao judicial)\b"),
    # The court's own wording in a DJEN act: "Defiro o processamento ...".
    ("decisao_deferimento", r"\bdefir\w*\s+(o\s+)?(pedido\s+de\s+)?processamento\b"),
    ("sentenca_concessao", r"\bsentenca\b.*\b(concess\w*|homolog\w*)\b|\b(concess\w*)\b.*\brecuperacao\b"),
    ("demonstracoes_contabeis", r"\b(demonstracoes contabeis|demonstrativos contabeis|balanco|balancete|dre)\b"),
)


def classify_tipo(title: str, section: str = "") -> str:
    """The document type from its title, then from the section it sits in."""
    for text in (fold(title), fold(f"{section} {title}")):
        for tipo, rule in _TIPO_RULES:
            if re.search(rule, text):
                return tipo
    return "outros"


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@dataclass
class DocLink:
    url: str
    titulo: str
    section: str = ""


@dataclass
class CasePage:
    numero_processo: Optional[str]
    devedor_nome: Optional[str]
    vara: Optional[str]
    documents: List[DocLink] = field(default_factory=list)
    other_numbers: List[str] = field(default_factory=list)


def _text(el) -> str:
    return re.sub(r"\s+", " ", el.text_content() or "").strip()


def _base(tree, base_url: str) -> str:
    """The URL relative links resolve against: the page's <base href>, else its own URL."""
    hrefs = tree.xpath("//base/@href")
    return urljoin(base_url, hrefs[0].strip()) if hrefs and hrefs[0].strip() else base_url


def _absolute(base: str, href: str) -> str:
    """An anchor's absolute URL, without the #fragment (it never reaches the server)."""
    return urldefrag(urljoin(base, href.strip()))[0]


def case_links(page_html: str, base_url: str, pattern: str, text_pattern: str = "") -> List[str]:
    """Case page URLs on a list page: every anchor whose URL matches ``pattern``.

    ``text_pattern`` (optional) is a regex the anchor's folded text must also
    match, for lists that mix case types and print the type only in the card.
    """
    tree = lxml_html.fromstring(page_html)
    base = _base(tree, base_url)
    rx = re.compile(pattern)
    trx = re.compile(text_pattern) if text_pattern else None
    out: List[str] = []
    for a in tree.xpath("//a[@href]"):
        url = _absolute(base, a.get("href"))
        if trx is not None and not trx.search(fold(_text(a))):
            continue
        if rx.search(url) and url not in out:
            out.append(url)
    return out


def _debtor(tree) -> Optional[str]:
    heads = [h for h in (_text(h) for h in tree.xpath("//h1|//h2|//h3|//h4|//h5|//h6")) if h]
    folded = [fold(h) for h in heads]
    if "processo" in folded:
        heads, folded = heads[folded.index("processo") + 1:], folded[folded.index("processo") + 1:]
    for h, f in zip(heads, folded):
        if f not in _SECTION_HEADINGS:
            return h
    # Pages with no heading at all (static exports): the page <title>.
    if not heads:
        title = _text(tree.xpath("//title")[0]) if tree.xpath("//title") else ""
        return title or None
    return None


_TYPE_PREFIX = re.compile(r"^(recupera[cç][aã]o (judicial|extrajudicial)|fal[eê]ncia)\s*[:\-\u2013]?\s*", re.I)


def _debtor_at(tree, xpath: str) -> Optional[str]:
    """The debtor from an element the site config names, minus a leading case type."""
    found = tree.xpath(xpath)
    text = _text(found[0]) if found else ""
    text = _TYPE_PREFIX.sub("", text).strip()
    return text or None


def _vara(tree) -> Optional[str]:
    """The text of the smallest element that starts with "Vara:", label removed."""
    for el in tree.xpath("//p|//li|//span|//td|//div"):
        t = _text(el)
        if fold(t).startswith("vara:") and len(t) < 250:
            return t.split(":", 1)[1].strip(" .") or None
    return None


def _section_of(a) -> str:
    """The table header or the nearest heading above the link."""
    th = a.xpath("ancestor::table[1]/thead//th[1]")
    if th:
        return _text(th[0])
    heads = a.xpath("preceding::*[self::h2 or self::h3 or self::h4 or self::h5][1]")
    return _text(heads[0]) if heads else ""


# Link texts that name the action, not the document.
_GENERIC_LABEL = re.compile(r"^(download|baixar|clique|aqui|visualizar|abrir|ver arquivo)\b")


def _context_title(a) -> str:
    """For a "DOWNLOAD" link: the text just before it, back to the previous line break,
    else the closest paragraph above it. Empty when neither is a short label."""
    parts, node = [], a
    while True:
        prev = node.getprevious()
        parts.append((prev.tail if prev is not None else node.getparent().text) or "")
        if prev is None or prev.tag == "br":
            break
        if isinstance(prev.tag, str):  # not a comment or processing instruction
            parts.append(_text(prev))
        node = prev
    before = re.sub(r"\s+", " ", "".join(reversed(parts))).strip(" :-\u2013\u00b7")
    if before and len(before) <= 200:
        return before
    above = a.xpath("preceding::p[normalize-space()][1]")
    text = _text(above[0]) if above else ""
    return text if 0 < len(text) <= 200 else ""


def _title_of(a, url: str) -> str:
    nome = parse_qs(urlsplit(url).query).get("nome")
    if nome and nome[0].strip():
        return nome[0].strip()
    row = a.xpath("ancestor::tr[1]")
    if row:
        cells = [_text(td) for td in row[0].xpath("./td")]
        cells = [c for c in cells if c and fold(c) not in {"baixar", "download", "visualizar"}]
        if cells:
            return cells[0]
    label = re.sub(r"^baixar\s+", "", (a.get("aria-label") or "").strip(), flags=re.I)
    if label:
        return label
    kids = [_text(c) for c in a if isinstance(c.tag, str) and _text(c)]
    if len(kids) >= 2:  # a title and then a size / "Baixar": the title is the first
        return kids[0]
    text = _text(a)
    if fold(text) in _GENERIC_LINK_TEXT or _GENERIC_LABEL.match(fold(text)):
        return _nearby_title(a) or _context_title(a) or text
    return text


# Link texts that name the action, not the document.
_GENERIC_LINK_TEXT = {"", "baixar", "download", "dowload", "visualizar", "abrir", "ver"}


def _nearby_title(a) -> str:
    """The title printed next to a "Download" button or an image-only link.

    The nearest paragraph or heading before the link, but only inside the
    link's own parent block, so a link with no title of its own never borrows
    the previous document's.
    """
    parent = a.getparent()
    if parent is None:
        return ""
    prev = a.xpath("preceding::*[self::p or self::h4 or self::h5 or self::h6][1]")
    if prev and parent in prev[0].iterancestors():
        return _text(prev[0])
    return ""


def parse_case_page(page_html: str, base_url: str, doc_pattern: str, debtor_xpath: str = "") -> CasePage:
    tree = lxml_html.fromstring(page_html)
    numbers = cnj_numbers(tree.text_content())
    base = _base(tree, base_url)
    rx = re.compile(doc_pattern)
    docs: List[DocLink] = []
    by_url = {}
    for a in tree.xpath("//a[@href]"):
        url = _absolute(base, a.get("href"))
        if not rx.search(url):
            continue
        titulo = _title_of(a, url)
        if url in by_url:
            # The same file linked twice: an empty first anchor (an icon) takes
            # the title of a later one, so the row is not left without a title.
            if not by_url[url].titulo and titulo:
                by_url[url].titulo = titulo
                by_url[url].section = _section_of(a)
            continue
        by_url[url] = DocLink(url=url, titulo=titulo, section=_section_of(a))
        docs.append(by_url[url])
    return CasePage(
        numero_processo=numbers[0] if numbers else None,
        devedor_nome=(_debtor_at(tree, debtor_xpath) if debtor_xpath else None) or _debtor(tree),
        vara=_vara(tree),
        documents=docs,
        other_numbers=numbers[1:],
    )
