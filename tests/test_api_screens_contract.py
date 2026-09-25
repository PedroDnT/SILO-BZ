"""The forensic screens in schema `api` (23_api_screens.sql, catalog v31).

Offline, like the rest of the suite: the SQL text, the catalog and the dashboard
sources are read from the repository and pinned to each other. What this file
exists to keep true:

* ONE definition. Every api.screen_* calls the public screen the dashboard
  calls (15_fraud_screens.sql) and never restates its logic, so the page and
  the API cannot disagree about who crossed a threshold.
* SIGNALS, NOT VERDICTS. Every row carries `screen` and `params`; no column is a
  score; the catalog's `meaning` says what else produces the same pattern.
* The house serving rules from 19: SECURITY DEFINER with an empty pinned
  search_path, REVOKE from PUBLIC then GRANT to anon/authenticated, one page
  plus one row and api.assert_row_cap refusing above it, 22023 on bad input.
* The defaults are the dashboard's own calls, in three places at once: the SQL
  DEFAULTs, catalog SCREENS[...]["params"] and dashboard/sources/supabase.
* The grants gap stays closed: the public screens are revoked from client roles
  and the apply asserts it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ANALYTICAL = ROOT / "src" / "store" / "analytical"
SQL23_PATH = ANALYTICAL / "23_api_screens.sql"
SQL15_PATH = ANALYTICAL / "15_fraud_screens.sql"
SQL23 = SQL23_PATH.read_text(encoding="utf-8")
SQL15 = SQL15_PATH.read_text(encoding="utf-8")
SOURCES = ROOT / "dashboard" / "sources" / "supabase"
APPLY = ROOT / "scripts" / "apply_analytical.sh"

# api wrapper -> (public function it calls, catalog SCREENS key)
WRAPPERS = {
    "screen_zombie_growth": ("fraud_screen_zombie_growth", "zombie_growth"),
    "screen_captive_vehicles": ("fraud_screen_captive_vehicles", "captive_vehicles"),
    "screen_evergreen_aging": ("fraud_screen_evergreen_aging", "evergreen_aging"),
    "screen_overdue_securit": ("fraud_screen_overdue_securit", "overdue_securit"),
    "screen_dormant_funds": ("fraud_screen_dormant_funds", "dormant_funds"),
    "screen_dormant_trend": ("fraud_screen_dormant_trend", "dormant_trend"),
    "screen_delinquency_drivers": ("fidc_delinquency_drivers", "delinquency_drivers"),
}

# The dashboard's calls, as the sources spell them (dashboard/pages/
# suspicious.md, dormant.md, fidc.md). The api defaults must reproduce them.
DASHBOARD_CALLS = {
    "zombie_growth": ("zombie_growth.sql", r"fraud_screen_zombie_growth\(\s*null\s*,\s*5\s*,\s*1e6\s*\)"),
    "captive_vehicles": ("captive_vehicles.sql", r"fraud_screen_captive_vehicles\(\s*3\s*,\s*10\s*,\s*5e7\s*\)"),
    "evergreen_aging": ("evergreen_aging.sql", r"fraud_screen_evergreen_aging\(\s*12\s*,\s*70\s*,\s*10\s*\)"),
    "overdue_securit": ("overdue_securit.sql", r"fraud_screen_overdue_securit\(\s*1e5\s*\)"),
    "dormant_funds": ("dormant_shells.sql", r"fraud_screen_dormant_funds\(\s*3\s*\)"),
    "delinquency_drivers": ("fidc_drivers_all.sql", r"fidc_delinquency_drivers\(\s*\)"),
}
DASHBOARD_VALUES = {
    "zombie_growth": {"p_period": None, "p_min_delinq_pct": 5, "p_min_aum": 1e6},
    "captive_vehicles": {"p_lookback_months": 3, "p_max_investors": 10, "p_min_aum": 5e7},
    "evergreen_aging": {"p_lookback_months": 12, "p_min_longtail_pct": 70, "p_max_variation_pp": 10},
    "overdue_securit": {"p_min_volume": 1e5},
    "dormant_funds": {"p_lookback_months": 3},
    "dormant_trend": {"p_lookback_months": 3, "p_history_months": 36},
}


def _strip(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _chunk(name: str) -> str:
    """The CREATE FUNCTION api.<name> ... up to its closing $fn$;"""
    start = SQL23.index(f"CREATE OR REPLACE FUNCTION api.{name}(")
    end = SQL23.index("$fn$;", start) + len("$fn$;")
    return SQL23[start:end]


def _signature(name: str) -> str:
    chunk = _chunk(name)
    return chunk[chunk.index("(") + 1: chunk.index("\nRETURNS")]


def _arg_defaults(name: str) -> dict:
    """{p_arg: python default} from the CREATE FUNCTION signature."""
    out = {}
    for line in _strip(_signature(name)).splitlines():
        m = re.match(r"\s*(p_\w+)\s+\w+\s+DEFAULT\s+([^,\s]+)", line)
        if not m:
            continue
        raw = m.group(2)
        out[m.group(1)] = None if raw.upper() == "NULL" else float(raw)
    return out


def _result_columns(name: str) -> list[str]:
    chunk = _strip(_chunk(name))
    body = chunk[chunk.index("RETURNS TABLE (") + len("RETURNS TABLE ("): chunk.index("\n)\nLANGUAGE")]
    return [ln.split()[0] for ln in body.splitlines() if ln.strip()]


def _arg_types(name: str) -> str:
    """'DATE, NUMERIC, NUMERIC' — the signature used in GRANT/REVOKE/COMMENT."""
    types = []
    for line in _strip(_signature(name)).splitlines():
        m = re.match(r"\s*p_\w+\s+(\w+)", line)
        if m:
            types.append(m.group(1))
    return ", ".join(types)


# ---------------------------------------------------------------------------
# Wiring: the file is picked up, after the files it depends on.
# ---------------------------------------------------------------------------


def test_apply_script_globs_every_numbered_file_so_23_is_applied():
    script = APPLY.read_text(encoding="utf-8")
    assert "src/store/analytical/[0-9][0-9]_*.sql" in script, (
        "apply_analytical.sh must glob the numbered files; a hand list would skip 23"
    )
    ordered = sorted(p.name for p in ANALYTICAL.glob("[0-9][0-9]_*.sql"))
    assert ordered.index("23_api_screens.sql") > ordered.index("15_fraud_screens.sql")
    assert ordered.index("23_api_screens.sql") > ordered.index("19_api_contract.sql")


def test_file_is_one_transaction_and_guards_its_dependencies():
    body = _strip(SQL23)
    assert re.search(r"^\s*BEGIN\s*;", body, re.M)
    assert re.search(r"COMMIT\s*;\s*$", body.strip())
    assert "to_regprocedure('api.assert_row_cap(bigint, boolean, text)') IS NULL" in body
    assert "to_regprocedure('public.fraud_screen_zombie_growth(date, numeric, numeric)') IS NULL" in body


def test_every_wrapper_exists_and_nothing_else_is_created():
    created = set(re.findall(r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+api\.(\w+)\(", _strip(SQL23)))
    assert created == set(WRAPPERS)


# ---------------------------------------------------------------------------
# One definition, served through the house privilege model.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(WRAPPERS))
def test_wrapper_calls_the_public_screen_and_restates_nothing(name):
    public_fn, _ = WRAPPERS[name]
    body = _strip(_chunk(name))
    assert f"FROM public.{public_fn}(" in body, f"{name} must call public.{public_fn}"
    # No landing table and no fact table: the logic lives in 15, only there.
    assert not re.search(r"\bpublic\.(cvm_\w+|fact_\w+|dim_\w+|b3_\w+)", body), (
        f"{name} reads a relation directly; call the screen instead"
    )


@pytest.mark.parametrize("name", sorted(WRAPPERS))
def test_wrapper_is_definer_with_an_empty_pinned_search_path(name):
    head = _chunk(name)
    head = head[: head.index("AS $fn$")]
    assert "SECURITY DEFINER" in head
    assert "SET search_path = ''" in head


@pytest.mark.parametrize("name", sorted(WRAPPERS))
def test_wrapper_is_revoked_from_public_then_granted_to_the_client_roles(name):
    sig = f"api.{name}({_arg_types(name)})"
    assert f"REVOKE ALL ON FUNCTION {sig} FROM PUBLIC;" in SQL23, sig
    assert f"GRANT EXECUTE ON FUNCTION {sig} TO anon, authenticated;" in SQL23, sig


def test_silo_api_gets_no_screen_grant():
    """No /v1 route serves a screen, so the adapter role has no reason to hold one
    (the decision 20/21 took for the lending views)."""
    assert "silo_api" not in _strip(SQL23)


@pytest.mark.parametrize("name", sorted(WRAPPERS))
def test_wrapper_refuses_above_one_page_instead_of_trimming(name):
    body = _strip(_chunk(name))
    assert re.search(r"\bLIMIT\s+1001\b", body), "fetch one page plus one row"
    assert re.search(r"\bLIMIT\s+1000\s*;", body), "return at most one page"
    assert f"api.assert_row_cap((SELECT count(*) FROM page), FALSE, '{name}')" in body
    assert "p_after" not in body, "screens are raise-only; publishing a cursor would be a lie"


@pytest.mark.parametrize("name", sorted(WRAPPERS))
def test_bad_arguments_raise_the_house_sqlstate(name):
    body = _strip(_chunk(name))
    assert "ERRCODE = '22023'" in body
    # Clamping a threshold would serve a different screen under the caller's label.
    assert "LEAST(" not in body and "GREATEST(" not in body


# ---------------------------------------------------------------------------
# Signals, not verdicts.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(WRAPPERS))
def test_every_row_carries_screen_and_params(name):
    cols = _result_columns(name)
    assert cols[-2:] == ["screen", "params"], f"{name}: screen, params must close every row"
    _, key = WRAPPERS[name]
    assert f"'{key}'::text" in _strip(_chunk(name)), f"{name} must label its rows '{key}'"


@pytest.mark.parametrize("name", sorted(WRAPPERS))
def test_params_echo_exactly_the_function_arguments(name):
    body = _strip(_chunk(name))
    call = body[body.index("jsonb_build_object("):]
    call = call[: call.index("\n    FROM page g")]
    keys = re.findall(r"'(p_\w+)'\s*,\s*(p_\w+)", call)
    assert keys, f"{name}: params must be built from the arguments"
    assert all(k == v for k, v in keys), f"{name}: a params key must be its own argument"
    declared = re.findall(r"^\s*(p_\w+)\s", _strip(_signature(name)), re.M)
    assert sorted(k for k, _ in keys) == sorted(declared), (
        f"{name}: every argument, and only arguments, is echoed in params"
    )


@pytest.mark.parametrize("name", sorted(WRAPPERS))
def test_no_column_is_a_score(name):
    for col in _result_columns(name):
        assert not re.search(r"score|suspic|fraud|risk_level|verdict", col, re.I), (
            f"{name}.{col}: the screens publish thresholds crossed, never a score"
        )


@pytest.mark.parametrize("name", sorted(WRAPPERS))
def test_comment_leads_with_signal_not_verdict(name):
    m = re.search(rf"COMMENT ON FUNCTION api\.{name}\([^)]*\) IS\s*'(.*?)';\n", SQL23, re.S)
    assert m, f"{name} has no COMMENT"
    assert m.group(1).startswith("SIGNAL, NOT A VERDICT."), name


@pytest.mark.parametrize("name", sorted(WRAPPERS))
def test_columns_are_english(name):
    """SERVING.md: never expose Portuguese landing columns as the user API."""
    portuguese = {"inad_pct", "pl_mm", "situacao", "data_vencimento", "cnpj_securit",
                  "codigo_identificacao", "admin_name", "last_pl", "parked_pl",
                  "del_start", "del_end", "min_investors", "max_investors"}
    assert not portuguese & set(_result_columns(name)), name


# ---------------------------------------------------------------------------
# Defaults: SQL == catalog == dashboard.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(WRAPPERS))
def test_catalog_params_are_the_sql_defaults(name):
    from serve.catalog import SCREENS

    _, key = WRAPPERS[name]
    published = SCREENS[key]["params"]
    sql = _arg_defaults(name)
    assert set(published) == set(sql), f"{key}: catalog params keys != SQL arguments"
    for arg, value in sql.items():
        got = published[arg]
        assert (got is None and value is None) or float(got) == value, (
            f"{key}.{arg}: catalog says {got}, SQL DEFAULT is {value}"
        )


@pytest.mark.parametrize("key", sorted(DASHBOARD_CALLS))
def test_dashboard_still_calls_the_screen_with_the_api_defaults(key):
    source, pattern = DASHBOARD_CALLS[key]
    text = (SOURCES / source).read_text(encoding="utf-8")
    assert re.search(pattern, text, re.I), (
        f"{source} no longer calls the screen with the values api.screen_* defaults to; "
        "move both, or the API stops reproducing the page"
    )


@pytest.mark.parametrize("key", sorted(DASHBOARD_VALUES))
def test_dashboard_values_are_the_catalog_defaults(key):
    from serve.catalog import SCREENS

    for arg, value in DASHBOARD_VALUES[key].items():
        got = SCREENS[key]["params"][arg]
        assert (got is None and value is None) or float(got) == float(value), (key, arg)


def test_delinquency_driver_defaults_match_the_public_function():
    """The /fidc page calls fidc_delinquency_drivers() bare, so its defaults are
    the page's — and the api wrapper must default to the same numbers."""
    fn = SQL15[SQL15.index("CREATE OR REPLACE FUNCTION fidc_delinquency_drivers("):]
    fn = fn[: fn.index("RETURNS TABLE")]
    assert "p_months        INT     DEFAULT 12" in fn
    assert "p_min_months    INT     DEFAULT 6" in fn
    d = _arg_defaults("screen_delinquency_drivers")
    assert (d["p_months"], d["p_min_months"], d["p_min_delta_brl"], d["p_min_delta_pp"]) == (12, 6, 1e6, 1.0)


# ---------------------------------------------------------------------------
# Output filters are refused, not silently ignored (they carry an enum).
# ---------------------------------------------------------------------------


def test_output_filters_refuse_unknown_values():
    dormant = _strip(_chunk("screen_dormant_funds"))
    assert "p_dormancy NOT IN ('empty_shell', 'parked_capital')" in dormant
    drivers = _strip(_chunk("screen_delinquency_drivers"))
    assert ("p_driver NOT IN ('consistent_worsening', 'value_up_rate_masked', "
            "'denominator_only', 'improvement', 'stable')") in drivers
    # The five classes are exactly what the public function emits.
    for cls in ("consistent_worsening", "value_up_rate_masked", "denominator_only",
                "improvement", "stable"):
        assert f"'{cls}'" in SQL15


# ---------------------------------------------------------------------------
# The grants gap (DATA_INVENTORY.md §3) stays closed.
# ---------------------------------------------------------------------------

PUBLIC_SIGNATURES = {
    "fraud_screen_zombie_growth": "DATE, NUMERIC, NUMERIC",
    "fraud_screen_captive_vehicles": "INT, INT, NUMERIC",
    "fraud_screen_evergreen_aging": "INT, NUMERIC, NUMERIC",
    "fraud_screen_overdue_securit": "NUMERIC",
    "fraud_screen_dormant_funds": "INT",
    "fraud_screen_dormant_trend": "INT, INT",
    "fidc_delinquency_drivers": "DATE, INT, INT, NUMERIC, NUMERIC",
}


@pytest.mark.parametrize("fn", sorted(PUBLIC_SIGNATURES))
def test_public_screen_is_revoked_from_every_client_role(fn):
    body = _strip(SQL15)
    assert not re.search(rf"GRANT\s+EXECUTE\s+ON\s+FUNCTION\s+{fn}\(", body), f"{fn} is granted again"
    assert re.search(
        rf"REVOKE ALL ON FUNCTION {fn}\({re.escape(PUBLIC_SIGNATURES[fn])}\)\s+FROM PUBLIC, anon, authenticated;",
        body,
    ), f"{fn} is not revoked from PUBLIC, anon, authenticated"


def test_public_screens_pin_their_own_search_path():
    """A DEFINER caller's empty search_path propagates down the stack; unpinned,
    the screens' unqualified table names would not resolve from the API."""
    n_fns = len(re.findall(r"CREATE OR REPLACE FUNCTION \w+\(", SQL15))
    assert n_fns == len(PUBLIC_SIGNATURES)
    assert SQL15.count("SECURITY INVOKER\nSET search_path = public, pg_temp") == n_fns


def test_apply_asserts_the_boundary_for_every_public_screen():
    block = SQL23[SQL23.index("DO $boundary$"):]
    for fn in PUBLIC_SIGNATURES:
        assert f"'public.{fn}(" in block, f"the boundary check does not cover {fn}"
    assert "has_function_privilege(r, f::regprocedure, 'EXECUTE')" in block
    assert "RAISE EXCEPTION" in block


def test_dashboard_reads_through_a_build_time_login_not_a_client_role():
    """The revoke is safe only because the Evidence build connects as the postgres
    login. If this ever changes to a PostgREST client role, the pages break."""
    readme = (ROOT / "dashboard" / "README.md").read_text(encoding="utf-8")
    assert "EVIDENCE_SOURCE__supabase__user          # postgres.<project-ref>" in readme
    conn = (SOURCES / "connection.yaml").read_text(encoding="utf-8")
    assert "anon" not in conn and "authenticated" not in conn


# ---------------------------------------------------------------------------
# The catalog publishes them.
# ---------------------------------------------------------------------------


# v35: the filing-behaviour screens (25_api_filing_screens.sql) share the
# catalog's `screens` block but are not wrappers — no dashboard page runs them.
# tests/test_filing_screens_contract.py owns them.
FILING_SCREENS = {"restatements", "late_filers", "silent_filers"}


def test_catalog_publishes_every_screen():
    from serve.catalog import CATALOG_VERSION, CONSTRAINTS, catalog_payload

    assert CATALOG_VERSION >= 31
    payload = catalog_payload()
    assert set(payload["screens"]) == {key for _, key in WRAPPERS.values()} | FILING_SCREENS
    for name, (_, key) in WRAPPERS.items():
        entry = payload["screens"][key]
        assert entry["function"] == name
        assert payload["postgrest"][name] == f"POST /rest/v1/rpc/{name}"
        assert len(entry["meaning"]) > 80, f"{key}: meaning must say what else looks the same"
        assert entry["dashboard"] in {"/suspicious", "/dormant", "/fidc"}
        assert name in payload["limits"]["page"]["all"]
        assert name in payload["limits"]["page"]["functions"]["raise_only"]
    assert any(c.startswith("THE SCREENS ARE SIGNALS, NOT VERDICTS.") for c in CONSTRAINTS)


def test_catalog_output_filters_match_the_sql_filters():
    from serve.catalog import SCREENS

    assert set(SCREENS["dormant_funds"]["filters"]) == {"p_dormancy", "p_min_nav"}
    assert set(SCREENS["delinquency_drivers"]["filters"]) == {"p_driver"}
