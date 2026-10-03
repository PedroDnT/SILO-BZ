"""SiloClient implementations: envelopes, refusals, provenance (no network)."""

from __future__ import annotations

import datetime as dt
import json

import pytest

from src.portfolio.client import (
    DEFAULT_MCP_URL,
    FakeClient,
    McpClient,
    PostgrestClient,
    ToolError,
    parse_mcp_message,
)

FIXED = dt.datetime(2026, 10, 3, 15, 0, 0, tzinfo=dt.timezone.utc)
REFUSAL_BODY = (
    '{"code":"22023","details":"the response is one 1000-row page","hint":"narrow the window",'
    '"message":"screen_dormant_funds: 8218 rows exceed the 1000-row page"}'
)


def mcp_ok(rows):
    text = f"rows: {len(rows)}\nprovenance: POST /rest/v1/rpc/x · schema api · params {{}}\n{json.dumps(rows)}"
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": text}]}}


def transport_for(status, text, seen):
    def t(url, method, body, headers, timeout):
        seen.append((url, method, body, headers))
        return status, text

    return t


def test_mcp_request_envelope_and_rows():
    seen = []
    c = McpClient(transport=transport_for(200, json.dumps(mcp_ok([{"a": 1}, {"a": 2}])), seen), clock=lambda: FIXED)
    rows = c.call("lookup", {"p_query": "PETR4"})
    assert rows == [{"a": 1}, {"a": 2}]
    url, method, body, headers = seen[0]
    assert url == DEFAULT_MCP_URL and method == "POST"
    msg = json.loads(body)
    assert msg["jsonrpc"] == "2.0" and msg["method"] == "tools/call"
    assert msg["params"] == {"name": "lookup", "arguments": {"p_query": "PETR4"}}
    assert headers["apikey"].startswith("sb_publishable_")
    assert "authorization" not in {k.lower() for k in headers}
    assert "text/event-stream" in headers["accept"]
    p = c.provenance[0].as_dict()
    assert p == {
        "call_id": 1,
        "tool": "lookup",
        "args": {"p_query": "PETR4"},
        "requested_at_utc": "2026-10-03T15:00:00Z",
        "row_count": 2,
        "error": None,
    }


def test_mcp_sse_body_is_parsed():
    sse = "event: message\ndata: " + json.dumps(mcp_ok([{"k": "v"}])) + "\n\n"
    c = McpClient(transport=transport_for(200, sse, []))
    assert c.call("lookup", {}) == [{"k": "v"}]
    assert parse_mcp_message(sse)["id"] == 1


def test_mcp_refusal_is_verbatim_and_recorded():
    text = f"PostgREST error HTTP 400 from POST /rest/v1/rpc/screen_dormant_funds\n--- verbatim response body ---\n{REFUSAL_BODY}"
    body = {"jsonrpc": "2.0", "id": 1, "result": {"isError": True, "content": [{"type": "text", "text": text}]}}
    c = McpClient(transport=transport_for(200, json.dumps(body), []))
    with pytest.raises(ToolError) as ei:
        c.call("screen_dormant_funds", {})
    assert ei.value.sqlstate == "22023"
    assert REFUSAL_BODY in ei.value.verbatim
    assert c.provenance[0].error == text and c.provenance[0].row_count is None


def test_mcp_http_error_and_network_error_are_toolerrors():
    c = McpClient(transport=transport_for(502, "bad gateway", []))
    with pytest.raises(ToolError, match="MCP HTTP 502: bad gateway"):
        c.call("lookup", {})

    def boom(*a):
        raise OSError("tunnel failed")

    c2 = McpClient(transport=boom)
    with pytest.raises(ToolError, match="OSError: tunnel failed"):
        c2.call("lookup", {})
    assert c2.provenance[0].error == "OSError: tunnel failed"


def test_no_retry_one_request_per_call():
    seen = []
    c = McpClient(transport=transport_for(500, "x", seen))
    with pytest.raises(ToolError):
        c.call("lookup", {})
    assert len(seen) == 1


def test_secret_key_is_refused():
    with pytest.raises(ValueError):
        McpClient(api_key="sb_secret_abc")
    with pytest.raises(ValueError):
        PostgrestClient(api_key="sb_secret_abc")


def test_postgrest_rpc_and_view_requests():
    seen = []
    c = PostgrestClient(transport=transport_for(200, "[]", seen))
    c.call("portfolio_fees", {"p_cnpjs": ["1"], "p_month": "2026-08-01"})
    c.call("short_interest", {"filters": {"ticker": "eq.PETR4"}, "order": "trade_date.desc", "limit": 1})
    (url1, m1, b1, h1), (url2, m2, b2, h2) = seen
    assert url1.endswith("/rest/v1/rpc/portfolio_fees") and m1 == "POST"
    assert json.loads(b1) == {"p_cnpjs": ["1"], "p_month": "2026-08-01"}
    assert h1["Accept-Profile"] == "api" and h1["Content-Profile"] == "api" and "Authorization" not in h1
    assert m2 == "GET" and b2 is None and h2["Accept-Profile"] == "api"
    assert "ticker=eq.PETR4" in url2 and "order=trade_date.desc" in url2 and "limit=1" in url2


def test_postgrest_error_is_verbatim():
    c = PostgrestClient(transport=transport_for(400, REFUSAL_BODY, []))
    with pytest.raises(ToolError) as ei:
        c.call("screen_dormant_funds", {})
    assert ei.value.sqlstate == "22023" and REFUSAL_BODY in ei.value.verbatim


def test_fake_client_matches_subset_and_records():
    c = FakeClient(
        {
            "t": [
                {"match": {"p_a": 1}, "rows": [{"x": 1}]},
                {"match": {}, "error": "boom 22023"},
            ]
        },
        clock=lambda: FIXED,
    )
    assert c.call("t", {"p_a": 1, "p_b": 2}) == [{"x": 1}]
    with pytest.raises(ToolError, match="boom"):
        c.call("t", {"p_a": 9})
    with pytest.raises(ToolError, match="no canned answer"):
        c.call("unknown", {})
    assert [p.row_count for p in c.provenance] == [1, None, None]
    assert c.provenance[1].error == "boom 22023"
