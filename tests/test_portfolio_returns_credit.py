"""Engine 2.1 (#766): CRA and CRI returns on the securitizer's curve (method A, api.portfolio_credit_curve).

The function flags every unknown month; the engine compounds the factors and never fills a month in."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from src.portfolio.client import FakeClient
from src.portfolio.common import REASON_TEXT
from src.portfolio.identify import LineId
from src.portfolio.returns import CURVE, CURVE_TOOL, REASONS, compute_returns
from src.portfolio.statement import parse_rows
from tests.test_portfolio_returns import D, MONTHS, cdi_rows, one


def credit_lines(*specs):
    """specs: (tipo, codigo)."""
    stmt = parse_rows([["total_extrato", 100.0 * len(specs)],
                       ["linha_extrato", "tipo", "codigo", "quantidade", "preco_unitario", "valor", "data_posicao"],
                       *[[f"Linha {i}", tipo, code, 1, 100, 100.0, D] for i, (tipo, code) in enumerate(specs, start=1)]])
    return [LineId(p, status="identified", kind="credito", name=p.linha_extrato) for p in stmt.positions]


def curve_rows(line_no, code, monthly=1.01, taxa="110% CDI", flags=None, pays=None):
    """13 months of a clean curve; ``flags`` {month index: flag} blanks that month's factor, ``pays`` {index: paid}."""
    flags, pays = flags or {}, pays or {}
    rows, pu = [], 1000.0
    for i, m in enumerate(MONTHS):
        paid = pays.get(i, 0.0)
        prev = pu
        if i:
            pu = prev * monthly - paid
        flag = flags.get(i)
        factor = None if i == 0 or flag else (pu + paid) / prev
        rows.append(dict(line_no=line_no, input_code=code, code=code.replace("CRA-", ""), month=m.isoformat(),
                         n_series=1, pu=None if flag == "mes_ausente" else pu, paid_per_unit=paid, factor=factor,
                         month_flag=flag, taxa_juros=taxa))
    return rows


def run(lines, rows, ok=True):
    canned = {"macro_series": [{"match": {"p_series": "CDI"}, "rows": cdi_rows()}]}
    if ok:
        canned[CURVE_TOOL] = [{"match": {}, "rows": rows}]
    client = FakeClient(canned)
    sec = compute_returns(lines, {"lines": []}, client, D, Decimal(100 * len(lines)))
    return sec, client


def test_a_clean_curve_compounds_the_monthly_factors_and_a_cdi_rate_gets_pct_of_cdi():
    sec, client = run(credit_lines(("CRI", "24I1980390")), curve_rows(1, "24I1980390", pays={6: 60.0}))
    ln = one(sec)
    assert ln["basis"] == CURVE and ln["code"] == "24I1980390" and ln["status"] == "avaliado"
    w = ln["windows"]["12m"]
    assert w["net_return_pct"] == pytest.approx((1.01 ** 12 - 1) * 100, abs=1e-6)  # the coupon month is (pu + paid) / pu
    assert w["cdi_like"] is True and w["pct_of_cdi"] == pytest.approx(w["net_return_pct"] / w["cdi_pct"] * 100, abs=1e-3)
    assert w["fee_status"] == "nao_se_aplica" and "não preço de mercado" in w["notes"][0]
    assert [m["month"] for m in ln["month_ends"]] == [m.isoformat() for m in MONTHS]
    calls = [p for p in client.provenance if p.tool == CURVE_TOOL]
    assert len(calls) == 1 and calls[0].args == {"p_codes": ["24I1980390"], "p_from": "2025-09-01", "p_to": "2026-09-01"}


def test_a_rate_without_cdi_shows_the_difference_and_no_pct_of_cdi():
    sec, _ = run(credit_lines(("CRA", "CRA-0260000X")), curve_rows(1, "CRA-0260000X", taxa="IPCA + 8,74% a.a."))
    w = one(sec)["windows"]["12m"]
    assert w["status"] == "avaliado" and w["net_minus_cdi_pp"] is not None
    assert w["pct_of_cdi"] is None and w["pct_of_cdi_reason_code"] == "taxa_nao_cdi"
    assert "taxa_nao_cdi" in REASON_TEXT


@pytest.mark.parametrize("flag,index", [("quantidade_mudou", 4), ("mes_ausente", 7), ("queda_sem_evento_arquivado", 10)])
def test_a_flagged_month_leaves_the_window_not_evaluated_with_its_code(flag, index):
    sec, _ = run(credit_lines(("CRI", "24I1980390")), curve_rows(1, "24I1980390", flags={index: flag}))
    ln = one(sec)
    w12, w6 = ln["windows"]["12m"], ln["windows"]["6m"]
    assert w12["status"] == "nao_avaliado" and w12["reason_code"] == f"curva_{flag}"
    assert w12["net_return_pct"] is None and w12["unknown_months"][0] == {"month": MONTHS[index].isoformat(), "flag": flag}
    assert w12["reason"] == REASONS[f"curva_{flag}"] and f"curva_{flag}" in REASON_TEXT
    # a flag before the 6-month window's base month leaves that window evaluated
    assert w6["status"] == ("avaliado" if index < 6 else "nao_avaliado")


def test_a_missing_base_month_is_not_evaluated():
    sec, _ = run(credit_lines(("CRA", "CRA0260025T")), curve_rows(1, "CRA0260025T", flags={0: "mes_ausente"}))
    assert one(sec)["windows"]["12m"]["reason_code"] == "curva_mes_ausente"


def test_every_cra_and_cri_goes_in_one_call_and_other_credit_keeps_no_series():
    lines = credit_lines(("CRA", "CRA-0260000X"), ("CDB", "CDB-1"), ("CRI", "24I1980390"))
    rows = curve_rows(1, "CRA-0260000X") + curve_rows(2, "24I1980390")
    sec, client = run(lines, rows)
    assert [p.args["p_codes"] for p in client.provenance if p.tool == CURVE_TOOL] == [["24I1980390", "CRA-0260000X"]]
    assert one(sec, 1)["status"] == one(sec, 3)["status"] == "avaliado"
    assert one(sec, 2)["reason_code"] == "retorno_credito_sem_serie"


def test_a_failed_call_leaves_every_curve_line_not_evaluated():
    sec, _ = run(credit_lines(("CRA", "CRA-0260000X")), [], ok=False)
    assert one(sec)["reason_code"] == "consulta_falhou"


def test_a_cra_without_a_code_has_no_curve():
    sec, client = run(credit_lines(("CRA", None)), [])
    assert one(sec)["reason_code"] == "retorno_curva_sem_codigo"
    assert not [p for p in client.provenance if p.tool == CURVE_TOOL]
