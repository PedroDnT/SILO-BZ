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
BUILT |= {"funds", "fidc", "events"}  # #1056
BUILT |= {"prices", "statements"}  # #1055
BUILT |= {"screens", "panel", "portfolio"}  # #1058
# A resource with a single kind takes no kind parameter (#1058).
ONE_KIND = {"panel"}
BUILT |= {"derivatives", "curves", "macro", "positioning"}  # #1057
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
    for b in resource.get("body", []):  # #1058: portfolio's POST body lists
        out[b["name"]] = {"visibility": "body", **b}
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
        if r["name"] in ONE_KIND:
            assert len(r["kinds"]) == 1 and "kind" not in {p["name"] for p in r["parameters"]}, r["name"]
        else:
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
                if p["type"] == "enum":
                    assert p["null_value"] in p["values"], where
                else:
                    assert p["null_value"] == p["default"], f"{where}: a free-text null_value is the default"


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
        if r["name"] in ONE_KIND:
            continue
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
            want = "view" if plan.get("view") else "rpc"
            assert m[ep].kind == want, f"{r['name']} kind {kind}: api.{ep} is a {m[ep].kind}; the plan says {want}"
            for view in plan.get("view_by", {}).get("views", {}).values():  # #1055
                assert view in m and m[view].kind == "view" and m[view].granted, f"{r['name']} kind {kind}: api.{view}"


def _view_columns(view: str) -> set[str]:
    """The filterable columns of a GET view, from the published openapi.json."""
    spec = json.loads((ROOT / "openapi.json").read_text(encoding="utf-8"))
    params = spec["paths"][f"/{view}"]["get"]["parameters"]
    return {p["name"] for p in params if p.get("in") == "query"} - {"select", "order", "limit", "offset"}


def test_every_argument_maps_a_declared_parameter_to_a_declared_p_argument():
    m = manifest()
    for r in _built():
        accepted = _accepted(r)
        for kind, plan in _plans(r):
            ep = m[plan["endpoint"]]
            if plan.get("view"):
                cols = _view_columns(ep.name)
                assert plan.get("order"), f"{r['name']} kind {kind}: a view read needs an order, or a page is undefined"
                for col in [c.split(".")[0] for c in plan["order"].split(",")] + list(plan.get("where", {})):
                    assert col in cols, f"{r['name']} kind {kind}: api.{ep.name} has no column {col}"
            for v2, p_name in plan["args"].items():
                assert v2 in accepted, f"{r['name']} kind {kind}: {v2} is not a parameter {r['name']} takes"
                if plan.get("view"):
                    ok = p_name in cols or (v2 == "limit" and p_name == "limit")
                    assert ok, f"{r['name']} kind {kind}: api.{ep.name} has no column {p_name}"
                    continue
                assert p_name in ep.params, f"{r['name']} kind {kind}: api.{ep.name} declares no {p_name} ({ep.params})"
            for name in plan.get("require_one_of", []):
                assert name in plan["args"], f"{r['name']} kind {kind}: requires {name} but never sends it"
            for f in plan.get("filters", []):
                assert f["parameter"] in accepted, (r["name"], kind, f)
                assert f["op"] in ("in", "between", "month_last"), (r["name"], kind, f)
                assert f.get("column") or (f.get("low") and f.get("high")), (r["name"], kind, f)


def test_every_accepted_parameter_is_used_by_some_kind():
    """A parameter no kind reads would be accepted and silently ignored."""
    for r in _built():
        used = {"kind", "limit"}  # limit is the page size of every kind (#1059)
        for _, plan in _plans(r):
            used |= set(plan["args"]) | {f["parameter"] for f in plan.get("filters", [])} | set(plan.get("uses", []))
            if "view_by" in plan:
                used.add(plan["view_by"]["parameter"])
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
    assert methods == {"POST", "GET"}, f"the gateway only calls POST /rpc/<fn> and GET /<view>: {methods}"
    # GET is the view read (#1056) and nothing else: one call site, in callView.
    postgrest = (FN_DIR / "postgrest.ts").read_text(encoding="utf-8")
    assert src.count('method: "GET"') == 1 and 'method: "GET"' in postgrest.split("export async function callView", 1)[1]
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


# -- funds, fidc, events (#1056) ------------------------------------------------

ISSUE_1056 = {
    "funds": {
        "profile": "fund_profile", "nav": "fund_nav", "holdings": "fund_holdings",
        "debentures": "fund_debentures", "properties": "fii_property_history",
    },
    "fidc": {
        "portfolio": "fidc_portfolio", "tranches": "fidc_tranches", "aging": "fidc_aging",
        "cedentes": "fidc_cedentes", "sacados": "fidc_sacados",
    },
    "events": {
        "company": "company_events", "fund": "fund_documents", "restatements": "fund_restatements",
        "restatement_diff": "fund_restatement_diff", "judicial_recovery": "rj_listed_documents",
    },
}
WINDOWS_1056 = {"funds": 36, "fidc": 24, "events": 12}
HIDDEN_1056 = {"funds": {"holding", "status"}, "fidc": {"series", "cedente", "item"}, "events": {"family"}}


@pytest.mark.parametrize("name", sorted(ISSUE_1056))
def test_1056_kinds_map_to_the_issue_endpoints(name):
    r = next(x for x in _resources() if x["name"] == name)
    assert {k: v["endpoint"] for k, v in r["kinds"].items()} == ISSUE_1056[name]
    kind = next(p for p in r["parameters"] if p["name"] == "kind")
    assert kind["default"] == next(iter(ISSUE_1056[name])), "the first kind is the default"
    assert r["window_months"] == WINDOWS_1056[name]
    hidden = {p["name"] for p in r["parameters"] if p["visibility"] == "hidden"}
    assert hidden == HIDDEN_1056[name]


def test_a_resource_whose_kinds_take_from_declares_a_default_window():
    for r in _built():
        if any("from" in plan["args"] for _, plan in _plans(r)):
            assert r.get("window_months", 0) > 0, f"{r['name']}: from has no default window"


def test_with_no_id_funds_and_fidc_list_the_funds_view():
    for name, where in (("funds", {}), ("fidc", {"entity_type": "fidc"})):
        r = next(x for x in _resources() if x["name"] == name)
        first = r["kinds"][next(iter(r["kinds"]))]
        assert first["when_empty"]["parameter"] == "id"
        plan = first["when_empty"]["plan"]
        assert plan["endpoint"] == "funds" and plan["view"] is True
        assert plan.get("where", {}) == where
        assert plan["paging"]["method"] == "view_offset" and "limit" not in plan["args"]


def test_fidc_help_keeps_the_2020_11_delinquency_regime_break():
    for name in ("fidc", "funds"):
        r = next(x for x in _resources() if x["name"] == name)
        assert any("2020-11" in n and "delinquency" in n for n in r["notes"]), name


@pytest.mark.parametrize("name", RESOURCES)
def test_the_spec_names_every_resource(name):
    assert f"`{name}`" in SPEC.read_text(encoding="utf-8"), f"docs/planning/API_V2.md does not name {name}"


# --------------------------------------------------- prices and statements (#1055) --

ANALYTICAL = ROOT / "src" / "store" / "analytical"
PRICES_TS = FN_DIR / "resources" / "prices.ts"


def _sql() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(ANALYTICAL.glob("[0-9][0-9]_*.sql")))


def _resource(name: str) -> dict:
    return next(r for r in _resources() if r["name"] == name)


def test_history_fields_are_the_sql_quote_history_fields():
    """fields=all must name every field api.quote_history publishes, no more."""
    body = re.search(r"FUNCTION api\.quote_history_fields\(\).*?VALUES(.*?)\$\$;", _sql(), re.S)
    assert body, "api.quote_history_fields() not found"
    sql_fields = re.findall(r"^\s*\('([a-z_]+)',", body.group(1), re.M)
    ts = re.search(r"export const HISTORY_FIELDS: string\[\] = \[(.*?)\];", PRICES_TS.read_text(encoding="utf-8"), re.S)
    assert ts, "HISTORY_FIELDS not found in prices.ts"
    assert re.findall(r'"([a-z_]+)"', ts.group(1)) == [f for f in sql_fields if f not in ("ticker", "trade_date")]


def test_session_reads_the_seven_price_views_on_columns_they_publish():
    session = _resource("prices")["kinds"]["session"]
    views = session["view_by"]["views"]
    assert sorted(views.values()) == sorted(["quotes", "equities", "bdrs", "units", "fund_quotas", "cash_securities", "auctions"])
    sql = _sql()
    for view in views.values():
        body = re.search(rf"CREATE OR REPLACE VIEW api\.{view} AS(.*?)\bFROM\b", sql, re.S)
        assert body, view
        for column in session["args"].values():
            assert re.search(rf"(\bAS\s+{column}\b|\bv\.{column}\s*,)", body.group(1)), f"api.{view} publishes no {column}"


def test_value_maps_name_declared_values():
    for r in _built():
        for p in r["parameters"]:
            assert set(p.get("sql_values", {})) <= set(p.get("values", [])), (r["name"], p["name"])
        for _, plan in _plans(r):
            for f in plan.get("filters", []):
                if "map" in f:
                    assert f["map"] == _accepted(r)[f["parameter"]].get("sql_values"), (r["name"], f)


def test_prices_and_statements_windows_are_the_sql_default_windows():
    """window_months (1 year, 5 years) is the window each SQL function defaults to (365, 1825 days)."""
    sql = _sql()
    for name, months in (("prices", 12), ("statements", 60)):
        r = _resource(name)
        assert r["window_months"] == months
        for kind, plan in _plans(r):
            if "from" not in plan["args"]:
                continue
            fn = re.search(rf"FUNCTION api\.{plan['endpoint']}\((.*?)\)\s*\n\s*RETURNS", sql, re.S)
            assert fn, plan["endpoint"]
            m = re.search(r"p_from\s+DATE\s+DEFAULT\s+\(CURRENT_DATE\s*-\s*(\d+)\)", fn.group(1))
            assert m and int(m.group(1)) == months * 365 // 12, (name, kind)
            assert "to" in plan["args"], (name, kind)


def test_statements_period_and_scope_map_to_the_sql_codes():
    st = {p["name"]: p for p in _resource("statements")["parameters"]}
    assert st["period"]["sql_values"] == {"quarterly": "itr", "annual": "dfp"} and st["period"]["null_value"] == "both"
    assert st["scope"]["sql_values"] == {"consolidated": "con", "individual": "ind"}
    kinds = _resource("statements")["kinds"]
    assert "as_of" not in kinds["versions"]["args"], "financial_statement_history has no p_as_of"
    assert kinds["versions"]["args"]["statement"] == "p_statement"


# ------------------------------------------- screens, panel, portfolio (#1058) --

PANEL_TS = FN_DIR / "resources" / "panel.ts"


def _catalog() -> dict:
    """api.catalog() is a constant JSON literal in the SQL; parse it offline."""
    src = (ANALYTICAL / "19_api_contract.sql").read_text(encoding="utf-8")
    body = src[src.index("CREATE OR REPLACE FUNCTION api.catalog()"):]
    m = re.search(r"SELECT \$json\$(.*?)\$json\$", body, re.S)
    assert m, "api.catalog()'s JSON literal not found"
    return json.loads(m.group(1))


def _sql_signature(fn: str) -> dict:
    """p_name -> its DEFAULT text (None when it has none), from CREATE FUNCTION api.<fn>(...)."""
    m = re.search(rf"CREATE OR REPLACE FUNCTION api\.{fn}\((.*?)\)\s*\n\s*RETURNS", _sql(), re.S)
    assert m, fn
    out = {}
    for line in m.group(1).splitlines():
        line = line.split("--", 1)[0].strip().rstrip(",")
        a = re.match(r"(p_\w+)\s+[A-Z\[\]]+(?:\s+DEFAULT\s+(.+))?$", line)
        if a:
            out[a.group(1)] = a.group(2).strip() if a.group(2) else None
    return out


def test_panel_metrics_are_the_catalog_metrics():
    """The gateway refuses a metric name api.panel would ignore; its list must be catalog().metrics."""
    ts = re.search(r"export const PANEL_METRICS: string\[\] = \[(.*?)\];", PANEL_TS.read_text(encoding="utf-8"), re.S)
    assert ts, "PANEL_METRICS not found in panel.ts"
    assert re.findall(r'"([a-z0-9_]+)"', ts.group(1)) == list(_catalog()["metrics"])


def test_panel_has_one_kind_a_list_id_and_the_issue_parameters():
    p = _resource("panel")
    assert list(p["kinds"]) == ["panel"] and p["kinds"]["panel"]["endpoint"] == "panel"
    main = [x["name"] for x in p["parameters"] if x["visibility"] == "main"]
    hidden = [x["name"] for x in p["parameters"] if x["visibility"] == "hidden"]
    assert main == ["metric", "freq", "family"] and hidden == ["min_nav", "min_months"]
    assert p["window_months"] == 36 and p["kinds"]["panel"]["args"]["id"] == "p_ids"
    fam = next(x for x in p["parameters"] if x["name"] == "family")
    assert fam["values"][1:] == ["fi", "fidc", "fii", "fip", "fiagro"], "assert_panel_universe's families"


def test_screens_are_one_kind_per_screen_function_and_the_catalog_screens():
    s = _resource("screens")
    kinds = {k: v["endpoint"] for k, v in s["kinds"].items() if k != "list"}
    assert kinds == {k: f"screen_{k}" for k in kinds}
    assert set(kinds) == set(_catalog()["screens"]), "catalog().screens lists the same screens"
    assert {n for n in manifest() if n.startswith("screen_")} == set(kinds.values())
    assert s["kinds"]["list"]["endpoint"] == "catalog"
    assert [p["name"] for p in s["parameters"] if p["visibility"] == "main"] == ["kind"]
    assert any("signal, not a verdict" in n.lower() for n in s["notes"])


def test_screens_sql_defaults_are_the_sql_function_defaults():
    """A threshold left null is sent as the kind's sql_defaults; each must be the SQL's own default."""
    for kind, plan in _resource("screens")["kinds"].items():
        if kind == "list":
            continue
        sig = _sql_signature(plan["endpoint"])
        assert set(plan["args"].values()) == set(sig), f"screens {kind}: every p_ argument is mapped"
        for v2, p_name in plan["args"].items():
            default = sig[p_name]
            if v2 in plan.get("sql_defaults", {}):
                assert default is not None and float(default) == float(plan["sql_defaults"][v2]), (kind, v2, default)
            else:
                assert default == "NULL", f"screens {kind}: {p_name} defaults to {default}; add it to sql_defaults"


def test_portfolio_maps_one_kind_per_function_without_credit_returns():
    pf = _resource("portfolio")
    funcs = {n for n in manifest() if n.startswith("portfolio_")}
    kinds = {k: v["endpoint"] for k, v in pf["kinds"].items()}
    assert kinds == {k: f"portfolio_{k}" for k in kinds}
    assert set(kinds.values()) == funcs - {"portfolio_credit_returns"}, "credit_returns is held back (ANBIMA)"
    assert next(iter(kinds)) == "resolve"
    assert [p["name"] for p in pf["parameters"] if p["visibility"] == "main"] == ["kind", "month"]
    depth = next(p for p in pf["parameters"] if p["name"] == "max_depth")
    assert _sql_signature("portfolio_lookthrough")["p_max_depth"] == str(depth["default"])
    for kind, plan in pf["kinds"].items():
        required = {p for p, d in _sql_signature(plan["endpoint"]).items() if d is None}
        assert required <= set(plan["args"].values()), f"portfolio {kind}: the SQL requires {required}"


def test_portfolio_kinds_read_no_anbima_table():
    """ANBIMA data is leaving SILO: a portfolio kind may carry the filed ANBIMA class label, never read an anbima_* table."""
    sql = (ANALYTICAL / "31_api_portfolio.sql").read_text(encoding="utf-8")
    assert not re.search(r"(?:FROM|JOIN)\s+(?:public\.)?anbima_", sql, re.I)


def test_only_portfolio_is_post_and_its_body_fields_are_lists():
    for r in _built():
        assert r.get("method", "GET") == ("POST" if r["name"] == "portfolio" else "GET"), r["name"]
        assert ("body" in r) == (r["name"] == "portfolio"), r["name"]
    for b in _resource("portfolio")["body"]:
        assert b["items"] in ("string", "number", "date") and b["default"] is None and b["default_doc"].strip(), b
# ------------------------------- derivatives, curves, macro, positioning (#1057) --

ISSUE_1057 = {
    "derivatives": {
        "chain": "option_chain", "history": "option_history", "exercises": "option_exercises",
        "termo": "termo_history", "futures": "future_series", "futures_curve": "future_curve",
        "di_settlement": "di_settlement",
    },
    "curves": {"snapshot": "curve", "history": "curve_history", "vertices": "reference_rate"},
    "macro": {
        "series": "macro_series", "inflation": "inflation", "inflation_items": "inflation_items",
        "fx": "ptax", "expectations": "focus_expectations",
    },
    "positioning": {
        "short_interest": "short_interest", "short_by_sector": "short_interest_by_sector",
        "lending": "lending_trades", "lending_brokers": "lending_participants", "investor_flow": "investor_flow",
    },
}
WINDOWS_1057 = {"derivatives": 12, "curves": 12, "macro": 12, "positioning": 3}
MAIN_1057 = {"derivatives": ["kind", "date"], "curves": ["kind", "curve", "tenor"], "macro": ["kind"], "positioning": ["kind"]}
HIDDEN_1057 = {
    "derivatives": {"expiry_from"}, "curves": {"date"},
    "macro": {"family", "currency", "horizon"}, "positioning": {"sector", "investor_type"},
}


@pytest.mark.parametrize("name", sorted(ISSUE_1057))
def test_1057_kinds_map_to_the_issue_endpoints(name):
    r = _resource(name)
    assert {k: v["endpoint"] for k, v in r["kinds"].items()} == ISSUE_1057[name]
    kind = next(p for p in r["parameters"] if p["name"] == "kind")
    assert kind["default"] == next(iter(ISSUE_1057[name])), "the first kind is the default"
    assert r["window_months"] == WINDOWS_1057[name]
    assert [p["name"] for p in r["parameters"] if p["visibility"] == "main"] == MAIN_1057[name]
    assert {p["name"] for p in r["parameters"] if p["visibility"] == "hidden"} == HIDDEN_1057[name]


def test_a_view_range_is_a_date_column_the_view_publishes_and_from_to_map_to_it():
    for r in _built():
        for kind, plan in _plans(r):
            if "range" not in plan:
                continue
            assert plan.get("view"), f"{r['name']} kind {kind}: range is for a view read"
            assert plan["range"] in _view_columns(plan["endpoint"]), (r["name"], kind)
            assert plan["args"].get("from") == plan["range"] == plan["args"].get("to"), (r["name"], kind)


def test_every_view_read_that_takes_a_window_has_a_range():
    """A view kind that maps from must select a range, never an eq. on one date."""
    for r in _built():
        for kind, plan in _plans(r):
            if plan.get("view") and "from" in plan["args"]:
                assert plan.get("range"), f"{r['name']} kind {kind}: from on a view needs range"


def test_macro_inflation_kinds_have_the_three_year_window():
    kinds = _resource("macro")["kinds"]
    for k in ("inflation", "inflation_items"):
        assert kinds[k]["window_months"] == 36, k
    assert all("window_months" not in kinds[k] for k in ("series", "fx", "expectations"))


def test_macro_family_maps_the_focus_surveys_to_the_sql_endpoints():
    fam = next(p for p in _resource("macro")["parameters"] if p["name"] == "family")
    body = re.search(r"FUNCTION api\.focus_expectations\(.*?NOT IN \((.*?)\)", _sql(), re.S)
    assert body, "api.focus_expectations endpoint list not found"
    assert sorted(fam["sql_values"].values()) == sorted(re.findall(r"'([A-Za-z0-9]+)'", body.group(1)))


def test_macro_fx_all_reads_the_ptax_daily_view():
    fx = _resource("macro")["kinds"]["fx"]
    assert fx["when_empty"]["parameter"] == "currency" and fx["when_empty"]["value"] == "all"
    assert fx["when_empty"]["plan"]["endpoint"] == "ptax_daily" and fx["when_empty"]["plan"]["view"] is True


def test_curves_tenor_default_is_a_fixed_vertex_in_calendar_days():
    """curve_history takes B3's nominal tenor in CALENDAR days; 360 is the one-year vertex."""
    tenor = next(p for p in _resource("curves")["parameters"] if p["name"] == "tenor")
    assert tenor["default"] == 360 and tenor["type"] == "integer"
    assert _resource("curves")["kinds"]["history"]["args"]["tenor"] == "p_tenor_days"
    curve = next(p for p in _resource("curves")["parameters"] if p["name"] == "curve")
    assert curve["default"] == "PRE" and set(curve["values"]) == {"PRE", "DOC", "DPL"}


def test_positioning_help_carries_the_bdi_ratchet_notes():
    notes = " ".join(_resource("positioning")["notes"])
    for must in ("is_total", "doador", "tomador", "beneficial owner", "float_basis", "21 business days"):
        assert must in notes, must


def test_derivatives_clamped_functions_take_limit_and_cut_silently():
    """option_chain and option_exercises cut at a tier ceiling (LIMIT LEAST), so derivatives.ts probes N+1."""
    sql = _sql()
    for fn in ("option_chain", "option_exercises"):
        body = re.search(rf"FUNCTION api\.{fn}\(.*?\$\$;", sql, re.S)
        assert body and "LIMIT LEAST(" in body.group(0), fn
    ts = (FN_DIR / "resources" / "derivatives.ts").read_text(encoding="utf-8")
    assert "option_chain:" in ts and "option_exercises:" in ts
    # #1059: limit is the page size, so the gateway itself asks for one SQL page and one row more.
    assert "export const ASK = 1001;" in ts and "p_limit: ASK" in ts
    for fn in ("option_chain", "option_exercises"):
        assert "p_limit" in manifest()[fn].params, fn


# ------------------------------------------------- cursors and tiers (#1059) --

CONFIG_TS = FN_DIR / "config.ts"
METHODS = {"p_after", "date_window", "view_offset", "single_page"}
P_AFTER_FUNCTIONS = {"panel", "quote_history", "fund_nav", "index_history", "trade_consolidated_history"}


def test_every_plan_declares_how_it_pages():
    """Every list kind pages one of four ways; single_page says why it cannot page upstream."""
    m = manifest()
    for r in _built():
        for kind, plan in _plans(r):
            where = f"{r['name']} kind {kind}"
            paging = plan.get("paging")
            assert paging, f"{where}: no paging method"
            method = paging["method"]
            assert method in METHODS, (where, method)
            assert "limit" not in plan["args"], f"{where}: limit is the page size, never sent to the SQL"
            if method == "p_after":
                assert plan["endpoint"] in P_AFTER_FUNCTIONS, where
                assert "p_after" in m[plan["endpoint"]].params, f"{where}: api.{plan['endpoint']} has no p_after"
                assert paging["key"], where
                if "requires" in paging:
                    assert paging["requires"] in _accepted(r) and paging["otherwise"] == "date_window", where
            if method == "date_window" or paging.get("otherwise") == "date_window":
                assert "from" in plan["args"] and "to" in plan["args"], f"{where}: a date-window walk needs from and to"
                assert paging.get("order") in ("asc", "desc"), where
            if method == "view_offset":
                assert plan.get("view") and plan.get("order"), f"{where}: view paging needs a view and an order"
            if method == "single_page":
                assert paging.get("reason", "").strip(), f"{where}: single_page must say why"
            if plan.get("view"):
                assert method == "view_offset", f"{where}: a view pages with order + limit + offset"


def test_every_function_with_a_p_after_cursor_pages_with_it():
    used = {plan["endpoint"] for r in _built() for _, plan in _plans(r) if plan["paging"]["method"] == "p_after"}
    with_cursor = {n for n, e in manifest().items() if "p_after" in e.params}
    assert with_cursor >= P_AFTER_FUNCTIONS
    assert used == P_AFTER_FUNCTIONS, used


def test_p_after_keys_are_the_sql_cursor_keys():
    """panel's cursor is date|id|metric|asset_class; the date-cursor functions page on their own date column."""
    keys = {plan["endpoint"]: plan["paging"]["key"] for r in _built() for _, plan in _plans(r) if plan["paging"]["method"] == "p_after"}
    assert keys["panel"] == ["date", "id", "metric", "asset_class"]
    assert keys["fund_nav"] == ["period"]
    for fn in ("quote_history", "index_history", "trade_consolidated_history"):
        assert keys[fn] == ["trade_date"], fn
    assert "date|id|metric|asset_class" in _sql()


def _final_order_by(fn: str) -> str:
    """The last ORDER BY (not a window's) of the newest CREATE OR REPLACE FUNCTION api.<fn>."""
    sql = _sql()
    starts = [mm.start() for mm in re.finditer(rf"CREATE OR REPLACE FUNCTION api\.{fn}\(", sql)]
    assert starts, fn
    body = sql[starts[-1]:]
    nxt = re.search(r"CREATE OR REPLACE FUNCTION api\.", body[10:])
    body = body[: nxt.start() + 10] if nxt else body
    orders = [o for o in re.findall(r"ORDER BY ([^\n]*)", body) if "OVER" not in o]
    assert orders, fn
    return orders[-1]


def test_date_window_order_is_the_sql_order():
    """A walk goes in the function's own date order, so pages stay in order across windows."""
    for r in _built():
        for kind, plan in _plans(r):
            paging = plan["paging"]
            if "date_window" not in (paging["method"], paging.get("otherwise")):
                continue
            last = _final_order_by(plan["endpoint"])
            depth, first = 0, ""
            for ch in last:  # the first key, up to a comma outside parentheses
                if ch == "," and depth == 0:
                    break
                depth += (ch == "(") - (ch == ")")
                first += ch
            want = "desc" if "DESC" in first else "asc"
            assert paging["order"] == want, (r["name"], kind, plan["endpoint"], last)


def test_every_resource_takes_limit_the_page_size():
    for r in _built():
        assert "limit" in r.get("shared", []), r["name"]


def test_daily_flags_are_well_formed():
    for r in _built():
        for kind, plan in _plans(r):
            d = plan.get("daily")
            if d is None:
                continue
            assert "from" in plan["args"], (r["name"], kind)
            assert d is True or (set(d) == {"parameter", "value"} and d["parameter"] in _accepted(r)), (r["name"], kind)


def _tiers() -> dict:
    src = CONFIG_TS.read_text(encoding="utf-8")
    block = re.search(r"// BEGIN TIERS\n(.*?)// END TIERS", src, re.S)
    assert block, "the TIERS block (between BEGIN and END markers) was not found in config.ts"
    out: dict = {}
    for tier, body in re.findall(r"^  (\w+): \{\n(.*?)^  \},", block.group(1), re.S | re.M):
        out[tier] = {k: json.loads(v) for k, v in re.findall(r"^    (\w+): ([^,\n]+),", body, re.M)}
    return out


def test_tier_numbers_are_the_owner_decision_in_one_block():
    """#1059 / #1061 (owner, 2026-11-03): the numbers live once, in config.ts."""
    t = _tiers()
    assert t["anonymous"] == {
        "page_max": 10, "rows_per_call": 50, "daily_window_months": 3, "panel_ids": 1,
        "screens": False, "portfolio": False, "panel_universe": False, "requests_per_minute": 10,
    }
    assert t["signed_in"] == {
        "page_max": 100, "rows_per_call": 1000, "daily_window_months": 24, "panel_ids": 3,
        "screens": True, "portfolio": True, "panel_universe": False, "requests_per_minute": 30,
    }
    assert t["pro"] == {
        "page_max": 1000, "rows_per_call": None, "daily_window_months": None, "panel_ids": 50,
        "screens": True, "portfolio": True, "panel_universe": True, "requests_per_minute": 300,
    }
    others = "\n".join(
        p.read_text(encoding="utf-8") for p in FN_DIR.rglob("*.ts") if p.name != "config.ts" and not p.name.endswith("_test.ts")
    )
    assert "rows_per_call:" not in others and "page_max:" not in others, "tier numbers belong in config.ts only"
