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

from silo_client import (  # noqa: E402
    SERVER_ROW_CAP,
    SiloClient,
    SiloError,
    SiloTimeout,
    SiloTruncated,
)

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


def _header_probe():
    seen = {}

    def responder(request):
        seen.update(request.headers)
        return httpx.Response(200, json=[])

    return seen, responder


def test_anonymous_sends_the_key_and_no_bearer():
    """Without a caller token the request must stay in the anon role."""
    seen, responder = _header_probe()
    c = make_client(catalog_then(responder))
    assert c.tier == "anon"
    c.coverage()
    assert seen.get("apikey") == "test-key"
    assert "authorization" not in seen


def test_a_token_moves_the_caller_to_the_authenticated_tier():
    """The publishable key identifies the PROJECT; the bearer identifies the CALLER.

    Without this the SDK was structurally stuck at the anonymous ceiling —
    3 panel ids, 25 search_funds rows, a 3s budget — no matter who was using
    it. The previous version of this test actively pinned that limitation.
    """
    seen, responder = _header_probe()
    c = SiloClient(
        url="https://example.supabase.co", key="test-key", token="jwt-abc",
        transport=httpx.MockTransport(catalog_then(responder)),
    )
    assert c.tier == "authenticated"
    c.coverage()
    assert seen.get("apikey") == "test-key", "the project key is still required"
    assert seen.get("authorization") == "Bearer jwt-abc"


def test_the_token_can_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("SILO_TOKEN", "env-jwt")
    seen, responder = _header_probe()
    c = SiloClient(
        url="https://example.supabase.co", key="test-key",
        transport=httpx.MockTransport(catalog_then(responder)),
    )
    c.coverage()
    assert seen.get("authorization") == "Bearer env-jwt"


def test_the_server_is_asked_to_count():
    """Without count=exact a capped response is indistinguishable from a whole one."""
    seen, responder = _header_probe()
    c = make_client(catalog_then(responder))
    c.coverage()
    assert "count=exact" in seen.get("prefer", "")


# ---------------------------------------------------------------------------
# Truncation. THE defect this release exists to close: PostgREST caps every
# response at db-max-rows (1000) and answers HTTP 200 with the first page,
# oldest first. Six years of daily quotes come back as three and a half, and
# the series simply appears to end. Range paging does not work on RPC, so the
# SDK cannot stitch the rest — raising is the only honest answer.
# ---------------------------------------------------------------------------

def _rows(n):
    return [{"date": "2024-01-01", "close": 1} for _ in range(n)]


def test_a_capped_response_raises_instead_of_returning_a_short_series():
    def responder(request):
        return httpx.Response(
            200, json=_rows(SERVER_ROW_CAP),
            headers={"Content-Range": f"0-{SERVER_ROW_CAP - 1}/4382"},
        )

    c = make_client(catalog_then(responder))
    with pytest.raises(SiloTruncated) as exc:
        c.quote_history("PETR4", start="2019-01-01")
    assert exc.value.returned == SERVER_ROW_CAP
    assert exc.value.total == 4382
    # The message must name what the caller can actually do about it.
    for lever in ("Narrow the window", "fewer ids", "one metric"):
        assert lever in str(exc.value)
    assert "aging does not work" in str(exc.value), "paging is not a workaround here"


def test_an_unconfirmable_full_page_also_raises():
    """Exactly the cap with no count is indistinguishable from truncation.

    Claiming completeness we cannot prove is the failure mode; a false positive
    costs the caller one narrower request.
    """
    def responder(request):
        return httpx.Response(200, json=_rows(SERVER_ROW_CAP))  # no Content-Range

    c = make_client(catalog_then(responder))
    with pytest.raises(SiloTruncated) as exc:
        c.quote_history("PETR4")
    assert exc.value.total is None


def test_a_complete_response_is_returned_untouched():
    def responder(request):
        return httpx.Response(200, json=_rows(42), headers={"Content-Range": "0-41/42"})

    c = make_client(catalog_then(responder))
    assert len(c.quote_history("PETR4")) == 42


def test_a_star_total_is_treated_as_unknown_not_zero():
    """PostgREST answers `0-41/*` when it was not asked to count."""
    def responder(request):
        return httpx.Response(200, json=_rows(42), headers={"Content-Range": "0-41/*"})

    c = make_client(catalog_then(responder))
    assert len(c.quote_history("PETR4")) == 42


def test_a_statement_timeout_is_its_own_error_with_advice():
    """57014 is a budget, not a bug — and the caller cannot raise the budget."""
    def responder(request):
        return httpx.Response(500, json={
            "code": "57014", "message": "canceling statement due to statement timeout",
        })

    c = make_client(catalog_then(responder))
    with pytest.raises(SiloTimeout) as exc:
        c.panel(["PETR4"], metrics=["close"])
    assert "3s to 8s" in str(exc.value), "signing in is the one lever that raises it"


def test_every_published_function_has_a_wrapper():
    """7 of 13 were wrapped; the rest were reachable only by hand.

    Read from the contract SQL so a new api.* function shows up here rather
    than being quietly absent from the client.
    """
    import re
    from pathlib import Path

    sql = (Path(__file__).resolve().parents[1]
           / "src/store/analytical/19_api_contract.sql").read_text()
    published = {
        m for m in re.findall(r"CREATE (?:OR REPLACE )?FUNCTION api\.(\w+)", sql)
        # internal helpers: REVOKEd from PUBLIC, never callable by a client
        if m not in {"caller_tier", "assert_panel_ids"}
    }
    missing = sorted(published - set(dir(SiloClient)))
    assert not missing, f"api functions with no SDK wrapper: {missing}"


def test_every_published_view_is_reachable():
    c = make_client(catalog_then(lambda r: httpx.Response(200, json=[])))
    assert len(SiloClient.VIEWS) == 8
    with pytest.raises(ValueError, match="unknown view"):
        c.view("not_a_view")


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
