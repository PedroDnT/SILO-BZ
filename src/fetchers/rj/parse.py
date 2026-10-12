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
from urllib.parse import parse_qs, urljoin, urlsplit

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
    ("relacao_credores_aj", r"(art(igo|\.)?\s*7o?\W{0,4}§\s*2|segundo edital|2o edital|relacao de credores do (administrador|aj))"),
    ("relacao_credores_devedor", r"(art\.?\s*52|artigo\s*52|primeiro edital|1o edital|art\.?\s*51|relacao (nominal )?de credores|lista de credores)"),
    ("qgc", r"\b(qgc|quadro geral)\b"),
    ("rma", r"\b(rma|relatorio mensal|relatorios mensais|relatorio de atividades|relatorio mensal de atividades)\b"),
    ("peticao_inicial", r"\b(peticao inicial|pet\.? inicial|inicial)\b"),
    ("plano", r"\bplano\b|^[\d\W]*prj$"),
    ("decisao_deferimento", r"\b(defer\w*)\b.*\bprocessamento\b|\bprocessamento\b.*\bdefer\w*|\bdeferimento (da |de )?(rj|recuperacao judicial)\b"),
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


def case_links(page_html: str, base_url: str, pattern: str) -> List[str]:
    """Case page URLs on a list page: every anchor whose URL matches ``pattern``."""
    tree = lxml_html.fromstring(page_html)
    rx = re.compile(pattern)
    out: List[str] = []
    for a in tree.xpath("//a[@href]"):
        url = urljoin(base_url, a.get("href").strip())
        if rx.search(url) and url not in out:
            out.append(url)
    return out


def _debtor(tree) -> Optional[str]:
    heads = [h for h in (_text(h) for h in tree.xpath("//h1|//h2|//h3|//h4|//h5")) if h]
    folded = [fold(h) for h in heads]
    if "processo" in folded:
        heads, folded = heads[folded.index("processo") + 1:], folded[folded.index("processo") + 1:]
    for h, f in zip(heads, folded):
        if f not in _SECTION_HEADINGS:
            return h
    return None


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
    return _text(a)


def parse_case_page(page_html: str, base_url: str, doc_pattern: str) -> CasePage:
    tree = lxml_html.fromstring(page_html)
    numbers = cnj_numbers(tree.text_content())
    rx = re.compile(doc_pattern)
    docs: List[DocLink] = []
    seen = set()
    for a in tree.xpath("//a[@href]"):
        url = urljoin(base_url, a.get("href").strip())
        if not rx.search(url) or url in seen:
            continue
        seen.add(url)
        docs.append(DocLink(url=url, titulo=_title_of(a, url), section=_section_of(a)))
    return CasePage(
        numero_processo=numbers[0] if numbers else None,
        devedor_nome=_debtor(tree),
        vara=_vara(tree),
        documents=docs,
        other_numbers=numbers[1:],
    )
