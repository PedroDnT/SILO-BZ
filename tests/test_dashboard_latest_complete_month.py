"""Single-month dashboard sources read the latest COMPLETE month.

A month opens thin: CVM's early filers land weeks before the rest. On
2026-10-04 the newest FII month held 8 filings with no yield and
top_fii_yield wrote 0 rows, which failed the production build (#599). On
2026-10-05 the newest FIDC month held 428 of ~4,400 funds, so every FIDC
source that took max(period) would rank the early filers alone. Each source
below anchors on least(latest_complete_period(<family>), max(period)) in a
MATERIALIZED CTE, so the clamp runs once (tests/test_dashboard_source_plans.py).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SOURCES = Path(__file__).resolve().parents[1] / "dashboard" / "sources" / "supabase"

ANCHORED = {
    "top_fii_yield.sql": "fii",
    "fidc_flows_by_oper.sql": "fidc",
    "fidc_subordination_top.sql": "fidc",
    "fidc_tranche_performance.sql": "fidc",
    "fidc_tranche_underperformers.sql": "fidc",
    "top_delinquent.sql": "fidc",
}


def _code(name: str) -> str:
    text = (SOURCES / name).read_text(encoding="utf-8")
    return re.sub(r"\s+", " ", re.sub(r"--[^\n]*", "", text))


@pytest.mark.parametrize("name,family", sorted(ANCHORED.items()))
def test_the_month_is_clamped_to_the_latest_complete_one(name, family):
    code = _code(name)
    assert re.search(
        rf"as materialized \( select least\( latest_complete_period\('{family}'\), \(select max\(period\) from \w+",
        code,
    ), f"{name}: anchor on least(latest_complete_period('{family}'), max(period)), materialized"
    # The bare form is gone: no source compares a period with a raw max(period).
    assert not re.search(r"period = \(select max\(period\)", code), name
    assert "with latest as ( select max(period)" not in code, name
