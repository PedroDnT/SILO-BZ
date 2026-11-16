"""api.debt_issues (43_api_debt_issues.sql, catalog v88, #1164).

Offline: the SQL text, the catalog and the v2 registry are pinned to each
other. The executed behaviour (newest version per reference date, values and
terms as filed, NULL kept, ticker resolution, refusals, the row cap) is in
tests/sql/debt_issues_behaviour.sql, which CI's sql-compile job runs.
"""

from __future__ import annotations

import re
from pathlib import Path

from serve.catalog import catalog_payload
from serve.endpoint_manifest import manifest

ROOT = Path(__file__).resolve().parents[1]
ANALYTICAL = ROOT / "src" / "store" / "analytical"
SQL43 = (ANALYTICAL / "43_api_debt_issues.sql").read_text(encoding="utf-8")
SIG = "api.debt_issues(TEXT, DATE, DATE)"


def _strip(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _function() -> str:
    start = SQL43.index("CREATE OR REPLACE FUNCTION api.debt_issues(")
    return SQL43[start: SQL43.index("$fn$;", start)]


def test_file_is_one_guarded_transaction_after_19():
    body = _strip(SQL43)
    assert re.search(r"^\s*BEGIN\s*;", body, re.M)
    assert re.search(r"COMMIT\s*;\s*$", body.strip())
    assert "to_regprocedure('api.company_ref(text)') IS NULL" in body
    assert "to_regclass('public.cvm_fre_outro_valor_mobiliario') IS NULL" in body
    ordered = sorted(p.name for p in ANALYTICAL.glob("[0-9][0-9]_*.sql"))
    assert ordered.index("43_api_debt_issues.sql") > ordered.index("19_api_contract.sql")


def test_function_is_granted_and_the_table_is_not():
    body = _strip(SQL43)
    head = _function()
    head = head[: head.index("AS $fn$")]
    assert "SECURITY DEFINER" in head and "SET search_path = ''" in head
    assert f"REVOKE ALL ON FUNCTION {SIG} FROM PUBLIC;" in body
    assert f"GRANT EXECUTE ON FUNCTION {SIG} TO anon, authenticated;" in body
    assert f"GRANT EXECUTE ON FUNCTION {SIG} TO silo_api;" in body
    assert not re.search(r"GRANT\s+\w+\s+ON\s+(TABLE\s+)?public\.", body)


def test_refuses_above_one_page_instead_of_trimming():
    body = _strip(_function())
    assert re.search(r"\bLIMIT\s+1001\b", body)
    assert re.search(r"\bLIMIT\s+1000\s*;", body)
    assert "api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'debt_issues')" in body
    assert "ERRCODE = '22023'" in body


def test_newest_version_and_the_terms_are_not_parsed():
    body = _strip(_function())
    assert "ORDER BY f.data_refer, f.versao DESC" in body
    # The terms text is served whole: no regex, no substring, no fill.
    after = body.split("RETURN QUERY", 1)[1]
    assert "g.caracteristicas_divida," in after
    assert not re.search(r"\b(regexp_\w+|substring|split_part|COALESCE)\s*\(", after, re.I)


def test_catalog_publishes_it_raise_only():
    endpoint = manifest()["debt_issues"]
    assert endpoint.granted and endpoint.raise_only
    assert endpoint.params == ("p_id", "p_from", "p_to")
    payload = catalog_payload()
    assert "debt_issues" in payload["limits"]["page"]["functions"]["raise_only"]
    assert payload["postgrest"]["debt_issues"] == "POST /rest/v1/rpc/debt_issues"
    assert payload["version"] >= 88


def test_catalog_states_the_limits():
    text = next(c for c in catalog_payload()["constraints"]
                if c.startswith("DEBT ISSUES ARE THE COMPANY'S FRE TEXT"))
    assert "LISTED ISSUERS ONLY" in text and "RATE NOT PARSED" in text


def test_v2_kind_and_docs_state_the_limits():
    registry = (ROOT / "supabase/functions/silo-api/registry.ts").read_text(encoding="utf-8")
    assert '"endpoint": "debt_issues"' in registry
    page = (ROOT / "api-docs/v2/operations/statements/debt_issues.mdx").read_text(encoding="utf-8")
    assert "unparsed" in page and "no FRE" in page
    api_md = (ROOT / "docs/reference/API.md").read_text(encoding="utf-8")
    assert "api.debt_issues(p_id, p_from, p_to)" in api_md


def test_executed_sql_acceptance_is_wired_into_ci():
    workflow = (ROOT / ".github/workflows/test.yml").read_text()
    assert "-f tests/sql/debt_issues_behaviour.sql" in workflow
