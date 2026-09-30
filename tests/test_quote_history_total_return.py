"""api.quote_history serves close_total_return (#418) from mv_b3_cash_event.

The offline suite has no database, so the SQL is pinned as text. The behaviour
was run on a local Postgres with a synthetic issuer whose levels were computed
by hand (a 0.50 dividend with ex close 9.50 and a 0.19 JCP with ex close 9.00:
10 / (1.0526316 x 1.0211111) = 9.303591 before both, flat across the ex day
because the price fell by exactly the cash; an unresolved PN event blocking only
the PN ISIN; a supplement-only event blocking; an ISIN with no resolved cash
evidence; an event with no ex close inside 7 days; an event on the latest
session ignored) and on real PETR4 data read-only from production, where the
level sits at 0.69 of the price-adjusted close at 2023-12-28.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "src/store/migrations/56_mv_b3_cash_event.sql"
CONTRACT = ROOT / "src/store/analytical/19_api_contract.sql"
MATVIEWS = ROOT / "src/store/analytical/22_b3_tape_matviews.sql"
SCHEMA = ROOT / "src/store/schema.sql"

ACTIONS = "'DIVIDENDO', 'JRS CAP PROPRIO', 'RENDIMENTO', 'REST CAP DIN'"


def _uncommented(text: str) -> str:
    return re.sub(r"--[^\n]*", "", text)


def _quote_history() -> str:
    sql = _uncommented(CONTRACT.read_text(encoding="utf-8"))
    start = sql.index("CREATE OR REPLACE FUNCTION api.quote_history(")
    return sql[start:sql.index("$$;", start)]


def _migration() -> str:
    return _uncommented(MIGRATION.read_text(encoding="utf-8"))


def test_the_matview_is_replay_safe_and_has_no_client_grant():
    sql = _migration()
    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS mv_b3_cash_event" in sql
    assert "WITH NO DATA" in sql
    # Every schema apply replays the migrations: a DROP would empty it until
    # the next analytical apply.
    assert "DROP MATERIALIZED VIEW" not in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_b3_cash_event" in sql
    assert "REVOKE ALL ON mv_b3_cash_event FROM PUBLIC, anon, authenticated;" in sql


def test_it_lives_in_a_migration_because_it_reads_cia_ticker():
    # schema.sql runs before migration 25 creates cia_ticker; the view it reads
    # is deliberately not in schema.sql either (migration 51).
    assert "mv_b3_cash_event" not in SCHEMA.read_text(encoding="utf-8")


def test_the_history_and_the_supplement_use_the_same_action_list():
    sql = _migration()
    assert sql.count(f"IN ({ACTIONS})") == 2
    # Non-cash actions are not in it.
    for label in ("CIS RED CAP", "SUBSCRICAO", "AMORTIZACAO RF"):
        assert label not in sql


def test_a_distribution_counts_only_where_the_isin_is_proven_against_the_tape():
    sql = _migration()
    assert "h.isin IS NOT NULL AND h.close_match IS TRUE" in sql
    assert "NOT (h.isin IS NOT NULL AND h.close_match IS TRUE)" in sql


def test_the_ex_session_is_the_next_print_within_seven_days():
    sql = _migration()
    assert "b.trade_date > r.last_date_prior_ex" in sql
    assert "b.trade_date <= r.last_date_prior_ex + 7" in sql
    assert re.search(r"ORDER BY b\.trade_date\s+LIMIT 1", sql)
    assert "1 + r.per_share / x.ex_close" in sql


def test_a_supplement_event_the_history_lacks_is_pending_with_no_age_limit():
    sql = _migration()
    block = sql[sql.index("pending AS ("):]
    assert "'pending'::text AS kind" in block
    assert "e.last_date_prior >= DATE '2019-01-02'" in sql
    # No "recent only" window: a hole in the history does not heal.
    assert "CURRENT_DATE" not in sql and "now()" not in sql


def test_the_function_reads_the_view_and_divides_earlier_sessions():
    body = _quote_history()
    assert "public.mv_b3_cash_event" in body
    assert re.search(r"m\.event_date\s*>=\s*g\.trade_date", body)
    assert re.search(r"m\.event_date\s*<\s*\(SELECT\s+an\.last_session\s+FROM\s+anchor\s+an\)", body)
    assert re.search(r"sum\(ln\(m\.factor\)\)", body)
    # Divide, not multiply: earlier levels are lower by the cash received since.
    assert re.search(
        r"exp\(-COALESCE\(j\.log_share_ratio,\s*0\)\s*-\s*COALESCE\(j\.log_cash_factor,\s*0\)\)", body
    )


def test_an_unresolved_event_blocks_only_its_issuers_share_class():
    body = _quote_history()
    assert "m.type_stock = split_part(btrim(g.spec), ' ', 1)" in body
    assert "m.stems @> ARRAY[left(g.ticker, 4)]" in body
    # By stem and class, never by an ISIN it does not have.
    assert re.search(r"m\.kind = 'unresolved'\s+AND m\.event_date", body)


def test_a_value_needs_the_adjusted_close_and_positive_cash_evidence_and_no_blocker():
    body = _quote_history()
    tr = body[body.index("j.has_cash_evidence\n"):]
    for clause in ("j.n_unresolved = 0", "j.n_pending = 0", "j.n_no_ex_close = 0"):
        assert clause in tr, clause
    assert "m.kind IN ('cash', 'no_ex_close')" in body


def test_every_total_return_null_has_a_reason():
    body = _quote_history()
    for reason in (
        "no cash distribution resolved for this ISIN in B3''s history",
        "a later distribution of this issuer''s share class has no proven ISIN",
        "a later distribution B3 lists is missing from its cash history",
        "a later distribution has no ex-date close within 7 days",
    ):
        assert f"'{reason}'" in body, reason
    assert "cash distribution history not yet backfilled" not in body


def test_the_matview_is_refreshed_by_the_analytical_apply():
    sql = _uncommented(MATVIEWS.read_text(encoding="utf-8"))
    assert "REFRESH MATERIALIZED VIEW CONCURRENTLY public.mv_b3_cash_event;" in sql
    assert "REFRESH MATERIALIZED VIEW public.mv_b3_cash_event;" in sql


def test_the_catalog_describes_the_total_return():
    from serve.catalog import CATALOG_VERSION, catalog_payload

    assert CATALOG_VERSION >= 46
    text = " ".join(catalog_payload()["constraints"])
    assert "until the cash distribution history is backfilled" not in text
    assert "ex-date close" in text and "gross of withholding tax" in text
    assert "A NULL is never the price return in disguise" in text
