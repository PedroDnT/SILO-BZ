"""ANBIMA class aggregates: served as aggregates, never as funds.

anbima_class_monthly is the Boletim de Fundos read long. Nothing in it is per
fund and nothing in the warehouse maps a fund to an ANBIMA class, so the one
way to serve a wrong number from it is to let a caller believe otherwise — a
name join, a panel arm, or an empty array that reads as "ANBIMA published
nothing" when the caller merely misspelt a class. These tests read the
contract SQL as text and pin those refusals.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "src/store/analytical/19_api_contract.sql").read_text(encoding="utf-8")


def _body(name: str) -> str:
    start = SQL.index(f"CREATE OR REPLACE FUNCTION api.{name}(")
    end = SQL.index(f"REVOKE ALL ON FUNCTION api.{name}(", start)
    return SQL[start:end]


def test_the_function_exists_and_reads_only_the_anbima_table():
    body = _body("anbima_classes")
    assert "FROM public.anbima_class_monthly" in body
    # Fully qualified because search_path is '' (DEFINER hygiene), and the
    # ANBIMA table is the ONLY relation it may touch: no fund table, no join.
    relations = set(re.findall(r"\bFROM\s+public\.(\w+)", body))
    assert relations == {"anbima_class_monthly"}, relations
    assert "JOIN" not in body.upper()


def test_class_aggregates_are_the_default_level():
    body = _body("anbima_classes")
    assert "p_level    TEXT DEFAULT 'category'" in body
    assert "a.level  = p_level" in body


def test_unknown_inputs_raise_rather_than_return_nothing():
    """An empty array is indistinguishable from 'nothing published'."""
    body = _body("anbima_classes")
    assert body.count("USING ERRCODE = '22023'") == 3, "level, category and metric each raise"
    # The valid lists come from the table, not a hard-coded set, so a class
    # ANBIMA adds is accepted the day it lands.
    assert "string_agg(DISTINCT a.anbima_category" in body
    assert "string_agg(DISTINCT a.metric" in body


def test_no_fund_is_ever_matched_to_a_class_by_name():
    body = _body("anbima_classes")
    assert "ILIKE" not in body.upper()
    assert "similarity(" not in body
    assert "dim_fund" not in body and "cvm_fi" not in body


def test_unit_is_read_off_the_metric_name_never_the_number():
    body = _body("anbima_classes")
    for suffix, unit in (("_brl_mm", "'brl_mm'"), ("_pct", "'pct'"), ("fund_count", "'count'")):
        assert unit in body, f"unit {unit} missing"
    assert "a.metric LIKE" in body


def test_values_are_served_as_published():
    """No scaling: R$ milhões and percentage points exactly as ANBIMA prints."""
    body = _body("anbima_classes")
    select = body[body.index("RETURN QUERY"):]
    assert re.search(r"\ba\.value\s*,", select)
    assert "* 1000000" not in select and "/ 100" not in select


def test_the_cap_and_definer_hygiene():
    body = _body("anbima_classes")
    # v25: one page plus one row, then REFUSE. The old LIMIT 5001 was a
    # sentinel PostgREST never let a caller reach.
    assert "LIMIT 1001" in body and "LIMIT 1000" in body
    assert "api.assert_row_cap((SELECT count(*) FROM page)" in body
    assert "'anbima_classes')" in body, "the 22023 must name the function"
    assert "LIMIT 5001" not in body
    assert "SECURITY DEFINER" in body and "SET search_path = ''" in body
    assert "ORDER BY 1, 2, 4, 6" in body, "positional order so the cut is deterministic"


def test_granted_to_every_client_role():
    sig = r"api\.anbima_classes\(TEXT, TEXT, TEXT, DATE, DATE\)"
    assert re.search(rf"GRANT EXECUTE ON FUNCTION {sig}\s+TO anon, authenticated;", SQL)
    assert re.search(rf"GRANT EXECUTE ON FUNCTION {sig}\s+TO silo_api;", SQL)


def test_coverage_reports_the_boletim_as_complete_by_construction():
    cov = _body("coverage")
    assert "SELECT 'anbima_classes'::text, MAX(a.reference_date), MAX(a.reference_date)," in cov
    assert "'anbima'::text" in cov


def test_the_catalog_names_the_endpoint_and_the_no_fund_rule():
    from serve.catalog import catalog_payload

    payload = catalog_payload()
    assert payload["postgrest"]["anbima_classes"] == "POST /rest/v1/rpc/anbima_classes"
    blob = " ".join(payload["constraints"]).lower()
    assert "anbima" in blob and "no fund" in blob and "not funds" in blob
