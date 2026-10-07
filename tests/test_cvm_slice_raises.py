"""A failed CVM slice writes its 'error' audit row, then raises (#691).

Owner decision, 2026-10-06: a CVM partial failure raises, as BACEN does, not
exit 0 as B3 does. Before this, every ingest_* method caught its exception,
wrote the 'error' row and returned 0, so the caller saw a quiet zero.

Contract pinned here:
  fetch fails          -> 'error' row written, then CVMSliceError
  404 (not published)  -> 'skipped' row written, returns 0, no raise
  fetched rows, none upserted -> 'error' row written, then CVMSliceError
  daily_update / backfill     -> every other slice still runs, then CVMRunFailed
  run_backfill                -> other sources still run, then exit 1
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.pipeline import run_backfill as rb
from src.pipeline.cvm_pipeline import CVMIngestor, CVMRunFailed, CVMSliceError


class _Cur:
    def __init__(self, sink):
        self.sink = sink
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.sink.append((sql, params))


class _Client:
    """Records the audit UPDATE that _log_finish issues."""

    def __init__(self):
        self.calls = []

    def cursor(self):
        return _Cur(self.calls)

    def reconnect(self):
        pass

    def finished(self):
        """(rows, status, error) of every terminal audit write, in order."""
        return [
            (p[0], p[1], p[2]) for sql, p in self.calls
            if sql.startswith("UPDATE cvm_ingest_log")
        ]


def _ingestor(fetch):
    ing = CVMIngestor.__new__(CVMIngestor)
    ing._supabase = _Client()
    ing._service = MagicMock()
    ing._service.fetch = fetch
    return ing


@pytest.fixture(autouse=True)
def _no_start_write():
    # The 'running' row goes through upsert_rows; this file checks the finish.
    with patch("src.pipeline.cvm_pipeline.upsert_rows") as up:
        yield up


@pytest.mark.asyncio
async def test_fetch_failure_writes_error_row_and_raises():
    ing = _ingestor(AsyncMock(side_effect=ConnectionResetError("reset by peer")))

    with pytest.raises(CVMSliceError) as raised:
        await ing.ingest_fi_balancete(2026, 8)

    [(rows, status, error)] = ing._supabase.finished()
    assert (rows, status) == (0, "error")
    assert "ConnectionResetError: reset by peer" in error
    # The raise names the slice, and the ledger holds it once.
    assert "fi/balancete 2026-08" in str(raised.value)
    assert [str(f) for f in ing.failures] == [str(raised.value.failures[0])]


@pytest.mark.asyncio
async def test_not_published_404_is_skipped_and_does_not_raise():
    # The fetcher's own 404 wording (tests/test_not_published_contract.py).
    url = "https://dados.cvm.gov.br/dados/FI/DOC/BALANCETE/DADOS/balancete_fi_202610.zip"
    ing = _ingestor(AsyncMock(side_effect=ValueError(f"Data not found at {url}")))

    assert await ing.ingest_fi_balancete(2026, 10) == 0

    [(rows, status, error)] = ing._supabase.finished()
    assert (rows, status) == (0, "skipped")
    assert "Data not found" in error
    assert ing.failures == []
    assert len(ing.skips) == 1


@pytest.mark.asyncio
async def test_rows_fetched_but_none_upserted_raises():
    ing = _ingestor(AsyncMock(return_value=[{"CNPJ_FUNDO": "x"}] * 3))
    with patch("src.pipeline.cvm_pipeline.ingest_fiagro_mensal", return_value=0):
        with pytest.raises(CVMSliceError):
            await ing.ingest_fiagro_mensal(2026, 8)
    [(_rows, status, error)] = ing._supabase.finished()
    assert status == "error" and "upserted 0" in error


@pytest.mark.asyncio
async def test_ok_slice_returns_rows():
    ing = _ingestor(AsyncMock(return_value=[{"a": 1}] * 2))
    with patch("src.pipeline.cvm_pipeline.ingest_fiagro_mensal", return_value=2):
        assert await ing.ingest_fiagro_mensal(2026, 8) == 2
    [(rows, status, error)] = ing._supabase.finished()
    assert (rows, status, error) == (2, "ok", None)


@pytest.mark.asyncio
async def test_fidc_hist_year_runs_every_month_then_raises_once():
    # Month 3 fails; the other eleven still run and each writes its own row.
    async def fetch(entity, doc_type, year, month):
        if month == 3:
            raise TimeoutError()
        return []

    ing = _ingestor(fetch)
    with patch("src.pipeline.cvm_pipeline.seed_fund_registry_from_hist"), \
         patch("src.pipeline.cvm_pipeline.upsert_rows", return_value=0):
        with pytest.raises(CVMSliceError) as raised:
            await ing.ingest_fidc_hist_mensal(2020)

    statuses = [s for _r, s, _e in ing._supabase.finished()]
    assert len(statuses) == 12
    assert statuses.count("error") == 1
    assert [f.month for f in raised.value.failures] == [3]


@pytest.mark.asyncio
async def test_backfill_runs_every_slice_then_raises_with_totals():
    ing = CVMIngestor.__new__(CVMIngestor)
    ing._supabase = _Client()

    async def flaky(year, month):
        async def work():
            if month == 4:
                raise TimeoutError()
            return 100, 100
        return await ing._audited("fi", "balancete", year, month, work)

    ing.ingest_fi_balancete = flaky
    with pytest.raises(CVMRunFailed) as raised:
        await ing.backfill(
            start_year=2019, end_year=2019,
            entity_filter="fi", doc_type_filter="balancete",
            months=[(2019, 4), (2019, 5), (2019, 6)],
        )
    assert raised.value.totals["cvm_fi_balancete_resumo"] == 200
    assert [(f.year, f.month) for f in raised.value.failures] == [(2019, 4)]
    # Recorded once: _run_task_batches does not add the raised slice again.
    assert len(ing.failures) == 1


@pytest.mark.asyncio
async def test_backfill_only_skips_does_not_raise():
    ing = CVMIngestor.__new__(CVMIngestor)
    ing._supabase = _Client()
    ing._service = MagicMock()
    ing._service.fetch = AsyncMock(side_effect=ValueError("Data not found at https://x"))
    totals = await ing.backfill(
        start_year=2026, end_year=2026,
        entity_filter="fi", doc_type_filter="balancete",
        months=[(2026, 10)],
    )
    assert totals["cvm_fi_balancete_resumo"] == 0
    assert ing.failures == []


@pytest.mark.asyncio
async def test_run_backfill_keeps_other_sources_and_exits_red(monkeypatch):
    from src.pipeline.cvm_pipeline import SliceFailure

    failure = SliceFailure("fi", "balancete", 2019, 4, "TimeoutError")
    cvm = MagicMock()
    cvm.backfill = AsyncMock(side_effect=CVMRunFailed([failure], {"cvm_fi_balancete_resumo": 200}))
    cvm.failures = [failure]
    cvm.skips = []
    bacen = MagicMock()
    bacen.backfill = AsyncMock(return_value={"bacen_sgs": 5})
    ibge = MagicMock()
    ibge.backfill = AsyncMock(return_value={})

    monkeypatch.setattr("sys.argv", ["run_backfill", "--start-year", "2019", "--end-year", "2019"])
    with patch.object(rb, "CVMIngestor", return_value=cvm), \
         patch.object(rb, "BacenIngestor", return_value=bacen), \
         patch.object(rb, "IbgeIngestor", return_value=ibge):
        with pytest.raises(SystemExit) as exc:
            await rb.main(rb.parse_args())
    assert exc.value.code == 1
    bacen.backfill.assert_awaited()
