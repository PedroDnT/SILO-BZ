"""One pooled Postgres client for the read-only `serve/` app.

Step 3 of docs/planning/SERVING.md: serving cannot fall over a panel.
`serve/` used to open a fresh psycopg2 connection per request (and mutate
``os.environ["POSTGRES_URL"]`` inside a request handler to steer
``get_pg_client``). This module replaces that with a single
``ThreadedConnectionPool`` shared by every handler:

- Configuration (``SILO_API_DATABASE_URL`` preferred, else ``POSTGRES_URL``)
  is read once at startup, never inside a request.
- ``SILO_API_DATABASE_URL`` is expected to be a **read-only** role on the
  Supabase *transaction* pooler (port 6543). Nothing is hardcoded here.
- Handlers check a connection out per request via the ``connection()``
  context manager; it is always put back in ``finally``, and closed instead
  of recycled when it can no longer roll back.
- The socket pool itself is built lazily on first checkout (so importing
  ``serve.app`` never dials the database), but exactly once per process.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Any, Iterator, Optional

import psycopg2
import psycopg2.pool

_DEFAULT_MAXCONN = 10
_DEFAULT_STATEMENT_TIMEOUT_MS = 15_000


class ServePool:
    """Thread-safe pool of read-only psycopg2 connections for `serve/`."""

    def __init__(
        self,
        dsn: Optional[str],
        *,
        minconn: int = 1,
        maxconn: int = _DEFAULT_MAXCONN,
        statement_timeout_ms: int = _DEFAULT_STATEMENT_TIMEOUT_MS,
    ) -> None:
        self._dsn = dsn
        self._minconn = minconn
        self._maxconn = maxconn
        self._statement_timeout_ms = int(statement_timeout_ms)
        self._pool: Any = None
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "ServePool":
        """Build from the environment, read exactly once at startup.

        A missing URL is not an import-time error — it fails on the first
        checkout, so offline tooling can import `serve.app` without a DB.
        """
        raw = os.environ.get("SILO_API_DATABASE_URL") or os.environ.get("POSTGRES_URL")
        # Same whitespace normalisation as src.store.pg_client.get_pg_client.
        dsn = "".join(raw.split()) if raw else None
        maxconn = int(os.environ.get("SILO_API_POOL_MAX", str(_DEFAULT_MAXCONN)))
        timeout_ms = int(
            os.environ.get(
                "SILO_API_STATEMENT_TIMEOUT_MS", str(_DEFAULT_STATEMENT_TIMEOUT_MS)
            )
        )
        return cls(dsn, maxconn=maxconn, statement_timeout_ms=timeout_ms)

    @property
    def dsn(self) -> Optional[str]:
        return self._dsn

    def _ensure_pool(self) -> Any:
        """Create the underlying pool once, on first use (double-checked)."""
        if self._pool is None:
            with self._lock:
                if self._pool is None:
                    if not self._dsn:
                        raise RuntimeError(
                            "POSTGRES_URL or SILO_API_DATABASE_URL must be set"
                        )
                    self._pool = psycopg2.pool.ThreadedConnectionPool(
                        self._minconn, self._maxconn, self._dsn
                    )
        return self._pool

    @contextmanager
    def connection(self) -> Iterator[Any]:
        """Check a connection out for one request; always put it back.

        The statement_timeout guard is a runtime ``SET LOCAL`` inside the
        request's transaction rather than an ``options='-c ...'`` startup
        parameter: the Supabase transaction pooler multiplexes many clients
        over few server connections per *transaction*, so startup options and
        session-level ``SET`` do not reliably reach the server connection that
        runs the query. ``SET LOCAL`` rides in the same transaction as the
        handler's SELECT (psycopg2 opens it implicitly, autocommit is off) and
        vanishes at rollback. Belt to the role-level timeout's suspenders —
        the role-level setting is applied on the SQL side.
        """
        pool = self._ensure_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SET LOCAL statement_timeout = %s",
                    (self._statement_timeout_ms,),
                )
            yield conn
        finally:
            try:
                # Read-only surface: discard the transaction (and the LOCAL
                # timeout) so the pooler gets a clean connection back.
                conn.rollback()
            except Exception:
                pool.putconn(conn, close=True)
            else:
                pool.putconn(conn)

    def close(self) -> None:
        """Close every pooled connection. Idempotent; used at app teardown."""
        with self._lock:
            if self._pool is not None:
                self._pool.closeall()
                self._pool = None
