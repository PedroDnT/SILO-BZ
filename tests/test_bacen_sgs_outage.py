"""An SGS host that does not exist is skipped for a few days, then caught up (#537).

`api.bcb.gov.br` stopped resolving on 2026-10-03 (NXDOMAIN at 1.1.1.1, 8.8.8.8,
9.9.9.9 and BCB's own nameservers, while olinda. and dadosabertos. kept
answering). `Daily CVM Ingest` ran red on SGS 432 with
"[Errno -2] Name or service not known". No retry and no resolver rotation heals
a name that is not there, so the policy is:

  * only that failure (gaierror EAI_NONAME) is the source's outage; a timeout,
    an HTTP 5xx, a body that is not JSON and EAI_AGAIN (a resolver that is busy
    for a moment) still raise;
  * while the last successful SGS load is within BACEN_SGS_TOLERATE_DAYS the SGS
    slice ends `skipped` and the run does not fail; after that it raises again;
  * when the host answers, the load starts at the last successful one (capped),
    so the days missed are fetched; the upsert is idempotent on
    (series_code, reference_date).

HTTP and Postgres are mocked.
"""

from __future__ import annotations

import socket
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.fetchers.bacen_fetcher import BacenClient, BacenFetchError, BacenHostUnresolved
from src.pipeline.bacen_pipeline import (
    FISCAL_SERIES,
    LOG_ENTITY,
    SGS_LAGGED_LOOKBACK_DAYS,
    BacenIngestor,
    sgs_catchup_start,
)
from src.pipeline.ingest_log import Outcome

TODAY = datetime.now(timezone.utc).date()


def _ago(days: int) -> date:
    return TODAY - timedelta(days=days)


# ── fetcher: which failure is the source's ────────────────────────────────


def _client_failing_with(exc: BaseException):
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    transport = httpx.MockTransport(handler)
    orig = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return orig(*args, **kwargs)

    return factory


def _connect_error(cause: BaseException) -> httpx.ConnectError:
    err = httpx.ConnectError(f"[Errno {getattr(cause, 'errno', '?')}] {cause}")
    err.__cause__ = cause
    return err


@pytest.fixture
def one_attempt(monkeypatch):
    monkeypatch.setenv("BACEN_OLINDA_MAX_RETRIES", "2")
    monkeypatch.setenv("BACEN_OLINDA_RETRY_DELAY", "0")


@pytest.mark.asyncio
async def test_a_name_that_does_not_exist_raises_the_typed_error(one_attempt):
    gai = socket.gaierror(socket.EAI_NONAME, "Name or service not known")
    with patch("httpx.AsyncClient", _client_failing_with(_connect_error(gai))):
        with pytest.raises(BacenHostUnresolved, match="failed after 2 attempts"):
            await BacenClient().get_sgs_series({"SELIC_META": 432}, start="2026-10-01")


def test_the_typed_error_is_still_a_fetch_error():
    assert issubclass(BacenHostUnresolved, BacenFetchError)


@pytest.mark.asyncio
async def test_a_resolver_that_is_only_busy_is_not_the_sources_outage(one_attempt):
    gai = socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution")
    with patch("httpx.AsyncClient", _client_failing_with(_connect_error(gai))):
        with pytest.raises(BacenFetchError) as exc:
            await BacenClient().get_sgs_series({"SELIC_META": 432}, start="2026-10-01")
    assert not isinstance(exc.value, BacenHostUnresolved)


@pytest.mark.asyncio
async def test_a_timeout_is_not_the_sources_outage(one_attempt):
    with patch("httpx.AsyncClient", _client_failing_with(httpx.ConnectTimeout("timed out"))):
        with pytest.raises(BacenFetchError) as exc:
            await BacenClient().get_sgs_series({"SELIC_META": 432}, start="2026-10-01")
    assert not isinstance(exc.value, BacenHostUnresolved)


@pytest.mark.asyncio
async def test_an_http_503_is_not_the_sources_outage(one_attempt):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    transport = httpx.MockTransport(handler)
    orig = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return orig(*args, **kwargs)

    with patch("httpx.AsyncClient", factory):
        with pytest.raises(BacenFetchError) as exc:
            await BacenClient().get_sgs_series({"SELIC_META": 432}, start="2026-10-01")
    assert not isinstance(exc.value, BacenHostUnresolved)


# ── pipeline: tolerate a few days, then raise ─────────────────────────────


def _ingestor(*, last_ok, fetch) -> BacenIngestor:
    with patch("src.pipeline.bacen_pipeline.BacenClient"), \
         patch("src.pipeline.bacen_pipeline.get_pg_client", return_value=MagicMock()):
        ing = BacenIngestor()
    ing._last_sgs_landing = MagicMock(return_value=last_ok)
    ing._client.get_sgs_series = fetch
    return ing


def _unresolved() -> AsyncMock:
    return AsyncMock(side_effect=BacenHostUnresolved(
        "SGS SELIC_META (432): failed after 4 attempts: [Errno -2] Name or service not known"
    ))


@pytest.mark.asyncio
async def test_an_outage_within_the_tolerance_ends_skipped_and_writes_nothing(monkeypatch):
    monkeypatch.delenv("BACEN_SGS_TOLERATE_DAYS", raising=False)
    ing = _ingestor(last_ok=_ago(1), fetch=_unresolved())
    with patch("src.pipeline.bacen_pipeline.upsert_rows") as up:
        out = await ing.ingest_sgs("2026-09-03")
    assert isinstance(out, Outcome)
    assert (out.rows, out.status) == (0, "skipped")
    assert _ago(1).isoformat() in out.error and "does not resolve" in out.error
    up.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("last_ok", [_ago(8), _ago(400), None], ids=["8 days", "400 days", "never"])
async def test_an_outage_beyond_the_tolerance_raises_again(monkeypatch, last_ok):
    monkeypatch.delenv("BACEN_SGS_TOLERATE_DAYS", raising=False)
    ing = _ingestor(last_ok=last_ok, fetch=_unresolved())
    with patch("src.pipeline.bacen_pipeline.upsert_rows"):
        with pytest.raises(RuntimeError, match="SGS fetch failed"):
            await ing.ingest_sgs("2026-09-03")


@pytest.mark.asyncio
async def test_the_tolerance_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("BACEN_SGS_TOLERATE_DAYS", "0")
    ing = _ingestor(last_ok=_ago(0), fetch=_unresolved())
    with patch("src.pipeline.bacen_pipeline.upsert_rows"):
        with pytest.raises(RuntimeError, match="SGS fetch failed"):
            await ing.ingest_sgs("2026-09-03")


@pytest.mark.asyncio
async def test_any_other_failure_still_raises_inside_the_tolerance(monkeypatch):
    monkeypatch.delenv("BACEN_SGS_TOLERATE_DAYS", raising=False)
    for exc in (BacenFetchError("SGS CDI (12): HTTP 503"), Exception("BCB unreachable")):
        ing = _ingestor(last_ok=_ago(1), fetch=AsyncMock(side_effect=exc))
        with patch("src.pipeline.bacen_pipeline.upsert_rows"):
            with pytest.raises(RuntimeError, match="SGS fetch failed"):
                await ing.ingest_sgs("2026-09-03")


def test_a_mistyped_tolerance_fails_loudly(monkeypatch):
    monkeypatch.setenv("BACEN_SGS_TOLERATE_DAYS", "a week")
    ing = _ingestor(last_ok=_ago(1), fetch=_unresolved())
    with pytest.raises(ValueError, match="BACEN_SGS_TOLERATE_DAYS"):
        import asyncio
        asyncio.run(ing.ingest_sgs("2026-09-03"))


# ── the audit row and the run ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_audit_row_is_skipped_and_the_run_does_not_fail(monkeypatch):
    """Through backfill(): SGS ends `skipped`, the other sources land, nothing raises."""
    monkeypatch.delenv("BACEN_SGS_TOLERATE_DAYS", raising=False)
    rows: List[Dict[str, Any]] = []

    def capture(client, table, batch, **kw):
        if table == "cvm_ingest_log":
            rows.extend(batch)
        return len(batch)

    ing = _ingestor(last_ok=_ago(2), fetch=_unresolved())
    ing.ingest_ptax = AsyncMock(return_value=92)
    ing.ingest_expectativas = AsyncMock(return_value=1235)
    with patch("src.pipeline.ingest_log.upsert_rows", side_effect=capture):
        totals = await ing.backfill(start=_ago(30).isoformat())

    assert totals["bacen_sgs"] == 0 and totals["bacen_ptax"] == 92
    sgs = [r for r in rows if r["doc_type"] == "sgs"]
    final = sgs[-1]
    assert final["entity"] == LOG_ENTITY and final["status"] == "skipped"
    assert "does not resolve" in final["error_msg"]


# ── catching up when the host answers ─────────────────────────────────────


@pytest.mark.parametrize(
    "start, last_ok, want",
    [
        (_ago(30).isoformat(), _ago(1), _ago(30).isoformat()),      # a normal day: unchanged
        (_ago(30).isoformat(), None, _ago(30).isoformat()),         # no load on record: unchanged
        ("2019-01-01", _ago(5), "2019-01-01"),                      # a historical start stays
        (_ago(30).isoformat(), _ago(40), _ago(41).isoformat()),     # a 40-day gap: from the day before
        (_ago(30).isoformat(), _ago(900), _ago(366).isoformat()),   # capped at 366 days
    ],
    ids=["normal day", "no load", "historical", "gap", "capped"],
)
def test_the_window_starts_at_the_last_good_load(monkeypatch, start, last_ok, want):
    monkeypatch.delenv("BACEN_SGS_CATCHUP_MAX_DAYS", raising=False)
    assert sgs_catchup_start(start, last_ok, TODAY) == want


def test_the_catchup_cap_can_be_changed(monkeypatch):
    monkeypatch.setenv("BACEN_SGS_CATCHUP_MAX_DAYS", "60")
    assert sgs_catchup_start(_ago(30).isoformat(), _ago(900), TODAY) == _ago(60).isoformat()


@pytest.mark.asyncio
async def test_once_the_host_answers_the_days_missed_are_fetched_and_stored(monkeypatch):
    """Outage, then recovery: day 1 is skipped, day 4 starts at the last good load."""
    monkeypatch.delenv("BACEN_SGS_TOLERATE_DAYS", raising=False)
    monkeypatch.delenv("BACEN_SGS_CATCHUP_MAX_DAYS", raising=False)
    last_ok = _ago(40)          # the last good load; skipped days do not advance it
    records = [
        {"date": (last_ok + timedelta(days=i)).isoformat(), "SELIC_META": 14.25}
        for i in range(0, 5)
    ]
    fetch = AsyncMock(side_effect=[
        BacenHostUnresolved("SGS SELIC_META (432): failed after 4 attempts: Name or service not known"),
        records,
        [],  # the lagged fiscal set, fetched in its own call
        [],  # the held research set, fetched last in its own call
    ])
    ing = _ingestor(last_ok=last_ok, fetch=fetch)
    stored: List[Dict[str, Any]] = []

    def fake_upsert(client, table, rows, **kw):
        stored.extend(rows)
        return len(rows)

    monkeypatch.setenv("BACEN_SGS_TOLERATE_DAYS", "60")
    with patch("src.pipeline.bacen_pipeline.upsert_rows", side_effect=fake_upsert):
        first = await ing.ingest_sgs(_ago(30).isoformat())
        second = await ing.ingest_sgs(_ago(30).isoformat())

    assert isinstance(first, Outcome) and first.status == "skipped"
    assert second == 5 and len(stored) == 5
    assert {r["reference_date"] for r in stored} == {r["date"] for r in records}
    starts = [call.kwargs["start"] for call in fetch.await_args_list
              if call.kwargs["codes"] is not FISCAL_SERIES and "ICBR" not in call.kwargs["codes"]]
    assert starts == [(last_ok - timedelta(days=1)).isoformat()] * 2, (
        "both loads start at the last good one, not at the 30-day window"
    )


# ── the lagged fiscal set ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_fiscal_set_is_fetched_from_past_its_publication_delay(monkeypatch):
    """BACEN dates fiscal month M on 01/M and publishes it ~60 days later: a 30-day
    window never reaches it, so the fiscal call starts SGS_LAGGED_LOOKBACK_DAYS back."""
    monkeypatch.delenv("BACEN_SGS_CATCHUP_MAX_DAYS", raising=False)
    month = _ago(70).replace(day=1).isoformat()

    async def fetch(codes, start, end):
        if codes is FISCAL_SERIES:
            return [{"date": month, "DBGG_PIB": 82.87, "NFSP_PRIMARIO_12M": 0.62}]
        return [{"date": _ago(1).isoformat(), "CDI": 0.055}]

    ing = _ingestor(last_ok=_ago(1), fetch=AsyncMock(side_effect=fetch))
    stored: List[Dict[str, Any]] = []
    with patch("src.pipeline.bacen_pipeline.upsert_rows",
               side_effect=lambda c, t, rows, **kw: stored.extend(rows) or len(rows)):
        n = await ing.ingest_sgs(_ago(30).isoformat())

    calls = {id(c.kwargs["codes"]): c.kwargs["start"] for c in ing._client.get_sgs_series.await_args_list}
    assert calls[id(FISCAL_SERIES)] == _ago(SGS_LAGGED_LOOKBACK_DAYS).isoformat()
    assert len(calls) == 3 and _ago(30).isoformat() in calls.values()
    assert n == 3
    assert {(r["series_code"], r["reference_date"]) for r in stored} == {
        (12, _ago(1).isoformat()), (13762, month), (5793, month),
    }


def test_the_fiscal_set_is_served_and_the_lookback_outlasts_the_delay():
    from src.pipeline.bacen_pipeline import INFLATION_SERIES, SGS_SERIES

    assert FISCAL_SERIES == {"DBGG_PIB": 13762, "NFSP_PRIMARIO_12M": 5793, "NFSP_NOMINAL_12M": 5727}
    assert all(SGS_SERIES[k] == v and k not in INFLATION_SERIES for k, v in FISCAL_SERIES.items())
    assert SGS_LAGGED_LOOKBACK_DAYS >= 120


@pytest.mark.asyncio
async def test_a_failed_research_series_does_not_stop_the_served_ones(monkeypatch):
    """#1031: BCB answered ICBR_ENERGIA (27577) with its HTML page and the whole
    SGS source raised before the fiscal group ran. A failure in the held
    research group lands every served row and ends the audit row `error`
    with the failure named; a served-group failure still raises."""
    from src.pipeline.bacen_pipeline import RESEARCH_SGS_SERIES

    monkeypatch.delenv("BACEN_SGS_CATCHUP_MAX_DAYS", raising=False)
    month = _ago(70).replace(day=1).isoformat()

    async def fetch(codes, start, end):
        if codes is RESEARCH_SGS_SERIES:
            raise BacenFetchError("SGS ICBR_ENERGIA (27577): response is not JSON: <html>")
        if codes is FISCAL_SERIES:
            return [{"date": month, "DBGG_PIB": 82.87}]
        return [{"date": _ago(1).isoformat(), "CDI": 0.055}]

    ing = _ingestor(last_ok=_ago(1), fetch=AsyncMock(side_effect=fetch))
    stored: List[Dict[str, Any]] = []
    with patch("src.pipeline.bacen_pipeline.upsert_rows",
               side_effect=lambda c, t, rows, **kw: stored.extend(rows) or len(rows)):
        out = await ing.ingest_sgs(_ago(30).isoformat())

    assert {(r["series_code"], r["reference_date"]) for r in stored} == {
        (12, _ago(1).isoformat()), (13762, month),
    }
    assert isinstance(out, Outcome)
    assert (out.rows, out.status) == (2, "error")
    assert "ICBR_ENERGIA" in out.error and "BacenFetchError" in out.error


@pytest.mark.asyncio
async def test_a_failed_served_group_still_raises_and_skips_research(monkeypatch):
    from src.pipeline.bacen_pipeline import RESEARCH_SGS_SERIES

    async def fetch(codes, start, end):
        if codes is RESEARCH_SGS_SERIES:
            raise AssertionError("research must not be fetched after a served failure")
        raise BacenFetchError("SGS CDI (12): HTTP 500")

    ing = _ingestor(last_ok=_ago(1), fetch=AsyncMock(side_effect=fetch))
    with patch("src.pipeline.bacen_pipeline.upsert_rows") as up:
        with pytest.raises(RuntimeError, match="SGS fetch failed"):
            await ing.ingest_sgs(_ago(30).isoformat())
    up.assert_not_called()
