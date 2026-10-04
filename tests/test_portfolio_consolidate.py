"""Consolidation of statements, and the engine over a PDF-derived (and consolidated) statement."""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from decimal import Decimal

import pytest

from src.portfolio.client import FakeClient
from src.portfolio.consolidate import ConsolidationError, consolidate
from src.portfolio.engine import dumps, run_engine
from src.portfolio.statement import Position
from src.portfolio.statement_pdf import parse_pdf_pages
from tests.portfolio_pdf_fixtures import BRUTO, HOLDER_ACCOUNT, HOLDER_NAME, ORIGINALS, variant_a_pages, variant_b_pages

D = Decimal


def stmt(pages=None, account=None, name=None, date=None):
    pages = list(pages or variant_a_pages())
    if account:
        pages[0] = pages[0].replace(HOLDER_ACCOUNT, account)
    if name:
        pages[0] = pages[0].replace(HOLDER_NAME, name)
    if date:
        pages[1] = pages[1].replace("31/12/2025", date)
    return parse_pdf_pages(pages)[0]


def no_originals(text: str) -> None:
    for o in ORIGINALS:
        assert o not in text, o


def test_same_assets_in_two_accounts_are_aggregated_and_kept_per_account():
    c = consolidate([stmt(account="0000111"), stmt(variant_b_pages(), account="0000222")])
    s = c.statement
    assert [a.conta_ref for a in c.accounts] == ["C1", "C2"]
    assert len(s.positions) == 11 and c.n_lines_before == 22 and c.n_assets_in_several_accounts == 11
    assert s.sum_of_lines == 2 * BRUTO == s.stated_total
    petr = next(p for p in s.positions if p.codigo == "PETR4")
    assert petr.valor == D("600000.00") and petr.quantidade == D("12000.00")
    assert [(x.conta_ref, x.valor) for x in petr.contas] == [("C1", D("300000.00")), ("C2", D("300000.00"))]
    fund = next(p for p in s.positions if p.linha_extrato.startswith("FUNDO ALFA"))
    assert fund.preco_implicito and fund.preco_unitario == D("2.00000000")  # recomputed on the sum
    caixa = next(p for p in s.positions if p.tipo == "caixa")
    assert caixa.valor == D("300000.00") and len(caixa.contas) == 2
    assert not any("multi-titular" in n for n in s.notes)
    assert all(a.positions for a in c.accounts) and c.accounts[0].positions[0].conta_ref == "C1"
    no_originals(repr(c))


def test_the_real_account_number_is_never_kept_only_ordinals():
    c = consolidate([stmt(account="0000111"), stmt(account="0000222")])
    blob = repr(c) + dumps(run_engine(c.statement, FakeClient({})))
    for o in ("0000111", "0000222", HOLDER_ACCOUNT):
        assert o not in blob
    assert "C1" in blob and "C2" in blob


def test_multi_titular_is_flagged_with_ordinals():
    c = consolidate([stmt(account="0000111"), stmt(account="0000222", name="JOSE OUTRO TITULAR")])
    assert [a.titular_ref for a in c.accounts] == ["T1", "T2"]
    assert any("multi-titular: 2 titulares (T1, T2)" in n for n in c.notes)
    assert "JOSE" not in repr(c)


def test_same_holder_twice_is_one_titular():
    c = consolidate([stmt(account="0000111"), stmt(account="0000222")])
    assert [a.titular_ref for a in c.accounts] == ["T1", "T1"]


def test_different_dates_are_reported_and_never_mixed():
    c = consolidate([stmt(account="0000111"), stmt(account="0000222", date="30/11/2025")])
    s = c.statement
    assert s.position_date == dt.date(2025, 12, 31) and s.position_dates == (dt.date(2025, 11, 30), dt.date(2025, 12, 31))
    note = next(n for n in c.notes if "Datas de posição diferentes" in n)
    assert "2025-11-30" in note and "2025-12-31" in note and "31 dias" in note
    assert len(s.positions) == 22 and c.n_assets_in_several_accounts == 0  # nothing aggregated across dates
    assert s.sum_of_lines == 2 * BRUTO


def test_the_same_account_on_the_same_date_is_refused():
    with pytest.raises(ConsolidationError, match="mesma conta na mesma data"):
        consolidate([stmt(), stmt(variant_b_pages())])


def test_the_same_account_on_two_dates_is_summed_with_a_note():
    c = consolidate([stmt(), stmt(date="30/11/2025")])
    assert any("mesma conta em datas diferentes" in n for n in c.notes)


def test_a_title_without_a_maturity_is_never_aggregated():
    def pos(conta, valor):
        return Position(1, 1, "BACEN - NTNB", "tesouro", "NTN-B", None, None, valor, dt.date(2025, 12, 31), conta_ref=conta)

    a = replace(stmt(account="0000111"), positions=(pos("C1", D("1")),), sum_of_lines=D("1"), stated_total=D("1"))
    b = replace(stmt(account="0000222"), positions=(pos("C2", D("2")),), sum_of_lines=D("2"), stated_total=D("2"))
    c = consolidate([a, b])
    assert len(c.statement.positions) == 2


def test_conflicting_rates_for_the_same_asset_leave_the_rate_empty_with_a_note():
    s1, s2 = stmt(account="0000111"), stmt(account="0000222")
    s2 = replace(s2, positions=tuple(replace(p, taxa_texto="IPCA + 9,99%") if p.codigo == "CRA0250001" else p for p in s2.positions))
    c = consolidate([s1, s2])
    cra = next(p for p in c.statement.positions if p.codigo == "CRA0250001")
    assert cra.taxa_texto is None and any("Taxas impressas diferentes" in n for n in c.notes)


# ---------------------------------------------------------------------------
# The engine over a PDF-derived statement
# ---------------------------------------------------------------------------

LOOKUPS = {
    "PETR4": dict(id="PETR4", id_type="ticker", asset_class="equity", name="PETROBRAS", isin="BRPETRACNPR6", cnpj=None, tickers=None),
    "HGLG11": dict(id="HGLG11", id_type="ticker", asset_class="fund_quota", name="FII HGLG PAX", isin="BRHGLGCTF004", cnpj=None, tickers=None),
}


def canned():
    rows = {"lookup": [{"match": {"p_query": k}, "rows": [v]} for k, v in LOOKUPS.items()]}
    rows["quote_latest"] = [{"match": {"p_ticker": k}, "rows": []} for k in LOOKUPS]
    rows["company_financials"] = [
        {"match": {"p_id": "PETR4"}, "rows": [dict(id="PETR4", cnpj="33000167000101", company="PETROBRAS", ref_date="2025-09-30", setor="Petróleo e Gás")]}
    ]
    return rows


def test_engine_over_a_pdf_statement_uses_the_statements_own_facts():
    s = stmt()
    doc = run_engine(s, FakeClient(canned()))
    ident = {ln["line_no"]: ln for ln in doc["identification"]["lines"]}
    by_name = {ln["linha_extrato"]: ln for ln in ident.values()}
    # the current account is identified as a statement line; a ticker typed 'outro' is resolved by lookup
    assert by_name["Conta corrente"]["status"] == "identified" and by_name["Conta corrente"]["identity"]["kind"] == "caixa"
    assert by_name["PETR4"]["status"] == "identified" and by_name["PETR4"]["identity"]["asset_class"] == "equity"
    assert by_name["PETR4"]["identity"]["issuer_cnpj"] == "33000167000101"
    assert by_name["HGLG11*"]["identity"]["asset_class"] == "fund_quota"
    # a Tesouro line with title and maturity is identified; a CRA stays unidentified and says why, with its code
    assert by_name["BACEN-BANCO CENTRAL DO BRASIL - RJ - NTNB"]["identity"]["tesouro_maturity"] == "2035-05-15"
    cra = by_name["EMPRESA ZETA AGRO S.A. - CRA-CRA0250001*"]
    assert cra["status"] == "unknown" and "CRA0250001" in cra["reason"]
    assert cra["statement_facts"]["taxa_texto"] == "IPCA + 7,00%" and cra["statement_facts"]["vencimento"] == "2030-06-20"
    # the indexer comes from the printed rate for direct credit and from the title for the Tesouro
    classes = {c["indexer_class"]: c["value_brl"] for c in doc["indexer"]["classes"]}
    assert classes["caixa (conta corrente)"] == 150000.0
    assert classes["inflação (IPCA)"] == 500000.0 + 400000.0  # NTN-B (title) + CRA ('IPCA + 7,00%')
    assert classes["pós-fixado (CDI)"] == 250000.0 + 200000.0  # '105,00% do CDI' and 'CDI + 1,80%'
    assert classes["pós-fixado (Selic)"] == 350000.0  # LFT
    assert classes["pré-fixado"] == 100000.0  # '11,87% a.a.'
    assert doc["indexer"]["classes"][-1]["indexer_class"] == "sem classificação"
    assert abs(doc["indexer"]["sum_check_brl"]) < 0.02
    facts = by_name["FUNDO ALFA RF CRED PRIV FIC FIRF"]["statement_facts"]
    assert facts["preco_implicito"] is True
    no_originals(dumps(doc))


def test_a_rate_text_without_a_rule_is_unclassified_not_guessed():
    s = stmt()
    s = replace(s, positions=tuple(replace(p, taxa_texto="TAXA ESPECIAL XPTO") if p.codigo == "CUTI11" else p for p in s.positions))
    doc = run_engine(s, FakeClient(canned()))
    reasons = " ".join(u["reason"] for u in doc["indexer"]["unclassified_breakdown"])
    assert "sem regra" in reasons


def test_engine_over_a_consolidated_portfolio_exposes_both_views():
    c = consolidate([stmt(account="0000111"), stmt(variant_b_pages(), account="0000222")])
    doc = run_engine(c.statement, FakeClient(canned()))
    st = doc["statement"]
    assert st["consolidated"] is True and [a["conta_ref"] for a in st["accounts"]] == ["C1", "C2"]
    assert len(st["positions"]) == 11 and all(len(a["positions"]) == 11 for a in st["accounts"])
    petr = next(p for p in st["positions"] if p["codigo"] == "PETR4")
    assert petr["valor_brl"] == 600000.0 and [x["conta_ref"] for x in petr["contas"]] == ["C1", "C2"]
    assert st["sum_of_lines_brl"] == 2 * float(BRUTO)
    assert any("ativo(s) presentes em mais de uma conta" in n for n in st["notes"])
    out = dumps(doc)
    no_originals(out)
    for o in ("0000111", "0000222"):
        assert o not in out


def test_a_single_statement_has_no_accounts_block():
    doc = run_engine(stmt(), FakeClient(canned()))
    assert doc["statement"]["consolidated"] is False and doc["statement"]["accounts"] == []
