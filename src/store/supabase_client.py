"""
Postgres client wrapper for bulk upsert operations.

Requires:
  POSTGRES_URL — postgresql://user:pass@host/db?sslmode=require
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras
from psycopg2.extras import Json

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 500
_RETRY_DELAYS = (5, 10, 20, 40)


class _PgClient:
    """Thin wrapper around a psycopg2 connection that auto-reconnects."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._conn: Any = None
        self._connect()

    def _connect(self) -> None:
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:
            pass
        self._conn = psycopg2.connect(self._url)
        self._conn.autocommit = True

    def cursor(self):
        return self._conn.cursor()

    def reconnect(self) -> None:
        logger.warning("Reconnecting to Postgres...")
        self._connect()

    @property
    def url(self) -> str:
        return self._url


def get_supabase_client() -> Any:
    """Return an initialised Postgres client (psycopg2-backed)."""
    url = os.environ.get("POSTGRES_URL")
    if not url:
        raise EnvironmentError("POSTGRES_URL must be set")
    url = "".join(url.split())
    return _PgClient(url)


def upsert_rows(
    client: Any,
    table: str,
    rows: List[Dict[str, Any]],
    conflict_columns: Optional[str] = None,
) -> int:
    """
    Upsert rows into a Postgres table in chunks.

    When `conflict_columns` is set, rows with duplicate conflict-key tuples are
    deduplicated (last write wins) before chunking — same behaviour as the
    previous PostgREST client.

    Args:
        client:           _PgClient instance
        table:            table name
        rows:             list of dicts to upsert
        conflict_columns: comma-separated column names for ON CONFLICT

    Returns:
        Total number of rows processed.
    """
    if not rows:
        return 0

    if conflict_columns:
        keys = [c.strip() for c in conflict_columns.split(",") if c.strip()]
        seen: Dict[tuple, int] = {}
        deduped: List[Dict[str, Any]] = []
        for row in rows:
            key = tuple(row.get(k) for k in keys)
            if key in seen:
                deduped[seen[key]] = row  # last write wins
            else:
                seen[key] = len(deduped)
                deduped.append(row)
        if len(deduped) < len(rows):
            logger.info(
                "upsert dedup: table=%s conflict=%s collapsed %d -> %d rows",
                table, conflict_columns, len(rows), len(deduped),
            )
        rows = deduped

    cols = list(rows[0].keys())
    if conflict_columns:
        update_set = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols)
        conflict_clause = f"ON CONFLICT ({conflict_columns}) DO UPDATE SET {update_set}"
    else:
        conflict_clause = "ON CONFLICT DO NOTHING"

    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES %s {conflict_clause}"

    total = 0
    def _adapt(v):
        if isinstance(v, (dict, list)):
            return Json(v)
        return v

    for i in range(0, len(rows), _CHUNK_SIZE):
        chunk = rows[i : i + _CHUNK_SIZE]
        values = [tuple(_adapt(r.get(c)) for c in cols) for r in chunk]
        last_exc: Optional[Exception] = None

        for attempt, delay in enumerate((0, *_RETRY_DELAYS)):
            if delay:
                logger.warning(
                    "upsert retry in %ds (table=%s chunk=%d attempt=%d): %s",
                    delay, table, i, attempt, last_exc,
                )
                time.sleep(delay)
                client.reconnect()
            try:
                with client.cursor() as cur:
                    psycopg2.extras.execute_values(
                        cur, sql, values, page_size=_CHUNK_SIZE
                    )
                total += len(chunk)
                last_exc = None
                break
            except Exception as exc:
                msg = str(exc).lower()
                if any(
                    k in msg
                    for k in (
                        "connection",
                        "server closed",
                        "57014",
                        "statement timeout",
                        "canceling statement",
                    )
                ):
                    last_exc = exc
                else:
                    logger.error(
                        "Upsert failed table=%s chunk=%d: %s", table, i, exc
                    )
                    raise

        if last_exc is not None:
            logger.error(
                "Upsert exhausted retries table=%s chunk=%d: %s",
                table, i, last_exc,
            )
            raise last_exc

    return total
