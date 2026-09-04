"""src/pipeline/ingest_log — the one cvm_ingest_log writer for ANBIMA, B3 and BACEN.

The BACEN tests (tests/test_bacen_audit_log.py) cover the audited() bracket.
These pin the two properties the ANBIMA and B3 migrations depend on:

  * finish() sends the period key only when the caller passes it, so a
    writer that keyed the start row (B3 cotahist_daily 2026-09) cannot have
    it erased by ON CONFLICT DO UPDATE on finish;
  * a caller can pass its own module's upsert_rows, so the per-pipeline
    mocks the test-suite already uses capture audit rows too — without it the
    real client's 75 s retry ladder ran against a MagicMock.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from src.pipeline import ingest_log


def _capture():
    rows: List[Dict[str, Any]] = []

    def upsert(client, table, sent, **kw):
        assert table == "cvm_ingest_log" and kw.get("conflict_columns") == "run_id"
        rows.extend(sent)
        return len(sent)

    return rows, upsert


def test_finish_without_a_period_leaves_the_key_alone():
    rows, upsert = _capture()
    ingest_log.finish(MagicMock(), "r1", "b3", "cotahist_daily", status="ok", rows=5, upsert=upsert)
    (row,) = rows
    assert "period_year" not in row and "period_month" not in row
    assert "started_at" not in row
    assert row["status"] == "ok" and row["rows_upserted"] == 5 and row["error_msg"] is None


def test_finish_with_a_period_carries_it_for_the_self_healing_insert():
    rows, upsert = _capture()
    ingest_log.finish(MagicMock(), "r1", "bacen", "sgs", status="error", rows=0,
                      error="TimeoutError", period_year=2026, period_month=8, upsert=upsert)
    (row,) = rows
    assert (row["period_year"], row["period_month"]) == (2026, 8)


def test_start_row_shape(ingest_log_columns):
    rows, upsert = _capture()
    ingest_log.start(MagicMock(), "r1", "b3", "cotahist_yearly", period_year=2025, upsert=upsert)
    (row,) = rows
    assert row["status"] == "running" and row["rows_upserted"] == 0
    assert (row["period_year"], row["period_month"]) == (2025, None)
    assert set(row) <= ingest_log_columns


def test_default_writer_is_pg_client_upsert_rows():
    with patch("src.pipeline.ingest_log.upsert_rows") as up:
        ingest_log.start(MagicMock(), "r1", "anbima_etf", "boletim_mensal")
        ingest_log.finish(MagicMock(), "r1", "anbima_etf", "boletim_mensal", status="ok", rows=1)
    assert up.call_count == 2


def test_statuses_are_the_three_the_gates_read():
    for status in ("ok", "error", "skipped"):
        rows, upsert = _capture()
        ingest_log.finish(MagicMock(), "r1", "b3", "cotahist_daily", status=status, rows=0, upsert=upsert)
        assert rows[0]["status"] == status


def test_anbima_and_b3_route_through_the_shared_writer():
    """Source-text guard: no pipeline but CVM may build a cvm_ingest_log row by hand."""
    from pathlib import Path
    for name in ("anbima_pipeline.py", "b3_pipeline.py", "bacen_pipeline.py"):
        body = Path("src/pipeline").joinpath(name).read_text(encoding="utf-8")
        assert '"cvm_ingest_log"' not in body, f"{name} writes cvm_ingest_log directly"
        assert "ingest_log" in body
