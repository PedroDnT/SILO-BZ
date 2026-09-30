"""api.quote_history serves a price-adjusted close (#417) over proven issuers (#413).

The rule is B3's, verified on the tape in #372: DESDOBRAMENTO and BONIFICACAO
multiply the share count by 1 + factor/100, GRUPAMENTO by factor, and a session
on or before an event's last_date_prior is DIVIDED by that ratio (backward
adjustment, anchored to the latest session). Checked against a scratch
database: BBAS3 56.46 on 2024-04-15 reads 28.23 and 27.91 on 2024-04-16 stays;
MGLU3 1.32 on 2024-05-24 reads 13.20 before its 2025-12-29 bonus is applied.
These tests pin the SQL text so the rule cannot drift silently.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "src/store/analytical/19_api_contract.sql"
RESEARCH = ROOT / "src/store/analytical/28_api_research.sql"


def _uncommented(text: str) -> str:
    return re.sub(r"--[^\n]*", "", text)


def _quote_history() -> str:
    sql = _uncommented(CONTRACT.read_text(encoding="utf-8"))
    start = sql.index("CREATE OR REPLACE FUNCTION api.quote_history(")
    return sql[start:sql.index("$$;", start)]


def test_the_adjusted_closes_and_their_reasons_are_columns():
    returns = _quote_history().split("AS $$")[0]
    for column, sql_type in (
        ("close_price_adjusted", "NUMERIC"),
        ("close_price_adjusted_null_reason", "TEXT"),
        ("close_total_return", "NUMERIC"),
        ("close_total_return_null_reason", "TEXT"),
    ):
        assert re.search(rf"\b{column}\s+{sql_type}\b", returns), column
    # `adjusted` describes the raw close and must stay FALSE.
    assert re.search(r"\badjusted\s+BOOLEAN\b", returns)


def test_the_return_type_change_drops_the_old_function_first():
    sql = CONTRACT.read_text(encoding="utf-8")
    drop = sql.index("DROP FUNCTION IF EXISTS api.quote_history(TEXT, DATE, DATE, TEXT, TEXT);")
    assert drop < sql.index("CREATE OR REPLACE FUNCTION api.quote_history(")


def test_the_share_ratio_is_b3s_rule_and_only_three_labels_adjust():
    body = _quote_history()
    assert re.search(
        r"CASE\s+e\.label\s+WHEN\s+'GRUPAMENTO'\s+THEN\s+e\.factor\s+ELSE\s+1\s*\+\s*e\.factor\s*/\s*100\s+END",
        body,
    )
    assert "e.label IN ('DESDOBRAMENTO', 'GRUPAMENTO', 'BONIFICACAO')" in body
    for unadjusted in ("CIS RED CAP", "INCORPORACAO", "SUBSCRICAO"):
        assert unadjusted not in body


def test_earlier_sessions_are_divided_and_unexpired_events_are_ignored():
    """Multiplying by the ratio instead of dividing is the classic inversion."""
    body = _quote_history()
    assert re.search(r"e\.last_date_prior\s*>=\s*g\.trade_date", body)
    assert re.search(r"e\.last_date_prior\s*<\s*\(SELECT\s+an\.last_session\s+FROM\s+anchor\s+an\)", body)
    assert re.search(r"sum\(ln\(x\.share_ratio\)\)", body)
    assert re.search(r"j\.close_unit\s*\*\s*exp\(-COALESCE\(j\.log_share_ratio,\s*0\)\)", body)
    # A republished event is one event.
    assert re.search(r"SELECT\s+DISTINCT\s+e\.label,\s+e\.last_date_prior,\s+e\.factor", body)


def test_only_proven_issuers_get_a_value():
    body = _quote_history()
    assert "public.b3_corporate_event_sweep" in body
    assert re.search(r"s\.issuing_company\s*=\s*left\(upper\(btrim\(p_ticker\)\),\s*4\)", body)


def test_the_universe_rule_is_the_research_universes():
    body = _quote_history()
    research = _uncommented(RESEARCH.read_text(encoding="utf-8"))
    assert "substr(q.isin, 7, 3) = 'ACN'" in research
    assert "substr(g.isin, 7, 3) = 'ACN'" in body
    assert re.search(r"substr\(g\.isin, 7, 3\) IN \('CDA', 'UNT'\) AND g\.ticker LIKE '%11'", body)


def test_every_null_carries_a_reason():
    body = _quote_history()
    for reason in (
        "outside research universe",
        "issuer corporate events not proven swept",
        "unreadable event factor",
        "no close on the session",
        "cash distribution history not yet backfilled",
    ):
        assert f"'{reason}'" in body, reason


def test_the_catalog_describes_the_adjusted_close():
    from serve.catalog import CATALOG_VERSION, catalog_payload

    assert CATALOG_VERSION >= 44
    text = str(catalog_payload())
    assert "close_price_adjusted" in text
    assert "no split, grouping or bonus adjustment exists yet" not in text
