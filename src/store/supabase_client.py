"""
Postgres client wrapper for bulk upsert operations (Neon-backed).

Requires:
  POSTGRES_URL — postgresql://user:pass@<neon-host>/db?sslmode=require
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras
from psycopg2.extras import Json

logger = logging.getLogger(__name__)

_DEFAULT_CHUNK_SIZE = 500
_RETRY_DELAYS = (5, 10, 20, 40)


def _norm_key(k: str) -> str:
    """Lowercase + strip underscores — collapses CSV header variants like
    'VL_TOTAL' / 'vl_total' / 'VlTotal' to a single canonical form."""
    return k.lower().replace("_", "")


def _strip_raw_duplicates(rows: List[Dict[str, Any]]) -> None:
    """Mutate `rows` in place: for each row that has a `raw` JSONB dict, drop
    any key whose case- and underscore-normalised form matches a sibling typed
    column. This eliminates the redundancy where every typed column has an
    identical copy inside raw (e.g. cvm_fi_diario row carrying both `vl_total`
    typed and `VL_TOTAL` in raw). Source-specific keys that don't collide
    (e.g. `TAB_IV_A_VL_PL`) are preserved for audit/re-mapping.

    Also drops common CNPJ-bearing keys when a `cnpj` / `cnpj_securit` typed
    column exists, since those are normalised at the typed level."""
    if not rows:
        return
    sample = rows[0]
    if "raw" not in sample:
        return
    typed_norm = {_norm_key(c) for c in sample.keys() if c != "raw"}
    has_cnpj_col = any(c in sample for c in ("cnpj", "cnpj_securit"))
    for row in rows:
        raw = row.get("raw")
        if not isinstance(raw, dict):
            continue
        kept: Dict[str, Any] = {}
        for k, v in raw.items():
            n = _norm_key(k)
            if n in typed_norm:
                continue
            if has_cnpj_col and "cnpj" in n:
                continue
            kept[k] = v
        # Keep as empty dict (not None) — several tables declare `raw JSONB NOT NULL`.
        row["raw"] = kept


def _get_upsert_chunk_size() -> int:
    raw = os.getenv("CVM_UPSERT_CHUNK_SIZE", str(_DEFAULT_CHUNK_SIZE)).strip()
    try:
        chunk_size = int(raw)
    except ValueError:
        logger.warning(
            "Invalid CVM_UPSERT_CHUNK_SIZE=%r; using default %d",
            raw,
            _DEFAULT_CHUNK_SIZE,
        )
        return _DEFAULT_CHUNK_SIZE
    if chunk_size < 1:
        logger.warning(
            "Non-positive CVM_UPSERT_CHUNK_SIZE=%r; using default %d",
            raw,
            _DEFAULT_CHUNK_SIZE,
        )
        return _DEFAULT_CHUNK_SIZE
    return chunk_size


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


def get_pg_client() -> Any:
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

    _strip_raw_duplicates(rows)

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
    chunk_size = _get_upsert_chunk_size()

    total = 0
    def _adapt(v):
        if isinstance(v, (dict, list)):
            return Json(v)
        return v

    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        values = [tuple(_adapt(r.get(c)) for c in cols) for r in chunk]
        last_exc: Optional[Exception] = None
        chunk_started = time.monotonic()

        for attempt, delay in enumerate((0, *_RETRY_DELAYS)):
            if delay:
                logger.warning(
                    "upsert retry in %ds (table=%s chunk_offset=%d chunk_size=%d attempt=%d): %s",
                    delay, table, i, len(chunk), attempt, last_exc,
                )
                time.sleep(delay)
                client.reconnect()
            try:
                with client.cursor() as cur:
                    psycopg2.extras.execute_values(
                        cur, sql, values, page_size=chunk_size
                    )
                total += len(chunk)
                logger.debug(
                    "upsert ok table=%s chunk_offset=%d rows=%d elapsed=%.2fs",
                    table,
                    i,
                    len(chunk),
                    time.monotonic() - chunk_started,
                )
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
                        "Upsert failed table=%s chunk_offset=%d chunk_size=%d elapsed=%.2fs: %s",
                        table,
                        i,
                        len(chunk),
                        time.monotonic() - chunk_started,
                        exc,
                    )
                    raise

        if last_exc is not None:
            logger.error(
                "Upsert exhausted retries table=%s chunk_offset=%d chunk_size=%d elapsed=%.2fs: %s",
                table,
                i,
                len(chunk),
                time.monotonic() - chunk_started,
                last_exc,
            )
            raise last_exc

    return total
