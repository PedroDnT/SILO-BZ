"""A re-fetch that lands far fewer rows than the period's last 'ok' load is an error (#978).

THE ROWS THIS EXISTS FOR. cvm_ingest_log, 2026-08-20..26: fi/inf_diario 2026-07
went from 585,154 rows to 0, fidc tab X_4 2026-07 from 46,484 to 0, and about 18
more slices the same week, every one logged 'ok'. The upsert never deletes, so no
stored row was lost, but a broken CVM file passed as a success.

Contract pinned here:
  previous >= 100 and rows < half of it   -> 'error', the empty file included
  previous under 100, or no previous       -> classified as before
  cia_aberta itr/dfp                       -> never compared (incremental, #961)
  the lookup fails                         -> no comparison, the slice is not blocked
"""

from unittest.mock import patch

import pytest

from src.pipeline.cvm_pipeline import CVMIngestor, CVMSliceError, _classify_finish


class TestClassify:
    def test_an_empty_refetch_of_a_loaded_period_is_an_error(self):
        status, msg = _classify_finish(None, fetched=0, rows=0, previous=585154)
        assert status == "error"
        assert "585154" in msg

    def test_a_partial_refetch_is_an_error(self):
        assert _classify_finish(None, fetched=400, rows=400, previous=1000)[0] == "error"

    def test_half_or_more_is_ok(self):
        assert _classify_finish(None, fetched=500, rows=500, previous=1000) == ("ok", None)

    def test_growth_is_ok(self):
        assert _classify_finish(None, fetched=1200, rows=1200, previous=1000) == ("ok", None)

    def test_a_small_previous_load_is_not_compared(self):
        assert _classify_finish(None, fetched=0, rows=0, previous=99) == ("ok", None)

    def test_no_previous_load_keeps_the_old_rules(self):
        assert _classify_finish(None, fetched=0, rows=0) == ("ok", None)

    def test_a_404_stays_skipped_whatever_the_previous_load(self):
        status, _ = _classify_finish("ValueError: Data not found at https://x", None, 0, previous=5000)
        assert status == "skipped"


class _Cur:
    def __init__(self, client):
        self.client = client
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        if self.client.lookup_fails and sql.startswith("SELECT rows_upserted"):
            raise RuntimeError("connection lost")
        self.client.calls.append((sql, params))

    def fetchone(self):
        return None if self.client.previous is None else (self.client.previous,)


class _Client:
    def __init__(self, previous=None, lookup_fails=False):
        self.previous = previous
        self.lookup_fails = lookup_fails
        self.calls = []

    def cursor(self):
        return _Cur(self)

    def reconnect(self):
        pass

    def lookups(self):
        return [p for sql, p in self.calls if sql.startswith("SELECT rows_upserted")]

    def statuses(self):
        return [p[1] for sql, p in self.calls if sql.startswith("UPDATE cvm_ingest_log")]


def _ingestor(client):
    ing = CVMIngestor.__new__(CVMIngestor)
    ing._supabase = client
    return ing


async def _work_returning(rows, fetched):
    async def work():
        return rows, fetched
    return work


@pytest.fixture(autouse=True)
def _no_start_write():
    with patch("src.pipeline.cvm_pipeline.upsert_rows"):
        yield


@pytest.mark.asyncio
async def test_an_empty_refetch_raises_and_logs_error():
    client = _Client(previous=585154)
    ing = _ingestor(client)
    with pytest.raises(CVMSliceError):
        await ing._audited("fi", "inf_diario", 2026, 7, await _work_returning(0, 0))
    assert client.statuses() == ["error"]
    assert client.lookups() == [("fi", "inf_diario", 2026, 7, 30)]


@pytest.mark.asyncio
async def test_a_normal_refetch_is_ok():
    client = _Client(previous=585154)
    rows = await _ingestor(client)._audited("fi", "inf_diario", 2026, 7, await _work_returning(590000, 590000))
    assert rows == 590000
    assert client.statuses() == ["ok"]


@pytest.mark.asyncio
async def test_itr_and_dfp_are_never_compared():
    client = _Client(previous=2205090)
    await _ingestor(client)._audited("cia_aberta", "itr", 2026, None, await _work_returning(10, 10))
    assert client.lookups() == []
    assert client.statuses() == ["ok"]


@pytest.mark.asyncio
async def test_a_failed_lookup_does_not_block_the_slice():
    client = _Client(previous=585154, lookup_fails=True)
    rows = await _ingestor(client)._audited("fi", "inf_diario", 2026, 7, await _work_returning(0, 0))
    assert rows == 0
    assert client.statuses() == ["ok"]
