"""The research price contract: api.quote_history and the panel's close_adj (#410).

The adjustment rule is B3's, verified on the tape in #372: DESDOBRAMENTO and
BONIFICACAO multiply the share count by 1 + factor/100, GRUPAMENTO by factor,
and a session on or before an event's last_date_prior is DIVIDED by that ratio
(backward adjustment, anchored to the instrument's latest session). Checked on
a scratch database in #449: BBAS3 56.46 on 2024-04-15 reads 28.23 and 27.91 on
2024-04-16 stays; MGLU3's grouping and 2025 bonus compound.

These tests pin the SQL text so the contract cannot drift silently. What the
SQL DOES on rows is executed in CI by tests/sql/quote_history_behaviour.sql.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "src/store/analytical/19_api_contract.sql"
RESEARCH = ROOT / "src/store/analytical/28_api_research.sql"
BEHAVIOUR = ROOT / "tests/sql/quote_history_behaviour.sql"
TEST_WORKFLOW = ROOT / ".github/workflows/test.yml"


def _uncommented(text: str) -> str:
    return re.sub(r"--[^\n]*", "", text)


def _function(name: str) -> str:
    sql = _uncommented(CONTRACT.read_text(encoding="utf-8"))
    start = sql.index(f"CREATE OR REPLACE FUNCTION api.{name}(")
    return sql[start:sql.index("$$;", sql.index("AS $$", start) + 5)]


def _fields_sql() -> list[tuple[str, str, bool]]:
    body = _function("quote_history_fields")
    return [
        (m.group(1), m.group(2), m.group(3) == "TRUE")
        for m in re.finditer(r"\('(\w+)',\s*'(\w+)',\s*(TRUE|FALSE),", body)
    ]


def test_the_field_list_is_one_list_in_sql_and_catalog():
    from serve.catalog import QUOTE_HISTORY_FIELDS

    assert [(f, t) for f, t, _ in _fields_sql()] == list(QUOTE_HISTORY_FIELDS.items())


def test_the_default_selection_is_ticker_date_and_close_adj():
    from serve.catalog import catalog_payload

    defaults = [f for f, _t, d in _fields_sql() if d]
    assert defaults == ["ticker", "trade_date", "close_adj"]
    assert catalog_payload()["defaults"]["quote_history"]["fields"] == defaults
    body = _function("quote_history")
    assert "v_fields := ARRAY['close_adj'];" in body
    assert re.search(r"p_fields\s+TEXT\[\]\s+DEFAULT\s+NULL", body)
    assert "RETURNS SETOF jsonb" in body


def test_the_raw_close_is_an_explicit_field_and_never_renamed():
    names = [f for f, _t, _d in _fields_sql()]
    for raw in ("close", "open", "high", "low", "volume", "close_unit"):
        assert raw in names
    body = _function("quote_history")
    assert "'close',            r.close," in body


def test_the_share_ratio_is_b3s_rule_and_only_three_labels_adjust():
    ratio = _function("close_adj_ratio")
    assert "CASE e.label WHEN 'GRUPAMENTO' THEN e.factor ELSE 1 + e.factor / 100 END" in ratio
    assert "e.label IN ('DESDOBRAMENTO', 'GRUPAMENTO', 'BONIFICACAO')" in ratio
    # Sessions on or before the cum date are divided; unexpired events adjust nothing.
    assert "e.last_date_prior >= p_trade_date" in ratio
    assert "e.last_date_prior < p_anchor" in ratio
    # Each row by its own ISIN's ratio, times the later instruments' of its lineage (#381).
    assert (
        "round(r.close_unit / (api.close_adj_ratio(r.seg_isin, r.trade_date, r.seg_anchor) * r.seg_tail), 6)"
        in _function("quote_history")
    )


def test_every_stock_label_that_is_not_adjusted_blocks():
    """Cash events and subscription rights are outside a price-only adjustment
    (owner, 2026-09-30); every other stock label (and any B3 adds later)
    blocks its stretch."""
    status = _function("close_adj_status")
    assert "e.event_class = 'stock'" in status
    assert "ev.label NOT IN ('DESDOBRAMENTO', 'GRUPAMENTO', 'BONIFICACAO')" in status
    assert "'unsupported corporate event '" in status
    assert "'unreadable factor on '" in status
    assert "published with two factors" in status


def test_the_anchor_and_the_proof_are_the_isins():
    status = _function("close_adj_status")
    # The anchor is the instrument's latest session on every board.
    assert "WHERE b.isin = p_isin AND b.tpmerc = '010'" in status
    assert "codbdi" not in status
    # The proof is keyed on the issuer code inside the ISIN.
    assert "s.issuing_company = substr(p_isin, 3, 4)" in status
    assert_ = _function("assert_close_adj")
    assert "s.proven_at IS NULL" in assert_
    assert "(s.proven_at AT TIME ZONE 'America/Sao_Paulo')::date < s.anchor" in assert_


def test_the_universe_rule_is_the_research_universes():
    universe = _uncommented(RESEARCH.read_text(encoding="utf-8"))
    assert "substr(q.isin, 7, 3) = 'ACN'" in universe
    status = _function("close_adj_status")
    assert "substr(p_isin, 7, 3) = 'ACN'" in status
    assert "substr(p_isin, 7, 3) IN ('CDA', 'UNT') AND p_ticker LIKE '%11'" in status


def test_close_adj_is_computed_only_after_the_refusal_check():
    body = _function("quote_history")
    check = body.index("PERFORM api.assert_close_adj('quote_history'")
    served = body.index("RETURN QUERY")
    assert check < served
    # No fallback: nothing coalesces the adjusted close onto the raw one.
    assert not re.search(r"COALESCE\([^)]*close_adj", body)


def test_every_refusal_names_its_reason():
    body = _function("quote_history") + _function("assert_close_adj")
    for reason in ("unknown_ticker", "outside_coverage", "isin_change",
                   "ambiguous_session", "invalid_field", "adjustment_unavailable"):
        assert f"reason={reason}" in body, reason
    assert body.count("ERRCODE = '22023'") >= 10


def test_the_series_follows_the_isin_not_the_latest_board():
    body = _function("quote_history")
    assert "latest.board" not in body
    # One (ticker, ISIN) per instrument of the series; boards are not split.
    assert "AND q.isin IS NOT DISTINCT FROM s.i" in body
    assert "(v_board IS NULL OR q.board = v_board)" in body


def test_the_lineage_rule_is_the_owners():
    """#381 follow-up, docs/adr/0002-ticker-activity-and-lineage.md: an older
    instrument is spliced only for the same company, the same class, adjacent
    sessions, no overlap, no stock event at the seam, and one candidate.
    Rows are executed in tests/sql/quote_history_behaviour.sql."""
    lin = _function("ticker_lineage")
    assert "o.cnpj_cia IN (SELECT x.cnpj_cia FROM public.cia_ticker x WHERE x.codneg = v_t)" in lin
    assert "substr(p.isin, 7, 5) = substr(v_i, 7, 5)" in lin
    assert "s.trade_date > p.trade_date AND s.trade_date < v_f" in lin
    assert "o.isin = p.isin AND o.tpmerc = '010' AND o.trade_date >= v_f" in lin
    assert "e.event_class = 'stock'" in lin
    assert "EXIT WHEN v_n <> 1;" in lin
    assert "ILIKE" not in lin and "nome" not in lin.lower()
    # quote_history looks the lineage up only when a window starts before the
    # current instrument's first session, and never with p_board.
    body = _function("quote_history")
    assert "IF v_board IS NULL AND (v_from IS NULL OR v_from < v_cur_first) THEN" in body


def test_the_panel_shares_the_same_adjustment():
    panel = _function("panel")
    assert "api.close_adj_status(d.isin, d.ticker)" in panel
    assert "api.assert_close_adj('panel'" in panel
    assert "api.close_adj_ratio(q.isin, q.obs_date, a.anchor)" in panel


def test_the_catalog_describes_close_adj_and_its_refusals():
    from serve.catalog import catalog_payload

    payload = catalog_payload()
    text = " ".join(payload["constraints"])
    assert "close_adj IS CONTINUOUS ACROSS SPLITS, GROUPINGS AND BONUS SHARES ONLY" in text
    assert "reason=adjustment_unavailable" in text
    assert "close_price_adjusted" not in text
    assert "close_adj" in payload["metrics"]
    assert payload["metrics"]["close_adj"]["asset_class"] == ["equity", "unit"]


def test_the_behaviour_file_runs_in_ci():
    assert "tests/sql/quote_history_behaviour.sql" in TEST_WORKFLOW.read_text(encoding="utf-8")
    sql = BEHAVIOUR.read_text(encoding="utf-8")
    assert sql.lstrip().splitlines()[0].startswith("--")
    assert "BEGIN;" in sql and sql.rstrip().endswith("ROLLBACK;")
