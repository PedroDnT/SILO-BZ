"""backfill.yml hardening (#1111), offline.

1. Dispatch inputs reach a ``run:`` block only through ``env:``. ``fi_months``
   is free text; pasted into Python or bash it could break the job or run code
   next to POSTGRES_URL.
2. The analytical apply is not ``continue-on-error``: a failed apply turns the
   run red (daily_ingest.yml learned this from 04_fact_fund_monthly.sql).
3. The two inline DB blocks are scripts that connect through
   ``src.store.pg_client``.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
BACKFILL = ROOT / ".github/workflows/backfill.yml"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate = _load("backfill_fi_year_gate")
snapshot = _load("backfill_coverage_snapshot")


def _jobs():
    return yaml.safe_load(BACKFILL.read_text())["jobs"]


# --- the workflow --------------------------------------------------------------


def test_no_expression_is_pasted_into_a_run_block():
    offenders = [
        (job, step.get("name"))
        for job, spec in _jobs().items()
        for step in spec.get("steps", [])
        if "${{" in step.get("run", "")
    ]
    assert offenders == []


def test_analytical_apply_fails_the_run_and_still_runs_after_a_red_slice():
    job = _jobs()["apply-analytical"]
    assert "continue-on-error" not in job
    assert job["if"].startswith("${{ always() &&")


def test_workflow_opens_no_raw_connection_and_installs_pinned_requirements():
    text = BACKFILL.read_text()
    assert "psycopg2" not in text
    assert "pip install psycopg2-binary" not in text
    steps = _jobs()["inspect-coverage"]["steps"]
    runs = [s.get("run", "") for s in steps]
    assert "pip install -r requirements.txt" in runs
    assert "python scripts/backfill_coverage_snapshot.py" in runs
    fi_steps = {s.get("name"): s for s in _jobs()["backfill-fi"]["steps"]}
    check = fi_steps["Skip if year already complete"]
    assert check["run"] == "python scripts/backfill_fi_year_gate.py"
    assert check["env"]["FI_MONTHS"] == "${{ inputs.fi_months }}"


def test_scripts_connect_through_pg_client():
    for name in ("backfill_fi_year_gate", "backfill_coverage_snapshot"):
        src = (ROOT / "scripts" / f"{name}.py").read_text()
        assert "pg_client.connect(" in src
        assert "psycopg2.connect" not in src


# --- the FI year gate ------------------------------------------------------------


def _coverage(n=12, *, yearly=None, diario_rows=None, **override):
    counts = {d: n for d in gate.MONTHLY_DOC_TYPES}
    counts.update(override)
    return {"counts": counts, "yearly_status": yearly, "diario_rows": diario_rows}


def _decide(year, doc, coverage, *, repair=False, months="", force=False):
    return gate.decide(
        year, doc, repair_gaps=repair, months=months, force=force, coverage=coverage
    )


def test_complete_year_skips_and_incomplete_runs():
    assert _decide(2024, "all", _coverage(12))[0] is True
    assert _decide(2024, "all", _coverage(12, perfil_mensal=3))[0] is False
    assert _decide(2024, "cda", _coverage(12))[0] is True
    assert _decide(2024, "cda", _coverage(2))[0] is False


def test_repair_and_months_never_skip():
    assert _decide(2024, "cda", _coverage(12), repair=True)[0] is False
    assert _decide(2024, "cda", _coverage(12), months="2024-01")[0] is False


def test_unknown_doc_type_and_unread_coverage_run_the_year():
    skip, msg = _decide(2024, "extrato", _coverage(12))
    assert not skip and "no coverage rule" in msg
    assert _decide(2024, "all", None)[0] is False


def test_yearly_hist_status_skips_only_hist_years():
    assert _decide(2010, "cda", _coverage(0, yearly="skipped"))[0] is True
    assert _decide(2024, "cda", _coverage(0, yearly="ok"))[0] is False


def test_2019_2020_need_diario_rows_and_perfil():
    assert _decide(2019, "all", _coverage(0, perfil_mensal=12, diario_rows=2_500_000))[0]
    assert not _decide(2019, "all", _coverage(12, diario_rows=100))[0]


def test_main_treats_fi_months_as_data(tmp_path, monkeypatch):
    out = tmp_path / "out"
    marker = tmp_path / "pwned"
    hostile = f'2024-01"); open("{marker}", "w"); ("'
    monkeypatch.setattr(gate.pg_client, "connect", pytest.fail)
    rc = gate.main({
        "YEAR": "2024", "FI_DOC_TYPE": "cda", "FI_MONTHS": hostile,
        "POSTGRES_URL": "postgres://x", "GITHUB_OUTPUT": str(out),
    })
    assert rc == 0 and not marker.exists() and not out.exists()


def test_main_without_url_runs_the_year(tmp_path, capsys):
    out = tmp_path / "out"
    gate.main({"YEAR": "2024", "FI_DOC_TYPE": "all", "GITHUB_OUTPUT": str(out)})
    assert not out.exists()
    assert "POSTGRES_URL missing" in capsys.readouterr().out


def test_main_fails_open_on_a_query_error(tmp_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("pooler down")

    monkeypatch.setattr(gate.pg_client, "connect", boom)
    out = tmp_path / "out"
    gate.main({"YEAR": "2024", "FI_DOC_TYPE": "all",
               "POSTGRES_URL": "postgres://x", "GITHUB_OUTPUT": str(out)})
    assert not out.exists()
    assert "fail-open" in capsys.readouterr().out


class _Cur:
    def __init__(self, answers, fail_on=None):
        self.answers = list(answers)
        self.sql = []
        self.fail_on = fail_on
        self.description = [("entity",), ("n",)]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.sql.append((sql, params))
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("no such function")

    def fetchone(self):
        return self.answers.pop(0)

    def fetchall(self):
        return self.answers.pop(0)

    def close(self):
        pass


class _Conn:
    def __init__(self, cur):
        self.cur = cur
        self.commits = self.rollbacks = self.closed = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed += 1


def test_main_reads_coverage_and_writes_skip(tmp_path, monkeypatch):
    cur = _Cur([(12,)] * len(gate.MONTHLY_DOC_TYPES))
    conn = _Conn(cur)
    seen = {}

    def fake_connect(dsn, **kw):
        seen["dsn"], seen["kw"] = dsn, kw
        return conn

    monkeypatch.setattr(gate.pg_client, "connect", fake_connect)
    out = tmp_path / "out"
    gate.main({"YEAR": "2024", "FI_DOC_TYPE": "all",
               "POSTGRES_URL": " postgres://x \n", "GITHUB_OUTPUT": str(out)})
    assert out.read_text() == "skip=true\n"
    assert seen == {"dsn": "postgres://x", "kw": {"connect_timeout": 20}}
    assert conn.closed == 1
    assert all(params[1] == 2024 for _, params in cur.sql)


# --- the coverage snapshot -------------------------------------------------------


def test_snapshot_marks_stale_commits_and_prints():
    cur = _Cur([[(1,), (2,)], [("fi", "cda", 2024, "ok", 3, 10)], [("fi", 1)]])
    conn = _Conn(cur)
    lines = []
    assert snapshot.run(conn, out=lines.append) == 2
    assert conn.commits == 1 and conn.rollbacks == 0
    assert "UPDATE cvm_ingest_log" in cur.sql[0][0]
    assert snapshot.STALE_NOTE in cur.sql[0][0]
    assert lines[0] == "Marked 2 stale running audit row(s) as error"
    assert "fi\tcda\t2024\tok\t3\t10" in lines


def test_snapshot_prints_a_missing_data_coverage_and_rolls_back():
    cur = _Cur([[], []], fail_on="data_coverage")
    conn = _Conn(cur)
    lines = []
    snapshot.run(conn, out=lines.append)
    assert conn.rollbacks == 1
    assert lines[-1].startswith("data_coverage unavailable:")


def test_snapshot_update_failure_raises():
    conn = _Conn(_Cur([], fail_on="UPDATE cvm_ingest_log"))
    with pytest.raises(RuntimeError):
        snapshot.run(conn, out=lambda _: None)
    assert conn.commits == 0


def test_snapshot_main_connects_through_pg_client(monkeypatch):
    conn = _Conn(_Cur([[], [], []]))
    monkeypatch.setattr(snapshot.pg_client, "connect", lambda dsn, **kw: conn)
    assert snapshot.main({"POSTGRES_URL": "postgres://x"}) == 0
    assert conn.closed == 1
