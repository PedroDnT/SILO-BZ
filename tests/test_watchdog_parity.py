"""The watchdog's recovery steps must run what the daily run runs (#689).

watchdog.yml re-states the daily steps it re-runs instead of calling a shared
action: the owner chose that on 2026-10-07 (issue #689, option b), because
the two files differ on purpose in step order, timeouts and `if:` gates, and a
shared action would hide that. These tests pin each recovery step to its twin
in daily_ingest.yml: the command (`run` / `uses` / `with`) and the env the step
sees (job env plus step env) must match. Every intended difference is listed
below with its reason. A difference that is not listed fails, and so does a
daily step that is neither twinned nor listed as not recovered.
"""
from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github/workflows"
DAILY_JOB = "ingest"
WATCHDOG_JOB = "watchdog"

# watchdog step name -> daily_ingest step name.
TWINS = {
    "Checkout repository": "Checkout repository",
    "Set up Python 3.12": "Set up Python 3.12",
    "Install dependencies": "Install dependencies",
    "Probe dados.cvm.gov.br": "Probe dados.cvm.gov.br",
    "Apply schema + migrations": "Apply schema + migrations",
    "Run daily ingest (recovery)": "Run daily update",
    "Refresh rates and market data (recovery)": "Refresh rates and market data",
    "Refresh B3 corporate events and cash dividends (recovery)": (
        "Refresh B3 corporate events and cash dividends"
    ),
}

# Step keys that may differ between twins, each with its reason.
ALLOWED_KEY_DIFFS = {
    "name": "the watchdog marks its steps '(recovery)'.",
    "if": "the watchdog gates on staleness or force; the daily run on schedule or mode.",
    "id": "daily ids feed its later ANALYZE / analytical / deploy gates (#473); the watchdog has none.",
}

# (watchdog step, key) -> reason, for a difference only one pair may have.
# Empty since 2026-10-08: the market step's 30-min cap now matches (owner's call).
ALLOWED_STEP_DIFFS: dict[tuple[str, str], str] = {}

# Daily `ingest` steps the watchdog does not re-run, each with its reason.
NOT_RECOVERED = {
    "Cache apt packages": "a download cache only; it changes no command or result.",
    "Run B3 COTAHIST yearly backfill": "dispatch-only mode b3-backfill, not part of a daily run.",
    "Run B3 cash-dividend history backfill": "dispatch-only mode b3-cash-dividends.",
    "Run B3 consolidated trades backfill": "dispatch-only mode b3-trade-consolidated.",
    "Build balancete summary from stored months": "dispatch-only mode balancete-summary.",
    "Move the CDA fund name out of raw": "dispatch-only mode cda-fund-name.",
    "Rewrite the CDA tables (VACUUM FULL)": "dispatch-only mode cda-vacuum-full.",
    "Analyze tables post-ingest": "recovery heals data only (docs/architecture/OPERATIONS.md).",
    "Build / refresh analytical layer": "recovery heals data only; the next 06:00 run rebuilds it.",
    "Trigger dashboard rebuild (Vercel deploy hook)": "recovery heals data only; it publishes nothing.",
    "Refresh FNET document register": "FNET is not a slice the staleness check watches.",
}

# Watchdog steps with no daily twin, each with its reason.
WATCHDOG_ONLY = {
    "Check ingest staleness": "decides whether to recover at all.",
    "Report no-op": "logs the no-op day.",
}

# Pairs of watchdog steps that run in the opposite order to their daily twins.
ALLOWED_ORDER_DIFFS = {
    ("Install dependencies", "Probe dados.cvm.gov.br"): (
        "the watchdog installs first because the staleness check needs the deps; "
        "the daily run probes before installing anything."
    ),
    ("Refresh rates and market data (recovery)",
     "Refresh B3 corporate events and cash dividends (recovery)"): (
        "the daily run puts market data after the analytical layer so four foreign "
        "hosts cannot skip it; the watchdog has no analytical layer to protect."
    ),
}

# Other daily_ingest jobs the watchdog has no counterpart for.
OTHER_DAILY_JOBS = {
    "fnet-diff": "FNET restatement diffs; not a slice the staleness check watches.",
    "notify-failure": "files the daily-failure tracking issue; a red watchdog run shows on its own.",
}

# Job keys that may differ between the two jobs.
ALLOWED_JOB_KEY_DIFFS = {
    "name": "each job names itself.",
    "timeout-minutes": "the daily job has more steps (analytical layer, FNET) than recovery.",
    "steps": "compared step by step below.",
}


def _load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text())


def _job(workflow: str, job: str) -> dict:
    return _load(workflow)["jobs"][job]


def _steps(job: dict) -> dict[str, dict]:
    out = {}
    for step in job["steps"]:
        name = step.get("name")
        assert name, f"every step needs a name for this test to pair it: {step}"
        assert name not in out, f"duplicate step name {name!r}"
        out[name] = step
    return out


def _normalise(value):
    return value.strip() if isinstance(value, str) else value


def _effective_env(job: dict, step: dict) -> dict:
    return {**(job.get("env") or {}), **(step.get("env") or {})}


def test_both_workflows_share_the_ingest_concurrency_group():
    daily, watchdog = _load("daily_ingest.yml"), _load("watchdog.yml")
    assert daily["concurrency"] == watchdog["concurrency"]


def test_daily_jobs_are_known():
    jobs = set(_load("daily_ingest.yml")["jobs"])
    assert jobs == {DAILY_JOB, *OTHER_DAILY_JOBS}, (
        "a new daily_ingest job: decide whether the watchdog must recover it, "
        "then twin it or list it in OTHER_DAILY_JOBS"
    )


def test_job_settings_match():
    daily = _job("daily_ingest.yml", DAILY_JOB)
    watchdog = _job("watchdog.yml", WATCHDOG_JOB)
    for key in sorted(set(daily) | set(watchdog)):
        if key in ALLOWED_JOB_KEY_DIFFS:
            continue
        assert daily.get(key) == watchdog.get(key), f"job key {key!r} differs"


def test_every_daily_step_is_twinned_or_listed():
    daily = _steps(_job("daily_ingest.yml", DAILY_JOB))
    twinned = set(TWINS.values())
    unlisted = sorted(set(daily) - twinned - set(NOT_RECOVERED))
    assert not unlisted, (
        f"daily steps with no watchdog twin and no reason in NOT_RECOVERED: {unlisted}"
    )
    stale = sorted((twinned | set(NOT_RECOVERED)) - set(daily))
    assert not stale, f"listed daily steps that no longer exist: {stale}"
    assert not twinned & set(NOT_RECOVERED)


def test_every_watchdog_step_is_twinned_or_listed():
    watchdog = _steps(_job("watchdog.yml", WATCHDOG_JOB))
    assert set(watchdog) == set(TWINS) | set(WATCHDOG_ONLY)


@pytest.mark.parametrize("watchdog_name", sorted(TWINS))
def test_twin_runs_the_same_command_with_the_same_env(watchdog_name):
    daily_job = _job("daily_ingest.yml", DAILY_JOB)
    watchdog_job = _job("watchdog.yml", WATCHDOG_JOB)
    d = _steps(daily_job)[TWINS[watchdog_name]]
    w = _steps(watchdog_job)[watchdog_name]

    assert _effective_env(daily_job, d) == _effective_env(watchdog_job, w), (
        f"{watchdog_name!r}: the env differs from its daily twin"
    )
    for key in sorted((set(d) | set(w)) - {"env"}):
        if key in ALLOWED_KEY_DIFFS or (watchdog_name, key) in ALLOWED_STEP_DIFFS:
            continue
        assert _normalise(d.get(key)) == _normalise(w.get(key)), (
            f"{watchdog_name!r}: {key!r} differs from its daily twin; change both "
            "files, or list the difference in this test with its reason"
        )


def test_allowed_step_diffs_are_real():
    daily_job = _job("daily_ingest.yml", DAILY_JOB)
    watchdog_job = _job("watchdog.yml", WATCHDOG_JOB)
    for watchdog_name, key in ALLOWED_STEP_DIFFS:
        d = _steps(daily_job)[TWINS[watchdog_name]]
        w = _steps(watchdog_job)[watchdog_name]
        assert d.get(key) != w.get(key), (
            f"{watchdog_name!r} {key!r} now matches; drop it from ALLOWED_STEP_DIFFS"
        )


def test_twins_keep_the_daily_order_except_the_listed_pairs():
    daily_pos = {
        s["name"]: i for i, s in enumerate(_job("daily_ingest.yml", DAILY_JOB)["steps"])
    }
    watchdog_twins = [
        s["name"] for s in _job("watchdog.yml", WATCHDOG_JOB)["steps"] if s["name"] in TWINS
    ]
    inverted = {
        (a, b)
        for i, a in enumerate(watchdog_twins)
        for b in watchdog_twins[i + 1:]
        if daily_pos[TWINS[a]] > daily_pos[TWINS[b]]
    }
    assert inverted == set(ALLOWED_ORDER_DIFFS), (
        f"order differences {sorted(inverted)} must equal ALLOWED_ORDER_DIFFS; "
        "keep the daily order or list the pair with its reason"
    )


def test_recovery_does_not_rebuild_analytics():
    # docs/architecture/OPERATIONS.md: "The watchdog heals data only."
    text = (WORKFLOWS / "watchdog.yml").read_text()
    assert "apply_analytical" not in text
    assert "VERCEL" not in text.upper()
