"""mode=cda-vacuum-full: the CDA tables' dead space goes back to the OS."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import strip_cda_fund_name as s

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/daily_ingest.yml"

yaml = pytest.importorskip("yaml")


class _Cur:
    def __init__(self, log, sizes):
        self.log, self.sizes, self._row = log, sizes, None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.log.append(sql)
        if sql.startswith("SELECT pg_total_relation_size"):
            self._row = (self.sizes.pop(0),)

    def fetchone(self):
        return self._row


class _Client:
    def __init__(self, sizes):
        self.log, self.sizes, self.closed = [], list(sizes), False

    def cursor(self):
        return _Cur(self.log, self.sizes)

    def closeall(self):
        self.closed = True


def test_rewrite_runs_vacuum_full_with_no_timeout_and_logs_the_sizes(caplog):
    client = _Client([15 * 2**30, 9 * 2**30])
    with caplog.at_level("INFO", logger="strip_cda_fund_name"):
        s.rewrite_table(client, "cvm_fi_cda_acoes")
    assert "SET statement_timeout = 0" in client.log
    assert client.log.index("SET statement_timeout = 0") < client.log.index("VACUUM FULL cvm_fi_cda_acoes")
    assert "15.00 GB -> 9.00 GB (6.00 GB returned)" in caplog.text


def test_rewrite_refuses_a_table_that_is_not_a_cda_table():
    with pytest.raises(ValueError):
        s.rewrite_table(_Client([]), "cvm_fi_diario")


def test_rewrite_order_is_smallest_first_and_covers_the_bloated_debentures_table():
    assert s.REWRITE_TABLES[0] == "cvm_fi_cda_debentures"
    assert s.REWRITE_TABLES[-1] == "cvm_fi_cda_acoes"
    assert set(s.TABLES) <= set(s.REWRITE_TABLES)


def test_vacuum_full_only_skips_the_strip(monkeypatch):
    client = _Client([2**30, 2**29] * len(s.REWRITE_TABLES))
    monkeypatch.setattr("src.store.pg_client.get_pg_client", lambda: client)
    monkeypatch.setattr(s, "strip_table", lambda *a, **k: pytest.fail("strip must not run"))
    assert s.main(["--vacuum-full-only"]) == 0
    assert [q for q in client.log if q.startswith("VACUUM FULL")] == [
        f"VACUUM FULL {t}" for t in s.REWRITE_TABLES
    ]


def test_the_workflow_offers_the_mode_after_the_schema_apply_and_runs_only_for_it():
    spec = yaml.safe_load(WORKFLOW.read_text())
    assert "cda-vacuum-full" in spec[True]["workflow_dispatch"]["inputs"]["mode"]["options"]
    steps = spec["jobs"]["ingest"]["steps"]
    names = [x.get("name") for x in steps]
    name = "Rewrite the CDA tables (VACUUM FULL)"
    assert names.index("Apply schema + migrations") < names.index(name)
    step = steps[names.index(name)]
    assert "mode == 'cda-vacuum-full'" in step["if"]
    assert "--vacuum-full-only" in step["run"]
    # no other step may fire for this mode: it holds locks on the CDA tables
    others = [x for x in steps if x.get("name") != name and "cda-vacuum-full" in str(x.get("if", ""))]
    assert not others
