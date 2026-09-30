"""api.index_history (#415): the benchmark index, by index code only.

The body is pinned as text, because the offline suite has no database; the
behaviour was run against a local Postgres holding the real 14,489-session IBOV
series (2025-12-30 = 161,125.37, 1997-03-03 flagged and 1997-02-28 not, every
ticker refused with 22023, 15 cursor pages with no row lost or repeated).
"""

from __future__ import annotations

import re
from pathlib import Path

from serve.catalog import CATALOG_VERSION, catalog_payload

ROOT = Path(__file__).resolve().parents[1]
INDEX_SQL = ROOT / "src/store/analytical/29_api_index.sql"
CONTRACT = ROOT / "src/store/analytical/19_api_contract.sql"


def _uncommented(text: str) -> str:
    return re.sub(r"--[^\n]*", "", text)


def _body() -> str:
    sql = _uncommented(INDEX_SQL.read_text(encoding="utf-8"))
    start = sql.index("CREATE OR REPLACE FUNCTION api.index_history(")
    return sql[start:sql.index("$fn$;", start)]


def test_the_signature_and_columns_are_the_specs():
    body = _body()
    head = body.split("AS $fn$")[0]
    assert re.search(r"p_index\s+TEXT,", head)
    assert re.search(r"p_from\s+DATE\s+DEFAULT\s+\(CURRENT_DATE\s*-\s*365\)", head)
    assert re.search(r"p_to\s+DATE\s+DEFAULT\s+CURRENT_DATE", head)
    assert re.search(r"p_after\s+TEXT\s+DEFAULT\s+NULL", head)
    returns = head.split("RETURNS TABLE")[1]
    for column in ("index_code", "trade_date", "level", "divisor_step", "source"):
        assert re.search(rf"\b{column}\b", returns), column


def test_there_is_no_return_adjusted_or_total_return_column():
    returns = _body().split("AS $fn$")[0].split("RETURNS TABLE")[1]
    for forbidden in ("return", "adjusted", "total", "change", "pct"):
        assert forbidden not in returns.lower(), forbidden


def test_a_ticker_is_refused_with_22023_naming_the_codes_held():
    body = _body()
    assert "v_held" in body and "string_agg" in body
    assert "BOVA11" in body and "IBOV11" in body
    assert body.count("USING ERRCODE = '22023'") >= 2
    # The accepted codes are those the table holds: a ticker is never in it.
    assert "FROM public.b3_index_level l WHERE l.index_code = v_code" in re.sub(r"\s+", " ", body)


def test_a_null_window_is_refused_not_served_as_empty():
    assert re.search(r"IF p_from IS NULL OR p_to IS NULL THEN", _body())


def test_it_pages_with_the_shared_date_cursor_and_refuses_over_one_page():
    body = _body()
    assert "api.parse_date_cursor(p_after, 'index_history')" in body
    assert re.search(r"api\.assert_row_cap\(\(SELECT count\(\*\) FROM page\),\s*\(SELECT pp\.paging FROM params pp\), 'index_history'\)", body)
    assert "LIMIT 1001" in body and "LIMIT 1000" in body
    assert re.search(r"ORDER BY l\.trade_date", body)


def test_it_reads_only_the_index_table_under_definer_with_a_pinned_path():
    sql = INDEX_SQL.read_text(encoding="utf-8")
    body = _body()
    assert "SECURITY DEFINER" in body and "SET search_path = ''" in body
    tables = set(re.findall(r"public\.(\w+)", body))
    assert tables == {"b3_index_level"}, tables
    assert "REVOKE ALL ON FUNCTION api.index_history(TEXT, DATE, DATE, TEXT) FROM PUBLIC;" in sql
    for role in ("anon, authenticated", "silo_api"):
        assert f"GRANT EXECUTE ON FUNCTION api.index_history(TEXT, DATE, DATE, TEXT) TO {role};" in sql


def test_the_row_cap_helper_has_a_hint_for_it():
    contract = _uncommented(CONTRACT.read_text(encoding="utf-8"))
    assert "WHEN p_fn = 'index_history' THEN" in contract


def test_coverage_reports_the_index_with_the_depth_of_each_code():
    contract = CONTRACT.read_text(encoding="utf-8")
    assert "SELECT 'index_history'::text," in contract
    assert "'*b3_index_level*'::text" in contract
    assert "l.entity = 'b3' AND l.doc_type = 'index_levels'" in contract
    assert "string_agg(d.index_code || ' from ' || d.first_date::text" in contract


def test_the_catalog_publishes_it_as_a_function_that_pages():
    payload = catalog_payload()
    assert CATALOG_VERSION >= 45
    assert "index_history" in payload["limits"]["page"]["all"]
    assert "index_history" in payload["limits"]["page"]["functions"]["paged"]
    assert "index_history" not in payload["limits"]["page"]["functions"]["raise_only"]
    assert payload["postgrest"]["index_history"] == "POST /rest/v1/rpc/index_history"
    constraints = " ".join(payload["constraints"])
    assert "api.index_history" in constraints
    assert "IBOV11" in constraints and "divisor_step" in constraints
