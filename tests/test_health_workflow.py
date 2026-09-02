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


def test_ingest_errors_ignore_historical_backfill_outside_daily_window():
    """DB Health #14: hist CDA backfill errors must not fail warehouse health.

    Run 33507857471 failed on 31 unhealed fi/cda_cotas 2010-2022 yearly and
    fi/cda_acoes 2025-12..2026-08 slices after a CVMHostUnreachable backfill.
    Completeness, catalog v17, and the anon API check all passed. Daily ingest
    #203 on that SHA was analytics-only; even a real daily run never retries
    those years. Restrict the fail set to slices daily_update would retry.
    """
    spec = _spec()
    env = spec["jobs"]["health"]["env"]
    assert env["DAILY_LOOKBACK_MONTHS"] == "4", (
        "must match CVM_DAILY_LOOKBACK_MONTHS default; a tighter window would "
        "miss in-window daily failures, a looser one re-counts hist backfill"
    )
    body = _step("Health checks")["run"]
    assert "make_date(e.period_year, e.period_month, 1)" in body
    assert "date_trunc('month', CURRENT_DATE)" in body
    assert "EXTRACT(YEAR FROM CURRENT_DATE)::int" in body
    assert "e.period_year IS NULL" in body
    assert body.count("make_date(e.period_year, e.period_month, 1)") >= 2, (
        "count query and the evidence SELECT must agree on the daily window"
    )
    # The fail signal names the daily window so a future edit cannot silently
    # revert to counting every historical error row.
    assert "daily window" in body


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


def test_ingest_error_query_failure_does_not_print_recovered():
    """A broken count query must not fall through to the green recovered line."""
    body = _step("Health checks")["run"]
    assert "did not return a count" in body
    assert 'elif [ "${errs:-0}" -gt 0 ]' in body, (
        "zeroing errs and continuing prints both ❌ query failed and ✅ recovered"
    )


def test_plan_disk_gb_is_a_real_provisioned_allowance():
    spec = _spec()
    env = spec["jobs"]["health"]["env"]
    # Empty was correct while no real number was known: 8 GB (the Pro *included*
    # quota) against a 71.9 GB database printed 899% and trained everyone to
    # ignore the line. 135 GB is the provisioned disk, so the percentage now
    # means something. It must stay a positive number, never a placeholder.
    raw = env["PLAN_DISK_GB"]
    assert raw not in ("", None), "an allowance was set; do not silently revert to empty"
    assert float(raw) > 0
    # Guard the specific failure mode: the included quota is not the allowance.
    assert float(raw) >= 100, "8 GB is the included quota, not the provisioned disk"
    body = _step("Health checks")["run"]
    # The empty-allowance branch must survive, so unsetting it degrades to
    # absolute-size reporting rather than dividing by nothing.
    assert 'if [ -n "${PLAN_DISK_GB:-}" ]' in body
    assert "do not drop landing tables" in body.lower()


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


# ---------------------------------------------------------------------------
# The public surface is checked over HTTPS as anon, not over psql as the owner.
#
# On 2026-08-29 every api.* function and view returned 42501 to the publishable
# key for hours, while the owner-path checks in this same workflow kept
# passing — they connect as the table owner, which bypasses grants. A
# privilege regression is invisible to owner-path SQL by construction.
# ---------------------------------------------------------------------------


def _anon_step():
    return _step("Public API reachable as anon")


def test_public_api_is_probed_as_anon_over_https():
    step = _anon_step()
    body = step["run"]
    # The whole point: an HTTP request carrying the publishable key, not psql.
    assert "apikey: $key" in body
    assert "psql" not in body, (
        "this check must not use psql — connecting as the owner bypasses the "
        "grants whose loss it exists to detect"
    )
    for route in ("rpc/coverage", "rpc/catalog", "quotes?limit=1", "funds?limit=1"):
        assert route in body, f"{route} is part of the documented surface"


def test_public_api_check_runs_even_when_the_db_checks_fail():
    # A DB-side failure must not mask the public surface, and this step needs
    # no secret, so it must not inherit the implicit success() gate.
    assert _anon_step()["if"] == "always()"


def test_landing_tables_are_verified_closed_against_production():
    """The standing rule, checked live rather than inferred from the SQL."""
    body = _anon_step()["run"]
    assert "Accept-Profile: public" in body, (
        "landing tables are only reachable under the public profile; without "
        "this header the check proves nothing about them"
    )
    for table in ("cvm_fi_diario", "b3_cotahist", "cia_account", "bacen_sgs"):
        assert table in body
    assert "is READABLE by anon" in body


def test_public_api_check_fails_the_job_rather_than_warning():
    body = _anon_step()["run"]
    # Disk warns because it needs human judgement. An unreachable API, or
    # exposed landing data, is unambiguous — it must go red.
    assert 'echo "PUBLIC API: FAIL"; exit 1' in body


def test_publishable_key_has_a_single_source():
    """Read from skill.md, never pasted in.

    The key is already published in skill.md and api-docs/. Duplicating it
    here would add another copy to rotate, and a stale copy would leave this
    check silently probing a dead credential instead of failing loudly.
    """
    body = _anon_step()["run"]
    assert "grep -oE 'sb_publishable_[A-Za-z0-9_]+' skill.md" in body
    assert "sb_publishable__" not in body, "do not paste the key into the workflow"


# --- 15_unhealed_ingest_errors.sql -----------------------------------------
#
# #174 narrowed check 1 so it fails only on slices daily_update would retry.
# That is correct — daily never probes 2005, so alarming on a 2005 slice every
# 26 hours is a red light only a backfill can clear. But it left the run
# printing "0 (of 7 error rows)" with no way to see the 7. Diagnostic 15 is
# that view. It restates the daily-window predicate as a literal, because
# `psql -f` gets no variables, so the two definitions can drift silently
# unless something holds them together. These tests are that something.

DIAG_BACKLOG = DIAG_DIR / "15_unhealed_ingest_errors.sql"


def _lookback_months() -> int:
    return int(_spec()["jobs"]["health"]["env"]["DAILY_LOOKBACK_MONTHS"])


def test_the_ingest_backlog_diagnostic_exists():
    assert DIAG_BACKLOG.exists(), (
        "check 1 no longer fails on historical slices; without this file the "
        "backlog is invisible as well as non-fatal"
    )


def test_backlog_diagnostic_uses_the_workflows_own_lookback():
    """The literal must equal DAILY_LOOKBACK_MONTHS - 1, as in health.yml."""
    sql = DIAG_BACKLOG.read_text(encoding="utf-8")
    expected = f"- {_lookback_months() - 1} * INTERVAL '1 month'"
    assert expected in sql, (
        f"diagnostic 15 must offset by {expected!r} to match health.yml's "
        f"DAILY_LOOKBACK_MONTHS={_lookback_months()}; otherwise the gate and "
        "the backlog view disagree about what the daily window is"
    )


def test_backlog_diagnostic_defines_unhealed_exactly_as_check_1_does():
    """A slice is healed by a later ok OR skipped row, matched NULL-safely."""
    sql = DIAG_BACKLOG.read_text(encoding="utf-8")
    check1 = _step("Health checks")["run"]
    for clause in (
        "s.status IN ('ok', 'skipped')",
        "s.entity       IS NOT DISTINCT FROM e.entity",
        "s.doc_type     IS NOT DISTINCT FROM e.doc_type",
        "s.period_year  IS NOT DISTINCT FROM e.period_year",
        "s.period_month IS NOT DISTINCT FROM e.period_month",
        "s.started_at   > e.started_at",
    ):
        assert clause in sql, f"diagnostic 15 is missing {clause!r}"
        assert clause in check1, f"check 1 no longer contains {clause!r} — resync diagnostic 15"


def test_backlog_diagnostic_is_read_only():
    """It runs against production. Nothing in it may write.

    Comments are stripped first: the header explains daily_update, and a
    substring match on prose would fail on the word rather than on a statement.
    """
    body = "\n".join(
        line.split("--", 1)[0]
        for line in DIAG_BACKLOG.read_text(encoding="utf-8").splitlines()
    ).upper()
    for verb in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "CREATE ", "TRUNCATE "):
        assert verb not in body, f"diagnostic 15 must not contain {verb.strip()}"
