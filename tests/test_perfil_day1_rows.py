"""cvm_fi_perfil keeps the published date, and the day-1 leftovers go (#1121).

Two halves:

* the ingest stores DT_COMPTC as published (month-end) and drops, counts and
  logs a row with no parseable date instead of stamping it with the first of
  the requested month;
* scripts/drop_perfil_day1_twins.py deletes a day-1 row only when the same
  fund has a row on another day of that month.

The script's SQL runs here for real, against an in-memory DuckDB table with the
same key, through a cursor that only translates psycopg2's %(name)s
placeholders. No statement is checked by its text alone.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

import pytest

from scripts import drop_perfil_day1_twins as s
from src.pipeline.ingest_fi import ingest_fi_perfil

duckdb = pytest.importorskip("duckdb")

DATED = {"CNPJ_FUNDO_CLASSE": "00.017.024/0001-53", "DT_COMPTC": "2026-09-30",
         "NR_COTST_PF_VAREJO": "10"}
BLANK = {"CNPJ_FUNDO_CLASSE": "11.111.111/0001-11", "DT_COMPTC": "",
         "NR_COTST_PF_VAREJO": "20"}
GARBAGE = {"CNPJ_FUNDO_CLASSE": "22.222.222/0001-22", "DT_COMPTC": "set/2026",
           "NR_COTST_PF_VAREJO": "30"}


def _ingest(rows, year=2026, month=9):
    captured: list = []

    def fake_upsert(conn, table, records, conflict_columns=None):
        captured.append((table, records, conflict_columns))
        return len(records)

    with patch("src.pipeline.ingest_fi.upsert_rows", fake_upsert):
        n = ingest_fi_perfil(None, rows, year, month)
    return n, captured


class TestIngestKeepsThePublishedDate:
    def test_a_dated_row_keeps_its_published_date(self):
        n, captured = _ingest([DATED])
        assert n == 1
        table, records, conflict = captured[0]
        assert (table, conflict) == ("cvm_fi_perfil", "cnpj,period")
        # Month-end as published: not re-keyed to 2026-09-01.
        assert records[0]["period"] == date(2026, 9, 30)
        assert records[0]["cnpj"] == "00017024000153"

    def test_the_requested_month_never_overrides_the_row(self):
        """A file asked for as 2026-10 still stores what the row says."""
        _n, captured = _ingest([DATED], year=2026, month=10)
        assert captured[0][1][0]["period"] == date(2026, 9, 30)

    @pytest.mark.parametrize("row", [BLANK, GARBAGE], ids=["blank", "unparseable"])
    def test_an_undated_row_is_dropped_and_counted(self, row, caplog):
        with caplog.at_level("WARNING", logger="src.pipeline.ingest_fi"):
            n, captured = _ingest([row])
        assert n == 0
        assert captured == []          # nothing reached the upsert
        assert "cvm_fi_perfil 2026-09: dropped 1 of 1 rows with no parseable DT_COMPTC" in caplog.text

    def test_a_mixed_file_stores_only_the_dated_rows(self, caplog):
        with caplog.at_level("WARNING", logger="src.pipeline.ingest_fi"):
            n, captured = _ingest([BLANK, DATED, GARBAGE])
        assert n == 1
        records = captured[0][1]
        assert [(r["cnpj"], r["period"]) for r in records] == [("00017024000153", date(2026, 9, 30))]
        assert date(2026, 9, 1) not in {r["period"] for r in records}
        assert "dropped 2 of 3 rows with no parseable DT_COMPTC" in caplog.text

    def test_a_fully_dated_file_logs_no_drop(self, caplog):
        with caplog.at_level("WARNING", logger="src.pipeline.ingest_fi"):
            _ingest([DATED])
        assert "dropped" not in caplog.text


# ---------------------------------------------------------------------------
# The repair script, on a real SQL engine
# ---------------------------------------------------------------------------

class _Cur:
    """psycopg2-shaped cursor over DuckDB: placeholders and rowcount only."""

    def __init__(self, con, log):
        self.con, self.log, self.rowcount, self._res = con, log, -1, None

    def execute(self, sql, params=None):
        self.log.append(sql)
        names = re.findall(r"%\((\w+)\)s", sql)
        translated = re.sub(r"%\((\w+)\)s", r"$\1", sql)
        self._res = self.con.execute(translated, {k: params[k] for k in set(names)} if names else None)
        if sql.lstrip().upper().startswith("DELETE"):
            self.rowcount = self._res.fetchone()[0]

    def fetchone(self):
        return self._res.fetchone()

    def fetchall(self):
        return self._res.fetchall()


class _Client:
    def __init__(self, rows):
        self.con = duckdb.connect()
        self.con.execute(
            "CREATE TABLE cvm_fi_perfil (cnpj TEXT NOT NULL, period DATE NOT NULL, "
            "UNIQUE (cnpj, period))"
        )
        self.con.executemany("INSERT INTO cvm_fi_perfil VALUES (?, ?)", rows)
        self.log: list = []
        self.closed = False

    @contextmanager
    def cursor(self):
        yield _Cur(self.con, self.log)

    def closeall(self):
        self.closed = True

    def rows(self):
        return self.con.execute("SELECT cnpj, period FROM cvm_fi_perfil ORDER BY 1, 2").fetchall()


TWIN, LONE, TWO_DATES, PLAIN = "0" * 13 + "1", "0" * 13 + "2", "0" * 13 + "3", "0" * 13 + "4"
SEP1, SEP30 = date(2026, 9, 1), date(2026, 9, 30)

SEED = [
    (TWIN, SEP1), (TWIN, SEP30),                    # day 1 + month-end: day 1 goes
    (LONE, SEP1),                                   # day 1 only: stays, listed
    (TWO_DATES, date(2026, 9, 28)), (TWO_DATES, SEP30),   # 2 other dates: counted, stays
    (PLAIN, SEP30),
    # Neighbouring months must not count as a twin of 2026-09-01.
    (LONE, date(2026, 8, 31)), (LONE, date(2026, 10, 1)), (LONE, date(2026, 10, 31)),
]


def test_dry_run_reports_and_changes_nothing(caplog):
    client = _Client(SEED)
    before = client.rows()
    with caplog.at_level("INFO", logger="drop_perfil_day1_twins"):
        rep = s.process_month(client, SEP1, apply=False)
        s.log_month(rep, apply=False)

    assert client.rows() == before
    assert not any(q.lstrip().upper().startswith(("DELETE", "BEGIN")) for q in client.log)
    assert (rep.rows_before, rep.rows_after, rep.day1) == (6, 6, 2)
    assert (rep.twinned, rep.lone, rep.multi_date, rep.deleted) == (1, 1, 1, 0)
    assert rep.lone_cnpjs == [LONE]
    assert "2026-09: 6 rows before, 6 after; 2 on day 1 (1 with a twin, 1 without); would delete 1" in caplog.text
    assert f"day-1 rows with no twin, left alone (1): {LONE}" in caplog.text
    assert "1 fund-months with rows on 2+ dates that are not day 1, left alone" in caplog.text


def test_apply_deletes_only_the_twinned_day1_row(caplog):
    client = _Client(SEED)
    with caplog.at_level("INFO", logger="drop_perfil_day1_twins"):
        rep = s.process_month(client, SEP1, apply=True)
        s.log_month(rep, apply=True)

    assert client.rows() == sorted(r for r in SEED if r != (TWIN, SEP1))
    assert (rep.rows_before, rep.rows_after, rep.deleted) == (6, 5, 1)
    assert "2026-09: 6 rows before, 5 after" in caplog.text
    assert "deleted 1" in caplog.text
    # One transaction, and the delete sits inside it.
    marks = [q.strip().split()[0].upper() for q in client.log]
    assert marks.index("BEGIN") < marks.index("DELETE") < marks.index("COMMIT")


def test_a_second_run_deletes_nothing():
    client = _Client(SEED)
    s.process_month(client, SEP1, apply=True)
    after_first = client.rows()
    client.log.clear()

    rep = s.process_month(client, SEP1, apply=True)

    assert client.rows() == after_first
    assert (rep.twinned, rep.lone, rep.deleted) == (0, 1, 0)
    assert (rep.rows_before, rep.rows_after) == (5, 5)
    assert not any(q.lstrip().upper().startswith("DELETE") for q in client.log)


def test_a_day1_row_of_the_next_month_is_not_a_twin():
    """2026-10-01 is another month's day 1, never the twin of 2026-09-01."""
    client = _Client([(LONE, SEP1), (LONE, date(2026, 10, 1))])
    rep = s.process_month(client, SEP1, apply=True)
    assert (rep.twinned, rep.lone, rep.deleted) == (0, 1, 0)
    assert len(client.rows()) == 2


def test_a_delete_that_disagrees_with_the_count_is_rolled_back(monkeypatch):
    client = _Client(SEED)
    before = client.rows()
    # A delete wider than the twin rule: it would also take the untwinned row.
    monkeypatch.setattr(s, "DELETE_SQL", "DELETE FROM cvm_fi_perfil WHERE period = %(first)s")
    with pytest.raises(RuntimeError, match="deleted 2 rows but 1 day-1 rows had a twin"):
        s.process_month(client, SEP1, apply=True)
    assert client.rows() == before
    assert client.log[-1] == "ROLLBACK"


def test_run_walks_month_by_month_and_totals(caplog):
    client = _Client(SEED)
    with caplog.at_level("INFO", logger="drop_perfil_day1_twins"):
        reports = s.run(client, date(2026, 8, 1), date(2026, 10, 1), apply=True)

    assert [r.first for r in reports] == [date(2026, 8, 1), SEP1, date(2026, 10, 1)]
    assert [r.deleted for r in reports] == [0, 1, 1]      # LONE has 10-01 and 10-31
    assert "cvm_fi_perfil 2026-08..2026-10 (applied): 9 rows before, 7 after" in caplog.text
    assert "2 deleted" in caplog.text


def test_every_statement_is_bounded_to_one_month():
    for sql in (s.MONTH_ROWS_SQL, s.TWINNED_SQL, s.LONE_SQL, s.MULTI_DATE_SQL, s.DELETE_SQL):
        assert "%(first)s" in sql and "%(next_first)s" in sql, sql
    assert "period = %(first)s" in s.DAY1_ROWS_SQL
    assert "UPDATE" not in s.DELETE_SQL.upper()


def test_months_and_arguments():
    assert list(s.months(date(2025, 11, 1), date(2026, 2, 1))) == [
        date(2025, 11, 1), date(2025, 12, 1), date(2026, 1, 1), date(2026, 2, 1)]
    args, start, end = s.parse_args(["--start", "2026-08", "--end", "2026-09"])
    assert (args.apply, start, end) == (False, date(2026, 8, 1), SEP1)     # dry run by default
    args, _, _ = s.parse_args(["--start", "2026-08", "--end", "2026-09", "--apply"])
    assert args.apply is True
    args, _, _ = s.parse_args(["--dry-run"])
    assert args.apply is False
    for bad in (["--dry-run", "--apply"], ["--start", "2026-13"], ["--start", "2026-09", "--end", "2026-08"]):
        with pytest.raises(SystemExit):
            s.parse_args(bad)


def test_main_goes_through_pg_client_and_closes_it(monkeypatch):
    client = _Client(SEED)
    monkeypatch.setattr("src.store.pg_client.get_pg_client", lambda: client)
    assert s.main(["--start", "2026-09", "--end", "2026-09"]) == 0
    assert client.closed
    assert len(client.rows()) == len(SEED)      # no --apply, nothing deleted
