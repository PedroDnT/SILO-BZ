"""The CVM probe gates the CVM scope, not the whole daily run (#866).

Before: "Run daily update" inherited success(), so a failed CVM probe skipped
run_daily outright, and with it BACEN, IBGE, ANBIMA, COTAHIST and the B3 BDI
ratchet (a session B3 keeps ~21 business days, then loses). Owner decision
2026-10-13: the probe step records `cvm_ok`, run_daily reads it as
CVM_REACHABLE and skips only the CVM entities (one `skipped` audit row each,
never silently), the non-CVM sources run, and a last step keeps the run red.

Adding plain `!cancelled()` alone would bring back the 40-minute connect loop
the probe was added to stop (2026-08-29): the CVM_REACHABLE skip is what stops it.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import src.pipeline.run_daily as rd
from tests.test_run_daily_failures import _patches

yaml = pytest.importorskip("yaml")

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github/workflows"
PROBE = "Probe dados.cvm.gov.br"
GATE = "Fail the run when CVM was unreachable"
ALL_CVM = {"fi", "fidc", "fip", "fiagro", "fii", "securit", "cia_aberta", "etf"}


# --- run_daily ------------------------------------------------------------


def _run_unreachable(monkeypatch, start=None, finish=None, **patch_kw):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    monkeypatch.setenv("CVM_REACHABLE", "false")
    monkeypatch.setenv("CVM_DAILY_SCOPE", "all")
    p1, p2, p3, p4, cvm, bacen, anbima, b3 = _patches(**patch_kw)
    start = start or MagicMock()
    finish = finish or MagicMock()
    return (p1, p2, p3, p4,
            patch.object(rd.ingest_log, "start", start),
            patch.object(rd.ingest_log, "finish", finish),
            patch("src.store.pg_client.get_pg_client", return_value=MagicMock()),
            ), (cvm, bacen, anbima, b3, start, finish)


async def test_unreachable_cvm_is_skipped_with_one_row_per_entity(monkeypatch):
    ps, (cvm, bacen, anbima, b3, start, finish) = _run_unreachable(monkeypatch)
    with ps[0], ps[1], ps[2], ps[3], ps[4], ps[5], ps[6]:
        await rd.main()  # the workflow's gate step is the alarm, not run_daily

    cvm.daily_update.assert_not_awaited()
    entities = {c.args[2] for c in finish.call_args_list}
    assert entities == ALL_CVM  # the ETF registry (cad_fi) is a CVM entity
    assert {c.args[2] for c in start.call_args_list} == ALL_CVM
    for c in finish.call_args_list:
        assert c.args[3] == rd.CVM_SKIP_DOC_TYPE == "daily_scope"
        assert c.kwargs["status"] == "skipped"
        assert c.kwargs["rows"] == 0
        assert "unreachable" in c.kwargs["error"]
    # Every non-CVM source still ran: BACEN, IBGE, ANBIMA, B3, the BDI ratchet.
    bacen.backfill.assert_awaited()
    anbima.daily_update.assert_awaited()
    b3.daily_update.assert_awaited()
    b3.daily_update_bdi.assert_awaited()


async def test_a_failed_skip_row_fails_the_run_but_not_the_other_sources(monkeypatch):
    """Never skip silently: no audit row means a red run."""
    start = MagicMock(side_effect=RuntimeError("audit table unreachable"))
    ps, (cvm, bacen, anbima, b3, *_x) = _run_unreachable(monkeypatch, start=start)
    with ps[0], ps[1], ps[2], ps[3], ps[4], ps[5], ps[6]:
        with pytest.raises(SystemExit) as exc:
            await rd.main()
    assert exc.value.code == 1
    cvm.daily_update.assert_not_awaited()
    bacen.backfill.assert_awaited()
    b3.daily_update_bdi.assert_awaited()


@pytest.mark.parametrize("value", [None, "", "true", "TRUE"])
async def test_cvm_runs_unless_the_probe_said_false(monkeypatch, value):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    if value is None:
        monkeypatch.delenv("CVM_REACHABLE", raising=False)
    else:
        monkeypatch.setenv("CVM_REACHABLE", value)
    p1, p2, p3, p4, cvm, *_ = _patches()
    finish = MagicMock()
    with p1, p2, p3, p4, patch.object(rd.ingest_log, "finish", finish):
        await rd.main()
    cvm.daily_update.assert_awaited_once()
    finish.assert_not_called()


# --- the workflow step conditions -----------------------------------------


def _steps(workflow: str, job: str) -> list[dict]:
    return yaml.safe_load((WORKFLOWS / workflow).read_text())["jobs"][job]["steps"]


def _by_name(steps: list[dict]) -> dict[str, dict]:
    return {s["name"]: s for s in steps}


CASES = [
    ("daily_ingest.yml", "ingest", "Run daily update"),
    ("watchdog.yml", "watchdog", "Run daily ingest (recovery)"),
]


@pytest.mark.parametrize("workflow,job,daily", CASES)
def test_probe_records_its_answer_and_stays_green(workflow, job, daily):
    probe = _by_name(_steps(workflow, job))[PROBE]
    assert probe["id"] == "cvm_probe"
    run = probe["run"]
    assert "python scripts/check_cvm_reachable.py" in run
    assert 'echo "cvm_ok=true" >> "$GITHUB_OUTPUT"' in run
    assert 'echo "cvm_ok=false" >> "$GITHUB_OUTPUT"' in run
    # Green by construction (if/else), so the schema step's implicit
    # success() still runs it; continue-on-error is not needed.
    assert "continue-on-error" not in probe


@pytest.mark.parametrize("workflow,job,daily", CASES)
def test_run_daily_runs_whatever_the_probe_said(workflow, job, daily):
    steps = _by_name(_steps(workflow, job))
    step = steps[daily]
    cond = step["if"]
    assert cond.startswith("${{ !cancelled() && "), "implicit success() would skip it"
    # The schema gate stays: no ingest against a failed migration.
    assert "steps.schema.outcome == 'success'" in cond
    assert steps["Apply schema + migrations"]["id"] == "schema"
    assert "cvm_probe" not in cond
    assert step["env"]["CVM_REACHABLE"] == "${{ steps.cvm_probe.outputs.cvm_ok }}"


@pytest.mark.parametrize("workflow,job,daily", CASES)
def test_a_failed_probe_still_turns_the_run_red(workflow, job, daily):
    steps = _steps(workflow, job)
    names = [s["name"] for s in steps]
    gate = _by_name(steps)[GATE]
    assert gate["if"] == "${{ !cancelled() && steps.cvm_probe.outputs.cvm_ok == 'false' }}"
    assert "exit 1" in gate["run"]
    assert "continue-on-error" not in gate
    assert names.index(PROBE) < names.index(daily) < names.index(GATE)


def test_the_daily_gate_is_the_last_ingest_step():
    """ANALYZE, the apply and the deploy hook read success(): an earlier red
    step would skip them, which is what #866 exists to stop."""
    names = [s["name"] for s in _steps("daily_ingest.yml", "ingest")]
    assert names[-1] == GATE


def test_the_watchdog_gate_follows_every_recovery_step():
    names = [s["name"] for s in _steps("watchdog.yml", "watchdog")]
    gate = names.index(GATE)
    assert all(names.index(n) < gate for n in names if n.endswith("(recovery)"))


@pytest.mark.parametrize("name", [
    "Apply schema + migrations",
    "Analyze tables post-ingest",
    "Build / refresh analytical layer",
    "Trigger dashboard rebuild (Vercel deploy hook)",
])
def test_steps_after_the_probe_do_not_depend_on_it(name):
    step = _by_name(_steps("daily_ingest.yml", "ingest"))[name]
    assert "cvm_probe" not in str(step.get("if", ""))


def test_the_watchdog_schema_step_does_not_depend_on_the_probe():
    step = _by_name(_steps("watchdog.yml", "watchdog"))["Apply schema + migrations"]
    assert "cvm_probe" not in str(step.get("if", ""))
