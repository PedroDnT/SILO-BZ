"""BCB Focus weekly expectation path contract over held survey-date rows."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "src/store/analytical/19_api_contract.sql").read_text(encoding="utf-8")


def _body(name: str) -> str:
    start = SQL.index(f"CREATE OR REPLACE FUNCTION api.{name}(")
    end = SQL.index(f"REVOKE ALL ON FUNCTION api.{name}(", start)
    return SQL[start:end]


def test_focus_path_pins_endpoint_horizon_sample_and_window() -> None:
    body = _body("focus_expectations")
    assert "p_horizon IS NULL" in body
    assert "e.endpoint_name = p_endpoint" in body
    assert "e.horizon = btrim(p_horizon)" in body
    assert "e.reference_date BETWEEN" in body
    assert "e.raw ->> 'baseCalculo' = '0'" in body
    assert "e.raw ->> 'Suavizada' = 'N'" in body
    assert "e.mean_val" in body and "e.std_dev" in body
    assert "api.assert_row_cap" in body
    assert "LIMIT 1001" in body and "LIMIT 1000" in body


def test_focus_coverage_reports_revision_and_legacy_horizon_limits() -> None:
    coverage_start = SQL.index("CREATE OR REPLACE FUNCTION api.coverage()")
    coverage_end = SQL.index("REVOKE ALL ON FUNCTION api.coverage()", coverage_start)
    coverage = SQL[coverage_start:coverage_end]
    assert "SELECT 'focus_expectations'::text," in coverage
    assert "FROM public.bacen_expectativas e" in coverage
    assert "older lost horizon rows require re-fetch" in coverage


def test_focus_api_is_in_catalog_and_not_a_vintage_archive() -> None:
    from serve.catalog import LIMITS, catalog_payload

    assert catalog_payload()["postgrest"]["focus_expectations"] == (
        "POST /rest/v1/rpc/focus_expectations"
    )
    assert "focus_expectations" in LIMITS["page"]["all"]
    assert "focus_expectations" in LIMITS["page"]["functions"]["raise_only"]
    assert "22023" in LIMITS["page"]["over_cap"]
    constraints = " ".join(catalog_payload()["constraints"])
    assert "focus" in constraints.lower() and "weekly path" in constraints


def test_focus_natural_key_keeps_survey_horizons_separate() -> None:
    migration = (ROOT / "src/store/migrations/16_bacen_expectativas_horizon.sql").read_text()
    schema = (ROOT / "src/store/schema.sql").read_text()
    assert "UNIQUE NULLS NOT DISTINCT (endpoint_name, indicador, reference_date, horizon)" in migration
    assert "UNIQUE NULLS NOT DISTINCT (endpoint_name, indicador, reference_date, horizon)" in schema
