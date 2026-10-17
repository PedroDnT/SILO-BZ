"""B3 corporate events, cash dividends and index levels run as their own daily step.

Until 2026-09-30 both ran inside run_daily, where a failure made the process
exit 1. That skipped ANALYZE, the analytical apply and the dashboard deploy hook
for data that had all landed; on 2026-08-29 a corporate-events SSL EOF did
exactly that. They now run in src/pipeline/run_b3_events.py, a step of its own
after the deploy hook, like the FNET register and the market data.

These tests pin the move: the step keeps run_daily's contract (each source runs,
any failure exits 1), the workflow runs it after publishing and the watchdog
can recover it, and run_daily no longer calls either source.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.pipeline.run_b3_events as rb

ROOT = Path(__file__).resolve().parents[1]
DAILY = ROOT / ".github/workflows/daily_ingest.yml"
WATCHDOG = ROOT / ".github/workflows/watchdog.yml"
RUN_DAILY = ROOT / "src/pipeline/run_daily.py"

STEP = "Refresh B3 corporate events and cash dividends"
RECOVERY = "Refresh B3 corporate events and cash dividends (recovery)"


def _ingestor(events=0, cash=0, index=0, trades=None) -> MagicMock:
    """Each arg is a return value, or an Exception to raise."""
    ing = MagicMock()
    trades = {"b3_trade_consolidated": 0} if trades is None else trades
    ing.daily_update_trade_consolidated = AsyncMock(
        side_effect=trades if isinstance(trades, Exception) else None,
        return_value=None if isinstance(trades, Exception) else trades,
    )
    ing.ingest_index_levels = AsyncMock(
        side_effect=index if isinstance(index, Exception) else None,
        return_value=None if isinstance(index, Exception) else index,
    )
    ing.ingest_corporate_events = AsyncMock(
        side_effect=events if isinstance(events, Exception) else None,
        return_value=None if isinstance(events, Exception) else events,
    )
    ing.ingest_cash_dividends = AsyncMock(
        side_effect=cash if isinstance(cash, Exception) else None,
        return_value=None if isinstance(cash, Exception) else cash,
    )
    return ing


@pytest.mark.asyncio
async def test_every_source_runs_and_a_healthy_run_exits_normally():
    ing = _ingestor(events=11664, cash=1107, index=14489)
    with patch.object(rb, "B3Ingestor", return_value=ing):
        await rb.main()  # no SystemExit
    ing.ingest_corporate_events.assert_awaited_once()
    ing.ingest_cash_dividends.assert_awaited_once()
    ing.ingest_index_levels.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_corporate_events_failure_does_not_skip_cash_dividends():
    ing = _ingestor(events=RuntimeError("SSL EOF"))
    with patch.object(rb, "B3Ingestor", return_value=ing):
        with pytest.raises(SystemExit) as exc:
            await rb.main()
    assert exc.value.code == 1
    ing.ingest_cash_dividends.assert_awaited_once()
    ing.ingest_index_levels.assert_awaited_once()


@pytest.mark.asyncio
async def test_an_index_levels_failure_exits_nonzero_after_the_others_ran(caplog):
    ing = _ingestor(index=RuntimeError("results=null for IBOV 2026"))
    with patch.object(rb, "B3Ingestor", return_value=ing):
        with caplog.at_level("ERROR"):
            with pytest.raises(SystemExit) as exc:
                await rb.main()
    assert exc.value.code == 1
    assert "b3_index_levels" in caplog.text
    ing.ingest_corporate_events.assert_awaited_once()
    ing.ingest_cash_dividends.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_cash_dividends_failure_exits_nonzero(caplog):
    ing = _ingestor(cash=RuntimeError("proxy 502"))
    with patch.object(rb, "B3Ingestor", return_value=ing):
        with caplog.at_level("ERROR"):
            with pytest.raises(SystemExit) as exc:
                await rb.main()
    assert exc.value.code == 1
    assert "b3_cash_dividends" in caplog.text


def test_run_daily_no_longer_calls_either_source():
    """If run_daily called them again, a failure there would again skip the
    analytical apply and the deploy hook."""
    src = RUN_DAILY.read_text(encoding="utf-8")
    assert "ingest_corporate_events(" not in src
    assert "ingest_cash_dividends(" not in src
    assert "daily_update_trade_consolidated(" not in src


async def test_a_consolidated_trades_failure_exits_nonzero_after_the_others_ran():
    ing = _ingestor(trades=RuntimeError("no row landed"))
    with patch.object(rb, "B3Ingestor", return_value=ing):
        with pytest.raises(SystemExit):
            await rb.main()
    ing.ingest_corporate_events.assert_awaited_once()
    ing.ingest_index_levels.assert_awaited_once()
    ing.daily_update_trade_consolidated.assert_awaited_once()


async def test_credit_is_disabled_until_the_real_export_is_verified(monkeypatch):
    monkeypatch.delenv("B3_CREDIT_ENABLED", raising=False)
    with patch.object(rb, "B3Ingestor", return_value=_ingestor()), \
         patch.object(rb, "B3CreditIngestor") as credit:
        await rb.main()
    credit.assert_not_called()


async def test_credit_opt_in_runs_and_failure_does_not_skip_other_sources(monkeypatch):
    monkeypatch.setenv("B3_CREDIT_ENABLED", "1")
    ing = _ingestor()
    credit = MagicMock()
    credit.daily_update = AsyncMock(side_effect=RuntimeError("credit export timeout"))
    with patch.object(rb, "B3Ingestor", return_value=ing), \
         patch.object(rb, "B3CreditIngestor", return_value=credit):
        with pytest.raises(SystemExit) as exc:
            await rb.main()
    assert exc.value.code == 1
    credit.daily_update.assert_awaited_once()
    ing.ingest_corporate_events.assert_awaited_once()
    ing.ingest_cash_dividends.assert_awaited_once()
    ing.ingest_index_levels.assert_awaited_once()


yaml = pytest.importorskip("yaml")


def _steps(path: Path, job: str) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"][job]["steps"]


def _names(path: Path, job: str) -> list[str]:
    return [s.get("name") for s in _steps(path, job)]


def _get(path: Path, job: str, name: str) -> dict:
    return next(s for s in _steps(path, job) if s.get("name") == name)


def test_the_daily_job_runs_the_step_after_the_ingest_job():
    """It is the `b3-events` job, which needs `ingest` (and so the deploy hook
    and the analytical apply that end it), not a step at its tail (#868)."""
    spec = yaml.safe_load(DAILY.read_text(encoding="utf-8"))["jobs"]
    assert spec["b3-events"]["needs"] == "ingest"
    assert STEP not in _names(DAILY, "ingest")
    step = _get(DAILY, "b3-events", STEP)
    assert step["run"].strip() == "python -m src.pipeline.run_b3_events"
    assert spec["b3-events"]["timeout-minutes"], "a hung proxy must not hold the run open"
    assert not step.get("continue-on-error"), "a failure must still fail the job"


def test_the_job_runs_after_a_failure_but_only_on_a_daily_run():
    cond = str(yaml.safe_load(DAILY.read_text(encoding="utf-8"))["jobs"]["b3-events"].get("if", ""))
    assert "!cancelled()" in cond, "it must run even when the ingest job failed"
    assert "github.event_name == 'schedule'" in cond
    assert "github.event.inputs.mode == 'daily'" in cond
    assert "analytics-only" not in cond


def test_the_watchdog_can_recover_the_step():
    """Without it, an unhealed corporate_events or cash_dividends error could
    never heal: the watchdog's run_daily no longer touches either source."""
    names = _names(WATCHDOG, "watchdog")
    assert names.index("Run daily ingest (recovery)") < names.index(RECOVERY)
    step = _get(WATCHDOG, "watchdog", RECOVERY)
    assert step["run"].strip() == "python -m src.pipeline.run_b3_events"
    cond = str(step.get("if", ""))
    assert "steps.staleness.outputs.stale == 'true'" in cond
    assert "!cancelled()" in cond


async def test_consolidated_trades_run_before_the_corporate_event_sweep():
    """Run 36842444079: the sweep took 44 of the step's 45 minutes, so nothing
    after it ran. The consolidated trades take seconds and go first."""
    order = []
    ing = _ingestor()
    ing.daily_update_trade_consolidated.side_effect = lambda: order.append("trades") or {}
    ing.ingest_corporate_events.side_effect = lambda: order.append("events") or 0
    with patch.object(rb, "B3Ingestor", return_value=ing):
        await rb.main()
    assert order[:2] == ["trades", "events"]


async def test_the_full_corporate_event_sweep_runs_alone_on_the_same_path():
    """#882: run_backfill --b3-corporate-events-full calls the nightly method
    with full=True, and nothing else (no CVM, no other B3 source)."""
    import argparse

    from src.pipeline import run_backfill as backfill

    ing = MagicMock()
    ing.ingest_corporate_events = AsyncMock(return_value=12)
    args = argparse.Namespace(doc_type=None, b3_corporate_events_full=True)
    with patch.object(backfill, "B3Ingestor", return_value=ing), \
         patch.object(backfill, "CVMIngestor", side_effect=AssertionError("must run alone")):
        await backfill.main(args)
    ing.ingest_corporate_events.assert_awaited_once_with(full=True)
    assert not ing.ingest_cash_dividends.called


async def test_a_full_sweep_that_lands_nothing_exits_red():
    import argparse

    from src.pipeline import run_backfill as backfill

    ing = MagicMock()
    ing.ingest_corporate_events = AsyncMock(return_value=0)
    args = argparse.Namespace(doc_type=None, b3_corporate_events_full=True)
    with patch.object(backfill, "B3Ingestor", return_value=ing):
        with pytest.raises(SystemExit):
            await backfill.main(args)
