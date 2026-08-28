"""Ingest published B3 corporate events into b3_corporate_event.

The events themselves (what they are, why they are not turned into an
adjustment factor here) are documented in
src/store/migrations/26_b3_corporate_event.sql and in the fetcher. This module
only parses B3's field formats and upserts.

Formats, all as B3 publishes them:
  dates    dd/mm/yyyy, with sentinels 01/01/1900 and 31/12/9999 for "unknown"
           and "never" — both are stored as NULL rather than as a date nobody
           means literally.
  numbers  Brazilian decimal comma, thousands dot: "5,00000000000".
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TABLE = "b3_corporate_event"
# upsert_rows takes a COMMA-SEPARATED STRING, not a list (src/store/pg_client.py:230).
# Passing a list makes its dedup key iterate the characters of the string.
CONFLICT_COLS = "isin,label,last_date_prior,approved_on,factor,rate"

# B3 uses these as "no date": a subscription with tradingPeriod
# "01/01/1900 a 01/01/1900" and subscriptionDate "31/12/9999" is not a
# subscription happening in the year 9999.
_DATE_SENTINELS = {date(1900, 1, 1), date(9999, 12, 31)}


def _parse_date(value: Any) -> Optional[date]:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
        return None if parsed in _DATE_SENTINELS else parsed
    return None


def _parse_decimal(value: Any) -> Optional[Decimal]:
    """Brazilian number → Decimal. Returns None on anything unparseable.

    Never coerces to zero: a factor that cannot be read is unknown, and an
    unknown factor written as 0 would look like a real (and catastrophic)
    corporate action.
    """
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(".", "").replace(",", ".")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def parse_events(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Turn fetcher rows into upsertable records.

    A row without an ISIN cannot be joined to the tape and cannot be keyed, so
    it is dropped and counted rather than stored under a synthesised id.
    """
    records: List[Dict[str, Any]] = []
    dropped = 0
    for row in rows:
        isin = (row.get("isin") or "").strip().upper()
        label = (row.get("label") or "").strip().upper()
        if not isin or not label:
            dropped += 1
            continue
        records.append(
            {
                "issuing_company": (row.get("issuing_company") or "").strip().upper(),
                "isin": isin,
                "event_class": row["event_class"],
                "label": label,
                "last_date_prior": _parse_date(row.get("last_date_prior")),
                "approved_on": _parse_date(row.get("approved_on")),
                "factor": _parse_decimal(row.get("factor")),
                "rate": _parse_decimal(row.get("rate")),
                "payment_date": _parse_date(row.get("payment_date")),
                "raw": row.get("raw") or {},
                "source": "b3_listed_companies",
            }
        )
    if dropped:
        logger.warning("dropped %d B3 event rows with no ISIN or label", dropped)
    return records


def ingest_b3_corporate_events(conn: Any, rows: List[Dict[str, Any]]) -> int:
    """Upsert parsed corporate events. Returns the number of rows written."""
    records = parse_events(rows)
    if not records:
        return 0
    from src.store.pg_client import upsert_rows

    return upsert_rows(conn, TABLE, records, CONFLICT_COLS)
