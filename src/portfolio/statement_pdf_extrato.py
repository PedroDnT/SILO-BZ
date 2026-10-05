"""Reader for the BTG "Extrato da Conta Investimento" PDF (text layer, co-branded "One Investimentos | BTG Pactual").

    python -m src.portfolio.statement_pdf_extrato FILE.pdf [FILE2.pdf ...] [--consolidate] [--mostrar-ativos]

An extrato whose labels are drawn as outlines (its text layer holds only the numbers and the SAC
footer) is read through ``statement_ocr``: numbers from the text layer, labels from OCR, then this
same parser in OCR mode (tolerant headings, codes / CNPJs / rates normalised and flagged).

The runner reads either BTG layout: the format is detected by content (``read_any_pdf_bytes``),
so a "Relatório de Performance" goes to ``statement_pdf`` and an extrato comes here.

Layout facts this reader is built on (docs/reference/portfolio/statement-pdf.md, "Extrato da
Conta Investimento"): a landscape page per table, every page headed "Extrato da Conta
Investimento" and "Período de DD/MM/YY a DD/MM/YY"; a "Sumário - Distribuição em DD/MM/YY" whose
``Total`` (end-date Saldo Bruto) is the statement's own total and whose class rows are the class
subtotals; one position table per section ("Fundo de Investimento - Posição", "Renda fixa -
Posição - <KIND>", "Previdência Individual - Posição - <cert>/PGBL", "Renda variável - Posição -
<KIND>", "Conta corrente - Posição"), each ending in its own subtotal. Every other section
(detalhamento, movimentação, rentabilidade, legends, disclaimers) is skipped.

Same hard rules as the other readers:

* the cover page is read only to build the masker (the unlabelled holder name line, "Conta
  investimento", "CPF" and the address line) and then discarded; every later line is scrubbed;
* the PDF bytes go to the extractor on STDIN (``statement_pdf.extract_pages``) and never touch disk;
* every table subtotal, every Sumário class row and the Sumário ``Total`` are checked within
  R$ 0,01 x the number of rows; a failure raises ``StatementTotalMismatch`` naming the check, the
  gap and the rows not read, by page, line and shape, never by their text;
* nothing is guessed: a line that cannot be placed stops the read, ``tipo`` and ``codigo`` come
  only from what the statement prints (the Ativo prefix, the section, the CNPJ, the ticker).
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

from src.portfolio import statement_ocr as ocr
from src.portfolio import statement_pdf as sp
from src.portfolio.mask import Masker, _strip_accents
from src.portfolio.statement import (
    Position,
    Statement,
    StatementError,
    StatementFormatError,
    StatementTotalMismatch,
    UnreadableRow,
    codigo_cnpj,
)

key = sp.key
CENT = Decimal("0.01")
EXTRATO_KEY = "extratodacontainvestimento"
TOKEN_ENDERECO = "[ENDERECO]"
MASK_TOKENS = ("[TITULAR]", "[CPF]", "[CONTA]", "[CNPJ_TITULAR]", TOKEN_ENDERECO)

# ---------------------------------------------------------------------------
# Tokens: this layout prints dd/mm/yy dates, en dashes, 9-decimal prices and 1.725 quantities.
# ---------------------------------------------------------------------------

_DATE = re.compile(r"^\d{2}/\d{2}/(\d{2}|\d{4})$")
_CNPJ = re.compile(r"^\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}$")
_NUM = re.compile(r"^-?(\d{1,3}(\.\d{3})+|\d+)(,\d+)?$")
_PCT = re.compile(r"^-?(\d{1,3}(\.\d{3})+|\d+)(,\d+)?%$")
_DASHES = {"-", "–", "—"}
_PERIOD = re.compile(r"per[ií]odo\s+de\s+(\d{2}/\d{2}/\d{2,4})\s+(?:a|à|até)\s+(\d{2}/\d{2}/\d{2,4})", re.I)
# OCR may drop the one-letter 'a' between the two dates, or misread 'Período'
_PERIOD_OCR = re.compile(r"per\S{0,2}odo\s+de\s+(\d{2}/\d{2}/\d{2,4})\s+(?:\S{1,3}\s+)?(\d{2}/\d{2}/\d{2,4})", re.I)
_CNPJ_ANY = re.compile(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}")
_TICKER = re.compile(r"^(?=[A-Z0-9]*[A-Z])[A-Z0-9]{4,6}\d{0,2}$")
_ATIVO_PREFIX = re.compile(r"^([A-Z]{2,5})-(.*)$")
_ATIVO_LIKE = re.compile(
    r"^(?:(?:CRA|CRI|DEB|CDB|CDCA|LCA|LCI|LF|LFS|LFSN|LFSC|LIG|LH|CCB|CCE|NCE|CPR|NC)-[A-Z0-9]*"
    r"|NTNB-P|NTNB1?|NTNF|NTNC|NTNI|LTN|LFT|[A-Z0-9]*\d[A-Z0-9]*)$"
)
REGISTRY_TIPO = {"CRA": "CRA", "CRI": "CRI", "DEB": "debênture", "CDB": "CDB", "LCA": "LCA", "LCI": "LCI"}
KIND_TIPO = {"cra": "CRA", "cri": "CRI", "debenture": "debênture", "cdb": "CDB", "lca": "LCA", "lci": "LCI"}
# Ativo (hyphen removed) -> the title spelling of identify.parse_tesouro ("NTN-B Principal 2035-05-15").
TESOURO_ATIVO = {
    "NTNBP": "NTN-B Principal",
    "NTNB": "NTN-B",
    "NTNB1": "NTN-B1",
    "NTNF": "NTN-F",
    "NTNC": "NTN-C",
    "NTNI": "NTN-I",
    "LTN": "LTN",
    "LFT": "LFT",
}
RV_KIND_TIPO = {"etf": "ETF", "etfs": "ETF", "acoes": "ação", "acao": "ação", "fii": "FII", "fiis": "FII"}
SUMARIO_GROUP = {
    "previdencia": "prev",
    "rendafixa": "rf",
    "fundosdeinvestimento": "fundos",
    "fundodeinvestimento": "fundos",
    "rendavariavel": "rv",
    "contacorrente": "cc",
}
GROUP_LABEL = {"prev": "Previdência", "rf": "Renda Fixa", "fundos": "Fundos de Investimento", "rv": "Renda Variável", "cc": "Conta Corrente"}
HEADER_VOCAB = {
    "emissor", "ativo", "emissao", "vencimento", "liquidez", "dias", "de", "carencia", "para", "data", "inicial",
    "taxa", "media", "ponderada", "quantidade", "preco", "r$", "saldo", "bruto", "ir", "iof", "liquido",
    "referencia", "cotas", "cotacao", "atual", "provisao", "variacao", "nominal", "fundo", "cnpj", "codigo",
    "qtde", "fechamento", "medio", "valor", "financeiro", "mercados", "em",
    "irr$", "iofr$",  # OCR reads 'IR R$' and 'IOF R$' as one word
}
HEADER_UPPER_OK = {"R$", "IR", "IOF", "CNPJ", "IR R$", "IOF R$"}


def tok_kind(t: str) -> str:
    """'D' date, 'C' CNPJ, 'P' percent, 'N' number, '-' missing, 'L' text."""
    if _DATE.match(t):
        return "D"
    if _CNPJ.match(t):
        return "C"
    if _PCT.match(t):
        return "P"
    if _NUM.match(t):
        return "N"
    if t in _DASHES:
        return "-"
    return "L"


@dataclass
class Tok:
    x: int
    t: str
    k: str

    @property
    def end(self) -> int:
        return self.x + len(self.t)


def tokens(line: str) -> list[Tok]:
    return [Tok(m.start(), m.group(), tok_kind(m.group())) for m in re.finditer(r"\S+", line)]


def shape_of(toks: list[Tok]) -> str:
    """The structure of a line, never its text: L text run, D date, N number, P percent, C CNPJ, - missing."""
    out: list[str] = []
    for t in toks:
        if t.k == "L" and out and out[-1] == "L":
            continue
        out.append(t.k)
    return "".join(out) or "empty"


def num(t: str) -> Decimal:
    return Decimal(t.strip().rstrip("%").replace(".", "").replace(",", "."))


def opt_num(t: Tok) -> Decimal | None:
    return None if t.k == "-" else num(t.t)


def date_of(t: str) -> dt.date:
    d, m, y = t.split("/")
    yy = int(y) + (2000 if len(y) == 2 else 0)
    return dt.date(yy, int(m), int(d))


def _gap_join(toks: list[Tok]) -> str:
    return " ".join(t.t for t in toks)


# ---------------------------------------------------------------------------
# Format detection.
# ---------------------------------------------------------------------------


def _lev(a: str, b: str) -> int:
    """Edit distance (insert, delete, substitute)."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _fuzzy_prefix(k: str, prefix: str) -> int | None:
    """Length of the start of ``k`` that reads as ``prefix`` with OCR noise (1 edit; 2 from 20 characters), or None."""
    if k.startswith(prefix):
        return len(prefix)
    if len(prefix) < 12:
        return None
    allowed = 2 if len(prefix) >= 20 else 1
    best = None
    for n in range(len(prefix) - allowed, len(prefix) + allowed + 1):
        if n <= 0 or n > len(k):
            continue
        d = _lev(k[:n], prefix)
        if d <= allowed and (best is None or d < best[0]):
            best = (d, n)
    return best[1] if best else None


def _approx_in(needle: str, hay: str, allowed: int = 2) -> bool:
    """``needle`` occurs in ``hay`` with at most ``allowed`` edits (Sellers' approximate substring match)."""
    if needle in hay:
        return True
    prev = [0] * (len(hay) + 1)
    for i, c in enumerate(needle, 1):
        cur = [i] + [0] * len(hay)
        for j, h in enumerate(hay, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (c != h))
        prev = cur
    return min(prev) <= allowed


def is_extrato(pages: list[str], tolerant: bool = False) -> bool:
    """True when the first page is headed 'Extrato da Conta Investimento' (the performance report never is).

    ``tolerant`` (OCR text only) accepts the heading with two OCR errors.
    """
    if not pages:
        return False
    k = key(pages[0])
    return EXTRATO_KEY in k or (tolerant and _approx_in(EXTRATO_KEY, k))


def _extract(data: bytes) -> tuple[list[str], str, "ocr.OcrResult | None"]:
    """The pages as layout text: the text layer, or, for the extrato whose labels are outlines, text layer + OCR."""
    pages, extractor = sp.extract_pages(data)
    if is_extrato(pages) or not ocr.may_need_ocr(pages):
        return pages, extractor, None
    # The SAC footer and no extrato heading in the text layer. Only page 1 is read by OCR first: if it
    # is not the extrato either, the file goes to the performance reader exactly as before.
    certain = ocr.needs_ocr(pages)  # nothing but numbers beside the footer
    if not certain and not ocr.available():
        return pages, extractor, None
    res = ocr.ocr_pages(data, first_page_ok=lambda text: is_extrato([text], tolerant=True))
    if res is None:
        if certain:
            raise StatementFormatError(
                "the PDF's text layer holds only numbers and the SAC footer, and OCR found no 'Extrato da Conta "
                "Investimento' heading on the first page: nothing was read"
            )
        return pages, extractor, None
    return res.pages, ocr.EXTRACTOR, res


def read_any_pdf_bytes(data: bytes):
    """(statement, diagnostics, layout) for either BTG PDF layout, picked by content.

    ``layout`` is ``"extrato"`` or ``"performance"``; anything that is not an extrato goes to the
    performance reader, exactly as before this reader existed. An extrato whose labels are drawn as
    outlines (a text layer of numbers and the SAC footer only) is read through OCR (``statement_ocr``).
    """
    pages, extractor, res = _extract(data)
    if res is not None:
        stmt, diag = parse_extrato_pages(pages, extractor, ocr_mode=True, ocr_stats=res.stats, line_ys=res.ys)
        return stmt, diag, "extrato"
    if is_extrato(pages):
        stmt, diag = parse_extrato_pages(pages, extractor)
        return stmt, diag, "extrato"
    stmt, diag = sp.parse_pdf_pages(pages, extractor)
    return stmt, diag, "performance"


def read_extrato_bytes(data: bytes):
    pages, extractor, res = _extract(data)
    return parse_extrato_pages(
        pages, extractor, ocr_mode=res is not None, ocr_stats=res.stats if res else None, line_ys=res.ys if res else None
    )


# ---------------------------------------------------------------------------
# The cover: masker only.
# ---------------------------------------------------------------------------


class _Scrubber:
    """The holder's masker plus the address, which ``Masker`` does not know. Transient: never store one."""

    __slots__ = ("_masker", "_patterns", "_name_words")

    def __init__(self, masker: Masker, address_parts: list[str], fuzzy_name: str | None = None):
        self._masker = masker
        # OCR text only: the holder's name words, to mask a reading one letter off from the cover's
        self._name_words = [_strip_accents(w).upper() for w in (fuzzy_name or "").split()]
        pats: list[re.Pattern[str]] = []
        for part in sorted({p for p in address_parts if p}, key=len, reverse=True):
            for variant in {part, _strip_accents(part)}:
                words = variant.split()
                if words:
                    pats.append(re.compile(r"\s+".join(re.escape(w) for w in words), re.I))
        self._patterns = pats

    def __repr__(self) -> str:
        return "_Scrubber(<redacted>)"

    def __call__(self, s: str) -> str:
        for p in self._patterns:
            s = p.sub(TOKEN_ENDERECO, s)
        s = str(self._masker.scrub(s))
        return self._fuzzy(s) if self._name_words else s

    def _fuzzy(self, s: str) -> str:
        """Two or more consecutive words that read as consecutive holder-name words, each at most one
        letter off (exactly, for words under four letters), with at least one long word: '[TITULAR]'."""
        words = self._name_words
        toks = list(re.finditer(r"\S+", s))
        norm = [_strip_accents(m.group()).upper().strip(".,;:") for m in toks]

        def close(a: str, b: str) -> bool:
            return a == b or (len(b) >= 4 and abs(len(a) - len(b)) <= 1 and _lev(a, b) <= 1)

        spans: list[tuple[int, int]] = []
        i = 0
        while i < len(toks):
            best = 0
            for j in range(len(words)):
                k = 0
                while i + k < len(toks) and j + k < len(words) and close(norm[i + k], words[j + k]):
                    k += 1
                if k >= 2 and any(len(words[j + q]) >= 4 for q in range(k)):
                    best = max(best, k)
            if best:
                spans.append((toks[i].start(), toks[i + best - 1].end()))
                i += best
            else:
                i += 1
        for a, b in reversed(spans):
            s = s[:a] + "[TITULAR]" + s[b:]
        return s

    @property
    def holder(self):
        return self._masker.holder


_LABEL_KEYS = ("containvestimento", "cpf", "periodo", "emitidoem", "extratodacontainvestimento", "informacoesdetalhadas")


def _cover_scrubber(cover: str, tolerant: bool = False) -> tuple[_Scrubber, list[str]]:
    lines = [ln.strip() for ln in cover.splitlines() if ln.strip()]
    # The real cover wraps the heading: "Informações detalhadas sobre" / "investimentos" (OCR, 2026-10-04).
    for i in range(len(lines) - 1):
        k = key(lines[i])
        if (k.endswith("informacoesdetalhadassobre") or (tolerant and _fuzzy_prefix(k, "informacoesdetalhadassobre"))) and key(
            lines[i + 1]
        ).startswith("investimentos"):
            lines[i : i + 2] = [lines[i] + " " + lines[i + 1]]
            break
    flat = _strip_accents("\n".join(lines))
    head = next((i for i, ln in enumerate(lines) if "informacoesdetalhadassobreinvestimentos" in key(ln)), None)
    if head is None and tolerant:
        head = next((i for i, ln in enumerate(lines) if _fuzzy_prefix(key(ln), "informacoesdetalhadassobreinvestimentos")), None)
    if head is None:
        raise StatementFormatError("cover page: no 'Informações detalhadas sobre investimentos' line, so the holder cannot be masked: nothing was read")
    rest = re.split(r"investimentos", _strip_accents(lines[head]), maxsplit=1, flags=re.I)
    nome = None
    name_idx = head
    if len(rest) == 2 and rest[1].strip() and not key(rest[1]).startswith(_LABEL_KEYS):
        nome = lines[head][len(lines[head]) - len(rest[1]) :].strip()
    elif head + 1 < len(lines) and not key(lines[head + 1]).startswith(_LABEL_KEYS):
        nome = lines[head + 1]
        name_idx = head + 1
    if not nome:
        raise StatementFormatError("cover page: no holder name line after 'Informações detalhadas sobre investimentos', so the holder cannot be masked: nothing was read")
    m = re.search(r"conta\s+investimento\s*:?\s*(\d[\d.\-/]*)", flat, re.I)
    conta = m.group(1) if m else None
    m = re.search(r"\bCPF\s*:?\s*(\d{3}\.?\d{3}\.?\d{3}-?\d{2})", flat, re.I)
    cpf = m.group(1) if m else None
    if cpf and tolerant:
        cpf = ocr.check_cpf(cpf)  # one OCR-confusable digit repaired by the check digits, so the mask matches
    notes = []
    if not conta:
        notes.append("Capa sem 'Conta investimento': o número da conta não pôde ser mascarado por valor.")
    if not cpf:
        notes.append("Capa sem 'CPF': mascarado só o formato de CPF.")
    # the address: every other line between the name and the period, each with its street part and CEP
    address: list[str] = []
    for ln in lines[name_idx + 1 :]:
        k = key(ln)
        if k.startswith("periodo") or k.startswith("emitidoem"):
            break
        if k.startswith(("containvestimento", "cpf")):
            continue
        address.append(ln)
        first = re.split(r",", ln)[0].strip()
        if len(first) >= 8:
            address.append(first)
        for cep in re.findall(r"\d{5}-?\d{3}", ln):
            address.append(cep)
    masker = Masker(nome, cpf, conta)
    return _Scrubber(masker, address, fuzzy_name=nome if tolerant else None), notes


# ---------------------------------------------------------------------------
# Sections.
# ---------------------------------------------------------------------------

_TITLE = re.compile(r"^[A-ZÀ-Ý][a-zà-ÿ]")


HEADING_PREFIXES = (
    "rendafixaposicaoconsolidadaporemissor",
    "previdenciaindividualposicao",
    "fundodeinvestimentoposicao",
    "posicoesabertasporaliquota",
    "previdenciainternaposicao",
    "rendavariavelposicao",
    "contacorrenteposicao",
    "sumariodistribuicao",
    "rendafixaposicao",
    "distribuicao",
)


def _canonical_key(k: str) -> str:
    """OCR text only: a heading key whose start reads as a known heading with OCR noise gets that heading's spelling."""
    for prefix in HEADING_PREFIXES:
        n = _fuzzy_prefix(k, prefix)
        if n is not None:
            return prefix + k[n:]
    return k


def heading_of(text: str, tolerant: bool = False) -> tuple[str, str] | None:
    """(section kind, argument) when the line is a section heading, else None.

    ``tolerant`` (OCR text only) reads a known heading with one OCR error (two in the long ones).
    """
    s = text.strip()
    if not _TITLE.match(s):
        return None
    k = key(s)
    if tolerant:
        k = _canonical_key(k)
    dashed = re.search(r"\S\s+[-–]\s+[A-Za-zÀ-ÿ]", s) is not None  # ' - <word>', never a missing value
    if k.startswith("sumariodistribuicao"):
        return ("sumario", "")
    if k == "indice" or k.startswith("disclaimer"):
        return ("ignore_page", "")  # the Disclaimers pages repeat section names ('Renda Fixa - Posição') as footnote titles
    if k.startswith(("distribuicao", "perfilderisco", "faleconosco")) or "abertasporaliquota" in k:
        return ("ignore", "")  # 'Previdência Individual - Posições abertas por alíquota' is not a position table
    if k.startswith("fundodeinvestimentoposicao"):
        return ("funds", "")
    if k.startswith("rendafixaposicaoconsolidadaporemissor"):
        return ("rf_emissor", "")
    if k.startswith("rendafixaposicao"):
        parts = [p.strip() for p in s.split(" - ")]
        return ("rf", parts[-1] if len(parts) >= 3 else "")
    if re.match(r"^previdencia(individual|interna)?posicao", k) and dashed:
        m = re.search(r"/\s*(PGBL|VGBL)\b", s, re.I)
        return ("prev", m.group(1).upper() if m else "")
    if k.startswith("rendavariavelposicao"):
        parts = [p.strip() for p in s.split(" - ")]
        return ("rv", parts[-1] if len(parts) >= 3 else "")
    if k.startswith("contacorrenteposicao"):
        return ("cc", "")
    if dashed and k.startswith(("fundodeinvestimento", "fundosdeinvestimento", "rendafixa", "previdencia", "rendavariavel", "contacorrente")):
        return ("ignore", "")
    if dashed and "cnpj" not in k and len(s) <= 80 and len(s.split(" - ")[0].split()) <= 4:
        segs = s.split(" - ")
        verb = key(segs[1])
        verb = verb if verb in ("posicao", "detalhamento", "movimentacao", "rentabilidade", "plano") else "?"
        return ("unknown", f"{key(segs[0])[:30]}/{verb}")  # never the rest: it can name an asset
    return None


def _is_furniture(text: str) -> bool:
    s = text.strip()
    k = key(s)
    return bool(
        EXTRATO_KEY in k
        or k.startswith(("periodode", "emitidoem", "sac0800", "ouvidoria", "informacoesdetalhadas"))
        or re.match(r"^(pagina)?\d+(/|de)\d+$", k)
        or k in ("oneinvestimentos|btgpactual", "btgpactual", "oneinvestimentos")
    )


def _vocab_word(w: str, tolerant: bool) -> bool:
    if w in HEADER_VOCAB:
        return True
    if not tolerant:
        return False
    if w in ("rs", "r"):  # 'R$' read by OCR
        return True
    return len(w) >= 4 and any(abs(len(v) - len(w)) <= 1 and _lev(w, v) <= 1 for v in HEADER_VOCAB if len(v) >= 4)


def _is_col_header(toks: list[Tok], tolerant: bool = False) -> bool:
    # the header's own dates ('Saldo Bruto R$ 31/08/26') and its footnote markers ('Saldo Líquido R$ 3') are
    # neutral; so, in OCR text, is a one- or two-letter speck ('ai', 'A') read off the table's rules
    words = [
        t
        for t in toks
        if t.k != "D"
        and not (t.k == "N" and re.fullmatch(r"\d", t.t))
        and not (tolerant and t.k == "L" and len(t.t) <= 2 and t.t not in HEADER_UPPER_OK and key(t.t) not in HEADER_VOCAB)
    ]
    if not words:
        return any(t.k == "D" for t in toks)  # the header's own dates ('31/08/26  31/08/26  30/09/26')
    strong = False
    good = bad = 0
    for t in words:
        if t.k != "L":
            return False
        w = re.sub(r"[^a-z$]", "", _strip_accents(t.t).lower())
        upper_ok = not (t.t.isupper() and len(t.t) >= 2 and t.t not in HEADER_UPPER_OK and not (tolerant and t.t in ("RS", "R$.")))
        if upper_ok and (not w or _vocab_word(w, tolerant)):
            good += 1
            strong = strong or len(w) >= 4
        elif not tolerant:
            return False
        else:
            bad += 1
    # OCR text: one garbled word among three or more header words still makes a header line
    return strong and (bad == 0 or (bad == 1 and good >= 3))


@dataclass
class Line:
    page: int
    no: int
    text: str
    toks: list[Tok]
    y: float | None = None  # OCR text: the line's vertical centre in font-size units (statement_ocr)

    @property
    def coord(self) -> str:
        return f"p{self.page}:l{self.no}"


@dataclass
class Block:
    kind: str
    arg: str
    heading_key: str
    lines: list[Line] = field(default_factory=list)
    header_ativo_x: int | None = None
    header: list[Line] = field(default_factory=list)


@dataclass
class Diagnostics:
    extractor: str = ""
    pages: int = 0
    sections: Counter = field(default_factory=Counter)
    unknown_sections: list[str] = field(default_factory=list)
    masked_lines_skipped: int = 0
    wrapped_prefix: int = 0
    wrapped_tail: int = 0
    wrap_ambiguous: int = 0
    layout_modes: Counter = field(default_factory=Counter)  # per table: top / bottom / centered / none
    fund_ref_date_differs: int = 0
    lines_after_total: int = 0
    emissor_table: str = "ausente"
    by_group: dict[str, tuple[int, Decimal]] = field(default_factory=dict)
    checks: list[tuple[str, bool, Decimal | None]] = field(default_factory=list)
    unread: list[str] = field(default_factory=list)
    # lines with money outside every table the reader knows (before any heading, or under an unknown
    # one): printed when a check fails, by page, line and shape, so an unread heading is findable
    unattributed: list[str] = field(default_factory=list)
    ocr: bool = False  # the labels were read by OCR (statement_ocr)
    ocr_stats: object = None  # statement_ocr.MergeStats, counts only
    ocr_checks: Counter = field(default_factory=Counter)
    ocr_specks: int = 0  # OCR mode: one- or two-character readings of a missing-value dash, ignored
    qty_price_checked: int = 0  # OCR mode: rows whose quantity x unit price gave their Saldo Bruto


def _has_money(toks: list[Tok]) -> bool:
    return any(t.k == "N" and "," in t.t for t in toks)


def _blocks(lines: list[Line], diag: Diagnostics) -> list[Block]:
    out: list[Block] = []
    cur: Block | None = None
    page_of_cur = None
    just_heading = False
    # A page's header and footer lines (the first four and the last three with text) may repeat the
    # holder; there a line with a mask token is furniture. Elsewhere it stays: an exclusive fund may
    # carry the holder's name, and its row must not vanish.
    by_page: dict[int, list[Line]] = {}
    for ln in lines:
        if ln.toks:
            by_page.setdefault(ln.page, []).append(ln)
    edge = {id(x) for pg in by_page.values() for x in pg[:4] + pg[-3:]}
    # OCR text: the page head above the 'Período' line is the logo and the holder header, which OCR reads as
    # stray words ('ne INVESTIMENTOS'); they must not join the table that runs on from the page before
    above_period: set[int] = set()
    if diag.ocr:
        for pg in by_page.values():
            cut = next((i for i, x in enumerate(pg[:6]) if key(x.text).startswith("periodo") or _PERIOD_OCR.search(_strip_accents(x.text))), None)
            if cut is not None:
                above_period.update(id(x) for x in pg[:cut] if not _has_money(x.toks))
    for ln in lines:
        if not ln.toks:
            continue
        if cur is not None and cur.kind == "ignore_page" and ln.page != page_of_cur:
            cur = None
        if id(ln) in edge and any(t in ln.text for t in MASK_TOKENS):
            diag.masked_lines_skipped += 1
            continue
        if diag.ocr and id(ln) in edge and ("containvestimento" in key(ln.text) or _approx_in(EXTRATO_KEY, key(ln.text))):
            # OCR reads the holder in each page header on its own, and one character off would escape the
            # mask: the header line with the account is furniture whether or not it was masked
            diag.masked_lines_skipped += 1
            continue
        if _is_furniture(ln.text) or id(ln) in above_period:
            continue
        if cur is not None and cur.kind == "ignore_page":
            continue  # the index and the Disclaimers pages: their section names are not tables
        h = heading_of(ln.text, tolerant=diag.ocr)
        if h is not None:
            hk = key(ln.text)
            just_heading = True
            if cur is not None and cur.heading_key == hk:
                continue  # the same heading repeated on a continuation page
            diag.sections[h[0]] += 1
            if h[0] == "unknown":
                diag.unknown_sections.append(h[1])
            cur = Block(h[0], h[1], hk)
            page_of_cur = ln.page
            out.append(cur)
            continue
        if just_heading and ln.toks[0].t[:1].islower() and all(t.k == "L" for t in ln.toks):
            just_heading = False
            continue  # the wrapped tail of a heading ('Portfólio de' / 'fundos')
        just_heading = False
        if cur is None or cur.kind in ("ignore", "ignore_page", "unknown"):
            if (cur is None or cur.kind == "unknown") and _has_money(ln.toks):
                where = "before any heading" if cur is None else "under an unknown heading"
                diag.unattributed.append(f"{ln.coord}: money {where} (shape {shape_of(ln.toks)})")
            continue
        if _is_col_header(ln.toks, tolerant=diag.ocr):
            for t in ln.toks:
                if key(t.t) == "ativo" and cur.header_ativo_x is None:
                    cur.header_ativo_x = t.x
            cur.header.append(ln)
            continue
        cur.lines.append(ln)
    return out


# ---------------------------------------------------------------------------
# Rows.
# ---------------------------------------------------------------------------


@dataclass
class Item:
    """A position read from a table, before it becomes a ``Position``."""

    group: str  # prev | rf | fundos | rv | cc
    name: str
    tipo: str
    codigo: str | None
    valor: Decimal
    quantidade: Decimal | None = None
    preco: Decimal | None = None
    vencimento: dt.date | None = None
    taxa: str | None = None
    emissor: str | None = None
    classe: str | None = None
    estrategia: str | None = None
    # OCR mode only: whether the code (or the fund's CNPJ) matched its shape or check digits, and what
    # the normalisation changed; None outside OCR or where there is no code
    codigo_conferido: bool | None = None
    ajustes: tuple[str, ...] = ()


class _Ctx:
    def __init__(self, diag: Diagnostics):
        self.diag = diag
        self.ocr = diag.ocr
        self.items: list[Item] = []
        self.unread: list[str] = []
        self.subtotals: list[tuple[str, Decimal, list[Item]]] = []  # check name, printed value, the rows it covers
        self.sumario: dict[str, Decimal] = {}
        self.sumario_total: Decimal | None = None
        self.rf_emissor_total: Decimal | None = None
        # How wrapped cells sit around their row, read once for the whole document (every table is
        # drawn by the same renderer): None in the evidence pass, then abaixo / acima / centralizado.
        self.mode: str | None = None
        self.mode_assumed = False
        self.ev_top = False  # text after a table's last row, or a row's Ativo ending in '-': cells wrap downwards
        self.ev_bottom = False  # text before a table's first row: cells wrap upwards

    def bad(self, ln: Line, reason: str) -> None:
        self.unread.append(f"{ln.coord}: {reason} (shape {shape_of(ln.toks)})")


def _qty_price_ok(ln: Line, q: Tok | None, p: Tok | None, b: Tok, ctx: "_Ctx") -> bool:
    """OCR mode: quantity x unit price must give Saldo Bruto, so a value taken from the wrong column is a row not read.

    The subtotals only check what was taken as Saldo Bruto; this checks the columns beside it. The tolerance
    covers a quota printed with its trailing digits cut (R$ 0,05, or 0,001% of the value when larger).
    """
    if q is None or p is None or q.k != "N" or p.k != "N":
        ctx.bad(ln, "quantity or unit price missing beside Saldo Bruto")
        return False
    try:
        qv, pv, bv = num(q.t), num(p.t), num(b.t)
    except (ValueError, InvalidOperation):
        ctx.bad(ln, "unreadable quantity, unit price or Saldo Bruto")
        return False
    if abs(qv * pv - bv) > max(Decimal("0.05"), bv * Decimal("0.00001")):
        ctx.bad(ln, "quantity x unit price is not Saldo Bruto: a value is not in its column")
        return False
    ctx.diag.qty_price_checked += 1
    return True


def _assign(entries: list[tuple[str, object]], prefer_tail: Callable[[object], bool], ctx: "_Ctx"):
    """Attach the text-only lines of a table to its data rows.

    ``entries`` is the table in order: ('d', row) or ('f', Line). Text before the first row is a
    prefix of it and text after the last row a tail of it, always. Text between two rows goes by the
    document's mode (``ctx.mode``): downwards (tails), upwards (prefixes) or vertically centred, where a
    row has as many lines above as below, so the gap is split in half (an odd middle line is ambiguous
    and goes by ``prefer_tail``). With no evidence for any mode, downwards is assumed and every line
    placed between rows is counted as ambiguous.
    Returns ({row id: (prefix lines, tail lines)}, orphan lines).
    """
    diag = ctx.diag
    rows = [i for i, (k, _) in enumerate(entries) if k == "d"]
    frags = [i for i, (k, _) in enumerate(entries) if k == "f"]
    if not rows:
        return {}, [entries[i][1] for i in frags]
    out = {id(entries[i][1]): ([], []) for i in rows}
    if not frags:
        diag.layout_modes["sem quebra"] += 1
        return out, []
    groups: list[list[Line]] = [[] for _ in range(len(rows) + 1)]
    r = 0
    for i, (k, obj) in enumerate(entries):
        if k == "d":
            r += 1
        else:
            groups[r].append(obj)
    if groups[0]:
        ctx.ev_bottom = True
    if groups[-1]:
        ctx.ev_top = True
    mode = ctx.mode or "abaixo"
    diag.layout_modes[mode + (" (assumido)" if ctx.mode_assumed else "")] += 1
    row_objs = [entries[i][1] for i in rows]
    if mode == "centralizado" and all(_y(obj) is not None for _, obj in entries):
        return _assign_by_y(entries, row_objs, prefer_tail, ctx), []
    # Centred cells: a row prints as many wrapped lines above its numbers as below, so the lines
    # before the first row say how many follow it, the rest of the next gap precedes the next row,
    # and so on down the table; the text after the last row must close the chain exactly.
    chain: dict[int, int] | None = None
    if mode == "centralizado":
        chain, k = {}, len(groups[0])
        for gi in range(1, len(groups) - 1):
            if k > len(groups[gi]):
                chain = None
                break
            chain[gi] = k
            k = len(groups[gi]) - k
        if chain is not None and len(groups[-1]) != k:
            chain = None
    for gi, g in enumerate(groups):
        if not g:
            continue
        prev_row = row_objs[gi - 1] if gi > 0 else None
        next_row = row_objs[gi] if gi < len(row_objs) else None
        if prev_row is None:
            tail, pre = [], g
        elif next_row is None:
            tail, pre = g, []
        elif mode == "abaixo":
            tail, pre = g, []
        elif mode == "acima":
            tail, pre = [], g
        elif chain is not None:
            tail, pre = list(g[: chain[gi]]), list(g[chain[gi] :])
        else:
            # the chain does not close: split the gap in half, and count every line as ambiguous
            h = len(g) // 2
            tail, pre = list(g[:h]), list(g[len(g) - h :])
            if len(g) % 2:
                mid = g[h]
                (tail.append(mid) if prefer_tail(prev_row) else pre.insert(0, mid))
            diag.wrap_ambiguous += len(g)
        if prev_row is not None and next_row is not None and ctx.mode_assumed:
            diag.wrap_ambiguous += len(g)
        if prev_row is not None:
            out[id(prev_row)][1].extend(tail)
        if next_row is not None:
            out[id(next_row)][0].extend(pre)
        diag.wrapped_tail += len(tail)
        diag.wrapped_prefix += len(pre)
    return out, []


def _y(obj) -> float | None:
    ln = obj.line if isinstance(obj, RfRow) else obj
    return ln.y


def _page(obj) -> int:
    return (obj.line if isinstance(obj, RfRow) else obj).page


Y_TIE = 0.15  # font-size units: a line this close to half-way between two rows is ambiguous


def _assign_by_y(entries, row_objs, prefer_tail, ctx: "_Ctx"):
    """Centred cells, OCR text: each text line goes to the row on its page whose numbers it sits closest to.

    OCR keeps the lines' vertical positions, so a wrapped Emissor or Ativo half a pitch above or below its
    row needs no counting of lines (a misread speck between rows would break the count). A line exactly
    half-way between two rows is ambiguous: it goes by ``prefer_tail`` and is counted.
    """
    diag = ctx.diag
    out = {id(r): ([], []) for r in row_objs}
    for k, obj in entries:
        if k != "f":
            continue
        cands = sorted((abs(_y(r) - obj.y), i) for i, r in enumerate(row_objs) if _page(r) == obj.page)
        if not cands:
            cands = [(0.0, 0 if obj.page < _page(row_objs[0]) else len(row_objs) - 1)]
        i = cands[0][1]
        if len(cands) > 1 and cands[1][0] - cands[0][0] <= Y_TIE:
            diag.wrap_ambiguous += 1
            a, b = sorted((cands[0][1], cands[1][1]))
            i = a if prefer_tail(row_objs[a]) else b
        r = row_objs[i]
        if obj.y < _y(r) or (obj.page < _page(r)):
            out[id(r)][0].append(obj)
            diag.wrapped_prefix += 1
        else:
            out[id(r)][1].append(obj)
            diag.wrapped_tail += 1
    return out


def _split_total(toks: list[Tok]) -> tuple[str, list[Tok]]:
    i = len(toks)
    while i > 0 and toks[i - 1].k in ("N", "-"):
        i -= 1
    return key(_gap_join(toks[:i])), toks[i:]


# --- Sumário ---------------------------------------------------------------


def _parse_sumario(b: Block, ctx: _Ctx) -> None:
    pending: list[str] = []
    for ln in b.lines:
        label, tail = _split_total(ln.toks)
        if not tail:
            if all(t.k == "L" for t in ln.toks):
                pending.append(_gap_join(ln.toks))  # a wrapped class label
            else:
                ctx.bad(ln, "Sumário line not read")
            continue
        label = key(" ".join(pending) + " " + _gap_join([t for t in ln.toks if t not in tail]))
        pending = []
        if len(tail) != 4 or tail[2].k not in ("N", "-"):
            ctx.bad(ln, "Sumário row without the four Saldo columns")
            continue
        end_bruto = Decimal("0") if tail[2].k == "-" else num(tail[2].t)
        if label == "total":
            ctx.sumario_total = end_bruto
        elif label:
            g = SUMARIO_GROUP.get(label, "?" + label[:40])
            ctx.sumario[g] = ctx.sumario.get(g, Decimal("0")) + end_bruto
        else:
            ctx.bad(ln, "Sumário row with no class")
    if pending:
        ctx.unread.append(f"Sumário: {len(pending)} text line(s) with no value (shape L)")


# --- Fundos ----------------------------------------------------------------

_FUND_TITLE = re.compile(r"^(?P<name>.*?)\s*-?\s*(?:Classe\s+)?CNPJ\s*:?\s*(?P<cnpj>\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})", re.I)
# OCR text: the CNPJ's 14 digits with a dot dropped or read as a space ('11.222 333/0001-81')
_FUND_TITLE_OCR = re.compile(
    r"^(?P<name>.*?)\s*-?\s*(?:Classe\s+)?CNPJ\s*:?\s*(?P<cnpj>\d{2}[.,\s]?\d{3}[.,\s]?\d{3}\s?/\s?\d{4}\s?-?\s?\d{2})(?!\d)", re.I
)
COL_SLACK = 2  # character columns: a right-aligned number's end against its column's


def _fund_tipo(name: str) -> str:
    up = _strip_accents(name).upper()
    if "FIDC" in up or re.search(r"\bDC\s*$", up):
        return "FIDC"
    if re.search(r"\bFII\b", up):
        return "FII"
    return "fundo"


def _is_fund_total(t: list[Tok]) -> bool:
    k0, tail0 = _split_total(t)
    return k0.startswith("totalem") or (k0 == "total" and bool(tail0))


def _fund_values(t: list[Tok], bruto_ref: Tok | None, ctx: _Ctx) -> tuple[Tok, Tok, Tok] | str:
    """(quantidade, cotação, Saldo Bruto) of a fund data line, or the reason it cannot be read.

    Text layer: the nine columns, a missing value printed '-'. OCR mode: the missing-value dash is an
    outline the text layer does not carry (and OCR reads it or not), so the columns are found by
    position: Saldo Bruto is the number right-aligned with the 'Total em fundos' value, quantity and
    quota the two numbers before it, after the date and the invested value. Nothing is counted.
    """
    if not ctx.ocr:
        if len(t) != 9 or any(x.k not in ("N", "-") for x in t[1:]) or t[4].k != "N":
            return "fund data line not in the nine columns"
        return t[2], t[3], t[4]
    if bruto_ref is None:
        return "fund data line in a table with no 'Total em fundos' value to align the columns"
    money = [i for i, x in enumerate(t) if x.k == "N" and "," in x.t]
    bi = next((i for i in money if abs(t[i].end - bruto_ref.end) <= COL_SLACK), None)
    if bi is None:
        bi = next((i for i in money if _in_col(t[i], bruto_ref)), None)
    # date, the invested value (a number, a dash, or a dash OCR did not see), quantity, quota, Saldo Bruto
    if bi not in (3, 4) or t[bi - 1].k != "N" or t[bi - 2].k != "N" or (bi == 4 and t[1].k not in ("N", "-")):
        return "fund data line: no Saldo Bruto under the total's column, after date, invested value, quantity and quota"
    after = t[bi + 1 :]
    if any(x.k not in ("N", "-") and not _ocr_speck(x) for x in after):
        return "fund data line: text after Saldo Bruto"
    ctx.diag.ocr_specks += sum(1 for x in after if x.k not in ("N", "-"))
    return t[bi - 2], t[bi - 1], t[bi]


RATE_WORDS = {"+", "do", "de", "aa", "aa.", "a.", "%"}


def _ocr_speck(x: Tok) -> bool:
    """OCR text only: a one- or two-character reading of a missing-value dash or a rule ('o', 'a', 'ã', 'x').

    Never a digit, nor a piece of a rate ('+', 'do').
    """
    return x.k == "L" and len(x.t) <= 2 and not any(c.isdigit() for c in x.t) and x.t.lower() not in RATE_WORDS


def _fund_title(text: str, tolerant: bool) -> tuple[str, str | None]:
    """(name, CNPJ) of a fund title line. OCR mode reads a CNPJ whose dots OCR dropped or split ('11.222333/0001-81')."""
    m = _FUND_TITLE.match(text)
    if m:
        return m.group("name").strip(" -"), m.group("cnpj")
    if tolerant:
        m = _FUND_TITLE_OCR.match(text)
        if m:
            d = re.sub(r"\D", "", m.group("cnpj"))
            return m.group("name").strip(" -"), ocr._fmt_cnpj(d)
    found = _CNPJ_ANY.search(text)
    return text.strip(), (found.group(0) if found else None)


def _parse_funds(b: Block, ctx: _Ctx, period_end: dt.date) -> None:
    title: list[Line] = []
    rows: list[Item] = []
    done = False
    tot = next((ln for ln in b.lines if _is_fund_total(ln.toks)), None)
    tot_nums = [x for x in tot.toks if x.k == "N"] if tot is not None else []
    bruto_ref = tot_nums[0] if tot_nums else None
    for ln in b.lines:
        t = ln.toks
        if _is_fund_total(t):
            nums = [x for x in t if x.k == "N"]
            if not nums:
                ctx.bad(ln, "'Total em fundos' with no value")
                continue
            ctx.subtotals.append(("folhas x 'Total em fundos'", num(nums[0].t), list(rows)))
            done = True
            continue
        if t[0].k == "D":
            if done:
                ctx.bad(ln, "fund row after 'Total em fundos'")
                continue
            vals = _fund_values(t, bruto_ref, ctx)
            if isinstance(vals, str):
                ctx.bad(ln, vals)
                title = []
                continue
            q_tok, p_tok, b_tok = vals
            if not title:
                ctx.bad(ln, "fund data line with no title line")
                continue
            if ctx.ocr and not _qty_price_ok(ln, q_tok, p_tok, b_tok, ctx):
                title = []
                continue
            text = " ".join(_gap_join(x.toks) for x in title)
            name, cnpj = _fund_title(text, ctx.ocr)
            if len(title) > 1:
                ctx.diag.wrapped_prefix += len(title) - 1
            title = []
            if date_of(t[0].t) != period_end:
                ctx.diag.fund_ref_date_differs += 1
            chk = ocr.check_cnpj(cnpj) if ctx.ocr else None
            if chk is not None:
                cnpj = chk.value
            it = Item(
                group="fundos",
                name=name,
                tipo=_fund_tipo(name),
                codigo=cnpj,
                codigo_conferido=chk.conferido if chk else None,
                ajustes=chk.ajustes if chk else (),
                valor=num(b_tok.t),
                quantidade=opt_num(q_tok),
                preco=opt_num(p_tok),
                classe="Fundo de Investimento",
                estrategia="Portfólio de fundos",
            )
            rows.append(it)
            ctx.items.append(it)
            continue
        if done:
            ctx.diag.lines_after_total += 1
            continue
        title.append(ln)
    if title:
        ctx.unread.append(f"{title[0].coord}: fund title with no data line (shape L x{len(title)})")


# --- Renda fixa --------------------------------------------------------------


@dataclass
class RfRow:
    line: Line
    lead: list[Tok]  # tokens before the Emissão date
    date_x: int
    venc: dt.date | None
    taxa_toks: list[Tok]
    taxa_lo: int  # where the Taxa column can start: just after 'Data inicial de liquidez'
    qty_x: int
    qty: Decimal | None
    preco: Decimal | None
    bruto: Decimal
    ativo_tok: Tok | None = None


def _rf_data(ln: Line) -> RfRow | None | str:
    """An RfRow for a data line, None for a line that is not one, or a reason when it is a broken one."""
    t = ln.toks
    di = next((i for i, x in enumerate(t) if x.k == "D"), None)
    if di is None:
        return None
    if len(t) < di + 2 + 6 or any(x.k not in ("N", "-") for x in t[-6:]):
        return "renda fixa line with a date but not the table's columns"
    if t[-4].k != "N":
        return "renda fixa row with no Saldo Bruto"
    if t[di + 1].k not in ("D", "-"):
        return "renda fixa row with no Vencimento"
    rest = t[di + 2 : len(t) - 6]
    taxa: list[Tok] | None = None
    taxa_lo = 0
    # liquidez (one word or more), carência (number or -), data inicial (date or -), then the rate
    for j in range(1, len(rest) - 1):
        if rest[j].k in ("N", "-") and rest[j + 1].k in ("D", "-"):
            taxa = rest[j + 2 :]
            taxa_lo = rest[j + 1].end + 1
            break
    if taxa is None:
        return "renda fixa row: liquidez / carência / data inicial not found"
    try:
        venc = date_of(t[di + 1].t) if t[di + 1].k == "D" else None
        qty = opt_num(t[-6])
        preco = opt_num(t[-5])
        bruto = num(t[-4].t)
    except (ValueError, InvalidOperation):
        return "renda fixa row with an unreadable number or date"
    return RfRow(ln, t[:di], t[di].x, venc, taxa, taxa_lo, t[-6].x, qty, preco, bruto)


def _is_subtotal(t: list[Tok]) -> bool:
    label, tail = _split_total(t)
    return bool(tail) and len(tail) >= 3 and label in ("", "total") and tail[0].k == "N" and "," in tail[0].t


def _header_x(b: Block, pattern: str) -> int | None:
    """The column where a header phrase ('taxa', 'data inicial', which OCR may print as 'Datainicial') starts, or None."""
    rx = re.compile(pattern, re.I)
    xs = [m.start() for ln in b.header for m in [rx.search(_strip_accents(ln.text))] if m]
    return min(xs) if xs else None


def _in_col(tok: Tok, ref: Tok) -> bool:
    """A number in the column of ``ref``: right-aligned with it (as printed) or, failing that, left-aligned."""
    return abs(tok.end - ref.end) <= COL_SLACK or abs(tok.x - ref.x) <= COL_SLACK


def _parse_rf_ocr(b: Block, ctx: _Ctx) -> None:
    """A renda fixa table in OCR text: numbers placed by column, wrapped cells by their vertical position.

    The text layer holds the dates and numbers, never the missing-value dashes (outlines, which OCR reads
    or not). So a row is the line with the Emissão and Vencimento dates; Saldo Bruto is its number
    right-aligned with the subtotal's first value, Quantidade and Preço the two numbers before it, and
    quantity x price must give Saldo Bruto. Liquidez, carência and data inicial are not used; the rate is
    the text between the header's 'Data inicial' and 'Taxa' columns and Quantidade. Emissor and Ativo are
    left of the Emissão date, split at the header's 'Ativo'.
    """
    kind = b.arg
    entries: list[tuple[str, object]] = []
    sub: Line | None = None
    for ln in b.lines:
        t = ln.toks
        if sub is not None:
            if any(x.k in ("N", "D") for x in t):
                ctx.bad(ln, "renda fixa line after the table's subtotal")
            else:
                ctx.diag.lines_after_total += 1
            continue
        di = next((i for i, x in enumerate(t) if x.k == "D"), None)
        if di is not None:
            if di + 1 >= len(t) or t[di + 1].k != "D":
                ctx.bad(ln, "renda fixa row with no Vencimento date after Emissão")
            else:
                entries.append(("d", ln))
            continue
        if any(x.k == "N" and "," in x.t for x in t) and all(x.k in ("N", "-") or _ocr_speck(x) for x in t):
            sub = ln
            continue
        if any(x.k == "C" or (x.k == "N" and "," in x.t) for x in t):
            ctx.bad(ln, "renda fixa line with numbers that is neither a row nor the subtotal")
            continue  # an integer stays: a code may read as digits only (a CRI's 'I' as '1'), or end in a wrapped '0'
        entries.append(("f", ln))
    if sub is None:
        for k, obj in entries:
            if k == "d":
                ctx.bad(obj, "renda fixa row in a table with no subtotal to align the columns")
        return
    sub_nums = [x for x in sub.toks if x.k == "N"]
    ativo_x = b.header_ativo_x
    taxa_x, inicial_x = _header_x(b, r"\btaxa"), _header_x(b, r"data\s*inicial")
    rows: list[RfRow] = []
    for k, obj in list(entries):
        if k != "d":
            continue
        ln: Line = obj  # type: ignore[assignment]
        t = ln.toks
        di = next(i for i, x in enumerate(t) if x.k == "D")
        money = [i for i, x in enumerate(t) if i > di + 1 and x.k == "N" and "," in x.t]
        bi = next((i for i in money if abs(t[i].end - sub_nums[0].end) <= COL_SLACK), None)
        if bi is None:
            bi = next((i for i in money if _in_col(t[i], sub_nums[0])), None)
        reason = None
        if bi is None or bi - 2 <= di + 1:
            reason = "renda fixa row: no Saldo Bruto under the subtotal's column, after Quantidade and Preço"
        elif any(x.k not in ("N", "-") and not _ocr_speck(x) for x in t[bi + 1 :]):
            reason = "renda fixa row: text after Saldo Bruto"
        if reason:
            ctx.bad(ln, reason)
            entries.remove((k, obj))
            continue
        q, pr, br = t[bi - 2], t[bi - 1], t[bi]
        if not _qty_price_ok(ln, q, pr, br, ctx):
            entries.remove((k, obj))
            continue
        ctx.diag.ocr_specks += sum(1 for x in t[bi + 1 :] if x.k == "L")
        # Between Vencimento and Quantidade: Liquidez (a word), carência and data inicial (a number, a date or
        # a dash OCR may read as a speck), then the rate. The rate starts after the row's own Liquidez value and
        # what follows it; with no Liquidez value read, 40% of the way from the 'Data inicial' header to the
        # 'Taxa' header (the rate prints a little left of its centred header).
        if taxa_x is not None and inicial_x is not None and inicial_x < taxa_x:
            header_lo = inicial_x + (taxa_x - inicial_x) * 2 // 5
        elif taxa_x is not None:
            header_lo = taxa_x - 8
        else:
            header_lo = q.x  # no header: no rate is read
        middle = t[di + 2 : bi - 2]
        j = 1 if middle and middle[0].k == "L" and not _ocr_speck(middle[0]) and middle[0].x < header_lo else 0
        while j < len(middle) and (middle[j].k in ("N", "D", "-") or _ocr_speck(middle[j])):
            j += 1
        taxa = middle[j:]
        taxa_lo = taxa[0].x if taxa else (middle[j - 1].end + 1 if j else header_lo)
        if any(x.k in ("D", "C") or (x.k == "N" and "," in x.t and not x.t.endswith("%")) for x in taxa):
            ctx.bad(ln, "renda fixa row: a date or value where the rate is printed")
            entries.remove((k, obj))
            continue
        try:
            venc = date_of(t[di + 1].t)
        except ValueError:
            ctx.bad(ln, "renda fixa row with an unreadable Vencimento")
            entries.remove((k, obj))
            continue
        r = RfRow(ln, t[:di], t[di].x, venc, taxa, taxa_lo, q.x, num(q.t), num(pr.t), num(br.t))
        rows.append(r)
        entries[entries.index((k, obj))] = ("d", r)

    def is_ativo(tk: Tok) -> bool:
        if ativo_x is not None:
            return tk.x >= ativo_x - COL_SLACK
        return _ATIVO_LIKE.match(tk.t) is not None and tk.x > 0

    for r in rows:
        if r.lead and is_ativo(r.lead[-1]):
            r.ativo_tok = r.lead[-1]
    if any(r.ativo_tok is not None and r.ativo_tok.t.endswith("-") for r in rows):
        ctx.ev_top = True

    def prefer_tail(row: RfRow) -> bool:
        return bool(row.ativo_tok and row.ativo_tok.t.endswith("-"))

    placed, orphans = _assign(entries, prefer_tail, ctx) if rows else ({}, [o for k, o in entries if k == "f"])
    for ln in orphans:
        ctx.bad(ln, "text line not attached to any renda fixa row")
    items: list[Item] = []
    for r in rows:
        pre, post = placed[id(r)]
        emissor_parts: list[str] = []
        ativo_parts: list[str] = []
        taxa_parts: list[str] = []
        ok = True

        def take(toks: list[Tok], ln: Line) -> bool:
            em, at, tx = [], [], []
            for tk in toks:
                if tk.x < r.date_x - 1:
                    (at if is_ativo(tk) else em).append(tk)
                elif _ocr_speck(tk):
                    ctx.diag.ocr_specks += 1  # a dash or a rule read as a letter: not read
                elif r.taxa_lo - COL_SLACK <= tk.x and tk.end <= r.qty_x - 1:
                    tx.append(tk)
                elif tk.k == "L" and tk.end <= r.taxa_lo:
                    ctx.diag.ocr_specks += 1  # the Liquidez text, wrapped: not read
                else:
                    ctx.bad(ln, "wrapped text outside the Emissor, Ativo and Taxa columns")
                    return False
            if em:
                emissor_parts.append(_gap_join(em))
            if at:
                ativo_parts.append("".join(x.t for x in at))
            if tx:
                taxa_parts.append(_gap_join(tx))
            return True

        for ln in pre:
            ok = take(ln.toks, ln) and ok
        lead_em = [x for x in r.lead if x is not r.ativo_tok]
        if lead_em:
            emissor_parts.append(_gap_join(lead_em))
        if r.ativo_tok is not None:
            ativo_parts.append(r.ativo_tok.t)
        if r.taxa_toks:
            taxa_parts.append(_gap_join(r.taxa_toks))
        for ln in post:
            ok = take(ln.toks, ln) and ok
        if not ok:
            continue
        item = _rf_item(r, kind, emissor_parts, ativo_parts, taxa_parts, ctx)
        if item is not None:
            items.append(item)
    ctx.subtotals.append((f"folhas x subtotal Renda fixa {kind or '?'}", num(sub_nums[0].t), items))


def _rf_item(r: RfRow, kind: str, emissor_parts: list[str], ativo_parts: list[str], taxa_parts: list[str], ctx: _Ctx) -> Item | None:
    ativo = "".join(ativo_parts).upper()
    emissor = sp.join_fragments(emissor_parts) or None
    if not ativo or ativo.endswith("-"):
        ctx.bad(r.line, "renda fixa row with no complete Ativo code")
        return None
    chk = None
    if ctx.ocr:
        ativo, chk = ocr.normalize_ativo("".join(ativo_parts))
    tipo, codigo = _rf_type(ativo, emissor, kind, r.venc)
    if ctx.ocr and chk is None:
        chk = ocr.FieldCheck(codigo or "", tipo == "tesouro" and codigo is not None and ativo.replace("-", "") in TESOURO_ATIVO)
    taxa = " ".join(taxa_parts) or None
    name = f"{emissor} - {ativo}" if emissor else ativo
    it = Item(
        group="rf",
        name=name,
        tipo=tipo,
        codigo=codigo,
        valor=r.bruto,
        quantidade=r.qty,
        preco=r.preco,
        vencimento=r.venc,
        taxa=taxa,
        emissor=emissor,
        classe="Renda Fixa",
        estrategia=kind or None,
        codigo_conferido=chk.conferido if chk else None,
        ajustes=chk.ajustes if chk else (),
    )
    ctx.items.append(it)
    return it


def _parse_rf(b: Block, ctx: _Ctx) -> None:
    if ctx.ocr:
        _parse_rf_ocr(b, ctx)
        return
    kind = b.arg
    entries: list[tuple[str, object]] = []
    subtotal: Decimal | None = None
    for ln in b.lines:
        if subtotal is not None:
            if any(x.k in ("N", "D") for x in ln.toks):
                ctx.bad(ln, "renda fixa line after the table's subtotal")
            else:
                ctx.diag.lines_after_total += 1
            continue
        if _is_subtotal(ln.toks):
            subtotal = num(_split_total(ln.toks)[1][0].t)
            continue
        r = _rf_data(ln)
        if isinstance(r, str):
            ctx.bad(ln, r)
        elif r is not None:
            entries.append(("d", r))
        else:
            entries.append(("f", ln))  # wrapped text; a token outside the text columns is refused below
    rows = [e[1] for e in entries if e[0] == "d"]
    # the Ativo column: from rows whose last lead token sits two or more spaces after the Emissor
    xs = []
    for r in rows:
        if len(r.lead) >= 2 and r.lead[-1].x - r.lead[-2].end >= 2 and _ATIVO_LIKE.match(r.lead[-1].t):
            xs.append(r.lead[-1].x)
        elif len(r.lead) == 1 and r.lead[0].x > 0 and _ATIVO_LIKE.match(r.lead[0].t):
            xs.append(r.lead[0].x)
    ativo_x = min(xs) if xs else b.header_ativo_x

    def is_ativo(tk: Tok, row: RfRow, alone: bool) -> bool:
        if ativo_x is not None:
            return tk.x >= ativo_x - 2
        return _ATIVO_LIKE.match(tk.t) is not None and (not alone or tk.x > 0)

    for r in rows:
        if r.lead:
            last = r.lead[-1]
            if is_ativo(last, r, len(r.lead) == 1):
                r.ativo_tok = last

    if any(r.ativo_tok is not None and r.ativo_tok.t.endswith("-") for r in rows):
        ctx.ev_top = True

    def prefer_tail(row: RfRow) -> bool:
        return bool(row.ativo_tok and row.ativo_tok.t.endswith("-"))

    placed, orphans = _assign(entries, prefer_tail, ctx)
    for ln in orphans:
        ctx.bad(ln, "text line not attached to any renda fixa row")
    items: list[Item] = []
    for r in rows:
        pre, post = placed[id(r)]
        emissor_parts: list[str] = []
        ativo_parts: list[str] = []
        taxa_parts: list[str] = []
        ok = True

        def take(toks: list[Tok], ln: Line) -> bool:
            em, at, tx = [], [], []
            for tk in toks:
                if tk.x < r.date_x - 1:
                    (at if is_ativo(tk, r, False) else em).append(tk)
                elif r.taxa_lo - 1 <= tk.x and tk.end <= r.qty_x - 1:
                    tx.append(tk)
                else:
                    ctx.bad(ln, "wrapped text outside the Emissor, Ativo and Taxa columns")
                    return False
            if em:
                emissor_parts.append(_gap_join(em))
            if at:
                ativo_parts.append("".join(x.t for x in at))
            if tx:
                taxa_parts.append(_gap_join(tx))
            return True

        for ln in pre:
            ok = take(ln.toks, ln) and ok
        lead_em = [x for x in r.lead if x is not r.ativo_tok]
        if lead_em:
            emissor_parts.append(_gap_join(lead_em))
        if r.ativo_tok is not None:
            ativo_parts.append(r.ativo_tok.t)
        data_taxa = _gap_join(r.taxa_toks)
        if data_taxa and data_taxa not in _DASHES:
            taxa_parts.append(data_taxa)
        for ln in post:
            ok = take(ln.toks, ln) and ok
        if not ok:
            continue
        it = _rf_item(r, kind, emissor_parts, ativo_parts, taxa_parts, ctx)
        if it is not None:
            items.append(it)
    if subtotal is None:
        if rows:
            ctx.unread.append(f"renda fixa {kind or '?'}: table with no subtotal row (shape -)")
    else:
        ctx.subtotals.append((f"folhas x subtotal Renda fixa {kind or '?'}", subtotal, items))


def _rf_type(ativo: str, emissor: str | None, kind: str, venc: dt.date | None) -> tuple[str, str | None]:
    akey = ativo.replace("-", "")
    if akey in TESOURO_ATIVO or key(emissor or "").startswith("bacen"):
        title = TESOURO_ATIVO.get(akey) or TESOURO_ATIVO.get(key(kind).upper())
        if title is None:
            return "tesouro", None
        return "tesouro", f"{title} {venc.isoformat()}" if venc else title
    m = _ATIVO_PREFIX.match(ativo)
    if m and m.group(2):
        return REGISTRY_TIPO.get(m.group(1), "outro"), m.group(2)
    return KIND_TIPO.get(key(kind), "outro"), ativo


# --- Renda fixa por emissor (extra check) ------------------------------------


def _parse_rf_emissor(b: Block, ctx: _Ctx) -> None:
    total = None
    rows = Decimal("0")
    n = 0
    bad = 0
    for ln in b.lines:
        label, tail = _split_total(ln.toks)
        if not tail:
            if all(t.k == "L" for t in ln.toks):
                continue  # a wrapped emissor name
            bad += 1
            continue
        if len(tail) != 1 or tail[0].k != "N":
            bad += 1
            continue
        if label == "total":
            total = num(tail[0].t)
        else:
            rows += num(tail[0].t)
            n += 1
    if bad or not n:
        ctx.diag.emissor_table = f"não conferida ({bad} linhas fora do formato, {n} emissores)"
        return
    ctx.rf_emissor_total = total if total is not None else rows
    ctx.diag.emissor_table = f"{n} emissores"


# --- Previdência -------------------------------------------------------------


def _parse_prev(b: Block, ctx: _Ctx, plan_no: int) -> None:
    wrapper = f"Previdência {b.arg}" if b.arg else "Previdência"
    entries: list[tuple[str, object]] = []
    total: Decimal | None = None
    for ln in b.lines:
        t = ln.toks
        if total is not None:
            if any(x.k in ("N", "D", "C") for x in t):
                ctx.bad(ln, "previdência line after the plan's Total")
            else:
                ctx.diag.lines_after_total += 1
            continue
        label, tail = _split_total(t)
        if (label == "total" or label.startswith("totalem")) and tail and tail[0].k == "N":
            total = num(tail[0].t)
            continue
        if len(t) >= 5 and [x.k for x in t[-5:]] in (list("CDNNN"), list("CD-NN"), list("CDN-N")):
            entries.append(("d", ln))
        elif any(x.k != "L" for x in t):
            ctx.bad(ln, "previdência line not in the table's columns")
        else:
            entries.append(("f", ln))
    placed, orphans = _assign(entries, lambda row: False, ctx)
    for ln in orphans:
        ctx.bad(ln, "text line not attached to any previdência row")
    items: list[Item] = []
    for k, obj in entries:
        if k != "d":
            continue
        ln: Line = obj  # type: ignore[assignment]
        t = ln.toks
        cnpj_tok = t[-5]
        pre, post = placed[id(ln)]
        parts: list[str] = []
        ok = True
        for fl in pre + [None] + post:
            if fl is None:
                if t[:-5]:
                    parts.append(_gap_join(t[:-5]))
                continue
            if any(x.x >= cnpj_tok.x - 1 for x in fl.toks):
                ctx.bad(fl, "wrapped text outside the Fundo column")
                ok = False
                continue
            parts.append(_gap_join(fl.toks))
        if not ok:
            continue
        name = sp.join_fragments(parts)
        if not name:
            ctx.bad(ln, "previdência row with no fund name")
            continue
        if ctx.ocr and not _qty_price_ok(ln, t[-3], t[-2], t[-1], ctx):
            continue
        chk = ocr.check_cnpj(cnpj_tok.t) if ctx.ocr else None
        it = Item(
            group="prev",
            name=name,
            tipo="fundo",
            codigo=chk.value if chk else cnpj_tok.t,
            codigo_conferido=chk.conferido if chk else None,
            ajustes=chk.ajustes if chk else (),
            valor=num(t[-1].t),
            quantidade=opt_num(t[-3]),
            preco=opt_num(t[-2]),
            classe="Previdência",
            estrategia=wrapper,
        )
        items.append(it)
        ctx.items.append(it)
    if total is None:
        if items:
            ctx.unread.append(f"previdência plano {plan_no}: table with no Total row (shape -)")
    else:
        ctx.subtotals.append((f"folhas x Total da previdência, plano {plan_no} ({b.arg or '?'})", total, items))


# --- Renda variável ----------------------------------------------------------


def _parse_rv(b: Block, ctx: _Ctx) -> None:
    kind = b.arg
    tipo = RV_KIND_TIPO.get(key(kind).replace("'", ""), "outro")
    entries: list[tuple[str, object]] = []
    total: Decimal | None = None
    for ln in b.lines:
        t = ln.toks
        if total is not None:
            if any(x.k in ("N", "D") for x in t):
                ctx.bad(ln, "renda variável line after the table's Total")
            else:
                ctx.diag.lines_after_total += 1
            continue
        label, tail = _split_total(t)
        if (label == "total" or label.startswith("totalem")) and tail and tail[-1].k == "N":
            total = num(tail[-1].t)
            continue
        if ctx.ocr and t and t[0].k == "L":
            # OCR mixes the case of look-alike letters ('BOvZ11'); a B3 code is upper case
            t = [Tok(t[0].x, t[0].t.upper(), "L")] + t[1:]
            ln = Line(ln.page, ln.no, ln.text, t)
        if len(t) >= 5 and _TICKER.match(t[0].t) and all(x.k in ("N", "-") for x in t[-4:]) and t[-1].k == "N" and t[-4].k == "N":
            entries.append(("d", ln))
        elif any(x.k != "L" for x in t):
            ctx.bad(ln, "renda variável line not in the table's columns")
        else:
            entries.append(("f", ln))
    placed, orphans = _assign(entries, lambda row: False, ctx)
    for ln in orphans:
        ctx.bad(ln, "text line not attached to any renda variável row")
    items: list[Item] = []
    for k, obj in entries:
        if k != "d":
            continue
        ln: Line = obj  # type: ignore[assignment]
        t = ln.toks
        pre, post = placed[id(ln)]
        name_lo, name_hi = t[0].end + 1, t[-4].x - 1
        parts: list[str] = []
        ok = True
        for fl in pre + [None] + post:
            if fl is None:
                if t[1:-4]:
                    parts.append(_gap_join(t[1:-4]))
                continue
            if any(not (name_lo <= x.x < name_hi) for x in fl.toks):
                ctx.bad(fl, "wrapped text outside the Ativo column")
                ok = False
                continue
            parts.append(_gap_join(fl.toks))
        if not ok:
            continue
        name = sp.join_fragments(parts) or t[0].t
        if ctx.ocr and not _qty_price_ok(ln, t[-4], t[-3], t[-1], ctx):
            continue
        chk = ocr.normalize_ticker(t[0].t) if ctx.ocr else None
        try:
            it = Item(
                group="rv",
                name=name,
                tipo=tipo,
                codigo=chk.value if chk else t[0].t,
                codigo_conferido=chk.conferido if chk else None,
                ajustes=chk.ajustes if chk else (),
                valor=num(t[-1].t),
                quantidade=opt_num(t[-4]),
                preco=opt_num(t[-3]),
                classe="Renda Variável",
                estrategia=kind or None,
            )
        except (ValueError, InvalidOperation):
            ctx.bad(ln, "renda variável row with an unreadable number")
            continue
        items.append(it)
        ctx.items.append(it)
    if total is None:
        if items:
            ctx.unread.append(f"renda variável {kind or '?'}: table with no Total row (shape -)")
    else:
        ctx.subtotals.append((f"folhas x Total Renda variável {kind or '?'}", total, items))


# --- Conta corrente ----------------------------------------------------------


def _parse_cc(b: Block, ctx: _Ctx) -> None:
    for ln in b.lines:
        t = ln.toks
        if len(t) == 2 and t[0].k == "D" and t[1].k == "N":
            v = num(t[1].t)
            if v != 0:
                ctx.items.append(Item(group="cc", name="Conta corrente", tipo="caixa", codigo=None, valor=v, classe="Conta Corrente", estrategia="Conta corrente"))
        elif all(x.k == "L" for x in t):
            ctx.diag.lines_after_total += 1
        else:
            ctx.bad(ln, "conta corrente line not 'Data  Valor'")


# ---------------------------------------------------------------------------
# The parser.
# ---------------------------------------------------------------------------


def _period_end(texts: list[str], tolerant: bool = False) -> dt.date:
    for text in texts:
        m = _PERIOD.search(text) or (_PERIOD_OCR.search(_strip_accents(text)) if tolerant else None)
        if m:
            try:
                return date_of(m.group(2))
            except ValueError:
                continue
    raise StatementFormatError("no period 'Período de DD/MM/YY a DD/MM/YY' found: the position date cannot be set")


def parse_extrato_pages(
    pages: list[str], extractor: str = "text", ocr_mode: bool = False, ocr_stats=None, line_ys: list[list[float]] | None = None
) -> tuple[Statement, Diagnostics]:
    """Read the extrato's pages (layout text). ``ocr_mode``: the labels came from OCR (``statement_ocr``):
    headings are matched with OCR tolerance, and codes, CNPJs and rates are normalised and flagged per position.
    ``line_ys`` (OCR only): per page, each line's vertical centre in font-size units, so a wrapped cell of a
    vertically centred row goes to the row it sits closest to.
    """
    diag = Diagnostics(extractor=extractor, pages=len(pages), ocr=ocr_mode, ocr_stats=ocr_stats)
    if not pages or not any(p.strip() for p in pages):
        raise StatementFormatError("the PDF has no text")
    if not is_extrato(pages, tolerant=ocr_mode):
        raise StatementFormatError("not a BTG 'Extrato da Conta Investimento' (no such heading on the first page)")
    scrub, notes = _cover_scrubber(pages[0], tolerant=ocr_mode)
    broker = "BTG Pactual" if "btgpactual" in key(pages[0]) else None
    period_end = _period_end([ln for pg in pages for ln in pg.splitlines()], tolerant=ocr_mode)
    rest = pages[1:]
    del pages
    ys = line_ys[1:] if line_ys else None

    def y_of(pi: int, li: int) -> float | None:
        return ys[pi][li] if ys is not None and pi < len(ys) and li < len(ys[pi]) else None

    lines = [
        Line(pi + 2, li + 1, s, tokens(s), y_of(pi, li))
        for pi, pg in enumerate(rest)
        for li, s in enumerate(scrub(raw) for raw in pg.splitlines())
    ]
    del rest
    blocks = _blocks(lines, diag)
    probe = _Ctx(Diagnostics(ocr=ocr_mode))
    _run_blocks(blocks, probe, period_end)
    ctx = _Ctx(diag)
    if probe.ev_top and probe.ev_bottom:
        ctx.mode = "centralizado"
    elif probe.ev_bottom:
        ctx.mode = "acima"
    else:
        ctx.mode = "abaixo"
        ctx.mode_assumed = not probe.ev_top
    _run_blocks(blocks, ctx, period_end)
    return _finish(ctx, diag, scrub, notes, broker, period_end)


def _run_blocks(blocks: list[Block], ctx: "_Ctx", period_end: dt.date) -> None:
    plan = 0
    for b in blocks:
        if b.kind == "sumario":
            _parse_sumario(b, ctx)
        elif b.kind == "funds":
            _parse_funds(b, ctx, period_end)
        elif b.kind == "rf":
            _parse_rf(b, ctx)
        elif b.kind == "rf_emissor":
            _parse_rf_emissor(b, ctx)
        elif b.kind == "prev":
            plan += 1
            _parse_prev(b, ctx, plan)
        elif b.kind == "rv":
            _parse_rv(b, ctx)
        elif b.kind == "cc":
            _parse_cc(b, ctx)


def _finish(ctx: "_Ctx", diag: Diagnostics, scrub, notes: list[str], broker, period_end: dt.date):
    if ctx.sumario_total is None:
        raise StatementFormatError("no 'Sumário - Distribuição' Total row: the statement's own total is unknown, nothing was reconciled")
    if not ctx.items and not ctx.unread:
        raise StatementFormatError("no position table found ('... - Posição'): the layout is not one this reader knows")

    positions: list[Position] = []
    for it in ctx.items:
        n = len(positions) + 1
        taxa, taxa_ok, ajustes = it.taxa, None, it.ajustes
        if diag.ocr:
            tchk = ocr.normalize_taxa(it.taxa)
            if tchk is not None:
                taxa, taxa_ok, ajustes = tchk.value, tchk.conferido, ajustes + tchk.ajustes
            if it.codigo is not None:
                diag.ocr_checks["código conferido" if it.codigo_conferido else "código não conferido"] += 1
            if taxa_ok is not None:
                diag.ocr_checks["taxa conferida" if taxa_ok else "taxa não conferida"] += 1
            if ajustes:
                diag.ocr_checks["posições com ajuste de OCR"] += 1
        positions.append(
            Position(
                line_no=n,
                source_row=n,
                linha_extrato=it.name,
                tipo=it.tipo,
                codigo=it.codigo,
                quantidade=it.quantidade,
                preco_unitario=it.preco,
                valor=it.valor,
                data_posicao=period_end,
                vencimento=it.vencimento,
                taxa_texto=taxa,
                estrategia_corretora=it.estrategia,
                classe_corretora=it.classe,
                emissor=it.emissor,
                fonte_texto="ocr" if diag.ocr else None,
                codigo_conferido=it.codigo_conferido,
                taxa_conferida=taxa_ok,
                ajustes_ocr=ajustes,
            )
        )
    for it in ctx.items:
        cnt, tot = diag.by_group.get(it.group, (0, Decimal("0")))
        diag.by_group[it.group] = (cnt + 1, tot + it.valor)
    n_rows = len(positions) + len(ctx.unread)
    sum_all = sum((p.valor for p in positions), Decimal("0"))
    checks: list[tuple[str, bool, Decimal | None]] = []

    def check(name: str, expected: Decimal, actual: Decimal, rows: int) -> None:
        gap = actual - expected
        ok = abs(gap) <= CENT * max(rows, 1)
        checks.append((name, ok, None if ok else gap))

    for name, printed, items in ctx.subtotals:
        check(name, printed, sum((i.valor for i in items), Decimal("0")), len(items))
    groups_in_items = {it.group for it in ctx.items}
    for g, printed in ctx.sumario.items():
        items = [i for i in ctx.items if i.group == g]
        label = GROUP_LABEL.get(g, f"{g[1:]} (classe sem leitor)")
        check(f"folhas x Sumário {label}", printed, sum((i.valor for i in items), Decimal("0")), len(items))
    for g in sorted(groups_in_items - set(ctx.sumario)):
        items = [i for i in ctx.items if i.group == g]
        check(f"folhas x Sumário {GROUP_LABEL[g]} (classe ausente do Sumário)", Decimal("0"), sum((i.valor for i in items), Decimal("0")), len(items))
    if ctx.rf_emissor_total is not None:
        rf = [i for i in ctx.items if i.group == "rf"]
        check("renda fixa x Posição Consolidada Por Emissor", ctx.rf_emissor_total, sum((i.valor for i in rf), Decimal("0")), len(rf))
    check("folhas x Total do Sumário", ctx.sumario_total, sum_all, n_rows)
    diag.checks = checks
    diag.unread = list(ctx.unread)
    tol = CENT * max(n_rows, 1)
    failures = [f"{name}: gap R$ {gap}" for name, ok, gap in checks if not ok]
    if failures and diag.unattributed:
        # numbers no reader took (a heading not found, or not known): where they are, never what they say
        failures += [f"não atribuída a nenhuma seção: {u}" for u in diag.unattributed]
    if ctx.unread or failures:
        first_fail = next(((n, g) for n, ok, g in checks if not ok), None)
        exc = StatementTotalMismatch(
            stated_total=ctx.sumario_total,
            sum_of_lines=sum_all,
            tolerance=tol,
            n_rows=n_rows,
            unreadable_rows=[UnreadableRow(i + 1, u) for i, u in enumerate(ctx.unread)],
            check=first_fail[0] if first_fail else None,
            failures=failures,
        )
        exc.extrato_diagnostics = diag  # for the runner's aggregate lines; holds no text of the statement
        raise exc
    notes.append("Verificações de soma executadas: " + ", ".join(f"{n}: ok" for n, _, _ in checks) + ".")
    if diag.fund_ref_date_differs:
        notes.append(
            f"{diag.fund_ref_date_differs} fundo(s) com data de referência da cota diferente da data da posição; "
            "a data da posição é a do período do extrato."
        )
    if diag.unknown_sections:
        notes.append(f"{len(diag.unknown_sections)} seção(ões) de título desconhecido ignorada(s); o Total do Sumário conferiu.")
    if diag.ocr:
        notes.append(
            "Extrato sem camada de texto nos rótulos: nomes, códigos, CNPJs, emissores e taxas lidos por OCR; "
            "valores, quantidades e datas lidos da camada de texto do PDF. Somas conferidas."
        )
    stmt = Statement(
        holder=scrub.holder,
        corretora=broker,
        stated_total=ctx.sumario_total,
        sum_of_lines=sum_all,
        tolerance=tol,
        positions=tuple(positions),
        position_date=period_end,
        position_dates=(period_end,),
        source_format="pdf",
        notes=tuple(notes),
    )
    return stmt, diag


# ---------------------------------------------------------------------------
# The local runner: masked, aggregate output only.
# ---------------------------------------------------------------------------


def describe(stmt: Statement, diag: Diagnostics) -> list[str]:
    """Counts, subtotals, checks and coverage. Never a name, account, CPF, address, certificate or asset name."""
    ps = stmt.positions
    n = len(ps)
    funds = [p for p in ps if p.tipo in ("fundo", "FIDC", "FII")]
    rf = [p for p in ps if p.classe_corretora == "Renda Fixa"]
    out = [
        f"layout: extrato da conta investimento; data da posição: {stmt.position_date.isoformat()}; "
        f"páginas: {diag.pages}; extrator: {diag.extractor}",
        "seções: " + ", ".join(f"{k} {v}" for k, v in sorted(diag.sections.items()))
        + (f"; desconhecidas: {', '.join(diag.unknown_sections)}" if diag.unknown_sections else ""),
        f"posições: {n} (por tipo: {dict(sorted(Counter(p.tipo for p in ps).items()))}); "
        f"total das linhas R$ {sp._fmt(stmt.sum_of_lines)}; total declarado R$ {sp._fmt(stmt.stated_total)}",
        f"linhas não lidas: {len(diag.unread)}",
    ]
    for g, (cnt, tot) in sorted(diag.by_group.items()):
        out.append(f"  {GROUP_LABEL.get(g, g)}: {cnt} posições, R$ {sp._fmt(tot)}")
    for name, ok, gap in diag.checks:
        out.append(f"  verificação [{'ok' if ok else 'FALHOU'}] {name}" + (f" (diferença R$ {sp._fmt(gap)})" if gap is not None else ""))
    out.append(
        "cobertura: "
        f"codigo {sum(1 for p in ps if p.codigo)}/{n}; "
        f"cnpj {sum(1 for p in funds if codigo_cnpj(p.codigo))}/{len(funds)} fundos; "
        f"vencimento {sum(1 for p in rf if p.vencimento)}/{len(rf)} renda fixa; "
        f"taxa_texto {sum(1 for p in rf if p.taxa_texto)}/{len(rf)} renda fixa; "
        f"emissor {sum(1 for p in rf if p.emissor)}/{len(rf)} renda fixa; "
        f"quantidade {sum(1 for p in ps if p.quantidade is not None)}/{n}"
    )
    out.append(
        f"quebras de linha: prefixo {diag.wrapped_prefix}, cauda {diag.wrapped_tail}, ambíguas {diag.wrap_ambiguous}; "
        f"tabelas: {dict(sorted(diag.layout_modes.items()))}; por emissor: {diag.emissor_table}; "
        f"linhas mascaradas ignoradas: {diag.masked_lines_skipped}; texto após totais: {diag.lines_after_total}; "
        f"fundos com data de cota diferente: {diag.fund_ref_date_differs}"
    )
    out += _describe_ocr(diag)
    return out


def _describe_ocr(diag: Diagnostics) -> list[str]:
    if not diag.ocr:
        return []
    st = diag.ocr_stats
    words = (
        f"palavras OCR {st.ocr_words}, da camada de texto {st.pdf_words}; descartadas: sobre a camada de texto "
        f"{st.dropped_overlap}, numéricas na coluna de um número {st.dropped_numeric}, marcas soltas {st.dropped_marks}; "
        f"códigos relidos sozinhos {st.reread}"
        if isinstance(st, ocr.MergeStats) else "contagem de palavras indisponível"
    )
    return [
        f"OCR: rótulos lidos por OCR (tesseract por); números e datas da camada de texto; {words}",
        f"OCR colunas: valores por posição; traços de valor ausente lidos e ignorados {diag.ocr_specks}; "
        f"linhas com quantidade x preço = Saldo Bruto {diag.qty_price_checked}",
        "OCR conferência: " + (", ".join(f"{k} {v}" for k, v in sorted(diag.ocr_checks.items())) or "nada a conferir"),
    ]


def describe_assets(stmt: Statement) -> list[str]:
    """``--mostrar-ativos``: one line per position with the asset as printed (the owner allowed asset names).

    Holder data stays masked: ``linha_extrato`` and ``emissor`` were scrubbed at read time, and the
    cover, the account, the CPF, the address and the plan certificates are never in a position.
    """
    out = []
    for p in stmt.positions:
        cnpj = codigo_cnpj(p.codigo)
        flags = []
        if p.fonte_texto:
            flags.append(f"lido por {p.fonte_texto.upper()}")
        if p.codigo_conferido is not None:
            flags.append("código conferido" if p.codigo_conferido else "código NÃO conferido")
        if p.taxa_conferida is not None:
            flags.append("taxa conferida" if p.taxa_conferida else "taxa NÃO conferida")
        flags += list(p.ajustes_ocr)
        out.append(
            f"  {p.line_no:>3} {p.tipo} | {p.linha_extrato} | codigo {p.codigo or '-'} | cnpj {cnpj or '-'} | "
            f"vencimento {p.vencimento.isoformat() if p.vencimento else '-'} | taxa {p.taxa_texto or '-'} | "
            f"valor R$ {sp._fmt(p.valor)}" + (f" | {'; '.join(flags)}" if flags else "")
        )
    return out


def _describe_failure(exc: StatementError) -> list[str]:
    out = [f"ERRO: {exc}"]
    diag = getattr(exc, "extrato_diagnostics", None)
    if isinstance(diag, Diagnostics):
        out += [f"  não atribuída: {u}" for u in diag.unattributed]
        out += _describe_ocr(diag)
        out.append("seções: " + ", ".join(f"{k} {v}" for k, v in sorted(diag.sections.items()))
                   + (f"; desconhecidas: {', '.join(diag.unknown_sections)}" if diag.unknown_sections else ""))
        out.append(f"linhas não lidas: {len(diag.unread)}")
        out += [f"  não lida: {u}" for u in diag.unread]
        for g, (cnt, tot) in sorted(diag.by_group.items()):
            out.append(f"  {GROUP_LABEL.get(g, g)}: {cnt} posições, R$ {sp._fmt(tot)}")
        for name, ok, gap in diag.checks:
            out.append(f"  verificação [{'ok' if ok else 'FALHOU'}] {name}" + (f" (diferença R$ {sp._fmt(gap)})" if gap is not None else ""))
        out.append(f"quebras de linha: prefixo {diag.wrapped_prefix}, cauda {diag.wrapped_tail}, ambíguas {diag.wrap_ambiguous}; "
                   f"tabelas: {dict(sorted(diag.layout_modes.items()))}; por emissor: {diag.emissor_table}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Reads BTG PDFs (extrato or performance report) and prints ONLY masked, aggregate output.")
    ap.add_argument("files", nargs="+", help="BTG 'Extrato da Conta Investimento' or 'Relatório de Performance' PDF(s)")
    ap.add_argument("--consolidate", action="store_true", help="consolidate the statements and describe the consolidated view")
    ap.add_argument(
        "--mostrar-ativos",
        action="store_true",
        help="also print, per position, type, asset name, code, CNPJ, maturity, rate, value and the OCR flags "
        "(holder name, CPF, account, address and plan certificate stay masked)",
    )
    args = ap.parse_args(argv)
    from src.portfolio.consolidate import consolidate, describe_consolidated

    statements = []
    rc = 0
    for i, f in enumerate(args.files, start=1):
        print(f"== arquivo {i} ==")
        try:
            stmt, diag, layout = read_any_pdf_bytes(Path(f).read_bytes())
        except (StatementFormatError, StatementTotalMismatch) as exc:
            print("\n".join(_describe_failure(exc)))
            rc = 2
            continue
        except OSError as exc:
            print(f"ERRO: arquivo não pôde ser aberto ({type(exc).__name__})")
            rc = 2
            continue
        statements.append(stmt)
        if layout == "extrato":
            print("\n".join(describe(stmt, diag)))
        else:
            print("layout: relatório de performance")
            print("\n".join(sp.describe(stmt, diag)))
        if args.mostrar_ativos:
            print("ativos:")
            print("\n".join(describe_assets(stmt)))
    if args.consolidate and statements and rc == 0:
        print("== consolidação ==")
        try:
            print("\n".join(describe_consolidated(consolidate(statements))))
        except StatementError as exc:
            print(f"ERRO: {exc}")
            rc = 2
    elif args.consolidate and rc != 0:
        print("== consolidação não executada: algum arquivo não foi lido ==")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
