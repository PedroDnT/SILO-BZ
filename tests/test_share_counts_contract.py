"""api.share_counts and api.free_float (41_api_share_counts.sql, catalog v86, #1161).

Offline: the SQL text, the catalog and the v2 registry are pinned to each
other. The executed behaviour (newest version per period, the FRE Integralizado
row, NULL kept, ticker resolution, refusals, the row cap) is in
tests/sql/share_counts_behaviour.sql, which CI's sql-compile job runs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from serve.catalog import catalog_payload
from serve.endpoint_manifest import manifest

ROOT = Path(__file__).resolve().parents[1]
ANALYTICAL = ROOT / "src" / "store" / "analytical"
SQL41 = (ANALYTICAL / "41_api_share_counts.sql").read_text(encoding="utf-8")
FUNCTIONS = ("share_counts", "free_float")


def _strip(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _function(name: str) -> str:
    start = SQL41.index(f"CREATE OR REPLACE FUNCTION api.{name}(")
    return SQL41[start: SQL41.index("$fn$;", start)]


def test_file_is_one_guarded_transaction_after_19():
    body = _strip(SQL41)
    assert re.search(r"^\s*BEGIN\s*;", body, re.M)
    assert re.search(r"COMMIT\s*;\s*$", body.strip())
    assert "to_regprocedure('api.company_ref(text)') IS NULL" in body
    assert "to_regclass('public.cia_share_count') IS NULL" in body
    ordered = sorted(p.name for p in ANALYTICAL.glob("[0-9][0-9]_*.sql"))
    assert ordered.index("41_api_share_counts.sql") > ordered.index("19_api_contract.sql")


@pytest.mark.parametrize("name", FUNCTIONS)
def test_function_is_granted_and_the_tables_are_not(name):
    body = _strip(SQL41)
    sig = f"api.{name}(TEXT, DATE, DATE)"
    head = _function(name)
    head = head[: head.index("AS $fn$")]
    assert "SECURITY DEFINER" in head and "SET search_path = ''" in head
    assert f"REVOKE ALL ON FUNCTION {sig} FROM PUBLIC;" in body
    assert f"GRANT EXECUTE ON FUNCTION {sig} TO anon, authenticated;" in body
    assert f"GRANT EXECUTE ON FUNCTION {sig} TO silo_api;" in body
    assert not re.search(r"GRANT\s+\w+\s+ON\s+(TABLE\s+)?public\.", body)


@pytest.mark.parametrize("name", FUNCTIONS)
def test_refuses_above_one_page_instead_of_trimming(name):
    body = _strip(_function(name))
    assert re.search(r"\bLIMIT\s+1001\b", body)
    assert re.search(r"\bLIMIT\s+1000\s*;", body)
    assert f"api.assert_row_cap((SELECT count(*) FROM page), FALSE, '{name}')" in body
    assert "ERRCODE = '22023'" in body


def test_newest_version_and_nothing_is_filled():
    for name in FUNCTIONS:
        body = _strip(_function(name))
        assert "versao DESC NULLS LAST" in body
        # No count is filled from another period or another source.
        assert not re.search(r"\bCOALESCE\s*\(", body.split("BEGIN", 1)[1])
        assert not re.search(r"\b(lag|lead|last_value)\s*\(", body, re.I)
    shares = _strip(_function("share_counts"))
    assert "f.tipo_capital = 'Capital Integralizado'" in shares
    assert "'cvm_fre'" in shares and "'cvm_' || s.doc_type" in shares


@pytest.mark.parametrize("name", FUNCTIONS)
def test_catalog_publishes_it_raise_only(name):
    endpoint = manifest()[name]
    assert endpoint.granted and endpoint.raise_only
    assert endpoint.params == ("p_id", "p_from", "p_to")
    payload = catalog_payload()
    assert name in payload["limits"]["page"]["functions"]["raise_only"]
    assert payload["postgrest"][name] == f"POST /rest/v1/rpc/{name}"
    assert payload["version"] >= 86  # v86 published it; later versions keep it


def test_catalog_states_the_limits():
    text = next(c for c in catalog_payload()["constraints"]
                if c.startswith("SHARE COUNTS AND THE FREE FLOAT ARE CVM'S"))
    assert "from 2020" in text and "from 2010" in text and "NOT point-in-time" in text


def test_executed_sql_acceptance_is_wired_into_ci():
    workflow = (ROOT / ".github/workflows/test.yml").read_text()
    assert "-f tests/sql/share_counts_behaviour.sql" in workflow
