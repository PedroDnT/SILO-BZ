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


# ---------------------------------------------------------------------------
# Lineage (migration 44): which code produced the slice
# ---------------------------------------------------------------------------

SHA = "0123456789abcdef0123456789abcdef01234567"


def test_start_and_finish_stamp_the_commit_and_parser_version(monkeypatch, ingest_log_columns):
    monkeypatch.setenv("GITHUB_SHA", SHA)
    rows, upsert = _capture()
    ingest_log.start(MagicMock(), "r1", "b3", "cotahist_daily", upsert=upsert)
    ingest_log.finish(MagicMock(), "r1", "b3", "cotahist_daily", status="ok", rows=1, upsert=upsert)
    assert len(rows) == 2
    for row in rows:
        assert row["git_sha"] == SHA
        assert row["parser_version"] == ingest_log.PARSER_VERSION
        assert set(row) <= ingest_log_columns


def test_git_sha_is_null_when_unset_never_invented(monkeypatch):
    """A local run has no GITHUB_SHA. The column stays NULL: no rev-parse of
    whatever checkout is on disk, no placeholder."""
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    assert ingest_log.lineage() == {"git_sha": None, "parser_version": ingest_log.PARSER_VERSION}
    monkeypatch.setenv("GITHUB_SHA", "   ")
    assert ingest_log.lineage()["git_sha"] is None


def test_a_value_that_is_not_a_commit_name_is_not_recorded(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "main")
    assert ingest_log.lineage()["git_sha"] is None
    monkeypatch.setenv("GITHUB_SHA", SHA.upper())
    assert ingest_log.lineage()["git_sha"] == SHA, "case-normalised, not rejected"


def test_parser_version_is_an_integer_as_text():
    assert isinstance(ingest_log.PARSER_VERSION, str)
    assert int(ingest_log.PARSER_VERSION) >= 1


def test_cvm_writer_stamps_lineage_on_start_and_finish(monkeypatch):
    """CVM keeps its own writer (an UPSERT on start, an UPDATE on finish);
    both must carry the same lineage as the shared one."""
    from src.pipeline import cvm_pipeline
    from src.pipeline.cvm_pipeline import CVMIngestor

    monkeypatch.setenv("GITHUB_SHA", SHA)
    sent: List[Dict[str, Any]] = []
    monkeypatch.setattr(cvm_pipeline, "upsert_rows",
                        lambda client, table, rows, *a, **k: sent.extend(rows) or len(rows))
    ing = CVMIngestor.__new__(CVMIngestor)
    cur = MagicMock()
    cur.__enter__ = lambda s: s
    cur.__exit__ = MagicMock(return_value=False)
    ing._supabase = MagicMock()
    ing._supabase.cursor.return_value = cur
    ing._log_start("r1", "fidc", "inf_mensal", 2026, 8)
    (row,) = sent
    assert (row["git_sha"], row["parser_version"]) == (SHA, ingest_log.PARSER_VERSION)

    ing._log_finish("r1", 7)
    sql, params = cur.execute.call_args[0]
    assert "git_sha=%s, parser_version=%s" in sql
    assert params[0] == 7 and params[1] == "ok"
    assert params[4:6] == (SHA, ingest_log.PARSER_VERSION)
    assert params[-1] == "r1"


def test_schema_and_migration_44_carry_the_lineage_columns(ingest_log_columns):
    """conftest's INGEST_LOG_COLUMNS is what every writer test checks against;
    it must be exactly the table schema.sql creates, and both new columns
    must reach an EXISTING database from schema.sql alone (guarded ALTER)."""
    import re
    from pathlib import Path

    schema = Path("src/store/schema.sql").read_text(encoding="utf-8")
    body = schema[schema.index("CREATE TABLE IF NOT EXISTS cvm_ingest_log ("):]
    body = body[: body.index("\n);")]
    cols = set()
    for line in body.splitlines()[1:]:
        m = re.match(r"\s+(\w+)\s+[A-Z]", line.split("--", 1)[0])
        if m:
            cols.add(m.group(1))
    assert cols == set(ingest_log_columns)
    alter = ("ALTER TABLE cvm_ingest_log ADD COLUMN IF NOT EXISTS git_sha TEXT, "
             "ADD COLUMN IF NOT EXISTS parser_version TEXT;")
    assert alter in schema
    mig = Path("src/store/migrations/44_ingest_lineage.sql").read_text(encoding="utf-8")
    assert alter in mig


def _cvm_with_cursor(monkeypatch, rowcount):
    """A CVMIngestor whose finish UPDATE reports ``rowcount`` rows matched."""
    from src.pipeline import cvm_pipeline
    from src.pipeline.cvm_pipeline import CVMIngestor

    sent: List[Dict[str, Any]] = []
    monkeypatch.setattr(cvm_pipeline, "upsert_rows",
                        lambda client, table, rows, *a, **k: sent.extend(rows) or len(rows))
    ing = CVMIngestor.__new__(CVMIngestor)
    cur = MagicMock()
    cur.__enter__ = lambda s: s
    cur.__exit__ = MagicMock(return_value=False)
    cur.rowcount = rowcount
    ing._supabase = MagicMock()
    ing._supabase.cursor.return_value = cur
    return ing, sent


def test_cvm_finish_inserts_the_row_when_the_start_row_never_landed(monkeypatch):
    """Rule 3: the start write is best-effort, so the finish UPDATE can match 0
    rows; the slice must still end in a row, keyed with its period."""
    ing, sent = _cvm_with_cursor(monkeypatch, rowcount=0)
    ing._log_start("r1", "fidc", "inf_mensal", 2026, 8)
    sent.clear()  # the start row "never landed"

    ing._log_finish("r1", 7)

    (row,) = sent
    assert row["run_id"] == "r1" and row["status"] == "ok" and row["rows_upserted"] == 7
    assert (row["entity"], row["doc_type"]) == ("fidc", "inf_mensal")
    assert (row["period_year"], row["period_month"]) == (2026, 8)


def test_cvm_finish_fallback_keeps_the_classified_status(monkeypatch):
    """A not-yet-published month is 'skipped' on the fallback row too."""
    ing, sent = _cvm_with_cursor(monkeypatch, rowcount=0)
    ing._log_start("r1", "fi", "diario", 2026, 9)
    sent.clear()

    ing._log_finish("r1", 0, error="Data not found at http://x")

    (row,) = sent
    assert row["status"] == "skipped"
    assert (row["period_year"], row["period_month"]) == (2026, 9)


def test_cvm_finish_writes_no_extra_row_when_the_update_landed(monkeypatch):
    ing, sent = _cvm_with_cursor(monkeypatch, rowcount=1)
    ing._log_start("r1", "fidc", "inf_mensal", 2026, 8)
    sent.clear()

    ing._log_finish("r1", 7)

    assert sent == []


# ── Outcome: a unit of work that does not raise but is not simply "ok" ────────

async def _run_audited(fn):
    """audited() with the audit rows captured; returns (result, finish row)."""
    rows, upsert = _capture()
    result = await ingest_log.audited(MagicMock(), "b3", "events", fn, upsert=upsert)
    running, finish_row = rows
    assert running["status"] == "running"
    return result, finish_row


@pytest.mark.asyncio
async def test_a_bare_row_count_is_still_an_ok_row():
    async def work():
        return 7

    result, row = await _run_audited(work)
    assert result == 7
    assert (row["status"], row["rows_upserted"], row["error_msg"]) == ("ok", 7, None)


@pytest.mark.asyncio
async def test_an_ok_outcome_is_an_ok_row():
    async def work():
        return ingest_log.Outcome(5)

    result, row = await _run_audited(work)
    assert result == 5
    assert (row["status"], row["rows_upserted"]) == ("ok", 5)


@pytest.mark.asyncio
async def test_a_skipped_outcome_returns_normally_and_logs_skipped():
    """A month CVM has not published: not a failure, so nothing raises."""
    async def work():
        return ingest_log.Outcome(0, "skipped", "Data not found at http://x")

    result, row = await _run_audited(work)
    assert result == 0
    assert (row["status"], row["rows_upserted"]) == ("skipped", 0)
    assert row["error_msg"] == "Data not found at http://x"


@pytest.mark.asyncio
async def test_an_error_outcome_logs_error_without_raising():
    """Some issuers failed but the step stays green: the row still says error."""
    async def work():
        return ingest_log.Outcome(3, "error", "2/10 issuers failed; first: boom")

    result, row = await _run_audited(work)
    assert result == 3
    assert (row["status"], row["rows_upserted"]) == ("error", 3)
    assert row["error_msg"] == "2/10 issuers failed; first: boom"


def test_an_outcome_status_outside_the_three_is_refused():
    """'success' is the status coverage and staleness checks silently ignore."""
    with pytest.raises(ValueError, match="success"):
        ingest_log.Outcome(1, "success")


def test_an_ok_outcome_cannot_carry_an_error_message():
    with pytest.raises(ValueError):
        ingest_log.Outcome(1, "ok", "something went wrong")


@pytest.mark.asyncio
async def test_a_bad_outcome_inside_the_work_is_recorded_as_an_error_row_and_raised():
    async def work():
        return ingest_log.Outcome(1, "success")

    rows, upsert = _capture()
    with pytest.raises(ValueError, match="success"):
        await ingest_log.audited(MagicMock(), "b3", "events", work, upsert=upsert)
    assert [r["status"] for r in rows] == ["running", "error"]


@pytest.mark.asyncio
async def test_a_raise_is_still_an_error_row_and_is_reraised():
    async def work():
        raise RuntimeError("fetch failed")

    rows, upsert = _capture()
    with pytest.raises(RuntimeError, match="fetch failed"):
        await ingest_log.audited(MagicMock(), "b3", "events", work, upsert=upsert)
    assert rows[-1]["status"] == "error"
    assert rows[-1]["error_msg"] == "RuntimeError: fetch failed"
