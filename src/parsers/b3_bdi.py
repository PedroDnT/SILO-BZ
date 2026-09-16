"""Parsers for B3's BDI CSV exports (securities lending, investor flow, instruments).

These are not plain CSVs. Every export carries 1-3 preamble lines (a prose
description, sometimes a `Glossário;<url>` line, sometimes a caption that is
the only place the reference date appears), then a blank line, then — for two
of the tables — a *banded* header row above the real one, then the data.

NOTHING HERE IS POSITIONAL. Header rows, column indices and the doador/tomador
rate bands are all DISCOVERED from published labels, for the reason
`anbima_pipeline`'s docstring spells out: a hardcoded offset does not fail
loudly when the source reflows, it keeps reading some *other* column and
stores it under the right-looking name. A row we cannot interpret is dropped
and counted, or raises — never guessed at.

Layout facts this encodes (all verified against live 2026-09-10 exports):

* `BTBLendingOpenPosition` publishes, for every (date, ticker, tipo), BOTH the
  per-market rows AND a `Mercado = 'Total'` row that is exactly their sum
  (verified: 1036/1036 groups). Summing the table without filtering therefore
  double-counts every short balance. We keep every published row (rule 3) and
  carry an explicit `is_total` flag so no consumer can get it wrong by
  accident; the analytical layer reads `is_total` rows only.
* `BTBLoanBalance` repeats the trio `Mínima; Média ponderada; Máxima` twice —
  once for the lender (doador) and once for the borrower (tomador). The ONLY
  thing that distinguishes them is the band row above the header. Without the
  band we would have to assume an order, and silently swapping lender and
  borrower rates is exactly the kind of plausible-looking wrong number this
  repo forbids — so a missing band raises.
* `SharesInvesVolum` is month-to-date cumulative with a T+2 lag: the export
  requested for 2026-09-10 is captioned "até o dia 08/09/2026". The caption is
  the reference date; the request date is NOT. Keying on the request date
  would smear two different snapshots onto one day and invent a flow.
* `SharesInvesVolumMonthly` names its month in Portuguese and without a year
  ("mês anterior (Agosto)"). The year comes from the request date; the month
  name is then cross-checked against it, and a mismatch raises rather than
  filing August's numbers under September.

Money is stored in the unit B3 publishes it in, named accordingly
(`*_brl_mil` for the daily investor table, `*_brl` elsewhere), and rates in
percentage points (40,00% -> 40.00), matching `anbima_class_monthly`.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from src.parsers.validation import DataValidator

logger = logging.getLogger(__name__)

SOURCE = "b3_bdi"

# Landing tables + their named UNIQUE keys (migration 39). Kept beside the
# parsers so a new column can never drift away from the conflict target.
TABLE_OPEN_POSITION = "b3_lending_open_position"
CONFLICT_OPEN_POSITION = ("trade_date", "codneg", "tipo_emprestimo", "mercado")

TABLE_LENDING_RATE = "b3_lending_rate"
CONFLICT_LENDING_RATE = ("trade_date", "codneg", "mercado")

TABLE_INVESTOR = "b3_investor_participation"
CONFLICT_INVESTOR = ("reference_date", "investor_type")

TABLE_INVESTOR_MONTHLY = "b3_investor_participation_monthly"
CONFLICT_INVESTOR_MONTHLY = ("reference_month", "investor_type", "market")

TABLE_INDEX_PORTFOLIO = "b3_index_portfolio"
CONFLICT_INDEX_PORTFOLIO = ("reference_date", "index_code", "codneg")

TABLE_INSTRUMENT = "b3_instrument_registry"
CONFLICT_INSTRUMENT = ("reference_date", "instrumento")

TOTAL_MERCADO = "Total"

_MTD_CAPTION = re.compile(r"at[ée]\s+o\s+dia\s+(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
_MONTH_CAPTION = re.compile(r"\(([A-Za-zÀ-ÿ]+)\)")

_PT_MONTHS = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}

_validator = DataValidator()


class B3BdiParseError(RuntimeError):
    """The export could not be interpreted — layout drift, or a missing band."""


# ── primitives ────────────────────────────────────────────────────────────


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", _strip_accents(str(text)).strip().lower())


def split_lines(text: str) -> List[List[str]]:
    """Every non-empty line of the export, split on ';'. BOM already gone."""
    return [line.split(";") for line in text.lstrip("﻿").splitlines() if line.strip()]


def find_header(rows: Sequence[Sequence[str]], labels: Iterable[str]) -> int:
    """Index of the first row carrying every label. Raises if there is none."""
    wanted = [_norm(l) for l in labels]
    for i, row in enumerate(rows):
        cells = [_norm(c) for c in row]
        if all(w in cells for w in wanted):
            return i
    raise B3BdiParseError(
        f"no header row carrying {list(labels)!r}; first rows: {[r[:6] for r in rows[:6]]!r}"
    )


def column_index(header: Sequence[str], label: str) -> int:
    target = _norm(label)
    for i, cell in enumerate(header):
        if _norm(cell) == target:
            return i
    raise B3BdiParseError(f"column {label!r} not in header {list(header)!r}")


def parse_number(value: Any) -> Optional[Decimal]:
    """pt-BR numeric ('1.234,56', '40,00%', '', '-') -> Decimal or None."""
    if value is None:
        return None
    text = str(value).strip().replace("%", "").replace("\xa0", "")
    if text in {"", "-", "--"}:
        return None
    text = text.replace(".", "").replace(",", ".")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def parse_date(value: Any) -> Optional[date]:
    """'dd/mm/yyyy' (or 'dd/mm/yy', as the index proxy sends) -> date or None."""
    if value is None:
        return None
    text = str(value).strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _validated(row: Dict[str, Any], required: Sequence[str], field_types: Dict[str, str]) -> bool:
    errors, _ = _validator.validate_record(row, list(required), field_types)
    if errors:
        logger.debug("b3_bdi row dropped: %s", "; ".join(str(e) for e in errors))
    return not errors


def _row_envelope(header: Sequence[str], cells: Sequence[str]) -> Dict[str, str]:
    """The published row, verbatim, for the `raw` column (provenance rule 3)."""
    return {str(h).strip(): (cells[i].strip() if i < len(cells) else "") for i, h in enumerate(header) if str(h).strip()}


def reconcile_span(
    rows: Sequence[Dict[str, Any]], field: str, requested: Sequence[date]
) -> Tuple[List[date], List[date]]:
    """Which requested sessions the export actually delivered, and which it did not.

    B3 answers an over-wide range with HTTP 200 and a silently truncated
    window (a 2024→2026 request came back with 18 sessions). A 200 is not
    evidence the span arrived, so every ingest reconciles and records the
    shortfall instead of believing it has history it does not have.
    """
    got = {r[field] for r in rows if r.get(field)}
    delivered = sorted(d for d in requested if d in got)
    missing = sorted(d for d in requested if d not in got)
    return delivered, missing


# ── BTBLendingOpenPosition ────────────────────────────────────────────────

_OPEN_POSITION_LABELS = ("Data", "Código IF", "Mercado", "Saldo em quantidade do ativo")


def parse_lending_open_position(text: str, *, origin: str = "") -> List[Dict[str, Any]]:
    rows = split_lines(text)
    hi = find_header(rows, _OPEN_POSITION_LABELS)
    header = rows[hi]
    ix = {name: column_index(header, label) for name, label in (
        ("trade_date", "Data"),
        ("codneg", "Código IF"),
        ("isin", "Código ISIN"),
        ("empresa", "Empresa ou fundo"),
        ("tipo_emprestimo", "Tipo de empréstimo"),
        ("mercado", "Mercado"),
        ("saldo_quantidade", "Saldo em quantidade do ativo"),
        ("preco_medio", "Preço médio"),
        ("saldo_brl", "Saldo em R$"),
    )}

    out: List[Dict[str, Any]] = []
    dropped = 0
    for cells in rows[hi + 1:]:
        if len(cells) <= ix["saldo_brl"]:
            dropped += 1
            continue
        trade_date = parse_date(cells[ix["trade_date"]])
        codneg = cells[ix["codneg"]].strip()
        mercado = cells[ix["mercado"]].strip()
        row = {
            "trade_date": trade_date,
            "codneg": codneg,
            "isin": cells[ix["isin"]].strip() or None,
            "empresa": cells[ix["empresa"]].strip() or None,
            "tipo_emprestimo": cells[ix["tipo_emprestimo"]].strip(),
            "mercado": mercado,
            "is_total": mercado == TOTAL_MERCADO,
            "saldo_quantidade": parse_number(cells[ix["saldo_quantidade"]]),
            "preco_medio": parse_number(cells[ix["preco_medio"]]),
            "saldo_brl": parse_number(cells[ix["saldo_brl"]]),
            "source": SOURCE,
            "raw": _row_envelope(header, cells),
        }
        if not _validated(row, ("trade_date", "codneg", "mercado"), {"trade_date": "date"}):
            dropped += 1
            continue
        out.append(row)

    if dropped:
        logger.warning("B3 lending open position%s: dropped %d unreadable rows",
                       f" ({origin})" if origin else "", dropped)
    if not out:
        raise B3BdiParseError(f"lending open position export{f' ({origin})' if origin else ''} had no usable rows")
    return out


# ── BTBLoanBalance ────────────────────────────────────────────────────────

_RATE_TRIO = ("Mínima", "Média ponderada", "Máxima")
_LOAN_BALANCE_LABELS = ("Data", "Código IF", "Mercado", "Quantidade de ativos")


def _rate_bands(rows: Sequence[Sequence[str]], hi: int, header: Sequence[str]) -> Dict[str, int]:
    """Column where each rate trio starts, taken from the band row above the header.

    `Mínima / Média ponderada / Máxima` appears twice and is identical both
    times; the band is B3's only published statement of which trio is the
    lender's and which is the borrower's. No band -> raise, because the
    fallback (assume an order) would swap doador and tomador invisibly.
    """
    if hi == 0:
        raise B3BdiParseError("BTBLoanBalance header has no band row above it")
    band = rows[hi - 1]
    starts: Dict[str, int] = {}
    for i, cell in enumerate(band):
        n = _norm(cell)
        if "doador" in n:
            starts["doador"] = i
        elif "tomador" in n:
            starts["tomador"] = i
    if set(starts) != {"doador", "tomador"}:
        raise B3BdiParseError(
            f"BTBLoanBalance band row names {sorted(starts)} — expected doador and tomador: {list(band)!r}"
        )
    for side, start in starts.items():
        got = [_norm(header[start + k]) if start + k < len(header) else "" for k in range(3)]
        if got != [_norm(x) for x in _RATE_TRIO]:
            raise B3BdiParseError(
                f"BTBLoanBalance {side} band at column {start} is over {got!r}, expected {list(_RATE_TRIO)!r}"
            )
    return starts


def parse_lending_rate(text: str, *, origin: str = "") -> List[Dict[str, Any]]:
    rows = split_lines(text)
    hi = find_header(rows, _LOAN_BALANCE_LABELS)
    header = rows[hi]
    bands = _rate_bands(rows, hi, header)
    ix = {name: column_index(header, label) for name, label in (
        ("trade_date", "Data"),
        ("codneg", "Código IF"),
        ("isin", "Código ISIN"),
        ("empresa", "Empresa ou fundo"),
        ("mercado", "Mercado"),
        ("num_contratos", "Número de contratos"),
        ("quantidade", "Quantidade de ativos"),
        ("valor_brl", "Valor em R$"),
    )}
    d0, t0 = bands["doador"], bands["tomador"]
    last = max(max(ix.values()), d0 + 2, t0 + 2)

    out: List[Dict[str, Any]] = []
    dropped = 0
    for cells in rows[hi + 1:]:
        if len(cells) <= last:
            dropped += 1
            continue
        contratos = parse_number(cells[ix["num_contratos"]])
        row = {
            "trade_date": parse_date(cells[ix["trade_date"]]),
            "codneg": cells[ix["codneg"]].strip(),
            "isin": cells[ix["isin"]].strip() or None,
            "empresa": cells[ix["empresa"]].strip() or None,
            "mercado": cells[ix["mercado"]].strip(),
            "num_contratos": int(contratos) if contratos is not None else None,
            "quantidade": parse_number(cells[ix["quantidade"]]),
            "valor_brl": parse_number(cells[ix["valor_brl"]]),
            "taxa_doador_min": parse_number(cells[d0]),
            "taxa_doador_media": parse_number(cells[d0 + 1]),
            "taxa_doador_max": parse_number(cells[d0 + 2]),
            "taxa_tomador_min": parse_number(cells[t0]),
            "taxa_tomador_media": parse_number(cells[t0 + 1]),
            "taxa_tomador_max": parse_number(cells[t0 + 2]),
            "source": SOURCE,
            "raw": _row_envelope(header, cells),
        }
        if not _validated(row, ("trade_date", "codneg", "mercado"), {"trade_date": "date"}):
            dropped += 1
            continue
        out.append(row)

    if dropped:
        logger.warning("B3 lending rate%s: dropped %d unreadable rows",
                       f" ({origin})" if origin else "", dropped)
    if not out:
        raise B3BdiParseError(f"lending rate export{f' ({origin})' if origin else ''} had no usable rows")
    return out


# ── SharesInvesVolum (daily, month-to-date) ───────────────────────────────

_INVESTOR_LABELS = ("Tipos de investidores", "Compras (R$) mil", "Vendas (R$) mil")


def mtd_reference_date(text: str) -> date:
    """The 'até o dia DD/MM/YYYY' caption — the snapshot's real date.

    B3 publishes this table with a T+2 lag, so the request date is always
    ahead of the data. Raises when the caption is absent: filing an MTD
    snapshot under the wrong day would manufacture a one-day flow out of two
    identical numbers.
    """
    m = _MTD_CAPTION.search(text)
    if not m:
        raise B3BdiParseError(
            "SharesInvesVolum export carries no 'até o dia DD/MM/YYYY' caption — "
            "cannot date the snapshot"
        )
    ref = parse_date(m.group(1))
    if ref is None:
        raise B3BdiParseError(f"SharesInvesVolum caption date {m.group(1)!r} does not parse")
    return ref


def parse_investor_participation(text: str, *, origin: str = "") -> List[Dict[str, Any]]:
    reference_date = mtd_reference_date(text)
    rows = split_lines(text)
    hi = find_header(rows, _INVESTOR_LABELS)
    header = rows[hi]
    i_type = column_index(header, "Tipos de investidores")
    i_buy = column_index(header, "Compras (R$) mil")
    i_sell = column_index(header, "Vendas (R$) mil")
    # The two "Participação (%)" columns are positional by construction: each
    # follows its own value column. That is the published layout, not a guess.
    out: List[Dict[str, Any]] = []
    for cells in rows[hi + 1:]:
        if len(cells) <= i_sell:
            continue
        investor_type = cells[i_type].strip()
        if not investor_type:
            continue
        row = {
            "reference_date": reference_date,
            "investor_type": investor_type,
            "compras_brl_mil": parse_number(cells[i_buy]),
            "compras_participacao_pct": parse_number(cells[i_buy + 1]) if i_buy + 1 < len(cells) else None,
            "vendas_brl_mil": parse_number(cells[i_sell]),
            "vendas_participacao_pct": parse_number(cells[i_sell + 1]) if i_sell + 1 < len(cells) else None,
            "source": SOURCE,
            "raw": _row_envelope(header, cells),
        }
        if not _validated(row, ("reference_date", "investor_type"), {"reference_date": "date"}):
            continue
        out.append(row)

    if not out:
        raise B3BdiParseError(f"investor participation export{f' ({origin})' if origin else ''} had no usable rows")
    return out


# ── SharesInvesVolumMonthly ───────────────────────────────────────────────


def monthly_reference_month(text: str, *, request_date: date) -> date:
    """First day of the month the export describes ('mês anterior (Agosto)').

    The caption names the month but never the year, so the year comes from
    the request date — and the caption is then checked against it. A mismatch
    raises: silently filing one month's numbers under another is precisely
    the fabrication rule 1 forbids.
    """
    year, month = (request_date.year, request_date.month - 1) if request_date.month > 1 else (request_date.year - 1, 12)
    expected = date(year, month, 1)
    m = _MONTH_CAPTION.search(text)
    if not m:
        raise B3BdiParseError("SharesInvesVolumMonthly export carries no '(Mês)' caption")
    named = _PT_MONTHS.get(_norm(m.group(1)))
    if named is None:
        raise B3BdiParseError(f"SharesInvesVolumMonthly caption month {m.group(1)!r} is not a Portuguese month")
    if named != expected.month:
        raise B3BdiParseError(
            f"SharesInvesVolumMonthly caption says {m.group(1)!r} (month {named}) but the export was "
            f"requested for {request_date.isoformat()}, whose previous month is {expected.month}"
        )
    return expected


def parse_investor_participation_monthly(
    text: str, *, request_date: date, origin: str = ""
) -> List[Dict[str, Any]]:
    reference_month = monthly_reference_month(text, request_date=request_date)
    rows = split_lines(text)
    hi = find_header(rows, ("Tipos de investidores",))
    header = rows[hi]
    if hi == 0:
        raise B3BdiParseError("SharesInvesVolumMonthly header has no market band row above it")
    band = rows[hi - 1]
    # Band cell -> the market its (R$, %) pair describes. Empty band cells
    # belong to the market named to their left, so carry it forward.
    markets: Dict[int, str] = {}
    current = ""
    for i, cell in enumerate(band):
        name = cell.strip()
        if name:
            current = name
        markets[i] = current

    i_type = column_index(header, "Tipos de investidores")
    out: List[Dict[str, Any]] = []
    for cells in rows[hi + 1:]:
        investor_type = cells[i_type].strip() if len(cells) > i_type else ""
        if not investor_type:
            continue
        for i, cell in enumerate(header):
            if _norm(cell) != "r$" or i >= len(cells):
                continue
            market = markets.get(i, "").strip()
            if not market:
                raise B3BdiParseError(f"SharesInvesVolumMonthly column {i} has no market in the band row")
            row = {
                "reference_month": reference_month,
                "investor_type": investor_type,
                "market": market,
                "valor_brl": parse_number(cells[i]),
                "participacao_pct": parse_number(cells[i + 1]) if i + 1 < len(cells) else None,
                "source": SOURCE,
                "raw": _row_envelope(header, cells),
            }
            if not _validated(row, ("reference_month", "investor_type", "market"),
                              {"reference_month": "date"}):
                continue
            out.append(row)

    if not out:
        raise B3BdiParseError(
            f"monthly investor participation export{f' ({origin})' if origin else ''} had no usable rows"
        )
    return out


# ── InstrumentsEquities ───────────────────────────────────────────────────

_INSTRUMENT_LABELS = ("Instrumento financeiro", "Categoria", "Capital social")
# The cash market is the whole universe a short monitor can speak about;
# EQUITY-DERIVATE is ~105k option series per day and belongs to nothing here.
CASH_MARKET = "EQUITY-CASH"


def parse_instrument_registry(
    text: str, *, reference_date: date, origin: str = ""
) -> List[Dict[str, Any]]:
    rows = split_lines(text)
    hi = find_header(rows, _INSTRUMENT_LABELS)
    header = rows[hi]
    ix = {name: column_index(header, label) for name, label in (
        ("instrumento", "Instrumento financeiro"),
        ("ativo", "Ativo"),
        ("descricao", "Descrição do ativo"),
        ("segmento", "Segmento"),
        ("mercado", "Mercado"),
        ("categoria", "Categoria"),
        ("isin", "Código ISIN"),
        ("nome_instituicao", "Nome da instituição"),
        ("capital_social", "Capital social"),
        ("nivel_governanca", "Nível de governança corporativa"),
    )}
    last = max(ix.values())

    out: List[Dict[str, Any]] = []
    for cells in rows[hi + 1:]:
        if len(cells) <= last:
            continue
        if cells[ix["mercado"]].strip().upper() != CASH_MARKET:
            continue
        row = {
            "reference_date": reference_date,
            "instrumento": cells[ix["instrumento"]].strip(),
            "ativo": cells[ix["ativo"]].strip() or None,
            "descricao": cells[ix["descricao"]].strip() or None,
            "segmento": cells[ix["segmento"]].strip() or None,
            "mercado": cells[ix["mercado"]].strip() or None,
            "categoria": cells[ix["categoria"]].strip() or None,
            "isin": cells[ix["isin"]].strip() or None,
            "nome_instituicao": cells[ix["nome_instituicao"]].strip() or None,
            "capital_social": parse_number(cells[ix["capital_social"]]),
            "nivel_governanca": cells[ix["nivel_governanca"]].strip() or None,
            "source": SOURCE,
            "raw": _row_envelope(header, cells),
        }
        if not _validated(row, ("reference_date", "instrumento"), {"reference_date": "date"}):
            continue
        out.append(row)

    if not out:
        raise B3BdiParseError(f"instrument registry export{f' ({origin})' if origin else ''} had no usable rows")
    return out


# ── index portfolio (JSON, not CSV) ───────────────────────────────────────


def parse_index_portfolio(records: Sequence[Dict[str, Any]], *, origin: str = "") -> List[Dict[str, Any]]:
    """Rows from B3BdiFetcher.fetch_index_portfolio into index-portfolio rows.

    `theoricalQty` is B3's free-float-adjusted share count for the index —
    the free float itself, not the share count — which is why the analytical
    layer prefers it and says so in `float_basis`.
    """
    out: List[Dict[str, Any]] = []
    for r in records:
        reference_date = parse_date(r.get("header_date"))
        codneg = str(r.get("cod") or "").strip()
        row = {
            "reference_date": reference_date,
            "index_code": str(r.get("index_code") or "").strip(),
            "codneg": codneg,
            "asset_name": (str(r.get("asset")).strip() or None) if r.get("asset") else None,
            "especificacao": (str(r.get("type")).strip() or None) if r.get("type") else None,
            "b3_sector": (str(r.get("segment")).strip() or None) if r.get("segment") else None,
            "participacao_pct": parse_number(r.get("part")),
            "theoretical_qty": parse_number(r.get("theoricalQty")),
            "source": SOURCE,
            "raw": {k: v for k, v in r.items() if k != "raw"},
        }
        if not _validated(row, ("reference_date", "index_code", "codneg"),
                          {"reference_date": "date"}):
            continue
        out.append(row)

    if not out:
        raise B3BdiParseError(f"index portfolio{f' ({origin})' if origin else ''} had no usable rows")
    return out


def batched(rows: Iterable[Dict[str, Any]], size: int) -> Iterator[List[Dict[str, Any]]]:
    batch: List[Dict[str, Any]] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
