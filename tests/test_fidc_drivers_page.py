"""The FIDC delinquency-drivers block: one definition, both metrics, honest nulls.

Pins the properties of fidc_delinquency_drivers() (15_fraud_screens.sql) and the
six dashboard sources / page block built on it. The classification is the
substance: a rate = overdue / net assets moves for two different reasons, and
the page exists to tell them apart.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCREENS = ROOT / "src" / "store" / "analytical" / "15_fraud_screens.sql"
SOURCES = ROOT / "dashboard" / "sources" / "supabase"
PAGE = ROOT / "dashboard" / "pages" / "fidc.md"

SOURCE_NAMES = [
    "fidc_drivers_summary",
    "fidc_drivers_consistent",
    "fidc_drivers_masked",
    "fidc_drivers_denominator",
    "fidc_drivers_all",
    "fidc_stopped_reporting",
]


def _fn() -> str:
    body = SCREENS.read_text(encoding="utf-8")
    start = body.index("CREATE OR REPLACE FUNCTION fidc_delinquency_drivers(")
    end = body.index("COMMENT ON FUNCTION fidc_delinquency_drivers")
    return "\n".join(l.split("--", 1)[0] for l in body[start:end].splitlines())


def test_function_reads_the_served_series_and_is_invoker():
    fn = _fn()
    assert "FROM fact_fund_monthly f" in fn
    assert "f.entity_type = 'fidc'" in fn
    assert "SECURITY INVOKER" in fn
    for landing in ("cvm_fidc_mensal", "cvm_fidc_aging"):
        assert landing not in fn, f"reads {landing} instead of the fact table the API serves"


def test_window_ends_at_the_complete_period_and_never_starts_before_the_regime():
    fn = _fn()
    assert "latest_complete_period('fidc')" in fn
    assert "v_from < DATE '2025-01-01'" in fn
    assert "ERRCODE = '22023'" in fn


def test_an_observation_needs_both_series_and_null_is_never_zero():
    fn = _fn()
    assert "f.vl_inadimpl IS NOT NULL" in fn
    assert "f.vl_patrim_liq IS NOT NULL" in fn
    assert "f.vl_patrim_liq > 0" in fn
    assert "COALESCE(f.vl_inadimpl" not in fn and "coalesce(f.vl_inadimpl" not in fn


def test_the_five_drivers_are_classified_from_both_deltas():
    fn = _fn()
    for driver in ("consistent_worsening", "value_up_rate_masked",
                   "denominator_only", "improvement", "stable"):
        assert f"'{driver}'" in fn
    case = fn[fn.index("CASE"):fn.index("END", fn.index("CASE"))]
    # consistent: value up AND rate up; masked: value up alone; denominator:
    # rate up alone; improvement: both down. Order of the WHENs is the logic.
    assert case.index("'consistent_worsening'") < case.index("'value_up_rate_masked'") \
        < case.index("'denominator_only'") < case.index("'improvement'") < case.index("'stable'")
    assert "s.delta_brl >= p_min_delta_brl" in case
    assert "(s.rate_end - s.rate_start) >= p_min_delta_pp" in case
    assert "s.delta_brl <= -p_min_delta_brl" in case


def test_stopped_reporting_and_missing_months_are_reported_not_filled():
    fn = _fn()
    assert "months_missing" in fn
    assert "stopped_reporting" in fn
    assert "s.last_month < (v_to - INTERVAL '1 month')::date" in fn


def test_thresholds_are_arguments_and_the_page_prints_them():
    fn = _fn()
    assert "p_min_delta_brl NUMERIC DEFAULT 1e6" in fn
    assert "p_min_delta_pp  NUMERIC DEFAULT 1.0" in fn
    assert "p_min_months    INT     DEFAULT 6" in fn
    page = PAGE.read_text(encoding="utf-8")
    assert "R$1mm" in page and "1 p.p." in page and "6 observations" in page


def test_every_source_exists_is_zero_row_safe_and_avoids_the_pct_tag():
    for name in SOURCE_NAMES:
        sql = (SOURCES / f"{name}.sql").read_text(encoding="utf-8").lower()
        assert "fidc_delinquency_drivers()" in sql, name
        if name != "fidc_drivers_summary":
            assert "where not exists" in sql, f"{name}: no zero-row guard"
        assert not re.search(r"\w+_pct\b", sql), f"{name}: _pct is an Evidence format tag"


def test_page_declares_every_source_and_the_caveats():
    page = PAGE.read_text(encoding="utf-8")
    for name in SOURCE_NAMES:
        assert f"```sql {name}\nselect * from supabase.{name}\n```" in page, name
        assert f"data={{{name}}}" in page, f"{name} declared but unused"
    assert "no sector, no debtor, no guarantee" in page
    assert "not a realised loss" in page
    assert "absent, never zero" in page


def test_function_is_granted_like_the_other_screens():
    body = SCREENS.read_text(encoding="utf-8")
    assert "GRANT EXECUTE ON FUNCTION fidc_delinquency_drivers(DATE, INT, INT, NUMERIC, NUMERIC) TO anon, authenticated;" in body
