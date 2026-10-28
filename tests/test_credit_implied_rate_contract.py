"""api.credit_implied_rate (38_api_credit_implied.sql, catalog v79, #1007).

Offline: the SQL text and the catalog are pinned to each other. The executed
behaviour (tags, no ANBIMA field, refusals, the row cap, grants) is in
tests/sql/credit_implied_rate_behaviour.sql, which CI's sql-compile job runs.
"""

from __future__ import annotations

import re
from pathlib import Path

from serve.catalog import catalog_payload
from serve.endpoint_manifest import manifest

ROOT = Path(__file__).resolve().parents[1]
ANALYTICAL = ROOT / "src" / "store" / "analytical"
SQL38 = (ANALYTICAL / "38_api_credit_implied.sql").read_text(encoding="utf-8")
SIG = "api.credit_implied_rate(TEXT, DATE, DATE)"


def _strip(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _function() -> str:
    start = SQL38.index("CREATE OR REPLACE FUNCTION api.credit_implied_rate(")
    return SQL38[start: SQL38.index("$fn$;", start)]


def test_file_is_one_guarded_transaction_after_19_and_37():
    body = _strip(SQL38)
    assert re.search(r"^\s*BEGIN\s*;", body, re.M)
    assert re.search(r"COMMIT\s*;\s*$", body.strip())
    assert "to_regprocedure('api.assert_row_cap(bigint, boolean, text)') IS NULL" in body
    ordered = sorted(p.name for p in ANALYTICAL.glob("[0-9][0-9]_*.sql"))
    assert ordered.index("38_api_credit_implied.sql") > ordered.index("37_credit_implied_check.sql")


def test_function_is_granted_and_the_tables_are_not():
    body = _strip(SQL38)
    head = _function()
    head = head[: head.index("AS $fn$")]
    assert "SECURITY DEFINER" in head and "SET search_path = ''" in head
    assert f"REVOKE ALL ON FUNCTION {SIG} FROM PUBLIC;" in body
    assert f"GRANT EXECUTE ON FUNCTION {SIG} TO anon, authenticated;" in body
    assert f"GRANT EXECUTE ON FUNCTION {SIG} TO silo_api;" in body
    assert not re.search(r"GRANT\s+\w+\s+ON\s+(TABLE\s+)?public\.", body)


def test_no_anbima_number_is_served():
    body = _strip(_function())
    returns = body[body.index("RETURNS TABLE"): body.index("LANGUAGE")]
    for name in ("anbima", "gap_pp", "taxa_indicativa"):
        assert name not in returns
    assert "public.anbima_debenture_indicative" not in body
    assert "public.credit_implied_vs_anbima" in body  # the tags only


def test_every_row_is_marked_calculated():
    returns = _function()
    assert "is_calculated BOOLEAN" in returns
    assert "r.is_calculated" in returns


def test_refuses_above_one_page_instead_of_trimming():
    body = _strip(_function())
    assert re.search(r"\bLIMIT\s+1001\b", body)
    assert re.search(r"\bLIMIT\s+1000\s*;", body)
    assert "api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'credit_implied_rate')" in body
    assert "p_after" not in body
    assert "ERRCODE = '22023'" in body


def test_catalog_publishes_it_raise_only():
    endpoint = manifest()["credit_implied_rate"]
    assert endpoint.granted and endpoint.raise_only
    assert endpoint.params == ("p_code", "p_from", "p_to")
    payload = catalog_payload()
    assert "credit_implied_rate" in payload["limits"]["page"]["functions"]["raise_only"]
    assert payload["postgrest"]["credit_implied_rate"] == "POST /rest/v1/rpc/credit_implied_rate"
    text = next(c for c in payload["constraints"] if c.startswith("A DEBENTURE'S IMPLIED RATE"))
    assert "CALCULATED, NOT OBSERVED" in text
    assert "are NOT served" in text and "unchecked means no check was possible" in text


def test_executed_sql_acceptance_is_wired_into_ci():
    workflow = (ROOT / ".github/workflows/test.yml").read_text()
    assert "-f tests/sql/credit_implied_rate_behaviour.sql" in workflow
