"""Published shape and generated-contract parity; SQL scenarios execute in CI."""
from pathlib import Path

from serve.catalog import catalog_payload
from serve.endpoint_manifest import manifest

ROOT = Path(__file__).resolve().parents[1]


def test_credit_is_capped_without_a_date_cursor():
    endpoint = manifest()["credit_market_history"]
    assert endpoint.granted and endpoint.raise_only
    assert endpoint.params == ("p_code", "p_from", "p_to", "p_as_of")
    payload = catalog_payload()
    assert "credit_market_history" in payload["limits"]["page"]["functions"]["raise_only"]
    assert payload["postgrest"]["credit_market_history"] == "POST /rest/v1/rpc/credit_market_history"


def test_executed_sql_acceptance_is_wired_into_ci():
    workflow = (ROOT / ".github/workflows/test.yml").read_text()
    assert "-f tests/sql/credit_market_history_behaviour.sql" in workflow


def test_public_contract_does_not_promise_derived_economics():
    constraints = " ".join(catalog_payload()["constraints"])
    credit = next(c for c in catalog_payload()["constraints"] if c.startswith("DEBENTURE MARKET"))
    assert "No summed repeated prices" in credit
    assert "coupon-adjusted return" in credit
    assert "original publication-time PIT" in credit
    assert "credit_market_history" in constraints
