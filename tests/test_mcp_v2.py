"""Pin MCP v2 (``supabase/functions/silo-mcp-v2/``) to the v2 registry, offline.

MCP v2 is 14 tools, one per v2 resource, named ``silo_<resource>`` (#1060). The
tools are built at load from the silo-api registry, which is imported, never
copied, so this test checks the two things that keep that true without Deno:

* the registry holds exactly the 14 resources, so the tool list is exactly
  ``silo_<resource>`` for each of them, and each tool maps to a resource;
* ``tools.ts`` derives its tools from the imported registry and holds no
  mapping of its own (no ``api.*`` endpoint, no ``p_`` argument, no tool list).

The Deno test next to the function (``silo_mcp_v2_test.ts``) checks behaviour;
the CI ``deno`` job runs it because the directory holds a ``*_test.ts``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FN = ROOT / "supabase" / "functions"
V2 = FN / "silo-mcp-v2"
REGISTRY_TS = FN / "silo-api" / "registry.ts"
CONFIG_TOML = ROOT / "supabase" / "config.toml"

RESOURCES = [
    "search", "prices", "statements", "funds", "fidc", "derivatives", "curves",
    "macro", "positioning", "events", "screens", "panel", "portfolio", "coverage",
]


def _registry() -> dict:
    src = REGISTRY_TS.read_text(encoding="utf-8")
    m = re.search(r"// BEGIN REGISTRY\nexport const REGISTRY: Registry = (\{.*?\});\n// END REGISTRY", src, re.S)
    assert m, "the REGISTRY block was not found in silo-api/registry.ts"
    return json.loads(m.group(1))


def _tool_names() -> list[str]:
    """The tool names tools.ts builds: TOOL_PREFIX + each registry resource name."""
    src = (V2 / "tools.ts").read_text(encoding="utf-8")
    prefix = re.search(r'export const TOOL_PREFIX = "([a-z_]+)";', src)
    assert prefix, "TOOL_PREFIX not found in tools.ts"
    assert re.search(r"export const TOOLS: V2Tool\[\] = REGISTRY\.resources\.map\(buildTool\);", src), (
        "TOOLS must be built from REGISTRY.resources, one tool per resource"
    )
    assert "name: `${TOOL_PREFIX}${r.name}`" in src
    return [f"{prefix.group(1)}{r['name']}" for r in _registry()["resources"]]


def test_exactly_14_tools_each_mapped_to_a_registry_resource():
    names = _tool_names()
    assert len(names) == 14
    assert len(set(names)) == 14, "duplicate tool names"
    assert names == [f"silo_{r}" for r in RESOURCES]
    resources = {r["name"] for r in _registry()["resources"]}
    for name in names:
        assert name.removeprefix("silo_") in resources, f"{name} maps to no registry resource"


def test_tools_import_the_registry_and_duplicate_no_mapping():
    src = (V2 / "tools.ts").read_text(encoding="utf-8")
    assert re.search(r'from "\.\./silo-api/registry\.ts"', src), "tools.ts must import the silo-api registry"
    assert re.search(r'from "\.\./silo-api/server\.ts"', src), "a call must run the silo-api gateway itself"
    code = "\n".join(line for line in src.splitlines() if not line.strip().startswith("//"))
    assert not re.search(r"\bp_[a-z]", code), "tools.ts names a p_ argument: the mapping belongs to the registry"
    assert "/rpc/" not in code and "rest/v1" not in code, "tools.ts must not call PostgREST directly"
    for r in RESOURCES:
        assert f'"{r}"' not in code, f"tools.ts hard-codes the resource {r!r}; read it from the registry"


def test_main_parameters_fit_the_tool_schema_rule():
    """At most 3 main parameters (kind counted), so each tool's top level stays short."""
    shared = set(_registry()["shared_parameters"])
    for r in _registry()["resources"]:
        main = [p["name"] for p in r.get("parameters", []) if p["visibility"] == "main" and p["name"] not in shared]
        assert len(main) <= 3, f"{r['name']}: {main}"
        for p in r.get("parameters", []):
            if p["type"] == "enum":
                assert p["default"] in p["values"], f"{r['name']}.{p['name']}: the default is not one of its values"


def _id_docs() -> dict[str, str]:
    src = (V2 / "id_docs.ts").read_text(encoding="utf-8")
    m = re.search(r"// BEGIN ID_DOCS\nexport const ID_DOCS: Record<string, string> = (\{.*?\});\n// END ID_DOCS", src, re.S)
    assert m, "the ID_DOCS block was not found in silo-mcp-v2/id_docs.ts"
    return json.loads(m.group(1))


def _id_mappings() -> dict[tuple[str, str], str]:
    """(resource, kind) -> the ID_DOCS key of the argument that kind maps id to."""
    out = {}
    for r in _registry()["resources"]:
        if "id" not in (r.get("shared") or []):
            continue  # portfolio's id is a body list (its body doc says what it holds), not the shared id
        for kind, spec in (r.get("kinds") or {}).items():
            arg = (spec.get("args") or {}).get("id")
            if arg:
                out[(r["name"], kind)] = f"{spec['endpoint']}.{arg}"
    return out


def _cnpj_normalised() -> set[tuple[str, str]]:
    """(resource, kind) pairs whose id the gateway runs through normalizeCnpjId (resources/*.ts)."""
    out: set[tuple[str, str]] = set()
    kinds = {r["name"]: list(r.get("kinds") or {}) for r in _registry()["resources"]}
    for path in (FN / "silo-api" / "resources").glob("*.ts"):
        src = path.read_text(encoding="utf-8")
        if "normalizeCnpjId(" not in src.replace("import { normalizeCnpjId", ""):
            continue
        only = re.search(r"const FUND_KINDS = new Set\(\[(.*?)\]\);", src)
        if only:
            assert "FUND_KINDS.has(kind) ? normalizeCnpjId(" in src, path.name
            names = re.findall(r'"([a-z_]+)"', only.group(1))
        else:
            assert re.search(r"\(kind, _plan, values\) => normalizeCnpjId\(", src), (
                f"{path.name}: normalizeCnpjId applies in a way this test does not recognise; update the test"
            )
            names = kinds[path.stem]
        out |= {(path.stem, k) for k in names}
    return out


def test_every_id_mapping_has_a_phrase_and_no_phrase_is_stale():
    phrases, mappings = _id_docs(), _id_mappings()
    missing = sorted({key for key in mappings.values() if key not in phrases})
    stale = sorted(set(phrases) - set(mappings.values()))
    assert not missing, f"id_docs.ts has no phrase for {missing}"
    assert not stale, f"id_docs.ts phrases no kind maps id to: {stale}"


def test_a_cnpj_normalised_id_is_described_as_a_fund_cnpj_and_only_then():
    phrases, mappings, cnpj = _id_docs(), _id_mappings(), _cnpj_normalised()
    assert {r for r, _ in cnpj} == {"funds", "fidc", "events"}, "the set of CNPJ-normalising resources changed"
    for (resource, kind), key in mappings.items():
        says = "14-digit fund CNPJ (punctuation allowed" in phrases[key]
        assert says == ((resource, kind) in cnpj), (resource, kind, phrases[key])
    generic = _registry()["shared_parameters"]["id"]["doc"]
    assert all(generic not in p for p in phrases.values())


def test_deno_test_sits_next_to_the_function_so_ci_runs_it():
    tests = sorted(V2.glob("*_test.ts"))
    assert tests, "the CI deno job runs only function directories holding a *_test.ts"
    assert (V2 / "deno.json").is_file(), "deno test runs inside the directory, with its own import map"
    imports = json.loads((V2 / "deno.json").read_text(encoding="utf-8"))["imports"]
    v1 = json.loads((FN / "silo-mcp" / "deno.json").read_text(encoding="utf-8"))["imports"]
    assert imports["@modelcontextprotocol/server"] == v1["@modelcontextprotocol/server"], "one MCP SDK version"


def test_config_disables_jwt_verification_for_the_function():
    toml = CONFIG_TOML.read_text(encoding="utf-8")
    section = re.search(r"\[functions\.silo-mcp-v2\](.*?)(?:\n\[|\Z)", toml, re.S)
    assert section, "[functions.silo-mcp-v2] missing from supabase/config.toml"
    assert re.search(r"^verify_jwt\s*=\s*false\s*$", section.group(1), re.M)


def test_read_only_and_public_key_only():
    for path in V2.glob("*.ts"):
        src = path.read_text(encoding="utf-8")
        assert "service_role" not in src and "SUPABASE_SERVICE_ROLE_KEY" not in src, path.name
        assert "sb_secret_" not in src, path.name
