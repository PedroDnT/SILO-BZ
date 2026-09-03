"""The BACEN ingestor writes one cvm_ingest_log row per source per run.

Integrity rule 3: every ingest writes exactly one audit row. Until
2026-09-03 the BACEN ingestor wrote none — so on the day both daily runs
landed `bacen_sgs: 0` (python-bcb raised on IPCA's 404 and the pipeline
swallowed it), DB Health check 1 and diagnostic 15 had nothing to see.

These tests run backfill()/daily_update() with the three ingest_* methods
mocked and capture what reaches cvm_ingest_log.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.pipeline.bacen_pipeline import LOG_DOC_TYPES, LOG_ENTITY, BacenIngestor


def _ingestor(captured: List[Dict[str, Any]], *, sgs=7, ptax=92, exp=1235,
              sgs_exc: Exception | None = None) -> BacenIngestor:
    def _fake_upsert(client, table, rows, **kw):
        if table == "cvm_ingest_log":
            assert kw.get("conflict_columns") == "run_id"
            captured.extend(rows)
        return len(rows)

    with patch("src.pipeline.bacen_pipeline.BacenClient"), \
         patch("src.pipeline.bacen_pipeline.get_pg_client", return_value=MagicMock()):
        ing = BacenIngestor()
    ing.ingest_sgs = AsyncMock(side_effect=sgs_exc) if sgs_exc else AsyncMock(return_value=sgs)
    ing.ingest_ptax = AsyncMock(return_value=ptax)
    ing.ingest_expectativas = AsyncMock(return_value=exp)
    ing._fake_upsert = _fake_upsert  # keep a handle for the patch below
    return ing


def _rows(captured, doc_type, status):
    return [r for r in captured if r["doc_type"] == doc_type and r["status"] == status]


@pytest.mark.asyncio
async def test_backfill_writes_running_then_ok_per_source():
    captured: List[Dict[str, Any]] = []
    ing = _ingestor(captured)
    with patch("src.pipeline.bacen_pipeline.upsert_rows", side_effect=ing._fake_upsert):
        totals = await ing.backfill(start="2026-08-04")

    assert totals == {"bacen_sgs": 7, "bacen_ptax": 92, "bacen_expectativas": 1235}
    assert {r["entity"] for r in captured} == {LOG_ENTITY} == {"bacen"}
    assert {r["doc_type"] for r in captured} == set(LOG_DOC_TYPES)
    for doc_type, n in (("sgs", 7), ("ptax", 92), ("expectativas", 1235)):
        (start,) = _rows(captured, doc_type, "running")
        (finish,) = _rows(captured, doc_type, "ok")
        assert start["run_id"] == finish["run_id"], "finish must UPDATE the same row"
        assert start["period_year"] is None and start["period_month"] is None, (
            "a trailing window is not a filing month; undated rows sit in health check 1's window"
        )
        assert finish["rows_upserted"] == n
        assert finish["error_msg"] is None
        assert "started_at" not in finish, "resending started_at would make every run look instantaneous"
    assert len({r["run_id"] for r in captured}) == 3, "one run_id per source"


@pytest.mark.asyncio
async def test_a_failing_source_gets_an_error_row_and_the_run_still_fails():
    """The 2026-09-03 shape: SGS breaks, PTAX and Expectativas land."""
    captured: List[Dict[str, Any]] = []
    ing = _ingestor(captured, sgs_exc=RuntimeError("SGS fetch failed: Download error: code = 433"))
    with patch("src.pipeline.bacen_pipeline.upsert_rows", side_effect=ing._fake_upsert):
        with pytest.raises(RuntimeError, match=r"failed for 1 source\(s\) — sgs: SGS fetch failed") as exc:
            await ing.backfill(start="2026-08-04")

    (err,) = _rows(captured, "sgs", "error")
    assert "code = 433" in err["error_msg"] and err["rows_upserted"] == 0
    assert not _rows(captured, "sgs", "ok")
    # the other two sources still ran to completion and recorded ok rows
    assert _rows(captured, "ptax", "ok")[0]["rows_upserted"] == 92
    assert _rows(captured, "expectativas", "ok")[0]["rows_upserted"] == 1235
    ing.ingest_ptax.assert_awaited_once()
    ing.ingest_expectativas.assert_awaited_once()


@pytest.mark.asyncio
async def test_daily_update_is_audited_the_same_way():
    captured: List[Dict[str, Any]] = []
    ing = _ingestor(captured)
    with patch("src.pipeline.bacen_pipeline.upsert_rows", side_effect=ing._fake_upsert):
        await ing.daily_update()
    assert sorted((r["doc_type"], r["status"]) for r in captured) == sorted(
        [(d, s) for d in LOG_DOC_TYPES for s in ("running", "ok")]
    )


@pytest.mark.asyncio
async def test_error_row_write_failure_does_not_mask_the_ingest_error():
    captured: List[Dict[str, Any]] = []
    ing = _ingestor(captured, sgs_exc=RuntimeError("BCB unreachable"))
    calls = {"n": 0}

    def _upsert(client, table, rows, **kw):
        if table == "cvm_ingest_log" and rows[0]["status"] == "error":
            raise ConnectionError("db went away")
        return ing._fake_upsert(client, table, rows, **kw)

    with patch("src.pipeline.bacen_pipeline.upsert_rows", side_effect=_upsert):
        with pytest.raises(RuntimeError, match="BCB unreachable"):
            await ing.backfill(start="2026-08-04")


@pytest.mark.asyncio
async def test_a_start_row_that_cannot_be_written_stops_that_source():
    """Same stance as ANBIMA: a run that cannot record itself does not proceed unrecorded."""
    captured: List[Dict[str, Any]] = []
    ing = _ingestor(captured)

    def _upsert(client, table, rows, **kw):
        if table == "cvm_ingest_log" and rows[0]["doc_type"] == "ptax":
            raise ConnectionError("db went away")
        return ing._fake_upsert(client, table, rows, **kw)

    with patch("src.pipeline.bacen_pipeline.upsert_rows", side_effect=_upsert):
        with pytest.raises(RuntimeError, match="ptax: db went away"):
            await ing.backfill(start="2026-08-04")
    ing.ingest_ptax.assert_not_awaited()
    assert _rows(captured, "sgs", "ok") and _rows(captured, "expectativas", "ok")
