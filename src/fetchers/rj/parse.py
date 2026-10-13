"""Parsing rules for RJ case pages on administrador judicial websites (#845).

Pure functions over HTML text, so every rule is tested offline against saved
fixtures. Nothing here fetches, and nothing here guesses: a case page with no
CNJ process number yields no case, and a document link always comes from an
anchor on a page that was fetched.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional, Sequence
from urllib.parse import parse_qs, unquote, urldefrag, urljoin, urlsplit, urlunsplit

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
    "busca", "buscar", "fale conosco",
}


def fold(text: str) -> str:
    """Lower case, no accents, single spaces: the form every rule matches on."""
    norm = unicodedata.normalize("NFKD", text or "")
    norm = "".join(c for c in norm if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", norm).strip().lower()


def cnj_numbers(text: str) -> List[str]:
    """Every CNJ process number in the text, as 20 digits, first seen first."""
    found: List[str] = []
    text = re.sub(r"[\u2010-\u2015]", "-", text or "")  # typographic hyphens, as some sites print them
    for m in _CNJ_PRINTED.finditer(text):
        n = "".join(m.groups())
        if n not in found:
            found.append(n)
    for m in _CNJ_BARE.finditer(text):
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
    ("relacao_credores_aj", r"(art(igo|\.)?\s*7o?\W{0,4}(§\s*2|par\.?\s*segundo|paragrafo\s*(2|segundo))|segundo edital|2[o°] edital|relacao de credores do (administrador|aj)|\b(lista|relacao) de credores (do |da )?(aj\b|administrador)|§\s*2o?\s+do\s+art(igo|\.)?\s*7)"),
    ("relacao_credores_devedor", r"(art\.?\s*52|artigo\s*52|primeiro edital|1[o°] edital|art\.?\s*51|relacao (nominal )?(de )?credores|lista de credores)"),
    ("qgc", r"\b(qgc|quadro geral)\b"),
    ("rma", r"\b(rma|relatorio mensal|relatorios mensais|relatorio de atividades|relatorio mensal de atividades|relatorio inicial d[ea]s? atividades)\b"),
    # "Relatório Inicial" is the AJ's first report, not the debtor's petition.
    ("peticao_inicial", r"\b(peticao inicial|pet\.? inicial|(?<!relatorio )(?<!emenda a )inicial)\b|^pedido de recuperacao judicial\b"),
    # Homologating the plan is the decision that grants the recuperação (art. 58).
    ("sentenca_concessao", r"\bhomologacao do (plano|prj)\b"),
    ("plano", r"\bplano\b|^[\d\W]*prj$"),
    ("decisao_deferimento", r"\b(defer\w*)\b.*\bprocessamento\b|\bprocessamento\b.*\bdefer\w*"
                            r"|\bdefer\w*\s+(d[aeo]s?\s+)?(pedido\s+(d[ea]\s+)?)?(recuperacao judicial|rj)\b"
                            r"|\b(decisao|despacho)\W+(?:de\W+)?processamento d[ao] (rj|recuperacao judicial)\b|\bdecisao defer\w*\s+(a\s+)?recuperacao\s*$|\bdef\b.*\bproc\b"
                            r"|^deferimento d[ao] recuperacao$"),
    # The court's own wording in a DJEN act: "Defiro o processamento ...".
    ("decisao_deferimento", r"\bdefir\w*\s+(o\s+)?(pedido\s+de\s+)?processamento\b"),
    ("sentenca_concessao", r"\bsentenca\b.*\b(concess\w*|homolog\w*)\b|\b(concess\w*|conced\w*)\b.*\brecuperacao\b"),
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


_ONCLICK_URL = re.compile(r"""location(?:\.href)?\s*=\s*['"]([^'"]+)['"]""")


def _text(el) -> str:
    return re.sub(r"\s+", " ", el.text_content() or "").strip()


def _base(tree, base_url: str) -> str:
    """The URL relative links resolve against: the page's <base href>, else its own URL."""
    hrefs = tree.xpath("//base/@href")
    return urljoin(base_url, hrefs[0].strip()) if hrefs and hrefs[0].strip() else base_url


def _absolute(base: str, href: str) -> str:
    """An anchor's absolute URL, without the #fragment (it never reaches the server)."""
    # Trailing %20 / spaces (some download scripts pad the "nome" parameter) name the same file.
    return re.sub(r"(?:%20|\s)+$", "", urldefrag(urljoin(base, href.strip()))[0])


def _same_host_https(page_url: str, url: str) -> str:
    """A page served over https that links its own pages as http:// (a leftover
    from before the move to https) would list the same case twice: use https."""
    page, parts = urlsplit(page_url), urlsplit(url)
    if page.scheme == "https" and parts.scheme == "http" and parts.netloc == page.netloc:
        return urlunsplit(parts._replace(scheme="https"))
    return url


def _card_text(a, resolve, rx) -> str:
    """The text of the card around an anchor: its largest ancestor that holds no
    other case link. For lists whose card prints the case type outside the link."""
    own = resolve(a)
    card = a
    for anc in a.iterancestors():
        others = {resolve(x) for x in anc.xpath(".//a[@href]")} - {own}
        if any(rx.search(u) for u in others):
            break
        card = anc
    return _text(card)


def _heading_above(el) -> str:
    """The folded text of the nearest h1-h4 heading before the element."""
    heads = el.xpath("preceding::*[self::h1 or self::h2 or self::h3 or self::h4][1]")
    return fold(_text(heads[0])) if heads else ""


def case_links(page_html: str, base_url: str, pattern: str, text_pattern: str = "",
               section_pattern: str = "", scope_xpath: str = "",
               card: bool = False, anchors_xpath: str = "") -> List[str]:
    """Case page URLs on a list page: every link whose URL matches ``pattern``.

    ``text_pattern`` (optional) is a regex the anchor's folded text must also
    match, for lists that mix case types and print the type only in the card.
    ``section_pattern`` (optional) is a regex the folded text of the heading
    above the link must match, for lists that group the cases under a heading
    per type ("Recuperação Judicial", "Falência"). ``scope_xpath`` (optional)
    selects the elements the case links must sit inside, for pages that print
    other links of the same shape (articles, menus) outside the case list.

    Besides anchors, three forms of a clickable container are read: a table row
    ``onclick="window.location.href='URL'"``, an Elementor Happy Addons
    ``data-ha-element-link='{"url": "..."}'`` and a JetEngine listing item
    ``data-url="URL"``. With ``card`` the ``text_pattern`` is matched against the
    whole card around the link (its largest ancestor holding no other case link),
    for lists whose card prints the type in a sibling element rather than in the link.
    ``anchors_xpath`` (optional) narrows the anchors considered to those it selects,
    for lists whose cards carry the type as a class on a container (ADJUD).
    """
    tree = lxml_html.fromstring(page_html)
    base = _base(tree, base_url)
    rx = re.compile(pattern)
    trx = re.compile(text_pattern) if text_pattern else None
    srx = re.compile(section_pattern) if section_pattern else None
    out: List[str] = []
    roots = tree.xpath(scope_xpath) if scope_xpath else [tree]

    def resolve(el) -> str:
        return _same_host_https(base_url, _absolute(base, el.get("href")))

    def keep(url: str, el) -> None:
        if rx.search(url) and url not in out and (srx is None or srx.search(_heading_above(el))):
            out.append(url)

    for root in roots:
        for a in root.xpath(anchors_xpath or ".//a[@href]"):
            url = resolve(a)
            if trx is not None and rx.search(url):
                if not trx.search(fold(_card_text(a, resolve, rx) if card else _text(a))):
                    continue
            keep(url, a)
        for el in root.xpath(".//*[@onclick]"):
            m = _ONCLICK_URL.search(el.get("onclick"))
            if m:
                keep(urljoin(base_url, m.group(1).strip()), el)
        for el in root.xpath(".//*[@data-ha-element-link]"):
            try:
                href = json.loads(el.get("data-ha-element-link")).get("url") or ""
            except ValueError:
                continue
            if href.strip():
                keep(_same_host_https(base_url, urljoin(base_url, href.strip())), el)
        for el in root.xpath(".//*[@data-url]"):
            if (el.get("data-url") or "").strip():
                keep(_same_host_https(base_url, urljoin(base_url, el.get("data-url").strip())), el)
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


def _context_title(a, headings: bool = False) -> str:
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
    # With ``headings`` (a button labelled "Download"), a heading closer than any paragraph is the title.
    kinds = "p[normalize-space()] or self::h2 or self::h3 or self::h4 or self::h5" if headings else "p[normalize-space()]"
    above = a.xpath(f"preceding::*[self::{kinds}][1]")
    text = _text(above[0]) if above else ""
    return text if 0 < len(text) <= 200 else ""


def _list_item_title(a) -> str:
    """For a "Download" button inside a list item: the item's own text (its date
    line, in <small>, left out). Empty when the item holds several links, so one
    item never lends its text to more than one file."""
    items = a.xpath("ancestor::li[1]")
    if not items or len(items[0].xpath(".//a[@href]")) != 1:
        return ""
    parts = items[0].xpath(".//text()[not(ancestor::small) and not(ancestor::a)]")
    text = re.sub(r"\s+", " ", " ".join(parts)).strip()
    return text if 0 < len(text) <= 200 else ""


def _title_of(a, url: str, title_xpath: str = "") -> str:
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
        found = (_xpath_title(a, title_xpath) if title_xpath else "") or _nearby_title(a) or _list_item_title(a) or _context_title(a, headings=bool(text))
        if found:
            return found
    if text:
        return text
    # An icon-only link with nothing printed beside it: the file name is the only title.
    stem = unquote(urlsplit(url).path.rsplit("/", 1)[-1]).rsplit(".", 1)[0]
    return re.sub(r"[-_]+", " ", stem).strip()


# Link texts that name the action, not the document.
_GENERIC_LINK_TEXT = {"", "baixar", "download", "dowload", "visualizar", "abrir", "ver", "arquivo para download"}


def _xpath_title(a, xpath: str) -> str:
    """The text of the first element the site's ``doc_title_xpath`` finds from the link."""
    found = a.xpath(xpath)
    return _text(found[0]) if found else ""


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


_CARD_TITLE = "(.//strong|.//b|.//h4|.//h5|.//h6)[normalize-space()][1]"


def _card_title(el) -> str:
    """The title of a document card whose download is a button, not an anchor:
    the first bold text or small heading in the nearest ancestor that has one."""
    for anc in list(el.iterancestors())[:4]:
        found = anc.xpath(_CARD_TITLE)
        if found:
            return _text(found[0])
    return ""


def _debtor_from_title(tree) -> Optional[str]:
    """The debtor as the page <title> names it: "<debtor> - <site name>" (hyphen or en/em dash)."""
    title = _text(tree.xpath("//title")[0]) if tree.xpath("//title") else ""
    parts = re.split(r"\s[-\u2013\u2014]\s", title)
    name = " - ".join(parts[:-1]).strip() if len(parts) > 1 else ""
    return name or None


_PROCESS_TAIL = re.compile(r"\s*[-\u2010-\u2015]\s*processo\s*n\S*\s.*$", re.I)


def _trim_process(name: Optional[str]) -> Optional[str]:
    """A heading that prints "<debtor> – Processo nº ..." names the debtor before the dash."""
    return (_PROCESS_TAIL.sub("", name).strip() or None) if name else name


def case_blocks(page_html: str, xpath: str) -> List[str]:
    """The HTML of each element ``xpath`` selects: one case block on an inline list page.

    Some AJ sites have no page per case: one page holds every case, each in its own
    block (an accordion item, a table row, a section) with the CNJ number and the
    document links. Each block is then read like a case page by ``parse_case_page``.
    The page's <base>, if any, is kept so relative links resolve as on the page.
    """
    tree = lxml_html.fromstring(page_html)
    base = tree.xpath("//base[@href]")
    head = lxml_html.tostring(base[0], encoding="unicode") if base else ""
    return [f"<html><head>{head}</head><body>{lxml_html.tostring(el, encoding='unicode')}</body></html>"
            for el in tree.xpath(xpath)]


def parse_case_page(page_html: str, base_url: str, doc_pattern: str, debtor_xpath: str = "",
                    debtor_from_title: bool = False, doc_title_xpath: str = "") -> CasePage:
    """``debtor_from_title`` for sites whose headings are document titles, not the debtor.
    ``doc_title_xpath`` (relative to the link) finds the title of a bare "Download" button."""
    tree = lxml_html.fromstring(page_html)
    numbers = cnj_numbers(tree.text_content())
    base = _base(tree, base_url)
    rx = re.compile(doc_pattern)
    docs: List[DocLink] = []
    by_url = {}
    textless = set()
    for a in tree.xpath("//a[@href]"):
        url = _absolute(base, a.get("href"))
        if not rx.search(url):
            continue
        titulo, section = _title_of(a, url, doc_title_xpath), _section_of(a)
        # A bare "Download" button under the document's own heading: the heading is the title.
        if fold(titulo) in _GENERIC_LINK_TEXT and section:
            titulo = section
        if url in by_url:
            # The same file linked twice: an empty first anchor (an icon) takes
            # the title of a later one, so the row is not left without a title.
            # That includes a first anchor with no text of its own, whose title is
            # only the file name or a neighbouring line, when a later one has text.
            if (not by_url[url].titulo or (url in textless and _text(a))) and titulo:
                by_url[url].titulo = titulo
                by_url[url].section = section
                textless.discard(url)
            continue
        if not _text(a):
            textless.add(url)
        by_url[url] = DocLink(url=url, titulo=titulo, section=section)
        docs.append(by_url[url])
    # Some sites make the download a <button data-file="URL">: same document, no anchor.
    for el in tree.xpath("//*[@data-file]"):
        url = _absolute(base, el.get("data-file"))
        if not rx.search(url) or url in by_url:
            continue
        by_url[url] = DocLink(url=url, titulo=_card_title(el) or _title_of(el, url), section=_section_of(el))
        docs.append(by_url[url])
    return CasePage(
        numero_processo=numbers[0] if numbers else None,
        devedor_nome=_trim_process(
            (_debtor_at(tree, debtor_xpath) if debtor_xpath else None)
            or (_debtor_from_title(tree) if debtor_from_title else None)
            or _debtor(tree)),
        vara=_vara(tree),
        documents=docs,
        other_numbers=numbers[1:],
    )
