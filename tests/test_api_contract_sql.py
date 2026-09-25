"""Offline assertions over the api-contract SQL (SERVING.md Steps 3 + 6).

No database: these tests parse the SQL text of 19_api_contract.sql and
12_grants_and_rls.sql and assert the privilege boundary and the in-SQL row
caps hold. They are deliberately regex-based (robust to reformatting), and
they strip comments before scanning for GRANT/REVOKE so prose never trips
them. A real apply is still Step 2's job (Silo `analytics-only` dispatch /
`api-smoke`) — substring tests are not proof the SQL runs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SQL19_PATH = ROOT / "src" / "store" / "analytical" / "19_api_contract.sql"
SQL12_PATH = ROOT / "src" / "store" / "analytical" / "12_grants_and_rls.sql"
SCHEMA_PATH = ROOT / "src" / "store" / "schema.sql"
MIG_OPTION_PATH = ROOT / "src" / "store" / "migrations" / "21_b3_cotahist_option_serve.sql"

SQL19 = SQL19_PATH.read_text(encoding="utf-8")
SQL12 = SQL12_PATH.read_text(encoding="utf-8")

# ONE page size everywhere: PostgREST db-max-rows, the SDK's SERVER_ROW_CAP,
# serve/app.py's _PAGE and catalog().limits.page.size. Since v26 NO function
# has a cap+1 sentinel: every one of them fetches PANEL_PAGE + 1 rows, sees the
# overflow, and REFUSES (22023) rather than trimming.
PANEL_PAGE = 1000

# Every set-returning function that refuses above one page, and how it behaves
# above it. The three `paged` ones take a p_after cursor; the rest ask the
# caller to narrow the window.
PAGED_FUNCTIONS = ("api.panel", "api.quote_history", "api.fund_nav")
RAISE_ONLY_FUNCTIONS = (
    "api.option_history",
    "api.termo_history",
    "api.financials",
    "api.company_financials",
    "api.income_statements",
    "api.balance_sheets",
    "api.cash_flow_statements",
    "api.anbima_classes",
    "api.inflation",
    "api.inflation_items",
    # v34 (plan 2e): until v33 these three trimmed SILENTLY at the tier
    # ceiling (500 / 5000). They now refuse like the rest; p_limit survives
    # as an explicit newest-first head, so their page CTE reads
    # LIMIT COALESCE(v_head, 1001) — see HEAD_PAGE below.
    "api.fidc_cedentes",
    "api.fidc_sacados",
    "api.fidc_portfolio",
    "api.fidc_tranches",
    "api.fidc_aging",
)
# The raise-only functions whose p_limit is an explicit head (1..1000) rather
# than a tier clamp. Without p_limit they fetch the page + 1 like every other.
HEAD_FUNCTIONS = ("api.fidc_cedentes", "api.fidc_sacados", "api.fidc_portfolio")
CAPPED_FUNCTIONS = PAGED_FUNCTIONS + RAISE_ONLY_FUNCTIONS

# The forensic screens (v31) live in 23_api_screens.sql, not in 19, so FUNCS
# (parsed from 19 alone) does not carry them; tests/test_api_screens_contract.py
# owns their bodies. They are raise-only: published in limits.page.all and
# limits.page.functions.raise_only beside the 19 functions.
SCREEN_FUNCTIONS = (
    "api.screen_zombie_growth",
    "api.screen_captive_vehicles",
    "api.screen_evergreen_aging",
    "api.screen_overdue_securit",
    "api.screen_dormant_funds",
    "api.screen_dormant_trend",
    "api.screen_delinquency_drivers",
    # v37: the filing-behaviour screens live in 25_api_filing_screens.sql
    # (tests/test_filing_screens_contract.py owns their bodies). Raise-only.
    "api.screen_restatements",
    "api.screen_late_filers",
    "api.screen_silent_filers",
)

# v38: held-but-unserved datasets in 26_api_events_macro.sql
# (tests/test_wave3_contract.py owns the bodies). Raise-only.
WAVE3_FUNCTIONS = (
    "api.company_events",
    "api.macro_series",
    "api.ptax",
)

# The FNET register (v33) lives in 24_api_fnet.sql, for the same reason: FUNCS
# does not carry it, tests/test_fnet_api_contract.py owns the bodies. Both are
# raise-only.
FNET_FUNCTIONS = (
    "api.fund_documents",
    "api.fund_restatements",
)

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
    "api.option_chain",
    "api.option_history",
    "api.option_exercises",
    "api.termo_history",
    "api.fund_profile",
    "api.fund_nav",
    "api.search_funds",
    "api.fund_holdings",
    "api.coverage",
    "api.panel",
    "api.lookup",
    "api.catalog",
    "api.financials",
    "api.company_financials",
    "api.income_statements",
    "api.balance_sheets",
    "api.cash_flow_statements",
    "api.anbima_classes",
    "api.fund_debentures",
    "api.metric_coverage",
    "api.fidc_cedentes",
    "api.fidc_sacados",
    "api.fidc_portfolio",
    "api.inflation",
    "api.inflation_items",
    "api.fidc_tranches",
    "api.fidc_aging",
}

# Internal helpers: called only from inside SECURITY DEFINER functions, which
# execute as the owner, so they need no client grant. Keeping them out of
# EXPECTED_FUNCTIONS is what makes "every public function is granted to anon"
# and "no internal helper is" two separate, checkable claims.
INTERNAL_FUNCTIONS = {
    "api.caller_tier",
    "api.assert_panel_ids",
    "api.assert_row_cap",
    "api.parse_panel_cursor",
    "api.parse_date_cursor",
    "api.assert_fund_nav_cursor",
    "api.assert_panel_universe",
    "api.company_ref",
    "api.cia_statement_rows",
    "api.inflation_registry",
}


def test_all_expected_api_functions_present():
    assert set(FUNCS) == EXPECTED_FUNCTIONS | INTERNAL_FUNCTIONS


def test_internal_helpers_are_never_granted_to_client_roles():
    """A client must not be able to call the tier helpers directly.

    api.caller_tier is harmless to read, but api.assert_panel_ids is the
    enforcement point for the anonymous id ceiling. Granting either to a
    client role would be a step toward making the limit negotiable by the
    caller it constrains.
    """
    grants = "\n".join(s for s in _statements(SQL19) if re.match(r"GRANT\b", s, re.I))
    for fn in sorted(INTERNAL_FUNCTIONS):
        assert not re.search(
            rf"GRANT\s+EXECUTE\s+ON\s+FUNCTION\s+{re.escape(fn)}", grants, re.I
        ), f"{fn} is internal and must not be granted to anon/authenticated"


def test_internal_helpers_are_revoked_from_public():
    revokes = "\n".join(s for s in _statements(SQL19) if re.match(r"REVOKE\b", s, re.I))
    for fn in sorted(INTERNAL_FUNCTIONS):
        assert re.search(
            rf"REVOKE\s+ALL\s+ON\s+FUNCTION\s+{re.escape(fn)}\s*\([^)]*\)\s+FROM\s+PUBLIC",
            revokes,
            re.I,
        ), f"{fn} must be revoked from PUBLIC"


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

# api.catalog() returns a jsonb constant and reads no relation at all, so it
# is the one deliberate SECURITY INVOKER: DEFINER would grant owner rights for
# nothing, and with no object references there is no search_path surface.
# test_constant_functions_read_nothing keeps that justification honest.
CONSTANT_FUNCTIONS = {"api.catalog"}


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


# Helpers that pin their OWN immutable search_path (verified below), so a
# caller with search_path = '' can invoke them safely without needing the
# 'public, pg_temp' pin itself. Everything else called under public.* still
# forces the caller into DELEGATING_FUNCTIONS.
SELF_PINNED_HELPERS = {"latest_complete_period"}


def test_self_pinned_helpers_actually_pin_their_search_path():
    sql04 = (ROOT / "src" / "store" / "analytical" / "04_fact_fund_monthly.sql").read_text(
        encoding="utf-8"
    )
    for helper in SELF_PINNED_HELPERS:
        m = re.search(
            rf"CREATE OR REPLACE FUNCTION {helper}\b.*?\$\$", sql04, re.S
        )
        assert m, f"{helper} not found in 04_fact_fund_monthly.sql"
        assert re.search(r"SET\s+search_path\s*=\s*public,\s*pg_temp", m.group(0)), (
            f"{helper} is on the SELF_PINNED_HELPERS allowlist but does not "
            "pin its own search_path — calling it from an api.* function "
            "with search_path = '' would fail at runtime"
        )


def test_delegating_set_matches_functions_that_call_public():
    # The two properties must move together: a function that calls a
    # public.* function needs the public pin; a self-contained one must keep
    # the empty pin. Derived from the bodies so the sets cannot drift.
    # Calls to SELF_PINNED_HELPERS don't count: those pin their own path.
    helper_call = re.compile(
        r"\bpublic\.(?:" + "|".join(sorted(SELF_PINNED_HELPERS)) + r")\s*\("
    )
    for name, chunk in FUNCS.items():
        body = re.split(r"\$\$", chunk, maxsplit=1)[-1]
        body = helper_call.sub("", body)
        calls_public = bool(re.search(r"\bpublic\.\w+\s*\(", body))
        assert calls_public == (name in DELEGATING_FUNCTIONS), (
            f"{name}: calls_public={calls_public} but "
            f"DELEGATING_FUNCTIONS says {name in DELEGATING_FUNCTIONS}"
        )


def test_constant_functions_read_nothing():
    # The INVOKER exemption is only honest while the body touches no relation:
    # the moment api.catalog() gains a FROM/JOIN it must become DEFINER with a
    # pinned search_path like every other function.
    for name in CONSTANT_FUNCTIONS:
        chunk = FUNCS[name]
        assert not re.search(r"\b(?:FROM|JOIN)\s+(?:public|api)\.", chunk, re.I), (
            f"{name} reads a relation; it can no longer stay SECURITY INVOKER"
        )
        assert not re.search(r"\bSECURITY\s+DEFINER\b", chunk, re.I)


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
    # Sole exemption: CONSTANT_FUNCTIONS, which read nothing (and
    # test_constant_functions_read_nothing keeps that claim honest).
    for name, chunk in FUNCS.items():
        if name in CONSTANT_FUNCTIONS:
            continue
        header = re.split(r"\$\$", chunk, maxsplit=1)[0]
        assert re.search(r"\bSECURITY\s+DEFINER\b", header, re.I), (
            f"{name} is not SECURITY DEFINER; see the Step 6 rationale in 19_api_contract.sql"
        )
        assert not re.search(r"\bSECURITY\s+INVOKER\b", header, re.I)


TYPED_CASH_VIEWS = {
    "api.equities": "equity",
    "api.bdrs": "bdr",
    "api.units": "unit",
    "api.fund_quotas": "fund_quota",
    "api.cash_securities": "cash_security",
}


@pytest.mark.parametrize("view,itype", sorted(TYPED_CASH_VIEWS.items()))
def test_typed_cash_view_filters_on_its_own_instrument_type(view, itype):
    # A view pointed at the wrong type would silently serve another instrument
    # class under this endpoint's name.
    body = _strip_comments(SQL19)
    chunk = body[body.index(f"CREATE OR REPLACE VIEW {view} AS"):]
    chunk = chunk[: chunk.index(";")]
    assert re.search(rf"instrument_type\s*=\s*'{itype}'", chunk), (
        f"{view} does not filter instrument_type = '{itype}'"
    )
    # Cash boards only: an option or termo row must never reach a cash endpoint.
    assert re.search(r"tpmerc\s+IN\s*\(\s*'010',\s*'020',\s*'021'\s*\)", chunk)


@pytest.mark.parametrize("view", sorted(TYPED_CASH_VIEWS))
def test_typed_cash_view_exposes_lot(view):
    # Odd lot outnumbers standard lot on equities, so a view that hides `lot`
    # invites silent double-counting of volume.
    body = _strip_comments(SQL19)
    chunk = body[body.index(f"CREATE OR REPLACE VIEW {view} AS"):]
    chunk = chunk[: chunk.index(";")]
    assert re.search(
        r"CASE\s+v\.tpmerc\s+WHEN\s+'010'\s+THEN\s+'standard'\s+ELSE\s+'odd'\s+END\s+AS\s+lot",
        chunk,
    ), f"{view} does not derive a lot column from tpmerc"


def test_api_quotes_stays_standard_lot_only():
    # The typed views are additive; api.quotes' published grain must not move.
    body = _strip_comments(SQL19)
    chunk = body[body.index("CREATE OR REPLACE VIEW api.quotes AS"):]
    chunk = chunk[: chunk.index(";")]
    assert re.search(r"WHERE\s+v\.tpmerc\s*=\s*'010'", chunk)
    assert "lot" not in chunk.split("FROM")[0]


def test_no_typed_history_functions_exist():
    # A codneg has exactly one instrument type, so a typed history would force
    # the caller to know the type before asking for a price. Deliberate.
    for stem in ("equity", "bdr", "unit", "fund_quota", "cash_security"):
        assert f"api.{stem}_history" not in FUNCS


def test_views_are_explicitly_owner_privileged():
    for view in ("api.quotes", "api.funds", *TYPED_CASH_VIEWS):
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
    # lookup's quotes arm aliases the typed subquery as t (q is the
    # escaped-query CTE since the step-5 hardening).
    assert "t.asset_class" in FUNCS["api.lookup"]
    assert "FROM api.quotes" in FUNCS["api.lookup"]


def test_typed_b3_surfaces_do_not_assume_equity_board_02():
    for name in ("api.panel", "api.lookup"):
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

@pytest.mark.parametrize("fn", CAPPED_FUNCTIONS)
def test_every_capped_function_fetches_one_page_plus_one_and_refuses(fn):
    """A result trimmed to fit looks exactly like a complete one.

    So no function returns a partial page: each fetches PANEL_PAGE + 1 rows,
    and api.assert_row_cap sees the extra row and raises 22023. The final
    LIMIT is the page itself, for the paging case.
    """
    body = _strip_comments(FUNCS[fn])
    page = body[body.index("page"):]
    # The explicit-head functions fetch COALESCE(v_head, 1001): the caller's
    # own p_limit (1..1000) when given, otherwise one page plus one.
    head = r"COALESCE\(v_head,\s*" if fn in HEAD_FUNCTIONS else ""
    assert re.search(rf"\bLIMIT\s+{head}{PANEL_PAGE + 1}\b", page), (
        f"{fn} must fetch page+1 rows to see the overflow"
    )
    assert re.search(rf"\bLIMIT\s+{PANEL_PAGE}\b", page), (
        f"{fn} must return at most one page"
    )
    name = fn.split(".", 1)[1]
    assert f"api.assert_row_cap((SELECT count(*) FROM page)" in page, (
        f"{fn} must count its own page and refuse over it"
    )
    assert f"'{name}')" in page, f"{fn} must name itself in the 22023"


@pytest.mark.parametrize("fn", CAPPED_FUNCTIONS)
def test_no_capped_function_keeps_the_unreachable_sentinel(fn):
    """5001 and 100001 were cap+1 sentinels the hosted API could never reach:
    PostgREST cut every response at 1000 rows first, so an oversized series
    came back as 1000 rows with a 200 and no signal at all. They are gone."""
    body = _strip_comments(FUNCS[fn])
    assert not re.search(r"\bLIMIT\s+5001\b", body), f"{fn} still has the 5001 sentinel"
    assert not re.search(r"\bLIMIT\s+100001\b", body), f"{fn} still has the 100001 sentinel"


def test_serve_page_size_is_the_server_page_size():
    """serve/ pages the SQL itself, so its page size must be the server's.
    _MAX_POINTS/_MAX_PANEL are the ADAPTER's own envelope ceilings — they stop
    its walk — and no longer stand in a cap+1 relation to anything in SQL."""
    app_py = (ROOT / "serve" / "app.py").read_text(encoding="utf-8")
    m_points = re.search(r"_MAX_POINTS\s*=\s*([\d_]+)", app_py)
    m_panel = re.search(r"_MAX_PANEL\s*=\s*([\d_]+)", app_py)
    m_page = re.search(r"_PAGE\s*=\s*([\d_]+)", app_py)
    assert m_points and m_panel and m_page, "serve/app.py no longer defines _MAX_POINTS/_MAX_PANEL/_PAGE"
    assert int(m_page.group(1)) == PANEL_PAGE
    assert int(m_panel.group(1).replace("_", "")) % PANEL_PAGE == 0


# ---------------------------------------------------------------------------
# The panel refuses instead of trimming (2026-09-15): one 1000-row page,
# 22023 above it unless p_after pages, a transparent cursor, and universe
# mode for signed-in callers. One page size everywhere.
# ---------------------------------------------------------------------------

def test_panel_returns_one_page_and_refuses_above_it():
    body = _strip_comments(FUNCS["api.panel"])
    page = body[body.index("page AS ("):]
    assert re.search(rf"\bLIMIT\s+{PANEL_PAGE + 1}\b", page), "the page CTE must fetch page+1 rows to see the overflow"
    assert re.search(rf"\bLIMIT\s+{PANEL_PAGE}\b\s*;", page), "the final select must return exactly one page"
    assert "api.assert_row_cap((SELECT count(*) FROM page), (SELECT paging FROM params), 'panel')" in page
    assert not re.search(r"\bLIMIT\s+100001\b", body), "the unreachable sentinel is gone"


def test_row_cap_helper_page_size_is_the_one_constant():
    helper = _strip_comments(FUNCS["api.assert_row_cap"])
    assert f"p_n > {PANEL_PAGE}" in helper
    assert "ERRCODE = '22023'" in helper
    from serve.catalog import catalog_payload
    from sdk.silo_client.client import SERVER_ROW_CAP
    limits = catalog_payload()["limits"]
    assert limits["page"]["size"] == PANEL_PAGE == SERVER_ROW_CAP == limits["rows_per_response"]["value"]
    # Every capped function is published, split by whether it hands back a
    # cursor or asks the caller to narrow.
    page = limits["page"]
    assert set(page["all"]) == {
        f.split(".", 1)[1]
        for f in CAPPED_FUNCTIONS + SCREEN_FUNCTIONS + FNET_FUNCTIONS + WAVE3_FUNCTIONS
    }
    assert set(page["functions"]["paged"]) == {f.split(".", 1)[1] for f in PAGED_FUNCTIONS}
    assert set(page["functions"]["raise_only"]) == {
        f.split(".", 1)[1]
        for f in RAISE_ONLY_FUNCTIONS + SCREEN_FUNCTIONS + FNET_FUNCTIONS + WAVE3_FUNCTIONS
    }



def test_row_cap_error_says_why_and_how():
    """"Error with error why" (v34): the refusal is all a caller sees, so the
    MESSAGE alone must carry the reason and the fix, and DETAIL / HINT carry
    them again for clients that read PostgREST's `details` / `hint`."""
    helper = _strip_comments(FUNCS["api.assert_row_cap"])
    # The phrase the SDK's SiloOverCap matches on must survive any rewording.
    assert "more than 1000 rows" in helper
    assert "SILO never returns a silently truncated result" in helper, "the WHY"
    assert "DETAIL  = v_why" in helper and "HINT    = v_how" in helper
    raise_at = helper[helper.index("RAISE EXCEPTION"):]
    assert "v_why, v_how" in raise_at, "the message itself must carry both halves"
    # The HOW is per function: a cursor for the three that page, a fund pin
    # and an explicit head for the FIDC trio, thresholds for the screens.
    for name in ("panel", "quote_history", "fund_nav"):
        assert f"p_fn = '{name}'" in helper
    assert "p_entity_type" in helper, "fund_nav paging requires a family; the hint must say so"
    assert "p_fn = 'fidc_cedentes'" in helper
    assert "('fidc_sacados', 'fidc_portfolio')" in helper
    assert "p_limit (1..1000)" in helper
    # p_cnpj and p_cedente are exclusive, so no FIDC hint may tell a caller
    # to "pin a fund" — a p_cedente caller cannot take that advice, and
    # sacados / portfolio already require p_cnpj.
    assert "pin a single fund" not in helper and "pin one fund" not in helper
    assert "left(p_fn, 7) = 'screen_'" in helper
    # A function with no cursor must never be told to page.
    fallback = helper[helper.index("ELSE\n"):]
    assert "p_after" not in fallback.split("END;")[0]


@pytest.mark.parametrize("fn", HEAD_FUNCTIONS)
def test_fidc_head_functions_take_p_limit_as_an_explicit_head(fn):
    """p_limit survives on the trio as the caller's own newest-first head:
    1..1000 is served as asked, NULL or above one page means the whole window
    (served whole or refused), and < 1 is refused — never clamped to 1."""
    body = _strip_comments(FUNCS[fn])
    name = fn.split(".", 1)[1]
    assert "v_head := CASE WHEN p_limit <= 1000 THEN p_limit END;" in body
    assert "IF p_limit IS NOT NULL AND p_limit < 1 THEN" in body
    assert "GREATEST(" not in body and "LEAST(" not in body, "nothing is clamped any more"
    assert f"api.assert_row_cap((SELECT count(*) FROM page), FALSE, '{name}')" in body


def test_panel_cursor_is_transparent_and_keyed_on_the_full_grain():
    body = _strip_comments(FUNCS["api.panel"])
    assert "api.parse_panel_cursor(p_after)" in body
    assert "(r.date, r.id, r.metric, COALESCE(r.asset_class, ''))" in body, (
        "the cursor must include asset_class: (id, date, metric) is not unique"
    )
    parser = _strip_comments(FUNCS["api.parse_panel_cursor"])
    assert "string_to_array(p_after, '|')" in parser
    assert "ERRCODE = '22023'" in parser
    from serve.catalog import catalog_payload
    published = catalog_payload()["limits"]["page"]["functions"]["paged"]["panel"]
    assert "date>|<id>|<metric>|<asset_class" in published, (
        "the panel cursor must be published in full: an agent builds it from "
        "the last row it received"
    )
    protocol = catalog_payload()["limits"]["page"]["cursor_protocol"]
    assert "'' = first page" in protocol and "null = whole result" in protocol


def test_panel_fund_arm_filters_entity_type_and_declares_the_grain():
    panel = FUNCS["api.panel"]
    fund_rows = panel[panel.index("fund_rows AS ("):panel.index(", ranked (")]
    assert "(p.entity_type IS NULL OR f.entity_type = p.entity_type)" in fund_rows
    from serve.catalog import catalog_payload, CONSTRAINTS
    assert "(id, asset_class, date, metric)" in catalog_payload()["defaults"]["panel"]["grain"]
    assert any(c.startswith("PANEL GRAIN IS (id, asset_class, date, metric)") for c in CONSTRAINTS)


def test_universe_mode_requires_a_family_and_a_signed_in_caller():
    gate = _strip_comments(FUNCS["api.assert_panel_universe"])
    assert "NOT IN ('fi', 'fidc', 'fii', 'fip', 'fiagro')" in gate
    assert "v_allowed = 0" in gate and "CASE api.caller_tier() WHEN 'authenticated' THEN 1 ELSE 0 END" in gate
    assert gate.count("ERRCODE = '22023'") >= 3
    body = _strip_comments(FUNCS["api.panel"])
    universe = body[body.index("universe AS ("):body.index("cnpjs AS (")]
    # filters on published values only: latest non-null NAV, count of the
    # first requested metric — no arithmetic, no rank.
    assert "ARRAY_AGG(f.vl_patrim_liq ORDER BY f.period DESC) FILTER (WHERE f.vl_patrim_liq IS NOT NULL))[1]" in universe
    assert "COUNT(CASE (SELECT metrics[1] FROM params)" in universe
    assert "public.latest_complete_period(f.entity_type)" in universe
    assert "SELECT u.cnpj FROM universe u" in body


def test_discovery_functions_stay_bounded():
    assert re.search(r"\bLIMIT\s+20\b", _strip_comments(FUNCS["api.lookup"]))
    assert re.search(r"\bLIMIT\s+1\b", _strip_comments(FUNCS["api.quote_latest"]))


def test_option_chain_clamps_its_page_limit():
    # 1..2000 — a chain-page cap, deliberately distinct from the 5001 series
    # cap (one prefix's chain on one session, not a time series).
    body = _strip_comments(FUNCS["api.option_chain"])
    # The ceiling is now per tier: 2000 signed in, 200 anonymous. The default
    # (100) is unchanged for both — that is a timeout budget, not a permission.
    assert re.search(r"GREATEST\(COALESCE\(p_limit,\s*100\),\s*1\)", body), (
        "api.option_chain lost its lower clamp / default of 100"
    )
    assert re.search(
        r"CASE\s+api\.caller_tier\(\)\s+WHEN\s+'authenticated'\s+THEN\s+2000\s+ELSE\s+200\s+END",
        body,
    ), "api.option_chain lost its per-tier page ceiling"


def test_option_chain_refuses_a_missing_or_short_prefix():
    # The required-prefix rule (INSTRUMENTS.md): an unfiltered whole-market
    # chain is exactly the query the caps exist to stop. The RAISE is the
    # PostgREST analogue of serve/'s 400.
    body = _strip_comments(FUNCS["api.option_chain"])
    assert re.search(r"length\(v_prefix\)\s*<\s*3", body)
    assert re.search(r"RAISE\s+EXCEPTION", body, re.I)
    assert re.search(r"requires\s+p_prefix", FUNCS["api.option_chain"], re.I)


def test_option_side_is_derived_only_from_tpmerc():
    # 'call'/'put' must come from the published tpmerc code, never from
    # codneg-name intuition.
    for fn in ("api.option_chain", "api.option_history"):
        body = _strip_comments(FUNCS[fn])
        assert re.search(
            r"CASE\s+b\.tpmerc\s+WHEN\s+'070'\s+THEN\s+'call'\s+WHEN\s+'080'\s+THEN\s+'put'",
            body,
            re.I,
        ), f"{fn}: side is not derived from tpmerc 070/080"


def test_no_underlying_column_is_served():
    # INSTRUMENTS.md: deriving an underlying from the codneg root would
    # synthesize an identity join (integrity rule 3).
    for fn in ("api.option_chain", "api.option_history", "api.termo_history"):
        # Only the declared output columns matter (the COMMENT ON FUNCTION
        # strings legitimately *say* there is no underlying column).
        header = re.split(r"\$\$", FUNCS[fn], maxsplit=1)[0]
        assert not re.search(r"\bunderlying\b", _strip_comments(header), re.I), (
            f"{fn} declares an underlying column; that mapping is not published by B3"
        )


def test_coverage_includes_the_derivatives_segment():
    body = _strip_comments(FUNCS["api.coverage"])
    assert re.search(r"'derivatives'", body)
    for code in ("070", "080", "030"):
        assert re.search(rf"tpmerc\s*=\s*'{code}'", body), (
            f"api.coverage lost the tpmerc {code} freshness probe"
        )


@pytest.mark.parametrize("fn", ["api.option_chain", "api.coverage"])
def test_latest_session_probes_avoid_an_in_list_max(fn):
    body = _strip_comments(FUNCS[fn])
    # Match the bad shape tightly — a max() whose OWN FROM/WHERE is the
    # b3_cotahist IN-list. A looser pattern spans unrelated arms of the same
    # statement (each arm does its own max(trade_date), and
    # its derivative arm separately filters tpmerc IN (...)) and cries wolf.
    assert not re.search(
        r"(?:max|MAX)\s*\(\s*(?:\w+\.)?trade_date\s*\)[^()]*?"
        r"FROM\s+public\.b3_cotahist(?:\s+\w+)?\s+"
        r"WHERE\s+(?:\w+\.)?tpmerc\s+IN\s*\(",
        body,
        re.I | re.S,
    ), (
        f"{fn} probes the latest session with an IN-list max over b3_cotahist; "
        "use GREATEST of per-tpmerc equality maxes so the index rewrite applies"
    )


def test_panel_has_option_and_termo_arms_with_derivative_class():
    body = _strip_comments(FUNCS["api.panel"])
    for id_type in ("option", "termo"):
        assert re.search(
            rf"'{id_type}',\s*'derivative'", body
        ), f"api.panel lost its {id_type} arm"
    # The derivative CTEs must stay disjoint from the vista arms by tpmerc.
    assert re.search(r"tpmerc\s+IN\s+\('070',\s*'080'\)", body)
    assert re.search(r"tpmerc\s*=\s*'030'", body)


def test_panel_normalises_fund_periods_to_first_of_month():
    """fact_fund_monthly mixes three period conventions; the panel must not.

    fi/fii/fiagro are first-of-month, fidc is month-END and fip is year-END.
    The equity arms stamp date_trunc('month', trade_date), so a raw f.period put
    a FIDC and an FI on different rows of the same month and their columns never
    co-occurred in a wide pivot.
    """
    body = _strip_comments(FUNCS["api.panel"])
    fund_arm = body[body.index("fund_rows AS ("):]
    fund_arm = fund_arm[: fund_arm.index(")\n")]
    assert re.search(
        r"date_trunc\(\s*'month'\s*,\s*f\.period\s*\)::date\s+AS\s+period",
        fund_arm,
    ), "api.panel emits a raw f.period; fidc/fip will not align with equity"


def test_panel_window_filter_uses_the_normalised_period():
    # Filtering the RAW period drops a month-end fidc row when p_to is the
    # first of that month — the newest month of every fidc panel. Since the
    # completeness clamp the upper bound has two regimes; both must stay
    # month-normalised where they compare against a caller date, and the
    # clamp branch compares raw-to-raw (same family convention) on purpose.
    body = _strip_comments(FUNCS["api.panel"])
    fund_arm = body[body.index("fund_rows AS ("):]
    fund_arm = fund_arm[: fund_arm.index(")\n")]
    where = fund_arm[fund_arm.index("WHERE"):]
    assert not re.search(r"\bAND\s+f\.period\s+BETWEEN", where), (
        "the window filter still compares the raw f.period"
    )
    assert re.search(
        r"date_trunc\(\s*'month'\s*,\s*f\.period\s*\)::date\s*>=\s*"
        r"date_trunc\(\s*'month'\s*,\s*p\.d0\s*\)::date",
        where,
    )
    assert re.search(
        r"date_trunc\(\s*'month'\s*,\s*f\.period\s*\)::date\s*\n?\s*"
        r"<=\s*date_trunc\(\s*'month'\s*,\s*p\.d1_explicit\s*\)::date",
        where,
    )


def test_panel_and_fund_nav_default_windows_clamp_to_complete_periods():
    # Directive: never serve an incomplete month by default. NULL p_to (the
    # default) must clamp fund rows per entity family; an explicit p_to is
    # the escape hatch and serves verbatim.
    panel = _strip_comments(FUNCS["api.panel"])
    assert re.search(r"p_to\s+DATE\s+DEFAULT\s+NULL", panel)
    assert "p.d1_explicit IS NULL" in panel
    assert (
        "f.period <= public.latest_complete_period(f.entity_type)" in panel
    )
    # Quote/option/termo arms keep CURRENT_DATE: session prints are complete.
    assert "COALESCE(p_to, CURRENT_DATE) AS d1" in panel

    nav = _strip_comments(FUNCS["api.fund_nav"])
    assert re.search(r"p_to\s+DATE\s+DEFAULT\s+NULL", nav)
    assert "s.period <= public.latest_complete_period(s.entity_type)" in nav
    assert "(p_to IS NOT NULL" in nav


def test_close_return_guards_adjacency_and_quotation_factor():
    panel = _strip_comments(FUNCS["api.panel"])
    ret = panel[panel.index("quote_ret AS ("):]
    ret = ret[: ret.index("option_month AS (")]
    assert (
        "lag(quotation_factor) OVER w IS DISTINCT FROM quotation_factor" in ret
    ), "a fatcot flip must NULL the return"
    assert "lag(obs_date) OVER w >= period - 7" in ret, (
        "a daily return needs the previous session within 7 calendar days"
    )


def test_coverage_reports_completeness_and_per_family_rows():
    cov = _strip_comments(FUNCS["api.coverage"])
    assert "complete_through" in FUNCS["api.coverage"]
    assert "public.latest_complete_period(NULL)" in cov
    assert "'funds_' || f.entity_type" in cov
    assert "public.latest_complete_period(f.entity_type)" in cov
    assert re.search(r"\bnotes\s+TEXT\b", cov), "coverage() must return a notes column"


# ---------------------------------------------------------------------------
# Applicability + regime breaks: the catalog says which fund_nav columns each
# family files, and 04_fact_fund_monthly.sql is the only place that is true.
# ---------------------------------------------------------------------------

FACT04_PATH = ROOT / "src" / "store" / "analytical" / "04_fact_fund_monthly.sql"

# fact_fund_monthly column -> api.fund_nav column
_FACT_TO_API = {
    "vl_patrim_liq": "nav",
    "vl_quota": "quota",
    "nr_cotst": "quotaholders",
    "vl_inadimpl": "delinquency",
    "pct_yield_mes": "monthly_yield",
    "captc_mes": "inflows",
    "resg_mes": "redemptions",
    "vl_ativo": "assets",
}


def _fact_arms_served_columns() -> dict[str, set[str]]:
    """Per family, the fund_nav columns its fact_fund_monthly arm actually
    fills: every mapped column minus the ones that arm sets `NULL::… AS`."""
    sql = _strip_comments(FACT04_PATH.read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for m in re.finditer(r"'(fi|fidc|fiagro|fii|fip)'\s+AS\s+entity_type", sql):
        fam = m.group(1)
        end = re.search(r"\bFROM\b", sql[m.end():]).start() + m.end()
        nulled = set(re.findall(r"NULL::\w+\s+AS\s+(\w+)", sql[m.end():end]))
        out[fam] = {api for col, api in _FACT_TO_API.items() if col not in nulled}
    return out


def test_catalog_applicability_matches_the_fact_table_arms():
    from serve.catalog import catalog_payload

    declared = catalog_payload()["applicability"]["fund_nav"]["columns_by_family"]
    arms = _fact_arms_served_columns()
    assert set(declared) == set(arms) == {"fi", "fidc", "fiagro", "fii", "fip"}
    for fam, served in arms.items():
        assert set(declared[fam]) == served, (
            f"{fam}: catalog applicability says {sorted(declared[fam])}, "
            f"04_fact_fund_monthly.sql serves {sorted(served)}"
        )


def test_fund_metric_asset_classes_follow_applicability():
    """A panel metric's asset_class list is exactly the families whose arm
    fills that column — the catalog must not offer quotaholders for a family
    whose arm sets nr_cotst NULL."""
    from serve.catalog import catalog_payload

    cat = catalog_payload()
    # Every applicability block pins some cnpj metrics to a source: fund_nav
    # to fact_fund_monthly's arms, fidc_concentration to the informe tabs of
    # migration 38. A cnpj metric must be named by exactly one of them.
    fam_cols: dict[str, set[str]] = {}
    for block in cat["applicability"].values():
        for fam, cols in block["columns_by_family"].items():
            fam_cols.setdefault(fam, set()).update(cols)
    rename = cat["applicability"]["fund_nav"]["panel_metric_names"]
    checked = 0
    for metric, spec in cat["metrics"].items():
        if spec["id_type"] != ["cnpj"]:
            continue
        col = next((k for k, v in rename.items() if v == metric), metric)
        expected = sorted(f for f, cols in fam_cols.items() if col in cols)
        assert expected, f"metrics.{metric} is pinned by no applicability block"
        assert sorted(spec["asset_class"]) == expected, (
            f"metrics.{metric}.asset_class = {spec['asset_class']}; "
            f"applicability serves it for {expected}"
        )
        checked += 1
    assert checked >= 7


def test_fidc_regime_break_is_in_catalog_and_on_the_coverage_row():
    from serve.catalog import catalog_payload

    breaks = catalog_payload()["regime_breaks"]
    fidc = [b for b in breaks if b["dataset"] == "funds_fidc" and b["column"] == "delinquency"]
    assert len(fidc) == 1 and fidc[0]["boundary"] == "2025-01-31"
    cov = _strip_comments(FUNCS["api.coverage"])
    assert "WHEN 'fidc'" in cov and "2025-01-31" in cov, (
        "the funds_fidc coverage row must carry the same boundary in notes"
    )


def test_lookup_escapes_like_and_ranks_before_the_limit():
    body = FUNCS["api.lookup"]
    stripped = _strip_comments(body)
    assert r"'\%'" in body and r"'\_'" in body, "LIKE metacharacters unescaped"
    assert "ESCAPE" in stripped
    # The rank must be computed and ordered on before LIMIT cuts to 20.
    assert stripped.index("ORDER BY h.rank") < stripped.index("LIMIT 20")


def test_panel_cap_applies_after_deterministic_order():
    body = _strip_comments(FUNCS["api.panel"])
    order = re.search(r"ORDER\s+BY\s+4\s*,\s*1\s*,\s*5\s*,\s*3", body)
    limit = re.search(rf"\bLIMIT\s+{PANEL_PAGE + 1}\b", body)
    assert order and limit and order.start() < limit.start(), (
        "api.panel must ORDER BY (date, id, metric, asset_class) before its page LIMIT so the page is deterministic"
    )


# ---------------------------------------------------------------------------
# Grants cover every function for every client role
# ---------------------------------------------------------------------------

def test_every_api_function_granted_to_anon_and_authenticated():
    grants = "\n".join(
        s for s in _statements(SQL19) if re.match(r"GRANT\b", s, re.I)
    )
    for fn in sorted(EXPECTED_FUNCTIONS):
        assert re.search(
            rf"GRANT\s+EXECUTE\s+ON\s+FUNCTION\s+{re.escape(fn)}\s*\([^)]*\)\s+TO\s+anon\s*,\s*authenticated",
            grants,
            re.I,
        ), f"missing GRANT EXECUTE ... {fn} TO anon, authenticated"


def test_every_api_function_revoked_from_public():
    revokes = "\n".join(
        s for s in _statements(SQL19) if re.match(r"REVOKE\b", s, re.I)
    )
    for fn in sorted(EXPECTED_FUNCTIONS):
        assert re.search(
            rf"REVOKE\s+ALL\s+ON\s+FUNCTION\s+{re.escape(fn)}\s*\([^)]*\)\s+FROM\s+PUBLIC",
            revokes,
            re.I,
        ), f"missing REVOKE ALL ... {fn} FROM PUBLIC"


# ---------------------------------------------------------------------------
# api.catalog() parity with serve/catalog.py (INSTRUMENTS.md: the SQL copy is
# pinned to catalog_payload(), same pattern as the caps-lockstep test)
# ---------------------------------------------------------------------------

def _embedded_catalog_json() -> str:
    chunk = FUNCS["api.catalog"]
    m = re.search(r"\$json\$(.*?)\$json\$", chunk, re.S)
    assert m, "api.catalog must embed its payload as one $json$...$json$ literal"
    return m.group(1)


def test_api_catalog_matches_serve_catalog_payload_exactly():
    from serve.catalog import catalog_payload

    embedded = json.loads(_embedded_catalog_json())
    assert embedded == catalog_payload(), (
        "api.catalog()'s jsonb literal drifted from serve.catalog.catalog_payload(). "
        "Regenerate the $json$ block in 19_api_contract.sql (command in its header "
        "comment) and bump CATALOG_VERSION."
    )


def test_catalog_limits_are_the_sql_tier_clamps():
    """The `limits` block is only worth publishing if it cannot lag the SQL.

    Every tiered ceiling is a `CASE api.caller_tier() WHEN 'authenticated'
    THEN <hi> ELSE <lo>` (or the panel's `v_max := CASE v_tier ...`); read them
    out of the function that owns each and compare number for number.
    """
    from serve.catalog import catalog_payload

    tiers = catalog_payload()["limits"]["tiers"]
    anon, auth = tiers["anon"], tiers["authenticated"]

    def clamp(fn):
        body = _strip_comments(FUNCS[fn])
        m = re.search(r"WHEN\s+'authenticated'\s+THEN\s+(\d+)\s+ELSE\s+(\d+)", body)
        assert m, f"{fn} has no tier CASE"
        return int(m.group(2)), int(m.group(1))

    # The panel ceiling lives in its id validator, not in api.panel itself.
    validator = "api.assert_panel_ids"
    assert clamp(validator) == (anon["panel_ids"], auth["panel_ids"])
    assert clamp("api.search_funds") == (anon["search_funds_rows"], auth["search_funds_rows"])
    assert clamp("api.option_chain") == (anon["option_chain_rows"], auth["option_chain_rows"])
    assert clamp("api.option_exercises") == (anon["option_exercises_rows"], auth["option_exercises_rows"])
    assert clamp("api.fund_holdings") == (anon["fund_holdings_rows"], auth["fund_holdings_rows"])
    assert clamp("api.fund_debentures") == (anon["fund_debentures_rows"], auth["fund_debentures_rows"])
    # v34: the FIDC concentration trio no longer trims at a tier ceiling, so
    # it has none to publish — and no tier CASE left in its body to lag one.
    for fn in HEAD_FUNCTIONS:
        name = fn.split(".", 1)[1]
        assert f"{name}_rows" not in anon and f"{name}_rows" not in auth, (
            f"{fn} is raise-only since v34; a published row ceiling would tell "
            "callers it still trims"
        )
        assert "caller_tier" not in _strip_comments(FUNCS[fn]), f"{fn} still branches on the tier"

    # Universe mode is a tier feature too: 0 anonymous, 1 signed in, read out
    # of the gate's COMMENT the same way.
    assert clamp("api.assert_panel_universe") == (int(anon["panel_universe"]), int(auth["panel_universe"]))

    limits = catalog_payload()["limits"]
    # v26: there is no sentinel block left to publish. Every function refuses
    # over the page instead of leaving a cap+1 row for the caller to count.
    assert "sql_sentinel" not in limits, (
        "the sentinels are gone; publishing one again would tell agents to "
        "detect truncation by a row count that PostgREST never lets them see"
    )
    assert limits["page"]["size"] == PANEL_PAGE
    assert limits["rows_per_response"]["value"] == 1000
    # The timeouts are Supabase's per-role defaults, stated in the SQL header.
    header = SQL19[:SQL19.index("CREATE OR REPLACE FUNCTION api.caller_tier")]
    assert "`anon` a 3s" in header and "`authenticated` 8s" in header
    assert (anon["statement_timeout_seconds"], auth["statement_timeout_seconds"]) == (3, 8)


def test_catalog_version_bumped_for_the_derivative_metrics():
    from serve.catalog import CATALOG_VERSION

    assert CATALOG_VERSION >= 3, (
        "adding option/termo id_types changed the catalog shape; "
        "CATALOG_VERSION must be bumped (INSTRUMENTS.md)"
    )
    assert json.loads(_embedded_catalog_json())["version"] == CATALOG_VERSION


# ---------------------------------------------------------------------------
# Migration 21 / schema.sql stay in sync on the option partial index
# ---------------------------------------------------------------------------

OPTION_INDEX_STMT = (
    "CREATE INDEX IF NOT EXISTS idx_b3_cotahist_option "
    "ON b3_cotahist (codneg, trade_date DESC) "
    "WHERE tpmerc IN ('070', '080')"
)


def test_option_partial_index_in_both_migration_and_schema():
    for path in (MIG_OPTION_PATH, SCHEMA_PATH):
        text = re.sub(
            r"\s+", " ", _strip_comments(path.read_text(encoding="utf-8"))
        )
        assert OPTION_INDEX_STMT in text, (
            f"{path.name} is missing the option partial index statement"
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


# ---------------------------------------------------------------------------
# Migration 23 serve surface: underlying mapping, exercises, auctions, classes
# ---------------------------------------------------------------------------


class TestOptionUnderlyingMapping:
    def test_underlying_join_is_published_isin_same_session(self):
        # The mapping is COTAHIST's own CODISI (an option row's ISIN is the
        # underlying's ISIN) joined to the SAME session's cash print. A join
        # without the trade_date equality would happily pair an option with a
        # cash row from another day — a fabricated as-of.
        for fn in ("api.option_chain", "api.option_history", "api.option_exercises"):
            body = FUNCS[fn]
            assert "c.isin = b.isin" in body, fn
            assert "c.trade_date = b.trade_date" in body, fn
            assert "c.tpmerc = '010'" in body, fn

    def test_underlying_join_is_deterministic_and_never_guesses(self):
        # LEFT JOIN LATERAL ... LIMIT 1 with a total ORDER BY: NULL when no
        # cash print exists (never a codneg-root guess), one deterministic
        # winner when (impossibly, today) several codnegs share an ISIN.
        for fn in ("api.option_chain", "api.option_history", "api.option_exercises"):
            body = FUNCS[fn]
            assert "LEFT JOIN LATERAL" in body, fn
            assert "ORDER BY (c.codbdi = '02') DESC, length(c.codneg), c.codneg" in body, fn

    def test_strike_points_decode_treats_zero_as_absent(self):
        # PTOEXE=0 is B3's filler for "not points-referenced"; serving it as a
        # 0-point strike would be a fabricated value.
        for fn in ("api.option_chain", "api.option_history"):
            assert "NULLIF((b.raw ->> 'ptoexe')::NUMERIC, 0) / 1e6" in FUNCS[fn], fn


class TestExerciseAndAuctionEvents:
    def test_option_exercises_requires_prefix_and_is_capped(self):
        body = FUNCS["api.option_exercises"]
        assert "length(v_prefix) < 3" in body
        assert "RAISE EXCEPTION" in body
        assert "LIMIT 5001" in body
        assert "IN ('012', '013')" in body

    def test_exercises_and_auctions_never_reach_the_quote_labels(self):
        # tpmerc 012/013/017 must not leak into the option quote endpoints.
        for fn in ("api.option_chain", "api.option_history"):
            body = FUNCS[fn]
            assert "'012'" not in body.replace("('012', '013')", "")
            assert "b.tpmerc IN ('070', '080')" in body

    def test_auctions_view_is_definer_granted_and_typed(self):
        assert "CREATE OR REPLACE VIEW api.auctions" in SQL19
        assert "v.instrument_type = 'auction'" in SQL19
        assert "ALTER VIEW api.auctions SET (security_invoker = false)" in SQL19
        assert "GRANT SELECT ON api.auctions TO anon, authenticated" in SQL19
        assert "GRANT SELECT ON api.auctions TO silo_api" in SQL19


class TestTypedCashTrailingColumns:
    def test_equities_share_class_columns_are_trailing(self):
        # CREATE OR REPLACE VIEW can only append columns; share_class and
        # governance_segment must come after fetched_at, in this order.
        view = SQL19.split("CREATE OR REPLACE VIEW api.equities AS")[1].split(
            "COMMENT ON VIEW"
        )[0]
        assert view.index("v.fetched_at") < view.index("v.share_class")
        assert view.index("v.share_class") < view.index("v.governance_segment")

    def test_fund_quotas_fund_type_is_trailing_and_from_subtype(self):
        view = SQL19.split("CREATE OR REPLACE VIEW api.fund_quotas AS")[1].split(
            "COMMENT ON VIEW"
        )[0]
        assert view.index("v.fetched_at") < view.index(
            "v.instrument_subtype AS fund_type"
        )
        # The view still filters on the unchanged parent label.
        assert "v.instrument_type = 'fund_quota'" in view


# ---------------------------------------------------------------------------
# close_unit: division by a PUBLISHED field, never an adjustment
# ---------------------------------------------------------------------------

_TYPED_CASH_VIEWS = [
    "api.quotes",
    "api.equities",
    "api.bdrs",
    "api.units",
    "api.fund_quotas",
    "api.cash_securities",
]


def test_every_cash_view_exposes_close_unit_as_a_trailing_column():
    # Trailing, because CREATE OR REPLACE VIEW can only APPEND columns: a
    # close_unit inserted mid-list would fail to deploy over the live view.
    for view in _TYPED_CASH_VIEWS:
        i = SQL19.index(f"CREATE OR REPLACE VIEW {view} AS")
        body = SQL19[i : SQL19.index("FROM public.vw_b3_instrument_typed v", i)]
        assert "AS close_unit" in body, f"{view} is missing close_unit"
        last_col = [
            ln.strip() for ln in body.splitlines() if ln.strip() and not ln.strip().startswith("--")
        ][-1]
        assert last_col.endswith("AS close_unit"), (
            f"{view}: close_unit must be the LAST column (CREATE OR REPLACE VIEW "
            f"can only append), found trailing {last_col!r}"
        )


def test_close_unit_divides_the_published_factor_and_guards_zero():
    for view in _TYPED_CASH_VIEWS:
        i = SQL19.index(f"CREATE OR REPLACE VIEW {view} AS")
        body = SQL19[i : SQL19.index("FROM public.vw_b3_instrument_typed v", i)]
        assert "v.preco_fechamento / NULLIF(v.fator_cotacao, 0) AS close_unit" in body, (
            f"{view}: close_unit must be close / NULLIF(factor,0) — both columns "
            "published by COTAHIST. Anything else would be an inferred adjustment."
        )


def test_close_unit_never_claims_to_be_corporate_action_adjusted():
    # `adjusted` stays FALSE everywhere until an event-sourced adjustment lands.
    assert "TRUE                AS adjusted" not in SQL19
    assert SQL19.count("FALSE               AS adjusted") >= len(_TYPED_CASH_VIEWS)


def test_panel_serves_close_unit_as_its_own_metric():
    panel = FUNCS["api.panel"]
    assert "'close_unit' = ANY (p.metrics)" in panel
    assert "'close_unit', q.close_unit" in panel
    # close stays raw: the new metric must not have rewritten the old one.
    assert "'close'::text, q.close," in panel


def test_close_unit_is_in_the_catalog_metric_map():
    from serve.catalog import METRICS

    assert "close_unit" in METRICS
    assert METRICS["close_unit"]["source"] == "b3_cotahist"
    assert METRICS["close_unit"].get("derived") is True


# ---------------------------------------------------------------------------
# The privilege sweep (SERVING.md Step 6).
#
# The revoke used to be a hand-written list of 19 tables, and an allowlist of
# revokes cannot track an append-only schema. Production on 2026-08-28 still
# had anon holding SELECT on 77 objects in `public` — every b3_cotahist_* and
# cvm_fi_diario_* partition (the list revokes only the parent, and partitions
# carry their own ACLs), all of cia_account, cvm_fi_balancete, the cia_*
# tables — and `Accept-Profile: public` made them readable over PostgREST with
# the publishable key.
# ---------------------------------------------------------------------------


def test_privilege_sweep_revokes_every_public_object_this_repo_owns():
    body = _strip_comments(SQL12)
    assert "REVOKE ALL ON %s FROM anon, authenticated" in body, (
        "12_grants_and_rls.sql must sweep, not enumerate: a per-table revoke list "
        "silently misses every dataset and partition added after it was written"
    )
    assert "nspname = 'public'" in body
    # The RLS arm still exists so the other application's tables stay out of
    # scope, but it can no longer be the ONLY thing that decides.
    assert "NOT c.relrowsecurity" in body
    assert "c.relname ~ " in body, (
        "the sweep must also match this repo's own objects by name: RLS was "
        "enabled on our landing tables on 2026-08-29 and a bare "
        "`NOT relrowsecurity` then stopped revoking them entirely"
    )


def test_sweep_name_pattern_covers_every_object_this_repo_declares():
    """The prefix list is load-bearing, so prove it against the real schema.

    If someone adds a dataset under a new naming family and forgets the
    pattern, the sweep silently stops covering it — exactly the failure this
    whole predicate exists to prevent. Catch it here, offline.
    """
    import re

    body = _strip_comments(SQL12)
    m = re.search(r"c\.relname ~ '(\^\([^']+\))'", body)
    assert m, "could not find the sweep's name pattern"
    pattern = re.compile(m.group(1))
    extra = set(re.findall(r"c\.relname = '([a-z0-9_]+)'", body))

    declared = set()
    roots = [ROOT / "src" / "store"]
    for base in roots:
        for path in list(base.glob("*.sql")) + list(base.glob("migrations/*.sql")) + list(
            base.glob("analytical/*.sql")
        ):
            for name in re.findall(
                r"^CREATE (?:TABLE|MATERIALIZED VIEW|OR REPLACE VIEW|VIEW)"
                r"(?:\s+IF NOT EXISTS)?\s+([a-z0-9_.]+)",
                path.read_text(),
                re.MULTILINE,
            ):
                # Schema-qualified objects (api.quotes) are out of the sweep's
                # scope by construction — it only walks nspname = 'public'.
                if "." not in name:
                    declared.add(name)

    assert declared, "found no declared public objects — the parser broke, not the SQL"
    missed = sorted(n for n in declared if not pattern.match(n) and n not in extra)
    assert not missed, (
        "these public objects are declared by this repo but the sweep's name "
        f"pattern does not match them, so they would keep any anon GRANT: {missed}"
    )


def test_sweep_precedes_the_grants_it_must_not_undo():
    body = _strip_comments(SQL12)
    sweep = body.index("REVOKE ALL ON %s FROM anon, authenticated")
    first_grant = body.index("GRANT SELECT ON fact_fund_monthly")
    assert sweep < first_grant, (
        "the sweep must run before the explicit GRANTs, or it revokes the client "
        "surface this file exists to define"
    )


def test_sweep_does_not_touch_the_other_application_tables():
    """The Edge-Functions app's tables stay out of scope.

    They are RLS-enabled and carry none of this repo's naming prefixes, so
    neither arm of the sweep predicate selects them. Stripping `authenticated`
    from them would break an app whose privilege needs this repo cannot see.
    """
    body = _strip_comments(SQL12)
    assert "ON ALL TABLES IN SCHEMA public FROM anon" not in body
    assert "ALTER DEFAULT PRIVILEGES" not in body


def test_partitioned_and_view_relkinds_are_in_scope():
    # 'p' partitioned parents, 'r' the partitions themselves, 'v'/'m' the views
    # and matviews built over the tape — the 2026-08-28 exposure was mostly
    # partitions, which a parent-only REVOKE never reaches.
    body = _strip_comments(SQL12)
    assert "relkind IN ('r', 'p', 'v', 'm', 'f')" in body


# ---------------------------------------------------------------------------
# Price is the default; everything else is opt-in.
#
# panel already defaulted to close+nav, but nothing in the contract SAID so, and
# an agent that cannot see a default asks for every metric it can enumerate — a
# price lookup becomes seven columns of fund accounting it never reads. The
# wide endpoints are the honest exception: a SQL function's RETURNS TABLE is
# fixed, so they are narrowed with PostgREST ?select= instead.
# ---------------------------------------------------------------------------


def test_panel_still_defaults_to_price():
    panel = FUNCS["api.panel"]
    assert "p_metrics TEXT[] DEFAULT ARRAY['close', 'nav']::TEXT[]" in panel
    # and the COALESCE fallback inside params must agree with the signature,
    # or an explicit NULL would widen what the signature narrows.
    assert "COALESCE(p_metrics, ARRAY['close','nav']::TEXT[])" in panel


def test_catalog_declares_the_default_machine_readably():
    from serve.catalog import catalog_payload

    d = catalog_payload()["defaults"]
    assert d["panel"]["metrics"] == ["close", "nav"]
    assert "opt-in" in d["principle"]
    # The escape hatch must be named, not implied: an agent told only "these are
    # the defaults" has no documented way to get the other columns back.
    assert "p_metrics" in d["panel"]["to_widen"]
    assert "select=" in d["wide_endpoints"]["to_narrow"]


def test_catalog_default_matches_the_sql_signature():
    """The declared default and the actual SQL default cannot drift apart."""
    from serve.catalog import catalog_payload

    declared = catalog_payload()["defaults"]["panel"]["metrics"]
    panel = FUNCS["api.panel"]
    m = re.search(r"p_metrics TEXT\[\] DEFAULT ARRAY\[(.*?)\]::TEXT\[\]", panel)
    assert m, "could not read p_metrics default out of api.panel"
    actual = [x.strip().strip("'") for x in m.group(1).split(",")]
    assert actual == declared, f"catalog says {declared}, SQL says {actual}"


# ---------------------------------------------------------------------------
# The row cap an agent must actually defend against.
#
# An independent audit of the live deployment (2026-08-27) found panel returning
# exactly 1000 rows spanning 2019-01-02..2023-01-09 for a request covering
# 2019..2026 — a 200, the OLDEST rows kept, and nothing in the body saying so.
# Reproduced against production 2026-08-28. The cause is PostgREST db-max-rows,
# not the SQL cap+1 sentinel this catalog used to tell agents to check: behind a
# 1000-row ceiling a count of 100001 can never occur.
#
# Content-Range is the only signal, and Range paging does NOT work on RPC
# (Range: 1000-1999 returns 0-999/1906 again — verified).
# ---------------------------------------------------------------------------


def _cap_constraint() -> str:
    from serve.catalog import CONSTRAINTS

    hits = [c for c in CONSTRAINTS if "Row caps" in c]
    assert len(hits) == 1, "expected exactly one row-cap constraint"
    return hits[0]


def test_cap_constraint_names_the_binding_cap_and_the_only_signal():
    c = _cap_constraint()
    assert "1000" in c, "the binding cap is 1000 rows (PostgREST db-max-rows)"
    assert "Content-Range" in c, "Content-Range is the only truncation signal"
    assert "OLDEST" in c, "which end is kept is the reason truncation is invisible"


def test_cap_constraint_says_every_function_refuses_and_which_ones_page():
    c = _cap_constraint()
    # The sentinels are gone, so the constraint no longer explains how to read
    # one. What it must carry now is which functions page and which do not —
    # getting THAT wrong is how a caller ends up narrowing a window they could
    # have walked, or walking one that has no cursor.
    assert "GONE" in c, "say plainly that the sentinels are gone"
    for name in ("panel", "quote_history", "fund_nav"):
        assert name in c, f"{name} pages; the constraint must say so"
    assert "p_entity_type" in c, (
        "fund_nav's cursor is a bare period: paging it without a family would "
        "skip or repeat a row at a page edge, so the requirement is part of "
        "the contract, not an implementation detail"
    )
    # The count moves with the surface: eleven at v30 (inflation,
    # inflation_items), eighteen at v31 (the seven screen_* functions), twenty
    # since v32 (fidc_tranches, fidc_aging), twenty-two since v33
    # (fund_documents, fund_restatements), twenty-five since v34
    # (fidc_cedentes, fidc_sacados, fidc_portfolio stopped trimming),
    # twenty-seven since v35 (balance_sheets, cash_flow_statements), thirty since
    # v37 (the three filing-behaviour screens), thirty-three since v38
    # (company_events, macro_series, ptax). The
    # prose said "eight" for two versions while listing nine — pin the word
    # to the tuples so it cannot drift again.
    assert "thirty-three" in c.lower().split(), "all thirty-three capped functions refuse"
    assert (
        len(CAPPED_FUNCTIONS) + len(SCREEN_FUNCTIONS) + len(FNET_FUNCTIONS)
        + len(WAVE3_FUNCTIONS)
    ) == 33
    for fn in WAVE3_FUNCTIONS:
        assert fn.split(".", 1)[1] in c, f"the cap constraint must name {fn}"
    for fn in HEAD_FUNCTIONS:
        assert fn.split(".", 1)[1] in c, f"the cap constraint must name {fn}"
    for fn in FNET_FUNCTIONS:
        assert fn.split(".", 1)[1] in c, f"the cap constraint must name {fn}"


def test_cap_constraint_warns_that_rpc_paging_does_not_work():
    c = _cap_constraint()
    assert "RANGE PAGING DOES NOT WORK ON RPC" in c, (
        "telling an agent to page an RPC would hand it page 1 twice and call it page 2"
    )


def test_agent_instructions_point_at_the_header():
    from serve.catalog import AGENT_INSTRUCTIONS

    assert "Content-Range" in AGENT_INSTRUCTIONS




# ---------------------------------------------------------------------------
# api.fund_holdings — the fund → ticker edge. cvm_fi_cda_acoes has carried the
# published B3 ticker since 2005 and nothing served it, so the one join between
# the fund universe and the quote tape existed only as rows in a landing table
# no caller can read.
# ---------------------------------------------------------------------------

def test_fund_holdings_is_published_and_granted():
    sql = SQL19
    assert "CREATE OR REPLACE FUNCTION api.fund_holdings" in sql
    assert "GRANT EXECUTE ON FUNCTION api.fund_holdings" in sql
    assert "REVOKE ALL ON FUNCTION api.fund_holdings" in sql, (
        "every api function revokes from PUBLIC before granting to the two roles"
    )


def test_fund_holdings_demands_exactly_one_identifier():
    """Neither is an unbounded scan of every fund; both is ambiguous.

    Both must be errors, not silently narrowed queries — an unbounded holdings
    scan would be the slowest query on the API and would time out rather than
    say why.
    """
    sql = SQL19
    body = sql[sql.index("FUNCTION api.fund_holdings"):]
    body = body[: body.index("$fn$;")]
    assert "(v_cnpj IS NULL) = (v_ticker IS NULL)" in body
    assert "22023" in body, "argument errors use the house SQLSTATE"


def test_fund_holdings_is_tier_aware():
    """Same pattern as every other row-capped function."""
    sql = SQL19
    body = sql[sql.index("FUNCTION api.fund_holdings"):]
    body = body[: body.index("$fn$;")]
    assert "api.caller_tier()" in body
    assert "5000" in body and "500" in body, "authenticated 5000 / anon 500"


def test_fund_holdings_pins_search_path():
    """SECURITY DEFINER without a pinned search_path is the classic hole."""
    sql = SQL19
    head = sql[sql.index("FUNCTION api.fund_holdings"):]
    head = head[: head.index("AS $fn$")]
    assert "SECURITY DEFINER" in head
    assert "SET search_path = ''" in head


def test_catalog_version_moved_with_the_surface():
    """A new endpoint that does not bump the catalog is invisible to agents."""
    import re
    from pathlib import Path

    sql_v = int(re.search(r'"version":\s*(\d+)', SQL19).group(1))
    py = (Path(__file__).resolve().parents[1] / "serve/catalog.py").read_text()
    py_v = int(re.search(r"CATALOG_VERSION = (\d+)", py).group(1))
    assert sql_v == py_v, f"catalog version drift: SQL {sql_v} vs serve {py_v}"
    assert sql_v >= 17, "fund_holdings shipped at v17"


# ---------------------------------------------------------------------------
# v26 — the series functions page, and coverage stops claiming the future
# ---------------------------------------------------------------------------

SQL04 = (ROOT / "src" / "store" / "analytical" / "04_fact_fund_monthly.sql").read_text(encoding="utf-8")
SQL08 = (ROOT / "src" / "store" / "analytical" / "08_cron_schedules.sql").read_text(encoding="utf-8")


@pytest.mark.parametrize("fn", PAGED_FUNCTIONS)
def test_paged_functions_take_a_cursor_and_the_others_do_not(fn):
    body = _strip_comments(FUNCS[fn])
    assert "p_after" in body, f"{fn} is published as paged but takes no cursor"


@pytest.mark.parametrize("fn", RAISE_ONLY_FUNCTIONS)
def test_raise_only_functions_have_no_cursor(fn):
    """Publishing a cursor these functions do not implement would send an
    agent round a loop that never advances."""
    body = _strip_comments(FUNCS[fn])
    assert "p_after" not in body, f"{fn} is published as raise-only but takes a cursor"


def test_the_date_cursor_is_shared_by_exactly_the_two_series_functions():
    parser = _strip_comments(FUNCS["api.parse_date_cursor"])
    assert r"^\d{4}-\d{2}-\d{2}$" in parser, "the cursor is a plain ISO date"
    assert "ERRCODE = '22023'" in parser, "a malformed cursor must raise, not be ignored"
    # p_fn is passed so the error names the function the agent actually called.
    assert "p_fn" in parser
    for fn in ("api.quote_history", "api.fund_nav"):
        body = _strip_comments(FUNCS[fn])
        name = fn.split(".", 1)[1]
        assert f"api.parse_date_cursor(p_after, '{name}')" in body


def test_fund_nav_paging_requires_a_family():
    """The cursor is a bare period, and a period is unique only WITHIN one
    family — 385 CNPJs file under two (fi + fidc) in the same month. Paging a
    two-family result on a bare date would skip or repeat a row at a page
    edge, so the server refuses rather than answering wrongly."""
    guard = _strip_comments(FUNCS["api.assert_fund_nav_cursor"])
    assert "ERRCODE = '22023'" in guard
    assert "p_entity_type" in guard
    nav = _strip_comments(FUNCS["api.fund_nav"])
    assert "api.assert_fund_nav_cursor(c.paging, p_entity_type)" in nav, (
        "the guard must ride the cursor parse, so it fires before any row is read"
    )
    # And the contract says so, in the copy an agent actually reads.
    from serve.catalog import catalog_payload
    published = catalog_payload()["limits"]["page"]["functions"]["paged"]["fund_nav"]
    assert "p_entity_type" in published


def test_fund_nav_publishes_the_panel_month_beside_the_filed_month():
    """period is CVM's filed month-END date; api.panel keys fund rows on the
    first of the month. Serving both means a caller joining the two does not
    have to rediscover the difference."""
    nav = _strip_comments(FUNCS["api.fund_nav"])
    assert "period_month" in nav
    assert "date_trunc('month', r.period)::date" in nav


def test_coverage_separates_elapsed_from_filed_and_from_landed():
    cov = _strip_comments(FUNCS["api.coverage"])
    assert "newest_period    DATE" in cov and "landed_at        TIMESTAMPTZ" in cov
    # as_of is bounded by today on every arm that can carry a forward-dated
    # key. FIP files annually keyed to 31-December, so on 2026-09-16 the
    # blended MAX read 2026-12-31 and an agent read it as freshness.
    assert cov.count("FILTER (WHERE") >= 4, (
        "every period arm must bound as_of by CURRENT_DATE"
    )
    assert "<= CURRENT_DATE" in cov


def test_coverage_serves_the_git_sha_of_the_landed_run():
    """v34 lineage: landed_git_sha is the commit of the SAME run that sets
    landed_at — taken off the newest finished row, not the newest non-null
    sha, so a NULL (pre-lineage or local run) is served as NULL rather than
    borrowed from an older run whose code did not produce the newest data."""
    cov = _strip_comments(FUNCS["api.coverage"])
    assert "landed_git_sha   TEXT" in cov
    head = cov[:cov.index("LANGUAGE sql")]
    assert head.index("landed_git_sha") > head.index("landed_at        TIMESTAMPTZ"), (
        "landed_git_sha is appended after landed_at so positional readers keep working"
    )
    landed = cov[cov.index("WITH landed AS ("):cov.index("base AS (")]
    arms = landed.count("MAX(l.finished_at)")
    picks = landed.count("(array_agg(l.git_sha ORDER BY l.finished_at DESC, l.id DESC))[1]")
    assert arms == picks >= 7, "every landed arm must carry the sha of its own newest run"
    assert "git_sha IS NOT NULL" not in landed, "a NULL sha is served as NULL, never skipped past"
    assert "l.landed_git_sha" in cov[cov.index("FROM base b") - 200:]


def test_landed_at_reads_only_successful_finished_runs():
    """A later FAILED run must not advance the date — that would report a
    failure as freshness — and a run still in flight has not landed."""
    cov = _strip_comments(FUNCS["api.coverage"])
    landed = cov[cov.index("WITH landed AS ("):cov.index("base AS (")]
    assert "l.status = 'ok'" in landed
    assert "l.finished_at IS NOT NULL" in landed
    assert "MAX(l.finished_at)" in landed


def test_the_fip_row_explains_why_its_newest_period_runs_ahead():
    cov = FUNCS["api.coverage"]
    assert "WHEN 'fip' THEN" in cov
    fip = cov[cov.index("WHEN 'fip' THEN"):].lower()
    assert "never read newest_period as freshness" in fip, (
        "the funds_fip row is exactly where as_of and newest_period diverge, "
        "so it must say which one is freshness"
    )


def test_metric_coverage_is_measured_not_declared():
    """An absent (family, metric) pair means the family never files it. The
    HAVING is what makes that true: a pair with no filed value anywhere is
    omitted rather than listed with null dates that read as a gap."""
    assert "CREATE MATERIALIZED VIEW mv_metric_coverage AS" in SQL04
    mv = SQL04[SQL04.index("CREATE MATERIALIZED VIEW mv_metric_coverage AS"):]
    mv = mv[:mv.index("COMMENT ON MATERIALIZED VIEW mv_metric_coverage")]
    assert "HAVING COUNT(*) FILTER (WHERE m.value IS NOT NULL) > 0" in mv
    assert "CREATE UNIQUE INDEX ix_metric_coverage_pk" in mv, (
        "a unique index is what lets the daily refresh run CONCURRENTLY"
    )
    fn = _strip_comments(FUNCS["api.metric_coverage"])
    assert "public.mv_metric_coverage" in fn


def test_metric_coverage_is_refreshed_and_granted():
    assert "REFRESH MATERIALIZED VIEW CONCURRENTLY mv_metric_coverage" in SQL08
    assert "'refresh-metric-coverage'" in SQL08
    assert re.search(
        r"GRANT\s+SELECT\s+ON\s+mv_metric_coverage\s+TO\s+anon,\s*authenticated", SQL12
    ), "the function is DEFINER, but the matview still needs its own grant line"


def test_fund_metrics_point_at_the_measured_coverage_not_a_written_date():
    """Only one `since` is stated as a constant — the FIDC regime break, which
    is a published boundary with its own lockstep test. Every other span is
    measured, so the catalog points at the function instead of carrying a date
    that can drift silently."""
    from serve.catalog import METRICS, catalog_payload

    # Scope: mv_metric_coverage reads fact_fund_monthly, so it measures exactly
    # the fund_nav metrics. The fidc_concentration metrics (receivables,
    # sacado_top1, sacado_top25) come from the FIDC informe tabs, NOT from the
    # fact table, so pointing them here would be a claim this function cannot
    # back — their spans live in applicability.fidc_concentration.starts.
    applic = catalog_payload()["applicability"]["fund_nav"]
    rename = applic["panel_metric_names"]
    # `assets` is a fund_nav column with no panel metric of its own, so
    # intersect with METRICS rather than assuming the two lists coincide.
    fund_metrics = sorted({
        rename.get(col, col)
        for cols in applic["columns_by_family"].values()
        for col in cols
    } & set(METRICS))
    assert fund_metrics, "expected fund metrics in the catalog"
    assert all(METRICS[m].get("id_type") == ["cnpj"] for m in fund_metrics)
    with_since = [m for m in fund_metrics if "since" in METRICS[m]]
    assert with_since == ["delinquency"], (
        "a hardcoded `since` is a claim nobody re-measures; only the published "
        f"regime break earns one, got {with_since}"
    )
    assert METRICS["delinquency"]["since"] == {"fidc": "2025-01-31"}
    for m in fund_metrics:
        assert METRICS[m].get("coverage") == "api.metric_coverage()", m
