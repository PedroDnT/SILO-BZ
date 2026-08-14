"""Regression checks for dashboard unit and economic-basis mistakes."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_percentage_point_outputs_do_not_use_evidence_pct_tag():
    """Evidence's ``_pct`` formatter multiplies an already-percent value by 100."""

    sql_alias = re.compile(r"\bas\s+[a-z0-9_]+_pct\b", re.IGNORECASE)
    page_binding = re.compile(r"(?:\by\s*=|<Column\s+id=)[^\n>]*_pct\b")

    for path in (DASHBOARD / "sources").rglob("*.sql"):
        assert not sql_alias.search(path.read_text(encoding="utf-8")), path
    for path in (DASHBOARD / "pages").glob("*.md"):
        assert not page_binding.search(path.read_text(encoding="utf-8")), path


def test_fi_quota_uses_one_stable_subclass_across_months():
    fact_sql = _read("src/store/analytical/04_fact_fund_monthly.sql")
    performance_sql = _read("src/store/analytical/17_performance_analysis.sql")

    assert "fi_quota_subclass AS" in fact_sql
    assert "p.id_subclasse = q.id_subclasse" in fact_sql
    assert "quota_subclass_id" in fact_sql
    assert "ARRAY_AGG(vl_quota ORDER BY vl_patrim_liq" not in fact_sql
    assert "m.entity_type <> 'fi' OR m.vl_quota > 0" in performance_sql
    assert "COALESCE(vl_quota, vl_patrim_liq)" not in performance_sql


def test_dashboard_does_not_present_pl_growth_as_return():
    class_summary = _read("dashboard/sources/supabase/class_summary.sql")
    ranking = _read("dashboard/sources/supabase/ranking_by_class.sql")
    series = _read("dashboard/sources/supabase/fund_perf_series.sql")

    true_return_bases = "('quota_return', 'dividend_yield')"
    assert true_return_bases in class_summary
    assert true_return_bases in ranking
    assert "s.entity_type in ('fi', 'fii')" in series


def test_null_latest_period_stays_blank_instead_of_unix_epoch():
    latest = _read("dashboard/sources/supabase/industry_class_latest.sql")
    assert "to_char(t.period, 'YYYY-MM-DD') as period" in latest

