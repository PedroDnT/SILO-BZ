"""Offline tests for scripts/apply_schema.py, the schema deployer (#890).

No database: psql is hidden and ``psycopg2.connect`` is replaced inside
``src.store.pg_client``, the one place the script's connection now comes from.
POSTGRES_URL is always a fake DSN, so no path can reach a real server.
"""
from __future__ import annotations

import pytest

from scripts import apply_schema
from src.store import pg_client

FAKE_DSN = "postgresql://127.0.0.1:1/db"


class _Cursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql):
        self.conn.executed.append(sql)
        if self.conn.fail_on and self.conn.fail_on in sql:
            raise RuntimeError("boom")


class _Conn:
    def __init__(self, fail_on=None):
        self.fail_on = fail_on
        self.executed: list[str] = []
        self.autocommit = False
        self.closed = False

    def cursor(self):
        return _Cursor(self)

    def close(self):
        self.closed = True


@pytest.fixture
def items(tmp_path):
    a = tmp_path / "a.sql"
    a.write_text(
        "CREATE TABLE IF NOT EXISTS t (x int);\n"
        "DO $$ BEGIN PERFORM 1; PERFORM 2; END $$;\n",
        encoding="utf-8",
    )
    b = tmp_path / "b.sql"
    b.write_text("SELECT 'second_file';\n", encoding="utf-8")
    return [("a.sql", str(a)), ("b.sql", str(b))]


@pytest.fixture
def fake_db(monkeypatch, items):
    """psycopg2 driver path only: fake DSN, no psql, recorded connect()."""
    monkeypatch.setenv("POSTGRES_URL", " " + FAKE_DSN + "\n")
    monkeypatch.setattr(apply_schema, "_resolve_psql", lambda: None)
    monkeypatch.setattr(apply_schema, "_build_migration_list", lambda: items)
    state: dict = {"calls": [], "conn": _Conn()}

    def _connect(dsn, **kwargs):
        state["calls"].append((dsn, kwargs))
        return state["conn"]

    monkeypatch.setattr(pg_client.psycopg2, "connect", _connect)
    return state


def test_all_files_ok_exits_zero_and_sends_each_file_whole(fake_db, items, capsys):
    with pytest.raises(SystemExit) as exc:
        apply_schema.main()
    assert exc.value.code == 0

    conn = fake_db["conn"]
    assert conn.autocommit is True
    assert conn.closed is True
    # One execute per file, the whole file: the DO $$ ... $$ block is not split on ';'.
    assert len(conn.executed) == len(items)
    assert "PERFORM 1; PERFORM 2;" in conn.executed[0]
    assert "second_file" in conn.executed[1]

    out = capsys.readouterr().out
    assert "ok a.sql" in out and "ok b.sql" in out
    assert "Done: 2 OK, 0 errors  (driver: psycopg2)" in out


def test_connection_goes_through_pg_client_with_keepalives(fake_db):
    with pytest.raises(SystemExit):
        apply_schema.main()
    [(dsn, kwargs)] = fake_db["calls"]
    assert dsn == FAKE_DSN  # whitespace stripped, as before
    for key, value in pg_client.KEEPALIVES.items():
        assert kwargs[key] == value


def test_a_failing_file_is_reported_and_exits_one(fake_db, capsys):
    fake_db["conn"] = _Conn(fail_on="second_file")
    with pytest.raises(SystemExit) as exc:
        apply_schema.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "ok a.sql" in out
    assert "! b.sql: boom" in out
    assert "Done: 1 OK, 1 errors  (driver: psycopg2)" in out


def test_no_postgres_url_prints_manual_fallback_without_exiting(monkeypatch, items, capsys):
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    monkeypatch.setattr(apply_schema, "_build_migration_list", lambda: items)

    def _never(*a, **k):
        raise AssertionError("must not connect without POSTGRES_URL")

    monkeypatch.setattr(pg_client.psycopg2, "connect", _never)
    apply_schema.main()  # returns, no SystemExit
    out = capsys.readouterr().out
    assert "POSTGRES_URL not set." in out
    assert "MANUAL FALLBACK" in out
    assert "second_file" in out


def test_without_psycopg2_or_asyncpg_falls_back_to_manual(monkeypatch, items, capsys):
    """psycopg2 is imported lazily, so a box without it still gets the fallback."""
    import sys

    monkeypatch.setenv("POSTGRES_URL", FAKE_DSN)
    monkeypatch.setattr(apply_schema, "_resolve_psql", lambda: None)
    monkeypatch.setattr(apply_schema, "_build_migration_list", lambda: items)
    monkeypatch.setitem(sys.modules, "psycopg2", None)
    monkeypatch.setitem(sys.modules, "asyncpg", None)
    apply_schema.main()  # returns, no SystemExit
    out = capsys.readouterr().out
    assert "No PostgreSQL client available" in out
    assert "MANUAL FALLBACK" in out


@pytest.mark.parametrize("rc, code", [(0, 0), (3, 1)])
def test_psql_path_exit_code_follows_psql(monkeypatch, items, capsys, rc, code):
    monkeypatch.setenv("POSTGRES_URL", FAKE_DSN)
    monkeypatch.setattr(apply_schema, "_resolve_psql", lambda: "/usr/bin/psql")
    monkeypatch.setattr(apply_schema, "_build_migration_list", lambda: items)
    calls = []

    def _call(argv, **kwargs):
        calls.append(argv)
        return rc

    monkeypatch.setattr(apply_schema.subprocess, "call", _call)
    with pytest.raises(SystemExit) as exc:
        apply_schema.main()
    assert exc.value.code == code
    assert len(calls) == len(items)
    assert all(argv[:5] == ["/usr/bin/psql", FAKE_DSN, "-v", "ON_ERROR_STOP=1", "-q"] for argv in calls)
    assert "(driver: psql)" in capsys.readouterr().out


def test_pg_client_connect_merges_keepalives_and_caller_wins(monkeypatch):
    seen = {}

    def _connect(dsn, **kwargs):
        seen.update(dsn=dsn, **kwargs)
        return "conn"

    monkeypatch.setattr(pg_client.psycopg2, "connect", _connect)
    assert pg_client.connect("dsn", connect_timeout=20, keepalives_idle=5) == "conn"
    assert seen["dsn"] == "dsn"
    assert seen["connect_timeout"] == 20
    assert seen["keepalives_idle"] == 5  # caller override wins
    assert seen["keepalives"] == pg_client.KEEPALIVES["keepalives"]
