"""Upsert helpers and the gap calendar for the B3 lending / investor-flow tables.

WHY THE GAP CALENDAR LIVES HERE
-------------------------------
Every other source in this repo can be healed by re-running a backfill. These
cannot: B3 keeps ~21 business days and then the session is gone for good
(see src/fetchers/b3_bdi_fetcher.py). So the daily run cannot simply fetch
"today" — it has to notice, on every run, which sessions inside the still-
retrievable window are missing from the landing table and claim them before
they age out. One skipped cron run is recoverable; two weeks of them are not.

"Missing" is decided against sessions WE ALREADY KNOW HAPPENED — the distinct
trade_dates in b3_cotahist — rather than against weekdays. Carnival and
Corpus Christi are weekdays on which B3 publishes nothing, and a calendar
built from weekdays would re-request them every single day forever while
reporting a permanent gap that does not exist. The tape is the session
calendar this warehouse owns; using it means a holiday is simply not a
session, which is the truth.

The newest days are always re-fetched regardless of what the table already
holds: B3 has published these tables as late as 15:00 (their own 2026-07-31
notice), so a run that catches a partially-published session must be able to
correct it the next day.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Sequence

from src.parsers import b3_bdi as P
from src.store.pg_client import upsert_rows

logger = logging.getLogger(__name__)

# B3's retention, in business days, with a little slack. Fetching a session
# that has already aged out is harmless (it comes back "Nenhum resultado" and
# is logged skipped); missing one that has not is permanent.
RETENTION_SESSIONS = 21

# The trailing sessions we re-fetch unconditionally, published-late insurance.
ALWAYS_REFRESH_SESSIONS = 2

# Ceiling on requests per run. The investor table needs one request per
# session, and B3 sits behind Cloudflare, which throttles bursts.
MAX_REQUESTS_PER_RUN = 30

_UPSERT_BATCH = 5000


def _upsert(conn: Any, table: str, conflict: Sequence[str], rows: List[Dict[str, Any]]) -> int:
    total = 0
    for batch in P.batched(rows, _UPSERT_BATCH):
        total += upsert_rows(conn, table, batch, conflict_columns=",".join(conflict))
    return total


def upsert_open_positions(conn: Any, rows: List[Dict[str, Any]]) -> int:
    return _upsert(conn, P.TABLE_OPEN_POSITION, P.CONFLICT_OPEN_POSITION, rows)


def upsert_lending_rates(conn: Any, rows: List[Dict[str, Any]]) -> int:
    return _upsert(conn, P.TABLE_LENDING_RATE, P.CONFLICT_LENDING_RATE, rows)


def upsert_investor_participation(conn: Any, rows: List[Dict[str, Any]]) -> int:
    return _upsert(conn, P.TABLE_INVESTOR, P.CONFLICT_INVESTOR, rows)


def upsert_investor_participation_monthly(conn: Any, rows: List[Dict[str, Any]]) -> int:
    return _upsert(conn, P.TABLE_INVESTOR_MONTHLY, P.CONFLICT_INVESTOR_MONTHLY, rows)


def upsert_index_portfolio(conn: Any, rows: List[Dict[str, Any]]) -> int:
    return _upsert(conn, P.TABLE_INDEX_PORTFOLIO, P.CONFLICT_INDEX_PORTFOLIO, rows)


def upsert_instrument_registry(conn: Any, rows: List[Dict[str, Any]]) -> int:
    return _upsert(conn, P.TABLE_INSTRUMENT, P.CONFLICT_INSTRUMENT, rows)


# ── the session calendar ──────────────────────────────────────────────────


def known_sessions(conn: Any, *, limit: int = RETENTION_SESSIONS) -> List[date]:
    """The most recent `limit` trading sessions, ascending, from our own tape."""
    sql = """
        SELECT trade_date FROM (
            SELECT DISTINCT trade_date
              FROM b3_cotahist
             WHERE tpmerc = '010'
             ORDER BY trade_date DESC
             LIMIT %s
        ) s ORDER BY trade_date
    """
    with conn.cursor() as cur:
        cur.execute(sql, (limit,))
        return [r[0] for r in cur.fetchall() if r and r[0]]


def _fallback_sessions(limit: int) -> List[date]:
    """Weekdays, used only when the tape is empty (a brand-new database).

    Deliberately crude: holidays will be requested once, come back
    "Nenhum resultado", and be logged skipped. That is the right trade on a
    cold start, where fetching a non-session costs one request and missing a
    real one costs it forever.
    """
    out: List[date] = []
    day = date.today()
    while len(out) < limit:
        if day.weekday() < 5:
            out.append(day)
        day -= timedelta(days=1)
    return sorted(out)


def sessions_to_fetch(
    conn: Any,
    table: str,
    date_column: str,
    *,
    limit: int = RETENTION_SESSIONS,
    always_refresh: int = ALWAYS_REFRESH_SESSIONS,
) -> List[date]:
    """Sessions inside the retention window this table is still missing.

    Always includes the newest `always_refresh` sessions, whether or not rows
    exist for them, so a session B3 published late is corrected rather than
    frozen half-written.
    """
    sessions = known_sessions(conn, limit=limit) or _fallback_sessions(limit)
    if not sessions:
        return []
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT DISTINCT {date_column} FROM {table} WHERE {date_column} >= %s",  # noqa: S608 - names are module constants
            (sessions[0],),
        )
        have = {r[0] for r in cur.fetchall() if r and r[0]}
    fresh = set(sessions[-always_refresh:]) if always_refresh else set()
    targets = sorted({s for s in sessions if s not in have} | fresh)
    if len(targets) > MAX_REQUESTS_PER_RUN:
        # Keep the newest: the oldest are the ones about to age out anyway,
        # and a run that never finishes claims nothing at all.
        targets = targets[-MAX_REQUESTS_PER_RUN:]
    return targets


def investor_request_dates(sessions: Sequence[date], missing: Sequence[date], *, lag: int = 2) -> List[date]:
    """Request dates that deliver each missing reference session.

    SharesInvesVolum is published T+2: the export requested on session i is
    captioned with session i-2. So to obtain reference session R we ask for
    the session `lag` places after it. Reference sessions whose delivering
    session has not happened yet are simply not requestable, and are left for
    a later run rather than requested against a date B3 cannot answer.
    """
    index = {s: i for i, s in enumerate(sessions)}
    out: List[date] = []
    for ref in missing:
        i = index.get(ref)
        if i is None or i + lag >= len(sessions):
            continue
        out.append(sessions[i + lag])
    return sorted(set(out))
