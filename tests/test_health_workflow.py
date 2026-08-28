"""Pins the warehouse health gate against the bugs that made it red on 2026-08-28.

Run https://github.com/PedroDnT/SILO-BZ/actions/runs/33163062887 failed three
distinct ways, two of them the gate's own:

1. `api.catalog()->>'catalog_version'` is empty because the jsonb key is
   `version` (serve/catalog.py CATALOG_VERSION). coverage() returned 9 rows —
   the contract was answering.
2. Diagnostics used `ON_ERROR_STOP=1`, so a missing `vw_b3_share_count_event`
   (migration 26 not yet applied; this job is read-only) aborted the step at
   psql exit 3 before D2.10 ran.
3. Ingest-error check counted every `error` row in 26h, including recovered
   TimeoutError attempts whose later `ok` already landed the slice
   (src/pipeline/gaps.py documents that trap).

These tests parse the workflow YAML. They cannot see production, but they stop
the same typos from shipping again.
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
    # Keep the workflow pin honest against the sources of truth.
    assert '"version": CATALOG_VERSION' in CATALOG_PY.read_text(encoding="utf-8")
    sql = SQL19.read_text(encoding="utf-8")
    assert '"version":' in sql
    assert '"catalog_version"' not in sql


def test_ingest_errors_count_unresolved_slices_not_recovered_attempts():
    body = _step("Health checks")["run"]
    assert "NOT EXISTS" in body
    assert "later.status IN ('ok', 'skipped')" in body
    assert "IS NOT DISTINCT FROM e.period_year" in body
    assert "unresolved" in body
    # The naive count of every error row must not be what fails the gate.
    # attempts= is informational; errs= is the fail signal.
    assert "unresolved slices:" in body
    assert 'FAIL: $errs unresolved ingest error slices' in body


def test_disk_warns_against_pro_included_allowance_and_does_not_fail_the_gate():
    spec = _spec()
    env = spec["jobs"]["health"]["env"]
    assert env["PLAN_DISK_GB"] == "8"
    body = _step("Health checks")["run"]
    assert "Pro included" in body
    # Disk is a warning annotation, not a fail=1. Dropping landing tables to
    # clear the % would destroy the warehouse.
    disk_section = body[body.index("# 5. Disk"):]
    assert "fail=1" not in disk_section
    assert "::warning::" in disk_section
    assert "do not drop landing tables" in disk_section.lower()


def test_diagnostics_does_not_use_on_error_stop():
    body = _step("Diagnostics")["run"]
    # A comment may mention the old flag; the psql invocation must not pass it.
    psql_lines = [
        line for line in body.splitlines()
        if line.lstrip().startswith("psql ")
    ]
    assert psql_lines, "diagnostics must invoke psql"
    assert all("ON_ERROR_STOP=1" not in line for line in psql_lines), (
        "ON_ERROR_STOP=1 is what turned a missing view into job exit 3 "
        "before the rest of the investigation queries ran"
    )
    assert "set +e" in body
    assert "DIAGNOSTICS: done" in body
    assert "to_regclass('public.vw_b3_share_count_event')" in body


def test_diagnostics_catalog_key_is_version():
    body = _step("Diagnostics")["run"]
    assert "api.catalog()->>'version'" in body
    assert "->>'catalog_version'" not in body


def test_diagnostics_runs_even_when_the_gate_failed():
    step = _step("Diagnostics")
    assert "always()" in str(step.get("if", ""))


def test_health_job_is_read_only():
    spec = _spec()
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "default_transaction_read_only = on" in text
    assert "supabase-ingest" not in str(spec.get("concurrency", {}))
    assert spec["concurrency"]["group"] == "silo-health"


@pytest.mark.parametrize("name", ["Health checks", "Diagnostics"])
def test_step_body_is_valid_bash(name):
    body = _step(name)["run"]
    proc = subprocess.run(
        ["bash", "-n"], input=body, text=True, capture_output=True,
    )
    assert proc.returncode == 0, f"{name} is not valid bash:\n{proc.stderr}"
