"""Offline assertions over 20_short_interest.sql and migration 39.

No database: these parse the SQL text and assert the invariants that make the
short-interest numbers trustworthy. A real apply is still the analytics-only
dispatch's job — a substring test is not proof the SQL runs — but these catch
the specific regressions that would produce a plausible WRONG number, which
is worse than an error.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SQL_PATH = ROOT / "src" / "store" / "analytical" / "20_short_interest.sql"
MIG_PATH = ROOT / "src" / "store" / "migrations" / "39_b3_lending_flow.sql"
SCHEMA_PATH = ROOT / "src" / "store" / "schema.sql"

SQL = SQL_PATH.read_text(encoding="utf-8")
MIG = MIG_PATH.read_text(encoding="utf-8")
SCHEMA = SCHEMA_PATH.read_text(encoding="utf-8")


def strip_comments(text: str) -> str:
    return re.sub(r"--[^\n]*", "", text)


SQL_CODE = strip_comments(SQL)
MIG_CODE = strip_comments(MIG)


# ── the double-count guard ────────────────────────────────────────────────


def test_short_interest_reads_only_b3s_total_rows():
    """B3 publishes per-market rows AND their own 'Total' sum for each group.

    Reading both doubles every short balance, which would look entirely
    plausible on a dashboard. The fact view must filter.
    """
    fact = SQL_CODE.split("CREATE OR REPLACE VIEW fact_short_interest_daily")[1]
    position_cte = fact.split("rate AS")[0]
    assert "b3_lending_open_position" in position_cte
    assert re.search(r"WHERE\s+p\.is_total", position_cte), (
        "fact_short_interest_daily must filter on is_total or it double-counts"
    )


def test_is_total_column_exists_in_both_schema_and_migration():
    for name, text in (("migration 39", MIG_CODE), ("schema.sql", SCHEMA)):
        assert "is_total" in text, f"{name} is missing the is_total double-count guard"


# ── denominators are never faked ──────────────────────────────────────────


@pytest.mark.parametrize("metric", ["pct_float", "days_to_cover"])
def test_ratios_are_null_when_their_denominator_is_missing(metric):
    """A missing float or a name that did not trade yields NULL, never 0.

    0% float reads as "nobody is short"; 0 days to cover sorts an untradeable
    position to the safe end of a risk screen. Both are lies.
    """
    body = SQL_CODE.split(f"END                                   AS {metric}")[0]
    tail = body[-600:]
    assert "THEN NULL" in tail, f"{metric} must resolve to NULL on a missing denominator"


def test_float_basis_is_published_beside_every_percentage():
    """% of free float and % of shares outstanding are different metrics."""
    assert "float_basis" in SQL_CODE
    assert "'index_free_float'" in SQL_CODE
    assert "'shares_outstanding'" in SQL_CODE
    api = SQL_CODE.split("CREATE OR REPLACE VIEW api.short_interest AS")[1]
    assert "float_basis" in api.split(";")[0], (
        "api.short_interest must expose float_basis next to pct_float"
    )


def test_free_float_prefers_the_least_capped_index():
    """Index weight caps only shrink theoretical_qty below the true float.

    Verified 2026-09-16: PETR3 is 3,478,479,815 in IBRA but 2,441,951,100 in
    IBOV. Taking whichever row sorted first would understate the float and so
    overstate every short percentage on the biggest names.
    """
    order = SQL_CODE.split("latest_index AS")[1].split("latest_instrument AS")[0]
    for code in ("'IBRA'", "'SMLL'", "'IBXX'", "'IBOV'"):
        assert code in order, f"index priority is missing {code}"
    assert order.index("'IBRA'") < order.index("'IBOV'"), (
        "IBOV must rank last: its weight caps shrink theoretical_qty below the real float"
    )


# ── the month-boundary guard ──────────────────────────────────────────────


def test_investor_flow_never_differences_across_a_month():
    """MTD resets on the 1st; a LAG across it reports a month as one day."""
    flow = SQL_CODE.split("CREATE OR REPLACE VIEW fact_investor_flow_daily")[1]
    window = flow.split("WINDOW w AS")[1].split(")")[0]
    assert "date_trunc('month'" in window, (
        "the LAG window must be partitioned by month or it subtracts across the reset"
    )


def test_investor_flow_marks_an_opening_snapshot_it_cannot_interpret():
    """The first snapshot we hold may not be the month's first session.

    Treating that MTD total as one day's flow would invent a spike on an
    arbitrary date — exactly what happened on the day this pipeline was first
    deployed mid-month.
    """
    flow = SQL_CODE.split("CREATE OR REPLACE VIEW fact_investor_flow_daily")[1]
    assert "'unknown_opening_snapshot'" in flow
    assert "first_session" in flow
    basis = flow.split("AS flow_basis")[0][-500:]
    assert "'month_open'" in basis


# ── privilege boundary (same stance as 12 and 19) ─────────────────────────


@pytest.mark.parametrize("table", [
    "b3_lending_open_position",
    "b3_lending_rate",
    "b3_investor_participation",
    "b3_investor_participation_monthly",
    "b3_index_portfolio",
    "b3_instrument_registry",
])
def test_landing_tables_are_revoked_from_client_roles(table):
    assert re.search(rf"REVOKE ALL ON TABLE\s+{table}\s+FROM anon, authenticated", SQL_CODE), (
        f"{table} is a landing table and must stay closed to anon/authenticated"
    )


@pytest.mark.parametrize("view", ["short_interest", "short_interest_by_sector", "investor_flow"])
def test_api_views_are_owner_privileged_and_granted(view):
    assert f"ALTER VIEW api.{view} SET (security_invoker = false)" in SQL_CODE, (
        f"api.{view} must be owner-privileged so its grant never implies one on the tape"
    )
    assert re.search(rf"GRANT SELECT ON api\.{view} TO anon, authenticated", SQL_CODE)


# ── idempotent apply ──────────────────────────────────────────────────────


def test_views_are_dropped_before_recreation():
    """CREATE OR REPLACE cannot insert a column mid-list; these views grow."""
    for view in ("fact_short_interest_daily", "dim_ticker_float", "vw_b3_adtv_21",
                 "vw_short_by_sector", "fact_investor_flow_daily"):
        assert f"DROP VIEW IF EXISTS {view}" in SQL_CODE, f"{view} has no guarded DROP"


def test_migration_is_idempotent_and_keyed():
    for table in ("b3_lending_open_position", "b3_lending_rate",
                  "b3_investor_participation", "b3_investor_participation_monthly",
                  "b3_index_portfolio", "b3_instrument_registry"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in MIG_CODE
        assert f"uq_{table}" in MIG_CODE, f"{table} has no named UNIQUE constraint"


def test_schema_and_migration_agree_on_every_table():
    """schema.sql stays canonical; migrations are append-only."""
    tables = re.findall(r"CREATE TABLE IF NOT EXISTS (b3_\w+)", MIG_CODE)
    assert len(tables) == 6
    for t in tables:
        assert f"CREATE TABLE IF NOT EXISTS {t}" in SCHEMA, f"{t} never reached schema.sql"


def test_the_retention_ratchet_is_documented_where_an_operator_will_see_it():
    """A gap here is permanent. The DDL must say so, not just the fetcher."""
    assert re.search(r"21[- ]BUSINESS[- ]DAY|21 business day", MIG, re.IGNORECASE)
    assert "backfill" in MIG.lower()


# ── zero-row safety on a fresh deploy ─────────────────────────────────────

DASHBOARD = ROOT / "dashboard"

# Sources that are a single aggregate row by construction (max() over an empty
# table still returns one row), so they cannot emit the 0-byte parquet.
_SINGLE_ROW_SOURCES = {"short_headline", "flow_headline"}


def _new_sources():
    return sorted(
        p for p in (DASHBOARD / "sources" / "supabase").glob("*.sql")
        if p.stem.startswith(("short_", "flow_"))
    )


def test_every_new_source_exists():
    assert len(_new_sources()) == 12


@pytest.mark.parametrize("path", _new_sources(), ids=lambda p: p.stem)
def test_new_sources_survive_an_empty_database(path):
    """These tables are empty until the first daily run — and B3 has no archive.

    A zero-row Evidence source writes a 0-byte parquet that kills the whole
    dashboard build, not just its own page. Every other dataset here is
    backfilled before a deploy ever sees it; these cannot be, so the empty
    window is real on every fresh database. Verified against an empty Postgres
    during development: 10 of the 12 returned zero rows before the guard.
    """
    body = strip_comments(path.read_text(encoding="utf-8"))
    if path.stem in _SINGLE_ROW_SOURCES:
        assert "max(" in body.lower(), (
            f"{path.stem} is listed as single-row but has no aggregate to guarantee it"
        )
        return
    assert re.search(r"union\s+all", body, re.IGNORECASE), (
        f"{path.stem} is a ranked/grouped source with no union-all sentinel: it "
        "returns zero rows on a fresh database and takes the whole build with it"
    )
    assert re.search(r"where\s+not\s+exists\s*\(\s*select\s+1", body, re.IGNORECASE), (
        f"{path.stem}'s sentinel is not gated on `where not exists (select 1 ...)`, "
        "so it would emit a null row even when real data exists"
    )


# ── the deploy-vs-migration race ──────────────────────────────────────────

PREFLIGHT = DASHBOARD / "scripts" / "preflight.js"


def test_preflight_names_the_new_objects_and_the_right_fix():
    """A Vercel deploy and a schema migration are independent events.

    The dashboard builds on push; migrations are applied by the ingest
    workflow. Merge a PR that adds both and the deploy can win the race —
    which is what `REQUIRED_AFTER_MIGRATION` exists to turn from five
    identical "Cannot read properties of undefined" lines into one legible
    line. These tables arrive in TWO stages, so both are checked: the landing
    table from migration 39, and the views the pages actually query from the
    analytical layer. They also have DIFFERENT fix commands, and naming the
    wrong one sends whoever reads the log down the wrong path.
    """
    js = PREFLIGHT.read_text(encoding="utf-8")
    block = js.split("REQUIRED_AFTER_MIGRATION = [")[1].split("];")[0]

    assert "'b3_lending_open_position'" in block
    assert "39_b3_lending_flow.sql" in block
    assert "'fact_short_interest_daily'" in block
    assert "'fact_investor_flow_daily'" in block
    assert "20_short_interest.sql" in block

    # The analytical views are NOT applied by apply_schema.py.
    for relation in ("fact_short_interest_daily", "fact_investor_flow_daily"):
        entry = block.split(f"'{relation}'")[1].split("},")[0]
        assert "apply_analytical.sh" in entry, (
            f"{relation} comes from the analytical layer; apply_schema.py will not create it"
        )
    landing = block.split("'b3_lending_open_position'")[1].split("},")[0]
    assert "apply_schema.py" in landing


def test_preflight_prints_every_distinct_fix_command():
    """Two stages means two commands, and the operator needs both."""
    js = PREFLIGHT.read_text(encoding="utf-8")
    assert "new Set(pending.map((p) => p.fix))" in js, (
        "the failure message must derive its commands from the pending entries, "
        "not hardcode a single one"
    )


# ── BTBTrade: the broker caveat and the per-session fetch ─────────────────

MIG40_PATH = ROOT / "src" / "store" / "migrations" / "40_b3_lending_trade.sql"
SQL21_PATH = ROOT / "src" / "store" / "analytical" / "21_lending_participants.sql"
MIG40 = MIG40_PATH.read_text(encoding="utf-8")
SQL21 = SQL21_PATH.read_text(encoding="utf-8")
SQL21_CODE = strip_comments(SQL21)


def test_trade_table_is_partitioned_and_keyed():
    """~43k rows a session, ~2.8 GB a year — partitioned like b3_cotahist."""
    assert "PARTITION BY RANGE (trade_date)" in MIG40
    assert "b3_lending_trade_future" in MIG40
    assert "uq_b3_lending_trade UNIQUE (trade_date, numero_negocio)" in MIG40
    assert "CREATE TABLE IF NOT EXISTS b3_lending_trade " in MIG40
    for t in ("b3_lending_trade", "b3_lending_trade_2026", "b3_lending_trade_future"):
        assert f"CREATE TABLE IF NOT EXISTS {t}" in SCHEMA, f"{t} never reached schema.sql"


def test_participant_views_publish_the_broker_caveat():
    """doador/tomador are brokerages, and ~75% of trades are self-crossed.

    Netting those away would make the rest look like inter-broker conviction;
    hiding them would make a broker's own client churn look like demand. The
    split has to be visible on the view and in its comment, or the numbers
    invite exactly the wrong reading.
    """
    assert "internal_legs" in SQL21_CODE
    assert "internal_qty" in SQL21_CODE
    assert "internal_trades" in SQL21_CODE
    for view in ("api.lending_participants", "fact_lending_participant_daily"):
        comment = SQL21.split(f"COMMENT ON VIEW {view} IS")[1].split(";")[0].lower()
        assert "broker" in comment
        assert "beneficial owner" in comment


def test_self_crossed_trades_cancel_rather_than_inflate_the_net():
    """A broker on both legs contributes to lent AND borrowed, so qty_net is 0
    for that trade instead of counting twice in one direction."""
    legs = SQL21_CODE.split("WITH legs AS")[1].split("SELECT\n    l.trade_date")[0]
    assert legs.count("UNION ALL") == 1
    assert "sum(l.qty_lent) - sum(l.qty_borrowed)" in SQL21_CODE


def test_landing_table_is_revoked_and_api_views_are_owner_privileged():
    assert re.search(r"REVOKE ALL ON TABLE\s+b3_lending_trade\s+FROM anon, authenticated", SQL21_CODE)
    for view in ("lending_trades", "lending_participants"):
        assert f"ALTER VIEW api.{view} SET (security_invoker = false)" in SQL21_CODE
        assert re.search(rf"GRANT SELECT ON api\.{view} TO anon, authenticated", SQL21_CODE)


def test_trade_ingest_is_per_session_because_b3_ignores_finaldate():
    """BTBTrade returns only the `Date` day whatever `FinalDate` says.

    Verified live: 2026-09-08..09-11 returned only 08/09, and 09-10..09-11 came
    back byte-identical to the single day. A ranged fetch would therefore log
    twenty sessions as a shortfall on every run, forever — so the ingestor must
    loop, not span.
    """
    pipeline = (ROOT / "src" / "pipeline" / "b3_pipeline.py").read_text(encoding="utf-8")
    body = pipeline.split("async def ingest_lending_trades")[1].split("async def ")[0]
    # The docstring names _ingest_bdi_span to explain why it is NOT used, so
    # match the call, not the prose.
    assert "self._ingest_bdi_span(" not in body, "BTBTrade cannot be range-fetched"
    assert "fetch_table(\"BTBTrade\", session)" in body, (
        "each request must name a single session"
    )
    assert "for session in targets" in body
    assert "MAX_TRADE_SESSIONS_PER_RUN" in body
    # And it must notice if B3 ever answers with a day it did not ask for.
    assert "returned sessions" in body
