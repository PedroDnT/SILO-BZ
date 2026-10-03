"""
Postgres client wrapper for bulk upsert operations (Supabase-backed).

Requires:
  POSTGRES_URL — postgresql://user:pass@<supabase-host>/db?sslmode=require
"""

import logging
import os
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Sequence

import psycopg2
import psycopg2.extras
import psycopg2.pool
from psycopg2.extras import Json

logger = logging.getLogger(__name__)

_DEFAULT_CHUNK_SIZE = 500
# See _get_pool_size() for why this is 4 and not max_connections.
_DEFAULT_POOL_SIZE = 4
_RETRY_DELAYS = (5, 10, 20, 40)

# libpq TCP keepalives. The ingest holds pooled connections idle for minutes
# (B3 corporate-events is one HTTP call per issuer — ~12 min of fetch before
# the upsert). Supabase's session pooler drops idle sockets well before the
# kernel default keepalive (2h), and the next write then hangs until
# `SSL SYSCALL error: EOF detected`. Probe after 30s idle so the pooler sees
# traffic and a dead peer is noticed in ~60s instead of ~15 min.
_KEEPALIVES = dict(
    keepalives=1,
    keepalives_idle=30,
    keepalives_interval=10,
    keepalives_count=3,
)

# Markers on psycopg2 errors that are safe to retry with a fresh connection.
# "connection" / "server closed" / statement_timeout were the original set;
# SSL SYSCALL EOF (run 33237536770, 2026-08-29) is the same class of death
# and was falling through to an immediate raise because none of those
# substrings appear in `SSL SYSCALL error: EOF detected`.
_TRANSIENT_DB_MARKERS = (
    "connection",
    "server closed",
    "57014",
    "statement timeout",
    "canceling statement",
    "ssl syscall",
    "eof detected",
    "ssl error",
    "broken pipe",
    "connection reset",
    "could not receive data",
    "could not send data",
    "terminating connection",
    "admin_shutdown",
    "crash shutdown",
    "57p01",
    "08006",
    "08003",
)


def _is_transient_db_error(exc: BaseException) -> bool:
    """True when the error is a dropped connection / cancelled statement."""
    msg = str(exc).lower()
    return any(marker in msg for marker in _TRANSIENT_DB_MARKERS)


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


def _get_pool_size() -> int:
    """How many Postgres connections the ingest may hold at once.

    Default 4, NOT the ~120 max_connections the server allows. The binding
    constraint is compute, not connection slots: the Supabase instance reports
    max_parallel_workers = 2 and max_worker_processes = 6 (a ~2 vCPU box), and
    the big writes go into single unpartitioned tables whose indexes every
    concurrent writer has to maintain. Past ~4 the writers mostly contend —
    on CPU, on the same B-tree pages, and on WAL — instead of adding
    throughput. Raise it only against a measured curve.
    """
    raw = os.getenv("CVM_DB_POOL_SIZE", str(_DEFAULT_POOL_SIZE)).strip()
    try:
        size = int(raw)
    except ValueError:
        logger.warning(
            "Invalid CVM_DB_POOL_SIZE=%r; using default %d", raw, _DEFAULT_POOL_SIZE
        )
        return _DEFAULT_POOL_SIZE
    if size < 1:
        logger.warning(
            "Non-positive CVM_DB_POOL_SIZE=%r; using default %d", raw, _DEFAULT_POOL_SIZE
        )
        return _DEFAULT_POOL_SIZE
    return size


class _PgClient:
    """Pooled Postgres client for the ingest pipeline.

    Was a single connection guarded by an RLock. That made every write in the
    run serial: correct, and enough to stop the blocking upserts starving the
    asyncio event loop (the 2026-08-27 balancete failures), but it capped
    throughput at one writer no matter how many slices were in flight.

    Now a ``ThreadedConnectionPool``. Combined with ``CVMIngestor._store``
    running each parse+upsert through ``asyncio.to_thread``, N slices write
    genuinely in parallel while the loop stays free.

    Two details worth keeping:

    * **A semaphore fronts the pool.** ``ThreadedConnectionPool.getconn()``
      *raises* ``PoolError`` when every connection is checked out rather than
      waiting. Callers here would rather wait — an ingest slice that dies
      because the pool was momentarily busy is a fabricated failure. The
      semaphore makes "pool full" mean "block", which is what the single-lock
      version did.
    * **A connection that errored is discarded, not returned.** psycopg2 hands
      back a connection in a failed state after an exception; putting it
      straight back would deal the same broken connection to the next caller.
      ``cursor()`` closes it instead and the pool opens a fresh one — which is
      what makes ``reconnect()`` unnecessary as a separate step (see below).
    """

    def __init__(self, url: str, pool_size: Optional[int] = None) -> None:
        self._url = url
        self._size = pool_size or _get_pool_size()
        # minconn=1: open one eagerly so a bad POSTGRES_URL fails at startup
        # rather than on the first slice, an hour into a backfill.
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            1, self._size, dsn=url, **_KEEPALIVES
        )
        self._slots = threading.Semaphore(self._size)
        logger.info("Postgres pool: %d connection(s)", self._size)

    @contextmanager
    def cursor(self):
        """Check a connection out of the pool and yield a cursor on it.

        Every caller uses ``with client.cursor() as cur:``, so the checkout is
        scoped exactly to the statements it serves. Holding it no longer than
        that is what keeps the pool from deadlocking under concurrency.
        """
        self._slots.acquire()
        conn = None
        broken = False
        try:
            conn = self._pool.getconn()
            # Idempotent and local — psycopg2 only touches the wire here if a
            # transaction is open, and the pool never hands one back mid-txn.
            conn.autocommit = True
            cur = conn.cursor()
            try:
                yield cur
            finally:
                try:
                    cur.close()
                except Exception:
                    # A cursor on an already-dead connection can raise on
                    # close. The connection is discarded below either way;
                    # masking the caller's real exception would be worse.
                    broken = True
        except Exception:
            broken = True
            raise
        finally:
            if conn is not None:
                try:
                    self._pool.putconn(conn, close=broken)
                except Exception:
                    logger.warning("failed returning a connection to the pool",
                                   exc_info=True)
            self._slots.release()

    def reconnect(self) -> None:
        """Retained for the upsert retry path; now close to a no-op.

        With one shared connection this had to physically reconnect. With a
        pool, ``cursor()`` has already discarded whatever connection failed, so
        the next checkout is a fresh one and there is nothing to reset here.
        Kept (and kept logging) because upsert_rows() calls it between retry
        attempts and the log line is a useful marker in a slow backfill.
        """
        logger.warning("Postgres retry: next checkout takes a fresh connection")

    def closeall(self) -> None:
        """Close every pooled connection. For tests and short-lived scripts."""
        try:
            self._pool.closeall()
        except Exception:
            logger.warning("failed closing the Postgres pool", exc_info=True)

    @property
    def pool_size(self) -> int:
        return self._size

    @property
    def url(self) -> str:
        return self._url


def get_pg_client() -> Any:
    """Return an initialised Postgres client (psycopg2-backed, pooled)."""
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

    rows, cols, sql = _prepare_upsert(table, rows, conflict_columns)
    chunk_size = _get_upsert_chunk_size()

    total = 0
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        values = [tuple(_adapt(r.get(c)) for c in cols) for r in chunk]

        def _write(cur, values=values):
            psycopg2.extras.execute_values(cur, sql, values, page_size=chunk_size)

        _with_retry(client, table, i, len(chunk), _write)
        total += len(chunk)

    return total


def _adapt(v):
    if isinstance(v, (dict, list)):
        return Json(v)
    return v


def _conflict_keys(conflict_columns: Optional[str]) -> List[str]:
    return [c.strip() for c in (conflict_columns or "").split(",") if c.strip()]


def _prepare_upsert(
    table: str, rows: List[Dict[str, Any]], conflict_columns: Optional[str]
):
    """Dedup on the conflict key and build the INSERT ... ON CONFLICT statement.

    Returns (rows, cols, sql). Shared by upsert_rows and replace_scoped_rows so
    the two write exactly the same statement.
    """
    _strip_raw_duplicates(rows)

    keys = _conflict_keys(conflict_columns)
    if conflict_columns:
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
        # Only rewrite a row that actually changed. Without the WHERE, every
        # ON CONFLICT hit rewrites the row even when EXCLUDED is byte-identical,
        # and each rewrite is a new tuple version with a dead one left behind.
        # Measured 2026-09-01 (health diagnostic 14): cia_account_2019..2022 at
        # 55-78 updates per insert, cia_account_2026 at 47M updates on 1.2M
        # rows, cvm_fi_perfil at 31 — whole yearly files re-upserted daily,
        # unchanged. That is where the disk was going.
        #
        # Row-wise IS DISTINCT FROM treats NULL = NULL as "not distinct", so a
        # row whose only difference is a NULL still updates, and one with no
        # difference at all does not. The conflict key columns are left out of
        # the comparison: on the DO UPDATE path they are equal by definition.
        # jsonb `raw` compares by value, so key order inside it does not count
        # as a change.
        #
        # `total` is still len(rows): it is "rows processed", and _log_finish's
        # "fetched N but upserted 0" defect detector depends on that meaning.
        # It must not become an affected-row count, or an idle daily re-fetch
        # would read as every row having been dropped by validation.
        update_set = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols)
        compared = [c for c in cols if c not in keys]
        if compared:
            lhs = ", ".join(f"{table}.{c}" for c in compared)
            rhs = ", ".join(f"EXCLUDED.{c}" for c in compared)
            conflict_clause = (
                f"ON CONFLICT ({conflict_columns}) DO UPDATE SET {update_set}"
                f" WHERE ({lhs}) IS DISTINCT FROM ({rhs})"
            )
        else:
            # Every supplied column is part of the key: a conflicting row is
            # already identical, and there is nothing to set.
            conflict_clause = f"ON CONFLICT ({conflict_columns}) DO NOTHING"
    else:
        conflict_clause = "ON CONFLICT DO NOTHING"

    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES %s {conflict_clause}"
    return rows, cols, sql


def _with_retry(client: Any, table: str, offset: int, size: int, work) -> Any:
    """Run `work(cur)` on a pooled cursor, retrying transient connection errors.

    A transient error (dropped connection, cancelled statement) is retried with
    a fresh connection after the _RETRY_DELAYS back-off; anything else raises at
    once, and so does the last transient error once the retries are spent.
    """
    started = time.monotonic()
    last_exc: Optional[Exception] = None
    for attempt, delay in enumerate((0, *_RETRY_DELAYS)):
        if delay:
            logger.warning(
                "upsert retry in %ds (table=%s chunk_offset=%d chunk_size=%d attempt=%d): %s",
                delay, table, offset, size, attempt, last_exc,
            )
            time.sleep(delay)
            client.reconnect()
        try:
            with client.cursor() as cur:
                result = work(cur)
            logger.debug(
                "upsert ok table=%s chunk_offset=%d rows=%d elapsed=%.2fs",
                table, offset, size, time.monotonic() - started,
            )
            return result
        except Exception as exc:
            if _is_transient_db_error(exc):
                last_exc = exc
            else:
                logger.error(
                    "Upsert failed table=%s chunk_offset=%d chunk_size=%d elapsed=%.2fs: %s",
                    table, offset, size, time.monotonic() - started, exc,
                )
                raise

    logger.error(
        "Upsert exhausted retries table=%s chunk_offset=%d chunk_size=%d elapsed=%.2fs: %s",
        table, offset, size, time.monotonic() - started, last_exc,
    )
    raise last_exc


def replace_scoped_rows(
    client: Any,
    table: str,
    rows: List[Dict[str, Any]],
    conflict_columns: str,
    *,
    nulls_distinct: bool,
    scope_columns: Sequence[str] = ("cnpj", "period"),
    stats: Optional[Dict[str, int]] = None,
) -> int:
    """Make each scope present in `rows` hold exactly `rows`, then report.

    A scope is one value of `scope_columns`: for the CDA blocks, one fund in
    one month. For every scope that appears in `rows`, the stored rows of that
    scope whose conflict key is not among the new rows are deleted, and the new
    rows are upserted exactly as upsert_rows would write them. A scope that
    does not appear in `rows` is not touched at all, so a partial or truncated
    file can never erase the funds it does not carry.

    The delete and the upsert of a scope run in ONE transaction, and a scope
    never straddles two: scopes are packed whole into batches of about the
    upsert chunk size (a scope bigger than that is a batch of its own). If a
    batch fails it rolls back whole and the stored rows of its scopes are as
    they were. A transient error retries the whole batch.

    `nulls_distinct` must match the arbiter of `conflict_columns`. A stored row
    survives exactly when the upsert will land on it: under NULLS DISTINCT a
    key with a NULL never conflicts, so such a row is compared with `=`, is
    deleted, and the new copy is inserted in its place (without this it would
    be re-inserted beside itself on every read). Under NULLS NOT DISTINCT the
    comparison is IS NOT DISTINCT FROM.

    `stats["rows_deleted"]` is increased after each committed batch, so a run
    that fails midway still reports what its committed batches removed.

    Returns the number of rows processed, as upsert_rows does.
    """
    if not rows:
        return 0
    keys = _conflict_keys(conflict_columns)
    missing = [c for c in scope_columns if c not in keys]
    if missing:
        raise ValueError(f"scope columns {missing} are not in the conflict key of {table}")

    rows, cols, upsert_sql = _prepare_upsert(table, rows, conflict_columns)
    for r in rows:
        if any(r.get(c) is None for c in scope_columns):
            raise ValueError(f"{table}: a row has no {'/'.join(scope_columns)}; refusing to replace")

    scopes: Dict[tuple, List[Dict[str, Any]]] = {}
    for r in rows:
        scopes.setdefault(tuple(r.get(c) for c in scope_columns), []).append(r)

    chunk_size = _get_upsert_chunk_size()
    batches: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    for scope_rows in scopes.values():
        if current and len(current) + len(scope_rows) > chunk_size:
            batches.append(current)
            current = []
        current.extend(scope_rows)
    if current:
        batches.append(current)

    key_list = ", ".join(keys)
    scope_list = ", ".join(scope_columns)
    rest = [c for c in keys if c not in scope_columns]
    op = "=" if nulls_distinct else "IS NOT DISTINCT FROM"
    same_key = " AND ".join(
        [f"k.{c} = t.{c}" for c in scope_columns] + [f"k.{c} {op} t.{c}" for c in rest]
    )
    same_scope = " AND ".join(f"t.{c} = s.{c}" for c in scope_columns)
    create_sql = (
        f"CREATE TEMP TABLE _replace_keys ON COMMIT DROP AS"
        f" SELECT {key_list} FROM {table} WITH NO DATA"
    )
    keys_sql = f"INSERT INTO _replace_keys ({key_list}) VALUES %s"
    delete_sql = (
        f"DELETE FROM {table} AS t"
        f" USING (SELECT DISTINCT {scope_list} FROM _replace_keys) AS s"
        f" WHERE {same_scope}"
        f" AND NOT EXISTS (SELECT 1 FROM _replace_keys AS k WHERE {same_key})"
    )

    total = 0
    offset = 0
    for batch in batches:
        key_values = [tuple(_adapt(r.get(c)) for c in keys) for r in batch]
        values = [tuple(_adapt(r.get(c)) for c in cols) for r in batch]

        def _replace(cur, key_values=key_values, values=values):
            cur.execute("BEGIN")
            try:
                cur.execute(create_sql)
                psycopg2.extras.execute_values(
                    cur, keys_sql, key_values, page_size=len(key_values)
                )
                cur.execute("ANALYZE _replace_keys")
                cur.execute(delete_sql)
                deleted = cur.rowcount if isinstance(cur.rowcount, int) and cur.rowcount > 0 else 0
                psycopg2.extras.execute_values(cur, upsert_sql, values, page_size=len(values))
                cur.execute("COMMIT")
            except BaseException:
                # The pool discards this connection on the way out, which also
                # ends the transaction; the ROLLBACK just says so first. Its own
                # failure is logged, and the original error is what propagates.
                try:
                    cur.execute("ROLLBACK")
                except Exception as rb_exc:
                    logger.warning("replace %s: ROLLBACK failed: %s", table, rb_exc)
                raise
            return deleted

        deleted = _with_retry(client, table, offset, len(batch), _replace)
        if stats is not None:
            stats["rows_deleted"] = stats.get("rows_deleted", 0) + deleted
        if deleted:
            logger.info(
                "replace %s: removed %d stored row(s) the new file no longer carries"
                " (%d scope rows offset %d)", table, deleted, len(batch), offset,
            )
        total += len(batch)
        offset += len(batch)

    return total
