"""api.trade_consolidated_history (research #606, catalog v65): B3's FORWARD segment.

The 46 Brazilian fixed-income ETFs are not in COTAHIST, so quote_history has
nothing for them; migration 57 lands their prints from B3's
TradeInformationConsolidatedFile and this function serves them.

The body is pinned as text, because the offline suite has no database; the
behaviour is executed in tests/sql/trade_consolidated_history_behaviour.sql by
the SQL compile job (unknown ticker and NULL window refused, an untraded session
carries only ref_price, the page edge refuses, the cursor walks every row once).
"""

from __future__ import annotations

import re
from pathlib import Path

from serve.catalog import CATALOG_VERSION, catalog_payload

ROOT = Path(__file__).resolve().parents[1]
SQL_FILE = ROOT / "src/store/analytical/32_api_trade_consolidated.sql"
CONTRACT = ROOT / "src/store/analytical/19_api_contract.sql"
SIGNATURE = "api.trade_consolidated_history(TEXT, DATE, DATE, TEXT)"

COLUMNS = (
    "ticker", "trade_date", "isin", "segment", "min_price", "max_price",
    "avg_price", "last_price", "ref_price", "oscillation_pct", "trade_count",
    "quantity", "notional_brl", "file_status", "source",
)


def _uncommented(text: str) -> str:
    return re.sub(r"--[^\n]*", "", text)


def _body() -> str:
    sql = _uncommented(SQL_FILE.read_text(encoding="utf-8"))
    start = sql.index("CREATE OR REPLACE FUNCTION api.trade_consolidated_history(")
    return sql[start:sql.index("$fn$;", start)]


def _returns() -> str:
    return _body().split("AS $fn$")[0].split("RETURNS TABLE")[1]


def _comment() -> str:
    sql = SQL_FILE.read_text(encoding="utf-8")
    start = sql.index(f"COMMENT ON FUNCTION {SIGNATURE} IS")
    return sql[start:sql.index("';\n", start)]


def test_the_signature_is_the_specs():
    head = _body().split("AS $fn$")[0]
    assert re.search(r"p_ticker\s+TEXT,", head)
    assert re.search(r"p_from\s+DATE\s+DEFAULT\s+\(CURRENT_DATE\s*-\s*365\)", head)
    assert re.search(r"p_to\s+DATE\s+DEFAULT\s+CURRENT_DATE", head)
    assert re.search(r"p_after\s+TEXT\s+DEFAULT\s+NULL", head)


def test_it_returns_the_published_columns_in_order():
    names = re.findall(r"^\s*(\w+)\s+(?:TEXT|DATE|NUMERIC|BIGINT)", _returns(), re.M)
    assert tuple(names) == COLUMNS


def test_there_is_no_open_adjusted_or_return_column():
    """The file has no opening price; none may be filled from another source."""
    returns = _returns().lower()
    for forbidden in ("open", "adjusted", "adj", "return", "close", "total"):
        assert forbidden not in returns, forbidden
    # Nor anywhere in the body: no column is borrowed from COTAHIST.
    assert "b3_cotahist" not in _body()


def test_an_unknown_ticker_is_refused_pointing_at_quote_history():
    body = _body()
    flat = re.sub(r"\s+", " ", body)
    assert "FROM public.b3_trade_consolidated t WHERE t.ticker = v_ticker" in flat
    refusal = body[body.index("RAISE EXCEPTION"):body.index("USING ERRCODE")]
    assert "FORWARD" in refusal and "quote_history" in refusal
    assert body.count("USING ERRCODE = '22023'") >= 2


def test_a_null_window_is_refused_not_served_as_empty():
    assert re.search(r"IF p_from IS NULL OR p_to IS NULL THEN", _body())


def test_it_pages_with_the_shared_date_cursor_and_refuses_over_one_page():
    body = _body()
    assert "api.parse_date_cursor(p_after, 'trade_consolidated_history')" in body
    assert re.search(
        r"api\.assert_row_cap\(\(SELECT count\(\*\) FROM page\),\s*"
        r"\(SELECT pp\.paging FROM params pp\), 'trade_consolidated_history'\)",
        body,
    )
    assert "LIMIT 1001" in body and "LIMIT 1000" in body
    assert re.search(r"ORDER BY t\.trade_date", body)


def test_it_reads_only_its_table_under_definer_with_a_pinned_path():
    sql = SQL_FILE.read_text(encoding="utf-8")
    body = _body()
    assert "SECURITY DEFINER" in body and "SET search_path = ''" in body
    assert "STABLE" in body and "LANGUAGE plpgsql" in body
    assert set(re.findall(r"public\.(\w+)", body)) == {"b3_trade_consolidated"}
    assert f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC;" in sql
    for role in ("anon, authenticated", "silo_api"):
        assert f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO {role};" in sql


def test_the_comment_states_the_five_caveats():
    c = _comment()
    # 1. the close, and the reference price that is never one
    assert "The close is last_price" in c
    assert "NOT a trade and NEVER a close" in c and "last_price" in c and "NULL" in c
    # 2. no opening price
    assert "NO opening price" in c
    # 3. volume not comparable, with migration 57's measurement
    assert "R$587,459,700.14" in c and "R$588,765,462.41" in c
    # 4. not adjusted for distributions: a price-only return
    assert "NOT adjusted for distributions" in c and "price-only return" in c
    # 5. retention
    assert "2025-06-10" in c and "2026-09-30" in c
    # the cap, which gen_openapi and test_openapi_spec read
    assert "22023" in c and "1000" in c


def test_the_row_cap_helper_has_a_hint_for_it():
    contract = _uncommented(CONTRACT.read_text(encoding="utf-8"))
    assert "WHEN p_fn = 'trade_consolidated_history' THEN" in contract


def test_coverage_reports_it_with_its_own_landed_row():
    contract = CONTRACT.read_text(encoding="utf-8")
    assert "SELECT 'trade_consolidated_history'::text," in contract
    assert "'*b3_trade_consolidated*'::text" in contract
    assert "l.entity = 'b3' AND l.doc_type = 'trade_consolidated'" in contract


def test_the_catalog_publishes_it_as_a_function_that_pages():
    payload = catalog_payload()
    assert CATALOG_VERSION >= 65
    page = payload["limits"]["page"]
    assert "trade_consolidated_history" in page["all"]
    assert "trade_consolidated_history" in page["functions"]["paged"]
    assert "trade_consolidated_history" not in page["functions"]["raise_only"]
    assert (payload["postgrest"]["trade_consolidated_history"]
            == "POST /rest/v1/rpc/trade_consolidated_history")
    constraints = " ".join(payload["constraints"])
    assert "api.trade_consolidated_history" in constraints
    assert "NEVER a close" in constraints and "NO opening price" in constraints


def test_the_mcp_server_exposes_it():
    tools = (ROOT / "supabase/functions/silo-mcp/tools.ts").read_text(encoding="utf-8")
    assert 't("trade_consolidated_history",' in tools
