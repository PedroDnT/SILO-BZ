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


# --- check 4b: a negative lag is healthy -----------------------------------
#
# Run 33666142198 failed with "fact_fund_monthly did not answer (missing,
# unpopulated, or empty)" about a matview that had been rebuilt 44 minutes
# earlier and answered -31. The fact table aggregates cvm_fi_diario, which the
# daily fills through the CURRENT month, while latest_complete_period('fi')
# counts only complete months — so a freshly built matview is one calendar
# month AHEAD, and `[ "$lag" -ge 0 ]` sent that into the not-queryable branch.
#
# These tests RUN the block rather than reading it. The defect was in shell
# control flow, which a substring assertion cannot see.

import subprocess
import tempfile


def _run_check_4b(lag_value: str) -> tuple[int, str, str]:
    """Execute check 4b's branch with a given $lag. Returns (fail, stderr, summary)."""
    body = _step("Health checks")["run"]
    start = body.index('if ! printf \'%s\' "${lag:-}"')
    end = body.index("\n", body.index("fi", body.index("fact_fund_monthly fresh ($lag days behind")))
    block = body[start:end]
    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False) as summary:
        summary_path = summary.name
    script = (
        f'set -u\nfail=0\nlag="{lag_value}"\n'
        f'GITHUB_STEP_SUMMARY="{summary_path}"\n'
        f"{block}\n"
        'echo "FAILFLAG=$fail"\n'
    )
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    fail = int(proc.stdout.split("FAILFLAG=")[1].strip())
    with open(summary_path) as fh:
        return fail, proc.stderr, fh.read()


class TestFactFundMonthlyLagBranch:
    def test_one_month_ahead_is_healthy(self):
        """-31: the exact value run 33666142198 failed on."""
        fail, stderr, summary = _run_check_4b("-31")
        assert fail == 0, f"a rebuilt matview must not fail the gate: {stderr}"
        assert "✅" in summary
        assert "in-progress month" in summary
        assert "did not answer" not in stderr

    def test_a_short_month_ahead_is_healthy(self):
        """February gives -28. The whole legitimate band must pass."""
        for lag in ("-28", "-29", "-30"):
            fail, _, _ = _run_check_4b(lag)
            assert fail == 0, f"lag={lag} must pass"

    def test_equal_periods_are_healthy(self):
        fail, _, summary = _run_check_4b("0")
        assert fail == 0 and "✅" in summary

    def test_within_a_month_behind_is_healthy(self):
        fail, _, summary = _run_check_4b("31")
        assert fail == 0 and "✅" in summary

    def test_stale_still_fails_with_the_stale_message(self):
        """The 2026-08-30 bug this check was built for."""
        fail, stderr, summary = _run_check_4b("45")
        assert fail == 1
        assert "45 days behind" in stderr
        assert "04_fact_fund_monthly.sql" in stderr
        assert "stale by 45 days" in summary

    def test_more_than_a_month_ahead_fails_as_future_dated(self):
        """Two months ahead is not an in-progress month; it is a bad DT_COMPTC."""
        fail, stderr, summary = _run_check_4b("-61")
        assert fail == 1
        assert "61 days AHEAD" in stderr
        assert "DT_COMPTC" in stderr
        assert "future-dated" in summary

    def test_a_genuinely_absent_answer_still_says_so(self):
        """An empty $lag must keep the not-queryable message — the branch is real."""
        fail, stderr, summary = _run_check_4b("")
        assert fail == 1
        assert "did not answer" in stderr
        assert "not queryable" in summary

    def test_psql_error_text_is_not_read_as_a_number(self):
        fail, stderr, _ = _run_check_4b("ERROR:relationdoesnotexist")
        assert fail == 1
        assert "did not answer" in stderr

    def test_the_two_failure_modes_have_different_messages(self):
        """Conflating them is what produced the wrong diagnosis in the first place."""
        _, absent, _ = _run_check_4b("")
        _, ahead, _ = _run_check_4b("-61")
        assert "did not answer" in absent and "did not answer" not in ahead


# --- check 4c: bacen_sgs daily series must keep moving -----------------------
#
# 2026-09-03: both daily runs logged `bacen_sgs: 0` and stayed green. Check 2
# saw ingest activity (CVM rows land), check 3 judges CVM completeness only,
# and nothing looked at bacen_sgs. These tests pin the gate's shape and RUN
# its branch, as the 4b tests do, because the failure modes are shell control
# flow.

DIAG_SGS = DIAG_DIR / "17_bacen_sgs_freshness_by_series.sql"


def test_sgs_gate_judges_only_the_daily_series():
    body = _step("Health checks")["run"]
    i = body.index("# 4c. BACEN SGS freshness")
    section = body[i: body.index("# 5. Disk.", i)]
    assert "FROM bacen_sgs WHERE series_code IN (11, 12)" in section, (
        "CDI (12) and SELIC_DIARIA (11) are the only series that publish every "
        "business day; a monthly series in this gate would fire every month"
    )
    assert "MAX_SGS_AGE_DAYS" in section
    assert "fail=1" in section


def test_sgs_age_limit_is_a_workflow_knob():
    spec = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    env = spec["jobs"]["health"]["env"]
    assert int(env["MAX_SGS_AGE_DAYS"]) >= 5, "must absorb a long weekend plus a holiday"
    assert int(env["MAX_SGS_AGE_DAYS"]) <= 10, "beyond this the refresh has been failing for a week"


def test_sgs_diagnostic_exists_and_is_read_only():
    assert DIAG_SGS.exists()
    body = " ".join(
        line for line in DIAG_SGS.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("--")
    ).upper()
    for verb in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "CREATE ", "TRUNCATE "):
        assert verb not in body, f"diagnostic 17 must not contain {verb.strip()}"
    assert "BACEN_SGS" in body and "GROUP BY" in body


def _run_check_4c(age_value: str, limit: str = "7") -> tuple[int, str, str]:
    """Execute check 4c's branch with a given $sgs_age. Returns (fail, stderr, summary)."""
    body = _step("Health checks")["run"]
    start = body.index('if ! printf \'%s\' "${sgs_age:-}"')
    end = body.index("\n", body.index("fi", body.index("bacen_sgs fresh ($sgs_age days")))
    block = body[start:end]
    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False) as summary:
        summary_path = summary.name
    script = (
        f'set -u\nfail=0\nsgs_age="{age_value}"\nMAX_SGS_AGE_DAYS="{limit}"\n'
        f'GITHUB_STEP_SUMMARY="{summary_path}"\n'
        f"{block}\n"
        'echo "FAILFLAG=$fail"\n'
    )
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    fail = int(proc.stdout.split("FAILFLAG=")[1].strip())
    with open(summary_path) as fh:
        return fail, proc.stderr, fh.read()


class TestBacenSgsFreshnessBranch:
    def test_yesterday_is_fresh(self):
        fail, err, summary = _run_check_4c("1")
        assert fail == 0 and "✅ bacen_sgs fresh" in summary and err == ""

    def test_a_long_weekend_is_fresh(self):
        fail, _, summary = _run_check_4c("4")
        assert fail == 0 and "fresh" in summary

    def test_at_the_limit_is_fresh(self):
        fail, _, _ = _run_check_4c("7")
        assert fail == 0

    def test_past_the_limit_fails_as_stale(self):
        """The 2026-09-03 shape: rows exist but nothing new has landed."""
        fail, err, summary = _run_check_4c("12")
        assert fail == 1 and "12 days old" in err and "stale by 12 days" in summary
        assert "did not answer" not in err

    def test_an_empty_table_fails_as_not_queryable(self):
        """max() over no rows is NULL → empty string, which is not a number."""
        fail, err, summary = _run_check_4c("")
        assert fail == 1 and "did not answer" in err and "not queryable" in summary

    def test_psql_error_text_is_not_read_as_a_number(self):
        fail, err, _ = _run_check_4c("ERROR:relationbacen_sgsdoesnotexist")
        assert fail == 1 and "did not answer" in err

    def test_the_limit_comes_from_the_knob(self):
        assert _run_check_4c("9", limit="10")[0] == 0
        assert _run_check_4c("9", limit="8")[0] == 1
