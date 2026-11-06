"""``api-docs/v2/openapi.json`` must be what ``scripts/gen_openapi_v2.py`` emits.

The v2 OpenAPI file feeds the Mintlify API playground (#1060). It is generated
from the silo-api registry, never edited by hand, so a registry change that is
not regenerated fails here. Offline: no Deno, no database.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "gen_openapi_v2.py"
SPEC = ROOT / "api-docs" / "v2" / "openapi.json"


def _gen():
    spec = importlib.util.spec_from_file_location("gen_openapi_v2", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_committed_spec_is_not_stale():
    assert SPEC.read_text(encoding="utf-8") == _gen().render(), (
        "api-docs/v2/openapi.json is stale against silo-api/registry.ts: run python scripts/gen_openapi_v2.py"
    )


def test_one_path_per_resource_plus_the_index():
    gen = _gen()
    registry = gen.load_registry()
    paths = json.loads(SPEC.read_text(encoding="utf-8"))["paths"]
    assert set(paths) == {"/"} | {f"/{r['name']}" for r in registry["resources"]}
    for r in registry["resources"]:
        method = (r.get("method") or "GET").lower()
        assert list(paths[f"/{r['name']}"]) == [method], r["name"]


def test_main_parameters_are_enums_with_defaults_and_hidden_ones_are_marked():
    gen = _gen()
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    for r in gen.load_registry()["resources"]:
        op = next(iter(spec["paths"][f"/{r['name']}"].values()))
        params = {p["name"]: p for p in op["parameters"]}
        for p in r.get("parameters", []):
            got = params[p["name"]]
            if p["type"] == "enum":
                assert got["schema"]["enum"] == p["values"], (r["name"], p["name"])
                assert got["schema"]["default"] == p["default"], (r["name"], p["name"])
            hidden = got["description"].startswith("Hidden parameter")
            assert hidden == (p["visibility"] == "hidden"), (r["name"], p["name"])
        assert "Deployed preview" in op["description"]


def test_id_is_described_per_resource_not_with_the_generic_sentence():
    gen = _gen()
    registry = gen.load_registry()
    generic = registry["shared_parameters"]["id"]["doc"]
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    for r in registry["resources"]:
        op = next(iter(spec["paths"][f"/{r['name']}"].values()))
        ids = [p for p in op["parameters"] if p["name"] == "id"]
        assert bool(ids) == ("id" in (r.get("shared") or [])), r["name"]
        if ids:
            assert generic not in ids[0]["description"], r["name"]
            assert ids[0]["description"] == gen.id_doc(r, gen.load_id_docs()) + " Default: none."
    funds = next(p for p in spec["paths"]["/funds"]["get"]["parameters"] if p["name"] == "id")
    assert "14-digit fund CNPJ" in funds["description"] and "ticker" not in funds["description"]


def test_server_and_prefilled_public_key():
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    assert spec["openapi"] == "3.1.0"
    assert spec["servers"][0]["url"] == "https://zcjbtpxuhdekpwcxmepn.supabase.co/functions/v1/silo-api/v2"
    key = spec["components"]["securitySchemes"]["apikey"]
    assert key["in"] == "header" and key["name"] == "apikey"
    assert key["x-default"].startswith("sb_publishable_"), "only the public key is prefilled"


def test_cheatsheet_names_every_resource_and_main_default():
    """The cheatsheet is hand-written prose; this keeps its table honest to the registry."""
    text = (ROOT / "api-docs" / "v2" / "cheatsheet.mdx").read_text(encoding="utf-8")
    rows = {line.split("|")[1].strip().split(" ")[0].strip("`"): line for line in text.splitlines() if line.startswith("| `")}
    for r in _gen().load_registry()["resources"]:
        row = rows.get(r["name"])
        assert row, f"cheatsheet has no row for {r['name']}"
        for p in r.get("parameters", []):
            if p["visibility"] != "main":
                continue
            default = "none" if p["default"] in (None, "") else str(p["default"])
            assert f"`{p['name']}` (`{default}`" in row or f"`{p['name']}` ({default})" in row, (r["name"], p["name"], default)


def test_every_v2_page_says_deployed_preview():
    for page in sorted((ROOT / "api-docs" / "v2").glob("*.mdx")):
        assert "Deployed preview" in page.read_text(encoding="utf-8"), page.name


def test_docs_json_points_the_v2_group_at_the_spec():
    docs = json.loads((ROOT / "docs.json").read_text(encoding="utf-8"))
    groups = {g["group"]: g for g in docs["navigation"]["groups"]}
    assert groups["v2 endpoints (preview)"]["openapi"] == "api-docs/v2/openapi.json"
    assert groups["v2 (preview)"]["pages"] == ["api-docs/v2/quickstart", "api-docs/v2/cheatsheet", "api-docs/v2/researchers"]
