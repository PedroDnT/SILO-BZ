"""serve.pool.ServePool — psycopg2 mocked, no network.

Step 3 of docs/planning/SERVING.md: one pool per process, per-request
checkout/putback in finally, runtime statement_timeout on every checkout.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from serve.pool import ServePool


def _timeout_calls(fake_conn):
    cur = fake_conn.cursor.return_value.__enter__.return_value
    return [
        c for c in cur.execute.call_args_list if "statement_timeout" in c.args[0]
    ]


def test_pool_is_created_once():
    with patch("psycopg2.pool.ThreadedConnectionPool") as tcp:
        pool = ServePool("postgresql://x", maxconn=3)
        with pool.connection():
            pass
        with pool.connection():
            pass
        assert tcp.call_count == 1
        assert tcp.call_args.args == (1, 3, "postgresql://x")
        inner = tcp.return_value
        assert inner.getconn.call_count == 2
        assert inner.putconn.call_count == 2


def test_statement_timeout_set_local_per_checkout():
    with patch("psycopg2.pool.ThreadedConnectionPool") as tcp:
        pool = ServePool("postgresql://x", statement_timeout_ms=15000)
        with pool.connection():
            pass
        fake_conn = tcp.return_value.getconn.return_value
        calls = _timeout_calls(fake_conn)
        assert len(calls) == 1
        # SET LOCAL (not options=/session SET) so it survives the Supabase
        # transaction pooler — it rides in the request's own transaction.
        assert calls[0].args[0].startswith("SET LOCAL statement_timeout")
        assert calls[0].args[1] == (15000,)
        # Read-only surface: the transaction is discarded at putback.
        assert fake_conn.rollback.call_count == 1


def test_putback_in_finally_when_body_raises():
    with patch("psycopg2.pool.ThreadedConnectionPool") as tcp:
        pool = ServePool("postgresql://x")
        with pytest.raises(RuntimeError):
            with pool.connection():
                raise RuntimeError("handler exploded")
        inner = tcp.return_value
        assert inner.putconn.call_count == 1
        assert inner.getconn.return_value.rollback.call_count == 1


def test_broken_connection_is_closed_not_recycled():
    with patch("psycopg2.pool.ThreadedConnectionPool") as tcp:
        inner = tcp.return_value
        inner.getconn.return_value.rollback.side_effect = Exception("server closed")
        pool = ServePool("postgresql://x")
        with pool.connection():
            pass
        assert inner.putconn.call_count == 1
        assert inner.putconn.call_args.kwargs == {"close": True}


def test_from_env_prefers_api_url_and_strips_whitespace():
    env = {
        "SILO_API_DATABASE_URL": "postgresql://api@host:6543/db ?sslmode=require",
        "POSTGRES_URL": "postgresql://ingest",
    }
    with patch.dict(os.environ, env, clear=True):
        pool = ServePool.from_env()
    assert pool.dsn == "postgresql://api@host:6543/db?sslmode=require"


def test_from_env_falls_back_to_postgres_url():
    with patch.dict(os.environ, {"POSTGRES_URL": "postgresql://ingest"}, clear=True):
        pool = ServePool.from_env()
    assert pool.dsn == "postgresql://ingest"


def test_missing_url_fails_on_first_checkout_not_at_import():
    with patch.dict(os.environ, {}, clear=True):
        pool = ServePool.from_env()  # constructing is import-time safe
    with pytest.raises(RuntimeError, match="SILO_API_DATABASE_URL"):
        with pool.connection():
            pass


def test_close_is_idempotent():
    with patch("psycopg2.pool.ThreadedConnectionPool") as tcp:
        pool = ServePool("postgresql://x")
        with pool.connection():
            pass
        pool.close()
        pool.close()
        assert tcp.return_value.closeall.call_count == 1


def test_create_app_builds_one_pool_and_registers_teardown():
    from serve.app import create_app

    with patch.dict(
        os.environ, {"SILO_API_DATABASE_URL": "postgresql://api"}, clear=True
    ):
        with patch("serve.app.atexit.register") as reg:
            app = create_app()
    pool = app.extensions["silo_pool"]
    assert isinstance(pool, ServePool)
    assert pool.dsn == "postgresql://api"
    reg.assert_called_once_with(pool.close)
