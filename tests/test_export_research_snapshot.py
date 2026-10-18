"""scripts/export_research_snapshot.py writes a frozen, reproducible snapshot (#984).

Contract pinned here:
  a table streams in batches into <name>.parquet with rows and sha256 in its entry
  an empty query still writes a file with its columns
  prices come from api.quote_history pages (adj_status 'ok')
  a refused ticker is retried raw: close/close_unit/volume, no close_adj, adj_status 'refused' (#987)
  a ticker refused even raw goes under `unavailable`; the export goes on
  each refusal rolls back to its own savepoint so the one transaction survives
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


def _row(ticker, fields):
    """What api.quote_history returns for the asked fields: only those keys."""
    row = {"ticker": ticker, "trade_date": dt.date(2026, 10, 16)}
    values = {"isin": "BRX", "close": 10.0, "close_unit": 10.0, "close_adj": 9.5,
              "close_total_return": None, "volume": 1000.0}
    row.update({f: values[f] for f in fields})
    return row


def _pages(conn, ticker, fields):
    """BAD3 is refused for the adjusted call only; WORSE3 is refused for any call."""
    if ticker == "WORSE3" or (ticker == "BAD3" and "close_adj" in fields):
        raise RuntimeError(f"quote_history: refused, close_adj is not available for {ticker} ...")
    return [_row(ticker, fields)]


def test_a_refused_ticker_is_exported_raw_and_flagged(tmp_path):
    entry = snap.export_prices(_Conn(), str(tmp_path), ["BAD3", "PETR4"], pages=_pages)
    df = pl.read_parquet(tmp_path / "equity_prices.parquet").sort("ticker")
    assert df["ticker"].to_list() == ["BAD3", "PETR4"], "the refused ticker stays in the file"
    assert df["adj_status"].to_list() == ["refused", "ok"]
    bad, good = df.to_dicts()
    assert bad["close"] == 10.0 and bad["close_unit"] == 10.0 and bad["volume"] == 1000.0
    assert bad["close_adj"] is None and bad["close_total_return"] is None, "nothing raw goes in close_adj"
    assert good["close_adj"] == 9.5
    assert "refused" in entry["refused"]["BAD3"]
    assert entry["raw_only_rows"] == 1 and entry["unavailable"] == {}
    assert df.schema["trade_date"] == pl.Date and df.schema["close"] == pl.Float64


def test_a_ticker_refused_even_raw_is_listed_and_the_export_goes_on(tmp_path):
    entry = snap.export_prices(_Conn(), str(tmp_path), ["WORSE3", "PETR4"], pages=_pages)
    df = pl.read_parquet(tmp_path / "equity_prices.parquet")
    assert df["ticker"].to_list() == ["PETR4"]
    assert "WORSE3" in entry["refused"] and "WORSE3" in entry["unavailable"]
    assert entry["raw_only_rows"] == 0


def test_the_adjusted_call_asks_for_adjusted_fields_and_the_retry_for_raw_only(tmp_path):
    asked = []

    def pages(conn, ticker, fields):
        asked.append((ticker, tuple(fields)))
        return _pages(conn, ticker, fields)

    snap.export_prices(_Conn(), str(tmp_path), ["BAD3"], pages=pages)
    assert asked == [("BAD3", tuple(snap.ADJ_FIELDS)), ("BAD3", tuple(snap.RAW_FIELDS))]
    assert "close_adj" in snap.ADJ_FIELDS and "close_total_return" in snap.ADJ_FIELDS
    assert "close_adj" not in snap.RAW_FIELDS and "close_total_return" not in snap.RAW_FIELDS


def test_every_refusal_rolls_back_to_its_own_savepoint(tmp_path):
    conn = _Conn()
    snap.export_prices(conn, str(tmp_path), ["BAD3", "PETR4"], pages=_pages)
    assert conn.log == [
        "SAVEPOINT q", "ROLLBACK TO SAVEPOINT q",   # BAD3 adjusted: refused
        "SAVEPOINT q", "RELEASE SAVEPOINT q",       # BAD3 raw: served
        "SAVEPOINT q", "RELEASE SAVEPOINT q",       # PETR4 adjusted: served
    ]


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
            calls.append((params[1], params[2]))

        def fetchall(self):
            return [({"ticker": "X", "trade_date": d},) for d in self.page]

    full = [f"2026-01-{i:02d}" for i in range(1, 4)]
    pages = iter([full, full[:1]])
    monkeypatch.setattr(snap, "PAGE", 3)

    class Conn:
        def cursor(self):
            return C(next(pages))

    rows = snap._price_pages(Conn(), "X", snap.RAW_FIELDS)
    assert calls == [("", list(snap.RAW_FIELDS)), ("2026-01-03", list(snap.RAW_FIELDS))]
    assert len(rows) == 4 and rows[0]["trade_date"] == dt.date(2026, 1, 1)


def test_every_table_query_only_reads():
    for name, sql in snap.TABLES:
        assert re.match(r"^SELECT\b", sql), name
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|TRUNCATE|DROP|ALTER|CREATE)\b", sql, re.I), name
