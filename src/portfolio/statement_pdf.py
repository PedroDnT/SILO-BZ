"""Reader for the BTG "Relatório de Performance" PDF (text layer, advisory co-branded).

    python -m src.portfolio.statement_pdf FILE.pdf [FILE2.pdf ...] [--consolidate]

Layout facts this reader is built on (docs/reference/portfolio/statement-pdf.md): the
position rows carry the name as printed and NO CNPJ, ISIN or CPF; credit instruments carry
their registry code inside the name; the page footer does not match the page count, so
sections are found by their headings, matched on an accent-stripped, lowercase, space-free
key (the text layer prints stray spaces next to the letter 't').

Same hard rules as the spreadsheet reader (``statement.py``):

* the cover page text is read only to build the ``Masker`` (lines ``Nome`` and
  ``Conta Investimento``) and then discarded; every later line is scrubbed through it;
* the PDF bytes are fed to the extractor on STDIN and never touch the disk;
* the sum checks (leaves vs strategy subtotals, strategy subtotals vs class totals, the
  consolidated ``Total`` vs the leaves, leaves + current account vs the gross equity) all run
  where their anchors exist, within R$ 0,01 x the number of rows, and a failure raises
  ``StatementTotalMismatch`` naming the gap and the rows not read;
* nothing is guessed: a row that cannot be read is named (by coordinates and shape, never by
  its text) and stops the read; ``tipo`` is set only from a fact the statement prints.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import re
import shutil
import subprocess
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from src.portfolio.mask import Masker
from src.portfolio.statement import (
    Position,
    Statement,
    StatementError,
    StatementFormatError,
    StatementTotalMismatch,
    UnreadableRow,
)

CENT = Decimal("0.01")

# ---------------------------------------------------------------------------
# Keys and vocabulary.
# ---------------------------------------------------------------------------


def _unaccent(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def key(s: str) -> str:
    """Accent-stripped, lowercase, with no space, hyphen, colon or asterisk: 'Fundo de Invest iment o' -> 'fundodeinvestimento'."""
    return re.sub(r"[\s\-_:*]+", "", _unaccent(s).lower())


CLASSES = {"rendafixa": "Renda Fixa", "fundodeinvestimento": "Fundo de Investimento", "rendavariavel": "Renda Variável"}
STRATEGIES = {
    "posfixado": "Pós-fixado",
    "inflacao": "Inflação",
    "prefixado": "Pré-fixado",
    "alternativo": "Alternativo",
    "retornoabsoluto": "Retorno Absoluto",
    "rendavariavel": "Renda Variável",
}
# "E, quando abrimos a rentabilidade por estratégia" and "Atribuição de Resultado" follow the position in the
# 2026-08 layout, which has no "Detalhamento dos ativos" between them (#747); key() keeps the comma.
SECTION_END_KEYS = (
    "detalhamentodosativos",
    "arentabilidadecompleta",
    "rentabilidadecompleta",
    "movimentacoesdaconta",
    "e,quandoabrimosarentabilidade",
    "atribuicaoderesultado",
)
FURNITURE = re.compile(r"^(pagina\d+(de\d+)?|relatoriodeperformance)$")
COLUMN_HEADER_KEYS = ("posicaobruta", "%total")
# The same header wrapped one word per line (2026-08 layout, #747): matched whole, never as a prefix.
COLUMN_HEADER_WORDS = {"posicao", "ativo", "bruta"}

_MONEY = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d{2}$|^-?\d+,\d{2}$")
# An amount the report printed with its last digit cut ("7.841,1"): never read as a value (#747).
_CUT_MONEY = re.compile(r"^\d{1,3}(?:\.\d{3})*,\d$")
_PCT = re.compile(r"^-?\d+(?:,\d+)?%$")
_DATE_RANGE = re.compile(r"(\d{2}/\d{2}/\d{4})\s*(?:a|à|até|-|–)\s*(\d{2}/\d{2}/\d{4})")
_TICKER = re.compile(r"^(?=[A-Z0-9]*[A-Z])[A-Z0-9]{4}\d{1,2}$")  # a root of letters or digits: B3SA3, B5P211, 5PRE11
_REGISTRY = re.compile(r"(?<![A-Z0-9])(CRA|CRI|CDB|DEB|CDCA|LCA|LCI|LF|LIG|NC)-([A-Z0-9]+)\*?\s*$")
_BACEN = re.compile(r"^BACEN\b.*?\b(NTNB|NTNF|NTNC|NTNI|LTN|LFT)\*?\s*$")
REGISTRY_TIPO = {"CRA": "CRA", "CRI": "CRI", "CDB": "CDB", "DEB": "debênture", "LCA": "LCA", "LCI": "LCI"}
BACEN_TITLE = {"NTNB": "NTN-B", "NTNF": "NTN-F", "NTNC": "NTN-C", "NTNI": "NTN-I", "LTN": "LTN", "LFT": "LFT"}


def parse_br_number(tok: str) -> Decimal:
    t = tok.strip().rstrip("%")
    return Decimal(t.replace(".", "").replace(",", "."))


def is_money(tok: str) -> bool:
    return bool(_MONEY.match(tok))


def is_pct(tok: str) -> bool:
    return bool(_PCT.match(tok))


def join_fragments(parts: list[str]) -> str:
    """Join the pieces of a wrapped name; a piece ending in a hyphen continues with no space ('...CRA-' + 'CRA0250001*')."""
    out = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        out += part if (not out or out.endswith("-")) else " " + part
    return out


def split_row(line: str) -> tuple[str, list[str]]:
    """(label, numeric tail): the tail is the maximal suffix of money, percent and '-' tokens."""
    toks = re.sub(r"R\$\s*", "", line).split()
    i = len(toks)
    while i > 0 and (is_money(toks[i - 1]) or is_pct(toks[i - 1]) or toks[i - 1] == "-"):
        i -= 1
    return " ".join(toks[:i]), toks[i:]


def shape(label: str, tail: list[str]) -> str:
    """The structure of a line, never its text: 'L' label, 'M' money, 'P' percent, '-' missing."""
    parts = ["L"] if label else []
    parts += ["M" if is_money(t) else "P" if is_pct(t) else "-" for t in tail]
    return "".join(parts) or "empty"


# ---------------------------------------------------------------------------
# Text extraction: in memory only.
# ---------------------------------------------------------------------------


def extract_pages(data: bytes) -> tuple[list[str], str]:
    """The PDF's text, one string per page, and the extractor used. ``data`` never touches the disk."""
    if shutil.which("pdftotext"):
        proc = subprocess.run(["pdftotext", "-layout", "-", "-"], input=data, capture_output=True, timeout=180, check=False)
        if proc.returncode != 0:
            raise StatementFormatError(f"pdftotext failed (exit {proc.returncode}): the file may be encrypted or damaged")
        pages = proc.stdout.decode("utf-8", errors="replace").split("\f")
        if pages and not pages[-1].strip():
            pages.pop()
        if any(p.strip() for p in pages):
            return pages, "poppler"
    try:
        from pypdf import PdfReader
    except ImportError:
        raise StatementFormatError(
            "no PDF text extractor: install poppler-utils (pdftotext) or the Python package pypdf, or the file has no text layer"
        ) from None
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(p.extract_text(extraction_mode="layout") or "") for p in reader.pages]
    except Exception as exc:  # noqa: BLE001 - pypdf raises many types; the message names the type only
        raise StatementFormatError(f"pypdf could not read the file ({type(exc).__name__})") from None
    if not any(p.strip() for p in pages):
        raise StatementFormatError("the PDF has no text layer (a scanned image): nothing to read")
    return pages, "pypdf"


def raw_words(data: bytes) -> frozenset[str]:
    """The words of ``pdftotext -raw`` (STDIN, never disk), which prints them whole where the
    layout mode splits them next to t, f and r ('Marf rig'). Empty without poppler or on failure:
    names then stay as the layout text printed them (#756)."""
    if not shutil.which("pdftotext"):
        return frozenset()
    proc = subprocess.run(["pdftotext", "-raw", "-", "-"], input=data, capture_output=True, timeout=180, check=False)
    if proc.returncode != 0:
        return frozenset()
    return frozenset(proc.stdout.decode("utf-8", errors="replace").split())


def respace_name(name: str, words: frozenset[str]) -> str:
    """Join a run of 2 to 4 tokens when the joined word is in ``words`` and one piece is not a word there.

    'Marf rig' -> 'Marfrig' and 'Invest iment o' -> 'Investimento'; 'Valor aplicado' stays, because
    'Valoraplicado' is not a word of the raw text. Nothing outside the raw text is ever produced.
    """
    if not words:
        return name
    toks = name.split()
    out: list[str] = []
    i = 0
    while i < len(toks):
        for j in range(min(len(toks), i + 4), i + 1, -1):
            run = toks[i:j]
            joined = "".join(run)
            if joined in words and any(t not in words for t in run):
                out.append(joined)
                i = j
                break
        else:
            out.append(toks[i])
            i += 1
    return " ".join(out)


# ---------------------------------------------------------------------------
# Parse model.
# ---------------------------------------------------------------------------


@dataclass
class Row:
    name: str
    valor: Decimal
    classe: str | None
    estrategia: str | None
    coord: str  # "p3:l41": page and line, never text
    wrapped_prefix: int = 0
    wrapped_tail: int = 0
    wrap_ambiguous: bool = False
    order: tuple[int, int, int] = (0, 0, 0)


@dataclass
class DetailRow:
    name: str
    strategy_key: str | None
    saldo_bruto: Decimal | None
    quantidade: Decimal | None
    vencimento: dt.date | None
    taxa: str | None
    preco: Decimal | None
    used: bool = False


@dataclass
class Diagnostics:
    extractor: str = ""
    pages: int = 0
    two_column_pages: int = 0
    wrapped_prefix: int = 0
    wrapped_tail: int = 0
    wrap_ambiguous: int = 0
    detail_rows: int = 0
    detail_joined: int = 0
    detail_unmatched: int = 0
    detail_lines_unread: int = 0
    by_strategy: dict[tuple[str, str], tuple[int, Decimal]] = field(default_factory=dict)
    checks: list[tuple[str, bool, Decimal | None]] = field(default_factory=list)  # name, ok, gap


@dataclass
class _Stream:
    cls: str | None = None
    strat: str | None = None
    frags: list[str] = field(default_factory=list)
    frags_anchored: bool = False  # the first fragment follows a numeric row
    last_row: Row | None = None
    last_was_row: bool = False


class _Section:
    """What the consolidated-position section yields."""

    def __init__(self) -> None:
        self.rows: list[Row] = []
        self.unread: list[UnreadableRow] = []
        self.strategy_subtotal: dict[tuple[str, str], Decimal] = {}
        self.class_subtotal: dict[str, Decimal] = {}
        self.total: Decimal | None = None


def _money_or_none(tail: list[str]) -> Decimal | None:
    return parse_br_number(tail[0]) if tail and is_money(tail[0]) else None


def _cells_with_spans(line: str) -> list[tuple[str, int]]:
    return [(m.group(0), m.start()) for m in re.finditer(r"\S+(?: \S+)*", line)]


def _flush_frags(st: _Stream, sec: _Section, coord: str, diag: Diagnostics) -> None:
    if not st.frags:
        return
    if st.frags_anchored and st.last_row is not None:
        st.last_row.name = join_fragments([st.last_row.name] + st.frags)
        st.last_row.wrapped_tail += len(st.frags)
        diag.wrapped_tail += len(st.frags)
    else:
        sec.unread.append(UnreadableRow(0, f"{coord}: text line(s) with no number, not attached to any row (shape L x{len(st.frags)})"))
    st.frags = []
    st.frags_anchored = False


def _end_block(st: _Stream, sec: _Section, coord: str, diag: Diagnostics) -> None:
    """A line blank in this column ends the row block: text after a value line is that row's tail.

    The 2026-08 layout prints a long name in two halves around its value line (#747), so the
    half below must not wait to become the next row's prefix.
    """
    if st.frags and st.frags_anchored:
        _flush_frags(st, sec, coord, diag)
    st.last_was_row = False


def _process_line(line: str, st: _Stream, sec: _Section, coord: str, diag: Diagnostics) -> None:
    label, tail = split_row(line)
    k = key(label)
    if not label and not tail:
        return
    if FURNITURE.match(k) or k in COLUMN_HEADER_WORDS or any(k.startswith(h) for h in COLUMN_HEADER_KEYS):
        return
    money = _money_or_none(tail)
    if k == "total" and money is not None:
        _flush_frags(st, sec, coord, diag)
        sec.total = money
        st.last_was_row = False
        return
    if k.startswith("total") and (k[5:] in CLASSES or k[5:] in STRATEGIES) and money is not None:
        _flush_frags(st, sec, coord, diag)
        rest = k[5:]
        as_strategy = rest in STRATEGIES and (rest != "rendavariavel" or st.cls == "Renda Variável")
        if as_strategy and st.cls:
            sec.strategy_subtotal[(st.cls, STRATEGIES[rest])] = money
        elif rest in CLASSES:
            sec.class_subtotal[CLASSES[rest]] = money
        st.last_was_row = False
        return
    is_heading = False
    if k in CLASSES or k in STRATEGIES:
        if k == "rendavariavel":
            is_heading = True
            as_strategy = st.cls == "Renda Variável"
        elif k in CLASSES:
            is_heading, as_strategy = True, False
        else:
            is_heading, as_strategy = True, True
        if is_heading:
            _flush_frags(st, sec, coord, diag)
            if as_strategy:
                st.strat = STRATEGIES[k]
                if money is not None and st.cls:
                    sec.strategy_subtotal[(st.cls, st.strat)] = money
            else:
                st.cls, st.strat = CLASSES[k], None
                if money is not None:
                    sec.class_subtotal[st.cls] = money
            st.last_row, st.last_was_row = None, False
            return
    if not tail:
        # text only: a wrapped name
        if not st.frags:
            st.frags_anchored = st.last_was_row
        st.frags.append(label)
        st.last_was_row = False
        return
    # a numeric line: a position row
    shp = shape(label, tail)
    if money is None:
        sec.unread.append(UnreadableRow(0, f"{coord}: position value missing or not a money amount (shape {shp})"))
        st.frags, st.frags_anchored = [], False
        st.last_was_row = False
        return
    if st.cls is None:
        sec.unread.append(UnreadableRow(0, f"{coord}: position row before any class heading (shape {shp})"))
        st.last_was_row = False
        return
    prefix = list(st.frags)
    ambiguous = bool(prefix and st.frags_anchored)
    st.frags, st.frags_anchored = [], False
    name = join_fragments(prefix + ([label] if label else []))
    if not name:
        sec.unread.append(UnreadableRow(0, f"{coord}: row with a value and no name (shape {shp})"))
        st.last_was_row = False
        return
    row = Row(name=name, valor=money, classe=st.cls, estrategia=st.strat, coord=coord, wrapped_prefix=len(prefix), wrap_ambiguous=ambiguous)
    diag.wrapped_prefix += len(prefix)
    diag.wrap_ambiguous += 1 if ambiguous else 0
    sec.rows.append(row)
    st.last_row, st.last_was_row = row, True


def _find_section(lines: list[tuple[int, int, str]], heading_key: str, follow_keys: set[str]) -> int | None:
    """Index of the first heading occurrence followed, within 25 lines, by one of ``follow_keys``."""
    for i, (_, _, text) in enumerate(lines):
        if key(split_row(text)[0]) == heading_key:
            for _, _, nxt in lines[i + 1 : i + 26]:
                if any(key(c) in follow_keys for c, _ in _cells_with_spans(nxt)):
                    return i
    return None


def _strip_furniture(pages: list[list[str]]) -> list[list[str]]:
    """Drop a text-only line from the first or last two lines of a page when the same line repeats at the edge of 2+ other pages."""
    if len(pages) < 3:
        return pages
    edges: Counter[str] = Counter()
    for pg in pages:
        nonblank = [ln for ln in pg if ln.strip()]
        for ln in set(nonblank[:2] + nonblank[-2:]):
            edges[re.sub(r"\s+", " ", ln.strip())] += 1
    out = []
    for pg in pages:
        nonblank = [ln for ln in pg if ln.strip()]
        edge = set(nonblank[:2] + nonblank[-2:])
        kept = []
        for ln in pg:
            norm = re.sub(r"\s+", " ", ln.strip())
            lab, tail = split_row(ln)
            if ln in edge and not tail and edges[norm] >= 3:
                continue
            kept.append(ln)
        out.append(kept)
    return out


# ---------------------------------------------------------------------------
# The parser.
# ---------------------------------------------------------------------------


def _holder_masker(cover: str) -> tuple[Masker, list[str]]:
    nome = conta = None
    for raw in cover.splitlines():
        line = raw.strip()
        k = key(line)
        if nome is None and re.match(r"^nome\b", _unaccent(line), re.I):
            nome = re.sub(r"^nome\s*[:\-]?\s*", "", line, flags=re.I).strip() or None
        elif conta is None and k.startswith("containvestimento"):
            conta = re.sub(r"^conta\s+investimento\s*[:\-]?\s*", "", line, flags=re.I).strip() or None
    if not nome:
        raise StatementFormatError("cover page: no 'Nome' line found, so the holder cannot be masked: nothing was read")
    notes = []
    if not conta:
        notes.append("Capa sem linha 'Conta Investimento': o número da conta não pôde ser mascarado por valor.")
    return Masker(nome, None, conta), notes


def parse_pdf_pages(pages: list[str], extractor: str = "text", words: frozenset[str] = frozenset()) -> tuple[Statement, Diagnostics]:
    diag = Diagnostics(extractor=extractor, pages=len(pages))
    if not pages or not any(p.strip() for p in pages):
        raise StatementFormatError("the PDF has no text")
    masker, notes = _holder_masker(pages[0])
    broker = "BTG Pactual" if "btgpactual" in key(pages[0]) else None
    # the cover is discarded; everything after is scrubbed
    scrubbed = [[str(masker.scrub(ln)) for ln in pg.splitlines()] for pg in pages[1:]]
    del pages
    # The period is read before the page furniture is stripped: a report that repeats
    # "Período de ... a ..." at the top of every page would otherwise lose it as a header.
    period_end = _period_end([(pi + 2, li + 1, ln) for pi, pg in enumerate(scrubbed) for li, ln in enumerate(pg)])
    scrubbed = _strip_furniture(scrubbed)
    lines: list[tuple[int, int, str]] = [(pi + 2, li + 1, ln) for pi, pg in enumerate(scrubbed) for li, ln in enumerate(pg)]

    bruto, liquido_unused, saldo_final, caixa_valor = _summary_anchors(lines)

    sec = _consolidated_section(lines, diag)
    detail = _detail_rows(lines, diag)

    leaves: list[Position] = []
    unread = list(sec.unread)
    for row in sec.rows:
        row.name = respace_name(row.name, words)
        pos = _position_from_row(row, period_end, len(leaves) + 1, detail, diag)
        leaves.append(pos)
    for pos in leaves:
        cnt, tot = diag.by_strategy.get((pos.classe_corretora or "?", pos.estrategia_corretora or "?"), (0, Decimal("0")))
        diag.by_strategy[(pos.classe_corretora or "?", pos.estrategia_corretora or "?")] = (cnt + 1, tot + pos.valor)
    diag.detail_unmatched = sum(1 for d in detail if not d.used)

    if caixa_valor is None:
        cut = _wrapped_conta_corrente(lines)[1]
        if cut is not None:
            caixa_valor = _derived_caixa(cut, bruto if bruto is not None else saldo_final, sec.total)
            if caixa_valor is not None:
                # The gross tie below then holds by construction; the leaves still tie to the 'Total' on their own.
                notes.append(
                    f"Conta corrente impressa cortada no PDF ('{cut}'): R$ {_br_money(caixa_valor)} é o patrimônio bruto "
                    "menos o 'Total' da posição consolidada, conferido contra os dígitos impressos."
                )
    caixa: Position | None = None
    if caixa_valor is not None and caixa_valor != 0:
        caixa = Position(
            line_no=len(leaves) + 1,
            source_row=len(leaves) + len(unread) + 1,
            linha_extrato="Conta corrente",
            tipo="caixa",
            codigo=None,
            quantidade=None,
            preco_unitario=None,
            valor=caixa_valor,
            data_posicao=period_end,
            estrategia_corretora="Conta corrente",
        )
    positions = leaves + ([caixa] if caixa else [])
    sum_leaves = sum((p.valor for p in leaves), Decimal("0"))
    sum_all = sum_leaves + (caixa.valor if caixa else Decimal("0"))
    n_rows = len(positions) + len(unread)

    checks = _run_checks(diag, sec, leaves, sum_leaves, sum_all, bruto, saldo_final, n_rows)
    anchors = [bruto, saldo_final, sec.total]
    if all(a is None for a in anchors) and not sec.strategy_subtotal and not sec.class_subtotal:
        raise StatementFormatError(
            "no reconciliation anchor found (no strategy subtotal, class total, consolidated 'Total', 'Patrimônio bruto' or 'Saldo Bruto'): the layout is not one this reader knows"
        )
    if not sec.rows and not unread:
        raise StatementFormatError("section 'Posição consolidada dos investimentos' not found or empty")

    if bruto is not None:
        stated = bruto
    elif saldo_final is not None:
        stated = saldo_final
    elif sec.total is not None:
        stated = sec.total + (caixa.valor if caixa else Decimal("0"))
    else:
        stated = sum_all  # only subtotal anchors exist: they were checked above; no external total to tie to
    tol = CENT * max(n_rows, 1)
    failures = [f"{name}: gap R$ {gap}" for name, ok, gap in checks if not ok]
    if unread or failures:
        first_fail = next(((n, g) for n, ok, g in checks if not ok), None)
        raise StatementTotalMismatch(
            stated_total=stated,
            sum_of_lines=sum_all,
            tolerance=tol,
            n_rows=n_rows,
            unreadable_rows=[UnreadableRow(i + 1, u.reason) for i, u in enumerate(unread)],
            check=first_fail[0] if first_fail else None,
            failures=failures,
        )
    ran = ", ".join(f"{name}: ok" for name, _, _ in checks)
    notes.append(f"Verificações de soma executadas: {ran}.")
    notes_t = tuple(notes)
    stmt = Statement(
        holder=masker.holder,
        corretora=broker,
        stated_total=stated,
        sum_of_lines=sum_all,
        tolerance=tol,
        positions=tuple(positions),
        position_date=period_end,
        position_dates=(period_end,),
        source_format="pdf",
        notes=notes_t,
    )
    return stmt, diag


def _period_end(lines: list[tuple[int, int, str]]) -> dt.date:
    for _, _, text in lines:
        m = _DATE_RANGE.search(text)
        if m:
            d, mo, y = m.group(2).split("/")
            try:
                return dt.date(int(y), int(mo), int(d))
            except ValueError:
                continue
    raise StatementFormatError("no period 'DD/MM/YYYY a DD/MM/YYYY' found: the position date cannot be set")


def _summary_anchors(lines):
    bruto = liquido = saldo_final = caixa = None
    for _, _, text in lines:
        label, tail = split_row(text)
        k = key(label)
        money = [parse_br_number(t) for t in tail if is_money(t)]
        if not money:
            continue
        if k == "patrimoniobruto" and bruto is None:
            bruto = money[0]
        elif k == "patrimonioliquido" and liquido is None:
            liquido = money[0]
        elif k == "saldobruto":
            saldo_final = money[-1]
    # the current account: a row of the 'Distribuição por classe de ativos' table
    start = next((i for i, (_, _, t) in enumerate(lines) if key(split_row(t)[0]) == "distribuicaoporclassedeativos"), None)
    if start is not None:
        for _, _, text in lines[start + 1 : start + 16]:
            label, tail = split_row(text)
            if key(label) == "contacorrente":
                moneys = [parse_br_number(t) for t in tail if is_money(t)]
                caixa = moneys[0] if moneys else Decimal("0")
                break
    if caixa is None:
        # no distribution table: the first 'Conta corrente' row with an amount before the account movements
        for _, _, text in lines:
            label, tail = split_row(text)
            k = key(label)
            if k.startswith("movimentacoesdaconta"):
                break
            if k == "contacorrente":
                moneys = [parse_br_number(t) for t in tail if is_money(t)]
                if moneys:
                    caixa = moneys[0]
                    break
    if caixa is None:
        caixa = _wrapped_conta_corrente(lines)[0]
    return bruto, liquido, saldo_final, caixa


def _wrapped_conta_corrente(lines) -> tuple[Decimal | None, str | None]:
    """(amount, cut amount) of a 'Conta corrente' label the summary table wraps around its value line.

    The 2026-08 layout prints 'Cont a', then a line with only the percent and the amount, then
    'corrent e' (#747). Only that exact three-line shape is read. Its PDF can print the amount
    with the last digit cut ('7.841,1'); that is returned as text, never as a value.
    """
    for i in range(len(lines) - 2):
        label, tail = split_row(lines[i][2])
        k = key(label)
        if k.startswith("movimentacoesdaconta"):
            return None, None
        if k != "conta" or tail or key(split_row(lines[i + 2][2])[0]) != "corrente":
            continue
        value_line = re.sub(r"R\$\s*", "", lines[i + 1][2]).split()
        moneys = [parse_br_number(t) for t in value_line if is_money(t)]
        cut = [t for t in value_line if _CUT_MONEY.match(t)]
        rest = [t for t in value_line if not (is_money(t) or is_pct(t) or _CUT_MONEY.match(t))]
        if rest:
            continue
        if len(moneys) == 1 and not cut:
            return moneys[0], None
        if len(cut) == 1 and not moneys:
            return None, cut[0]
    return None, None


def _br_money(v: Decimal) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _derived_caixa(cut: str, gross: Decimal | None, total: Decimal | None) -> Decimal | None:
    """Gross minus the consolidated 'Total', accepted only when it is the cut amount plus one digit."""
    if gross is None or total is None:
        return None
    v = gross - total
    shown = _br_money(v)
    return v if v > 0 and len(shown) == len(cut) + 1 and shown.startswith(cut) else None


def _consolidated_section(lines, diag: Diagnostics) -> _Section:
    heading = "posicaoconsolidadadosinvestimentos"
    start = _find_section(lines, heading, set(CLASSES) | set(STRATEGIES))
    sec = _Section()
    if start is None:
        return sec
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if any(key(split_row(lines[j][2])[0]).startswith(e) for e in SECTION_END_KEYS):
            end = j
            break
    streams: dict[str, _Stream] = {}
    section_lines = lines[start + 1 : end]
    by_page: dict[int, list[str]] = {}
    for page, _, text in section_lines:
        by_page.setdefault(page, []).append(text)
    right_start_for_page: dict[int, int | None] = {}
    last_two_col = False
    for page, texts in by_page.items():
        found = None
        for text in texts:
            units = _split_units(text)
            if len(units) >= 2 and sum(1 for _, u in units[:2] if _is_heading_text(u)) == 2:
                found = units[1][0]
                break
        if found is None and last_two_col:
            # a continuation page: no heading pair, but many lines hold two units
            two = [_split_units(t) for t in texts if t.strip()]
            multi = [u for u in two if len(u) >= 2]
            if multi and len(multi) >= max(2, int(0.3 * len(two))):
                found = min(u[1][0] for u in multi)
        last_two_col = found is not None
        if found is not None:
            diag.two_column_pages += 1
        right_start_for_page[page] = found
    seq = 0
    for page, ln_no, text in section_lines:
        coord = f"p{page}:l{ln_no}"
        right_start = right_start_for_page[page]
        if right_start is None:
            parts = [("S", text)]
        else:
            units = _split_units(text, right_start)
            if len(units) >= 2:
                parts = [("L", units[0][1]), ("R", " ".join(u for _, u in units[1:]))]
            elif units:
                parts = [("R" if units[0][0] >= right_start - 6 else "L", units[0][1])]
            else:
                parts = []
        present = {sid for sid, part in parts if part.strip()}
        for sid, st in streams.items():
            if sid not in present:
                _end_block(st, sec, coord, diag)
        for sid, part in parts:
            if not part.strip():
                continue
            st = streams.setdefault(sid, _Stream())
            before = len(sec.rows)
            _process_line(part, st, sec, coord, diag)
            for r in sec.rows[before:]:
                r.order = (page, 1 if sid == "R" else 0, seq)
                seq += 1
    for st in streams.values():
        _flush_frags(st, sec, "end of section", diag)
    sec.rows.sort(key=lambda r: r.order)
    return sec


def _split_units(line: str, right_start: int | None = None) -> list[tuple[int, str]]:
    """The row units of a (possibly two-column) line, as (start column, text).

    A unit ends when its run of money and percent tokens ends and text follows, or at a gap of
    three or more spaces between two text tokens. This does not depend on a fixed character
    column, which the text layer rescales from page to page and even from line to line.

    With ``right_start`` (the page's right column, once known), a run of numbers that began in
    the left column also ends at the first number that starts in the right one: a line can hold
    only the two columns' values, their names wrapped above and below it (#747).
    """
    units: list[list[tuple[int, str]]] = []
    cur: list[tuple[int, str]] = []
    prev_end: int | None = None
    prev_numeric = False
    for m in re.finditer(r"\S+", line):
        t, start = m.group(), m.start()
        gap = start - prev_end if prev_end is not None else 0
        numeric = is_money(t) or is_pct(t) or (t == "-" and gap >= 3)
        crosses = (
            right_start is not None and prev_numeric and numeric and cur[0][0] < right_start - 6 <= start
        )
        if cur and ((prev_numeric and not numeric) or (not prev_numeric and not numeric and gap >= 3) or crosses):
            units.append(cur)
            cur = []
        cur.append((start, t))
        prev_end, prev_numeric = m.end(), numeric
    if cur:
        units.append(cur)
    return [(u[0][0], " ".join(t for _, t in u)) for u in units]


def _is_heading_text(unit: str) -> bool:
    label, _ = split_row(unit)
    k = key(label)
    return k in CLASSES or k in STRATEGIES


DETAIL_COLUMNS = sorted(
    ["ativo", "datainicial", "quantidade", "resgate", "vencimento", "taxa", "saldobruto", "precomedio", "saldoliquido", "valoraplicado", "defasagem", "projecao", "preco"],
    key=len,
    reverse=True,
)
_DATE_TOKEN = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def _detail_header(text: str) -> list[str] | None:
    """The column keys of a 'Detalhamento' header line, however the text layer spaced it."""
    rest = key(text)
    cols: list[str] = []
    while rest:
        for c in DETAIL_COLUMNS:
            if rest.startswith(c):
                cols.append(c)
                rest = rest[len(c) :]
                break
        else:
            # a last column cut at the page edge ('Def' for 'Defasagem', #751): it holds no value we read
            if len(rest) >= 3 and any(c.startswith(rest) for c in DETAIL_COLUMNS):
                break
            return None
    return cols if cols and cols[0] == "ativo" and "saldobruto" in cols else None


def _detail_cells(text: str, header: list[str]) -> list[str] | None:
    """The row's cells aligned to ``header``: by wide gaps when they survive, else by the columns' types."""
    cells = [c.strip() for c in re.split(r"\s{2,}", text.strip())]
    if len(cells) == len(header):
        return cells
    toks = text.split()
    if "taxa" in header:
        ti = header.index("taxa")
        after = len(header) - ti - 1
        dates = [i for i, t in enumerate(toks) if _DATE_TOKEN.match(t)]
        if "datainicial" not in header or not dates:
            return None
        i = dates[0]
        n_before = ti - 1
        end = len(toks) - after
        if i + n_before >= end or not toks[:i]:
            return None
        return [" ".join(toks[:i])] + toks[i : i + n_before] + [" ".join(toks[i + n_before : end])] + toks[end:]
    n = len(header) - 1
    if len(toks) < n + 1:
        return None
    return [" ".join(toks[: len(toks) - n])] + toks[len(toks) - n :]


def _detail_rows(lines, diag: Diagnostics) -> list[DetailRow]:
    start = next((i for i, (_, _, t) in enumerate(lines) if key(split_row(t)[0]) == "detalhamentodosativos"), None)
    if start is None:
        return []
    end = len(lines)
    for j in range(start + 1, len(lines)):
        k = key(split_row(lines[j][2])[0])
        if k.startswith("arentabilidadecompleta") or k.startswith("rentabilidadecompleta") or k.startswith("movimentacoesdaconta"):
            end = j
            break
    if any(_carteira_strategy(t) for _, _, t in lines[start + 1 : end]):
        return _detail_rows_blocks(lines[start + 1 : end], diag)
    out: list[DetailRow] = []
    header: list[str] | None = None
    strat: str | None = None
    frags: list[str] = []
    for page, ln_no, text in lines[start + 1 : end]:
        if not text.strip():
            continue
        hdr = _detail_header(text)
        if hdr is not None:
            header = hdr
            frags = []
            continue
        label, tail = split_row(text)
        k_text = key(text)
        if k_text in STRATEGIES:
            strat = k_text
            frags = []
            continue
        if k_text in CLASSES or FURNITURE.match(k_text):
            continue
        cells = _detail_cells(text, header) if header else None
        if cells is None:
            if header is not None and not tail and not any(_DATE_TOKEN.match(t) for t in text.split()):
                frags.append(text.strip())  # a wrapped name
            else:
                diag.detail_lines_unread += 1
                frags = []
            continue
        row = dict(zip(header, cells))
        try:
            saldo = parse_br_number(row["saldobruto"]) if "saldobruto" in row and is_money(row["saldobruto"]) else None
            qtd = _opt_number(row.get("quantidade"))
            preco = parse_br_number(row["preco"]) if "preco" in row and is_money(row["preco"]) else None
            venc = _opt_date(row.get("vencimento"))
        except (ValueError, InvalidOperation):
            diag.detail_lines_unread += 1
            frags = []
            continue
        taxa = row.get("taxa")
        if taxa is not None and taxa.strip() in ("", "-"):
            taxa = None
        name = join_fragments(frags + [row.get("ativo", "")])
        frags = []
        out.append(DetailRow(name=name, strategy_key=strat, saldo_bruto=saldo, quantidade=qtd, vencimento=venc, taxa=taxa, preco=preco))
    diag.detail_rows = len(out)
    return out


# The 2026-08 layout (#751): each detail table opens with '<estratégia> ... Em carteira NN% R$ ...', its header
# spans three lines ('Preço'/'Valor' above, 'médio'/'aplicado' below), and each row is a block between blank
# lines: the name and the rate wrap above and below the one line that holds the values.
_HEADER_WORDS = ("aplicado", "preco", "valor", "medio")


def _carteira_strategy(text: str) -> str | None:
    k = key(split_row(text)[0])
    return k[: -len("emcarteira")] if k.endswith("emcarteira") and k[: -len("emcarteira")] in STRATEGIES else None


def _is_header_context(text: str) -> bool:
    rest = key(text)
    while rest:
        w = next((w for w in _HEADER_WORDS if rest.startswith(w)), None)
        if w is None:
            return False
        rest = rest[len(w) :]
    return True


def _detail_rows_blocks(section, diag: Diagnostics) -> list[DetailRow]:
    out: list[DetailRow] = []
    header: list[str] | None = None
    taxa_lo: int | None = None
    strat: str | None = None
    block: list[str] = []

    def flush() -> None:
        nonlocal block
        if block and header is not None:
            row = _block_row(block, header, taxa_lo, strat)
            if row is None:
                diag.detail_lines_unread += len(block)
            else:
                out.append(row)
        elif block:
            diag.detail_lines_unread += len(block)
        block = []

    for _, _, text in section:
        if not text.strip():
            flush()
            continue
        s = _carteira_strategy(text)
        if s is not None:
            flush()
            strat, header = s, None
            continue
        hdr = _detail_header(text)
        if hdr is not None:
            flush()
            header = hdr
            m = re.search(r"\bTaxa\b", text)
            taxa_lo = m.start() - 15 if m and "taxa" in hdr else None
            continue
        k = key(split_row(text)[0])
        if _is_header_context(text) or k.startswith("total") or FURNITURE.match(k) or _DATE_RANGE.search(text):
            flush()
            continue
        block.append(text)
    flush()
    diag.detail_rows = len(out)
    return out


def _block_row(block: list[str], header: list[str], taxa_lo: int | None, strat: str | None) -> DetailRow | None:
    """One detail row from its block of lines; None when the block has not exactly one line of values."""
    value_at = [i for i, t in enumerate(block) if re.search(r"R\$\s*\S", t)]
    if len(value_at) != 1:
        return None
    vi = value_at[0]
    toks = [(m.start(), m.group()) for m in re.finditer(r"\S+", block[vi])]
    r_at = [i for i, (_, t) in enumerate(toks) if t == "R$"]
    moneys = [toks[i + 1][1] for i in r_at if i + 1 < len(toks) and is_money(toks[i + 1][1])]
    if not moneys:
        return None
    before = toks[: r_at[0]]
    dates = [i for i, (_, t) in enumerate(before) if _DATE_TOKEN.match(t)]
    venc = qtd = None
    if "datainicial" in header and dates:
        name_end = dates[0]
        nxt = before[dates[0] + 1][1] if dates[0] + 1 < len(before) else None
        qtd = parse_br_number(nxt) if nxt is not None and is_money(nxt) else None
        if "vencimento" in header and len(dates) > 1:
            venc = _opt_date(before[dates[1]][1])
    else:
        name_end = next((i for i, (_, t) in enumerate(before) if is_money(t)), len(before))
        qtd = parse_br_number(before[name_end][1]) if name_end < len(before) else None
    used = set(range(name_end)) | set(dates) | ({dates[0] + 1} if dates and qtd is not None else set())
    # the rate: what stands in the 'Taxa' column, above, on and below the line of values, in reading order
    taxa_parts: list[str] = []
    name_parts: list[str] = []
    for i, line in enumerate(block):
        if i == vi:
            name_parts.append(" ".join(t for _, t in before[:name_end]))
            if taxa_lo is not None:
                taxa_parts += [t for j, (p, t) in enumerate(before) if j not in used and p >= taxa_lo]
            continue
        line_toks = [(m.start(), m.group()) for m in re.finditer(r"\S+", line)]
        name_parts.append(" ".join(t for p, t in line_toks if taxa_lo is None or p < taxa_lo))
        if taxa_lo is not None:
            taxa_parts += [t for p, t in line_toks if p >= taxa_lo]
    preco = parse_br_number(moneys[1]) if "precomedio" in header and "preco" in header and len(moneys) > 1 else None
    return DetailRow(
        name=join_fragments(name_parts),
        strategy_key=strat,
        saldo_bruto=parse_br_number(moneys[0]),
        quantidade=qtd,
        vencimento=venc,
        taxa=" ".join(taxa_parts) or None,
        preco=preco,
    )


def _opt_number(tok: str | None) -> Decimal | None:
    if tok is None or tok.strip() in ("", "-"):
        return None
    return parse_br_number(tok)


def _opt_date(tok: str | None) -> dt.date | None:
    if tok is None or tok.strip() in ("", "-"):
        return None
    d, m, y = tok.strip().split("/")
    return dt.date(int(y), int(m), int(d))


def _type_row(name: str, classe: str | None) -> tuple[str, str | None]:
    """(tipo, codigo) from a fact the statement prints; anything else is 'outro'."""
    up = _unaccent(name).upper()
    m = _REGISTRY.search(up)
    if m:
        return REGISTRY_TIPO.get(m.group(1), "outro"), m.group(2)
    m = _BACEN.match(up)
    if m:
        return "tesouro", BACEN_TITLE[m.group(1)]
    if classe == "Fundo de Investimento":
        return "fundo", None
    first = up.split()[0].rstrip("*") if up.split() else ""
    if classe == "Renda Variável" and _TICKER.match(first):
        return "outro", first
    return "outro", None


def _position_from_row(row: Row, period_end: dt.date, line_no: int, detail: list[DetailRow], diag: Diagnostics) -> Position:
    tipo, codigo = _type_row(row.name, row.classe)
    d = _join_detail(row, detail)
    vencimento = taxa = None
    qtd = preco = None
    implicit = False
    if d is not None:
        diag.detail_joined += 1
        vencimento, taxa, qtd = d.vencimento, d.taxa, d.quantidade
        if tipo == "fundo" and qtd:
            preco, implicit = (row.valor / qtd).quantize(Decimal("0.00000001")), True
        elif d.preco is not None:
            preco = d.preco
    if tipo == "tesouro" and codigo and vencimento:
        codigo = f"{codigo} {vencimento.isoformat()}"
    return Position(
        line_no=line_no,
        source_row=line_no,
        linha_extrato=row.name,
        tipo=tipo,
        codigo=codigo,
        quantidade=qtd,
        preco_unitario=preco,
        valor=row.valor,
        data_posicao=period_end,
        vencimento=vencimento,
        taxa_texto=taxa,
        estrategia_corretora=row.estrategia,
        classe_corretora=row.classe,
        preco_implicito=implicit,
    )


def _join_detail(row: Row, detail: list[DetailRow]) -> DetailRow | None:
    skey = key(row.estrategia or "")
    cands = [d for d in detail if not d.used and d.saldo_bruto is not None and abs(d.saldo_bruto - row.valor) <= CENT and (d.strategy_key in (None, skey))]
    if len(cands) == 1:
        cands[0].used = True
        return cands[0]
    if len(cands) > 1:
        rk = key(row.name)
        scored = []
        for d in cands:
            dk = key(d.name)
            n = 0
            while n < min(len(rk), len(dk)) and rk[n] == dk[n]:
                n += 1
            scored.append((n, d))
        scored.sort(key=lambda x: -x[0])
        if scored[0][0] >= 6 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
            scored[0][1].used = True
            return scored[0][1]
    return None


def _run_checks(diag, sec: _Section, leaves, sum_leaves, sum_all, bruto, saldo_final, n_rows):
    checks: list[tuple[str, bool, Decimal | None]] = []

    def check(name: str, expected: Decimal, actual: Decimal, rows: int) -> None:
        gap = actual - expected
        ok = abs(gap) <= CENT * max(rows, 1)
        checks.append((name, ok, None if ok else gap))

    by_strat: dict[tuple[str, str], list[Position]] = {}
    for p in leaves:
        by_strat.setdefault((p.classe_corretora or "?", p.estrategia_corretora or "?"), []).append(p)
    for (cls, strat), sub in sec.strategy_subtotal.items():
        group = by_strat.get((cls, strat), [])
        check(f"folhas x subtotal da estratégia {cls}/{strat}", sub, sum((p.valor for p in group), Decimal("0")), len(group))
    classes_with_strat = {c for c, _ in sec.strategy_subtotal}
    for cls, total in sec.class_subtotal.items():
        if cls in classes_with_strat:
            subs = [v for (c, _), v in sec.strategy_subtotal.items() if c == cls]
            check(f"subtotais das estratégias x total da classe {cls}", total, sum(subs, Decimal("0")), len(subs))
        else:
            group = [p for p in leaves if p.classe_corretora == cls]
            check(f"folhas x total da classe {cls}", total, sum((p.valor for p in group), Decimal("0")), len(group))
    if sec.total is not None:
        check("folhas x 'Total' da posição consolidada", sec.total, sum_leaves, len(leaves))
    if bruto is not None:
        check("folhas + conta corrente x Patrimônio bruto", bruto, sum_all, n_rows)
    elif saldo_final is not None:
        check("folhas + conta corrente x Saldo Bruto final", saldo_final, sum_all, n_rows)
    diag.checks = checks
    return checks


# ---------------------------------------------------------------------------
# Public readers and the local runner.
# ---------------------------------------------------------------------------


def read_pdf_statement_bytes(data: bytes) -> tuple[Statement, Diagnostics]:
    pages, extractor = extract_pages(data)
    return parse_pdf_pages(pages, extractor, raw_words(data) if extractor == "poppler" else frozenset())


def read_pdf_statement(path: str | Path) -> Statement:
    """Read, mask and reconcile one BTG performance report. The file is read into memory once."""
    stmt, _ = read_pdf_statement_with_diagnostics(path)
    return stmt


def read_pdf_statement_with_diagnostics(path: str | Path) -> tuple[Statement, Diagnostics]:
    return read_pdf_statement_bytes(Path(path).read_bytes())


def _fmt(d: Decimal) -> str:
    return f"{d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def describe(stmt: Statement, diag: Diagnostics) -> list[str]:
    """Aggregate, masked lines only: counts, subtotals, checks, coverage. No name, account, CPF or asset name."""
    ps = stmt.positions
    funds = [p for p in ps if p.tipo == "fundo"]
    out = [
        f"data da posição: {stmt.position_date.isoformat()}; páginas: {diag.pages}; extrator: {diag.extractor}; "
        f"páginas em duas colunas: {diag.two_column_pages}",
        f"posições: {len(ps)} (por tipo: {dict(sorted(Counter(p.tipo for p in ps).items()))}); "
        f"total das linhas R$ {_fmt(stmt.sum_of_lines)}; total declarado R$ {_fmt(stmt.stated_total)}",
        "linhas não lidas: 0",
    ]
    for (cls, strat), (n, tot) in sorted(diag.by_strategy.items()):
        out.append(f"  {cls} / {strat}: {n} posições, subtotal R$ {_fmt(tot)}")
    for name, ok, gap in diag.checks:
        out.append(f"  verificação [{'ok' if ok else 'FALHOU'}] {name}" + (f" (diferença R$ {_fmt(gap)})" if gap is not None else ""))
    n = len(ps) or 1
    out.append(
        "cobertura: "
        f"codigo {sum(1 for p in ps if p.codigo)}/{len(ps)}; vencimento {sum(1 for p in ps if p.vencimento)}/{len(ps)}; "
        f"taxa_texto {sum(1 for p in ps if p.taxa_texto)}/{len(ps)}; "
        f"quantidade {sum(1 for p in ps if p.quantidade is not None)}/{len(ps)}; "
        f"cota implícita {sum(1 for p in funds if p.preco_implicito)}/{len(funds)} fundos"
    )
    out.append(
        f"nomes quebrados: prefixo {diag.wrapped_prefix}, cauda {diag.wrapped_tail}, ambíguos {diag.wrap_ambiguous}; "
        f"detalhamento: {diag.detail_rows} linhas, {diag.detail_joined} ligadas às posições, "
        f"{diag.detail_unmatched} sem posição, {diag.detail_lines_unread} linhas não lidas"
    )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Reads BTG performance PDFs and prints ONLY masked, aggregate output.")
    ap.add_argument("files", nargs="+", help="BTG 'Relatório de Performance' PDF(s)")
    ap.add_argument("--consolidate", action="store_true", help="consolidate the statements and describe the consolidated view")
    args = ap.parse_args(argv)
    from src.portfolio.consolidate import consolidate, describe_consolidated

    statements = []
    rc = 0
    for i, f in enumerate(args.files, start=1):
        print(f"== arquivo {i} ==")
        try:
            stmt, diag = read_pdf_statement_with_diagnostics(f)
        except (StatementFormatError, StatementTotalMismatch) as exc:
            print(f"ERRO: {exc}")
            rc = 2
            continue
        except OSError as exc:
            print(f"ERRO: arquivo não pôde ser aberto ({type(exc).__name__})")
            rc = 2
            continue
        statements.append(stmt)
        print("\n".join(describe(stmt, diag)))
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
