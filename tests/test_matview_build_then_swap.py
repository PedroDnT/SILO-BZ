"""dim_fund and fact_fund_monthly rebuild beside the live copy, then swap (#1175).

The analytical apply used to open 01_dim_fund.sql and 04_fact_fund_monthly.sql
with DROP MATERIALIZED VIEW ... CASCADE and build the replacement in the same
transaction, so the DROP's AccessExclusiveLock lasted the whole build (70 s and
299 s on 2026-11-16). Every reader queued behind it, and anon's 3 s
statement_timeout answered api.search_funds and api.coverage with 57014 for as
long as the files ran: the v2 eval's `timeout` errors.

Now each file builds in the staging schema analytical_build while public keeps
serving, and a short last transaction drops the old matviews and moves the new
ones in. These tests pin that shape: the transaction that drops a live matview
builds nothing, and the transaction that builds drops nothing in public. The
sql-compile job in test.yml executes it (an anonymous search and freshness call
during a paused rebuild).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ANALYTICAL = ROOT / "src" / "store" / "analytical"

# file -> the matviews it rebuilds
FILES = {
    "01_dim_fund.sql": ("dim_fund",),
    "04_fact_fund_monthly.sql": ("fact_fund_monthly", "mv_period_completeness", "mv_metric_coverage"),
}


def _transactions(name: str) -> list[str]:
    sql = re.sub(r"--[^\n]*", "", (ANALYTICAL / name).read_text(encoding="utf-8"))
    # Top-level BEGIN; / COMMIT; only (a DO block's BEGIN has no semicolon).
    blocks = re.findall(r"^BEGIN;\s*$(.*?)^COMMIT;\s*$", sql, re.S | re.M)
    assert blocks, f"{name}: no BEGIN; ... COMMIT; transaction found"
    return blocks


def _build_and_swap(name: str) -> tuple[str, str]:
    txs = _transactions(name)
    assert len(txs) == 2, f"{name}: expected a build transaction and a swap transaction, got {len(txs)}"
    return txs[0], txs[1]


@pytest.mark.parametrize("name", sorted(FILES))
def test_build_lands_in_the_staging_schema(name):
    build, _ = _build_and_swap(name)
    assert "set_config('search_path', 'analytical_build, ' || current_setting('search_path'), true)" in build
    assert "DROP SCHEMA IF EXISTS analytical_build CASCADE;" in build
    assert "CREATE SCHEMA analytical_build;" in build
    for mv in FILES[name]:
        assert re.search(rf"CREATE MATERIALIZED VIEW {mv} AS", build), f"{name}: {mv} is not built here"


@pytest.mark.parametrize("name", sorted(FILES))
def test_build_transaction_drops_no_live_matview(name):
    """On the staging search_path an unqualified DROP falls through to public."""
    build, _ = _build_and_swap(name)
    assert not re.search(r"DROP\s+(MATERIALIZED\s+)?VIEW", build, re.I), (
        f"{name}: a DROP in the build transaction takes the live matview's "
        "AccessExclusiveLock for the whole build, the #1175 timeouts"
    )


@pytest.mark.parametrize("name", sorted(FILES))
def test_swap_transaction_builds_nothing(name):
    _, swap = _build_and_swap(name)
    assert not re.search(r"CREATE\s+(UNIQUE\s+)?(MATERIALIZED\s+VIEW|INDEX)", swap, re.I), (
        f"{name}: the swap holds AccessExclusiveLock; a build inside it blocks readers again"
    )
    for mv in FILES[name]:
        assert f"ALTER MATERIALIZED VIEW analytical_build.{mv} SET SCHEMA public;" in swap
    assert re.search(r"^DROP SCHEMA analytical_build;", swap, re.M), (
        "the staging schema is dropped RESTRICT, so a leftover object fails the swap"
    )
    # The drop of the old copy is schema-qualified: no search_path can redirect it.
    for stmt in re.findall(r"DROP\s+(?:MATERIALIZED\s+)?VIEW[^;']*", swap, re.I):
        assert "public." in stmt, f"{name}: unqualified drop in the swap: {stmt!r}"


def test_fact_swap_drops_the_old_dependents_before_moving_the_new_ones():
    _, swap = _build_and_swap("04_fact_fund_monthly.sql")
    drop = swap.index("DROP MATERIALIZED VIEW IF EXISTS public.fact_fund_monthly CASCADE;")
    for mv in FILES["04_fact_fund_monthly.sql"]:
        assert drop < swap.index(f"ALTER MATERIALIZED VIEW analytical_build.{mv} SET SCHEMA public;")
    # latest_complete_period and its grants are created on public, after the move.
    assert swap.index("SET SCHEMA public") < swap.index("CREATE OR REPLACE FUNCTION latest_complete_period")
    assert "GRANT SELECT ON mv_period_completeness TO anon, authenticated;" in swap
