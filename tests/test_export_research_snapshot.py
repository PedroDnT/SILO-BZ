"""scripts/export_research_snapshot.py writes a frozen, reproducible snapshot (#984).

Contract pinned here:
  a table streams in batches into <name>.parquet with rows and sha256 in its entry
  an empty query still writes a file with its columns
  prices come from api.quote_history pages; a refused ticker is listed, not filled
  a refusal rolls back to a savepoint so the one transaction survives
  every SQL the script runs on a table reads, never writes
"""

import datetime as dt
import hashlib
import re

import polars as pl

from scripts import export_research_snapshot as snap


class _NamedCursor:
    def __init__(self, rows, columns):
        self.rows = list(rows)
        self.description = [(c,) for c in columns]
        self.itersize = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.sql = sql

    def fetchmany(self, n):
        out, self.rows = self.rows[:n], self.rows[n:]
        return out


class _Cur:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.log.append(sql)


class _Conn:
    def __init__(self, rows=(), columns=()):
        self._rows, self._columns, self.log = rows, columns, []

    def cursor(self, name=None):
        if name:
            return _NamedCursor(self._rows, self._columns)
        return _Cur(self.log)


def test_a_table_streams_in_batches_into_parquet(tmp_path, monkeypatch):
    monkeypatch.setattr(snap, "BATCH", 2)
    rows = [("00000000000191", dt.date(2026, 8, 1), 1.5), ("00000000000272", dt.date(2026, 8, 1), None),
            ("00000000000353", dt.date(2026, 9, 1), 2.0)]
    entry = snap.export_table(_Conn(rows, ["cnpj", "period", "vl_quota"]), "fund_monthly", "SELECT 1", str(tmp_path))
    df = pl.read_parquet(tmp_path / "fund_monthly.parquet")
    assert entry["rows"] == 3 and df.height == 3
    assert df["cnpj"].to_list()[0] == "00000000000191", "a CNPJ keeps its leading zeros"
    assert df["vl_quota"].to_list()[1] is None, "a null stays null"
    assert entry["sha256"] == hashlib.sha256((tmp_path / "fund_monthly.parquet").read_bytes()).hexdigest()


def test_an_empty_table_still_writes_its_columns(tmp_path):
    entry = snap.export_table(_Conn([], ["a", "b"]), "empty", "SELECT 1", str(tmp_path))
    assert entry["rows"] == 0
    assert pl.read_parquet(tmp_path / "empty.parquet").columns == ["a", "b"]


def _pages(conn, ticker):
    if ticker == "BAD3":
        raise RuntimeError("quote_history: refused, close_adj is not available for BAD3 ...")
    return [{"ticker": ticker, "trade_date": dt.date(2026, 10, 16), "isin": "BRX", "close": 10,
             "close_adj": 9.5, "close_total_return": None, "volume": 1000}]


def test_prices_list_a_refused_ticker_and_keep_the_rest(tmp_path):
    conn = _Conn()
    entry = snap.export_prices(conn, str(tmp_path), ["BAD3", "PETR4"], pages=_pages)
    df = pl.read_parquet(tmp_path / "equity_prices.parquet")
    assert df["ticker"].to_list() == ["PETR4"], "a refused ticker is never exported with raw closes"
    assert "refused" in entry["refused"]["BAD3"]
    assert df.schema["trade_date"] == pl.Date and df.schema["close"] == pl.Float64
    assert df["close_total_return"].to_list() == [None]


def test_a_refusal_rolls_back_to_its_savepoint(tmp_path):
    conn = _Conn()
    snap.export_prices(conn, str(tmp_path), ["BAD3", "PETR4"], pages=_pages)
    assert conn.log == ["SAVEPOINT q", "ROLLBACK TO SAVEPOINT q", "SAVEPOINT q", "RELEASE SAVEPOINT q"]


def test_price_pages_follow_the_cursor_until_a_short_page(monkeypatch):
    calls = []

    class C:
        def __init__(self, page):
            self.page = page

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params):
            calls.append(params[1])

        def fetchall(self):
            return [({"ticker": "X", "trade_date": d},) for d in self.page]

    full = [f"2026-01-{i:02d}" for i in range(1, 4)]
    pages = iter([full, full[:1]])
    monkeypatch.setattr(snap, "PAGE", 3)

    class Conn:
        def cursor(self):
            return C(next(pages))

    rows = snap._price_pages(Conn(), "X")
    assert calls == ["", "2026-01-03"]
    assert len(rows) == 4 and rows[0]["trade_date"] == dt.date(2026, 1, 1)


def test_every_table_query_only_reads():
    for name, sql in snap.TABLES:
        assert re.match(r"^SELECT\b", sql), name
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|TRUNCATE|DROP|ALTER|CREATE)\b", sql, re.I), name
