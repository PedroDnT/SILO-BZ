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
    # A page's inline ```sql block can name a column too, and that is a THIRD
    # place the suffix leaks in. It is also how a renamed source column goes
    # stale: rename `participacao_pct` to `participacao` in the source, update
    # every <Column id=...>, and the `select ..._pct from supabase.x` inside the
    # page still points at a column that no longer exists — a DuckDB "column not
    # found" at build time, caught on PR #235 by a review bot rather than here.
    inline_sql_column = re.compile(r"```sql\b.*?```", re.S)

    for path in (DASHBOARD / "sources").rglob("*.sql"):
        assert not sql_alias.search(path.read_text(encoding="utf-8")), path
    for path in (DASHBOARD / "pages").glob("*.md"):
        text = path.read_text(encoding="utf-8")
        assert not page_binding.search(text), path
        for block in inline_sql_column.findall(text):
            offenders = re.findall(r"\b[a-z0-9_]+_pct\b", block, re.IGNORECASE)
            assert not offenders, f"{path}: inline sql selects {sorted(set(offenders))}"


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


# --- Spine rule (dashboard/README.md, "Spine rule") --------------------------
#
# Every time-series source is a generate_series spine LEFT JOINed for zero-row
# safety, and no chart sets xMin/xMax, so the spine's last period IS the x-axis
# end. A spine that stops at the month in progress, or at the current calendar
# year, puts a month (or year) with no data on every chart it feeds. The rule:
# a spine ends at the last period that is over AND has data. These checks pin
# the mechanical half of it — no spine may stop at the open month/year — with
# an explicit allowlist for the two sources where the open period is the point.

SPINE_OPEN_PERIOD_ALLOWLIST = {
    "ops_daily_rows.sql",        # today's bar is legitimately 0 before the 06:00 cron
    "securit_maturity_wall.sql", # forward maturity ladder, not a history
}
B3_MATVIEW_SOURCES = {
    "b3_monthly_volume.sql",
    "b3_asset_class_volume.sql",
    "b3_options_activity.sql",
    "etf_market_series.sql",
}
OPEN_PERIOD = re.compile(
    r"date_trunc\('month',\s*current_date\)(?!\s*-\s*interval)"   # the open month
    r"|extract\(year from current_date\)"                          # the open year
    r"|(?<![a-z_.])current_date\s*$",                              # bare current_date as the stop
    re.IGNORECASE | re.MULTILINE,
)


def _generate_series_stops(sql: str) -> list[str]:
    """The second (stop) argument of every generate_series(...) call, comments
    stripped, top-level commas only."""
    sql = re.sub(r"--[^\n]*", "", sql)
    stops = []
    for m in re.finditer(r"generate_series\s*\(", sql, re.IGNORECASE):
        depth, i, args, buf = 1, m.end(), [], []
        while i < len(sql) and depth:
            ch = sql[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            if ch == "," and depth == 1:
                args.append("".join(buf).strip()); buf = []
            else:
                buf.append(ch)
            i += 1
        args.append("".join(buf).strip())
        if len(args) >= 2:
            stops.append(args[1])
    return stops


def test_there_are_spines_to_check():
    assert sum(len(_generate_series_stops(p.read_text(encoding="utf-8")))
               for p in (DASHBOARD / "sources").rglob("*.sql")) > 30


def test_monthly_spines_never_end_in_the_open_period():
    offenders = {}
    for path in sorted((DASHBOARD / "sources").rglob("*.sql")):
        if path.name in SPINE_OPEN_PERIOD_ALLOWLIST:
            continue
        bad = [s for s in _generate_series_stops(path.read_text(encoding="utf-8"))
               if OPEN_PERIOD.search(s)]
        if bad:
            offenders[path.name] = bad
    assert not offenders, (
        "spine stops at the month/year in progress — the chart draws a period "
        f"with no data:\n{offenders}"
    )


def test_b3_matview_sources_exclude_the_month_in_progress():
    """mv_b3_monthly_activity carries the open month with the sessions traded
    so far; drawn, it reads as a volume collapse."""
    for name in B3_MATVIEW_SOURCES:
        text = _read(f"dashboard/sources/supabase/{name}")
        assert "period < date_trunc('month', current_date)" in text, name


def test_cpi_chart_stops_at_its_own_last_reading():
    """macro_rate_series ends at the last ended month, which the monthly indices
    (published in M+1) usually have not reached; macro.md clamps that chart."""
    page = _read("dashboard/pages/macro.md")
    assert "```sql cpi_series" in page
    assert "data={cpi_series}" in page
    assert "ipca_mes_num2 is not null" in page
