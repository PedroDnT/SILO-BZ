"""SGS fetch: one request per series, a 404 empties one series, never all ten.

Daily CVM Ingest 33721538761 and 33798733736 (both 2026-09-03) logged

    SGS fetch failed: Download error: code = 433

and `bacen_sgs: 0`. The 433 is not an HTTP status: it is the IPCA series
code. python-bcb fetched the ten configured series in sequence and raised on
the first non-200, discarding Selic, CDI and everything already fetched. The
daily window (today-30 .. today) asks for IPCA before the month's figure is
published, and BACEN answers that with HTTP 404 "Value(s) not found" — so on
most days every SGS series landed zero rows, and the run stayed green.

HTTP is mocked; each handler answers per series code.
"""

from __future__ import annotations

import json
from typing import Callable, Dict
from unittest.mock import patch

import httpx
import pytest

from src.fetchers.bacen_fetcher import BacenClient, BacenFetchError, _to_sgs_date

_NOT_FOUND = json.dumps({"erro": {"statusCode": 404, "detail":
    "br.gov.bcb.pec.sgs.comum.excecoes.SGSNegocioException: Value(s) not found"}})

_CDI = [{"data": "04/08/2026", "valor": "0.052531"}, {"data": "05/08/2026", "valor": "0.051660"}]
_IGPM = [{"data": "01/08/2026", "valor": "-0.22"}]


def _client_factory(handler: Callable[[httpx.Request], httpx.Response]):
    transport = httpx.MockTransport(handler)
    orig = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return orig(*args, **kwargs)

    return factory


def _series_code(request: httpx.Request) -> int:
    return int(request.url.path.split("bcdata.sgs.")[1].split("/")[0])


def _by_code(answers: Dict[int, httpx.Response]):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return answers[_series_code(request)]

    return handler, calls


@pytest.fixture
def one_attempt(monkeypatch):
    monkeypatch.setenv("BACEN_OLINDA_MAX_RETRIES", "1")
    monkeypatch.setenv("BACEN_OLINDA_RETRY_DELAY", "0")


def test_sgs_date_format_is_day_month_year():
    assert _to_sgs_date("2026-08-04") == "04/08/2026"
    assert _to_sgs_date(None) is None


@pytest.mark.asyncio
async def test_a_404_on_one_series_does_not_discard_the_others(one_attempt, caplog):
    handler, calls = _by_code({
        12: httpx.Response(200, json=_CDI),
        433: httpx.Response(404, text=_NOT_FOUND),
        189: httpx.Response(200, json=_IGPM),
    })
    with patch("httpx.AsyncClient", _client_factory(handler)), caplog.at_level("WARNING"):
        rows = await BacenClient().get_sgs_series(
            {"CDI": 12, "IPCA": 433, "IGPM": 189}, start="2026-08-04", end="2026-09-03",
        )
    assert rows == [
        {"date": "2026-08-01", "IGPM": -0.22},
        {"date": "2026-08-04", "CDI": 0.052531},
        {"date": "2026-08-05", "CDI": 0.05166},
    ]
    assert len(calls) == 3, "one request per series, all three attempted"
    assert "IPCA" in caplog.text and "no observation" in caplog.text
    assert not any("IPCA" in r for r in rows), "an absent series is absent, never zero"


@pytest.mark.asyncio
async def test_requests_carry_the_window_in_bacen_date_format(one_attempt):
    handler, calls = _by_code({12: httpx.Response(200, json=_CDI)})
    with patch("httpx.AsyncClient", _client_factory(handler)):
        await BacenClient().get_sgs_series({"CDI": 12}, start="2026-08-04", end="2026-09-03")
    q = dict(calls[0].url.params)
    assert q == {"formato": "json", "dataInicial": "04/08/2026", "dataFinal": "03/09/2026"}


@pytest.mark.asyncio
async def test_last_uses_the_ultimos_path(one_attempt):
    handler, calls = _by_code({12: httpx.Response(200, json=_CDI[-1:])})
    with patch("httpx.AsyncClient", _client_factory(handler)):
        await BacenClient().get_sgs_series({"CDI": 12}, last=1)
    assert calls[0].url.path.endswith("/bcdata.sgs.12/dados/ultimos/1")


@pytest.mark.asyncio
async def test_a_500_raises_instead_of_reading_as_a_quiet_window(one_attempt):
    handler, _ = _by_code({12: httpx.Response(500, text="boom")})
    with patch("httpx.AsyncClient", _client_factory(handler)):
        with pytest.raises(BacenFetchError, match=r"SGS CDI \(12\)"):
            await BacenClient().get_sgs_series({"CDI": 12}, start="2026-08-04")


@pytest.mark.asyncio
async def test_a_503_is_retried_then_succeeds(monkeypatch):
    monkeypatch.setenv("BACEN_OLINDA_MAX_RETRIES", "2")
    monkeypatch.setenv("BACEN_OLINDA_RETRY_DELAY", "0")
    n = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        n["calls"] += 1
        return httpx.Response(503, text="<html>") if n["calls"] == 1 else httpx.Response(200, json=_CDI)

    with patch("httpx.AsyncClient", _client_factory(handler)):
        rows = await BacenClient().get_sgs_series({"CDI": 12}, start="2026-08-04")
    assert n["calls"] == 2 and len(rows) == 2


@pytest.mark.asyncio
async def test_a_200_html_interstitial_is_retried_then_succeeds(monkeypatch):
    """Seen live 2026-09-03: series 432 answered HTTP 200 with an XHTML page once."""
    monkeypatch.setenv("BACEN_OLINDA_MAX_RETRIES", "2")
    monkeypatch.setenv("BACEN_OLINDA_RETRY_DELAY", "0")
    n = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        n["calls"] += 1
        if n["calls"] == 1:
            return httpx.Response(200, text='<?xml version="1.0"?><html><title>BCB</title></html>',
                                  headers={"content-type": "text/html"})
        return httpx.Response(200, json=_CDI)

    with patch("httpx.AsyncClient", _client_factory(handler)):
        rows = await BacenClient().get_sgs_series({"CDI": 12}, start="2026-08-04")
    assert n["calls"] == 2 and len(rows) == 2


@pytest.mark.asyncio
async def test_a_200_html_interstitial_every_time_raises(one_attempt):
    handler, _ = _by_code({12: httpx.Response(200, text="<html>maintenance</html>")})
    with patch("httpx.AsyncClient", _client_factory(handler)):
        with pytest.raises(BacenFetchError, match="response is not JSON"):
            await BacenClient().get_sgs_series({"CDI": 12}, start="2026-08-04")


@pytest.mark.asyncio
async def test_a_404_without_bacens_marker_is_an_error(one_attempt):
    """Only BACEN's documented 'Value(s) not found' is an empty window."""
    handler, _ = _by_code({12: httpx.Response(404, text="<html>not here</html>")})
    with patch("httpx.AsyncClient", _client_factory(handler)):
        with pytest.raises(BacenFetchError, match="HTTP 404"):
            await BacenClient().get_sgs_series({"CDI": 12}, start="2026-08-04")


@pytest.mark.asyncio
async def test_empty_value_is_null_and_garbage_raises(one_attempt):
    handler, _ = _by_code({12: httpx.Response(200, json=[{"data": "04/08/2026", "valor": ""}])})
    with patch("httpx.AsyncClient", _client_factory(handler)):
        rows = await BacenClient().get_sgs_series({"CDI": 12}, start="2026-08-04")
    assert rows == [{"date": "2026-08-04", "CDI": None}], "null stays null, never 0"

    handler, _ = _by_code({12: httpx.Response(200, json=[{"data": "04/08/2026", "valor": "n/d"}])})
    with patch("httpx.AsyncClient", _client_factory(handler)):
        with pytest.raises(BacenFetchError, match="non-numeric"):
            await BacenClient().get_sgs_series({"CDI": 12}, start="2026-08-04")


@pytest.mark.asyncio
async def test_non_list_payload_raises(one_attempt):
    handler, _ = _by_code({12: httpx.Response(200, json={"unexpected": True})})
    with patch("httpx.AsyncClient", _client_factory(handler)):
        with pytest.raises(BacenFetchError, match="expected a JSON list"):
            await BacenClient().get_sgs_series({"CDI": 12}, start="2026-08-04")


def test_pipeline_no_longer_swallows_sgs_failures():
    from pathlib import Path
    src = Path("src/pipeline/bacen_pipeline.py").read_text(encoding="utf-8")
    i = src.index("async def ingest_sgs(")
    body = src[i: src.index("async def ingest_ptax(")]
    assert 'logger.error("SGS fetch failed' not in body
    assert "raise RuntimeError(f\"SGS fetch failed" in body
