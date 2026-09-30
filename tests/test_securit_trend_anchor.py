"""The /securit trend ends on the last complete month (issue #436).

Its spine used to end at the last ended month with ANY filing, so early filers
made a partial month the last point. On 2026-09-30 that was 2026-08, with
1,247 series against 2026-07's 6,810, and the value chart fell about 92%. The
owner chose the rule distressed_securities() already uses (register item 5):
the newest period holding at least half the previous period's rows.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TREND = ROOT / "dashboard/sources/supabase/securit_issuance_trend.sql"
FUNCTIONS = ROOT / "src/store/analytical/09_analytical_functions.sql"
RULE = r"n\s*>=\s*([0-9.]+)\s*\*\s*prev_n"


def _uncommented(path: Path) -> str:
    return re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))


def _distressed_body() -> str:
    sql = _uncommented(FUNCTIONS)
    start = sql.index("CREATE OR REPLACE FUNCTION distressed_securities(")
    open_tag = sql.index("$$", start)
    return sql[open_tag:sql.index("$$", open_tag + 2)]


def test_the_spine_does_not_end_on_any_filed_month():
    assert not re.search(r"max\(\s*data_referencia\s*\)", _uncommented(TREND), re.I)


def test_the_spine_uses_the_distressed_rule():
    """One rule for both readers. Pinning the threshold against the function's
    own keeps them from drifting apart silently."""
    trend = _uncommented(TREND)
    assert re.search(r"lag\(count\(\*\)\)\s+over\s*\(\s*order\s+by\s+period\s*\)", trend, re.I)
    assert "from fact_security_monthly" in trend
    ours = re.search(RULE, trend)
    theirs = re.search(RULE, _distressed_body())
    assert ours and theirs
    assert float(ours.group(1)) == float(theirs.group(1))


def test_only_ended_months_are_candidates():
    """An in-progress month holding half of a partial previous month would
    otherwise pass the rule."""
    assert re.search(
        r"period\s*<=\s*\(date_trunc\('month',\s*current_date\)\s*-\s*interval '1 month'\)::date",
        _uncommented(TREND),
    )
