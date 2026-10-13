"""Offline tests for scripts/_check_conn.py (#947).

No database: ``pg_client.connect`` is replaced by a fake that records every
statement. The script must read ``pg_class.reltuples`` in one query and never
issue a ``COUNT(``, which on ``cvm_fi_diario`` is an unbounded scan.
"""
from __future__ import annotations

from scripts import _check_conn
from src.store import pg_client

FAKE_DSN = "postgresql://127.0.0.1:6543/db"


class _Cursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.conn.executed.append((sql, params))

    def fetchall(self):
        return self.conn.rows


class _Conn:
    def __init__(self, rows):
        self.rows = rows
        self.executed: list = []
        self.closed = False

    def cursor(self):
        return _Cursor(self)

    def close(self):
        self.closed = True


def _run(monkeypatch, rows):
    conn = _Conn(rows)
    dsns = []

    def fake_connect(dsn, **kwargs):
        dsns.append(dsn)
        return conn

    monkeypatch.setenv("POSTGRES_URL", FAKE_DSN)
    monkeypatch.setattr(pg_client, "connect", fake_connect)
    _check_conn.main()
    return conn, dsns


def test_reads_estimates_in_one_query_without_count(monkeypatch, capsys):
    rows = [
        ("cvm_ingest_log", 52_000, False),
        ("cvm_fi_diario", 312_000_000, False),
        ("cvm_fidc_mensal", 0, False),
        ("cvm_fidc_aging", 0, True),
    ]
    conn, dsns = _run(monkeypatch, rows)

    assert dsns == ["postgresql://127.0.0.1:5432/db"]
    assert conn.closed
    assert len(conn.executed) == 1
    sql, params = conn.executed[0]
    assert "COUNT(" not in sql.upper()
    assert "reltuples" in sql and "pg_inherits" in sql
    assert params == (_check_conn.TABLES,)

    out = capsys.readouterr().out
    assert "Connection: OK" in out
    assert "estimates" in out
    lines = {line.split()[0]: line for line in out.splitlines() if line.startswith("  ")}
    assert "312000000" in lines["cvm_fi_diario"] and "✓" in lines["cvm_fi_diario"]
    assert "52000" in lines["cvm_ingest_log"]
    assert "(empty)" in lines["cvm_fidc_mensal"]
    assert "(never analyzed)" in lines["cvm_fidc_aging"]
    assert "(empty)" not in lines["cvm_fidc_aging"]
    assert "(missing)" in lines["cvm_securit_fluxo"]
