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

import pytest

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


# ---------------------------------------------------------------------------
# The same class of bug, one layer down: finding ONE date by scanning a whole
# landing table.
#
# #233 pushed the build back over Vercel's 45-minute limit (main's own
# production build for 0622e47 and every branch build after it died with
# BUILD_EXCEEDED_MAXIMUM_TIME). Source evaluation alone ran 31m36s, and the
# three slowest sources -- fi_concentration 6m12s, fi_top_aplic 5m10s,
# fi_perfil_coverage 4m12s, 15m34s between them -- all opened with the same
# anchor: `max(period) FILTER (WHERE period <= <clamp>)` over a raw landing
# table.
#
# An aggregate FILTER blocks Postgres's index MIN/MAX rewrite, so that form
# reads EVERY row to return one date. `api.coverage()` already carries the same
# lesson ("only the equality form gets the MIN/MAX index rewrite"). Measured on
# the ephemeral database with 48,000 cvm_fi_perfil rows (2026-09-16), both forms
# returning the identical date:
#
#   max(period) FILTER (...)        Seq Scan, 48,000 rows, 1,101 buffers, 304 ms
#   ORDER BY period DESC LIMIT 1    Index Only Scan,           15 buffers, 0.3 ms
#
# The FILTER form is O(table); production holds far more than 48,000 rows, and
# the gap grows with every ingest.
# ---------------------------------------------------------------------------

#: Landing tables large enough that a full scan to find one date costs minutes.
BIG_LANDING_TABLES = ("cvm_fi_perfil", "cvm_fi_cda")

#: The three sources whose anchors were rewritten.
ANCHORED_SOURCES = ("fi_concentration.sql", "fi_perfil_coverage.sql", "fi_top_aplic.sql")

_MAX_FILTER = re.compile(r"max\s*\(\s*[a-z_.]*period\s*\)\s*filter", re.I)


def test_no_source_finds_a_date_by_scanning_a_big_landing_table():
    """`max(period) FILTER (...)` over a landing table seq-scans it for one date."""
    offenders = []
    for path in sorted(SOURCES.glob("*.sql")):
        sql = _sql(path.name).lower()
        if not any(t in sql for t in BIG_LANDING_TABLES):
            continue
        if _MAX_FILTER.search(sql):
            offenders.append(path.name)
    assert offenders == [], (
        "max(period) FILTER (...) cannot use the index MIN/MAX rewrite, so it reads "
        f"the whole table to find one date; use ORDER BY period DESC LIMIT 1 in: {offenders}"
    )


@pytest.mark.parametrize("name", ANCHORED_SOURCES)
def test_the_anchor_walks_the_period_index_and_pins_the_clamp(name):
    sql = _sql(name)
    low = sql.lower()
    assert re.search(r"bound\s+as\s+materialized\s*\(", low), (
        f"{name}: the latest_complete_period() clamp must be pinned to ONE evaluation; "
        "STABLE only means the planner MAY hoist it, and #231 measured it not hoisting"
    )
    assert re.search(r"order\s+by\s+t\.period\s+desc\s+limit\s+1", low), (
        f"{name}: the anchor must walk the period index and stop at the first row"
    )
    assert not _MAX_FILTER.search(low), f"{name}: the aggregate-FILTER anchor is back"
