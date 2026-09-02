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
    # Last-day PL is still summed across subclasses; quota is not.
    assert "SUM(p.vl_patrim_liq)" in fact_sql
    assert "MAX(p.vl_quota) FILTER (WHERE p.id_subclasse = q.id_subclasse)" in fact_sql


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



# ---------------------------------------------------------------------------
# Identity columns: manager, brand and index are three different things
# ---------------------------------------------------------------------------

def _source(name: str) -> str:
    return (DASHBOARD / "sources" / "supabase" / f"{name}.sql").read_text(encoding="utf-8")


def test_etf_sources_serve_the_published_manager_not_the_curated_brand():
    # cvm_etf_registry.gestor is CVM's published manager (cad_fi). `provider` is
    # a hand-curated seed label, and the fund NAME often carries the index
    # publisher ("TREND ETF BLOOMBERG ..."), which is neither. Serving only the
    # curated column made Bloomberg look like the manager of an XP fund.
    for name in ("etf_list", "etf_market"):
        sql = _source(name)
        assert "gestor" in sql and "as manager" in sql, (
            f"{name}.sql must expose cvm_etf_registry.gestor as manager"
        )
        assert "as brand" in sql, (
            f"{name}.sql must label the curated provider column as brand, so it "
            "is not mistaken for the manager"
        )


def test_etf_market_keeps_exchange_price_and_fund_nav_separate():
    sql = _source("etf_market")
    # An ETF's quota value and its exchange price are different published facts
    # (premium/discount lives between them); they must never be one column.
    assert "as price_date" in sql and "as nav_date" in sql, (
        "price and NAV come from different sources on different days — each "
        "needs its own as-of column"
    )
    assert "fator_cotacao" in sql, "exchange price must be the unit price"


def test_fiagro_source_clamps_the_start_as_well_as_the_end():
    sql = _source("industry_fiagro")
    assert "greatest(" in sql.lower(), (
        "FIAGRO's file starts 2025-05; a fixed-length window renders leading "
        "months that read as a collapse to zero. The spine start must be "
        "clamped to the family's first published period."
    )
    assert "min(period)" in sql.lower()


def test_monthly_formation_chart_excludes_the_yearly_filer():
    page = (DASHBOARD / "pages" / "industry.md").read_text(encoding="utf-8")
    chart = page[page.index("data={industry_new_funds}") : page.index("data={industry_new_funds}") + 400]
    assert "fip_new" not in chart, (
        "FIP files yearly and dim_fund stamps its first_period on 1 January, so "
        "plotting it on a monthly spine invents a January formation spike"
    )
