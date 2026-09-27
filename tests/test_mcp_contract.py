"""Pin the silo-mcp edge function to the read contract, offline.

Three sources must agree, and this is the test that fails when they do not:

* ``serve/catalog.py`` ``catalog_payload()["postgrest"]`` — what the catalog
  tells an agent exists on the deployed surface;
* ``openapi.json`` — generated from the SQL and carried into
  ``supabase/functions/silo-mcp/contract.generated.ts`` by
  ``scripts/gen_mcp_contract.py``;
* ``supabase/functions/silo-mcp/tools.ts`` ``TOOL_SPECS`` — the hand-listed
  MCP tools.

Adding an endpoint to the catalog without a tool (or a tool without a catalog
entry) fails here, as does editing openapi.json without regenerating the
module. The Deno test next to the function checks behaviour; this one checks
that the list cannot drift.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts import gen_mcp_contract
from serve.catalog import catalog_payload

ROOT = Path(__file__).resolve().parents[1]
FN_DIR = ROOT / "supabase" / "functions" / "silo-mcp"
TOOLS_TS = FN_DIR / "tools.ts"
CONFIG_TOML = ROOT / "supabase" / "config.toml"

# The owner's minimum set (2026-09-24 decision, backlog B2).
MINIMUM = {
    "catalog", "coverage", "metric_coverage", "lookup", "panel", "quote_history",
    "quote_latest", "option_chain", "fund_profile", "fund_nav", "search_funds",
    "fund_holdings", "fund_debentures", "fidc_cedentes", "fidc_sacados",
    "fidc_portfolio", "fidc_tranches", "fidc_aging", "screen_zombie_growth",
    "screen_captive_vehicles", "screen_evergreen_aging", "screen_overdue_securit",
    "screen_dormant_funds", "screen_dormant_trend", "screen_delinquency_drivers",
    "financials", "company_financials", "income_statements", "balance_sheets",
    "cash_flow_statements", "anbima_classes",
    "inflation", "inflation_items", "short_interest", "investor_flow",
}


def _tool_specs() -> list[str]:
    src = TOOLS_TS.read_text(encoding="utf-8")
    block = re.search(r"export const TOOL_SPECS: ToolSpec\[\] = \[(.*?)\n\];", src, re.S)
    assert block, "TOOL_SPECS block not found in tools.ts"
    return re.findall(r'^\s*t\("([a-z0-9_]+)"', block.group(1), re.M)


def _catalog_resources() -> dict[str, tuple[str, str]]:
    """resource name -> (verb, catalog key), from the catalog's postgrest map."""
    out: dict[str, tuple[str, str]] = {}
    for key, route in catalog_payload()["postgrest"].items():
        verb, path = route.split(" ", 1)
        assert path.startswith("/rest/v1/"), route
        resource = path[len("/rest/v1/"):]
        if resource.startswith("rpc/"):
            resource = resource[len("rpc/"):]
        out[resource] = (verb, key)
    return out


def _openapi() -> dict:
    return json.loads(gen_mcp_contract.OPENAPI.read_text(encoding="utf-8"))


def test_generated_contract_is_current():
    expected = gen_mcp_contract.render(_openapi())
    actual = gen_mcp_contract.OUT.read_text(encoding="utf-8")
    assert actual == expected, "run: python scripts/gen_mcp_contract.py"


def test_tool_list_has_no_duplicates_and_covers_minimum():
    names = _tool_specs()
    assert len(names) == len(set(names)), "duplicate tool in TOOL_SPECS"
    missing = MINIMUM - set(names)
    assert not missing, f"minimum MCP tools missing: {sorted(missing)}"


def test_tool_list_matches_catalog_postgrest_exactly():
    """One tool per catalog endpoint, plus `catalog` itself (which the
    postgrest map does not list because it is the map)."""
    tools = set(_tool_specs())
    catalog = set(_catalog_resources()) | {"catalog"}
    assert tools - catalog == set(), f"MCP tools absent from the catalog: {sorted(tools - catalog)}"
    assert catalog - tools == set(), f"catalog endpoints with no MCP tool: {sorted(catalog - tools)}"


def test_every_tool_has_a_contract_entry_of_the_right_kind():
    entries = gen_mcp_contract.build(_openapi())
    resources = _catalog_resources()
    for name in _tool_specs():
        assert name in entries, f"{name} is not in openapi.json"
        kind = entries[name]["kind"]
        if name == "catalog":
            assert kind == "rpc"
            continue
        verb, key = resources[name]
        assert (verb, kind) in {("POST", "rpc"), ("GET", "view")}, (name, verb, kind, key)


def test_rpc_schemas_are_the_openapi_bodies():
    openapi = _openapi()
    entries = gen_mcp_contract.build(openapi)
    for name, entry in entries.items():
        if entry["kind"] != "rpc":
            continue
        body = openapi["paths"][entry["path"]]["post"]["requestBody"]["content"]["application/json"]["schema"]
        schema = entry["inputSchema"]
        assert set(schema.get("properties", {})) == set(body.get("properties", {})), name
        assert schema.get("required", []) == body.get("required", []), name
        assert schema["additionalProperties"] is False, name


def test_view_schemas_expose_filters_not_query_language():
    for name, entry in gen_mcp_contract.build(_openapi()).items():
        if entry["kind"] != "view":
            continue
        props = entry["inputSchema"]["properties"]
        assert set(props) == {"filters", "select", "order", "limit", "offset"}, name
        assert entry["columns"], name
        assert set(props["filters"]["properties"]) == set(entry["columns"]), name
        assert props["limit"]["maximum"] == 1000


def test_function_is_read_only_and_holds_no_secret():
    src = "\n".join(p.read_text(encoding="utf-8") for p in FN_DIR.glob("*.ts") if not p.name.endswith("_test.ts"))
    # Only POST /rpc and GET views are ever issued.
    methods = set(re.findall(r'method: "([A-Z]+)"', src))
    assert methods <= {"GET", "POST"}, methods
    for forbidden in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEYS", "SUPABASE_DB_URL"):
        assert forbidden not in src, forbidden
    # The only environment the bridge reads: the REST base and the public key.
    env_reads = set(re.findall(r'get\("([A-Z_]+)"\)', src))
    assert env_reads == {"SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_PUBLISHABLE_KEYS"}, env_reads
    assert not re.search(r"sb_publishable_[A-Za-z0-9_]{8,}", src), "no key literal in the function"
    assert re.search(r"readOnlyHint: true", src)
    assert re.search(r"openWorldHint: false", src)


def test_config_disables_jwt_verification_for_the_function_only():
    toml = CONFIG_TOML.read_text(encoding="utf-8")
    section = re.search(r"\[functions\.silo-mcp\](.*?)(?:\n\[|\Z)", toml, re.S)
    assert section, "[functions.silo-mcp] missing from supabase/config.toml"
    assert re.search(r"^verify_jwt\s*=\s*false\s*$", section.group(1), re.M)


@pytest.mark.parametrize("path", ["api-docs/mcp.mdx"])
def test_docs_page_exists_and_is_registered(path):
    assert (ROOT / path).exists()
    docs = json.loads((ROOT / "docs.json").read_text(encoding="utf-8"))
    assert path[:-len(".mdx")] in json.dumps(docs)
    assert "mcp" in (ROOT / "llms.txt").read_text(encoding="utf-8")
