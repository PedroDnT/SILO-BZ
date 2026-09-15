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
    KNOWN_CATALOG_VERSION,
    SERVER_ROW_CAP,
    SiloCatalogDrift,
    SiloClient,
    SiloError,
    SiloTimeout,
    SiloTruncated,
)

CATALOG = {
    "kind": "catalog",
    "version": KNOWN_CATALOG_VERSION,
    "metrics": {
        "close": {"id_type": ["ticker"]},
        "nav": {"id_type": ["cnpj"]},
        "delinquency": {"id_type": ["cnpj"]},
    },
    "limits": {
        "rows_per_response": {"value": 1000},
        "tiers": {"anon": {"panel_ids": 3}, "authenticated": {"panel_ids": 50}},
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


def test_a_truncated_error_carries_the_partial_page_for_inspection():
    """The rows are evidence of where the cut fell — not a shorter answer.

    They ride on the exception so a caller can see the last date served and
    narrow the window from there, without the SDK ever RETURNING them as if
    they were the series.
    """
    rows = _rows(SERVER_ROW_CAP)
    rows[-1] = {"date": "2023-01-09", "close": 1}

    def responder(request):
        return httpx.Response(
            200, json=rows, headers={"Content-Range": f"0-{SERVER_ROW_CAP - 1}/1906"},
        )

    c = make_client(catalog_then(responder))
    with pytest.raises(SiloTruncated) as exc:
        c.quote_history("PETR4", start="2019-01-01")
    assert len(exc.value.rows) == SERVER_ROW_CAP
    assert exc.value.rows[-1]["date"] == "2023-01-09", "the cut date is the useful fact"
    assert ".rows" in str(exc.value)


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
    # "Published" is not the same as "defined": an internal helper is CREATEd
    # exactly like a public function and then REVOKEd from PUBLIC. The client
    # surface is precisely what anon may EXECUTE, so read the grants rather
    # than maintaining a second hand-written list of helpers that drifts.
    published = set(
        re.findall(r"GRANT EXECUTE ON FUNCTION api\.(\w+)\([^)]*\)\s*TO anon", sql)
    )
    assert len(published) >= 14, f"grant scan found too few functions: {published}"

    missing = sorted(published - set(dir(SiloClient)))
    assert not missing, f"api functions with no SDK wrapper: {missing}"


# ---------------------------------------------------------------------------
# Views are the ONE surface that pages. The docs' "enumerate every FIDC from
# the funds view with limit/offset" pattern used to raise SiloTruncated on the
# first page, because the RPC truncation rule (total > returned => wrong
# answer) fired on a response that was exactly the page the caller asked for.
# ---------------------------------------------------------------------------

def _view_server(total, page_cap=SERVER_ROW_CAP):
    """A mock view of `total` rows that honours limit/offset and counts."""
    seen = []

    def responder(request):
        q = dict(request.url.params)
        seen.append(q)
        limit = min(int(q.get("limit", page_cap)), page_cap)
        offset = int(q.get("offset", 0))
        rows = [{"cnpj": f"{i:014d}"} for i in range(offset, min(offset + limit, total))]
        end = offset + len(rows) - 1
        return httpx.Response(
            200, json=rows, headers={"Content-Range": f"{offset}-{end}/{total}"},
        )

    return seen, responder


def test_an_explicit_view_page_is_a_page_not_a_truncation():
    seen, responder = _view_server(total=2500)
    c = make_client(catalog_then(responder))
    page = c.view("funds", entity_type="eq.fidc", order="cnpj.asc", limit=1000, offset=1000)
    assert len(page) == 1000
    assert page[0]["cnpj"] == f"{1000:014d}", "page two starts at offset 1000"
    assert seen[-1]["offset"] == "1000"


def test_a_view_with_no_limit_that_hits_the_cap_still_raises():
    """No limit means the caller did not ask for a page; a 1000-row answer to
    a 2500-row question is the same silent cut a function call would be."""
    _, responder = _view_server(total=2500)
    c = make_client(catalog_then(responder))
    with pytest.raises(SiloTruncated) as exc:
        c.view("funds", entity_type="eq.fidc")
    assert exc.value.total == 2500


def test_view_all_walks_every_page_and_stops_at_the_total():
    seen, responder = _view_server(total=2500)
    c = make_client(catalog_then(responder))
    rows = c.view_all("funds", entity_type="eq.fidc", order="cnpj.asc")
    assert len(rows) == 2500
    assert [r["cnpj"] for r in rows] == [f"{i:014d}" for i in range(2500)], "no dup, no gap"
    offsets = [q["offset"] for q in seen]
    assert offsets == ["0", "1000", "2000"], "three pages, no fourth empty round trip"
    assert all(q["order"] == "cnpj.asc" for q in seen), "the order rides on every page"


def test_view_all_stops_on_a_short_page_when_the_server_does_not_count():
    calls = {"n": 0}

    def responder(request):
        calls["n"] += 1
        offset = int(request.url.params.get("offset", 0))
        rows = [{"cnpj": str(i)} for i in range(offset, min(offset + 1000, 1300))]
        return httpx.Response(200, json=rows)  # no Content-Range at all

    c = make_client(catalog_then(responder))
    assert len(c.view_all("funds", order="cnpj.asc")) == 1300
    assert calls["n"] == 2


def test_view_all_page_size_is_clamped_to_the_server_cap():
    seen, responder = _view_server(total=10)
    c = make_client(catalog_then(responder))
    c.view_all("funds", order="cnpj.asc", page_size=5000)
    assert seen[0]["limit"] == str(SERVER_ROW_CAP), "the server would clamp it silently; we say so"


def test_view_all_requires_an_order():
    """Offset paging with no total order can duplicate a row at one boundary
    and drop one at the next, with nothing in the response to say so."""
    _, responder = _view_server(total=10)
    c = make_client(catalog_then(responder))
    with pytest.raises(ValueError, match="order"):
        c.view_all("funds", entity_type="eq.fidc")
    with pytest.raises(ValueError, match="page_size"):
        c.view_all("funds", order="cnpj.asc", limit=100)


def test_iter_view_is_lazy_and_carries_no_extra_rows():
    seen, responder = _view_server(total=2500)
    c = make_client(catalog_then(responder))
    it = c.iter_view("funds", order="cnpj.asc")
    first = next(it)
    assert first["cnpj"] == f"{0:014d}"
    assert len(seen) == 1, "one page fetched for one row"


# ---------------------------------------------------------------------------
# The catalog carries the limits as numbers, and tells the client when it is
# out of date.
# ---------------------------------------------------------------------------

def test_limits_are_read_from_the_catalog():
    c = make_client(catalog_then(lambda r: httpx.Response(200, json=[])))
    assert c.limits()["rows_per_response"]["value"] == SERVER_ROW_CAP
    assert c.limits()["tiers"]["anon"]["panel_ids"] == 3


def test_the_client_row_cap_matches_the_published_catalog():
    """SERVER_ROW_CAP is the one number the client hard-codes; the catalog must
    agree, or an agent reading the catalog and a script using the SDK would
    defend against two different ceilings."""
    from serve.catalog import CATALOG_VERSION, catalog_payload

    limits = catalog_payload()["limits"]
    assert limits["rows_per_response"]["value"] == SERVER_ROW_CAP
    assert CATALOG_VERSION == KNOWN_CATALOG_VERSION, (
        "serve/catalog.py moved on; bump KNOWN_CATALOG_VERSION in the SDK "
        "after checking the wrappers still match"
    )


def test_a_matching_catalog_version_is_silent():
    import warnings

    c = make_client(catalog_then(lambda r: httpx.Response(200, json=[])))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        c.catalog()


def test_a_newer_server_catalog_warns_and_still_serves():
    newer = {**CATALOG, "version": KNOWN_CATALOG_VERSION + 5}

    def handler(request):
        return httpx.Response(200, json=newer)

    c = make_client(handler)
    with pytest.warns(SiloCatalogDrift, match="newer"):
        payload = c.catalog()
    assert payload["version"] == KNOWN_CATALOG_VERSION + 5, "warned, not refused"
    # Cached: the second read does not warn again.
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        c.catalog()


def test_an_older_server_catalog_warns_too():
    older = {**CATALOG, "version": KNOWN_CATALOG_VERSION - 1}
    c = make_client(lambda r: httpx.Response(200, json=older))
    with pytest.warns(SiloCatalogDrift, match="older"):
        c.catalog()


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
