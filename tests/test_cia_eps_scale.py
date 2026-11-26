"""Per-share accounts of cia_account are stored unscaled, and the stored rows get corrected once (#1115).

Two halves:

* the ingest multiplies a money line by its ESCALA_MOEDA factor and leaves the
  per-share accounts (3.99 and under) as published;
* scripts/fix_cia_eps_scale.py divides the rows stored before that, once.

The script's SQL runs here for real, against in-memory DuckDB tables, through a
cursor that only translates psycopg2's %(name)s placeholders. No statement is
checked by its text alone. The reference row is real: cd_cvm 4170, DFP
2025-12-31, account 3.99.01.02, stored 3240.00 under MIL for a published 3.24
(read on the live table on 2026-11-26).
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from scripts import fix_cia_eps_scale as s
from src.pipeline import ingest_log
from src.pipeline.ingest_cia import _MONEY_SCALE, _is_per_share_account, ingest_cia_account

duckdb = pytest.importorskip("duckdb")

D = Decimal

# ---------------------------------------------------------------------------
# The ingest
# ---------------------------------------------------------------------------

EPS_ROW = {
    "CNPJ_CIA": "33.592.510/0001-54",
    "DT_REFER": "2025-12-31",
    "VERSAO": "1",
    "DENOM_CIA": "VALE S.A.",
    "CD_CVM": "004170",
    "GRUPO_DFP": "DF Consolidado - Demonstração do Resultado",
    "MOEDA": "REAL",
    "ESCALA_MOEDA": "MIL",
    "ORDEM_EXERC": "ÚLTIMO",
    "DT_INI_EXERC": "2025-01-01",
    "DT_FIM_EXERC": "2025-12-31",
    "CD_CONTA": "3.99.01.02",
    "DS_CONTA": "ON",
    "VL_CONTA": "3.2400000000",
    "ST_CONTA_FIXA": "S",
}
NET_INCOME_ROW = {**EPS_ROW, "CD_CONTA": "3.11", "DS_CONTA": "Lucro/Prejuízo Consolidado do Período",
                  "VL_CONTA": "14000000.0000000000"}


class _Member:
    grupo, escopo, is_account_data, member_name = "DRE", "con", True, "dfp_cia_aberta_DRE_con_2025.csv"

    def __init__(self, rows):
        self.rows = rows


def _ingest(rows):
    captured: list = []

    def fake_upsert(conn, table, records, conflict_columns=None):
        captured.extend(records)
        return len(records)

    with patch("src.pipeline.ingest_cia.upsert_rows", fake_upsert):
        ingest_cia_account(MagicMock(), [_Member(rows)], "dfp")
    return {r["cd_conta"]: r for r in captured}


class TestIngestLeavesPerShareAccountsUnscaled:
    def test_eps_under_mil_keeps_the_published_value(self):
        rec = _ingest([EPS_ROW])["3.99.01.02"]
        assert rec["vl_conta"] == 3.24                 # not 3240.0
        assert rec["escala_moeda"] == "MIL"            # as published, not rewritten
        assert rec["cd_cvm"] == "4170"

    def test_a_money_line_in_the_same_file_is_still_scaled(self):
        recs = _ingest([EPS_ROW, NET_INCOME_ROW])
        assert recs["3.11"]["vl_conta"] == 14_000_000.0 * 1_000.0
        assert recs["3.99.01.02"]["vl_conta"] == 3.24

    @pytest.mark.parametrize("cd_conta", ["3.99", "3.99.01", "3.99.01.02", "3.99.02", "3.99.02.02"])
    def test_every_account_under_3_99_is_unscaled(self, cd_conta):
        assert _ingest([{**EPS_ROW, "CD_CONTA": cd_conta}])[cd_conta]["vl_conta"] == 3.24

    @pytest.mark.parametrize("cd_conta", ["3.990", "3.9", "3.09", "3.98.01", "13.99", "3.99x"])
    def test_a_neighbouring_code_is_a_money_line(self, cd_conta):
        assert _ingest([{**EPS_ROW, "CD_CONTA": cd_conta}])[cd_conta]["vl_conta"] == 3.24 * 1_000.0

    def test_the_raw_residual_holds_no_copy_of_the_value(self):
        """So nothing stored can tell a scaled row from an unscaled one."""
        raw = _ingest([EPS_ROW])["3.99.01.02"]["raw"]
        assert "VL_CONTA" not in raw and set(raw) == {"DENOM_CIA", "GRUPO_DFP", "MOEDA"}


@pytest.mark.parametrize("cd_conta,expected", [
    ("3.99", True), ("3.99.01", True), ("3.99.01.02", True), ("3.99.02.02", True),
    ("3.990", False), ("3.9", False), ("3.99x", False), ("13.99", False), ("", False), (None, False),
])
def test_the_prefix_rule(cd_conta, expected):
    assert _is_per_share_account(cd_conta) is expected


def test_the_parser_version_moved_with_the_unit():
    """The script tells the fixed ingest by this number."""
    assert int(ingest_log.PARSER_VERSION) >= s.FIXED_PARSER_VERSION == 3


# ---------------------------------------------------------------------------
# The correction script, on a real SQL engine
# ---------------------------------------------------------------------------

_DML = ("UPDATE", "INSERT", "DELETE")


class _Cur:
    """psycopg2-shaped cursor over DuckDB: placeholders and rowcount only."""

    def __init__(self, con, log):
        self.con, self.log, self.rowcount, self._res = con, log, -1, None

    def execute(self, sql, params=None):
        self.log.append(sql)
        names = re.findall(r"%\((\w+)\)s", sql)
        translated = re.sub(r"%\((\w+)\)s", r"$\1", sql)
        self._res = self.con.execute(translated, {k: params[k] for k in set(names)} if names else None)
        if sql.lstrip().upper().startswith(_DML):
            self.rowcount = self._res.fetchone()[0]

    def fetchone(self):
        return self._res.fetchone()

    def fetchall(self):
        return self._res.fetchall()


class _Client:
    def __init__(self, rows, log_rows=()):
        self.con = duckdb.connect()
        self.con.execute(
            "CREATE TABLE cia_account (cd_cvm TEXT NOT NULL, dt_refer DATE NOT NULL, "
            "cd_conta TEXT NOT NULL, vl_conta DECIMAL(28,2), escala_moeda TEXT)"
        )
        self.con.executemany("INSERT INTO cia_account VALUES (?, ?, ?, ?, ?)", rows)
        self.con.execute(
            "CREATE TABLE cvm_ingest_log (entity TEXT, doc_type TEXT, status TEXT, "
            "parser_version TEXT, started_at TIMESTAMP, rows_upserted INT)"
        )
        if log_rows:
            self.con.executemany("INSERT INTO cvm_ingest_log VALUES (?, ?, ?, ?, ?, ?)", log_rows)
        self.log: list = []
        self.closed = False

    @contextmanager
    def cursor(self):
        yield _Cur(self.con, self.log)

    def closeall(self):
        self.closed = True

    def rows(self):
        return self.con.execute(
            "SELECT cd_cvm, dt_refer, cd_conta, vl_conta, escala_moeda FROM cia_account "
            "ORDER BY cd_cvm, dt_refer, cd_conta"
        ).fetchall()

    def value(self, cd_cvm, cd_conta, dt_refer=date(2025, 12, 31)):
        return self.con.execute(
            "SELECT vl_conta FROM cia_account WHERE cd_cvm = ? AND cd_conta = ? AND dt_refer = ?",
            [cd_cvm, cd_conta, dt_refer],
        ).fetchone()[0]

    def marker(self):
        return self.con.execute(
            f"SELECT dt_refer_year, rows_updated, rows_rounded FROM {s.MARKER} ORDER BY 1"
        ).fetchall()


@pytest.fixture(autouse=True)
def _no_postgres_only_statements(monkeypatch):
    """Row level security and role grants do not exist in DuckDB."""
    monkeypatch.setattr(s, "MARKER_LOCKDOWN_SQL", ())


Y25, Y24 = date(2025, 12, 31), date(2024, 12, 31)

SEED = [
    # The reference filing: basic and diluted EPS stored 1,000 times too large.
    ("4170", Y25, "3.99.01.02", D("3240.00"), "MIL"),
    ("4170", Y25, "3.99.02.02", D("3230.00"), "MIL"),
    # Its parent lines store zero: counted, never changed.
    ("4170", Y25, "3.99", D("0.00"), "MIL"),
    ("4170", Y25, "3.99.01", D("0.00"), "MIL"),
    ("4170", Y25, "3.99.02", D("0.00"), "MIL"),
    # A money line of the same filing is right as stored.
    ("4170", Y25, "3.11", D("14000000000.00"), "MIL"),
    # Codes that only look like the prefix.
    ("4170", Y25, "3.990", D("5000.00"), "MIL"),
    ("4170", Y25, "3.9", D("6000.00"), "MIL"),
    # The ingest multiplied these by 1: nothing to undo.
    ("9512", Y25, "3.99.01.01", D("1.87"), "UNIDADE"),
    ("9513", Y25, "3.99.01.01", D("2.50"), None),
    ("9514", Y25, "3.99.01.01", D("4.10"), "BILHAO"),
    # A null value, a lower-case scale and the other multiplied scales.
    ("9515", Y25, "3.99.01.01", None, "MIL"),
    ("9516", Y25, "3.99.01.01", D("-1500.00"), " mil "),
    ("9517", Y25, "3.99.01.01", D("2000000.00"), "MILHAO"),
    ("9518", Y25, "3.99.01.01", D("7000000.00"), "MILHÃO"),
    # Another year, so the batches are seen to be separate.
    ("4170", Y24, "3.99.01.02", D("9310.00"), "MIL"),
]
CHANGED = {
    ("4170", Y25, "3.99.01.02"): D("3.24"),
    ("4170", Y25, "3.99.02.02"): D("3.23"),
    ("9516", Y25, "3.99.01.01"): D("-1.50"),
    ("9517", Y25, "3.99.01.01"): D("2.00"),
    ("9518", Y25, "3.99.01.01"): D("7.00"),
    ("4170", Y24, "3.99.01.02"): D("9.31"),
}


def _key(row):
    return row[:3]


def _expected(seed=SEED, changed=CHANGED):
    return sorted(((c, d, a, changed.get((c, d, a), v), e) for c, d, a, v, e in seed), key=_key)


def _run(client, **kw):
    kw.setdefault("apply", True)
    return s.run(client, 2024, 2025, **kw)


def test_the_factors_are_the_ingests_own():
    assert s.FACTORS == {k: int(v) for k, v in _MONEY_SCALE.items() if v != 1}
    assert s.FACTORS == {"MIL": 1_000, "MILHAO": 1_000_000, "MILHÃO": 1_000_000}
    assert "UNIDADE" not in s.FACTORS
    assert [s.factor_of(x) for x in ("MIL", " mil ", "UNIDADE", None, "BILHAO")] == [1000, 1000, 1, 1, 1]


def test_dry_run_reports_and_writes_nothing(caplog):
    client = _Client(SEED)
    before = client.rows()
    with caplog.at_level("INFO", logger="fix_cia_eps_scale"):
        reports = _run(client, apply=False)

    assert client.rows() == before
    assert not any(q.lstrip().upper().startswith(_DML + ("BEGIN", "CREATE")) for q in client.log)
    assert not s.marked_years(client)                      # no marker table either
    y24, y25 = reports
    assert (y24.per_share_rows, y24.to_change) == (1, 1)
    assert (y25.per_share_rows, y25.to_change, y25.rounded, y25.updated) == (12, 5, 0, 0)
    assert "2025: 12 per-share rows" in caplog.text and "would change 5" in caplog.text
    assert "'UNIDADE' 1 rows (1 with a value, left alone)" in caplog.text
    assert "None 1 rows (1 with a value, left alone)" in caplog.text
    assert "'MIL' 6 rows (2 with a value, divide by 1,000)" in caplog.text      # 3 zeros and a NULL stay
    assert "' mil ' 1 rows (1 with a value, divide by 1,000)" in caplog.text
    assert "'MILHAO' 1 rows (1 with a value, divide by 1,000,000)" in caplog.text
    assert "sample rows (cd_cvm, dt_refer, cd_conta, old value, new value):" in caplog.text
    assert "4170  2025-12-31  3.99.01.02  3240.00 -> 3.24" in caplog.text
    assert ("cia_account 2024..2025 (dry run): 13 per-share rows before, 13 after; "
            "6 to change, 0 changed") in caplog.text


def test_apply_divides_only_the_scaled_per_share_rows(caplog):
    client = _Client(SEED)
    with caplog.at_level("INFO", logger="fix_cia_eps_scale"):
        reports = _run(client)

    assert client.rows() == _expected()
    assert client.value("4170", "3.99.01.02") == D("3.24")
    assert client.value("4170", "3.99.02.02") == D("3.23")
    assert client.value("4170", "3.99") == D("0.00")                 # zero stays zero
    assert client.value("4170", "3.11") == D("14000000000.00")       # another account
    assert client.value("4170", "3.990") == D("5000.00")             # not under 3.99.
    assert client.value("9512", "3.99.01.01") == D("1.87")           # UNIDADE
    assert client.value("9514", "3.99.01.01") == D("4.10")           # unknown scale
    assert client.value("9515", "3.99.01.01") is None
    assert [r.updated for r in reports] == [1, 5]
    assert client.marker() == [(2024, 1, 0), (2025, 5, 0)]
    assert "2025: 12 per-share rows" in caplog.text and "changed 5" in caplog.text
    assert "(apply): 13 per-share rows before, 13 after; 6 to change, 6 changed" in caplog.text


def test_each_year_marks_and_updates_in_one_transaction():
    client = _Client(SEED)
    _run(client)
    marks = [q.strip().split()[0].upper() for q in client.log]
    first = marks.index("BEGIN")
    year = marks[first:marks.index("COMMIT", first) + 1]
    assert year.index("BEGIN") < year.index("INSERT") < year.index("UPDATE") < year.index("COMMIT")
    assert marks.count("BEGIN") == marks.count("COMMIT") == 2          # one per year
    assert "ROLLBACK" not in marks


def test_a_second_apply_is_refused_and_changes_nothing():
    client = _Client(SEED)
    _run(client)
    after_first, marker = client.rows(), client.marker()
    client.log.clear()

    with pytest.raises(s.Refused, match="the correction has run"):
        _run(client)

    assert client.rows() == after_first and client.marker() == marker
    assert client.value("4170", "3.99.01.02") == D("3.24")             # not 0.00
    assert not any(q.lstrip().upper().startswith(_DML + ("BEGIN",)) for q in client.log)


def test_a_second_apply_exits_non_zero(monkeypatch):
    client = _Client(SEED)
    monkeypatch.setattr("src.store.pg_client.get_pg_client", lambda: client)
    argv = ["--start-year", "2024", "--end-year", "2025", "--apply"]
    assert s.main(argv) == 0
    after_first = client.rows()
    assert s.main(argv) == s.EXIT_REFUSED == 2
    assert s.main(argv + ["--resume"]) == 2                            # nothing left to resume
    assert client.rows() == after_first == _expected()
    assert client.closed


def test_a_dry_run_after_the_correction_says_it_ran(caplog):
    client = _Client(SEED)
    _run(client)
    after = client.rows()
    with caplog.at_level("INFO", logger="fix_cia_eps_scale"):
        reports = _run(client, apply=False)
    assert client.rows() == after
    assert all(r.marked for r in reports)
    assert "2025: corrected by an earlier run (5 rows), not touched" in caplog.text
    assert "--apply would be refused" in caplog.text and "the correction has run" in caplog.text


def test_resume_does_only_the_unmarked_years():
    """A run that stopped after 2024: 2025 is still to do, 2024 must not be divided again."""
    client = _Client(SEED)
    s.ensure_marker(client)
    s.apply_year(client, s.report_year(client, 2024))
    assert client.value("4170", "3.99.01.02", Y24) == D("9.31")
    assert client.value("4170", "3.99.01.02") == D("3240.00")

    with pytest.raises(s.Refused, match="--apply --resume"):
        _run(client)                                                   # plain --apply refuses
    assert client.value("4170", "3.99.01.02") == D("3240.00")

    reports = _run(client, resume=True)
    assert client.rows() == _expected()
    assert [(r.year, r.marked, r.updated) for r in reports] == [(2024, True, 1), (2025, False, 5)]


def test_a_marked_year_is_never_divided_again():
    """Even called directly, the marker insert stops the year before any row changes."""
    client = _Client(SEED)
    s.ensure_marker(client)
    s.apply_year(client, s.report_year(client, 2025))
    # Rows that look scaled again, as a late run of the old ingest would leave them.
    client.con.execute(
        "UPDATE cia_account SET vl_conta = 3240.00 "
        "WHERE cd_conta = '3.99.01.02' AND dt_refer = DATE '2025-12-31'"
    )
    with pytest.raises(s.Refused, match="already marked"):
        s.apply_year(client, s.report_year(client, 2025))
    assert client.value("4170", "3.99.01.02") == D("3240.00")          # left for a person to read
    assert client.log[-1] == "ROLLBACK"
    assert client.marker() == [(2025, 5, 0)]


@pytest.mark.parametrize("status", ["ok", "running", "error"])
def test_it_refuses_once_the_fixed_ingest_has_written(status):
    log = [("cia_aberta", "dfp", status, "3", "2026-11-27 06:10:00", 0 if status == "running" else 1200)]
    client = _Client(SEED, log)
    before = client.rows()
    with pytest.raises(s.Refused, match="fixed ingest has already"):
        _run(client)
    assert client.rows() == before and not s.marked_years(client)


@pytest.mark.parametrize("log_row", [
    ("cia_aberta", "dfp", "ok", "2", "2026-11-25 06:10:00", 1200),     # the old parser
    ("cia_aberta", "itr", "ok", None, "2026-01-01 06:10:00", 1200),    # before lineage
    ("cia_aberta", "dfp", "skipped", "3", "2026-11-27 06:10:00", 0),   # wrote nothing
    ("cia_aberta", "itr", "ok", "3", "2026-11-27 06:10:00", 0),        # no new document that day
    ("cia_aberta", "ipe", "ok", "3", "2026-11-27 06:10:00", 1200),     # not cia_account
    ("fi", "diario", "ok", "3", "2026-11-27 06:10:00", 1200),
    ("cia_aberta", "dfp", "ok", "local", "2026-11-27 06:10:00", 1200), # not a number: no crash
])
def test_other_ingest_rows_do_not_block_it(log_row):
    client = _Client(SEED, [log_row])
    _run(client)
    assert client.rows() == _expected()


def test_rows_that_lose_digits_need_the_flag(caplog):
    seed = SEED + [
        ("9520", Y25, "3.99.01.01", D("551.23"), "MIL"),               # a published 0.55123
        ("9521", Y25, "3.99.01.01", D("4.10"), "MIL"),                 # a published 0.00410
    ]
    client = _Client(seed)
    before = client.rows()

    with caplog.at_level("INFO", logger="fix_cia_eps_scale"):
        rep = _run(client, apply=False)[1]
    assert (rep.to_change, rep.rounded, rep.to_zero) == (7, 2, 1)
    assert "2 lose digits past 2 decimals (1 become 0.00)" in caplog.text

    with pytest.raises(s.Refused, match="--accept-rounding"):
        _run(client)
    assert client.rows() == before and not s.marked_years(client)

    _run(client, accept_rounding=True)
    assert client.value("9520", "3.99.01.01") == D("0.55")
    assert client.value("9521", "3.99.01.01") == D("0.00")
    assert client.value("4170", "3.99.01.02") == D("3.24")
    assert client.marker() == [(2024, 1, 0), (2025, 7, 2)]


def test_a_row_outside_the_year_range_stops_the_run():
    client = _Client(SEED + [("4170", date(2031, 12, 31), "3.99.01.02", D("1000.00"), "MIL")])
    before = client.rows()
    with pytest.raises(s.Refused, match=r"1 rows to change have a dt_refer outside 2024\.\.2025"):
        _run(client)
    assert client.rows() == before and not s.marked_years(client)


def test_an_update_that_disagrees_with_the_count_is_rolled_back(monkeypatch):
    client = _Client(SEED)
    s.ensure_marker(client)
    before = client.rows()
    # An update wider than the rule: it would also divide the UNIDADE row.
    monkeypatch.setattr(s, "UPDATE_SQL", (
        "UPDATE cia_account SET vl_conta = vl_conta / 1000 "
        "WHERE dt_refer >= %(lo)s AND dt_refer < %(hi)s AND left(cd_conta, 5) = '3.99.' AND vl_conta <> 0"
    ))
    with pytest.raises(RuntimeError, match="updated 8 rows but 5 were to change"):
        s.apply_year(client, s.report_year(client, 2025))
    assert client.rows() == before
    assert client.marker() == []                                       # the marker row went with it
    assert client.log[-1] == "ROLLBACK"


def test_a_scale_the_sql_and_the_ingest_read_differently_stops_the_run(monkeypatch):
    client = _Client(SEED)
    monkeypatch.setattr(s, "FACTORS", {"MIL": 1000})                   # the SQL still divides MILHAO
    with pytest.raises(s.Refused, match="the ingest's scale table selects 3 rows but the SQL selects 5"):
        s.report_year(client, 2025)


def test_every_statement_is_bounded_to_one_year():
    for sql in (s.SCALES_SQL, s.CANDIDATES_SQL, s.SCALED_SUM_SQL, s.PER_SHARE_ROWS_SQL,
                s.SAMPLE_SQL, s.UPDATE_SQL):
        assert "dt_refer >= %(lo)s AND dt_refer < %(hi)s" in sql, sql
    assert "LIMIT %(limit)s" in s.SAMPLE_SQL
    for sql in (s.UPDATE_SQL, s.CANDIDATES_SQL, s.SAMPLE_SQL, s.OUTSIDE_SQL):
        assert s.CANDIDATE_SQL in sql
    assert "DELETE" not in s.UPDATE_SQL.upper() and "escala_moeda =" not in s.UPDATE_SQL
    assert "%" not in s.UPDATE_SQL.replace("%(lo)s", "").replace("%(hi)s", "")


def test_the_marker_table_is_closed_to_the_public_roles(monkeypatch):
    monkeypatch.undo()                                                 # the real statements
    text = " ".join(s.MARKER_LOCKDOWN_SQL)
    assert "ENABLE ROW LEVEL SECURITY" in text and "REVOKE ALL" in text
    assert "'anon'" in text and "'authenticated'" in text
    assert "CREATE TABLE IF NOT EXISTS" in s.MARKER_DDL and "PRIMARY KEY" in s.MARKER_DDL


def test_arguments():
    args = s.parse_args([])
    assert (args.apply, args.resume, args.accept_rounding) == (False, False, False)   # dry run by default
    assert (args.start_year, args.end_year) == (2010, date.today().year + 1)
    assert s.parse_args(["--apply", "--resume", "--accept-rounding"]).apply is True
    assert s.parse_args(["--dry-run"]).apply is False
    for bad in (["--dry-run", "--apply"], ["--resume"], ["--start-year", "2026", "--end-year", "2025"],
                ["--sample-limit", "-1"]):
        with pytest.raises(SystemExit):
            s.parse_args(bad)


def test_main_goes_through_pg_client_and_closes_it(monkeypatch):
    client = _Client(SEED)
    monkeypatch.setattr("src.store.pg_client.get_pg_client", lambda: client)
    assert s.main(["--start-year", "2024", "--end-year", "2025"]) == 0
    assert client.closed
    assert client.rows() == sorted(SEED, key=_key)                     # no --apply, nothing changed
