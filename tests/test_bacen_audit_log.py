"""BACEN audit rows through the shared writer (src/pipeline/ingest_log).

Integrity rule 3: every ingest writes exactly one audit row. Until 2026-09-03
the BACEN ingestor wrote none; the first version that did (2727240) was the
fourth hand-rolled copy of the helpers and reviewed red on six points. These
tests pin the shared contract instead:

  * running → ok | error per source, keyed on the window's start month;
  * the finish row is written even when the source is cancelled;
  * a failed audit write never fails a landed source and never masks an
    ingest error;
  * the original exceptions survive (ExceptionGroup), with their types in
    error_msg; a partial ingest records the rows that did land;
  * every row's columns exist in cvm_ingest_log;
  * audit writes run off the event loop.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.pipeline.bacen_pipeline import LOG_ENTITY, BacenIngestor
from src.pipeline.ingest_log import PartialIngestError, describe

MAIN = threading.main_thread()


class _Capture:
    """Stand-in for upsert_rows: records cvm_ingest_log rows, can fail on demand."""

    def __init__(self, fail_when=None):
        self.rows: List[Dict[str, Any]] = []
        self.threads: List[threading.Thread] = []
        self.fail_when = fail_when or (lambda row: False)

    def __call__(self, client, table, rows, **kw):
        if table == "cvm_ingest_log":
            assert kw.get("conflict_columns") == "run_id"
            (row,) = rows
            self.threads.append(threading.current_thread())
            if self.fail_when(row):
                raise ConnectionError("db went away")
            self.rows.append(row)
        return len(rows)

    def of(self, doc_type, status):
        return [r for r in self.rows if r["doc_type"] == doc_type and r["status"] == status]


def _ingestor(*, sgs=7, ptax=92, exp=1235, sgs_exc=None, ptax_exc=None) -> BacenIngestor:
    with patch("src.pipeline.bacen_pipeline.BacenClient"), \
         patch("src.pipeline.bacen_pipeline.get_pg_client", return_value=MagicMock()):
        ing = BacenIngestor()
    ing.ingest_sgs = AsyncMock(side_effect=sgs_exc) if sgs_exc else AsyncMock(return_value=sgs)
    ing.ingest_ptax = AsyncMock(side_effect=ptax_exc) if ptax_exc else AsyncMock(return_value=ptax)
    ing.ingest_expectativas = AsyncMock(return_value=exp)
    return ing


def _patched(capture):
    return patch("src.pipeline.ingest_log.upsert_rows", side_effect=capture)


@pytest.mark.asyncio
async def test_backfill_writes_running_then_ok_per_source(ingest_log_columns):
    cap = _Capture()
    with _patched(cap):
        totals = await _ingestor().backfill(start="2026-08-04")

    assert totals == {"bacen_sgs": 7, "bacen_ptax": 92, "bacen_expectativas": 1235}
    assert {r["entity"] for r in cap.rows} == {"bacen"} == {LOG_ENTITY}
    assert {r["doc_type"] for r in cap.rows} == {"sgs", "ptax", "expectativas"}
    for doc_type, n in (("sgs", 7), ("ptax", 92), ("expectativas", 1235)):
        (start,) = cap.of(doc_type, "running")
        (finish,) = cap.of(doc_type, "ok")
        assert start["run_id"] == finish["run_id"], "finish must UPDATE the same row"
        assert (start["period_year"], start["period_month"]) == (2026, 8), (
            "a trailing window is keyed on its start month, so a daily refresh sits in "
            "health check 1's lookback window and a 2019 backfill in the historical backlog"
        )
        assert finish["rows_upserted"] == n and finish["error_msg"] is None
        assert "started_at" not in finish, "resending started_at makes every run look instantaneous"
    assert len({r["run_id"] for r in cap.rows}) == 3
    for row in cap.rows:
        assert set(row) <= ingest_log_columns, f"unknown cvm_ingest_log column(s): {set(row) - ingest_log_columns}"


@pytest.mark.asyncio
async def test_a_deep_backfill_is_keyed_apart_from_the_daily_window():
    cap = _Capture()
    with _patched(cap):
        await _ingestor().backfill(start="2019-01-01")
    assert {(r["period_year"], r["period_month"]) for r in cap.rows} == {(2019, 1)}


@pytest.mark.asyncio
async def test_audit_writes_run_off_the_event_loop():
    cap = _Capture()
    with _patched(cap):
        await _ingestor().backfill(start="2026-08-04")
    assert cap.threads and all(t is not MAIN for t in cap.threads), (
        "a blocking psycopg2 write (and upsert_rows' retry sleeps) on the loop thread "
        "stalls the sibling sources' HTTP fetches"
    )


@pytest.mark.asyncio
async def test_a_failing_source_gets_an_error_row_and_the_originals_are_raised():
    """The 2026-09-03 shape: SGS breaks, PTAX and Expectativas land."""
    cap = _Capture()
    boom = RuntimeError("SGS fetch failed: Download error: code = 433")
    with _patched(cap):
        with pytest.raises(ExceptionGroup) as exc:
            await _ingestor(sgs_exc=boom).backfill(start="2026-08-04")

    assert exc.group_contains(RuntimeError, match="code = 433")
    assert exc.value.exceptions[0] is boom, "the original exception object, with its traceback"
    assert "sgs: RuntimeError: SGS fetch failed" in str(exc.value)
    (err,) = cap.of("sgs", "error")
    assert err["error_msg"] == "RuntimeError: SGS fetch failed: Download error: code = 433"
    assert err["rows_upserted"] == 0 and not cap.of("sgs", "ok")
    assert cap.of("ptax", "ok")[0]["rows_upserted"] == 92
    assert cap.of("expectativas", "ok")[0]["rows_upserted"] == 1235


@pytest.mark.asyncio
async def test_a_bare_exception_still_names_its_type():
    cap = _Capture()
    with _patched(cap):
        with pytest.raises(ExceptionGroup):
            await _ingestor(sgs_exc=TimeoutError()).backfill(start="2026-08-04")
    assert cap.of("sgs", "error")[0]["error_msg"] == "TimeoutError"


@pytest.mark.asyncio
async def test_a_partial_ingest_records_the_rows_that_landed():
    cap = _Capture()
    partial = PartialIngestError("PTAX: 1 of 5 currencies failed; first error: BacenFetchError: ARS", rows=80)
    with _patched(cap):
        with pytest.raises(ExceptionGroup):
            await _ingestor(ptax_exc=partial).backfill(start="2026-08-04")
    (err,) = cap.of("ptax", "error")
    assert err["rows_upserted"] == 80, "the audit must reconcile against bacen_ptax, which has the 80 rows"
    assert err["error_msg"].startswith("PartialIngestError: PTAX: 1 of 5")


@pytest.mark.asyncio
async def test_cancellation_leaves_an_error_row_not_a_permanent_running_one():
    cap = _Capture()
    with _patched(cap):
        with pytest.raises(asyncio.CancelledError):
            await _ingestor(sgs_exc=asyncio.CancelledError()).backfill(start="2026-08-04")
    (err,) = cap.of("sgs", "error")
    assert err["error_msg"] == "CancelledError"
    assert not cap.of("sgs", "running") or len(cap.of("sgs", "running")) == 1


@pytest.mark.asyncio
async def test_error_row_write_failure_does_not_mask_the_ingest_error(caplog):
    cap = _Capture(fail_when=lambda row: row["status"] == "error")
    with _patched(cap), caplog.at_level("WARNING"):
        with pytest.raises(ExceptionGroup) as exc:
            await _ingestor(sgs_exc=RuntimeError("BCB unreachable")).backfill(start="2026-08-04")
    assert exc.group_contains(RuntimeError, match="BCB unreachable")
    assert sum(1 for t in cap.threads) == 6, "start ×3, finish ×3 — the error row WAS attempted"
    assert "could not write the error row" in caplog.text
    assert cap.of("ptax", "ok") and cap.of("expectativas", "ok")


@pytest.mark.asyncio
async def test_start_row_failure_is_a_warning_and_the_finish_row_self_heals(caplog):
    """CVM's stance: the audit table must not be able to stop ingesting."""
    cap = _Capture(fail_when=lambda row: row["status"] == "running" and row["doc_type"] == "ptax")
    ing = _ingestor()
    with _patched(cap), caplog.at_level("WARNING"):
        totals = await ing.backfill(start="2026-08-04")
    assert totals["bacen_ptax"] == 92
    ing.ingest_ptax.assert_awaited_once()
    assert "could not write the running row" in caplog.text
    (finish,) = cap.of("ptax", "ok")
    assert finish["period_year"] == 2026 and finish["period_month"] == 8, (
        "the finish upsert INSERTs when the start never landed, so it must carry the key too"
    )


@pytest.mark.asyncio
async def test_ok_row_failure_never_fails_a_landed_source(caplog):
    cap = _Capture(fail_when=lambda row: row["status"] == "ok" and row["doc_type"] == "sgs")
    with _patched(cap), caplog.at_level("WARNING"):
        totals = await _ingestor().backfill(start="2026-08-04")
    assert totals == {"bacen_sgs": 7, "bacen_ptax": 92, "bacen_expectativas": 1235}
    assert "could not write the ok row" in caplog.text


def test_daily_update_is_gone_and_backfill_is_the_one_entry_point():
    assert not hasattr(BacenIngestor, "daily_update"), "no caller existed; run_daily uses backfill(start=today-30d)"


def test_describe_is_shared_with_cvm():
    from src.pipeline.cvm_pipeline import _describe
    assert _describe is describe
    assert describe(ValueError()) == "ValueError" and describe(ValueError("x")) == "ValueError: x"


def test_ops_dashboard_spines_include_every_audit_entity():
    from pathlib import Path
    for name in ("ops_freshness.sql", "ops_status_by_dataset.sql"):
        body = Path("dashboard/sources/supabase").joinpath(name).read_text(encoding="utf-8")
        for entity in ("'bacen'", "'b3'", "'anbima_etf'"):
            assert entity in body, f"{name} spine omits {entity}: its rows never reach the ops page"
