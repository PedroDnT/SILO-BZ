"""Pin the silo-mcp edge function to the read contract, offline.

Which tools exist has one source: the ``api.*`` functions and views granted
to anon / authenticated in the analytical SQL (``serve/endpoint_manifest.py``).
``scripts/gen_mcp_contract.py`` writes that list (``ENDPOINT_NAMES``) into
``supabase/functions/silo-mcp/contract.generated.ts`` beside each endpoint's
schema and prose from ``openapi.json``, and refuses when openapi.json publishes
a different set. ``serve/catalog.py``'s ``postgrest`` map is pinned to the same
set by ``tests/test_endpoint_manifest.py``.

The only hand-kept part is ``TOOL_TITLES`` in ``tools.ts``: a title and an
optional lead per endpoint. An endpoint with no title, or a title naming no
endpoint, fails here (and fails the module at load). Editing openapi.json or a
grant without regenerating the module fails the staleness test. The Deno test
next to the function checks behaviour; this one checks that nothing drifts.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from scripts import gen_mcp_contract
from serve.endpoint_manifest import manifest

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


def _titled() -> list[str]:
    """The names TOOL_TITLES titles, in tools/list order."""
    src = TOOLS_TS.read_text(encoding="utf-8")
    block = re.search(r"export const TOOL_TITLES: ToolSpec\[\] = \[(.*?)\n\];", src, re.S)
    assert block, "TOOL_TITLES block not found in tools.ts"
    return re.findall(r'^\s*t\("([a-z0-9_]+)"', block.group(1), re.M)


def _granted() -> dict:
    """name -> Endpoint for every api.* object granted to anon/authenticated."""
    return {name: e for name, e in manifest().items() if e.granted}


def _generated_names() -> list[str]:
    src = gen_mcp_contract.OUT.read_text(encoding="utf-8")
    block = re.search(r"export const ENDPOINT_NAMES: string\[\] = (\[.*?\]);", src, re.S)
    assert block, "ENDPOINT_NAMES not found in contract.generated.ts"
    return json.loads(block.group(1))


def _openapi() -> dict:
    return json.loads(gen_mcp_contract.OPENAPI.read_text(encoding="utf-8"))


def test_generated_contract_is_current():
    expected = gen_mcp_contract.render(_openapi())
    actual = gen_mcp_contract.OUT.read_text(encoding="utf-8")
    assert actual == expected, "run: python scripts/gen_mcp_contract.py"


def test_tool_names_are_the_granted_surface():
    """ENDPOINT_NAMES is every granted api.* endpoint, read from the SQL."""
    assert _generated_names() == sorted(_granted())
    missing = MINIMUM - set(_generated_names())
    assert not missing, f"minimum MCP tools missing: {sorted(missing)}"


def test_every_endpoint_has_exactly_one_title():
    titled = _titled()
    dups = sorted({n for n in titled if titled.count(n) > 1})
    assert not dups, f"titled twice in TOOL_TITLES: {dups}"
    granted = set(_granted())
    untitled = sorted(granted - set(titled))
    assert not untitled, f"granted endpoints with no title in tools.ts TOOL_TITLES (add a t() line): {untitled}"
    orphans = sorted(set(titled) - granted)
    assert not orphans, f"TOOL_TITLES names no granted endpoint (remove the t() line): {orphans}"


def test_generation_refuses_an_openapi_that_disagrees_with_the_sql():
    openapi = _openapi()
    dropped = copy.deepcopy(openapi)
    del dropped["paths"]["/rpc/panel"]
    with pytest.raises(ValueError, match=r"granted but unpublished \['panel'\]"):
        gen_mcp_contract.render(dropped)
    extra = copy.deepcopy(openapi)
    extra["paths"]["/not_granted"] = copy.deepcopy(openapi["paths"]["/equities"])
    with pytest.raises(ValueError, match=r"published but not granted \['not_granted'\]"):
        gen_mcp_contract.render(extra)


def test_every_tool_has_a_contract_entry_of_the_right_kind():
    entries = gen_mcp_contract.build(_openapi())
    granted = _granted()
    for name in _titled():
        assert name in entries, f"{name} is not in openapi.json"
        assert entries[name]["kind"] == granted[name].kind, (name, entries[name]["kind"], granted[name].kind)


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
