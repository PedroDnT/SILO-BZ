"""DB Health and the watchdog see every slice the daily run re-reads (gap 1 of PR #554).

PR #554 made the daily run re-read the four CDA blocks of every month M until
M+5 ends, and last year's FII yearly files from January to March. DB Health
(health.yml checks 1 and 1b) and the watchdog (scripts/check_staleness.py)
counted errors only inside CVM_DAILY_LOOKBACK_MONTHS (4) plus current-year
yearly slices, so a failed re-read of a CDA month at M+4 or M+5, or of a
previous-year FII file in Q1, never turned anything red.

The numbers live once, in src/pipeline/daily_window.py. The pipeline plans from
them, the watchdog runs `daily_window_sql()`, and health.yml restates the same
predicate as its DAILY_WINDOW shell variable; these tests hold the three
together. A 404 on a month CVM has not published is logged 'skipped', which
heals, so the wider window cannot turn CVM's filing calendar into a red run.
"""
from __future__ import annotations

import re
import subprocess
from datetime import date
from pathlib import Path

import pytest

from src.pipeline import cvm_pipeline, daily_window

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/health.yml"
DIAG = ROOT / "scripts/health_diagnostics"


def _health():
    spec = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = spec["jobs"]["health"]
    body = next(s for s in job["steps"] if s.get("name") == "Health checks")["run"]
    return job["env"], body


def _norm(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def test_health_env_equals_the_pipeline_defaults():
    env, _ = _health()
    assert env["DAILY_LOOKBACK_MONTHS"] == str(daily_window.DAILY_LOOKBACK_MONTHS)
    assert env["CDA_REFRESH_MONTHS"] == str(daily_window.CDA_REFRESH_MONTHS)
    assert env["FII_PREVIOUS_YEAR_THROUGH_MONTH"] == str(
        daily_window.FII_PREVIOUS_YEAR_THROUGH_MONTH
    )


def test_the_pipeline_reads_the_same_numbers():
    assert cvm_pipeline._CDA_DOC_TYPES == daily_window.CDA_DOC_TYPES
    # Unless the environment overrides them, which no workflow does.
    assert cvm_pipeline._CDA_REFRESH_MONTHS == daily_window.CDA_REFRESH_MONTHS
    assert cvm_pipeline._DAILY_LOOKBACK_MONTHS == daily_window.DAILY_LOOKBACK_MONTHS
    for wf in (ROOT / ".github/workflows").glob("*.yml"):
        text = wf.read_text(encoding="utf-8")
        assert "CVM_CDA_REFRESH_MONTHS" not in text, wf.name
        assert "CVM_DAILY_LOOKBACK_MONTHS:" not in text, wf.name


def test_health_window_is_the_watchdogs_predicate():
    """Expand health.yml's DAILY_WINDOW with bash and compare it to daily_window_sql()."""
    env, body = _health()
    start = body.index('DAILY_WINDOW="(')
    definition = body[start: body.index(')"', start) + 2]
    out = subprocess.run(
        ["bash", "-c", f'set -u\n{definition}\nprintf %s "$DAILY_WINDOW"'],
        capture_output=True, text=True, check=True,
        env={k: str(v) for k, v in env.items() if k in (
            "DAILY_LOOKBACK_MONTHS", "CDA_REFRESH_MONTHS", "FII_PREVIOUS_YEAR_THROUGH_MONTH")},
    ).stdout
    expected = daily_window.daily_window_sql("e") % daily_window.daily_window_params()
    assert _norm(out) == _norm(expected)


def test_checks_1_and_1b_all_use_the_window():
    _, body = _health()
    assert body.count("AND ${DAILY_WINDOW}") == 3, (
        "check 1's count, its evidence SELECT and check 1b must share one window"
    )


def test_the_cda_arm_names_exactly_the_four_blocks():
    sql = daily_window.daily_window_sql("e")
    listed = set(re.findall(r"'(cda\w*)'", sql))
    assert listed == set(daily_window.CDA_DOC_TYPES)
    _, body = _health()
    assert set(re.findall(r"'(cda\w*)'", body)) == set(daily_window.CDA_DOC_TYPES)


def test_the_new_arms_are_gated_on_their_entity():
    """Without the entity filter, last year's FIP, SECURIT or CIA backfill errors
    would turn Health red every January to March."""
    sql = _norm(daily_window.daily_window_sql("e"))
    assert "e.entity = 'fi' AND e.doc_type IN (" in sql
    assert ("e.entity = 'fii' AND e.period_month IS NULL AND e.period_year = "
            "EXTRACT(YEAR FROM CURRENT_DATE)::int - 1 AND "
            "EXTRACT(MONTH FROM CURRENT_DATE)::int <= %s::int") in sql
    assert sql.count("%s") == len(daily_window.daily_window_params())


def _months_back(today: date, n: int) -> tuple:
    y, m = today.year, today.month - n
    while m <= 0:
        m, y = m + 12, y - 1
    return (y, m)


@pytest.mark.parametrize("today", [date(2026, 10, 3), date(2027, 2, 10), date(2026, 1, 1)])
def test_the_cda_bound_is_the_oldest_month_the_pipeline_rereads(today):
    """The SQL keeps months >= this month minus CDA_REFRESH_MONTHS (not minus N-1)."""
    oldest = cvm_pipeline._cda_refresh_months(today)[0]
    assert oldest == _months_back(today, daily_window.CDA_REFRESH_MONTHS)
    assert "- %s::int * INTERVAL '1 month'" in daily_window.daily_window_sql()


@pytest.mark.parametrize("today, previous", [
    (date(2027, 1, 2), True), (date(2027, 3, 31), True), (date(2027, 4, 1), False),
])
def test_the_fii_bound_follows_the_pipeline(today, previous):
    years = cvm_pipeline._fii_daily_years(today)
    assert (today.year - 1 in years) is previous
    assert (today.month <= daily_window.FII_PREVIOUS_YEAR_THROUGH_MONTH) is previous


def test_the_watchdog_runs_the_shared_predicate():
    import inspect
    import scripts.check_staleness as cs

    assert cs._DAILY_WINDOW_SQL == daily_window.daily_window_sql("e")
    for fn in (cs.unhealed_error_slices, cs.stuck_running_slices):
        src = inspect.getsource(fn)
        assert "_DAILY_WINDOW_SQL" in src and "daily_window_params()" in src


@pytest.mark.parametrize("name", ["15_unhealed_ingest_errors.sql", "18_stuck_running_rows.sql"])
def test_the_diagnostics_see_the_same_window(name):
    """psql -f gets no variables, so the diagnostics carry the numbers as literals."""
    sql = (DIAG / name).read_text(encoding="utf-8")
    assert f"- {daily_window.CDA_REFRESH_MONTHS} * INTERVAL '1 month'" in sql
    assert f"<= {daily_window.FII_PREVIOUS_YEAR_THROUGH_MONTH}" in sql
    assert set(re.findall(r"'(cda\w*)'", sql)) == set(daily_window.CDA_DOC_TYPES)
    assert "e.entity = 'fii' AND e.period_month IS NULL" in sql
