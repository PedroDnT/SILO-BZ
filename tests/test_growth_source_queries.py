"""The /growth page pinned itself to an almost-unfiled fiscal year.

`webapp/sources/supabase/cia_growth_*.sql` selected the comparison year with
`MAX(fy)`. That is wrong for CVM data and the reason the whole page collapsed to
six companies in one sector: a fiscal year exists in `cia_account` the moment its
first filer reports, and the filing calendar is not synchronised. Sugar and
ethanol names run April-March and file a full year ahead of calendar-year filers,
so measured 2026-09-17 fiscal 2026 held 8 filers against fiscal 2025's 438.

Reproduced and fixed against a local fixture (66 ordinary companies in 3 sectors
plus 6 early filers): the old query returned 1 sector / 6 companies at fy2026,
the fixed query returns 4 sectors / 66 companies at fy2025 with the early filers
still present on their fy2025 row.

This is the same family as the warning in CLAUDE.md about `complete_through` and
FIP being keyed 31-December: a MAX() over a filing date is not "the current
period".
"""

from __future__ import annotations

from pathlib import Path

import pytest

SOURCES = Path(__file__).resolve().parents[1] / "webapp/sources/supabase"
GROWTH = ["cia_growth_company.sql", "cia_growth_sector.sql"]


def _sql(name: str) -> str:
    return (SOURCES / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", GROWTH)
def test_the_comparison_year_is_not_a_bare_max(name: str) -> None:
    """`MAX(fy)` alone is the bug. The selection must be coverage-gated."""
    sql = _sql(name)
    assert "SELECT MAX(fy) AS fy FROM scoped" not in sql, (
        f"{name} picks the comparison year with a bare MAX(fy) over every year "
        "present. A fiscal year appears as soon as its first filer reports, so "
        "this pins the page to a handful of early (April-March) filers. Gate it "
        "on how many comparable companies the year actually has."
    )
    assert "HAVING COUNT(*) >= 50" in sql, (
        f"{name} must require a minimum number of comparable companies before "
        "using a fiscal year as the comparison year."
    )


@pytest.mark.parametrize("name", GROWTH)
def test_the_version_lookup_is_date_bounded(name: str) -> None:
    """Unbounded, latest_ver aggregated every DRE partition back to 2010.

    ~857k rows at a planner cost of 1.33M, to resolve versions for years the page
    never displays — which is why it timed out at the Supabase gateway. It also
    now pins doc_type, so it cannot pick a version from a filing the page will
    not read.
    """
    sql = _sql(name)
    head = sql[sql.index("WITH latest_ver AS ("): sql.index("annual AS (")]
    assert "dt_refer >= (CURRENT_DATE - INTERVAL '5 years')" in head, (
        f"{name}: latest_ver must be bounded by dt_refer"
    )
    assert "doc_type = 'dfp'" in head, (
        f"{name}: latest_ver must pin doc_type, matching what the page reads"
    )


@pytest.mark.parametrize("name", GROWTH)
def test_net_income_has_no_3_09_fallback(name: str) -> None:
    """Matches api.company_financials (catalog v28): 3.11 only, null stays null."""
    sql = _sql(name)
    assert "'3.11'" in sql
    assert "'3.09'" not in sql.replace("no 3.09 fallback", ""), (
        f"{name}: 3.09 is profit BEFORE statutory profit-sharing, not net income"
    )


@pytest.mark.parametrize("name", GROWTH)
def test_the_accent_on_ultimo_survives(name: str) -> None:
    """The source is latin-1; an unaccented 'ULTIMO' matches zero rows."""
    assert "'ÚLTIMO'" in _sql(name), f"{name}: ordem_exerc must carry the accent"
