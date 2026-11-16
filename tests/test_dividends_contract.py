"""api.dividends (40_api_dividends.sql, catalog v84, #1157).

Offline: the SQL text, the catalog and the v2 registry are pinned to each
other. The executed behaviour (share class, installment payment dates, an
ambiguous date left NULL, supplement-only events, refusals, the row cap) is in
tests/sql/dividends_behaviour.sql, which CI's sql-compile job runs.
"""

from __future__ import annotations

import re
from pathlib import Path

from serve.catalog import catalog_payload
from serve.endpoint_manifest import manifest

ROOT = Path(__file__).resolve().parents[1]
ANALYTICAL = ROOT / "src" / "store" / "analytical"
SQL40 = (ANALYTICAL / "40_api_dividends.sql").read_text(encoding="utf-8")
SIG = "api.dividends(TEXT, DATE, DATE)"


def _strip(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _function() -> str:
    start = SQL40.index("CREATE OR REPLACE FUNCTION api.dividends(")
    return SQL40[start: SQL40.index("$fn$;", start)]


def test_file_is_one_guarded_transaction_after_19():
    body = _strip(SQL40)
    assert re.search(r"^\s*BEGIN\s*;", body, re.M)
    assert re.search(r"COMMIT\s*;\s*$", body.strip())
    assert "to_regprocedure('api.ticker_lineage(text)') IS NULL" in body
    ordered = sorted(p.name for p in ANALYTICAL.glob("[0-9][0-9]_*.sql"))
    assert ordered.index("40_api_dividends.sql") > ordered.index("19_api_contract.sql")


def test_function_is_granted_and_the_tables_are_not():
    body = _strip(SQL40)
    head = _function()
    head = head[: head.index("AS $fn$")]
    assert "SECURITY DEFINER" in head and "SET search_path = ''" in head
    assert f"REVOKE ALL ON FUNCTION {SIG} FROM PUBLIC;" in body
    assert f"GRANT EXECUTE ON FUNCTION {SIG} TO anon, authenticated;" in body
    assert f"GRANT EXECUTE ON FUNCTION {SIG} TO silo_api;" in body
    assert not re.search(r"GRANT\s+\w+\s+ON\s+(TABLE\s+)?public\.", body)


def test_every_row_names_its_source_and_payment_date_is_never_filled():
    body = _strip(_function())
    returns = body[body.index("RETURNS TABLE"): body.index("LANGUAGE")]
    for col in ("payment_date", "ex_date", "last_date_with", "value_per_share", "source"):
        assert col in returns
    assert "'b3_cash_history'" in body and "'b3_supplement'" in body
    # payment_date comes only from the supplement; no COALESCE onto another date.
    assert not re.search(r"COALESCE\s*\([^)]*payment_date", body)


def test_refuses_above_one_page_instead_of_trimming():
    body = _strip(_function())
    assert re.search(r"\bLIMIT\s+1001\b", body)
    assert re.search(r"\bLIMIT\s+1000\s*;", body)
    assert "api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'dividends')" in body
    assert "ERRCODE = '22023'" in body


def test_catalog_publishes_it_raise_only():
    endpoint = manifest()["dividends"]
    assert endpoint.granted and endpoint.raise_only
    assert endpoint.params == ("p_ticker", "p_from", "p_to")
    payload = catalog_payload()
    assert "dividends" in payload["limits"]["page"]["functions"]["raise_only"]
    assert payload["postgrest"]["dividends"] == "POST /rest/v1/rpc/dividends"
    text = next(c for c in payload["constraints"] if c.startswith("DIVIDENDS ARE B3'S"))
    assert "NEVER GUESSED" in text and "NULL before 2019" in text


def test_executed_sql_acceptance_is_wired_into_ci():
    workflow = (ROOT / ".github/workflows/test.yml").read_text()
    assert "-f tests/sql/dividends_behaviour.sql" in workflow
