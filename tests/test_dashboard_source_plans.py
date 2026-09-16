"""Evidence sources must not evaluate a function per fact row.

Measured on production (2026-09-16): dashboard/sources/supabase/aum_by_entity.sql
as merged in #228 took 37 minutes for 48 rows. Its anchor was a plain CTE and
the window predicate wrapped `f.period` in date_trunc(), so Postgres inlined
the CTE and ran the four latest_complete_period() calls inside the row filter
of an index-only scan over every fact row. Every dashboard build after #228
died at Vercel's 45-minute limit and the live site froze on the #226 build.
The sargable shape (materialized anchor, a range on the raw period column) runs
in 0.6 s. These pins keep the shape from drifting back.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "dashboard" / "sources" / "supabase"


def _sql(name: str) -> str:
    text = (SOURCES / name).read_text(encoding="utf-8")
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("--"))


def test_aum_by_entity_anchor_is_materialized_and_the_window_is_a_range_on_period():
    sql = _sql("aum_by_entity.sql")
    assert re.search(r"with\s+anchor\s+as\s+materialized\s*\(", sql, re.I), (
        "the anchor must be MATERIALIZED: inlined, its latest_complete_period() calls "
        "run once per fact row"
    )
    where = sql[sql.lower().index("where"):sql.lower().index("group by")]
    assert re.search(r"\bf\.period\s*>=", where) and re.search(r"\bf\.period\s*<", where), (
        "the 12-month window must be a range on the raw period column (an Index Cond), "
        "not an expression"
    )
    assert "date_trunc" not in where, "no date_trunc() on the fact column inside WHERE"
    assert "latest_complete_period" not in where, "the clamp is computed in the anchor, once"


def test_no_source_calls_latest_complete_period_inside_a_fact_row_filter():
    """A `latest_complete_period(<family>)` call in a WHERE that also compares
    the fact table's own period column is evaluated per row unless the planner
    can prove it constant; the per-family clamp `period <= latest_complete_period(entity_type)`
    is the one accepted form (a STABLE call the planner hoists, measured fast on
    every pre-#228 build)."""
    offenders = []
    for path in sorted(SOURCES.glob("*.sql")):
        sql = _sql(path.name).lower()
        if "as materialized" in sql:
            continue
        for m in re.finditer(r"where(.*?)(group by|order by|$)", sql, re.S):
            clause = m.group(1)
            if "least(" in clause and "latest_complete_period(" in clause and "period" in clause:
                offenders.append(path.name)
                break
    assert offenders == [], f"LEAST(latest_complete_period(...)) evaluated per row in: {offenders}"
