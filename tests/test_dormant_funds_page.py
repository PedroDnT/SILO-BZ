"""The Dormant Funds page (/dormant) and the two screen functions behind it.

The page answers "are there more parked fund CNPJs than listed companies?"
Health diagnostic 16 measured it at daily grain on 2026-09-02: 61 empty shells
against 670 companies (no), 8,257 parked-capital classes (12x, yes). These
tests pin the properties that made that number honest, so the dashboard copy of
the screen cannot drift into a looser one:

  * NULL is not zero — an unreported flow or quotaholder month disqualifies.
  * A fund must be present in every month of the window.
  * FI only: fact_fund_monthly carries flows for no other family.
  * The window is anchored on latest_complete_period('fi'), never CURRENT_DATE.
  * Every source can never return zero rows (a 0-byte parquet kills the build).
  * The page's SQL blocks reference only sources that exist.
  * One lookback literal per source, and it is the same everywhere.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCREENS = ROOT / "src/store/analytical/15_fraud_screens.sql"
SOURCES = ROOT / "dashboard/sources/supabase"
PAGE = ROOT / "dashboard/pages/dormant.md"

DORMANT_SOURCES = sorted(SOURCES.glob("dormant_*.sql"))


def _strip(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


def _function(name: str) -> str:
    body = SCREENS.read_text(encoding="utf-8")
    start = body.index(f"CREATE OR REPLACE FUNCTION {name}(")
    end = body.index("$$;", start) + 3
    return body[start:end]


# --- the screen functions ---------------------------------------------------


class TestScreenFunctions:
    @pytest.mark.parametrize("name", ["fraud_screen_dormant_funds", "fraud_screen_dormant_trend"])
    def test_exists_and_is_granted(self, name):
        body = SCREENS.read_text(encoding="utf-8")
        assert f"CREATE OR REPLACE FUNCTION {name}(" in body
        assert re.search(rf"GRANT EXECUTE ON FUNCTION {name}\(", body), f"{name} has no GRANT"
        assert f"• {name}(" in body, f"{name} missing from the file header list"

    @pytest.mark.parametrize("name", ["fraud_screen_dormant_funds", "fraud_screen_dormant_trend"])
    def test_fi_only(self, name):
        assert "f.entity_type = 'fi'" in _function(name), (
            "fact_fund_monthly carries captc_mes/resg_mes for FI alone; the other "
            "families are NULL and would read as 'no flow'"
        )

    @pytest.mark.parametrize("name", ["fraud_screen_dormant_funds", "fraud_screen_dormant_trend"])
    def test_null_flows_disqualify_rather_than_count_as_zero(self, name):
        fn = _function(name)
        assert "captc_mes IS NOT NULL AND" in fn and "resg_mes IS NOT NULL" in fn
        assert "nr_cotst IS NOT NULL" in fn
        assert not re.search(r"coalesce\s*\(\s*\w*\.?captc_mes", fn, re.I), "captc_mes must not be coalesced"
        assert not re.search(r"coalesce\s*\(\s*\w*\.?resg_mes", fn, re.I), "resg_mes must not be coalesced"
        assert not re.search(r"coalesce\s*\(\s*\w*\.?nr_cotst", fn, re.I), "nr_cotst must not be coalesced"

    @pytest.mark.parametrize("name", ["fraud_screen_dormant_funds", "fraud_screen_dormant_trend"])
    def test_window_is_anchored_on_completeness_not_today(self, name):
        fn = _function(name)
        assert "latest_complete_period('fi')" in fn
        assert "CURRENT_DATE" not in fn, "a partially-filed current month would read as zero flow"

    def test_funds_screen_requires_every_month_present(self):
        assert "p.months_observed = p_lookback_months" in _function("fraud_screen_dormant_funds")

    def test_trend_uses_a_range_frame_so_gaps_drop_out(self):
        fn = _function("fraud_screen_dormant_trend")
        assert "RANGE BETWEEN" in fn and "ROWS BETWEEN" not in fn, (
            "a ROWS frame would let three non-adjacent filings pass as three months"
        )
        assert "months_observed = p_lookback_months" in fn

    def test_classification_is_by_zero_investors(self):
        fn = _function("fraud_screen_dormant_funds")
        assert "WHEN p.max_investors = 0 THEN 'empty_shell'" in fn
        assert "'parked_capital'" in fn


# --- the sources ------------------------------------------------------------


class TestSources:
    def test_there_are_dormant_sources(self):
        names = {p.name for p in DORMANT_SOURCES}
        assert names == {
            "dormant_headline.sql",
            "dormant_trend.sql",
            "dormant_shells.sql",
            "dormant_parked_top.sql",
            "dormant_by_admin.sql",
            "dormant_admin_coverage.sql",
        }

    @pytest.mark.parametrize("path", DORMANT_SOURCES, ids=lambda p: p.name)
    def test_source_can_never_return_zero_rows(self, path: Path):
        body = _strip(path.read_text(encoding="utf-8")).lower()
        is_spine = "generate_series(" in body and "left join" in body
        # a no-GROUP-BY aggregate: count(*) present and no bare `group by` on a
        # hit column (dormant_headline groups by its constant bounds only)
        is_aggregate = "count(" in body and (
            "group by" not in body or "group by b.win_from" in body
        )
        assert is_spine or is_aggregate, (
            f"{path.name} must be a spine + LEFT JOIN or a no-GROUP-BY aggregate; "
            "a 0-row source writes a 0-byte parquet and kills the whole build"
        )

    @pytest.mark.parametrize("path", DORMANT_SOURCES, ids=lambda p: p.name)
    def test_source_uses_the_same_lookback(self, path: Path):
        body = _strip(path.read_text(encoding="utf-8"))
        literals = set(re.findall(r"fraud_screen_dormant_(?:funds|trend)\(\s*(\d+|p\.lookback)", body))
        params = set(re.findall(r"select\s+(\d+)\s+as\s+lookback", body, re.I))
        assert (literals | params) <= {"3", "p.lookback"}, (
            f"{path.name} passes a lookback other than 3: {literals | params}. "
            "Every dormant_* source and the page's stated threshold must agree."
        )

    def test_headline_dates_are_strings_not_raw_dates(self):
        body = SOURCES.joinpath("dormant_headline.sql").read_text(encoding="utf-8")
        assert "to_char(b.win_from, 'YYYY-MM-DD')" in body
        assert "to_char(b.win_to,   'YYYY-MM-DD')" in body

    def test_headline_company_count_does_not_drop_null_situacao(self):
        body = SOURCES.joinpath("dormant_headline.sql").read_text(encoding="utf-8")
        assert "coalesce(situacao, '') <> 'CANCELADA'" in body

    def test_no_source_reads_the_daily_tape(self):
        for path in DORMANT_SOURCES:
            body = _strip(path.read_text(encoding="utf-8")).lower()
            assert "cvm_fi_diario" not in body, f"{path.name} must read fact_fund_monthly, not the tape"

    def test_no_percentage_alias_ends_in_pct(self):
        """Evidence's _pct formatter multiplies an already-percent value by 100."""
        for path in DORMANT_SOURCES:
            assert not re.search(r"\bas\s+\w+_pct\b", path.read_text(encoding="utf-8"), re.I), path.name


# --- the page ---------------------------------------------------------------


class TestPage:
    def test_every_page_source_exists(self):
        page = PAGE.read_text(encoding="utf-8")
        referenced = set(re.findall(r"from supabase\.(\w+)", page))
        assert referenced, "the page references no sources"
        for name in referenced:
            assert (SOURCES / f"{name}.sql").exists(), f"page references missing source {name}"
        assert referenced == {p.stem for p in DORMANT_SOURCES}, "page and sources are out of sync"

    def test_list_blocks_filter_the_slot_spine_nulls(self):
        page = PAGE.read_text(encoding="utf-8")
        for name, col in (
            ("dormant_shells", "cnpj"),
            ("dormant_parked_top", "cnpj"),
            ("dormant_by_admin", "admin_name"),
        ):
            assert re.search(rf"from supabase\.{name}\s+where {col} is not null", page), (
                f"the {name} block must filter the slot spine's NULL rows in DuckDB"
            )

    def test_page_states_its_threshold_and_disclaims_zombie(self):
        page = PAGE.read_text(encoding="utf-8")
        assert "3 complete months" in page
        assert "floor" in page
        assert "/suspicious" in page and "zombie growth" in page, (
            "the page must say why it is not the FIDC zombie-growth screen"
        )

    def test_page_is_linked_from_the_index_and_readme(self):
        assert "(/dormant)" in (ROOT / "dashboard/pages/index.md").read_text(encoding="utf-8")
        assert "`/dormant`" in (ROOT / "README.md").read_text(encoding="utf-8")
