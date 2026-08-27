"""Offline assertions over the api-contract SQL (SERVING.md Steps 3 + 6).

No database: these tests parse the SQL text of 19_api_contract.sql and
12_grants_and_rls.sql and assert the privilege boundary and the in-SQL row
caps hold. They are deliberately regex-based (robust to reformatting), and
they strip comments before scanning for GRANT/REVOKE so prose never trips
them. A real apply is still Step 2's job (Silo `analytics-only` dispatch /
`api-smoke`) — substring tests are not proof the SQL runs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SQL19_PATH = ROOT / "src" / "store" / "analytical" / "19_api_contract.sql"
SQL12_PATH = ROOT / "src" / "store" / "analytical" / "12_grants_and_rls.sql"

SQL19 = SQL19_PATH.read_text(encoding="utf-8")
SQL12 = SQL12_PATH.read_text(encoding="utf-8")

# Keep in lockstep with serve/app.py (_MAX_POINTS / _MAX_PANEL) and the cap
# comments in 19_api_contract.sql: SQL caps are serve cap + 1 so the adapter
# can 400 instead of silently truncating.
SERIES_CAP = 5001
PANEL_CAP = 100001

LANDING_PATTERN = re.compile(
    r"\b(?:public\.)?(?:cvm_\w+|b3_cotahist\w*|vw_b3_(?:quote_vista|instrument_typed))\b",
    re.I,
)


def _strip_comments(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _statements(sql: str) -> list[str]:
    """Comment-free ;-separated chunks. Splitting inside $$ bodies is fine for
    the GRANT/REVOKE scans below (a GRANT never lives inside a function body)."""
    return [s.strip() for s in _strip_comments(sql).split(";") if s.strip()]


def _function_chunks(sql: str) -> dict[str, str]:
    """Map function name -> full CREATE OR REPLACE FUNCTION chunk (up to the
    next CREATE statement or end of file)."""
    out: dict[str, str] = {}
    pattern = re.compile(
        r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+(api\.\w+)", re.I
    )
    starts = [(m.start(), m.group(1).lower()) for m in pattern.finditer(sql)]
    for i, (pos, name) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(sql)
        out[name] = sql[pos:end]
    return out


FUNCS = _function_chunks(SQL19)

EXPECTED_FUNCTIONS = {
    "api.quote_history",
    "api.quote_latest",
    "api.fund_profile",
    "api.fund_nav",
    "api.search_funds",
    "api.coverage",
    "api.panel",
    "api.universe",
    "api.lookup",
}


def test_all_expected_api_functions_present():
    assert set(FUNCS) == EXPECTED_FUNCTIONS


# ---------------------------------------------------------------------------
# Step 6 — SECURITY DEFINER hygiene
# ---------------------------------------------------------------------------

# Wrappers that delegate to a public.* analytical function. search_path
# propagates down the call stack and those inner functions resolve relation
# names unqualified, so an empty pin breaks them at runtime ("relation does
# not exist" — found by review on PR #102). They pin "public, pg_temp"
# instead: still an immutable per-function GUC, so the DEFINER hole (a
# caller-controlled search_path) stays closed.
DELEGATING_FUNCTIONS = {"api.fund_profile", "api.fund_nav", "api.search_funds"}


def test_every_definer_function_pins_an_immutable_search_path():
    for name, chunk in FUNCS.items():
        header = re.split(r"\$\$", chunk, maxsplit=1)[0]
        if not re.search(r"\bSECURITY\s+DEFINER\b", header, re.I):
            continue
        if name in DELEGATING_FUNCTIONS:
            assert re.search(
                r"SET\s+search_path\s*=\s*public,\s*pg_temp", header, re.I
            ), f"{name} delegates to public.* and must pin 'public, pg_temp'"
        else:
            assert re.search(r"SET\s+search_path\s*=\s*''", header, re.I), (
                f"{name} is SECURITY DEFINER without SET search_path = ''"
            )


def test_delegating_set_matches_functions_that_call_public():
    # The two properties must move together: a function that calls a
    # public.* function needs the public pin; a self-contained one must keep
    # the empty pin. Derived from the bodies so the sets cannot drift.
    for name, chunk in FUNCS.items():
        body = re.split(r"\$\$", chunk, maxsplit=1)[-1]
        calls_public = bool(re.search(r"\bpublic\.\w+\s*\(", body))
        assert calls_public == (name in DELEGATING_FUNCTIONS), (
            f"{name}: calls_public={calls_public} but "
            f"DELEGATING_FUNCTIONS says {name in DELEGATING_FUNCTIONS}"
        )


def test_no_definer_function_keeps_a_mutable_search_path():
    # A search_path a caller can influence is the exact hole Step 6 closes.
    # Allowed pins: '' (pg_catalog + explicit qualification) or the
    # delegating wrappers' immutable "public, pg_temp" — nothing else.
    body = _strip_comments(SQL19)
    values = re.findall(r"SET\s+search_path\s*=\s*([^\n;]*)", body, re.I)
    assert values, "expected SET search_path clauses in 19_api_contract.sql"
    for value in values:
        assert value.strip() in ("''", "public, pg_temp"), (
            f"unexpected search_path pin: {value.strip()!r}"
        )


def test_api_functions_are_definer_not_invoker():
    # The design is DEFINER + no landing-table grants; an INVOKER api function
    # would force granting clients SELECT on landing tables to work at all.
    for name, chunk in FUNCS.items():
        header = re.split(r"\$\$", chunk, maxsplit=1)[0]
        assert re.search(r"\bSECURITY\s+DEFINER\b", header, re.I), (
            f"{name} is not SECURITY DEFINER; see the Step 6 rationale in 19_api_contract.sql"
        )
        assert not re.search(r"\bSECURITY\s+INVOKER\b", header, re.I)


def test_views_are_explicitly_owner_privileged():
    for view in ("api.quotes", "api.funds"):
        assert re.search(
            rf"ALTER\s+VIEW\s+{re.escape(view)}\s+SET\s*\(\s*security_invoker\s*=\s*false\s*\)",
            SQL19,
            re.I,
        ), f"{view} does not pin security_invoker = false"


# ---------------------------------------------------------------------------
# Step 6 — grants: silo_api gets schema api only; anon gets no landing tables
# ---------------------------------------------------------------------------

def test_no_grant_to_client_roles_on_landing_tables():
    for path, sql in ((SQL19_PATH, SQL19), (SQL12_PATH, SQL12)):
        for stmt in _statements(sql):
            if not re.match(r"GRANT\b", stmt, re.I):
                continue
            if not re.search(r"\b(anon|authenticated|silo_api)\b", stmt, re.I):
                continue
            assert not LANDING_PATTERN.search(stmt), (
                f"{path.name}: client-role grant touches a landing table: {stmt!r}"
            )


def test_silo_api_grants_are_schema_api_only():
    for stmt in _statements(SQL19) + _statements(SQL12):
        if re.match(r"GRANT\b", stmt, re.I) and re.search(r"\bsilo_api\b", stmt, re.I):
            assert re.search(r"\bapi\b", stmt, re.I), (
                f"silo_api granted something outside schema api: {stmt!r}"
            )


def test_silo_api_covers_the_whole_api_surface():
    grants = [
        s
        for s in _statements(SQL19)
        if re.match(r"GRANT\b", s, re.I) and re.search(r"\bsilo_api\b", s, re.I)
    ]
    joined = "\n".join(grants)
    assert re.search(r"GRANT\s+USAGE\s+ON\s+SCHEMA\s+api\s+TO\s+silo_api", joined, re.I)
    assert re.search(r"GRANT\s+SELECT\s+ON\s+api\.quotes\s*,\s*api\.funds\s+TO\s+silo_api", joined, re.I)
    for fn in sorted(EXPECTED_FUNCTIONS):
        assert re.search(
            rf"GRANT\s+EXECUTE\s+ON\s+FUNCTION\s+{re.escape(fn)}\s*\(", joined, re.I
        ), f"missing GRANT EXECUTE ... {fn} TO silo_api"


def test_defensive_public_schema_revokes_for_silo_api():
    body = _strip_comments(SQL19)
    assert re.search(
        r"REVOKE\s+ALL\s+ON\s+ALL\s+TABLES\s+IN\s+SCHEMA\s+public\s+FROM\s+silo_api", body, re.I
    )
    assert re.search(
        r"REVOKE\s+ALL\s+ON\s+ALL\s+FUNCTIONS\s+IN\s+SCHEMA\s+public\s+FROM\s+silo_api", body, re.I
    )


def test_landing_table_revokes_for_anon_are_present():
    body = _strip_comments(SQL12)
    for table in (
        "cvm_ingest_log",
        "b3_cotahist",
        "vw_b3_quote_vista",
        "vw_b3_instrument_typed",
        "cvm_fidc_mensal",
    ):
        assert re.search(
            rf"REVOKE\s+ALL\s+ON\s+TABLE\s+{table}\s+FROM\s+anon\s*,\s*authenticated", body, re.I
        ), f"missing landing-table revoke for {table}"


def test_b3_asset_type_reaches_every_discovery_and_panel_surface():
    assert "v.instrument_type   AS asset_class" in SQL19
    assert "FROM public.vw_b3_instrument_typed v" in SQL19
    assert "q.asset_class" in FUNCS["api.panel"]
    assert "q.asset_class" in FUNCS["api.universe"]
    assert "q.asset_class" in FUNCS["api.lookup"]


def test_universe_classifies_only_the_latest_b3_session():
    chunk = FUNCS["api.universe"]
    assert "latest_quote_session AS" in chunk
    assert "SELECT max(q.trade_date)" in chunk
    assert "s.trade_date = q.trade_date" in chunk


def test_typed_b3_surfaces_do_not_assume_equity_board_02():
    for name in ("api.panel", "api.universe", "api.lookup"):
        assert "board = '02'" not in FUNCS[name]
    assert re.search(r"p_board\s+TEXT\s+DEFAULT\s+NULL", FUNCS["api.quote_history"])
    assert re.search(r"p_board\s+TEXT\s+DEFAULT\s+NULL", FUNCS["api.quote_latest"])
    assert "latest.board" in FUNCS["api.quote_history"]


def test_ingest_log_summary_not_executable_by_clients():
    body = _strip_comments(SQL12)
    assert not re.search(
        r"GRANT\s+EXECUTE\s+ON\s+FUNCTION\s+ingest_log_summary", body, re.I
    )
    assert re.search(
        r"REVOKE\s+ALL\s+ON\s+FUNCTION\s+ingest_log_summary", body, re.I
    )


# ---------------------------------------------------------------------------
# Step 6 — role creation and role-level runtime settings
# ---------------------------------------------------------------------------

def test_role_creation_is_guarded_and_nologin():
    assert re.search(
        r"IF\s+NOT\s+EXISTS\s*\(\s*SELECT\s+1\s+FROM\s+pg_roles\s+WHERE\s+rolname\s*=\s*'silo_api'",
        SQL12,
        re.I,
    ), "CREATE ROLE silo_api is not guarded by a pg_roles check"
    assert re.search(r"CREATE\s+ROLE\s+silo_api\s+NOLOGIN", SQL12, re.I)
    # And 19 must NOT try to create the role (12 applies first, owns creation).
    assert not re.search(r"CREATE\s+ROLE", _strip_comments(SQL19), re.I)


def test_statement_timeout_is_a_role_property():
    assert re.search(
        r"ALTER\s+ROLE\s+silo_api\s+SET\s+statement_timeout\s*=\s*'15s'", SQL12, re.I
    )
    assert re.search(
        r"ALTER\s+ROLE\s+silo_api\s+SET\s+default_transaction_read_only\s*=\s*on", SQL12, re.I
    )


def test_no_password_outside_comments():
    for path, sql in ((SQL12_PATH, SQL12), (SQL19_PATH, SQL19)):
        stripped = _strip_comments(sql)
        assert "PASSWORD" not in stripped.upper(), (
            f"{path.name}: PASSWORD appears outside a comment — never commit credentials"
        )


# ---------------------------------------------------------------------------
# Step 3 (SQL half) — hard row caps inside the functions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "fn,cap",
    [
        ("api.panel", PANEL_CAP),
        ("api.quote_history", SERIES_CAP),
        ("api.fund_nav", SERIES_CAP),
    ],
)
def test_series_functions_carry_internal_row_caps(fn, cap):
    body = _strip_comments(FUNCS[fn])
    assert re.search(rf"\bLIMIT\s+{cap}\b", body), f"{fn} lost its LIMIT {cap} cap"


def test_caps_are_serve_caps_plus_one():
    """The SQL cap must be exactly serve's cap + 1: at the cap itself serve
    could never distinguish 'too large' from 'complete' and would silently
    hand back a truncated (fabricated) panel."""
    app_py = (ROOT / "serve" / "app.py").read_text(encoding="utf-8")
    m_points = re.search(r"_MAX_POINTS\s*=\s*([\d_]+)", app_py)
    m_panel = re.search(r"_MAX_PANEL\s*=\s*([\d_]+)", app_py)
    assert m_points and m_panel, "serve/app.py no longer defines _MAX_POINTS/_MAX_PANEL"
    assert SERIES_CAP == int(m_points.group(1).replace("_", "")) + 1
    assert PANEL_CAP == int(m_panel.group(1).replace("_", "")) + 1


def test_discovery_functions_stay_bounded():
    assert re.search(r"LIMIT\s+LEAST\(GREATEST\(COALESCE\(p_limit,\s*50\),\s*1\),\s*500\)", FUNCS["api.universe"])
    assert re.search(r"\bLIMIT\s+20\b", _strip_comments(FUNCS["api.lookup"]))
    assert re.search(r"\bLIMIT\s+1\b", _strip_comments(FUNCS["api.quote_latest"]))


def test_panel_cap_applies_after_deterministic_order():
    body = _strip_comments(FUNCS["api.panel"])
    order = re.search(r"ORDER\s+BY\s+4\s*,\s*1\s*,\s*5", body)
    limit = re.search(rf"\bLIMIT\s+{PANEL_CAP}\b", body)
    assert order and limit and order.start() < limit.start(), (
        "api.panel must ORDER BY (date, id, metric) before its LIMIT so the cut is deterministic"
    )


# ---------------------------------------------------------------------------
# psql-cleanliness under ON_ERROR_STOP=1
# ---------------------------------------------------------------------------

def test_files_are_transactional_and_psql_clean():
    for path, sql in ((SQL19_PATH, SQL19), (SQL12_PATH, SQL12)):
        stripped = _strip_comments(sql)
        assert re.search(r"^\s*BEGIN\s*;", stripped, re.M), f"{path.name}: missing BEGIN"
        assert re.search(r"COMMIT\s*;\s*$", stripped.strip()), f"{path.name}: missing trailing COMMIT"
        # No psql backslash meta-commands (they would not be plain SQL).
        for line in sql.splitlines():
            assert not line.lstrip().startswith("\\"), f"{path.name}: psql meta-command {line!r}"
