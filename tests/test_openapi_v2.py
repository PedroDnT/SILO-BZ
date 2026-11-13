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


def test_server_and_credential_requirements():
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    assert spec["openapi"] == "3.1.0"
    assert spec["servers"][0]["url"] == "https://zcjbtpxuhdekpwcxmepn.supabase.co/functions/v1/silo-api/v2"
    assert spec["security"] == [{}, {"bearerAuth": []}]
    assert spec["components"]["securitySchemes"]["bearerAuth"]["scheme"] == "bearer"
    assert spec["paths"]["/"]["get"]["security"] == []
    for path, method in (("/screens", "get"), ("/portfolio", "post")):
        assert spec["paths"][path][method]["security"] == [{"bearerAuth": []}]


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


def test_mintlify_navigation_covers_all_v2_operations():
    docs = json.loads((ROOT / "docs.json").read_text(encoding="utf-8"))
    v2, v1 = docs["navigation"]["tabs"]
    assert (v2["tab"], v1["tab"]) == ("SILO v2", "API v1")
    groups = {g["group"]: g for g in v2["groups"]}
    assert groups["Get started"]["pages"][:2] == ["index", "api-docs/v2/quickstart"]
    ref = groups["REST reference"]
    assert ref["openapi"] == "api-docs/v2/openapi.json"
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    tags = [tag["name"] for tag in spec["tags"]]
    assert tags == ["Discovery", "Markets and macro", "Companies and funds", "Research"]
    assert all(op["tags"][0] in tags for methods in spec["paths"].values() for op in methods.values())


def test_operation_playgrounds_preserve_auth_and_use_explicit_routes():
    from scripts.gen_v2_operation_docs import artifacts

    files, groups = artifacts()
    base = json.loads(SPEC.read_text())
    pages = {page for group in groups for page in group["pages"]}
    for path, text in files.items():
        assert (ROOT / path).read_text() == text, f"stale operation docs: {path}"
        if not path.startswith("api-docs/v2/") or not path.endswith(".json"):
            continue
        spec = json.loads(text)
        assert spec["servers"] == base["servers"]
        assert spec["security"] == base["security"]
        route, methods = next(iter(spec["paths"].items()))
        method, operation = next(iter(methods.items()))
        original = base["paths"]["/" + route.split("/")[1]][method]
        assert operation.get("security") == original.get("security")
        assert operation["responses"] == original["responses"]
        assert operation["x-mint"]["href"].lstrip("/") in pages
        assert all(p["name"] not in {"id", "kind"} for p in operation["parameters"])
    assert len(pages) == sum(len(r["kinds"]) for r in _gen().load_registry()["resources"])


def test_operation_navigation_and_request_examples():
    from scripts.gen_v2_operation_docs import artifacts

    files, groups = artifacts()
    docs = json.loads((ROOT / "docs.json").read_text())
    nav = next(g for g in docs["navigation"]["tabs"][0]["groups"] if g["group"] == "Browse operations")
    assert nav["pages"] == groups
    # Never prefill a fund/document/index operation with a stock ticker.
    for path, content in files.items():
        if not path.startswith("api-docs/v2/") or not path.endswith(".json"):
            continue
        spec = json.loads(content)
        route, methods = next(iter(spec["paths"].items()))
        op = next(iter(methods.values()))
        if route.split("/")[1] in {"funds", "fidc", "derivatives"}:
            assert all(p.get("example") != "PETR4" for p in op["parameters"])
        if route.startswith("/portfolio/") and route != "/portfolio/resolve":
            media = op["requestBody"]["content"]["application/json"]
            assert "example" not in media
            assert len(media["schema"]["required"]) == 1
            assert "id" not in media["schema"]["properties"]
