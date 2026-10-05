"""Peer comparison uses the displayed fee, keeps gaps and does not fabricate savings."""
import copy
import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pytest

from src.portfolio.client import FakeClient
from src.portfolio.fee_peers import compute_fee_peers
from src.portfolio.identify import LineId
from src.portfolio.report import adapt, build, redator, render, revisor
from src.portfolio.statement import parse_rows

AS_OF = dt.date(2026, 10, 3)
ID = "08935128000159"


def inputs(n=1):
    stmt = parse_rows([["total_extrato", n * 100],
        ["linha_extrato", "tipo", "codigo", "quantidade", "preco_unitario", "valor", "data_posicao"],
        *[[f"Fundo {i}", "fundo", ID, 1, 100, 100, dt.date(2026, 9, 30)] for i in range(n)]])
    lines = [LineId(p, status="identified", kind="fund", cnpj=ID, entity_type="fi", name=p.linha_extrato)
             for p in stmt.positions]
    fees = {"lines": [{"line_no": li.line_no, "headline": {"origin": "extrato", "kind": "fixa",
             "stale": False, "as_of": "2026-07-31", "rate_pct_year": 2}} for li in lines]}
    return lines, fees


def row(**changes):
    r = dict(cnpj=ID, classe_anbima="Ações Livre", fundo_cotas="N", tp_fundo_classe="FI", taxa_adm=2,
             fee_as_of="2026-07-31", comparison_as_of="2026-10-03", activity_from="2026-08-01",
             activity_to="2026-10-01", n_peers=30, n_excluded=2, peer_fee_oldest="2024-01-31",
             peer_fee_newest="2026-09-30", p25_pct_year=0.75, median_pct_year=1, p75_pct_year=1.5,
             percentile_pct=98.3333, difference_pp=999, status="compared", reason_code=None)
    return r | changes


def compute(r=None, fees=None, error=None):
    lines, normal = inputs()
    answer = {"match": {}}
    if error:
        answer["error"] = error
    else:
        answer["rows"] = [r or row()]
    client = FakeClient({"portfolio_fee_peers": [answer]})
    return compute_fee_peers(lines, fees or normal, client, AS_OF, Decimal(200)), client


def test_difference_is_computed_from_displayed_fee_and_coverage_has_explicit_denominators():
    sec, client = compute()
    assert sec["status"] == "complete"
    assert sec["lines"][0]["difference_pp"] == 1  # ignores the malicious difference in the response
    assert sec["coverage_fund_value_pct"] == 100
    assert sec["coverage_portfolio_value_pct"] == 50
    assert sec["compared_value_brl"] == 100
    assert sec["lines"][0]["sources"][1]["call_id"] == 1
    assert client.provenance[0].args == {"p_cnpjs": [ID], "p_as_of": AS_OF.isoformat()}
    assert "saving" not in str(sec) and "economia_brl" not in str(sec)


@pytest.mark.parametrize("change", [{"n_peers": 29}, {"n_peers": 30.5}, {"median_pct_year": None},
    {"p25_pct_year": 3}, {"percentile_pct": 101}, {"taxa_adm": 0}, {"taxa_adm": -1},
    {"fee_as_of": "2026-11-01"}, {"fee_as_of": "2022-01-31"}, {"comparison_as_of": "2026-10-04"},
    {"classe_anbima": None}, {"fundo_cotas": None}, {"tp_fundo_classe": "unknown"}])
def test_inconsistent_statistics_are_never_compared(change):
    sec, _ = compute(row(**change))
    r = sec["lines"][0]
    assert r["status"] == "not_compared" and r["reason_code"] == "resposta_inconsistente"
    assert r["median_pct_year"] is None and r["difference_pp"] is None
    assert sec["compared_value_brl"] == 0


@pytest.mark.parametrize("change", [{"origin": "lamina"}, {"rate_pct_year": 1.5},
    {"kind": "faixa"}, {"stale": True}, {"as_of": "2026-08-31"}])
def test_another_source_or_version_never_compares_a_different_fee(change):
    _, fees = inputs()
    fees["lines"][0]["headline"].update(change)
    sec, _ = compute(fees=fees)
    assert sec["lines"][0]["reason_code"] == "fonte_taxa_diverge"
    assert sec["lines"][0]["difference_pp"] is None


def test_refusal_and_missing_rows_are_explicit_gaps():
    sec, _ = compute(error='{"code":"22023","message":"refused"}')
    assert sec["status"] == "unknown" and sec["errors"]
    assert sec["lines"][0]["reason_code"] == "consulta_falhou"
    lines, fees = inputs()
    sec = compute_fee_peers(lines, fees, FakeClient({"portfolio_fee_peers": [{"match": {}, "rows": []}]}),
                            AS_OF, Decimal(100))
    assert sec["lines"][0]["reason_code"] == "sem_linha_comparacao"
    sec, _ = compute(row(status="not_compared", reason_code="pares_insuficientes"))
    assert sec["lines"][0]["reason_code"] == "pares_insuficientes"


def test_unidentified_funds_remain_in_the_coverage_denominator_and_do_not_get_queried():
    lines, fees = inputs(2)
    lines[1].status = "ambiguous"
    c = FakeClient({"portfolio_fee_peers": [{"match": {}, "rows": [row()]}]})
    sec = compute_fee_peers(lines, fees, c, AS_OF, Decimal(200))
    assert sec["coverage_fund_value_pct"] == 50 and sec["n_not_compared"] == 1
    assert sec["lines"][1]["reason_code"] == "sem_identificacao"
    assert len(c.provenance) == 1


def test_chunks_and_deduplication_do_not_drop_positions():
    lines, fees = inputs(201)
    for i, li in enumerate(lines):
        li.cnpj = f"98{i:012d}"
    c = FakeClient({"portfolio_fee_peers": [{"match": {}, "rows": []}]})
    sec = compute_fee_peers(lines, fees, c, AS_OF, Decimal(20100))
    assert [len(p.args["p_cnpjs"]) for p in c.provenance] == [200, 1]
    assert len(sec["lines"]) == 201


def test_report_and_redator_get_the_same_statistics_and_only_fixed_gap_text():
    engine = json.loads((Path(__file__).parent / "fixtures/portfolio/demo_engine_output.json").read_text())
    view = adapt.to_view(engine)
    comp = view["fees"]["comparison"]
    compared = next(r for r in comp["by_line"] if r["status"] == "compared")
    assert compared["difference_pp"] == 1
    assert "errors" not in comp and "sources" not in compared
    html, narrative = build.build(view, provider_name="fake")
    assert "Taxas versus fundos comparáveis" in html and "1,00 p.p." in html
    assert "não comparado:" in html and "Datas dos pares" in html
    assert "portfolio_fee_peers" in html  # provenance, no internal failure message
    assert "fees.comparison" in redator.SYSTEM_PROMPT
    f = redator.Finding(id="fee-peer", section="taxas", title="Taxa versus pares",
        text="A taxa supera a mediana em {{fees.comparison.by_line[0].difference_pp}} pontos percentuais.",
        citations=compared["provenance"])
    # Both a real numeric placeholder and a recorded source are required.
    result = revisor.check(view, [f])
    assert result.kept


@pytest.mark.parametrize("fee_date,expected", [("2025-02-28", "compared"), ("2025-02-27", "not_compared")])
def test_fee_age_limit_clamps_the_leap_day_like_postgres(fee_date, expected):
    lines, fees = inputs()
    fees["lines"][0]["headline"]["as_of"] = fee_date
    r = row(fee_as_of=fee_date, comparison_as_of="2028-02-29", peer_fee_oldest="2025-02-28")
    client = FakeClient({"portfolio_fee_peers": [{"match": {}, "rows": [r]}]})
    sec = compute_fee_peers(lines, fees, client, dt.date(2028, 2, 29), Decimal(100))
    assert sec["lines"][0]["status"] == expected
