"""Parse B3's TradeInformationConsolidatedFile into b3_trade_consolidated.

The source and its quirks are in src/fetchers/b3_trade_consolidated_fetcher.py;
the table, the scope and the checks against COTAHIST are in migration 57.

Nothing is inferred. A cell B3 left empty stays NULL, a row that fails
validation is dropped and counted, and a file that does not say what we asked
for raises:

* a "Status do Arquivo" other than Final is not stored (NotFinal; the daily
  window fetches the session again);
* a row dated other than the requested session raises (a misdated file);
* a non-empty file with no FORWARD row at all raises. The segment held 18 to
  67 tickers on every session checked, so zero is a changed file, not a quiet
  day;
* EXCEPT a file with no CASH row either (Incomplete; skipped). B3's file for
  2025-08-13, a normal session (COTAHIST has 14,176 rows), is marked Final but
  carries only options, FINANCIAL and AGRIBUSINESS: the whole cash market is
  missing. That is B3 publishing part of a day, and nothing can be stored for
  it, but it is not a format change.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from src.parsers.b3_bdi import parse_number

logger = logging.getLogger(__name__)

TABLE = "b3_trade_consolidated"
# upsert_rows takes a COMMA-SEPARATED STRING, not a list (src/store/pg_client.py).
CONFLICT_COLS = "ticker,trade_date"
SOURCE = "b3_trade_consolidated_file"
# B3's segment for the fixed income ETFs. Every other segment of the file is
# in b3_cotahist already, or out of scope.
SEGMENTS: Tuple[str, ...] = ("FORWARD",)
FINAL = "Final"
# The cash equities segment. Its absence marks a file B3 published incomplete.
CASH = "CASH"

_STATUS_PREFIX = "status do arquivo:"
_COLUMNS = (
    "RptDt", "TckrSymb", "ISIN", "SgmtNm", "MinPric", "MaxPric", "TradAvrgPric",
    "LastPric", "OscnPctg", "AdjstdQt", "AdjstdQtTax", "RefPric", "TradQty",
    "FinInstrmQty", "NtlFinVol",
)
_PRICES = (
    ("min_price", "MinPric"), ("max_price", "MaxPric"),
    ("avg_price", "TradAvrgPric"), ("last_price", "LastPric"),
)


class B3TradeConsolidatedParseError(RuntimeError):
    """The file is not the shape the contract describes."""


class B3TradeConsolidatedIncomplete(RuntimeError):
    """B3's file is marked Final but carries no cash-market segment at all."""


class B3TradeConsolidatedNotFinal(RuntimeError):
    """B3 has not marked the session's file Final yet."""


def decode(payload: bytes) -> str:
    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        return payload.decode("latin-1")


def _int(raw: str) -> Optional[int]:
    value = parse_number(raw)
    if value is None:
        return None
    if value != value.to_integral_value():
        raise ValueError(f"{raw!r} is not a whole number")
    return int(value)


def parse(text: str, session: date) -> Tuple[List[Dict[str, Any]], int]:
    """Rows of SEGMENTS for ``session``, and how many rows were dropped.

    Raises NotFinal, or ParseError for a file that is not what was asked for.
    """
    lines = [line for line in text.lstrip("﻿").splitlines() if line.strip()]
    if not lines or not lines[0].strip().lower().startswith(_STATUS_PREFIX):
        raise B3TradeConsolidatedParseError(
            f"{session}: no 'Status do Arquivo' line; first line {lines[:1]!r}"
        )
    status = lines[0].split(":", 1)[1].strip()
    if status != FINAL:
        raise B3TradeConsolidatedNotFinal(f"{session}: file status is {status!r}, not {FINAL!r}")

    header = [h.strip() for h in lines[1].split(";")] if len(lines) > 1 else []
    missing = [c for c in _COLUMNS if c not in header]
    if missing:
        raise B3TradeConsolidatedParseError(f"{session}: header lacks {missing}; got {header}")
    ix = {c: header.index(c) for c in _COLUMNS}
    width = max(ix.values()) + 1

    rows: List[Dict[str, Any]] = []
    dropped = 0
    has_cash = False
    for line in lines[2:]:
        cells = line.split(";")
        if len(cells) < width:
            dropped += 1
            continue
        segment = cells[ix["SgmtNm"]].strip()
        has_cash = has_cash or segment == CASH
        if segment not in SEGMENTS:
            continue
        try:
            trade_date = datetime.strptime(cells[ix["RptDt"]].strip(), "%Y-%m-%d").date()
        except ValueError:
            dropped += 1
            continue
        if trade_date != session:
            raise B3TradeConsolidatedParseError(
                f"{session}: the file carries a row dated {trade_date}"
            )
        ticker = cells[ix["TckrSymb"]].strip()
        isin = cells[ix["ISIN"]].strip() or None
        try:
            row: Dict[str, Any] = {
                "trade_date": trade_date,
                "ticker": ticker,
                "isin": isin,
                "segment": segment,
                "oscillation_pct": parse_number(cells[ix["OscnPctg"]]),
                "adjusted_qty": parse_number(cells[ix["AdjstdQt"]]),
                "adjusted_qty_tax": parse_number(cells[ix["AdjstdQtTax"]]),
                "ref_price": parse_number(cells[ix["RefPric"]]),
                "trade_count": _int(cells[ix["TradQty"]]),
                "quantity": _int(cells[ix["FinInstrmQty"]]),
                "notional_brl": parse_number(cells[ix["NtlFinVol"]]),
                "file_status": status,
                "source": SOURCE,
            }
            for column, label in _PRICES:
                row[column] = parse_number(cells[ix[label]])
        except ValueError as exc:
            logger.debug("b3_trade_consolidated row dropped (%s): %s", ticker, exc)
            dropped += 1
            continue
        if not _valid(row):
            dropped += 1
            continue
        rows.append(row)

    if not rows and not has_cash:
        raise B3TradeConsolidatedIncomplete(
            f"{session}: B3's file is marked {status!r} but has no CASH or "
            f"{'/'.join(SEGMENTS)} row ({len(lines) - 2} data lines): the cash "
            f"market is missing from B3's file"
        )
    if not rows:
        raise B3TradeConsolidatedParseError(
            f"{session}: the file has no usable {'/'.join(SEGMENTS)} row "
            f"({len(lines) - 2} data lines, {dropped} dropped)"
        )
    return rows, dropped


def _valid(row: Dict[str, Any]) -> bool:
    """Drop, never coerce: a key that is not a ticker, or a negative or zero
    price, quantity or count, is not stored."""
    ticker = row["ticker"]
    if not ticker or len(ticker) > 12 or not ticker.isalnum():
        return False
    if row["isin"] is not None and len(row["isin"]) != 12:
        return False
    for column, _ in _PRICES:
        if row[column] is not None and row[column] <= 0:
            return False
    for column in ("trade_count", "quantity", "notional_brl"):
        if row[column] is not None and row[column] < 0:
            return False
    return True
