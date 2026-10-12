"""RJ documents of listed companies in schema `api` (34_api_rj_listed.sql, v75, #842).

Offline: the SQL text and the catalog are pinned to each other. The executed
behaviour (newest version, both signals, window on the delivery date, refusals,
anon can call the function but not read the view) is in
tests/sql/rj_listed_documents_behaviour.sql, which CI's sql-compile job runs.
"""

from __future__ import annotations

import re
from pathlib import Path

from serve.catalog import catalog_payload
from serve.endpoint_manifest import manifest

ROOT = Path(__file__).resolve().parents[1]
ANALYTICAL = ROOT / "src" / "store" / "analytical"
SQL34 = (ANALYTICAL / "34_api_rj_listed.sql").read_text(encoding="utf-8")
SIG = "api.rj_listed_documents(TEXT, DATE, DATE, TEXT)"


def _strip(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _function() -> str:
    start = SQL34.index("CREATE OR REPLACE FUNCTION api.rj_listed_documents(")
    return SQL34[start: SQL34.index("$fn$;", start)]


def test_file_is_one_guarded_transaction_after_19():
    body = _strip(SQL34)
    assert re.search(r"^\s*BEGIN\s*;", body, re.M)
    assert re.search(r"COMMIT\s*;\s*$", body.strip())
    assert "to_regprocedure('api.assert_row_cap(bigint, boolean, text)') IS NULL" in body
    assert "to_regprocedure('api.company_ref(text)') IS NULL" in body
    ordered = sorted(p.name for p in ANALYTICAL.glob("[0-9][0-9]_*.sql"))
    assert ordered.index("34_api_rj_listed.sql") > ordered.index("19_api_contract.sql")


def test_view_is_internal_and_function_is_granted():
    body = _strip(SQL34)
    assert "REVOKE ALL ON public.rj_listed_documents FROM PUBLIC;" in body
    assert not re.search(r"GRANT\s+\w+\s+ON\s+(TABLE\s+)?public\.rj_listed_documents", body)
    head = _function()
    head = head[: head.index("AS $fn$")]
    assert "SECURITY DEFINER" in head and "SET search_path = ''" in head
    assert f"REVOKE ALL ON FUNCTION {SIG} FROM PUBLIC;" in body
    assert f"GRANT EXECUTE ON FUNCTION {SIG} TO anon, authenticated;" in body
    assert f"GRANT EXECUTE ON FUNCTION {SIG} TO silo_api;" in body


def test_both_signals_and_newest_version():
    body = _strip(SQL34)
    assert "'Informações de Companhias em Recuperação Judicial ou Extrajudicial'" in body
    assert "e.categoria = 'Fato Relevante'" in body
    assert "DISTINCT ON (e.protocolo)" in body
    assert "ORDER BY e.protocolo, e.versao DESC NULLS LAST" in body
    # Falência is served by company_events, not here.
    view = body[body.index("CREATE OR REPLACE VIEW"): body.index("REVOKE ALL ON public.rj_listed_documents")]
    assert "Falência" not in view


def test_company_resolved_never_by_name():
    body = _strip(_function())
    assert "api.company_ref(v_id)" in body
    assert "ilike" not in body.lower() and "denom_cia" not in body


def test_window_is_the_delivery_date():
    body = _strip(_function())
    assert "d.delivery_date BETWEEN v_from AND v_to" in body
    assert "reference_date BETWEEN" not in body


def test_refuses_above_one_page_instead_of_trimming():
    body = _strip(_function())
    assert re.search(r"\bLIMIT\s+1001\b", body)
    assert re.search(r"\bLIMIT\s+1000\s*;", body)
    assert "api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'rj_listed_documents')" in body
    assert "p_after" not in body
    assert "ERRCODE = '22023'" in body


def test_catalog_publishes_it_raise_only():
    endpoint = manifest()["rj_listed_documents"]
    assert endpoint.granted and endpoint.raise_only
    assert endpoint.params == ("p_id", "p_from", "p_to", "p_doc_type")
    payload = catalog_payload()
    assert "rj_listed_documents" in payload["limits"]["page"]["functions"]["raise_only"]
    assert payload["postgrest"]["rj_listed_documents"] == "POST /rest/v1/rpc/rj_listed_documents"
    rj = next(c for c in payload["constraints"] if c.startswith("RJ DOCUMENTS"))
    assert "cadastro_status" in rj and "lags" in rj


def test_executed_sql_acceptance_is_wired_into_ci():
    workflow = (ROOT / ".github/workflows/test.yml").read_text()
    assert "-f tests/sql/rj_listed_documents_behaviour.sql" in workflow
