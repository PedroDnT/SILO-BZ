"""The retry contract of every fetcher, pinned (issue #876).

Each fetcher grew its own copy of the same loop. These tests state what every
copy does, from the outside, so the loops can move into ``src/fetchers/http.py``
without changing a request count, a wait or an error type:

* a transient failure (transport error, retryable status) is retried up to the
  fetcher's attempt budget, waiting between attempts and never after the last;
* an answer that is not transient (a 418) raises at once, with no second try;
* a failure that outlasts the budget raises the fetcher's own error type.

HTTP is mocked with ``httpx.MockTransport``; ``asyncio.sleep`` / ``time.sleep``
are replaced by a recorder, so no test waits.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, List

import httpx
import pytest

from src.fetchers import (
    b3_bdi_fetcher,
    b3_corporate_events_fetcher,
    b3_fetcher,
    b3_index_fetcher,
    b3_pesquisapregao_fetcher,
    b3_trade_consolidated_fetcher,
    bacen_fetcher,
    fnet_fetcher,
    global_market_fetcher,
    ibge_sidra_fetcher,
)

REAL_CLIENT = httpx.AsyncClient
DELAY = 1.5
ATTEMPTS = 3
LINEAR = [DELAY * 1, DELAY * 2]  # waits after attempt 1 and 2 of 3, none after 3


class Script:
    """Answers requests from a list of steps; the last step repeats."""

    def __init__(self, *steps: Any) -> None:
        self.steps = steps
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        step = self.steps[min(self.calls, len(self.steps) - 1)]
        self.calls += 1
        if isinstance(step, Exception):
            raise step
        return step


@pytest.fixture
def sleeps(monkeypatch) -> List[float]:
    waited: List[float] = []

    async def fake_async_sleep(seconds: float, *a: Any, **k: Any) -> None:
        waited.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_async_sleep)
    monkeypatch.setattr(time, "sleep", lambda seconds: waited.append(seconds))
    return waited


def _patch_client(monkeypatch, script: Script) -> None:
    """Every ``httpx.AsyncClient`` a fetcher opens talks to ``script``."""

    class Client(REAL_CLIENT):
        def __init__(self, *a: Any, **kw: Any) -> None:
            kw["transport"] = httpx.MockTransport(script)
            super().__init__(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", Client)


def _explicit_client(script: Script) -> httpx.AsyncClient:
    return REAL_CLIENT(transport=httpx.MockTransport(script))


def _boom() -> Exception:
    return httpx.ConnectError("boom")


def _r(status: int, **kw: Any) -> httpx.Response:
    return httpx.Response(status, **kw)


@dataclass
class Case:
    name: str
    run: Callable[[Script, Any], Awaitable[Any]]  # (script, monkeypatch) -> result
    ok: httpx.Response
    exc: type
    fatal: httpx.Response = field(default_factory=lambda: _r(418, text="teapot"))
    fatal_exc: type | None = None
    retry: httpx.Response = field(default_factory=lambda: _r(503))
    waits: List[float] = field(default_factory=lambda: list(LINEAR))
    attempts: int = ATTEMPTS


def _cotahist(script, mp):
    _patch_client(mp, script)
    f = b3_fetcher.B3CotahistFetcher(max_retries=ATTEMPTS, retry_delay=DELAY)
    return f._download("http://x/f.zip", label="f")


def _bdi_post(script, mp):
    _patch_client(mp, script)
    f = b3_bdi_fetcher.B3BdiFetcher(max_retries=ATTEMPTS, retry_delay=DELAY)
    return f._post("http://x/bdi", {}, label="bdi")


def _bdi_json(script, mp):
    _patch_client(mp, script)
    f = b3_bdi_fetcher.B3BdiFetcher(max_retries=ATTEMPTS, retry_delay=DELAY)
    return f._get_json("http://x/idx", label="idx")


def _pesquisa(script, mp):
    _patch_client(mp, script)
    f = b3_pesquisapregao_fetcher.B3PesquisaPregaoFetcher(
        base_url="http://x/p", max_retries=ATTEMPTS, retry_delay=DELAY)
    return f._download("name.zip")


def _trade(script, mp):
    f = b3_trade_consolidated_fetcher.B3TradeConsolidatedFetcher(max_retries=ATTEMPTS, retry_delay=DELAY)

    async def go():
        async with _explicit_client(script) as client:
            return await f._get(client, "http://x/api", params={}, label="t")
    return go()


def _global(script, mp):
    _patch_client(mp, script)
    f = global_market_fetcher.GlobalMarketFetcher(max_retries=ATTEMPTS, retry_delay=DELAY)
    return f._get("http://x/m", label="mkt")


def _ibge(script, mp):
    _patch_client(mp, script)
    mp.setenv("IBGE_SIDRA_MAX_RETRIES", str(ATTEMPTS))
    mp.setenv("IBGE_SIDRA_RETRY_DELAY", str(DELAY))
    return ibge_sidra_fetcher.fetch_ipca_items(1419, "202001", "202001")


def _olinda(script, mp):
    async def go():
        async with _explicit_client(script) as client:
            return await bacen_fetcher._olinda_request(
                client, "http://x/o", "http://x/o?a=1", attempts=ATTEMPTS, delay=DELAY)
    return go()


def _sgs(script, mp):
    async def go():
        async with _explicit_client(script) as client:
            return await bacen_fetcher._sgs_request(
                client, "SELIC", 432, None, None, 5, attempts=ATTEMPTS, delay=DELAY)
    return go()


def _fnet_page(script, mp):
    f = fnet_fetcher.FnetFetcher(max_retries=ATTEMPTS, retry_delay=DELAY, min_interval=0)

    async def go():
        async with _explicit_client(script) as client:
            return await f._get_page(client, {}, "lbl")
    return go()


def _fnet_download(script, mp):
    f = fnet_fetcher.FnetFetcher(max_retries=ATTEMPTS, retry_delay=DELAY, min_interval=0)

    async def go():
        async with _explicit_client(script) as client:
            return await f.download(client, 5)
    return go()


_SIDRA = json.dumps([{"V": "Valor"}, {"V": "1"}])

CASES = [
    Case("b3_cotahist", _cotahist, _r(200, content=b"zip"), b3_fetcher.B3CotahistFetchError),
    Case("b3_bdi_post", _bdi_post, _r(200, text="a;b\n1;2"), b3_bdi_fetcher.B3BdiFetchError,
         retry=_r(403)),
    Case("b3_bdi_get_json", _bdi_json, _r(200, json={"a": 1}), b3_bdi_fetcher.B3BdiFetchError),
    Case("b3_pesquisapregao", _pesquisa, _r(200, content=b"zip"), b3_pesquisapregao_fetcher.B3FileFetchError),
    Case("b3_trade_consolidated", _trade, _r(200, content=b"x"),
         b3_trade_consolidated_fetcher.B3TradeConsolidatedFetchError, retry=_r(403)),
    Case("global_market", _global, _r(200, text="a,b"), global_market_fetcher.MarketFetchError),
    Case("ibge_sidra", _ibge, _r(200, text=_SIDRA), ibge_sidra_fetcher.SidraFetchError),
    Case("bacen_olinda", _olinda, _r(200, text="{\"value\": []}"), bacen_fetcher.BacenFetchError),
    Case("bacen_sgs", _sgs, _r(200, text="[]"), bacen_fetcher.BacenFetchError),
    Case("fnet_page", _fnet_page, _r(200, json={"data": [], "recordsTotal": 0}),
         fnet_fetcher.FnetFetchError, retry=_r(403)),
    Case("fnet_download", _fnet_download,
         _r(200, content=b"%PDF", headers={"content-type": "application/pdf"}),
         fnet_fetcher.FnetFetchError, retry=_r(522)),
]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
async def test_transient_failures_use_the_whole_budget_then_raise(case, sleeps, monkeypatch):
    script = Script(case.retry)
    with pytest.raises(case.exc):
        await case.run(script, monkeypatch)
    assert script.calls == case.attempts
    assert sleeps == case.waits  # a wait between attempts, none after the last


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
async def test_a_transport_error_is_retried_then_recovers(case, sleeps, monkeypatch):
    script = Script(_boom(), case.ok)
    result = await case.run(script, monkeypatch)
    assert result is not None
    assert script.calls == 2
    assert sleeps == [DELAY]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
async def test_a_transport_error_that_never_clears_raises_the_fetchers_error(case, sleeps, monkeypatch):
    script = Script(_boom())
    with pytest.raises(case.exc):
        await case.run(script, monkeypatch)
    assert script.calls == case.attempts
    assert sleeps == case.waits


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
async def test_a_non_transient_status_raises_at_once(case, sleeps, monkeypatch):
    script = Script(case.fatal)
    with pytest.raises(case.fatal_exc or case.exc):
        await case.run(script, monkeypatch)
    assert script.calls == 1
    assert sleeps == []


# --- fetcher-specific transient answers (a 200 that is not the data) -------------------------------

BODY_CASES = [
    ("b3_bdi_html", _bdi_post, "<!DOCTYPE html><html>challenge</html>", b3_bdi_fetcher.B3BdiFetchError,
     _r(200, text="a;b\n1;2")),
    ("ibge_non_json", _ibge, "<html>overload</html>", ibge_sidra_fetcher.SidraFetchError, _r(200, text=_SIDRA)),
    ("bacen_sgs_non_json", _sgs, "<html>xhtml</html>", bacen_fetcher.BacenFetchError, _r(200, text="[]")),
    ("fnet_page_non_json", _fnet_page, "<html>waf</html>", fnet_fetcher.FnetFetchError,
     _r(200, json={"data": [], "recordsTotal": 0})),
    ("fnet_download_html", _fnet_download, "<html>waf</html>", fnet_fetcher.FnetFetchError,
     _r(200, content=b"%PDF", headers={"content-type": "application/pdf"})),
]


@pytest.mark.parametrize("name,run,body,exc,ok", BODY_CASES, ids=[c[0] for c in BODY_CASES])
async def test_a_200_that_is_not_the_data_is_retried(name, run, body, exc, ok, sleeps, monkeypatch):
    headers = {"content-type": "text/html"}
    bad = _r(200, text=body, headers=headers)
    script = Script(bad)
    with pytest.raises(exc):
        await run(script, monkeypatch)
    assert script.calls == ATTEMPTS
    assert sleeps == LINEAR

    script = Script(bad, ok)
    sleeps.clear()
    assert await run(script, monkeypatch) is not None
    assert script.calls == 2 and sleeps == [DELAY]


async def test_cotahist_404_raises_not_found_without_retry(sleeps, monkeypatch):
    script = Script(_r(404))
    with pytest.raises(b3_fetcher.B3CotahistNotFound):
        await _cotahist(script, monkeypatch)
    assert script.calls == 1 and sleeps == []


async def test_sgs_value_not_found_is_an_empty_answer_not_a_retry(sleeps, monkeypatch):
    script = Script(_r(404, text="Value(s) not found"))
    assert await _sgs(script, monkeypatch) == []
    assert script.calls == 1 and sleeps == []


async def test_trade_consolidated_400_problem_body_is_no_session(sleeps):
    f = b3_trade_consolidated_fetcher.B3TradeConsolidatedFetcher(max_retries=ATTEMPTS, retry_delay=DELAY)
    script = Script(_r(400, json={"status": 400, "title": "Bad Request"}))
    async with _explicit_client(script) as client:
        with pytest.raises(b3_trade_consolidated_fetcher.B3TradeConsolidatedNoSession):
            await f._get(client, "http://x/api", params={}, label="t", no_session_on_400=True)
    assert script.calls == 1 and sleeps == []


async def test_attempt_budget_is_floored_at_one(sleeps, monkeypatch):
    script = Script(_r(503))
    f = global_market_fetcher.GlobalMarketFetcher(max_retries=0, retry_delay=DELAY)
    _patch_client(monkeypatch, script)
    with pytest.raises(global_market_fetcher.MarketFetchError):
        await f._get("http://x/m", label="mkt")
    assert script.calls == 1 and sleeps == []


# --- the synchronous fetchers: requests.Session, exponential wait -----------------------------------

class FakeSession:
    def __init__(self, *steps: Any) -> None:
        self.steps = steps
        self.calls = 0
        self.headers: dict = {}

    def get(self, url: str, timeout: Any = None):
        step = self.steps[min(self.calls, len(self.steps) - 1)]
        self.calls += 1
        if isinstance(step, Exception):
            raise step
        return step


class FakeResponse:
    def __init__(self, text: str, status: int = 200) -> None:
        self.text = text
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


SYNC_BASE = 0.5
EXPONENTIAL = [SYNC_BASE * 2, SYNC_BASE * 4]


def _index(session: FakeSession):
    f = b3_index_fetcher.B3IndexFetcher(max_retries=ATTEMPTS, sleep_between=SYNC_BASE)
    f.session = session
    return f.fetch_year("IBOV", 2024)


def _corp(session: FakeSession):
    f = b3_corporate_events_fetcher.B3CorporateEventsFetcher(max_retries=ATTEMPTS, sleep_between=SYNC_BASE)
    f.session = session
    return f._call("GetInitialCompanies", {"language": "pt-br"})


SYNC_CASES = [
    ("b3_index", _index, json.dumps({"results": [1]})),
    ("b3_corporate_events", _corp, json.dumps({"results": [1]})),
]


@pytest.mark.parametrize("name,run,ok", SYNC_CASES, ids=[c[0] for c in SYNC_CASES])
def test_sync_fetchers_back_off_exponentially_and_raise_runtime_error(name, run, ok, sleeps):
    session = FakeSession(FakeResponse("", 503))
    with pytest.raises(RuntimeError, match=f"after {ATTEMPTS} attempts"):
        run(session)
    assert session.calls == ATTEMPTS
    assert sleeps == EXPONENTIAL


@pytest.mark.parametrize("name,run,ok", SYNC_CASES, ids=[c[0] for c in SYNC_CASES])
def test_sync_fetchers_recover_after_a_transport_error(name, run, ok, sleeps):
    session = FakeSession(ConnectionError("down"), FakeResponse(ok))
    assert run(session)
    assert session.calls == 2
    assert sleeps == [SYNC_BASE * 2]


def test_index_null_results_use_the_budget_then_raise_no_results(sleeps):
    session = FakeSession(FakeResponse(json.dumps({"results": None})))
    with pytest.raises(b3_index_fetcher.B3IndexNoResults, match="on all 3 attempts"):
        _index(session)
    assert session.calls == ATTEMPTS and sleeps == EXPONENTIAL


def test_supplement_empty_is_not_retried(sleeps):
    session = FakeSession(FakeResponse("  "))
    f = b3_corporate_events_fetcher.B3CorporateEventsFetcher(max_retries=ATTEMPTS, sleep_between=SYNC_BASE)
    f.session = session
    with pytest.raises(b3_corporate_events_fetcher.B3SupplementEmpty):
        f._call("GetListedSupplementCompany", {"issuingCompany": "ADMF"})
    assert session.calls == 1 and sleeps == []


# --- CVM: aiohttp, the breaker, DNS rotation --------------------------------------------------------

@pytest.fixture
def cvm(tmp_path, monkeypatch):
    from src.fetchers.cvm_fetcher import CVMFetcher

    monkeypatch.setenv("CVM_CACHE_DIR", str(tmp_path / "cache"))
    f = CVMFetcher()
    f.max_retries = ATTEMPTS
    f.retry_delay = DELAY
    f.timeout = 0.2
    f.dns_nameservers = []
    CVMFetcher.reset_circuit()
    yield f
    CVMFetcher.reset_circuit()


async def _local_server(handler):
    from aiohttp import web

    app = web.Application()
    app.router.add_get("/f.zip", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return f"http://127.0.0.1:{runner.addresses[0][1]}/f.zip", runner.cleanup


async def test_cvm_refused_connections_wait_linearly_between_attempts(cvm, tmp_path, sleeps):
    with pytest.raises(RuntimeError, match=f"after {ATTEMPTS} attempts \\(cannot connect"):
        await cvm._download_uncached("http://127.0.0.1:1/f.zip", str(tmp_path / "c"), str(tmp_path / "m"))
    assert sleeps == LINEAR


async def test_cvm_timeouts_wait_linearly_between_attempts(cvm, tmp_path, sleeps):
    from aiohttp import web

    calls = 0

    async def stall(request):
        nonlocal calls
        calls += 1
        await asyncio.Event().wait()  # never answers; asyncio.sleep is the recorder here
        return web.Response(body=b"x")

    url, cleanup = await _local_server(stall)
    try:
        with pytest.raises(RuntimeError, match=f"after {ATTEMPTS} attempts"):
            await cvm._download_uncached(url, str(tmp_path / "c"), str(tmp_path / "m"))
    finally:
        await cleanup()
    assert sleeps.count(DELAY) == 1 and sleeps.count(DELAY * 2) == 1


async def test_cvm_a_server_error_is_not_retried(cvm, tmp_path, sleeps):
    from aiohttp import web

    calls = 0

    async def broken(request):
        nonlocal calls
        calls += 1
        return web.Response(status=500)

    url, cleanup = await _local_server(broken)
    try:
        with pytest.raises(RuntimeError, match="HTTP 500"):
            await cvm._download_uncached(url, str(tmp_path / "c"), str(tmp_path / "m"))
    finally:
        await cleanup()
    assert calls == 1 and sleeps == []
