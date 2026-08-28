"""No dashboard source may aggregate the full COTAHIST tape.

On 2026-08-28 the production dashboard build (Vercel dpl_7KGd3f6ryn3NcikxdBpTSzwuR9D8)
failed on Vercel's 45-minute ceiling. Its log stops immediately before
`b3_monthly_volume`, which was measured running 26 minutes against production:
it aggregated all of b3_cotahist, 2019-2026, to produce ~92 rows. Four more
sources did the same. Those scans also held AccessShareLock long enough to fail
two schema applies the same day — one cause, three symptoms.

mv_b3_monthly_activity (migration 30) does that pass once a day. These tests
stop it drifting back: a source that reads the tape must bound what it reads.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SOURCES = Path(__file__).resolve().parents[1] / "dashboard" / "sources" / "supabase"

# Relations that mean "the raw tape" — b3_cotahist and the views over it.
TAPE = re.compile(r"\b(from|join)\s+(b3_cotahist|vw_b3_instrument_typed|vw_b3_quote_vista)\b", re.I)
# A bound on the partition key, or a join to the precomputed monthly aggregate.
BOUNDED = re.compile(r"trade_date\s*(>=|>|between)|mv_b3_monthly_activity", re.I)


def _strip_sql_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


def _tape_readers() -> list[Path]:
    return sorted(p for p in SOURCES.glob("*.sql") if TAPE.search(_strip_sql_comments(p.read_text(encoding="utf-8"))))


def test_there_are_tape_readers_to_check():
    """Guard the guard: a rename must not silently empty this suite."""
    assert _tape_readers(), "no dashboard source reads b3_cotahist — did a relation get renamed?"


@pytest.mark.parametrize("path", _tape_readers(), ids=lambda p: p.name)
def test_tape_reader_is_bounded_or_uses_the_aggregate(path: Path):
    body = _strip_sql_comments(path.read_text(encoding="utf-8"))
    assert BOUNDED.search(body), (
        f"{path.name} reads the COTAHIST tape with no trade_date bound and without "
        "mv_b3_monthly_activity. That is a full scan of the largest table in the "
        "warehouse on every dashboard build — it cost a production deploy on "
        "2026-08-28. Read the matview, or bound trade_date."
    )


def test_the_five_rewritten_sources_read_the_matview():
    """Pin the specific sources the 2026-08-28 failure was traced to."""
    for name in (
        "b3_monthly_volume.sql",
        "b3_options_activity.sql",
        "b3_asset_class_volume.sql",
        "etf_market_series.sql",
        "b3_market_overview.sql",
    ):
        body = (SOURCES / name).read_text(encoding="utf-8")
        assert "mv_b3_monthly_activity" in body, f"{name} must read the monthly aggregate"


def test_grain_is_filtered_explicitly_never_by_null():
    """A NULL subtype means 'rolled up' on one row and 'no subtype' on another.

    Only the grain label separates them, so every matview reader must say which
    grain it wants rather than inferring it from IS NULL.
    """
    for path in SOURCES.glob("*.sql"):
        body = _strip_sql_comments(path.read_text(encoding="utf-8"))
        if "mv_b3_monthly_activity" not in body:
            continue
        # b3_market_overview only reads max(period) — no grain needed there.
        if "max(period)" in body.lower() and "grain" not in body.lower():
            continue
        assert re.search(r"grain\s*=", body, re.I), (
            f"{path.name} reads mv_b3_monthly_activity without filtering on grain; "
            "it would sum rolled-up rows together with detail rows"
        )
