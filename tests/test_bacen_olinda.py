"""Olinda HTTP retries for BACEN PTAX / Expectativas.

HTTP is mocked. The 2026-08-19 daily ingest (Actions run 32221952063) died
because Olinda answered HTML 503 and `_olinda_get` parsed that body as JSON
with no retry, failing the whole job after CVM/ANBIMA/B3 had already landed.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from src.fetchers.bacen_fetcher import (
    BacenClient,
    BacenFetchError,
    _olinda_parse,
)


_503_HTML = (
    '<!DOCTYPE HTML PUBLIC "-//IETF//DTD HTML 2.0//EN">\n'
    "<html><head>\n"
    "<title>503 Service Temporarily Unavailable</title>\n"
    "</head><body>\n"
    "<h1>Service Temporarily Unavailable</h1>\n"
    "<p>The server is temporarily unable to service your request.\n"
)


def _client_factory(handler):
    transport = httpx.MockTransport(handler)
    orig = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return orig(*args, **kwargs)

    return factory


@pytest.fixture
def no_backoff(monkeypatch):
    monkeypatch.setenv("BACEN_OLINDA_RETRY_DELAY", "0")


def test_olinda_parse_unwraps_error_envelope():
    with pytest.raises(BacenFetchError, match="Invalid name"):
        _olinda_parse(
            '/*{"codigo":"500","mensagem":"Invalid name"}*/',
            "https://olinda.example/x",
        )


def test_olinda_parse_rejects_html():
    with pytest.raises(BacenFetchError, match="response is not JSON"):
        _olinda_parse(_503_HTML, "https://olinda.example/x")


@pytest.mark.asyncio
async def test_ptax_503_then_200_succeeds(no_backoff, monkeypatch):
    """The Aug 19 failure mode: HTML 503 is retried, then rows land."""
    monkeypatch.setenv("BACEN_OLINDA_MAX_RETRIES", "3")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, text=_503_HTML)
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "cotacaoCompra": 5.10,
                        "cotacaoVenda": 5.11,
                        "dataHoraCotacao": "2026-08-19 13:00:00.000",
                    }
                ]
            },
        )

    client = BacenClient()
    with patch("httpx.AsyncClient", side_effect=_client_factory(handler)):
        rows = await client.get_ptax_moeda_periodo("USD", "2026-07-20", "2026-08-19")

    assert calls["n"] == 3
    assert len(rows) == 1
    assert rows[0]["cotacaoVenda"] == pytest.approx(5.11)


@pytest.mark.asyncio
async def test_ptax_503_exhausted_raises_http_status(no_backoff, monkeypatch):
    monkeypatch.setenv("BACEN_OLINDA_MAX_RETRIES", "2")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, text=_503_HTML)

    client = BacenClient()
    with patch("httpx.AsyncClient", side_effect=_client_factory(handler)):
        with pytest.raises(BacenFetchError, match=r"failed after 2 attempts:.*HTTP 503"):
            await client.get_ptax_moeda_periodo("USD", "2026-07-20", "2026-08-19")

    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_expectativas_400_envelope_is_not_retried(no_backoff, monkeypatch):
    """Client errors are permanent; retrying cannot help."""
    monkeypatch.setenv("BACEN_OLINDA_MAX_RETRIES", "4")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            400,
            text='/*{"codigo":"400","mensagem":"Invalid name"}*/',
        )

    client = BacenClient()
    with patch("httpx.AsyncClient", side_effect=_client_factory(handler)):
        with pytest.raises(BacenFetchError, match="Invalid name"):
            await client.get_expectativas("ExpectativasMercadoMensais", start="2026-07-20")

    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_olinda_network_error_is_retried(no_backoff, monkeypatch):
    monkeypatch.setenv("BACEN_OLINDA_MAX_RETRIES", "3")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json={"value": []})

    client = BacenClient()
    with patch("httpx.AsyncClient", side_effect=_client_factory(handler)):
        rows = await client.get_ptax_moeda_periodo("EUR", "2026-07-20", "2026-08-19")

    assert calls["n"] == 2
    assert rows == []
