"""FI HIST daily: a failed month fails the year's audit row (#1105).

ingest_fi_hist_diario loops the twelve monthly members of one yearly HIST
archive. A month that failed used to be dropped from the audit trail: the year
was logged 'ok' unless every month failed, so the gap was never reported or
retried. Now any failed month other than a member absent before the first
loaded month (a partial first year) logs the year 'error', with every failed
month in error_msg and the rows that landed in rows_upserted.
"""

from unittest.mock import MagicMock

import pytest

from src.pipeline import cvm_pipeline
from src.pipeline.cvm_pipeline import CVMIngestor, CVMSliceError

_ABSENT = "ZIP member 'inf_diario_fi_2000{m:02d}.csv' not found in archive — refusing to fall back"


def _ingestor(monkeypatch, fail):
    """An ingestor whose fetch raises fail(month) when it returns an exception."""
    ing = CVMIngestor.__new__(CVMIngestor)
    ing._supabase = None
    ing._log_start = MagicMock()
    ing._previous_ok_rows = MagicMock(return_value=None)
    finished = []
    ing._write_finish = lambda run_id, rows, status, error, deleted: finished.append(
        (rows, status, error)
    )

    async def fake_fetch(entity, doc_type, year, month):
        exc = fail(month)
        if exc is not None:
            raise exc
        return [{"month": month}] * 3

    ing._fetch_all_pages = fake_fetch
    monkeypatch.setattr(cvm_pipeline, "ingest_fi_diario", lambda client, rows: len(rows))
    return ing, finished


@pytest.mark.asyncio
async def test_mid_year_failure_logs_the_year_error_and_keeps_rows(monkeypatch):
    ing, finished = _ingestor(
        monkeypatch, lambda m: TimeoutError("read timed out") if m == 7 else None
    )
    with pytest.raises(CVMSliceError):
        await ing.ingest_fi_hist_diario(2015)

    assert len(finished) == 1
    rows, status, error = finished[0]
    assert status == "error"
    assert rows == 33  # eleven months of 3 rows landed and stay
    assert "07: read timed out" in error
    assert len(ing.failures) == 1 and ing.failures[0].rows == 33


@pytest.mark.asyncio
async def test_every_failed_month_reaches_error_msg(monkeypatch):
    ing, finished = _ingestor(
        monkeypatch,
        lambda m: ValueError(_ABSENT.format(m=m)) if m == 12 else
        (RuntimeError("bad zip") if m == 3 else None),
    )
    with pytest.raises(CVMSliceError):
        await ing.ingest_fi_hist_diario(2015)

    rows, status, error = finished[0]
    assert status == "error"
    assert rows == 30
    # A trailing absent member is not a partial first year: it counts too.
    assert "03: bad zip" in error and "12: ZIP member" in error


@pytest.mark.asyncio
async def test_partial_first_year_is_ok(monkeypatch):
    # The series starts mid-year: members before the first loaded month are
    # absent from the archive, which is expected, not a failure.
    ing, finished = _ingestor(
        monkeypatch, lambda m: ValueError(_ABSENT.format(m=m)) if m < 4 else None
    )
    rows = await ing.ingest_fi_hist_diario(2000)

    assert rows == 27
    assert finished == [(27, "ok", None)]
    assert ing.failures == []


@pytest.mark.asyncio
async def test_leading_month_failing_for_another_reason_is_an_error(monkeypatch):
    ing, finished = _ingestor(
        monkeypatch, lambda m: TimeoutError("read timed out") if m == 1 else None
    )
    with pytest.raises(CVMSliceError):
        await ing.ingest_fi_hist_diario(2000)

    rows, status, error = finished[0]
    assert (rows, status) == (33, "error")
    assert "01: read timed out" in error
