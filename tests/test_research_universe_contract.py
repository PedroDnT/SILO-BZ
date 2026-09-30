"""The research universe in schema `api` (28_api_research.sql, catalog v43).

Offline: the SQL text, the cron schedule, the row-cap helper and the catalog are
pinned to each other. What this file keeps true (docs/planning/RESEARCH_SEAM.md
§4, ticket #411):

* the house serving rules: SECURITY DEFINER with an empty pinned search_path,
  REVOKE from PUBLIC then GRANT to anon / authenticated / silo_api, one page
  plus one row and api.assert_row_cap refusing above it;
* the universe is read from a materialized view (anon's statement_timeout is 3 s
  and the bare aggregate takes 1.6 s warm), which no client role can read, is
  rebuilt by the apply and refreshed by cron;
* membership is the ISIN's own instrument code (ACN; CDA / UNT with a ticker
  ending 11), not instrument_type, so subscription receipts stay out;
* the company link says how it was made, and nothing is guessed from a name;
* no listing / delisting dates and no is_active are served (#373, #381);
* the over-cap message does not advise a narrowing that does not exist.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANALYTICAL = ROOT / "src" / "store" / "analytical"
SQL28 = (ANALYTICAL / "28_api_research.sql").read_text(encoding="utf-8")
SQL19 = (ANALYTICAL / "19_api_contract.sql").read_text(encoding="utf-8")
SQL08 = (ANALYTICAL / "08_cron_schedules.sql").read_text(encoding="utf-8")


def _strip(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _view() -> str:
    start = SQL28.index("CREATE MATERIALIZED VIEW public.mv_research_universe AS")
    return _strip(SQL28[start: SQL28.index("CREATE UNIQUE INDEX", start)])


def _function() -> str:
    start = SQL28.index("CREATE OR REPLACE FUNCTION api.research_universe(")
    return SQL28[start: SQL28.index("$$;", SQL28.index("AS $$", start)) + 3]


def _comment() -> str:
    start = SQL28.index("COMMENT ON FUNCTION api.research_universe(")
    return SQL28[start: SQL28.index("';\n", start)]


# ---------------------------------------------------------------------------
# Wiring and privileges
# ---------------------------------------------------------------------------


def test_file_is_one_guarded_transaction_after_19():
    body = _strip(SQL28)
    assert re.search(r"^\s*BEGIN\s*;", body, re.M)
    assert re.search(r"COMMIT\s*;\s*$", body.strip())
    assert "to_regprocedure('api.assert_row_cap(bigint,boolean,text)') IS NULL" in body
    for rel in ("b3_cotahist", "vw_company_ticker", "cia_company"):
        assert f"to_regclass('public.{rel}') IS NULL" in body
    ordered = sorted(p.name for p in ANALYTICAL.glob("[0-9][0-9]_*.sql"))
    assert ordered.index("28_api_research.sql") > ordered.index("19_api_contract.sql")


def test_exactly_one_function_is_created():
    created = re.findall(r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+api\.(\w+)\(", _strip(SQL28))
    # v46 adds index_history to the same file (tests/test_index_history_contract.py).
    assert created == ["research_universe", "index_history"]


def test_definer_empty_search_path_and_grants():
    head = _function()
    head = head[: head.index("AS $$")]
    assert "SECURITY DEFINER" in head and "SET search_path = ''" in head
    sig = "api.research_universe()"
    assert f"REVOKE ALL ON FUNCTION {sig} FROM PUBLIC;" in SQL28
    assert f"GRANT EXECUTE ON FUNCTION {sig} TO anon, authenticated;" in SQL28
    assert f"GRANT EXECUTE ON FUNCTION {sig} TO silo_api;" in SQL28


def test_the_view_has_no_client_grant_and_revokes_the_default_privileges():
    body = _strip(SQL28)
    assert not re.search(r"GRANT\s+\w+\s+ON\s+(?:TABLE\s+)?(?:public\.)?mv_research_universe", body, re.I)
    # Supabase gives new public objects SELECT for anon by default, and this
    # view is re-created on every apply, after 12_grants_and_rls.sql has run.
    revoke = "REVOKE ALL ON public.mv_research_universe FROM PUBLIC, anon, authenticated;"
    assert revoke in body
    assert body.index(revoke) > body.index("CREATE MATERIALIZED VIEW public.mv_research_universe")


def test_the_function_reads_only_the_view_and_qualifies_it():
    body = re.sub(r"'[^']*'", "''", _strip(_function()))
    sources = re.findall(r"\bFROM\s+([\w.]+)", body, re.I)
    # The view, then the CTE it feeds (once in the cap count, once in the select).
    assert sources[0] == "public.mv_research_universe"
    assert set(sources[1:]) == {"page"}


# ---------------------------------------------------------------------------
# The materialized view: refresh, uniqueness, membership
# ---------------------------------------------------------------------------


def test_the_view_is_rebuilt_by_the_apply_and_refreshed_by_cron():
    assert "DROP MATERIALIZED VIEW IF EXISTS public.mv_research_universe CASCADE;" in SQL28
    assert "CREATE UNIQUE INDEX uq_mv_research_universe ON public.mv_research_universe (ticker, isin);" in SQL28
    assert "REFRESH MATERIALIZED VIEW CONCURRENTLY mv_research_universe" in SQL08
    assert "'refresh-research-universe'" in SQL08


def test_membership_is_the_isin_instrument_code_not_instrument_type():
    v = _view()
    assert "q.tpmerc = '010'" in v
    assert "q.trade_date >= DATE '2019-01-02'" in v
    assert "substr(q.isin, 7, 3) = 'ACN'" in v
    assert re.search(r"substr\(q\.isin, 7, 3\) IN \('CDA', 'UNT'\) AND q\.codneg ~ '11\$'", v)
    # Receipts (ISIN code R01..R21) are excluded by the rule, never by name.
    assert "instrument_type" not in v.split("SELECT\n    t.codneg")[0]
    assert "vw_b3_instrument_typed" not in v and "api.quotes" not in v


def test_a_session_is_counted_once_and_the_type_comes_from_the_isin_code():
    v = _view()
    assert "count(DISTINCT q.trade_date)" in v
    assert re.search(r"CASE substr\(t\.isin, 7, 3\) WHEN 'ACN' THEN 'equity' ELSE 'unit' END", v)


# ---------------------------------------------------------------------------
# The company link: published only, and it says how
# ---------------------------------------------------------------------------


def test_the_link_is_the_fca_map_with_a_basis_and_never_a_name_match():
    v = _view()
    assert "public.vw_company_ticker" in v
    assert "'fca_ticker'" in v and "'fca_issuer_stem'" in v
    # An ambiguous ticker or stem links nothing.
    assert v.count("HAVING count(DISTINCT cnpj_cia) = 1") == 2
    # Placeholder tickers ('0000', 'NÃO') are filtered by shape.
    assert "vt.codneg ~ '^[A-Z]{4}[0-9]{1,2}[A-Z]?$'" in v
    for banned in ("denom_cia", "ILIKE", "nome_resumido", "short_name"):
        assert banned not in v, f"the link must never match on a name: {banned}"


def test_setor_is_current_and_segmento_is_not_served():
    v = _view()
    assert "FROM public.cia_company" in v and "count(DISTINCT setor) = 1" in v
    columns = _function()[: _function().index("LANGUAGE sql")]
    assert "setor_current" in columns
    assert "segmento" not in columns


def test_no_listing_dates_and_no_is_active_are_served():
    columns = _function()[: _function().index("LANGUAGE sql")]
    for banned in ("is_active", "dt_inicio", "dt_fim", "listing", "delisting"):
        assert banned not in re.sub(r"--.*", "", columns), banned
    v = _view()
    assert "is_active" not in v and "dt_inicio" not in v and "dt_fim" not in v


# ---------------------------------------------------------------------------
# Refuse, never trim
# ---------------------------------------------------------------------------


def test_one_page_plus_one_and_the_cap_helper_refuses():
    body = _strip(_function())
    assert "LIMIT 1001" in body and "LIMIT 1000" in body
    assert "api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'research_universe')" in body


def test_the_over_cap_message_does_not_advise_a_narrowing_that_does_not_exist():
    start = SQL19.index("WHEN p_fn = 'research_universe' THEN")
    branch = SQL19[start: SQL19.index("WHEN left(p_fn, 7) = 'screen_'", start)]
    assert "no narrowing parameter" in branch and "p_after" in branch
    assert "Narrow the window" not in branch


# ---------------------------------------------------------------------------
# What the comment promises
# ---------------------------------------------------------------------------


def test_the_comment_states_the_rules_a_research_caller_needs():
    c = _comment()
    for phrase in (
        "The ISIN is the identity",
        "NEW row",
        "not listing or delisting dates",
        "cnpj_basis",
        "fca_issuer_stem",
        "as of today",
        "first_observed <= T <= last_observed",
        "a pair inside a gap still matches",
        "lags the tape by up to a day",
        "22023",
        "subscription receipts",
    ):
        assert phrase in c, phrase


# ---------------------------------------------------------------------------
# The catalog and the MCP tool list know about it
# ---------------------------------------------------------------------------


def test_the_catalog_and_the_mcp_tool_list_name_the_function():
    from serve.catalog import CATALOG_VERSION, catalog_payload

    assert CATALOG_VERSION >= 43
    payload = catalog_payload()
    assert payload["postgrest"]["research_universe"] == "POST /rest/v1/rpc/research_universe"
    page = payload["limits"]["page"]
    assert "research_universe" in page["all"]
    assert "research_universe" in page["functions"]["raise_only"]
    tools = (ROOT / "supabase" / "functions" / "silo-mcp" / "tools.ts").read_text(encoding="utf-8")
    assert 't("research_universe"' in tools
