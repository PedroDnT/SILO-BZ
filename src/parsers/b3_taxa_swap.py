"""B3 reference rates (TaxaSwap.txt) → `b3_reference_rate` rows.

Fixed-width, 72 characters per row, one row per (curve, vertex). Layout,
0-based slices, measured on 2008-01-02, 2017-01-02 and 2026-09-25 (unchanged):

    [0:6]    record id                [6:9]   complement   [9:11] record type
    [11:19]  generation date YYYYMMDD [19:21] curve-file code ('T1')
    [21:26]  curve code ('PRE', 'DOC', 'DIC' …, left-justified)
    [26:41]  curve description        [41:46] calendar days  [46:51] business days
    [51]     sign '+'/'-'             [52:66] rate × 10^7
    [66]     vertex type: F fixed, M moving
    [67:72]  vertex code

What the curves are, from B3's Manual de Curvas (v21, 2025-12-12) and the
file itself. Only the configured curves are kept; the rest of the file (116
curves in 2026) is skipped, not stored.

* PRE, "DIxPRE" (§2.1): % a.a. on 252 business days, rounded to the 3rd
  decimal. Vertex 1 is the day's CDI; every DI1 maturity is a vertex at that
  contract's settlement rate (checked 2026-09-25); between them flat-forward
  252; AFTER THE LAST DI1 MATURITY the last segment's forward is EXTENDED, so
  the long vertices (out to ~34 years in 2026) are B3's extrapolation, not
  contract prices.
* DOC, "DIxXDOL Cupom l" (§4.5): the clean onshore dollar coupon from DDI
  futures, a LINEAR rate on 360 calendar days (factor 1 + r·DC/36000),
  rounded to the 2nd decimal; extrapolated beyond the last DDI maturity.
* DPL, "Cupom Limpo de" (§3.2): the IPCA CLEAN coupon (real rate, 252
  basis, 2 decimals) from DAP futures settlements, falling back to ANBIMA's
  NTN-B indicative rates; B3 defines implied inflation as
  (1 + PRE) / (1 + DPL) - 1 and fills non-DAP vertices flat-forward 252.
  Its short end leans on the IPCA preview for the current month, so it is
  read from one year out. Chosen over DIC ("DI X IPCA", §3.1), which is the
  DIRTY coupon from the median of a POLL of informants and steps with the
  IPCA release calendar (9.85 at 362 days, 9.63 at 399, on 2026-09-25).

Files before 2005 use other layouts (65 characters in 2001, 67 in 2003,
measured) and are refused by the length check below, as they should be.

A row that is not 72 characters, a date that is not the file's session, or a
(curve, calendar days) pair seen twice raises: that is a layout change, and
guessing a layout is how a wrong number gets stored under the right name.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Sequence, Tuple

from src.parsers.validation import DataValidator

logger = logging.getLogger(__name__)

TABLE = "b3_reference_rate"
CONFLICT = ("curve", "trade_date", "calendar_days")
DEFAULT_CURVES: Tuple[str, ...] = ("PRE", "DOC", "DPL")
LINE_LENGTH = 72

_validator = DataValidator()


class TaxaSwapFormatError(ValueError):
    """The file is not the documented 72-character layout."""


class TaxaSwapStaleFile(TaxaSwapFormatError):
    """B3 served an earlier session's file under this date: no curve was
    generated that day. Measured: TS101224 and TS101231 are the 2010-12-23 and
    2010-12-30 files, every PRE/DOC/DPL vertex identical. Nothing is stored
    under the requested date; the earlier session keeps its own rows."""


def _line_dates(text: str, wanted: set) -> set:
    """The generation date of every line of the ``wanted`` curves (None if unreadable)."""
    dates = set()
    for line in text.splitlines():
        if len(line) == LINE_LENGTH and line[21:26].strip() in wanted:
            try:
                dates.add(datetime.strptime(line[11:19], "%Y%m%d").date())
            except ValueError:
                dates.add(None)
    return dates


def _valid(row: Dict[str, Any]) -> bool:
    errors, _ = _validator.validate_record(
        row, ["trade_date", "curve", "calendar_days", "business_days", "rate"], {"trade_date": "date"}
    )
    if errors:
        return False
    # A vertex has positive tenors and never more business than calendar days.
    # The rate bound is a PARSE sanity check, not a plausibility filter: B3
    # publishes 1- and 2-day DOC vertices of several hundred percent (a
    # one-day onshore dollar coupon annualised linearly — measured +430.3 on
    # 2026-09-14 and -332.3 on 2026-09-21). Those are the published numbers
    # and are kept; research reads DOC at 30 days and beyond.
    if row["calendar_days"] <= 0 or row["business_days"] < 0:
        return False
    if row["business_days"] > row["calendar_days"]:
        return False
    return Decimal("-1000") < row["rate"] < Decimal("1000")


def parse_taxa_swap(
    text: str,
    *,
    session: date,
    curves: Sequence[str] = DEFAULT_CURVES,
    origin: str = "",
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Rows for ``curves`` on ``session``; ``(rows, counts)`` as in the price report."""
    wanted = set(curves)
    rows: List[Dict[str, Any]] = []
    seen: set = set()
    present: set = set()
    counts = {"kept": 0, "dropped_invalid": 0, "lines": 0}

    for n, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        counts["lines"] += 1
        if len(line) != LINE_LENGTH:
            raise TaxaSwapFormatError(f"{origin} line {n}: {len(line)} characters, expected {LINE_LENGTH}")
        curve = line[21:26].strip()
        if curve not in wanted:
            continue
        present.add(curve)
        try:
            generated = datetime.strptime(line[11:19], "%Y%m%d").date()
            calendar_days = int(line[41:46])
            business_days = int(line[46:51])
            sign = line[51]
            magnitude = int(line[52:66])
        except ValueError as exc:
            raise TaxaSwapFormatError(f"{origin} line {n}: unreadable fixed-width field ({exc})") from exc
        if sign not in "+-":
            raise TaxaSwapFormatError(f"{origin} line {n}: sign {sign!r}")
        if generated != session:
            # One earlier date on every line is B3 republishing that session's
            # file; any other mismatch is a broken file.
            if generated < session and _line_dates(text, wanted) == {generated}:
                raise TaxaSwapStaleFile(
                    f"{origin}: every {'/'.join(sorted(wanted))} line is dated {generated}; "
                    f"B3 republished that file under {session}")
            raise TaxaSwapFormatError(f"{origin} line {n}: dated {generated}, file is {session}")
        key = (curve, calendar_days)
        if key in seen:
            raise TaxaSwapFormatError(f"{origin}: {curve} vertex {calendar_days} appears twice")
        seen.add(key)

        rate = Decimal(magnitude).scaleb(-7)
        row = {
            "trade_date": generated,
            "curve": curve,
            "curve_desc": line[26:41].strip(),
            "calendar_days": calendar_days,
            "business_days": business_days,
            "rate": -rate if sign == "-" else rate,
            "vertex_type": line[66],
            "vertex_code": line[67:72],
        }
        if row["vertex_type"] not in ("F", "M") or not _valid(row):
            counts["dropped_invalid"] += 1
            continue
        rows.append(row)

    if counts["lines"] == 0:
        raise TaxaSwapFormatError(f"{origin}: empty TaxaSwap.txt")
    missing = wanted - present
    if missing:
        # A configured curve absent from a session's file is a source change,
        # not an empty day: the file itself was published.
        raise TaxaSwapFormatError(f"{origin}: curve(s) {sorted(missing)} not in the file")
    unusable = wanted - {r["curve"] for r in rows}
    if unusable:
        raise TaxaSwapFormatError(f"{origin}: every vertex of {sorted(unusable)} failed validation")
    counts["kept"] = len(rows)
    if counts["dropped_invalid"]:
        logger.warning("TaxaSwap %s: dropped %d invalid vertices", origin, counts["dropped_invalid"])
    return rows, counts
