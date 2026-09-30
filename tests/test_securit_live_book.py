"""The /securit snapshot counts only live series (issue #434).

Four sources built their snapshot from each series' latest filing EVER, so the
series that stopped filing stayed in: 10,855 series against 6,862 live at
2026-07, and R$427.8 bn against R$376.8 bn. The owner chose a two-month
window. A series is live when its latest filing falls in the as-of month or
the month before. The as-of month is the one securit_issuance_trend.sql and
distressed_securities() resolve: the newest ended period holding at least half
the previous period's rows.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [
    ROOT / "dashboard/sources/supabase" / f"securit_{name}.sql"
    for name in ("overview", "ratings", "subordination", "maturity_wall")
]
FUNCTIONS = ROOT / "src/store/analytical/09_analytical_functions.sql"
RULE = r"n\s*>=\s*([0-9.]+)\s*\*\s*prev_n"


def _uncommented(path: Path) -> str:
    return re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))


def _distressed_threshold() -> float:
    sql = _uncommented(FUNCTIONS)
    start = sql.index("CREATE OR REPLACE FUNCTION distressed_securities(")
    open_tag = sql.index("$$", start)
    return float(re.search(RULE, sql[open_tag:sql.index("$$", open_tag + 2)]).group(1))


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.stem)
def test_the_as_of_month_uses_the_distressed_rule(path):
    sql = _uncommented(path)
    assert "from fact_security_monthly" in sql
    assert re.search(r"lag\(count\(\*\)\)\s+over\s*\(\s*order\s+by\s+period\s*\)", sql, re.I)
    m = re.search(RULE, sql)
    assert m and float(m.group(1)) == _distressed_threshold()
    assert re.search(
        r"period\s*<=\s*\(date_trunc\('month',\s*current_date\)\s*-\s*interval '1 month'\)::date",
        sql,
    )


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.stem)
def test_the_snapshot_is_the_two_month_live_window(path):
    """The latest filing EVER kept series that stopped filing. The as-of month
    alone halves the book while that month is still being filed (3,763 series
    against 6,824 with 2026-07 at 55%)."""
    sql = _uncommented(path)
    assert re.search(r"s\.data_referencia\s*>=\s*\(a\.p_end\s*-\s*interval '1 month'\)::date", sql)
    assert re.search(r"s\.data_referencia\s*<\s*\(a\.p_end\s*\+\s*interval '1 month'\)::date", sql)
    assert "where s.data_referencia is not null" not in sql


def test_the_overview_dates_its_tiles():
    """The tiles are as of one month, so the page shows that month, not the
    newest filing anyone made."""
    sql = _uncommented(SOURCES[0])
    assert re.search(r"\(select p_end from as_of\)\s+as as_of_period", sql)
    assert "max(data_referencia)" not in sql
