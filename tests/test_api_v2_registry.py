"""Pin the silo-api v2 gateway's resource registry to its rules, offline.

The registry (``supabase/functions/silo-api/registry.ts``) declares every v2
resource: its parameters with their defaults, its kinds, and which ``api.*``
endpoint each kind calls. The object between its BEGIN and END markers is
strict JSON, so this test parses it without Deno and checks the rules of
``docs/planning/API_V2.md`` (#1052, #1053):

* 14 resources, exactly the owner's list;
* at most 3 main parameters per resource, ``kind`` counted as one of them;
* every parameter has a default;
* every endpoint a kind calls exists in ``serve/endpoint_manifest.py`` and is
  granted to the public tiers, and every ``p_`` argument is one it declares;
* the function is read-only, holds no secret and reads only the public key.

The Deno test next to the function checks behaviour; CI does not run Deno yet
(#1052 child 2/8), so this is what CI protects today.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from serve.endpoint_manifest import manifest

ROOT = Path(__file__).resolve().parents[1]
FN_DIR = ROOT / "supabase" / "functions" / "silo-api"
REGISTRY_TS = FN_DIR / "registry.ts"
ERRORS_TS = FN_DIR / "errors.ts"
CONFIG_TOML = ROOT / "supabase" / "config.toml"
SPEC = ROOT / "docs" / "planning" / "API_V2.md"

RESOURCES = [
    "search", "prices", "statements", "funds", "fidc", "derivatives", "curves",
    "macro", "positioning", "events", "screens", "panel", "portfolio", "coverage",
]
SHARED = ["id", "from", "to", "limit", "cursor"]
ERROR_CODES = [
    "bad_request", "unknown_parameter", "unknown_id", "unauthorized", "forbidden_for_tier",
    "over_limit", "rate_limited", "timeout", "unavailable", "internal",
]
# Built in this child; the others arrive with #1052's later children.
BUILT = {"search", "coverage"}
NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def _registry() -> dict:
    src = REGISTRY_TS.read_text(encoding="utf-8")
    m = re.search(r"// BEGIN REGISTRY\nexport const REGISTRY: Registry = (\{.*?\});\n// END REGISTRY", src, re.S)
    assert m, "the REGISTRY block (between BEGIN and END markers) was not found in registry.ts"
    return json.loads(m.group(1))


def _resources() -> list[dict]:
    return _registry()["resources"]


def _built() -> list[dict]:
    return [r for r in _resources() if r["status"] == "built"]


def _plans(resource: dict):
    """(kind, plan) for every plan a resource can run, the when_empty ones included."""
    for kind, spec in resource.get("kinds", {}).items():
        yield kind, spec
        if "when_empty" in spec:
            yield f"{kind} (empty {spec['when_empty']['parameter']})", spec["when_empty"]["plan"]


def _accepted(resource: dict) -> dict:
    """name -> spec for every parameter the resource takes, shared ones included."""
    shared = _registry()["shared_parameters"]
    out = {p["name"]: p for p in resource.get("parameters", [])}
    for name in resource.get("shared", []):
        out[name] = {"name": name, "visibility": "main", **shared[name]}
    return out


def test_registry_block_is_strict_json_with_the_14_resources():
    names = [r["name"] for r in _resources()]
    assert names == RESOURCES
    assert {r["name"] for r in _built()} == BUILT
    for r in _resources():
        assert r["status"] in ("built", "planned"), r["name"]
        assert r["summary"].strip() and r["example"].strip(), r["name"]
        if r["status"] == "planned":
            assert "kinds" not in r and "parameters" not in r, f"{r['name']} is planned: it declares nothing yet"


def test_shared_parameters_are_the_five_and_each_has_a_default():
    shared = _registry()["shared_parameters"]
    assert list(shared) == SHARED
    for name, spec in shared.items():
        assert "default" in spec, name
        assert spec["default_doc"].strip(), f"{name}: say what the default means"
        assert spec["doc"].strip(), name
    for r in _built():
        assert set(r.get("shared", [])) <= set(SHARED), r["name"]


def test_at_most_three_main_parameters_kind_included():
    for r in _built():
        main = [p["name"] for p in r["parameters"] if p["visibility"] == "main"]
        assert "kind" in main, f"{r['name']}: kind is a main parameter"
        assert len(main) <= 3, f"{r['name']} has {len(main)} main parameters {main}; the cap is 3, kind included"
        for p in r["parameters"]:
            assert p["visibility"] in ("main", "hidden"), (r["name"], p["name"])


def test_every_parameter_has_a_default():
    for r in _built():
        for p in r["parameters"]:
            where = f"{r['name']}.{p['name']}"
            assert "default" in p, f"{where} has no default"
            assert p["doc"].strip(), where
            if p["default"] is None or p["default"] == "":
                assert p.get("default_doc", "").strip(), f"{where}: an empty default needs default_doc"
            if p["type"] == "enum":
                assert p["default"] in p["values"], where
            if "null_value" in p:
                assert p["null_value"] in p["values"], where


def test_parameter_names_are_plain_words_and_never_shadow_a_shared_one():
    for r in _built():
        names = [p["name"] for p in r["parameters"]]
        assert len(names) == len(set(names)), r["name"]
        for n in names:
            assert NAME.match(n) and not n.startswith("p_"), f"{r['name']}.{n}: snake_case, no p_ prefix"
            assert n not in SHARED, f"{r['name']}.{n} shadows a shared parameter"
            assert n != "help", f"{r['name']}: help is reserved for ?help"


def test_kind_values_are_the_declared_kinds():
    for r in _built():
        kind = next(p for p in r["parameters"] if p["name"] == "kind")
        assert kind["type"] == "enum"
        assert kind["values"] == list(r["kinds"]), r["name"]
        for name, spec in r["kinds"].items():
            assert spec["doc"].strip(), (r["name"], name)


def test_every_endpoint_exists_and_is_granted():
    m = manifest()
    for r in _built():
        for kind, plan in _plans(r):
            ep = plan["endpoint"]
            assert ep in m, f"{r['name']} kind {kind}: api.{ep} is not in serve/endpoint_manifest.py"
            assert m[ep].granted, f"{r['name']} kind {kind}: api.{ep} is not granted to anon/authenticated"
            assert m[ep].kind == "rpc", f"{r['name']} kind {kind}: api.{ep} is a view; the gateway calls functions only so far"


def test_every_argument_maps_a_declared_parameter_to_a_declared_p_argument():
    m = manifest()
    for r in _built():
        accepted = _accepted(r)
        for kind, plan in _plans(r):
            ep = m[plan["endpoint"]]
            for v2, p_name in plan["args"].items():
                assert v2 in accepted, f"{r['name']} kind {kind}: {v2} is not a parameter {r['name']} takes"
                assert p_name in ep.params, f"{r['name']} kind {kind}: api.{ep.name} declares no {p_name} ({ep.params})"
            for f in plan.get("filters", []):
                assert f["parameter"] in accepted, (r["name"], kind, f)
                assert f["op"] in ("in", "between"), (r["name"], kind, f)
                assert f.get("column") or (f.get("low") and f.get("high")), (r["name"], kind, f)


def test_every_accepted_parameter_is_used_by_some_kind():
    """A parameter no kind reads would be accepted and silently ignored."""
    for r in _built():
        used = {"kind"}
        for _, plan in _plans(r):
            used |= set(plan["args"]) | {f["parameter"] for f in plan.get("filters", [])}
        for spec in r["kinds"].values():
            if "when_empty" in spec:
                used.add(spec["when_empty"]["parameter"])
        unused = sorted(set(_accepted(r)) - used)
        assert not unused, f"{r['name']}: no kind uses {unused}"


def test_coverage_returns_data_through_not_as_of():
    cov = next(r for r in _resources() if r["name"] == "coverage")
    assert cov["kinds"]["freshness"]["rename"] == {"as_of": "data_through"}


def test_error_codes_are_the_ten():
    src = ERRORS_TS.read_text(encoding="utf-8")
    block = re.search(r"export const ERROR_CODES = \[(.*?)\] as const;", src, re.S)
    assert block, "ERROR_CODES not found in errors.ts"
    assert re.findall(r'"([a-z_]+)"', block.group(1)) == ERROR_CODES


def test_function_is_read_only_and_holds_no_secret():
    src = "\n".join(
        p.read_text(encoding="utf-8") for p in FN_DIR.rglob("*.ts") if not p.name.endswith("_test.ts")
    )
    methods = set(re.findall(r'method: "([A-Z]+)"', src))
    assert methods == {"POST"}, f"the gateway only calls POST /rpc/<fn>: {methods}"
    for forbidden in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEYS", "SUPABASE_DB_URL"):
        assert forbidden not in src, forbidden
    env_reads = set(re.findall(r'get\("([A-Z_]+)"\)', src))
    assert env_reads == {"SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_PUBLISHABLE_KEYS"}, env_reads
    assert not re.search(r"sb_publishable_[A-Za-z0-9_]{8,}", src), "no key literal in the function"
    assert '"Accept-Profile": "api"' in src and '"Content-Profile": "api"' in src


def test_config_disables_jwt_verification_for_the_function():
    toml = CONFIG_TOML.read_text(encoding="utf-8")
    section = re.search(r"\[functions\.silo-api\](.*?)(?:\n\[|\Z)", toml, re.S)
    assert section, "[functions.silo-api] missing from supabase/config.toml"
    assert re.search(r"^verify_jwt\s*=\s*false\s*$", section.group(1), re.M)


@pytest.mark.parametrize("name", RESOURCES)
def test_the_spec_names_every_resource(name):
    assert f"`{name}`" in SPEC.read_text(encoding="utf-8"), f"docs/planning/API_V2.md does not name {name}"
