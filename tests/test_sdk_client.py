"""silo-client SDK: offline contract tests via httpx.MockTransport.

No network. The mock serves the documented response shapes; the tests pin
the client's honesty rules — catalog-driven validation, NaN-stays-NaN,
NULL `to` passthrough (the server's honest-window clamp), and loud errors.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdk"))

from silo_client import SiloClient, SiloError  # noqa: E402

CATALOG = {
    "kind": "catalog",
    "version": 9,
    "metrics": {
        "close": {"id_type": ["ticker"]},
        "nav": {"id_type": ["cnpj"]},
        "delinquency": {"id_type": ["cnpj"]},
    },
}


def make_client(handler):
    return SiloClient(
        url="https://example.supabase.co",
        key="test-key",
        transport=httpx.MockTransport(handler),
    )


def catalog_then(responder):
    """Route /rpc/catalog to the fixture, everything else to `responder`."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/rpc/catalog"):
            return httpx.Response(200, json=CATALOG)
        return responder(request)

    return handler


def test_requires_url_and_key(monkeypatch):
    monkeypatch.delenv("SILO_URL", raising=False)
    monkeypatch.delenv("SILO_ANON_KEY", raising=False)
    with pytest.raises(ValueError):
        SiloClient()
    with pytest.raises(ValueError):
        SiloClient(url="https://example.supabase.co")


def test_apikey_header_only_never_bearer():
    seen = {}

    def responder(request):
        seen.update(request.headers)
        return httpx.Response(200, json=[])

    c = make_client(catalog_then(responder))
    c.coverage()
    assert seen.get("apikey") == "test-key"
    # The docs are explicit: publishable key via apikey only, never a
    # bearer token the server would treat as an auth credential.
    assert "authorization" not in seen


def test_catalog_is_cached():
    calls = {"n": 0}

    def handler(request):
        assert request.url.path.endswith("/rpc/catalog")
        calls["n"] += 1
        return httpx.Response(200, json=CATALOG)

    c = make_client(handler)
    c.catalog()
    c.catalog()
    assert c.metrics() == ["close", "delinquency", "nav"]
    assert calls["n"] == 1
    c.catalog(refresh=True)
    assert calls["n"] == 2


def test_unknown_metric_fails_client_side_and_loudly():
    def responder(request):  # pragma: no cover - must never be reached
        raise AssertionError("panel must not be called with an unknown metric")

    c = make_client(catalog_then(responder))
    with pytest.raises(ValueError, match="close_retrun"):
        c.panel(["PETR4"], metrics=["close_retrun"])


def test_panel_omitted_end_sends_no_p_to():
    captured = {}

    def responder(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=[])

    c = make_client(catalog_then(responder))
    c.panel(["PETR4"], metrics=["close"], wide=False)
    # None keys are dropped, so the SERVER default (NULL -> the honest
    # completeness clamp) applies — the client must not inject a date.
    assert "p_to" not in captured["body"]
    assert captured["body"]["p_ids"] == ["PETR4"]


def test_panel_wide_keeps_gaps_as_nan():
    rows = [
        {"id": "PETR4", "id_type": "ticker", "asset_class": "equity",
         "date": "2026-06-01", "metric": "close", "value": 40.0, "source": "b3"},
        {"id": "PETR4", "id_type": "ticker", "asset_class": "equity",
         "date": "2026-07-01", "metric": "close", "value": 41.0, "source": "b3"},
        # 11222333000144 has no June observation — that gap must stay NaN.
        {"id": "11222333000144", "id_type": "cnpj", "asset_class": "fi",
         "date": "2026-07-01", "metric": "nav", "value": 1e9, "source": "cvm"},
    ]

    c = make_client(catalog_then(lambda r: httpx.Response(200, json=rows)))
    df = c.panel(["PETR4", "11222333000144"], metrics=["close", "nav"])
    import pandas as pd

    assert list(df.index) == [pd.Timestamp("2026-06-01"), pd.Timestamp("2026-07-01")]
    assert pd.isna(df.loc["2026-06-01", ("11222333000144", "nav")])
    assert df.loc["2026-07-01", ("PETR4", "close")] == 41.0


def test_empty_panel_is_an_empty_frame_not_an_error():
    c = make_client(catalog_then(lambda r: httpx.Response(200, json=[])))
    df = c.panel(["ZZZZ9"], metrics=["close"])
    assert df.empty


def test_server_errors_surface_with_the_servers_message():
    err = {"message": "option_chain requires p_prefix: a codneg prefix of at least 3 characters"}

    c = make_client(catalog_then(lambda r: httpx.Response(400, json=err)))
    with pytest.raises(SiloError, match="requires p_prefix") as ei:
        c.option_chain("PE")
    assert ei.value.status == 400


def test_dates_serialize_iso():
    from datetime import date

    captured = {}

    def responder(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=[])

    c = make_client(catalog_then(responder))
    c.fund_nav("11222333000144", start=date(2019, 1, 1), end="2026-07-31")
    assert captured["body"]["p_from"] == "2019-01-01"
    assert captured["body"]["p_to"] == "2026-07-31"
