"""The ANBIMA class -> ETF index pairs (#609): the reviewed YAML, its loader and its SQL copy.

Offline. Spellings are checked against a fixture of the values the warehouse files
(tests/fixtures/portfolio/equivalents_spellings.json, read on 2026-10-05), never live data.
The SQL behaviour of the pairs (ETF fee peers) is executed in tests/sql/portfolio_behaviour.sql.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from src.portfolio import equivalents as eq

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "portfolio" / "equivalents_spellings.json").read_text("utf-8"))
SQL31 = (ROOT / "src" / "store" / "analytical" / "31_api_portfolio.sql").read_text(encoding="utf-8")
DOC = yaml.safe_load(eq.RULES.read_text(encoding="utf-8"))


def _pair(**kw):
    base = {"class": "RENDA FIXA SIMPLES", "index": "Tesouro Selic B3", "status": "proposta", "rationale": "same objective"}
    base.update(kw)
    return base


def test_the_file_loads_and_every_spelling_is_filed():
    pairs = eq.load_pairs()
    assert 8 <= len(pairs) <= 12
    eq.check_spellings(pairs, FIXTURE["classe_anbima"], FIXTURE["underlying_index"])


def test_every_pair_is_a_proposal_until_the_owner_approves_it():
    assert {p.status for p in eq.load_pairs()} <= set(eq.STATUSES)
    assert all(p.rationale for p in eq.load_pairs())


def test_header_says_never_inferred_and_owner_approves():
    head = eq.RULES.read_text(encoding="utf-8").split("pairs:", 1)[0]
    assert "NEVER inferred from a fund's name" in head
    assert "The owner approves this file" in head


def test_unmapped_classes_are_not_mapped_and_previdencia_is_out():
    pairs = eq.load_pairs()
    mapped = {p.classe_anbima for p in pairs}
    for cls in ("AÇÕES - INDEXADO - ÍNDICE PASSIVO", "RENDA FIXA - PASSIVO - ÍNDICES", "AÇÕES - ATIVO - ÍNDICE ATIVO"):
        assert cls not in mapped
        assert any(u["class"] == cls for u in DOC["unmapped"])
    assert not any(c.startswith("PREVIDÊNCIA") for c in mapped)


def test_reverse_lookup_an_index_reaches_its_classes():
    pairs = eq.load_pairs()
    assert eq.classes_for_index(pairs, "Tesouro Selic (LFT)") == ["RENDA FIXA SIMPLES", "RENDA FIXA BAIXA DURAÇÃO - SOBERANO"]
    assert eq.indices_for_class(pairs, "AÇÕES - ATIVO - SMALL CAPS") == ["SMLL (Small Cap)"]
    assert eq.classes_for_index(pairs, "Ibovespa") == []


def test_a_misspelled_class_or_index_is_refused():
    pairs = eq.parse_pairs({"pairs": [_pair(**{"class": "RENDA FIXA - SIMPLES"}), _pair(index="Tesouro Selic")]})
    with pytest.raises(eq.EquivalentsError) as e:
        eq.check_spellings(pairs, FIXTURE["classe_anbima"], FIXTURE["underlying_index"])
    assert "class 'RENDA FIXA - SIMPLES'" in str(e.value) and "index 'Tesouro Selic'" in str(e.value)


@pytest.mark.parametrize("doc,needle", [
    ({}, "non-empty 'pairs'"),
    ({"pairs": []}, "non-empty 'pairs'"),
    ({"pairs": [_pair()], "extra": 1}, "unknown top-level"),
    ({"pairs": [{"class": "X", "index": "Y", "status": "proposta"}]}, "keys must be exactly"),
    ({"pairs": [_pair(status="approved")]}, "status must be one of"),
    ({"pairs": [_pair(), _pair()]}, "duplicate pair"),
    ({"pairs": [_pair(index=" Tesouro Selic B3")]}, "no outer spaces"),
    ({"pairs": [_pair(rationale="")]}, "non-empty string"),
    ({"pairs": [_pair()], "unmapped": [{"class": "RENDA FIXA SIMPLES", "reason": "x"}]}, "both mapped and unmapped"),
    ({"pairs": [_pair()], "unmapped": [{"class": "X"}]}, "keys must be exactly"),
])
def test_malformed_files_are_refused(doc, needle):
    with pytest.raises(eq.EquivalentsError, match=re.escape(needle)):
        eq.parse_pairs(doc)


def test_the_sql_block_is_generated_from_the_yaml():
    """scripts/gen_class_index_sql.py writes it; a hand edit or a stale block fails here."""
    block = eq.sql_block(eq.load_pairs())
    assert SQL31.count(eq.SQL_BEGIN) == 1
    assert block in SQL31
    rows = re.findall(r"^\s+\('([^']*)', '([^']*)', '([^']*)'\)", block, re.M)
    assert rows == [(p.classe_anbima, p.underlying_index, p.status) for p in eq.load_pairs()]
    assert "REVOKE ALL ON public.portfolio_class_index FROM PUBLIC, anon, authenticated;" in block
    # The view is created before the function that reads it, in the same file.
    assert SQL31.index(eq.SQL_BEGIN) < SQL31.index("CREATE OR REPLACE FUNCTION api.portfolio_fee_peers(")


def test_sql_literals_are_quoted():
    block = eq.sql_block([eq.Pair("A'B", "I", "proposta", "r")])
    assert "('A''B', 'I', 'proposta')" in block


def test_replace_sql_block_needs_exactly_one_block():
    with pytest.raises(eq.EquivalentsError):
        eq.replace_sql_block("no block here", "x")
    assert eq.replace_sql_block(f"a\n{eq.SQL_BEGIN}\nold\n{eq.SQL_END}\nb", "NEW") == "a\nNEW\nb"


def test_fee_peers_reads_the_map_and_labels_etf_fees_third_party():
    start = SQL31.index("CREATE OR REPLACE FUNCTION api.portfolio_fee_peers(")
    body = SQL31[start: SQL31.index("$fn$;", start)]
    assert "FROM public.portfolio_class_index m" in body
    assert "r.underlying_index = m.underlying_index AND r.is_active IS TRUE" in body
    assert "public.etf_market_snapshot x" in body and "x.snapshot_date <= v_as_of" in body
    assert "not a CVM filing" in body
    for col in ("n_fund_peers INT", "n_etf_peers INT", "n_etf_excluded INT", "etf_peer_tickers TEXT[]",
                "etf_peer_fee_oldest DATE", "etf_peer_fee_newest DATE", "etf_peer_fee_source TEXT"):
        assert col in body
    # Appended, never renamed: the v63 columns keep their order at the head of the row.
    head = body[body.index("RETURNS TABLE"): body.index("n_fund_peers INT")]
    v63 = ["cnpj", "classe_anbima", "fundo_cotas", "tp_fundo_classe", "taxa_adm", "fee_as_of", "comparison_as_of",
           "activity_from", "activity_to", "n_peers", "n_excluded", "peer_fee_oldest", "peer_fee_newest",
           "p25_pct_year", "median_pct_year", "p75_pct_year", "percentile_pct", "difference_pp", "status", "reason_code"]
    assert re.findall(r"\b(\w+) (?:TEXT|NUMERIC|DATE|INT)\b", head) == v63
    assert "DROP FUNCTION IF EXISTS api.portfolio_fee_peers(TEXT[], DATE);" in SQL31


def test_class_return_distribution_contract():
    start = SQL31.index("CREATE OR REPLACE FUNCTION api.class_return_distribution(")
    body = SQL31[start: SQL31.index("$fn$;", start)]
    assert "v_min      INT := 30;" in body
    assert "public.latest_complete_period('fi')" in body and "public.mv_period_completeness" in body
    assert "unnest(ARRAY[12, 6])" in body
    assert "e.quota_subclass_id IS NOT DISTINCT FROM s.quota_subclass_id" in body
    assert "LIMIT 1001" in body and "api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'class_return_distribution')" in body
    flat = re.sub(r"\s+", " ", SQL31)
    sig = "api.class_return_distribution(TEXT, TEXT, DATE)"
    assert f"REVOKE ALL ON FUNCTION {sig} FROM PUBLIC;" in flat
    assert f"GRANT EXECUTE ON FUNCTION {sig} TO anon, authenticated;" in flat
    assert f"GRANT EXECUTE ON FUNCTION {sig} TO silo_api;" in flat
