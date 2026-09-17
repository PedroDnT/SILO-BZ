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
    SiloOverCap,
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
# the series simply appears to end. The SDK never returns that short answer as
# if it were the series.
#
# What it offers INSTEAD has moved on, and the message has to keep up. RANGE
# paging still does not work on RPC — but p_after does, and since catalog
# v24/v26 panel, quote_history and fund_nav all carry that cursor while the
# server refuses an over-page window outright (22023) rather than trimming it.
# So "paging is not a workaround" is no longer true of the responses below;
# it is true only where no cursor exists, which is a view read with no page
# bounds. The message names the levers AND the right cursor for the surface.
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
    # And it must point at the cursor that actually exists for this surface.
    # quote_history DOES page with p_after (iter_quote_history), so a message
    # saying paging is impossible here would send the caller to narrow a window
    # they could simply have walked.
    assert "iter_quote_history()" in str(exc.value)


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


def test_the_package_reports_one_version():
    """`pip show silo-client` and `silo_client.__version__` must agree.

    They had drifted to 0.4.0 in pyproject.toml against 0.6.0 in the package,
    so the two ways of asking "which build is this?" named different releases
    of the same code and neither could be trusted in a bug report.
    """
    import re
    from pathlib import Path

    import silo_client

    pyproject = (
        Path(__file__).resolve().parents[1] / "sdk" / "pyproject.toml"
    ).read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M)
    assert m, "sdk/pyproject.toml has no version"
    assert m.group(1) == silo_client.__version__, (
        f"sdk/pyproject.toml says {m.group(1)}, silo_client.__version__ says "
        f"{silo_client.__version__} — they describe the same build"
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
    assert len(SiloClient.VIEWS) == 13
    with pytest.raises(ValueError, match="unknown view"):
        c.view("not_a_view")


# ---------------------------------------------------------------------------
# The B3 lending / investor-flow group (catalog v27).
#
# These five views were GRANTed to anon/authenticated and answering on the
# publishable key for weeks before anything could discover them: absent from
# api.catalog(), from serve/catalog.py, from every docs page, and not even
# listed in SiloClient.VIEWS — so view() refused them as unknown. The tests
# below pin the two halves of the fix together: the catalog publishes them,
# and the client can reach them by name.
# ---------------------------------------------------------------------------

_LENDING_VIEWS = (
    "short_interest",
    "short_interest_by_sector",
    "lending_trades",
    "lending_participants",
    "investor_flow",
)


@pytest.mark.parametrize("name", _LENDING_VIEWS)
def test_lending_views_are_published_and_named(name):
    """Each one is in VIEWS, has a wrapper, and hits its own REST resource."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json=[])

    assert name in SiloClient.VIEWS
    c = make_client(catalog_then(handler))
    method = getattr(c, name)
    assert callable(method), f"SiloClient.{name} is missing"
    method(order="trade_date.desc")
    assert seen["path"].endswith(f"/rest/v1/{name}")


@pytest.mark.parametrize("name", _LENDING_VIEWS)
def test_lending_view_filters_pass_through_verbatim(name):
    """PostgREST's own filter syntax, not a query language invented here."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["query"] = str(request.url.query, "utf-8")
        return httpx.Response(200, json=[])

    c = make_client(catalog_then(handler))
    getattr(c, name)(ticker="eq.PETR4", limit=5)
    assert "ticker=eq.PETR4" in seen["query"]


def test_the_catalog_publishes_every_lending_endpoint():
    """A named wrapper nobody can find in the catalog is still undiscoverable.

    The whole defect this group fixes is that the endpoints existed and the
    contract did not mention them, so an agent following the catalog-first
    instruction could not reach them. Pin both halves together.
    """
    from serve.catalog import catalog_payload

    postgrest = catalog_payload()["postgrest"]
    for name in _LENDING_VIEWS:
        assert name in postgrest, f"catalog does not publish {name}"
        assert postgrest[name] == f"GET /rest/v1/{name}", (
            f"{name} is a view, not an RPC: it filters and pages with "
            "PostgREST syntax, and telling an agent to POST it is a 404"
        )


def test_the_lending_caveats_travel_with_the_endpoints():
    """The four ways to be confidently wrong, stated where an agent reads.

    These are not decoration. A pct_float ranking that mixes float bases, a
    broker read as a beneficial owner, a first difference summed through its
    null rows, or a 21-session window read as a data gap each produce a
    confident, wrong answer — so the constraints must ship with the endpoints,
    not in a docs page the agent never opens.
    """
    from serve.catalog import catalog_payload

    joined = " ".join(catalog_payload()["constraints"]).lower()
    assert "ratchet" in joined and "21 business days" in joined
    assert "float_basis" in joined and "index_free_float" in joined
    assert "brokerages, not beneficial owners" in joined
    assert "first difference" in joined and "unknown_opening_snapshot" in joined


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


# ---------------------------------------------------------------------------
# The panel refuses over the page and pages with p_after (catalog v24)
# ---------------------------------------------------------------------------

_OVER_CAP_BODY = (
    '{"code":"22023","message":"panel: your window produces more than 1000 rows, '
    'which the server would silently cut at 1000. Narrow p_from/p_to, ids or '
    'metrics, or page with p_after (start with p_after = \'\')."}'
)


def _panel_rows(n, start=0, id_="PETR4", asset_class="equity", metric="close"):
    return [
        {"id": id_, "id_type": "ticker", "asset_class": asset_class,
         "date": f"2024-{(i // 28) % 12 + 1:02d}-{i % 28 + 1:02d}", "metric": metric,
         "value": float(i), "source": "b3_cotahist"}
        for i in range(start, start + n)
    ]


def test_a_refused_panel_is_its_own_error_and_names_the_way_out():
    c = make_client(catalog_then(lambda r: httpx.Response(400, text=_OVER_CAP_BODY)))
    with pytest.raises(SiloOverCap) as exc:
        c.panel(["PETR4"], metrics=["close"], start="2019-01-01", freq="day")
    assert exc.value.status == 400
    assert "iter_panel" in exc.value.hint and "p_after" in exc.value.hint
    assert isinstance(exc.value, SiloError)


def test_other_22023s_stay_plain_errors():
    body = '{"code":"22023","message":"panel accepts at most 3 ids per call"}'
    c = make_client(catalog_then(lambda r: httpx.Response(400, text=body)))
    with pytest.raises(SiloError) as exc:
        c.panel(["A", "B", "C", "D"], metrics=["close"], wide=False)
    assert not isinstance(exc.value, SiloOverCap)


def test_iter_panel_walks_pages_with_the_last_rows_key_and_stops_on_a_short_page():
    seen = []
    page1 = _panel_rows(SERVER_ROW_CAP)
    page2 = _panel_rows(3, start=SERVER_ROW_CAP)

    def responder(request):
        body = json.loads(request.content)
        seen.append(body.get("p_after"))
        rows = page1 if body.get("p_after") == "" else page2
        return httpx.Response(200, json=rows, headers={"Content-Range": f"0-{len(rows)-1}/*"})

    c = make_client(catalog_then(responder))
    rows = list(c.iter_panel(["PETR4"], metrics=["close"], start="2019-01-01", freq="day"))
    assert len(rows) == SERVER_ROW_CAP + 3
    last = page1[-1]
    assert seen == ["", f"{last['date']}|{last['id']}|{last['metric']}|{last['asset_class']}"]


def test_panel_all_is_iter_panel_collected_and_can_pivot():
    def responder(request):
        return httpx.Response(200, json=_panel_rows(5))

    c = make_client(catalog_then(responder))
    rows = c.panel_all(["PETR4"], metrics=["close"], freq="day")
    assert len(rows) == 5
    df = c.panel_all(["PETR4"], metrics=["close"], freq="day", wide=True)
    assert df.shape == (5, 1)


def test_a_full_page_in_paging_mode_is_a_page_not_a_truncation():
    """iter_panel passes page=True, so exactly 1000 rows with no total does
    not raise SiloTruncated — it asks for the next page."""
    calls = {"n": 0}

    def responder(request):
        calls["n"] += 1
        rows = _panel_rows(SERVER_ROW_CAP) if calls["n"] == 1 else []
        return httpx.Response(200, json=rows)

    c = make_client(catalog_then(responder))
    assert len(list(c.iter_panel(["PETR4"], metrics=["close"], freq="day"))) == SERVER_ROW_CAP
    assert calls["n"] == 2


def test_wide_pivot_refuses_a_cnpj_that_files_under_two_families():
    rows = [
        {"id": "11726466000195", "id_type": "cnpj", "asset_class": "fi",
         "date": "2025-06-01", "metric": "nav", "value": 26520603.71, "source": "cvm"},
        {"id": "11726466000195", "id_type": "cnpj", "asset_class": "fidc",
         "date": "2025-06-01", "metric": "nav", "value": 26579571.83, "source": "cvm"},
    ]
    c = make_client(catalog_then(lambda r: httpx.Response(200, json=rows)))
    with pytest.raises(ValueError) as exc:
        c.panel(["11726466000195"], metrics=["nav"])
    assert "11726466000195" in str(exc.value) and "entity_type" in str(exc.value)
    # long rows are handed back untouched: the caller keeps asset_class
    assert len(c.panel(["11726466000195"], metrics=["nav"], wide=False)) == 2


def test_panel_sends_entity_type_and_universe_filters():
    captured = {}

    def responder(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=[])

    c = make_client(catalog_then(responder))
    c.panel(None, metrics=["nav"], entity_type="fidc", min_nav=1e7, min_months=12, wide=False)
    assert captured["body"]["p_ids"] == []
    assert captured["body"]["p_entity_type"] == "fidc"
    assert captured["body"]["p_min_nav"] == 1e7
    assert captured["body"]["p_min_months"] == 12


def test_universe_mode_needs_a_family_client_side():
    c = make_client(catalog_then(lambda r: httpx.Response(200, json=[])))
    with pytest.raises(ValueError):
        c.panel(None, metrics=["nav"])
    with pytest.raises(ValueError):
        list(c.iter_panel([], metrics=["nav"]))


# ---------------------------------------------------------------------------
# v26 — the series functions refuse and page like the panel
# ---------------------------------------------------------------------------

def _quote_rows(n: int, start: int = 0):
    return [
        {"ticker": "PETR4",
         "trade_date": f"2019-{1 + (start + i) // 28 % 12:02d}-{1 + (start + i) % 28:02d}",
         "close": 10.0 + i}
        for i in range(n)
    ]


def test_iter_quote_history_walks_pages_with_the_last_rows_trade_date():
    seen = []
    page1 = _quote_rows(SERVER_ROW_CAP)
    page2 = _quote_rows(7, start=SERVER_ROW_CAP)

    def responder(request):
        body = json.loads(request.content)
        seen.append(body.get("p_after"))
        rows = page1 if body.get("p_after") == "" else page2
        return httpx.Response(200, json=rows,
                              headers={"Content-Range": f"0-{len(rows)-1}/*"})

    c = make_client(catalog_then(responder))
    rows = list(c.iter_quote_history("PETR4", start="2019-01-01"))
    assert len(rows) == SERVER_ROW_CAP + 7
    # The cursor is the bare date of the last row, not a composite key.
    assert seen == ["", page1[-1]["trade_date"]]


def test_quote_history_all_is_the_iterator_collected():
    def responder(request):
        return httpx.Response(200, json=_quote_rows(4))

    c = make_client(catalog_then(responder))
    assert len(c.quote_history_all("PETR4")) == 4


def test_iter_fund_nav_refuses_to_page_without_a_family():
    """The cursor is a bare period, unique only within one family: 385 CNPJs
    file under two in the same month. Paging without a family would skip or
    repeat a row at a page edge, so the client refuses before the round trip
    — the server refuses too (22023), but failing here names the fix."""
    c = make_client(catalog_then(lambda r: httpx.Response(200, json=[])))
    with pytest.raises(ValueError) as exc:
        list(c.iter_fund_nav("05754060000113", ""))
    assert "entity_type" in str(exc.value)
    assert "fund_nav()" in str(exc.value), "name the whole-result escape hatch"


def test_iter_fund_nav_pages_within_one_family_on_the_period():
    seen = []
    page1 = [{"cnpj": "05754060000113", "period": f"20{19 + i // 12:02d}-{1 + i % 12:02d}-28",
              "entity_type": "fi", "nav": 1.0 * i} for i in range(SERVER_ROW_CAP)]
    page2 = [{"cnpj": "05754060000113", "period": "2099-01-31",
              "entity_type": "fi", "nav": 2.0}]

    def responder(request):
        body = json.loads(request.content)
        seen.append((body.get("p_after"), body.get("p_entity_type")))
        rows = page1 if body.get("p_after") == "" else page2
        return httpx.Response(200, json=rows,
                              headers={"Content-Range": f"0-{len(rows)-1}/*"})

    c = make_client(catalog_then(responder))
    rows = list(c.iter_fund_nav("05754060000113", "fi"))
    assert len(rows) == SERVER_ROW_CAP + 1
    # Every page carries the family; the cursor is the last row's period.
    assert seen == [("", "fi"), (page1[-1]["period"], "fi")]


def test_metric_coverage_is_served_and_separate_from_coverage():
    calls = []

    def responder(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=[
            {"entity_type": "fidc", "metric": "delinquency",
             "first_period": "2025-01-31", "last_period": "2026-08-31",
             "filed_rows": 73259, "total_rows": 73259},
        ])

    c = make_client(catalog_then(responder))
    rows = c.metric_coverage()
    assert calls[-1].endswith("/rpc/metric_coverage")
    assert rows[0]["first_period"] == "2025-01-31"


# ---------------------------------------------------------------------------
# pandas is a HARD dependency, not an extra.
#
# `panel()` defaults to `wide=True`, and the README, api-docs/sdk.mdx and the
# notebooks all lead with a DataFrame — so while pandas was an optional extra,
# a bare `pip install silo-client` followed by the documented first call raised
# ImportError. Defaulting `wide=False` instead would have silently changed the
# return type under fifteen existing call sites, which is the worse failure.
# ---------------------------------------------------------------------------


def test_pandas_is_a_hard_dependency():
    """Not an extra: the documented first call must work on a bare install."""
    import re
    from pathlib import Path

    pyproject = (Path(__file__).resolve().parents[1] / "sdk" / "pyproject.toml").read_text()
    m = re.search(r"^dependencies\s*=\s*\[(?P<deps>[^\]]*)\]", pyproject, re.M)
    assert m, "sdk/pyproject.toml declares no [project] dependencies"
    assert "pandas" in m.group("deps"), (
        "pandas must be a hard dependency — panel() defaults to wide=True, so a "
        "bare install would otherwise fail on the documented first call"
    )


def test_panel_still_defaults_to_wide():
    """If this default ever flips, the dependency rationale above changes too."""
    import inspect

    sig = inspect.signature(SiloClient.panel)
    assert sig.parameters["wide"].default is True


def test_install_docs_do_not_advertise_a_pandas_extra():
    """The `[pandas]` extra is now a no-op; telling people to install it misleads."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for rel in ("sdk/README.md", "api-docs/sdk.mdx"):
        text = (root / rel).read_text()
        assert "[pandas]" not in text, (
            f"{rel} still advertises the pandas extra, which no longer adds anything"
        )


# ---------------------------------------------------------------------------
# A bare string is ONE id / ONE metric, never its characters.
#
# `str` satisfies `Sequence[str]`, so `list("PETR4")` is ['P','E','T','R','4'] —
# five ids that do not exist. The server answers that with an empty panel and a
# 200, which reads as "no data for PETR4". Brackets stay optional, and the
# single-string case is spelled out rather than left to sequence semantics.
# ---------------------------------------------------------------------------


def _capture_panel_body():
    """A handler that records the RPC body and returns one row."""
    seen = {}

    def responder(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=[
            {"id": "PETR4", "asset_class": "equity", "date": "2026-08-31",
             "metric": "close", "value": 38.1},
        ])

    return seen, catalog_then(responder)


def test_a_bare_string_id_is_one_id_not_five_characters():
    seen, handler = _capture_panel_body()
    make_client(handler).panel("PETR4", metrics="close")
    assert seen["body"]["p_ids"] == ["PETR4"]
    assert seen["body"]["p_metrics"] == ["close"]


def test_brackets_and_bare_strings_send_the_same_body():
    seen_a, handler_a = _capture_panel_body()
    make_client(handler_a).panel("PETR4", metrics="close")
    seen_b, handler_b = _capture_panel_body()
    make_client(handler_b).panel(["PETR4"], metrics=["close"])
    assert seen_a["body"] == seen_b["body"]


def test_a_bare_metric_typo_names_the_metric_not_its_letters():
    _, handler = _capture_panel_body()
    with pytest.raises(ValueError) as exc:
        make_client(handler).panel("PETR4", metrics="clse")
    assert "'clse'" in str(exc.value)


def test_sequences_still_work_for_ids_and_metrics():
    seen, handler = _capture_panel_body()
    make_client(handler).panel(("PETR4", "VALE3"), metrics=("close", "nav"))
    assert seen["body"]["p_ids"] == ["PETR4", "VALE3"]
    assert seen["body"]["p_metrics"] == ["close", "nav"]


def test_universe_mode_still_sends_an_empty_id_list():
    """ids=None + entity_type is universe mode; it must not become [''] ."""
    seen, handler = _capture_panel_body()
    make_client(handler).panel(None, metrics="nav", entity_type="fidc")
    assert seen["body"]["p_ids"] == []
    assert seen["body"]["p_entity_type"] == "fidc"


def test_iter_panel_normalises_the_same_way():
    seen, handler = _capture_panel_body()
    list(make_client(handler).iter_panel("PETR4", metrics="close"))
    assert seen["body"]["p_ids"] == ["PETR4"]
