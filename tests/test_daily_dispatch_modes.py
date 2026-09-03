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
