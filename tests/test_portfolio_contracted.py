"""Engine 2.1 (#766, method C): the contracted return of a CDB, LCI, LCA or CDCA, apart from the measured returns."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from src.portfolio.client import FakeClient
from src.portfolio.common import REASON_TEXT
from src.portfolio.contracted import REASONS, parse_rate
from src.portfolio.identify import LineId
from src.portfolio.returns import compute_returns
from src.portfolio.statement import parse_rows
from tests.test_portfolio_returns import CDI_DAYS, D, MONTHS, cdi_rows

RATE = 0.05  # % a business day, as cdi_rows() serves it


def lines(*specs):
    """specs: (tipo, taxa, data_inicial)."""
    stmt = parse_rows([["total_extrato", 100.0 * len(specs)],
                       ["linha_extrato", "tipo", "codigo", "quantidade", "preco_unitario", "valor", "data_posicao", "taxa", "vencimento"],
                       *[[f"Linha {i}", t, None, 1, 100, 100.0, D, taxa, dt.date(2030, 1, 1)] for i, (t, taxa, _) in enumerate(specs, 1)]])
    out = []
    for p, (_, _, inicio) in zip(stmt.positions, specs):
        object.__setattr__(p, "data_inicial", inicio)  # the PDF reader sets it; the sheet has no such column
        out.append(LineId(p, status="unknown", kind="credito", name=p.linha_extrato))
    return out


def run(ls, ipca=None):
    canned = {"macro_series": [{"match": {"p_series": "CDI"}, "rows": cdi_rows()}]}
    if ipca is not None:
        canned["inflation"] = [{"match": {}, "rows": ipca}]
    client = FakeClient(canned)
    sec = compute_returns(ls, {"lines": []}, client, D, Decimal(100 * len(ls)))
    return sec, client


def w12(sec, line_no=1):
    return next(l for l in sec["contracted"]["lines"] if l["line_no"] == line_no)["windows"]["12m"]


def window_days():
    from src.portfolio.returns import _Cdi
    c = _Cdi([(d, Decimal(str(RATE))) for d in CDI_DAYS], None, None)
    start, end = c.month_end(MONTHS[0]), c.month_end(MONTHS[-1])
    return [d for d in CDI_DAYS if start <= d < end]


@pytest.mark.parametrize("text,expected", [
    ("112,00% do CDI", {"kind": "pct_cdi", "value_pct": 112.0}), ("CDI", {"kind": "pct_cdi", "value_pct": 100.0}),
    ("CDI + 1,80%", {"kind": "cdi_spread", "value_pct": 1.8}), ("IPCA + 6,20%", {"kind": "ipca_spread", "value_pct": 6.2}),
    ("15,41% a.a.", {"kind": "prefixado", "value_pct": 15.41}), ("100% CDI + 15,4102% a.a.", None), ("", None), (None, None),
])
def test_only_the_five_plain_shapes_are_read(text, expected):
    assert parse_rate(text) == expected


def test_pct_of_cdi_accrues_on_the_daily_cdi_and_gives_pct_of_cdi():
    sec, _ = run(lines(("CDB", "110% do CDI", dt.date(2021, 11, 9))))
    w = w12(sec)
    n = len(window_days())
    assert w["status"] == "avaliado" and w["n_business_days"] == n
    assert w["contracted_return_pct"] == pytest.approx(((1 + RATE / 100 * 1.1) ** n - 1) * 100, abs=1e-6)
    assert w["pct_of_cdi"] == pytest.approx(w["contracted_return_pct"] / w["cdi_pct"] * 100, abs=1e-3)


def test_prefixed_and_ipca_rates_show_the_difference_and_no_pct_of_cdi():
    ipca = [dict(reference_date=m.isoformat(), series="IPCA", value=0.4) for m in MONTHS]
    sec, client = run(lines(("CDB", "12,00% a.a.", dt.date(2024, 1, 1)), ("CDB", "IPCA + 6,20%", dt.date(2021, 11, 9))), ipca)
    n = len(window_days())
    pre, ip = w12(sec, 1), w12(sec, 2)
    assert pre["contracted_return_pct"] == pytest.approx((1.12 ** (n / 252) - 1) * 100, abs=1e-6)
    assert ip["contracted_return_pct"] == pytest.approx((1.004 ** 12 * 1.062 ** (n / 252) - 1) * 100, abs=1e-6)
    assert pre["pct_of_cdi"] is None and pre["pct_of_cdi_reason_code"] == "taxa_nao_cdi" and pre["net_minus_cdi_pp"] is not None
    assert [p.args for p in client.provenance if p.tool == "inflation"] == [
        {"p_series": "IPCA", "p_from": "2025-09-01", "p_to": "2026-09-01"}]


@pytest.mark.parametrize("inicio,taxa,code", [
    (None, "110% do CDI", "contratado_sem_data_inicial"),
    (dt.date(2026, 7, 28), "110% do CDI", "contratado_papel_mais_novo"),
    (dt.date(2021, 1, 1), "100% CDI + 15,4102% a.a.", "contratado_taxa_ilegivel"),
    (dt.date(2021, 1, 1), None, "contratado_sem_taxa"),
])
def test_a_contract_that_cannot_cover_the_window_is_not_evaluated(inicio, taxa, code):
    sec, _ = run(lines(("CDB", taxa, inicio)))
    w = w12(sec)
    assert w["status"] == "nao_avaliado" and w["reason_code"] == code and w["contracted_return_pct"] is None
    assert code in REASON_TEXT and code in REASONS


def test_a_missing_ipca_month_is_not_evaluated():
    ipca = [dict(reference_date=m.isoformat(), series="IPCA", value=0.4) for m in MONTHS[:-1]]
    sec, _ = run(lines(("CDB", "IPCA + 6,20%", dt.date(2021, 11, 9))), ipca)
    assert w12(sec)["reason_code"] == "contratado_ipca_indisponivel"


def test_the_contracted_return_never_enters_the_measured_lines_or_the_coverage():
    sec, _ = run(lines(("CDB", "110% do CDI", dt.date(2021, 11, 9))))
    assert sec["contracted"]["n_evaluated"] == 1 and sec["contracted"]["label"] == "retorno contratado"
    assert sec["lines"][0]["status"] == "nao_avaliado" and sec["coverage"]["12m"]["n_evaluated"] == 0


def test_the_report_shows_the_contracted_return_in_the_annex_only():
    import copy
    import json
    from pathlib import Path
    from src.portfolio.report import adapt, build
    eng = json.loads((Path(__file__).parent / "fixtures" / "portfolio" / "demo_engine_output.json").read_text(encoding="utf-8"))
    c = eng["returns"]["contracted"]["lines"][0]
    c["data_inicial"] = "2021-11-09"
    c["windows"]["12m"].update(status="avaliado", reason_code=None, contracted_return_pct=15.2, cdi_pct=14.4,
                               net_minus_cdi_pp=0.8, pct_of_cdi=105.5, base_date="2025-09-30", end_date="2026-09-30")
    html_text, _ = build.build(adapt.to_view(copy.deepcopy(eng)), "fake")
    body, annex = html_text.split('<details id="apendice">')
    assert "Retorno contratado (não é retorno de mercado)" not in body and "retorno contratado" not in body.lower()
    sec = annex.split("<h2>Retorno contratado (não é retorno de mercado)</h2>")[1].split("</section>")[0]
    assert "15,20%" in sec and "105,50% do CDI" in sec and "Sem retorno contratado:" in sec
