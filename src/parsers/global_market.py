"""U.S. Treasury, Cboe and EIA files → `mkt_series` rows.

One long shape for every non-Brazilian daily series:
``{source, series_id, observation_date, value, unit}``. A cell the source left
empty is not a row (null stays absent, never 0). A header we do not know
raises: Treasury adds tenors over time (``1.5 Month`` and ``4 Mo`` appear in
2026 and not in 2008, measured), and a silently skipped new column is a
series that quietly never lands.

Contracts measured 2026-09-26:

* Treasury "Daily Treasury Par Yield Curve Rates", one CSV per year:
  ``Date,"1 Mo",…,"30 Yr"``, dates MM/DD/YYYY, newest first, values in %.
* Cboe ``VIX_History.csv``: ``DATE,OPEN,HIGH,LOW,CLOSE``, MM/DD/YYYY,
  1990-01-02 onward, index points.
* EIA API v2 ``petroleum/pri/spt/data`` for series ``RBRTE`` (Europe Brent
  Spot Price FOB): JSON ``response.data[]`` with ``period`` (YYYY-MM-DD),
  ``series``, ``value`` (a string) and ``units`` (``$/BBL``).
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Tuple

from src.parsers.validation import DataValidator

logger = logging.getLogger(__name__)

TABLE = "mkt_series"
CONFLICT = ("source", "series_id", "observation_date")

SOURCE_TREASURY = "us_treasury"
SOURCE_CBOE = "cboe"
SOURCE_EIA = "eia"

# Treasury CSV header → series_id. Every header ever seen goes here; an
# unknown one raises (see module docstring).
TREASURY_TENORS: Dict[str, str] = {
    "1 Mo": "UST_PAR_1M",
    "1.5 Month": "UST_PAR_6W",
    "2 Mo": "UST_PAR_2M",
    "3 Mo": "UST_PAR_3M",
    "4 Mo": "UST_PAR_4M",
    "6 Mo": "UST_PAR_6M",
    "1 Yr": "UST_PAR_1Y",
    "2 Yr": "UST_PAR_2Y",
    "3 Yr": "UST_PAR_3Y",
    "5 Yr": "UST_PAR_5Y",
    "7 Yr": "UST_PAR_7Y",
    "10 Yr": "UST_PAR_10Y",
    "20 Yr": "UST_PAR_20Y",
    "30 Yr": "UST_PAR_30Y",
}
CBOE_VIX_COLUMNS: Dict[str, str] = {
    "OPEN": "VIX_OPEN", "HIGH": "VIX_HIGH", "LOW": "VIX_LOW", "CLOSE": "VIX_CLOSE",
}
EIA_BRENT = "RBRTE"
EIA_BRENT_SERIES_ID = "BRENT_SPOT_FOB"

# Plausibility bounds per unit. A value outside is dropped and counted.
_BOUNDS = {
    "pct": (Decimal("-5"), Decimal("30")),
    "index_pts": (Decimal("0"), Decimal("200")),
    "usd_per_bbl": (Decimal("0"), Decimal("1000")),
}

_validator = DataValidator()


class MarketFormatError(ValueError):
    """The file is not the documented shape."""


def _us_date(text: str, origin: str) -> date:
    try:
        return datetime.strptime(text.strip(), "%m/%d/%Y").date()
    except ValueError as exc:
        raise MarketFormatError(f"{origin}: unreadable date {text!r}") from exc


def _decimal(text: Any, origin: str) -> Any:
    if text is None or str(text).strip() in ("", "N/A", "NA", "."):
        return None
    try:
        return Decimal(str(text).strip())
    except InvalidOperation as exc:
        raise MarketFormatError(f"{origin}: non-numeric value {text!r}") from exc


def _keep(row: Dict[str, Any]) -> bool:
    errors, _ = _validator.validate_record(
        row, ["source", "series_id", "observation_date", "value"], {"observation_date": "date"}
    )
    if errors:
        return False
    # Open intervals: VIX and Brent must be strictly positive; yields may be
    # slightly negative (short bills, 2020).
    lo, hi = _BOUNDS[row["unit"]]
    return lo < row["value"] < hi


def _finish(rows: Iterable[Dict[str, Any]], origin: str) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    kept: List[Dict[str, Any]] = []
    seen: set = set()
    dropped = 0
    for row in rows:
        key = (row["series_id"], row["observation_date"])
        if key in seen:
            raise MarketFormatError(f"{origin}: {key} appears twice")
        seen.add(key)
        if _keep(row):
            kept.append(row)
        else:
            dropped += 1
    if dropped:
        logger.warning("%s: dropped %d implausible observations", origin, dropped)
    return kept, {"kept": len(kept), "dropped_invalid": dropped}


def parse_treasury_par_csv(text: str, *, origin: str = "treasury") -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    try:
        header = next(reader)
    except StopIteration:
        raise MarketFormatError(f"{origin}: empty file")
    if not header or header[0].strip() != "Date":
        raise MarketFormatError(f"{origin}: first column is {header[:1]}, expected Date")
    unknown = [h for h in header[1:] if h.strip() not in TREASURY_TENORS]
    if unknown:
        raise MarketFormatError(f"{origin}: unknown Treasury column(s) {unknown}")
    tenors = [TREASURY_TENORS[h.strip()] for h in header[1:]]

    def rows():
        for rec in reader:
            if not rec or not rec[0].strip():
                continue
            if len(rec) != len(header):
                raise MarketFormatError(f"{origin}: row {rec[:1]} has {len(rec)} fields, header {len(header)}")
            obs = _us_date(rec[0], origin)
            for series_id, cell in zip(tenors, rec[1:]):
                value = _decimal(cell, origin)
                if value is None:
                    continue
                yield {"source": SOURCE_TREASURY, "series_id": series_id,
                       "observation_date": obs, "value": value, "unit": "pct"}

    return _finish(rows(), origin)


def parse_cboe_vix_csv(text: str, *, origin: str = "cboe") -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    header = [h.strip().upper() for h in next(reader, [])]
    if header != ["DATE", *CBOE_VIX_COLUMNS]:
        raise MarketFormatError(f"{origin}: header {header}, expected DATE,OPEN,HIGH,LOW,CLOSE")

    def rows():
        for rec in reader:
            if not rec or not rec[0].strip():
                continue
            obs = _us_date(rec[0], origin)
            for column, cell in zip(CBOE_VIX_COLUMNS.values(), rec[1:]):
                value = _decimal(cell, origin)
                if value is None:
                    continue
                yield {"source": SOURCE_CBOE, "series_id": column,
                       "observation_date": obs, "value": value, "unit": "index_pts"}

    return _finish(rows(), origin)


def parse_eia_spot(records: List[Dict[str, Any]], *, origin: str = "eia") -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    def rows():
        for rec in records:
            if rec.get("series") != EIA_BRENT:
                raise MarketFormatError(f"{origin}: series {rec.get('series')!r}, asked for {EIA_BRENT}")
            if rec.get("units") != "$/BBL":
                raise MarketFormatError(f"{origin}: units {rec.get('units')!r}, expected $/BBL")
            value = _decimal(rec.get("value"), origin)
            if value is None:
                continue
            try:
                obs = date.fromisoformat(str(rec.get("period")))
            except ValueError as exc:
                raise MarketFormatError(f"{origin}: unreadable period {rec.get('period')!r}") from exc
            yield {"source": SOURCE_EIA, "series_id": EIA_BRENT_SERIES_ID,
                   "observation_date": obs, "value": value, "unit": "usd_per_bbl"}

    return _finish(rows(), origin)
