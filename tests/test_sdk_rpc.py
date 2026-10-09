"""SiloClient.rpc(): any published function, checked against the bundled contract.

The named methods cover most of schema `api`, but recent endpoints shipped with
"no SDK wrapper" and were reachable only through the private `_rpc`. `rpc()`
is the public door: it checks the function name and every argument name
against `sdk/silo_client/contract.json` (generated from `openapi.json` by
`scripts/gen_sdk_contract.py`) before anything is sent, because PostgREST
resolves a call by argument NAMES and answers a typo with a 404 against a
function that exists.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import httpx
import pytest

from scripts import gen_sdk_contract

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdk"))

from silo_client import SiloClient  # noqa: E402


def _recording_client(rows=None):
    sent: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append((request.url.path, json.loads(request.content or b"{}")))
        return httpx.Response(200, json=rows if rows is not None else [])

    client = SiloClient(
        url="https://example.supabase.co", key="test-key",
        transport=httpx.MockTransport(handler),
    )
    return client, sent


def test_the_bundled_contract_is_current():
    expected = gen_sdk_contract.render(
        json.loads(gen_sdk_contract.OPENAPI.read_text(encoding="utf-8"))
    )
    actual = gen_sdk_contract.OUT.read_text(encoding="utf-8")
    assert actual == expected, "run: python scripts/gen_sdk_contract.py"


def test_the_contract_lists_every_function_openapi_publishes():
    spec = json.loads(gen_sdk_contract.OPENAPI.read_text(encoding="utf-8"))
    rpcs = {p[len("/rpc/"):] for p in spec["paths"] if p.startswith("/rpc/")}
    assert rpcs and set(gen_sdk_contract.build(spec)) == rpcs


def test_rpc_posts_the_named_function_with_its_arguments():
    rows = [{"codneg": "PETRT100", "trade_date": "2026-01-02"}]
    silo, sent = _recording_client(rows)
    got = silo.rpc("termo_history", p_codneg="PETRT100",
                   p_from=date(2026, 1, 2), p_to=None)
    assert got == rows
    # A date goes as ISO; a None is left out so the server default applies.
    assert sent == [("/rest/v1/rpc/termo_history",
                     {"p_codneg": "PETRT100", "p_from": "2026-01-02"})]


def test_rpc_reaches_a_function_with_no_named_method():
    silo, sent = _recording_client()
    assert not hasattr(SiloClient, "portfolio_fees")
    silo.rpc("portfolio_fees", p_cnpjs=["05754060000113"])
    assert sent == [("/rest/v1/rpc/portfolio_fees", {"p_cnpjs": ["05754060000113"]})]


def test_an_unknown_function_is_refused_before_any_request():
    silo, sent = _recording_client()
    with pytest.raises(ValueError, match="termo_histroy"):
        silo.rpc("termo_histroy", p_codneg="PETRT100")
    assert sent == []


def test_an_unknown_parameter_is_refused_and_the_declared_ones_named():
    silo, sent = _recording_client()
    with pytest.raises(ValueError) as exc:
        silo.rpc("option_exercises", p_underlying="PETR")
    assert "p_underlying" in str(exc.value) and "p_prefix" in str(exc.value)
    assert sent == []


def test_a_required_parameter_left_out_is_refused():
    silo, sent = _recording_client()
    with pytest.raises(ValueError, match="requires p_codneg"):
        silo.rpc("termo_history", p_from="2026-01-02")
    assert sent == []


def test_the_named_methods_send_what_they_sent_before():
    """The pass-through methods are rpc() underneath; the body is unchanged."""
    silo, sent = _recording_client()
    silo.termo_history("PETRT100", start=date(2026, 1, 2))
    silo.option_exercises(" petr ", end="2026-03-01", limit=10)
    silo.curve()
    assert sent == [
        ("/rest/v1/rpc/termo_history", {"p_codneg": "PETRT100", "p_from": "2026-01-02"}),
        ("/rest/v1/rpc/option_exercises",
         {"p_prefix": "PETR", "p_to": "2026-03-01", "p_limit": 10}),
        ("/rest/v1/rpc/curve", {"p_curve": "PRE"}),
    ]


def test_credit_rpc_preserves_explicit_capture_cutoff():
    silo, sent = _recording_client([{"quantity": None}])
    assert silo.rpc("credit_market_history", p_code="TEST01",
                    p_from=date(2026, 10, 2), p_to=date(2026, 10, 8),
                    p_as_of="2026-10-09T05:00:00-03:00") == [{"quantity": None}]
    assert sent == [("/rest/v1/rpc/credit_market_history", {
        "p_code": "TEST01", "p_from": "2026-10-02", "p_to": "2026-10-08",
        "p_as_of": "2026-10-09T05:00:00-03:00"})]
    with pytest.raises(ValueError, match="requires p_code"):
        silo.rpc("credit_market_history", p_from="2026-10-02")
    assert len(sent) == 1
