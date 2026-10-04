"""A manual `mode=daily` dispatch is the scheduled run, not a subset of it.

Daily CVM Ingest 33798733736 (2026-09-03, `workflow_dispatch` mode=daily on
main) ingested 3,185,854 rows and landed the day's ETF snapshot — and then
skipped "Analyze tables post-ingest" and "Build / refresh analytical layer",
because both steps were gated on `schedule` or `analytics-only` only. An
operator who dispatches `daily` to re-run the morning pipeline (the reason it
exists) got the data without the refresh that makes it visible.

These tests parse the workflow and pin which modes reach each post-ingest
step, so the gating cannot silently drift again.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DAILY = ROOT / ".github/workflows/daily_ingest.yml"

yaml = pytest.importorskip("yaml")


def _step(name: str) -> dict:
    spec = yaml.safe_load(DAILY.read_text())
    return next(s for s in spec["jobs"]["ingest"]["steps"] if s.get("name") == name)


def _condition(name: str) -> str:
    return str(_step(name).get("if", ""))


@pytest.mark.parametrize("name", ["Analyze tables post-ingest", "Build / refresh analytical layer"])
def test_post_ingest_steps_run_on_schedule(name):
    assert "github.event_name == 'schedule'" in _condition(name)


@pytest.mark.parametrize("name", ["Analyze tables post-ingest", "Build / refresh analytical layer"])
def test_post_ingest_steps_run_on_a_manual_daily_dispatch(name):
    """Run 33798733736: mode=daily ingested 3.19M rows, then skipped both."""
    assert "github.event.inputs.mode == 'daily'" in _condition(name), (
        f"{name!r} must run after a workflow_dispatch mode=daily, exactly as after "
        "the 06:00 schedule — a manual daily is the same pipeline, not a subset"
    )


@pytest.mark.parametrize("name", ["Analyze tables post-ingest", "Build / refresh analytical layer"])
def test_post_ingest_steps_run_on_analytics_only(name):
    assert "github.event.inputs.mode == 'analytics-only'" in _condition(name)


def test_analytical_refresh_is_not_continue_on_error():
    """It was once, and that hid 04_fact_fund_monthly.sql failing on every apply."""
    assert not _step("Build / refresh analytical layer").get("continue-on-error", False)


def test_readme_describes_daily_as_the_full_pipeline():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "`daily` is the scheduled" in text and "ANALYZE and analytical refresh included" in text


def test_cash_dividend_history_is_a_dispatch_mode_that_uses_the_secret():
    """The one-off history load runs in Actions, with the POSTGRES_URL secret,
    after the shared schema apply that creates b3_cash_dividend."""
    spec = yaml.safe_load(DAILY.read_text())
    modes = spec[True]["workflow_dispatch"]["inputs"]["mode"]["options"]
    assert "b3-cash-dividends" in modes
    names = [s.get("name") for s in spec["jobs"]["ingest"]["steps"]]
    step = "Run B3 cash-dividend history backfill"
    assert names.index("Apply schema + migrations") < names.index(step)
    assert "mode == 'b3-cash-dividends'" in _condition(step)
    assert "--b3-cash-dividends-only" in _step(step)["run"]
    assert "mode == 'b3-cash-dividends'" not in _condition("Run daily update")


# --- #473: a red source must not block analytics and publish --------------------

_SCHEMA = "Apply schema + migrations"
_DAILY = "Run daily update"
_ANALYZE = "Analyze tables post-ingest"
_APPLY = "Build / refresh analytical layer"
_HOOK = "Trigger dashboard rebuild (Vercel deploy hook)"


def _wf_steps() -> list:
    return yaml.safe_load(DAILY.read_text())["jobs"]["ingest"]["steps"]


def test_decoupled_steps_have_ids_the_conditions_read():
    ids = {s["name"]: s.get("id") for s in _wf_steps() if "name" in s}
    assert ids[_SCHEMA] == "schema"
    assert ids[_DAILY] == "daily"
    assert ids[_APPLY] == "analytical"


@pytest.mark.parametrize("name", [_ANALYZE, _APPLY])
def test_analyze_and_apply_run_after_a_failed_daily_update(name):
    """A red source used to skip both through the implicit success()."""
    cond = _condition(name)
    assert "!cancelled()" in cond, "without a status function GitHub adds success()"
    assert "steps.daily.outcome == 'failure'" in cond


@pytest.mark.parametrize("name", [_ANALYZE, _APPLY])
def test_analyze_and_apply_still_skip_when_the_schema_step_failed(name):
    """A failed probe or schema apply leaves the schema step failed or skipped."""
    assert "steps.schema.outcome == 'success'" in _condition(name)


@pytest.mark.parametrize("name", [_ANALYZE, _APPLY])
def test_a_failed_backfill_mode_step_still_skips_analyze_and_apply(name):
    """Only the daily update's failure is let through; success() covers the rest."""
    assert "|| success()" in _condition(name)


def test_the_hook_runs_after_a_failed_daily_update_but_not_a_failed_apply():
    cond = _condition(_HOOK)
    assert "!cancelled()" in cond
    assert "steps.analytical.outcome == 'success'" in cond
    assert "steps.daily" not in cond
    assert _step(_HOOK).get("continue-on-error") is True


def test_the_daily_update_stays_red_when_a_source_fails():
    """The run must stay red: the tracking issue and DB Health hang off it."""
    assert not _step(_DAILY).get("continue-on-error", False)
    assert not _step(_APPLY).get("continue-on-error", False)


def test_the_ordering_the_conditions_rely_on():
    names = [s.get("name") for s in _wf_steps()]
    order = [names.index(n) for n in (_SCHEMA, _DAILY, _ANALYZE, _APPLY, _HOOK)]
    assert order == sorted(order)
