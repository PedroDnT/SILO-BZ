"""The portfolio_lookthrough contract's edge rows: no_cda_filing, no weight, a quota that could not be opened."""

from __future__ import annotations

from pathlib import Path

from src.portfolio.client import FakeClient, load_fake_rows
from src.portfolio.diagnose import FAKE_CLOCK
from src.portfolio.engine import default_params, run_engine
from src.portfolio.statement import read_statement

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "docs" / "reference" / "portfolio" / "statement-template.xlsx"
FAKE_ROWS = ROOT / "tests" / "fixtures" / "portfolio" / "fake_silo_rows.json"
GERACAO = "08935128000159"


def _row(**kw):
    base = dict(
        root_cnpj=GERACAO, path=[GERACAO], depth=0, holder_cnpj=GERACAO, block=4, asset_kind="stock", asset_key="PETR4",
        asset_name="PETR4", isin=None, issuer_cnpj=None, issuer_code=None, tp_aplic="Ações", tp_ativo=None, tp_titpub=None,
        indexer_code=None, maturity=None, value_brl=100.0, weight_in_root=0.5, period="2026-05-01", is_cycle=False,
    )
    base.update(kw)
    return base


def _run(rows):
    canned = load_fake_rows(FAKE_ROWS)
    canned["portfolio_lookthrough"][0] = {"match": {"p_cnpjs": [GERACAO]}, "rows": rows}
    stmt = read_statement(TEMPLATE)
    return run_engine(stmt, FakeClient(canned, clock=lambda: FAKE_CLOCK), default_params(stmt.position_date), clock=lambda: FAKE_CLOCK)


def _line(doc):
    return next(ln for ln in doc["look_through"]["lines"] if ln["line_no"] == 3)


def test_root_without_cda_is_no_holdings_with_the_tool_s_reason():
    d = _run([_row(block=None, asset_kind="no_cda_filing", asset_key=None, weight_in_root=None, value_brl=None)])
    ln = _line(d)
    assert ln["status"] == "no_holdings" and "no_cda_filing" in ln["reason"]
    assert any("linha 3" in u["reason"] for u in d["indexer"]["unclassified_breakdown"])


def test_a_row_with_no_weight_is_left_out_and_said():
    d = _run([_row(), _row(asset_key="VALE3", weight_in_root=None)])
    ln = _line(d)
    assert ln["status"] == "partial" and len(ln["rows_without_weight"]) == 1 and len(ln["exposures"]) == 1
    assert ln["explained_weight"] == 0.5 and d["look_through"]["status"] == "partial"


def test_a_quota_that_could_not_be_opened_is_a_leaf_with_a_reason():
    d = _run([_row(block=2, asset_kind="fund_quota_unfiled", asset_key="11111111000191", asset_name="FUNDO SEM CDA", tp_aplic="Cotas de Fundos")])
    ln = _line(d)
    assert ln["exposures"][0]["not_opened_fund"] is True
    assert ln["fund_nodes"][0]["expanded"] is False and "não entregou CDA" in ln["fund_nodes"][0]["not_expanded_reason"]
    assert any("fundo investido sem carteira" in u["reason"] for u in d["indexer"]["unclassified_breakdown"])
