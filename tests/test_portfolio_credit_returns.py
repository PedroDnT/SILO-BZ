"""Schema 2.1 (#766): the return of direct credit, offline.

Method A: a CRA or CRI on the securitizer's curve (``portfolio_credit_returns``, one call for every such line).
Method C: the contracted return of a CDB, LCI, LCA or CDCA, from the rate the statement prints, in the line's
``contracted`` block and never in a measured figure or total. Method B (debentures) is not built (owner, 2026-10-08).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from decimal import Decimal

import pytest

from src.portfolio import contracted
from src.portfolio.client import FakeClient
from src.portfolio.common import REASON_TEXT
from src.portfolio.identify import LineId
from src.portfolio.returns import CURVE, DEBENTURE, compute_returns
from src.portfolio.statement import parse_rows

D = dt.date(2026, 8, 31)  # the 08/10 report's position date: windows end in 2026-08
MONTHS = [dt.date(2025 + (7 + i) // 12, (7 + i) % 12 + 1, 1) for i in range(13)]  # 2025-08 .. 2026-08


def weekdays(start: dt.date, end: dt.date) -> list[dt.date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


CDI_DAYS = weekdays(dt.date(2025, 8, 1), D)
CDI_RATE = Decimal("0.05")


def cdi_rows():
    return [dict(reference_date=d.isoformat(), series="CDI", value=float(CDI_RATE)) for d in CDI_DAYS]


def month_end(m: dt.date) -> dt.date:
    return max(d for d in CDI_DAYS if d.year == m.year and d.month == m.month)


def cdi_between(a: dt.date, b: dt.date) -> tuple[Decimal, int]:
    n = sum(1 for d in CDI_DAYS if a <= d < b)
    return (1 + CDI_RATE / 100) ** n - 1, n


def credit_line(tipo="CRA", code="CRA0250018H", taxa="100% CDI", valor=100.0, inicial=None, venc=None, serie=1,
                linha=None, status="identified"):
    stmt = parse_rows([["total_extrato", valor],
                       ["linha_extrato", "tipo", "codigo", "quantidade", "preco_unitario", "valor", "data_posicao"],
                       [linha or f"EMISSOR - {tipo}-{code}*", tipo, f"{tipo}-{code}", 1, valor, valor, D]])
    p = dataclasses.replace(stmt.positions[0], taxa_texto=taxa, data_inicial=inicial, vencimento=venc)
    credit = {"match_kind": "securit_cetip", "code": code, "numero_serie": str(serie), "classe": "Sênior"} if tipo in ("CRA", "CRI") else None
    return LineId(p, status=status, kind="credito", credit=credit)


def renumber(lines):
    out = []
    for i, li in enumerate(lines, start=1):
        p = dataclasses.replace(li.position, line_no=i, source_row=i)
        out.append(dataclasses.replace(li, position=p))
    return out


def curve_rows(line_no, code, factors, flags=None, pu0=1000.0):
    """13 month rows: pu growing by each factor; flags {month index: flag} blank the factor."""
    flags = flags or {}
    rows, pu = [], pu0
    for i, m in enumerate(MONTHS):
        f = None if i == 0 else factors[i - 1]
        if i:
            pu = pu * f
        flag = flags.get(i)
        rows.append(dict(line_no=line_no, input_code=code, code=code, numero_serie=1, classe="Sênior", month=m.isoformat(),
                         data_referencia=None if flag == "mes_ausente" else m.isoformat(), versao=1,
                         quantidade_certificados=1000, valor_certificados=pu * 1000, rendimentos=0, amortizacoes=0,
                         pu=pu, paid_per_unit=0, factor=None if (i == 0 or flag) else f, month_flag=flag,
                         taxa_juros="100% CDI", data_vencimento="2031-01-15", reason="valor na curva (sintético)"))
    return rows


def run(lines, canned=None, total=None):
    canned = {"macro_series": [{"match": {"p_series": "CDI"}, "rows": cdi_rows()}], **(canned or {})}
    client = FakeClient(canned)
    total = total or Decimal(str(sum(float(li.position.valor) for li in lines)))
    return compute_returns(lines, {"lines": []}, client, D, total), client


def one(sec, line_no=1):
    return next(ln for ln in sec["lines"] if ln["line_no"] == line_no)


FLAT = [1.01] * 12


# Method A ------------------------------------------------------------------------------------------------


def test_a_clean_series_compounds_the_factors_over_the_cdi_calendar_month_ends():
    sec, client = run([credit_line()], {"portfolio_credit_returns": [{"match": {}, "rows": curve_rows(1, "CRA0250018H", FLAT)}]})
    ln = one(sec)
    assert (ln["basis"], ln["status"], ln["credit_code"]) == (CURVE, "avaliado", "CRA0250018H")
    w = ln["windows"]["12m"]
    assert w["net_return_pct"] == pytest.approx((1.01 ** 12 - 1) * 100, abs=1e-6)
    cdi, n = cdi_between(month_end(MONTHS[0]), month_end(MONTHS[-1]))
    assert (w["cdi_base_date"], w["cdi_end_date"], w["cdi_n_rates"]) == (
        month_end(MONTHS[0]).isoformat(), month_end(MONTHS[-1]).isoformat(), n)
    assert w["cdi_pct"] == pytest.approx(float(cdi * 100), abs=1e-5)
    # the rate the statement prints contains CDI: "% do CDI" is shown
    assert w["cdi_like"] is True and w["pct_of_cdi"] == pytest.approx(w["net_return_pct"] / w["cdi_pct"] * 100, abs=1e-3)
    assert ln["fee"]["status"] == "nao_se_aplica" and ln["fee"]["reason_code"] == "taxa_credito_sem_taxa_adm"
    assert ln["windows"]["6m"]["status"] == "avaliado"
    assert [m["factor"] for m in ln["month_ends"]][1] == pytest.approx(1.01)
    calls = [p for p in client.provenance if p.tool == "portfolio_credit_returns"]
    assert len(calls) == 1 and calls[0].args["p_codes"] == ["CRA0250018H"] and calls[0].args["p_end_month"] == "2026-08-01"
    assert calls[0].args["p_series"] == [1] and calls[0].args["p_classes"] == ["Sênior"]


def test_a_value_on_the_curve_is_counted_in_coverage_and_left_out_of_the_contribution():
    sec, _ = run([credit_line()], {"portfolio_credit_returns": [{"match": {}, "rows": curve_rows(1, "CRA0250018H", FLAT)}]})
    assert sec["coverage"]["12m"]["n_evaluated"] == 1 and sec["coverage"]["12m"]["coverage_portfolio_value_pct"] == 100.0
    c = sec["contribution"]["windows"]["12m"]
    assert c["status"] == "nao_avaliado" and c["n_lines"] == 0
    assert c["excluded_lines"] == [{"line_no": 1, "basis": CURVE, "reason_code": "metodo_fora_do_total"}]
    assert "metodo_fora_do_total" in REASON_TEXT


def test_a_quantity_change_makes_every_window_that_holds_it_unknown():
    # month 3 (2025-11) is in the 12-month window, not in the 6-month one
    rows = curve_rows(1, "CRA0250018H", FLAT, flags={3: "quantidade_mudou"})
    sec, _ = run([credit_line()], {"portfolio_credit_returns": [{"match": {}, "rows": rows}]})
    ln = one(sec)
    w = ln["windows"]["12m"]
    assert w["status"] == "nao_avaliado" and w["reason_code"] == "quantidade_mudou" and w["net_return_pct"] is None
    assert w["month_flags"] == [{"month": "2025-11-01", "flag": "quantidade_mudou"}]
    assert ln["windows"]["6m"]["status"] == "avaliado" and ln["status"] == "avaliado"


def test_a_missing_month_is_the_existing_incomplete_series_code_with_its_months():
    rows = curve_rows(1, "CRA0250018H", FLAT, flags={11: "mes_ausente", 12: "mes_ausente"})
    sec, _ = run([credit_line()], {"portfolio_credit_returns": [{"match": {}, "rows": rows}]})
    ln = one(sec)
    assert ln["status"] == "nao_avaliado" and ln["reason_code"] == "serie_incompleta"
    assert ln["windows"]["12m"]["missing_months"] == ["2026-07-01", "2026-08-01"]
    assert ln["windows"]["6m"]["reason_code"] == "serie_incompleta"


@pytest.mark.parametrize("flag", ["pu_repetido", "pagamento_acima_do_pu", "pagamento_incompativel", "valor_invalido",
                                  "serie_ambigua"])
def test_a_every_month_flag_is_the_windows_reason_with_its_fixed_text(flag):
    # pagamento_incompativel: CRA02400AYL filed 238.01 a unit in 2026-05 for a fall of about 60 (measured 2026-10-08);
    # without it the 6-month window read 23.86%, 340% of the CDI
    rows = curve_rows(1, "CRA02400AYL", FLAT, flags={9: flag})
    sec, _ = run([credit_line(code="CRA02400AYL")], {"portfolio_credit_returns": [{"match": {}, "rows": rows}]})
    ln = one(sec)
    assert ln["windows"]["6m"]["reason_code"] == flag and ln["windows"]["6m"]["net_return_pct"] is None
    assert flag in REASON_TEXT


def test_a_fall_with_no_payment_filed_is_unknown_never_a_loss():
    # MRV's CRI 24I1980390, 2026-04: the pu fell 6.1% and no coupon was filed (measured 2026-10-08)
    rows = curve_rows(1, "24I1980390", FLAT, flags={8: "queda_sem_evento_arquivado"})
    sec, _ = run([credit_line(tipo="CRI", code="24I1980390", taxa="112,00% do CDI")],
                 {"portfolio_credit_returns": [{"match": {}, "rows": rows}]})
    ln = one(sec)
    assert ln["reason_code"] == "queda_sem_evento_arquivado" and ln["windows"]["12m"]["net_return_pct"] is None
    assert "queda_sem_evento_arquivado" in REASON_TEXT


@pytest.mark.parametrize("taxa,code", [("IPCA + 8,40%", "credito_nao_cdi"), ("15,41% a.a.", "credito_nao_cdi"),
                                       (None, "taxa_nao_informada")])
def test_a_paper_not_on_the_cdi_shows_the_difference_and_no_pct_of_cdi(taxa, code):
    sec, _ = run([credit_line(taxa=taxa)], {"portfolio_credit_returns": [{"match": {}, "rows": curve_rows(1, "CRA0250018H", FLAT)}]})
    w = one(sec)["windows"]["12m"]
    assert w["pct_of_cdi"] is None and w["pct_of_cdi_reason_code"] == code and w["net_minus_cdi_pp"] is not None
    assert code in REASON_TEXT


def test_a_is_one_call_for_every_cra_and_cri_and_an_unmatched_line_is_not_read():
    lines = renumber([credit_line(code="AAA1"), credit_line(tipo="CRI", code="BBB2"),
                      credit_line(code="CCC3", status="unknown")])
    rows = curve_rows(1, "AAA1", FLAT) + curve_rows(2, "BBB2", FLAT)
    sec, client = run(lines, {"portfolio_credit_returns": [{"match": {}, "rows": rows}]})
    calls = [p for p in client.provenance if p.tool == "portfolio_credit_returns"]
    assert len(calls) == 1 and calls[0].args["p_codes"] == ["AAA1", "BBB2"]
    assert [ln["status"] for ln in sec["lines"]] == ["avaliado", "avaliado", "nao_avaliado"]
    assert one(sec, 3)["reason_code"] == "retorno_linha_nao_identificada"


def test_a_response_for_another_code_is_inconsistent():
    rows = curve_rows(1, "OTHER", FLAT)
    sec, _ = run([credit_line()], {"portfolio_credit_returns": [{"match": {}, "rows": rows}]})
    assert one(sec)["reason_code"] == "resposta_inconsistente" and sec["status"] == "partial"


def test_a_failed_call_is_recorded_and_the_line_is_not_evaluated():
    sec, _ = run([credit_line()], {"portfolio_credit_returns": [{"match": {}, "error": "22023: refused"}]})
    assert one(sec)["reason_code"] == "consulta_falhou" and sec["errors"][0]["error"] == "22023: refused"


def test_a_debenture_waits_for_its_method_and_makes_no_call():
    sec, client = run([credit_line(tipo="debênture", code="CUTI11", taxa="IPCA + 5,00%")])
    assert one(sec)["reason_code"] == "retorno_debenture_sem_serie"
    assert [p.tool for p in client.provenance] == ["macro_series"]


# Method C ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("text,indexer,value", [
    ("110,00% do CDI", "pct_cdi", 110.0), ("105% CDI", "pct_cdi", 105.0), ("CDI + 1,50%", "cdi_spread", 1.5),
    ("CDI + 0,5% a.a.", "cdi_spread", 0.5), ("IPCA + 6,20%", "ipca_spread", 6.2), ("ipca + 6,2 % a.a", "ipca_spread", 6.2),
    ("11,87% a.a.", "prefixado", 11.87), ("13,84% a.a", "prefixado", 13.84),
])
def test_c_reads_only_the_four_rate_shapes(text, indexer, value):
    assert contracted.parse_rate(text) == {"indexer": indexer, "value": value}


@pytest.mark.parametrize("text", ["CDI", "IPCA", "100% CDI + 15,4102% a.a.", "IGPM + 6%", "", None, "11,87%"])
def test_c_any_other_text_is_not_read(text):
    assert contracted.parse_rate(text) is None


def bank_line(taxa="105,00% do CDI", inicial=dt.date(2024, 1, 10), venc=dt.date(2027, 3, 15), tipo="CDB", linha=None):
    return credit_line(tipo=tipo, code="CDB421A6V20", taxa=taxa, inicial=inicial, venc=venc, linha=linha)


def debenture_line(ticker="CUTI11", linha=None):
    li = credit_line(tipo="debênture", code=ticker, taxa="110% CDI", linha=linha)
    return dataclasses.replace(li, credit={"match_kind": "cda_ticker", "code": ticker})


def debenture_rows(line_no=1, ticker="CUTI11", flags=None, n_fundos=3, drop_at=None, missing=None):
    flags, out, pu = flags or {}, [], Decimal("100")
    for i, m in enumerate(MONTHS):
        if i and i == drop_at:
            pu *= Decimal("0.90")
        row_flag = flags.get(i)
        if i == missing:
            row_flag = "mes_ausente"
        if i and row_flag is None and i != drop_at:
            pu *= Decimal("1.005")
        out.append(dict(line_no=line_no, input_ticker=ticker, ticker=ticker, month=m.isoformat(),
                        n_fundos=0 if row_flag == "mes_ausente" else n_fundos, n_invalid_fundos=0,
                        median_pu=float(pu), factor=None if i == 0 or row_flag else 1.005,
                        month_flag=row_flag, reason="marca mediana sintética"))
    return out


# Method B ------------------------------------------------------------------------------------------------


def test_b_uses_one_bounded_call_and_returns_the_median_mark_against_cdi():
    rows = debenture_rows()
    sec, client = run([debenture_line()], {"portfolio_debenture_returns": [{"match": {}, "rows": rows}]})
    ln = one(sec)
    assert ln["basis"] == DEBENTURE and ln["windows"]["12m"]["status"] == "avaliado"
    assert ln["windows"]["12m"]["months_used"] == [m.isoformat() for m in MONTHS]
    assert ln["windows"]["12m"]["pct_of_cdi"] is not None
    assert ln["series"]["source_table"] == "cvm_fi_cda_acoes"
    assert [(c.tool, c.args["p_tickers"], c.args["p_max_monthly_drop_pct"]) for c in client.provenance if c.tool == "portfolio_debenture_returns"] == [
        ("portfolio_debenture_returns", ["CUTI11"], None)]


@pytest.mark.parametrize("flag", ["mes_ausente", "fundos_insuficientes", "posicao_invalida", "limite_pendente"])
def test_b_unknown_month_keeps_the_12m_window_unknown_with_the_flag(flag):
    rows = debenture_rows(flags={5: flag}, n_fundos=2 if flag == "fundos_insuficientes" else 3)
    sec, _ = run([debenture_line()], {"portfolio_debenture_returns": [{"match": {}, "rows": rows}]})
    w = one(sec)["windows"]["12m"]
    assert w["status"] == "nao_avaliado" and w["reason_code"] == flag
    assert w["net_return_pct"] is None and "2026-01-01" in w["months_used"]


def test_b_large_pu_fall_is_unknown_as_a_possible_event_and_never_a_loss():
    rows = debenture_rows(drop_at=5, flags={5: "queda_pu_possivel_evento"})
    sec, _ = run([debenture_line()], {"portfolio_debenture_returns": [{"match": {}, "rows": rows}]})
    w = one(sec)["windows"]["12m"]
    assert w["status"] == "nao_avaliado" and w["reason_code"] == "queda_pu_possivel_evento"
    assert w["net_return_pct"] is None


def test_b_missing_month_is_reported_instead_of_shortening_the_window():
    rows = debenture_rows(missing=8)
    sec, _ = run([debenture_line()], {"portfolio_debenture_returns": [{"match": {}, "rows": rows}]})
    w = one(sec)["windows"]["12m"]
    assert w["status"] == "nao_avaliado" and w["reason_code"] == "mes_ausente"
    assert w["missing_months"] == ["2026-04-01"]


def test_c_pct_of_cdi_is_b3s_di_factor_at_the_printed_percentage():
    sec, _ = run([bank_line()])
    ln = one(sec)
    assert ln["status"] == "nao_avaliado" and ln["reason_code"] == "retorno_contratado_anexo" and ln["basis"] is None
    c = ln["contracted"]
    assert (c["label"], c["rate"], c["data_inicial"], c["data_inicial_source"]) == (
        "retorno contratado", {"indexer": "pct_cdi", "value": 105.0}, "2024-01-10", "data_inicial")
    w = c["windows"]["12m"]
    d0, d1 = month_end(MONTHS[0]), month_end(MONTHS[-1])
    _, n = cdi_between(d0, d1)
    expect = (1 + CDI_RATE / 100 * Decimal("1.05")) ** n - 1
    assert w["status"] == "avaliado" and w["n_business_days"] == n
    assert w["accrual_pct"] == pytest.approx(float(expect * 100), abs=1e-5)
    assert w["pct_of_cdi"] == pytest.approx(w["accrual_pct"] / w["cdi_pct"] * 100, abs=1e-3)
    assert 104.9 < w["pct_of_cdi"] < 105.6


def test_c_cdi_spread_and_prefixado_compound_the_spread_over_business_days_of_252():
    lines = renumber([bank_line(taxa="CDI + 1,50%"), bank_line(taxa="12,00% a.a.", tipo="LCA")])
    sec, _ = run(lines)
    d0, d1 = month_end(MONTHS[0]), month_end(MONTHS[-1])
    cdi, n = cdi_between(d0, d1)
    spread = Decimal("1.015") ** (Decimal(n) / 252)
    w1, w2 = one(sec, 1)["contracted"]["windows"]["12m"], one(sec, 2)["contracted"]["windows"]["12m"]
    assert w1["accrual_pct"] == pytest.approx(float(((1 + cdi) * spread - 1) * 100), abs=1e-5)
    assert w1["pct_of_cdi"] is not None
    assert w2["accrual_pct"] == pytest.approx(float((Decimal("1.12") ** (Decimal(n) / 252) - 1) * 100), abs=1e-5)
    assert w2["pct_of_cdi"] is None and w2["pct_of_cdi_reason_code"] == "credito_nao_cdi"


def test_c_ipca_spread_uses_the_windows_ipca_months_and_says_it_is_an_approximation():
    ipca = [dict(reference_date=m.isoformat(), series="IPCA", value=0.4) for m in MONTHS[1:]]
    sec, client = run([bank_line(taxa="IPCA + 6,20%", venc=dt.date(2026, 11, 9))],
                      {"inflation": [{"match": {"p_series": "IPCA"}, "rows": ipca}]})
    c = one(sec)["contracted"]
    w = c["windows"]["12m"]
    _, n = cdi_between(month_end(MONTHS[0]), month_end(MONTHS[-1]))
    expect = Decimal("1.004") ** 12 * Decimal("1.062") ** (Decimal(n) / 252) - 1
    assert w["accrual_pct"] == pytest.approx(float(expect * 100), abs=1e-5)
    assert w["index_pct"] == pytest.approx(float((Decimal("1.004") ** 12 - 1) * 100), abs=1e-6)
    assert w["approximation"] == contracted.NOTE_IPCA and contracted.NOTE_IPCA in c["notes"]
    assert w["pct_of_cdi_reason_code"] == "credito_nao_cdi"
    calls = [p for p in client.provenance if p.tool == "inflation"]
    assert len(calls) == 1 and calls[0].args == {"p_series": "IPCA", "p_from": "2025-09-01", "p_to": "2026-09-01"}


def test_c_ipca_month_missing_is_not_computed():
    ipca = [dict(reference_date=m.isoformat(), series="IPCA", value=0.4) for m in MONTHS[1:-1]]
    sec, _ = run([bank_line(taxa="IPCA + 6,20%")], {"inflation": [{"match": {}, "rows": ipca}]})
    assert one(sec)["contracted"]["windows"]["12m"]["reason_code"] == "contratado_ipca_indisponivel"


@pytest.mark.parametrize("kw,code", [
    (dict(inicial=None), "contratado_sem_data_inicial"),
    (dict(inicial=dt.date(2026, 5, 5)), "contratado_papel_mais_novo"),  # after both windows' base dates
    (dict(venc=dt.date(2026, 6, 1)), "contratado_vence_na_janela"),
    (dict(taxa="CDI"), "contratado_taxa_ilegivel"),
])
def test_c_the_paper_must_exist_for_the_whole_window_and_its_rate_be_legible(kw, code):
    sec, _ = run([bank_line(**kw)])
    c = one(sec)["contracted"]
    assert c["status"] == "nao_avaliado" and c["reason_code"] == code and code in REASON_TEXT
    assert c["windows"]["12m"]["accrual_pct"] is None


def test_c_a_younger_paper_can_still_have_its_6_month_window():
    sec, _ = run([bank_line(inicial=dt.date(2026, 1, 5))])
    c = one(sec)["contracted"]
    assert c["windows"]["12m"]["reason_code"] == "contratado_papel_mais_novo"
    assert c["windows"]["6m"]["status"] == "avaliado" and c["status"] == "avaliado"


def test_c_a_cdca_the_statement_prints_is_bank_credit_and_other_lines_carry_no_contracted_block():
    cdca = bank_line(taxa="11,87% a.a.", tipo="outro", linha="BTG PACTUAL COMMODITIES SERTRADING S.A. - CDCA-24G02736842*")
    lines = renumber([cdca, credit_line()])
    sec, _ = run(lines, {"portfolio_credit_returns": [{"match": {}, "rows": curve_rows(1, "CRA0250018H", FLAT)}]})
    assert one(sec, 1)["reason_code"] == "retorno_contratado_anexo"
    assert one(sec, 1)["contracted"]["windows"]["12m"]["status"] == "avaliado"
    assert one(sec, 2)["contracted"] is None


def test_c_is_never_a_measured_return_coverage_or_contribution():
    lines = renumber([bank_line(), credit_line()])
    sec, _ = run(lines, {"portfolio_credit_returns": [{"match": {}, "rows": curve_rows(1, "CRA0250018H", FLAT)}]},
                 total=Decimal(200))
    cov = sec["coverage"]["12m"]
    assert (cov["n_evaluated"], cov["coverage_portfolio_value_pct"]) == (1, 50.0)  # the CRA only
    assert (cov["n_contracted"], cov["contracted_coverage_portfolio_value_pct"]) == (1, 50.0)
    assert sec["n_evaluated"] == 1 and one(sec, 1)["windows"]["12m"]["status"] == "nao_avaliado"
    assert sec["contribution"]["windows"]["12m"]["n_lines"] == 0
    assert sec["contracted_note"] == contracted.NOTE
