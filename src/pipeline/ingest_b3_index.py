"""Ingest B3's published index levels into b3_index_level (#412).

The source grid and its quirks are in src/fetchers/b3_index_fetcher.py; the
table, and why levels are stored as published, are in migration 55. This module
parses a year's grid, marks the divisor steps and refuses what it cannot
explain, then upserts.

Nothing here is inferred. A cell is stored when B3 published a number for that
session, and a cell that is not a positive number raises: the format was
verified clean over 14,489 cells, so a change is B3 drifting, not noise to drop.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Tuple

from src.pipeline.ingest_b3_events import _parse_decimal

logger = logging.getLogger(__name__)

TABLE = "b3_index_level"
# upsert_rows takes a COMMA-SEPARATED STRING, not a list (src/store/pg_client.py).
CONFLICT_COLS = "index_code,trade_date"
SOURCE = "b3_index_statistics"

# The indices SILO ingests, and the first year B3 publishes for each. A year
# before it answers results=null, which is an error for a configured index.
# Every one is a TOTAL-RETURN index by B3's own pages and Manual (Feb 2023,
# section 1.2: dividends reinvested); none on this endpoint is a price-return
# version. The eight added by #416 were checked on 2026-10-03 against B3's base
# values (all), its daily bulletin (IBXX, IBXL, IFIX) and IBOV's session dates
# (docs/reference/research/index-candidates-416.md). FIRST_YEAR is the year of
# each one's first served session (IBXX 1994-12-29, IBXL 1997-12-30, SMLL
# 2005-08-31, IFIX 2010-12-30, IDIV and UTIL 2005-12-29, ICON 2006-12-28, IMOB
# 2007-12-28). Levels before an index's publication date are B3's own
# back-calculation and the endpoint does not mark them.
# IEEX (first served 1994-01-03) is deliberately NOT here: it moved +70% on
# 1999-03-15 and -29% on 1999-03-31 with no divisor step and nothing in B3's
# methodology history to explain it, so it stays held until that is sourced.
INDEX_CODES: Tuple[str, ...] = (
    "IBOV", "IBXX", "IBXL", "IFIX", "SMLL", "IDIV", "ICON", "IMOB", "UTIL",
)
FIRST_YEAR: Dict[str, int] = {
    "IBOV": 1968,
    "IBXX": 1994,
    "IBXL": 1997,
    "IFIX": 2010,
    "SMLL": 2005,
    "IDIV": 2005,
    "ICON": 2006,
    "IMOB": 2007,
    "UTIL": 2005,
}

# The sessions on which B3 re-scaled a series, with the divisor. The published
# history is not adjusted across them, so the level ratio on these days is not
# a return. Found on 2026-09-30 in the full IBOV 1968-2026 series: 11 sessions
# whose level is about 1/10 (1/100 on 1983-10-04) of the session before. Each
# is checked against its divisor on every ingest, and any OTHER one-session move
# beyond a factor of two raises, so a new step is reviewed and added here, never
# served as a return. 1991-02-04 (+36%) is a real move, not a step.
INDEX_DIVISOR_STEPS: Dict[str, Dict[date, int]] = {
    "IBOV": {
        date(1983, 10, 4): 100,
        date(1985, 12, 3): 10,
        date(1988, 8, 30): 10,
        date(1989, 4, 18): 10,
        date(1990, 1, 15): 10,
        date(1991, 5, 29): 10,
        date(1992, 1, 22): 10,
        date(1993, 1, 27): 10,
        date(1993, 8, 30): 10,
        date(1994, 2, 10): 10,
        date(1997, 3, 3): 10,
    },
}

# A listed step must show a level ratio within these bounds of 1/divisor: the
# real market move on the same day is at most a few percent (1.4% to 10.6%
# measured), so this catches a wrong date or a wrong divisor, not noise.
_STEP_RATIO_LOW, _STEP_RATIO_HIGH = 0.6, 1.6
# Beyond this one-session ratio (either way) a move must be a listed step.
_UNEXPLAINED_LOW, _UNEXPLAINED_HIGH = 0.5, 2.0


def year_may_be_empty(year: int, today: date) -> bool:
    """True when B3 may legitimately have no grid for ``year`` yet.

    Only the current year, and only in the first days of January, before its
    first session. Any other null is an error.
    """
    return year == today.year and today.month == 1 and today.day <= 10


def parse_year(index_code: str, year: int, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Turn one year's grid into records, one per published session.

    Null and empty cells are days with no session and are skipped. A value on
    a date that does not exist, or a value that is not a positive number,
    raises: nothing is coerced or dropped.
    """
    results = payload.get("results")
    if results is None:
        raise ValueError(f"{index_code} {year}: results is null")
    records: List[Dict[str, Any]] = []
    for row in results:
        day = row.get("day")
        if not isinstance(day, int) or not 1 <= day <= 31:
            continue
        for month in range(1, 13):
            cell = row.get(f"rateValue{month}")
            if cell is None or (isinstance(cell, str) and not cell.strip()):
                continue
            try:
                session = date(year, month, day)
            except ValueError:
                raise ValueError(
                    f"{index_code} {year}: B3 published {cell!r} on the "
                    f"non-existent date {year}-{month:02d}-{day:02d}"
                ) from None
            level = _parse_decimal(cell)
            if level is None or level <= 0:
                raise ValueError(
                    f"{index_code} {session}: {cell!r} is not a positive level"
                )
            records.append(
                {
                    "index_code": index_code,
                    "trade_date": session,
                    "level": level,
                    "divisor_step": False,
                    "source": SOURCE,
                }
            )
    return records


def mark_divisor_steps(index_code: str, records: List[Dict[str, Any]]) -> None:
    """Flag the listed steps in place, and refuse any move nothing explains.

    ``records`` is the index's whole ingested series. Raises when a listed step
    inside the span has no session, when a listed step's level ratio is not
    about 1/divisor, or when an unlisted one-session move is beyond a factor of
    two either way.
    """
    steps = INDEX_DIVISOR_STEPS.get(index_code, {})
    records.sort(key=lambda r: r["trade_date"])
    if not records:
        return
    observed = {r["trade_date"] for r in records}
    first, last = records[0]["trade_date"], records[-1]["trade_date"]
    for step_date in steps:
        if first <= step_date <= last and step_date not in observed:
            raise ValueError(
                f"{index_code}: the listed divisor step {step_date} has no "
                "published session"
            )
    previous: Decimal | None = None
    for record in records:
        session = record["trade_date"]
        divisor = steps.get(session)
        record["divisor_step"] = divisor is not None
        if previous is not None:
            ratio = float(record["level"] / previous)
            if divisor is not None:
                expected = 1.0 / divisor
                if not _STEP_RATIO_LOW * expected <= ratio <= _STEP_RATIO_HIGH * expected:
                    raise ValueError(
                        f"{index_code} {session}: listed as a divisor-{divisor} "
                        f"step but the level ratio is {ratio:.4f}"
                    )
            elif ratio < _UNEXPLAINED_LOW or ratio > _UNEXPLAINED_HIGH:
                raise ValueError(
                    f"{index_code} {session}: the level moved by a factor of "
                    f"{ratio:.4f} in one session and it is not a listed divisor "
                    "step. Check B3's methodology and add it to "
                    "INDEX_DIVISOR_STEPS (src/pipeline/ingest_b3_index.py) "
                    "before serving it"
                )
        previous = record["level"]


def ingest_b3_index_levels(conn: Any, records: List[Dict[str, Any]]) -> int:
    """Upsert parsed levels. Returns the number of rows processed."""
    if not records:
        return 0
    from src.store.pg_client import upsert_rows

    return upsert_rows(conn, TABLE, records, CONFLICT_COLS)
