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


yaml = pytest.importorskip("yaml")


def _steps(path: Path, job: str) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"][job]["steps"]


def _names(path: Path, job: str) -> list[str]:
    return [s.get("name") for s in _steps(path, job)]


def _get(path: Path, job: str, name: str) -> dict:
    return next(s for s in _steps(path, job) if s.get("name") == name)


def test_the_daily_job_runs_the_step_after_publishing():
    names = _names(DAILY, "ingest")
    assert names.index("Trigger dashboard rebuild (Vercel deploy hook)") < names.index(STEP), (
        "the step must come after the deploy hook, or a failure could still "
        "keep the dashboard from publishing"
    )
    assert names.index("Build / refresh analytical layer") < names.index(STEP)
    step = _get(DAILY, "ingest", STEP)
    assert step["run"].strip() == "python -m src.pipeline.run_b3_events"
    assert step.get("timeout-minutes"), "a hung proxy must not eat the job's 180 minutes"
    assert not step.get("continue-on-error"), "a failure must still fail the job"


def test_the_step_runs_after_a_failure_but_only_on_a_daily_run():
    cond = str(_get(DAILY, "ingest", STEP).get("if", ""))
    assert "!cancelled()" in cond, "it must run even when an earlier step failed"
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
