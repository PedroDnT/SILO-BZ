"""Pins the `needs:` graph of daily_ingest.yml (#868).

The post-hook work (B3 events, rates/market, the FNET register, the ETF
snapshot) is four jobs that need `ingest`, not steps at its tail: the worst case
is the longest job (75 min) instead of the sum. `fnet-diff` needs only the FNET
register, and `notify-failure` must see every job or a red one files no issue.
A change to this graph fails here, so it is made on purpose.
"""
from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

DAILY = Path(__file__).resolve().parents[1] / ".github/workflows/daily_ingest.yml"

POST_HOOK = {
    "b3-events": 75,
    "market-data": 30,
    "fnet-register": 60,
    "etf-market": 60,
}


def _spec() -> dict:
    return yaml.safe_load(DAILY.read_text())


def _needs(job: dict) -> list[str]:
    needs = job.get("needs") or []
    return [needs] if isinstance(needs, str) else list(needs)


def test_the_job_set_is_pinned():
    assert set(_spec()["jobs"]) == {
        "ingest", *POST_HOOK, "fnet-diff", "notify-failure",
    }


def test_ingest_needs_nothing():
    assert _needs(_spec()["jobs"]["ingest"]) == []


@pytest.mark.parametrize("name", sorted(POST_HOOK))
def test_each_post_hook_job_needs_only_ingest(name):
    assert _needs(_spec()["jobs"][name]) == ["ingest"]


def test_fnet_diff_needs_only_the_fnet_register():
    """It waited for the whole ingest job, though it only needs FNET."""
    assert _needs(_spec()["jobs"]["fnet-diff"]) == ["fnet-register"]


def test_notify_failure_sees_every_job():
    jobs = _spec()["jobs"]
    assert set(_needs(jobs["notify-failure"])) == set(jobs) - {"notify-failure"}


@pytest.mark.parametrize("name", sorted(POST_HOOK))
def test_post_hook_jobs_run_after_a_red_ingest_on_the_old_gate(name):
    """The steps were `!cancelled()` on the schedule and mode=daily; so are the jobs."""
    cond = str(_spec()["jobs"][name]["if"])
    assert "!cancelled()" in cond
    assert "github.event_name == 'schedule'" in cond
    assert "github.event.inputs.mode == 'daily'" in cond


@pytest.mark.parametrize("name,minutes", sorted(POST_HOOK.items()))
def test_post_hook_timeouts_keep_the_old_caps(name, minutes):
    assert _spec()["jobs"][name]["timeout-minutes"] == minutes


def test_worst_case_post_hook_wall_time_is_the_longest_job():
    jobs = _spec()["jobs"]
    caps = [jobs[n]["timeout-minutes"] for n in POST_HOOK]
    assert max(caps) == 75
    # Parallel: nothing among them waits for a sibling.
    assert all(_needs(jobs[n]) == ["ingest"] for n in POST_HOOK)


def test_the_run_stays_in_the_supabase_ingest_group_and_never_cancels():
    """The group is the workflow's, so every job holds it until the run ends."""
    spec = _spec()
    assert spec["concurrency"] == {"group": "supabase-ingest", "cancel-in-progress": False}
    for name, job in spec["jobs"].items():
        assert "concurrency" not in job, f"{name}: a job-level group would leave the run's"


def test_ingest_no_longer_carries_the_post_hook_steps():
    names = [s.get("name") for s in _spec()["jobs"]["ingest"]["steps"]]
    for gone in (
        "Refresh B3 corporate events and cash dividends",
        "Refresh rates and market data",
        "Refresh FNET document register",
        "Refresh ETF market snapshot",
    ):
        assert gone not in names
    assert names[-1] == "Fail the run when CVM was unreachable"


def test_each_post_hook_job_runs_its_module():
    jobs = _spec()["jobs"]
    modules = {
        "b3-events": "src.pipeline.run_b3_events",
        "market-data": "src.pipeline.market_pipeline",
        "fnet-register": "src.pipeline.fnet_pipeline",
        "etf-market": "src.pipeline.run_etf_market",
    }
    for job, module in modules.items():
        runs = [s.get("run", "") for s in jobs[job]["steps"]]
        assert f"python -m {module}" in runs, job


def test_only_the_etf_job_sees_the_apify_token():
    jobs = _spec()["jobs"]
    assert "APIFY_TOKEN" in jobs["etf-market"]["env"]
    for name, job in jobs.items():
        if name != "etf-market":
            assert "APIFY_TOKEN" not in (job.get("env") or {}), name
