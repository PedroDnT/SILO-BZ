"""Pins the warehouse health gate against the bugs that made it red on 2026-08-28.

Two consecutive DB Health runs failed for different reasons:

* Run 33163062887 (ae2719d) counted every error row and read
  ``api.catalog()->>'catalog_version'`` (always empty). #133 fixed those.
* Run 33164105326 (c84dc67, after #133) still failed Health checks. The only
  assertion that set ``fail=1`` was **1 unhealed ingest error**:
  ``fidc/mensal_tab_x2/2026-08 TimeoutError`` at 2026-08-27 09:00:58Z.
  Daily ingest later 404'd the same slice (unpublished August FIDC file) and
  logged ``skipped``. Completeness, ingest activity (261 rows / 26h), and
  ``api.catalog()->>'version'`` (=9, 9 coverage rows) all passed. Disk 899%
  is a warning, not a fail.

The remaining gate bug is that a later ``skipped`` did not count as a heal.
These tests parse the workflow YAML. They cannot see production, but they stop
the same predicate from shipping again.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/health.yml"
CATALOG_PY = ROOT / "serve/catalog.py"
SQL19 = ROOT / "src/store/analytical/19_api_contract.sql"
DIAG_DIR = ROOT / "scripts/health_diagnostics"


def _spec() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _step(name: str) -> dict:
    for step in _spec()["jobs"]["health"]["steps"]:
        if step.get("name") == name:
            return step
    raise AssertionError(
        f"no step {name!r}: {[s.get('name') for s in _spec()['jobs']['health']['steps']]}"
    )


def test_workflow_yaml_is_parseable():
    spec = _spec()
    assert spec["name"] == "DB Health"
    assert spec["jobs"]["health"]["name"] == "Warehouse health"


def test_catalog_check_reads_the_version_key_not_catalog_version():
    body = _step("Health checks")["run"]
    assert "api.catalog()->>'version'" in body, (
        "the catalog jsonb key is `version` (CATALOG_VERSION); "
        "`catalog_version` is always NULL and the gate reports a dead contract"
    )
    assert "->>'catalog_version'" not in body


def test_embedded_catalog_key_is_version_in_sql_and_python():
    assert '"version": CATALOG_VERSION' in CATALOG_PY.read_text(encoding="utf-8")
    sql = SQL19.read_text(encoding="utf-8")
    assert '"version":' in sql
    assert '"catalog_version"' not in sql


def test_ingest_errors_treat_later_skipped_as_healed():
    """Run 33164105326: TimeoutError then 404-skip must not fail the gate."""
    body = _step("Health checks")["run"]
    heal = "s.status IN ('ok', 'skipped')"
    assert heal in body, (
        "a later skipped (CVM 404, unpublished month) is a recovered probe, "
        "not a broken slice — run 33164105326 stayed red because only ok healed"
    )
    assert body.count(heal) >= 2, "count query and the evidence SELECT must agree"
    assert "IS NOT DISTINCT FROM e.entity" in body
    assert "IS NOT DISTINCT FROM e.period_year" in body
    assert "IS NOT DISTINCT FROM e.period_month" in body
    # The fail signal is unresolved slices, not every error attempt in the window.
    assert "UNHEALED ingest error slices" in body
    sql_lines = [
        line for line in body.splitlines()
        if "s.status" in line and not line.lstrip().startswith("#")
    ]
    assert sql_lines, "heal predicate must appear in SQL, not only comments"
    assert all("IN ('ok', 'skipped')" in line for line in sql_lines), (
        "an ok-only heal predicate is what counted the fidc 2026-08 TimeoutError "
        "after daily ingest had already skipped it as unpublished"
    )


def test_disk_warns_and_does_not_fail_the_gate():
    body = _step("Health checks")["run"]
    disk_section = body[body.index("# 5. Disk"):]
    # 71.9 GB vs a placeholder 8 GB printed 899% on run 33164105326. That is
    # a warning annotation, not fail=1. Dropping landing tables to clear a
    # percentage would destroy the warehouse.
    assert "fail=1" not in disk_section
    assert "::warning::" in disk_section


def test_diagnostics_are_one_file_per_query():
    body = _step("Diagnostics")["run"]
    assert "scripts/health_diagnostics/*.sql" in body
    assert "ON_ERROR_STOP=1" in body  # per-file; a missing view must not abort the rest
    assert "for f in scripts/health_diagnostics/*.sql" in body
    files = sorted(DIAG_DIR.glob("*.sql"))
    assert len(files) >= 10, f"expected split diagnostic SQL files, found {files}"


def test_diagnostics_runs_even_when_the_gate_failed():
    step = _step("Diagnostics")
    assert "always()" in str(step.get("if", ""))


def test_health_check_and_diagnostics_scripts_are_bash_n_clean():
    """Catch YAML-block-scalar / heredoc breakage before CI parses it on the runner."""
    body = _step("Health checks")["run"]
    proc = subprocess.run(
        ["bash", "-n"],
        input=body.encode("utf-8"),
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode()
    diag = _step("Diagnostics")["run"]
    proc = subprocess.run(
        ["bash", "-n"],
        input=diag.encode("utf-8"),
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode()
