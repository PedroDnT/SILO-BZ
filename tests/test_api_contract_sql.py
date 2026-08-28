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
    "api.option_chain",
    "api.option_history",
    "api.option_exercises",
    "api.termo_history",
    "api.fund_profile",
    "api.fund_nav",
    "api.search_funds",
    "api.coverage",
    "api.panel",
    "api.universe",
    "api.lookup",
    "api.catalog",
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
    assert "q.asset_class" in FUNCS["api.universe"]
    # lookup's quotes arm aliases the typed subquery as t (q is the
    # escaped-query CTE since the step-5 hardening).
    assert "t.asset_class" in FUNCS["api.lookup"]
    assert "FROM api.quotes" in FUNCS["api.lookup"]


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
        ("api.option_history", SERIES_CAP),
        ("api.termo_history", SERIES_CAP),
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


def test_option_chain_clamps_its_page_limit():
    # 1..2000 — a chain-page cap, deliberately distinct from the 5001 series
    # cap (one prefix's chain on one session, not a time series).
    body = _strip_comments(FUNCS["api.option_chain"])
    assert re.search(
        r"LIMIT\s+LEAST\(GREATEST\(COALESCE\(p_limit,\s*500\),\s*1\),\s*2000\)", body
    ), "api.option_chain lost its 1..2000 clamp"


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


def test_universe_supports_option_and_termo_classes():
    body = _strip_comments(FUNCS["api.universe"])
    assert re.search(r"p_asset_class\s*=\s*'option'", body)
    assert re.search(r"p_asset_class\s*=\s*'termo'", body)
    assert re.search(r"'derivative'", body)


def test_universe_derivative_branches_are_scoped_to_the_latest_session():
    # Aggregating every option row ever landed is a seq scan over ~89% of
    # b3_cotahist — a full-table GROUP BY there already times out in
    # production. Both derivative branches must pin trade_date to their own
    # segment's newest session (which is also the honest answer: expired
    # series are not "the universe").
    body = _strip_comments(FUNCS["api.universe"])
    derivative_part = body[body.index("'option'"):]
    assert derivative_part.count("b.trade_date = ") == 2, (
        "a universe derivative branch lost its latest-session scope"
    )


# The MIN/MAX -> index-scan rewrite only fires under a plain equality qual, so
# `max(trade_date) WHERE tpmerc IN (...)` plans as a seq scan over the option
# segment. Every latest-session probe must therefore be per-tpmerc equality
# (combined with GREATEST where more than one segment counts).
@pytest.mark.parametrize("fn", ["api.option_chain", "api.coverage", "api.universe"])
def test_latest_session_probes_avoid_an_in_list_max(fn):
    body = _strip_comments(FUNCS[fn])
    # Match the bad shape tightly — a max() whose OWN FROM/WHERE is the
    # b3_cotahist IN-list. A looser pattern spans unrelated arms of the same
    # statement (api.universe's equity arm does its own max(trade_date), and
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
    assert "WHERE p_to IS NOT NULL" in nav


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


def test_lookup_escapes_like_and_ranks_before_the_limit():
    body = FUNCS["api.lookup"]
    stripped = _strip_comments(body)
    assert r"'\%'" in body and r"'\_'" in body, "LIKE metacharacters unescaped"
    assert "ESCAPE" in stripped
    # The rank must be computed and ordered on before LIMIT cuts to 20.
    assert stripped.index("ORDER BY h.rank") < stripped.index("LIMIT 20")


def test_panel_cap_applies_after_deterministic_order():
    body = _strip_comments(FUNCS["api.panel"])
    order = re.search(r"ORDER\s+BY\s+4\s*,\s*1\s*,\s*5", body)
    limit = re.search(rf"\bLIMIT\s+{PANEL_CAP}\b", body)
    assert order and limit and order.start() < limit.start(), (
        "api.panel must ORDER BY (date, id, metric) before its LIMIT so the cut is deterministic"
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


def test_privilege_sweep_revokes_every_rls_disabled_public_object():
    body = _strip_comments(SQL12)
    assert "REVOKE ALL ON %s FROM anon, authenticated" in body, (
        "12_grants_and_rls.sql must sweep, not enumerate: a per-table revoke list "
        "silently misses every dataset and partition added after it was written"
    )
    assert "NOT c.relrowsecurity" in body
    assert "nspname = 'public'" in body


def test_sweep_precedes_the_grants_it_must_not_undo():
    body = _strip_comments(SQL12)
    sweep = body.index("REVOKE ALL ON %s FROM anon, authenticated")
    first_grant = body.index("GRANT SELECT ON fact_fund_monthly")
    assert sweep < first_grant, (
        "the sweep must run before the explicit GRANTs, or it revokes the client "
        "surface this file exists to define"
    )


def test_sweep_does_not_touch_the_other_application_tables():
    """RLS-enabled tables belong to the Edge-Functions app, not this pipeline.

    Their boundary is RLS; stripping `authenticated` from them would break an
    app whose privilege needs this repo cannot see.
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


def test_cap_constraint_no_longer_tells_agents_to_check_an_unreachable_sentinel():
    c = _cap_constraint()
    # The sentinel may still be MENTIONED (to say it is unreachable), but the
    # constraint must not present it as the way to detect truncation.
    assert "unreachable" in c.lower(), (
        "100001/5001 cannot fire behind a 1000-row ceiling; saying so is the point"
    )
    assert "must not be used to detect truncation" in c


def test_cap_constraint_warns_that_rpc_paging_does_not_work():
    c = _cap_constraint()
    assert "RANGE PAGING DOES NOT WORK ON RPC" in c, (
        "telling an agent to page an RPC would hand it page 1 twice and call it page 2"
    )


def test_agent_instructions_point_at_the_header():
    from serve.catalog import AGENT_INSTRUCTIONS

    assert "Content-Range" in AGENT_INSTRUCTIONS


def test_universe_bounds_the_tape_scan():
    """api.universe('equity') took 6.83s and failed every anon call at 3s."""
    body = _strip_comments(FUNCS["api.universe"])
    assert "tape_floor" in body, "universe must bound the partition key"
    assert "mv_b3_monthly_activity" in body
    # Both scans need it: latest_quote_session AND quote_rows.
    assert body.count("f.from_date") >= 2, (
        "bounding only the max() leaves quote_rows scanning every partition"
    )
