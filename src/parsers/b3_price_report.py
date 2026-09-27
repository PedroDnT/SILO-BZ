"""B3 Price Report (BVBG.086.01) → `b3_futures_settlement` rows.

One `<PricRpt>` per instrument per session (~59k on 2026-09-25, most of them
options). Only OUTRIGHT futures of the configured roots are kept (default
DI1): the ticker must be root + one B3 month letter + two digits. Strategy
and spread tickers of the same root are dropped and counted. The ticker is
the natural key and is never decomposed here (docs/planning/INSTRUMENTS.md):
maturity and business days are research-layer arithmetic, not landing data.

Values are stored AS PUBLISHED. For DI1 the price fields (FrstPric …
LastPric, BestBid/Ask, trade limits) are RATES in % a.a., because that is how
DI1 is quoted; AdjstdQt is the settlement PU and AdjstdQtTax the settlement
rate. A contract that did not trade has no TradDtls and no prices, but still
carries settlement and open interest (measured on 2018-01-02, DI1N24): those
prices stay NULL, never 0.

Measured field set (2026-09-25, DI1F27): TradDt/Dt, SctyId/TckrSymb,
FinInstrmId/OthrId/Id, TradDtls/TradQty and FinInstrmAttrbts/{MktDataStrmId,
NtlFinVol, IntlFinVol, OpnIntrst, FinInstrmQty, BestBidPric, BestAskPric,
FrstPric, MinPric, MaxPric, TradAvrgPric, LastPric, RglrTxsQty,
RglrTraddCtrcts, NtlRglrVol, IntlRglrVol, AdjstdQt, AdjstdQtTax,
AdjstdQtStin, PrvsAdjstdQt, PrvsAdjstdQtTax, PrvsAdjstdQtStin, OscnPctg,
VartnPts, AdjstdValCtrct, MaxTradLmt, MinTradLmt}. Every leaf is kept in
`raw`; the typed columns are the subset research reads.
"""

from __future__ import annotations

import io
import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.parsers.validation import DataValidator

logger = logging.getLogger(__name__)

TABLE = "b3_futures_settlement"
CONFLICT = ("trade_date", "ticker")
DEFAULT_ROOTS: Tuple[str, ...] = ("DI1",)

_MONTH_LETTERS = "FGHJKMNQUVXZ"
_validator = DataValidator()

# FinInstrmAttrbts leaf → typed column. Anything else stays in raw only.
_ATTR_COLUMNS = {
    "OpnIntrst": "open_interest",
    "FinInstrmQty": "contracts",
    "NtlFinVol": "notional_brl",
    "FrstPric": "open_px",
    "MinPric": "low_px",
    "MaxPric": "high_px",
    "TradAvrgPric": "avg_px",
    "LastPric": "close_px",
    "BestBidPric": "best_bid",
    "BestAskPric": "best_ask",
    "AdjstdQt": "settlement_price",
    "AdjstdQtTax": "settlement_rate",
    "AdjstdQtStin": "settlement_status",
    "PrvsAdjstdQt": "prev_settlement_price",
    "PrvsAdjstdQtTax": "prev_settlement_rate",
    "PrvsAdjstdQtStin": "prev_settlement_status",
    "VartnPts": "variation_points",
    "AdjstdValCtrct": "settlement_value_per_contract",
}
_INT_COLUMNS = {"open_interest", "contracts", "trades"}
_TEXT_COLUMNS = {"settlement_status", "prev_settlement_status"}


class PriceReportFormatError(ValueError):
    """The XML is not the documented BVBG.086.01 shape."""


def outright_pattern(roots: Sequence[str]) -> re.Pattern:
    alt = "|".join(re.escape(r) for r in roots)
    return re.compile(rf"^(?:{alt})[{_MONTH_LETTERS}][0-9]{{2}}$")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _number(text: Optional[str], column: str) -> Any:
    if text is None or not text.strip():
        return None
    try:
        value = Decimal(text.strip())
    except InvalidOperation as exc:
        raise PriceReportFormatError(f"{column}: non-numeric {text!r}") from exc
    return int(value) if column in _INT_COLUMNS else value


def _created_at(head: bytes) -> Optional[datetime]:
    m = re.search(rb"<CreDtAndTm>([^<]+)</CreDtAndTm>", head)
    return datetime.fromisoformat(m.group(1).decode()) if m else None


def _valid(row: Dict[str, Any]) -> bool:
    errors, _ = _validator.validate_record(
        row, ["trade_date", "ticker", "settlement_price"], {"trade_date": "date"}
    )
    if errors:
        return False
    # Impossible values: a PU is positive; a DI rate outside (-5, 100) % is
    # not a DI rate. Dropped and counted, never clipped.
    if row["settlement_price"] <= 0:
        return False
    for col in ("settlement_rate", "prev_settlement_rate", "open_px", "low_px", "high_px", "close_px"):
        v = row.get(col)
        if v is not None and not (Decimal("-5") < v < Decimal("100")):
            return False
    for col in ("open_interest", "contracts", "trades"):
        v = row.get(col)
        if v is not None and v < 0:
            return False
    return True


def parse_price_report(
    xml: bytes,
    *,
    session: date,
    roots: Sequence[str] = DEFAULT_ROOTS,
    origin: str = "",
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Rows for the outright futures of ``roots`` on ``session``.

    Returns ``(rows, counts)`` where counts has ``kept``, ``dropped_invalid``
    (failed validation) and ``dropped_non_outright`` (same root, not an
    outright ticker). A row dated anything but ``session`` raises: the file
    answered a different day than the one asked for. A ticker repeated within
    the file raises too — the natural key must be unique at the source.
    """
    outright = outright_pattern(roots)
    created = _created_at(xml[:16_384])
    rows: List[Dict[str, Any]] = []
    seen: set = set()
    counts = {"kept": 0, "dropped_invalid": 0, "dropped_non_outright": 0}
    reports = 0

    for _event, elem in ET.iterparse(io.BytesIO(xml), events=("end",)):
        if _local(elem.tag) != "PricRpt":
            continue
        reports += 1
        leaves = {_local(e.tag): (e.text or "").strip() for e in elem.iter() if len(e) == 0}
        ticker = leaves.get("TckrSymb", "")
        elem.clear()
        if not any(ticker.startswith(r) for r in roots):
            continue
        if not outright.match(ticker):
            counts["dropped_non_outright"] += 1
            continue
        dt_text = leaves.get("Dt")
        if not dt_text:
            raise PriceReportFormatError(f"{origin}: {ticker} has no TradDt")
        trade_date = date.fromisoformat(dt_text)
        if trade_date != session:
            raise PriceReportFormatError(f"{origin}: {ticker} dated {trade_date}, file is {session}")
        if ticker in seen:
            raise PriceReportFormatError(f"{origin}: {ticker} appears twice")
        seen.add(ticker)

        row: Dict[str, Any] = {
            "trade_date": trade_date,
            "ticker": ticker,
            "instrument_id": int(leaves["Id"]) if leaves.get("Id") else None,
            "trades": _number(leaves.get("TradQty"), "trades"),
            "report_created_at": created,
        }
        for leaf, column in _ATTR_COLUMNS.items():
            text = leaves.get(leaf)
            row[column] = (text or None) if column in _TEXT_COLUMNS else _number(text, column)
        row["raw"] = {k: v for k, v in leaves.items() if v}
        if not _valid(row):
            counts["dropped_invalid"] += 1
            logger.debug("price report %s: dropped %s", origin, ticker)
            continue
        rows.append(row)

    if reports == 0:
        raise PriceReportFormatError(f"{origin}: no PricRpt element — not a BVBG.086.01 file")
    counts["kept"] = len(rows)
    if counts["dropped_invalid"]:
        logger.warning("price report %s: dropped %d invalid rows", origin, counts["dropped_invalid"])
    return rows, counts

