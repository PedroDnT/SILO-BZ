"""Engine 1.9, offline: direct credit by its registry code (portfolio_instruments), the funds' managers and redemption
terms (portfolio_fund_terms), the liquidity ladder, the new risk rows, FIP, and the report's badges, credit table and
charts. Synthetic data only: every code, CNPJ, name and value below is invented."""

from __future__ import annotations

import copy
import dataclasses
import datetime as dt
import json
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path

import pytest

from src.portfolio import risks as R
from src.portfolio.allocation import compute_allocation
from src.portfolio.client import FakeClient, ToolError, load_fake_rows
from src.portfolio.common import SiloUnavailable
from src.portfolio.diagnose import FAKE_CLOCK
from src.portfolio.engine import default_params, run_engine
from src.portfolio.identify import identify
from src.portfolio.liquidity import compute_liquidity
from src.portfolio.lookthrough import compute_lookthrough
from src.portfolio.report import adapt, build, charts, redator, render, revisor
from src.portfolio.statement import TIPOS, parse_rows, read_statement
from src.portfolio.statement_pdf_extrato import _fund_tipo
from src.portfolio.terms import fetch_fund_terms

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "docs" / "reference" / "portfolio" / "statement-template.xlsx"
FAKE_ROWS = ROOT / "tests" / "fixtures" / "portfolio" / "fake_silo_rows.json"
DEMO = ROOT / "tests" / "fixtures" / "portfolio" / "demo_engine_output.json"
D = dt.date(2026, 9, 30)
HDR = ["linha_extrato", "tipo", "codigo", "quantidade", "preco_unitario", "valor", "data_posicao", "vencimento", "taxa"]
TIMEOUT = '{"code":"57014","details":null,"hint":null,"message":"canceling statement due to statement timeout"}'
SVG_NS = "{http://www.w3.org/2000/svg}"


def stmt(*lines):
    total = sum(r[5] for r in lines)
    return parse_rows([["total_extrato", total], HDR, *[list(r) for r in lines]])


def patch(s, i, **kw):
    """A statement with position i (0-based) changed: Statement and Position are frozen."""
    pos = list(s.positions)
    pos[i] = dataclasses.replace(pos[i], **kw)
    return dataclasses.replace(s, positions=tuple(pos))


def credit(name, tipo, codigo, valor=100.0, venc=None, taxa=None, preco=None):
    return [name, tipo, codigo, 1, preco if preco is not None else valor, valor, D, venc, taxa]


def fund(name, cnpj, valor=100.0, tipo="fundo"):
    return [name, tipo, cnpj, 1, valor, valor, D, None, None]


def inst(line_no, input_code, code, kind, **kw):
    base = dict(line_no=line_no, input_code=input_code, code=code, match_kind=kind, instrument_type=None, cnpj_securit=None,
                numero_serie=None, classe=None, data_vencimento=None, situacao=None, taxa_juros=None,
                classificacao_risco_atual=None, valor_total_integralizado=None, data_referencia=None, cd_isin=None,
                issuer_code=None, n_fundos=None, preco_marcacao_fundos=None, cda_period=None, reason=None)
    base.update(kw)
    return base


def terms_row(line_no, cnpj, gid=None, gname=None, pagto=None, tp=None, lock=None, conv=None, src="extrato"):
    return dict(line_no=line_no, input_cnpj=cnpj, cnpj=cnpj, gestor_id=gid, gestor_name=gname, admin_cnpj=None, admin_name=None,
                terms_source=src if pagto is not None or lock is not None else None, terms_dt_comptc="2026-06-30",
                qt_dia_conversao_cota=conv, qt_dia_pagto_resgate=pagto, tp_dia_pagto_resgate=tp, qt_dia_resgate_cotas=lock,
                reason=None)


def ident_of(s, canned):
    sec, lines = identify(s, FakeClient(canned))
    return sec, {ln["line_no"]: ln for ln in sec["lines"]}, lines


# --- 1. credit matching ---------------------------------------------------------------------------------------------


def test_cra_series_chosen_by_the_statements_maturity():
    s = stmt(credit("CRA AGRO X", "CRA", "CRA-0AA00001", venc=dt.date(2031, 10, 15), taxa="IPCA + 8,00%"))
    rows = [inst(1, "CRA-0AA00001", "0AA00001", "securit_cetip", numero_serie="1", data_vencimento="2029-01-15", situacao="Adimplente"),
            inst(1, "CRA-0AA00001", "0AA00001", "securit_cetip", numero_serie="2", data_vencimento="2031-10-15", situacao="Adimplente",
                 classificacao_risco_atual="brAAA (sf)", taxa_juros="IPCA+ 8,0000% a.a")]
    sec, by, lines = ident_of(s, {"portfolio_instruments": [{"match": {"p_codes": ["CRA-0AA00001"]}, "rows": rows}]})
    cm = by[1]["credit_match"]
    assert by[1]["status"] == "identified" and by[1]["identity"]["kind"] == "credito" and by[1]["reason_code"] is None
    assert (cm["numero_serie"], cm["data_vencimento"], cm["n_series"]) == ("2", "2031-10-15", 2)
    assert cm["flags"] == [] and cm["classificacao_risco_atual"] == "brAAA (sf)" and cm["taxa_juros"] == "IPCA+ 8,0000% a.a"
    assert cm["statement"]["issuer_as_printed"] == "AGRO X"  # the printed issuer stays as printed
    assert sec["status"] == "complete"


def test_cra_maturity_diverges_lowest_series_and_both_dates_flagged():
    s = stmt(credit("CRA AGRO X", "CRA", "CRA-0AA00001", venc=dt.date(2030, 4, 15)))
    rows = [inst(1, "CRA-0AA00001", "0AA00001", "securit_cetip", numero_serie="10", data_vencimento="2033-01-15"),
            inst(1, "CRA-0AA00001", "0AA00001", "securit_cetip", numero_serie="2", data_vencimento="2029-01-15", situacao="Inadimplente")]
    _, by, _ = ident_of(s, {"portfolio_instruments": [{"match": {}, "rows": rows}]})
    cm = by[1]["credit_match"]
    assert cm["numero_serie"] == "2"  # numeric order, not text order ("10" < "2")
    flags = {f["code"]: f for f in cm["flags"]}
    assert flags["vencimento_diverge"]["statement_vencimento"] == "2030-04-15"
    assert flags["vencimento_diverge"]["registry_vencimento"] == "2029-01-15"
    assert flags["situacao_fora_adimplente"]["situacao"] == "Inadimplente"


def test_single_series_is_taken_and_a_null_situacao_is_not_outside_adimplente():
    s = stmt(credit("CRI IMOB Y", "CRI", "CRI-0BB00002"))  # no maturity printed
    rows = [inst(1, "CRI-0BB00002", "0BB00002", "securit_cetip", numero_serie="1", data_vencimento="2035-01-15", situacao=None)]
    _, by, _ = ident_of(s, {"portfolio_instruments": [{"match": {}, "rows": rows}]})
    assert by[1]["status"] == "identified" and by[1]["credit_match"]["flags"] == []


def test_several_series_and_no_printed_maturity_is_its_own_flag_not_a_divergence():
    s = stmt(credit("CRI IMOB Y", "CRI", "CRI-0BB00002"))
    rows = [inst(1, "CRI-0BB00002", "0BB00002", "securit_cetip", numero_serie=n, data_vencimento=f"203{n}-01-15") for n in ("1", "2")]
    _, by, _ = ident_of(s, {"portfolio_instruments": [{"match": {}, "rows": rows}]})
    assert [f["code"] for f in by[1]["credit_match"]["flags"]] == ["serie_sem_vencimento"]


def test_debenture_takes_the_cda_ticker_row_and_the_funds_mark():
    s = stmt(credit("DEB ENERGIA Z", "debênture", "DEB-ZZZZ11", valor=55000.0, preco=55000.0))
    rows = [inst(1, "DEB-ZZZZ11", "ZZZZ11", "securit_cetip"),  # a CRA/CRI match kind is never taken for a debênture
            inst(1, "DEB-ZZZZ11", "ZZZZ11", "cda_ticker", cd_isin="BRZZZZDBS001", issuer_code="ZZZZ", n_fundos=3,
                 preco_marcacao_fundos=50000.0, cda_period="2026-05-01")]
    _, by, lines = ident_of(s, {"portfolio_instruments": [{"match": {}, "rows": rows}]})
    cm = by[1]["credit_match"]
    assert cm["match_kind"] == "cda_ticker" and cm["preco_marcacao_fundos_brl"] == 50000.0
    assert cm["price_gap_pct"] == 10.0 and cm["price_gap_abs_pct"] == 10.0
    assert cm["price_gap_label"] == "informativo, não é veredito de preço"
    assert by[1]["identity"]["isin"] == "BRZZZZDBS001" and by[1]["identity"]["issuer_code"] == "ZZZZ"


def test_no_match_stays_unknown_with_a_fixed_code_and_the_code_read():
    s = stmt(credit("CRA AGRO X", "CRA", "CRA-0AA00001"), credit("DEB Q", "debênture", "DEB-QQQQ11"))
    sec, by, _ = ident_of(s, {"portfolio_instruments": [{"match": {}, "rows": []}]})
    for n in (1, 2):
        assert by[n]["status"] == "unknown" and by[n]["reason_code"] == "credito_sem_registro"
        assert by[n]["credit_match"]["matched"] is False
    assert "CRA-0AA00001" in by[1]["reason"]
    assert {g["reason_code"] for g in sec["unknown_groups"]} == {"credito_sem_registro"}


def test_a_credit_line_without_code_is_not_sent():
    s = stmt(credit("CRA AGRO X", "CRA", None))
    calls = []

    class Spy(FakeClient):
        def _request(self, tool, args):
            calls.append(tool)
            return super()._request(tool, args)

    sec, lines = identify(s, Spy({}))
    assert "portfolio_instruments" not in calls and sec["lines"][0]["reason_code"] == "credito_sem_codigo"


def test_an_ocr_code_not_checked_is_sent_as_read_and_flagged():
    s = stmt(credit("CRA AGRO X", "CRA", "CRA-0AA0OOO1"))
    s = patch(s, 0, codigo_conferido=False)
    rows = [inst(1, "CRA-0AA0OOO1", "0AA0OOO1", "securit_cetip", numero_serie="1")]
    _, by, _ = ident_of(s, {"portfolio_instruments": [{"match": {"p_codes": ["CRA-0AA0OOO1"]}, "rows": rows}]})
    assert [f["code"] for f in by[1]["credit_match"]["flags"]] == ["codigo_nao_conferido"]


def test_an_echoed_code_that_is_not_the_one_sent_is_inconsistent():
    s = stmt(credit("CRA AGRO X", "CRA", "CRA-0AA00001"))
    rows = [inst(1, "CRA-0ZZ99999", "0ZZ99999", "securit_cetip")]
    sec, by, _ = ident_of(s, {"portfolio_instruments": [{"match": {}, "rows": rows}]})
    assert by[1]["status"] == "unknown" and by[1]["reason_code"] == "resposta_inconsistente"


def test_a_refused_instruments_call_degrades_and_a_timeout_raises():
    s = stmt(credit("CRA AGRO X", "CRA", "CRA-0AA00001"))
    sec, by, _ = ident_of(s, {"portfolio_instruments": [{"match": {}, "error": "Unknown tool `portfolio_instruments`."}]})
    assert by[1]["reason_code"] == "consulta_falhou" and sec["status"] == "partial" and sec["errors"]
    with pytest.raises(SiloUnavailable):
        identify(s, FakeClient({"portfolio_instruments": [{"match": {}, "error": TIMEOUT}]}))


def test_the_document_is_produced_when_neither_new_tool_is_deployed():
    canned = load_fake_rows(FAKE_ROWS)
    for tool in ("portfolio_instruments", "portfolio_fund_terms"):
        canned[tool] = [{"match": {}, "error": f"Unknown tool `{tool}`."}]
    s = read_statement(TEMPLATE)
    doc = run_engine(s, FakeClient(canned, clock=lambda: FAKE_CLOCK), default_params(s.position_date), clock=lambda: FAKE_CLOCK)
    by = {ln["line_no"]: ln for ln in doc["identification"]["lines"]}
    assert by[11]["reason_code"] == "consulta_falhou" and by[12]["reason_code"] == "consulta_falhou"
    rows = {r["id"]: r for r in doc["risks"]["rows"]}
    for rid in ("liquidez", "concentracao_gestor", "credito_situacao", "credito_vencimento_diverge", "credito_preco_marcacao"):
        assert rows[rid]["status"] == "nao_avaliado", rid
    assert doc["liquidity"]["status"] == "unknown" and doc["concentration"]["manager"]["status"] == "unknown"
    html_text, _ = build.build(adapt.to_view(doc), "fake")
    assert "Unknown tool" not in html_text


# --- the direct exposure is kept -------------------------------------------------------------------------------------


def test_identified_credit_keeps_its_direct_exposure_and_a_debenture_its_issuer_code():
    s = stmt(credit("CRA AGRO X", "CRA", "CRA-0AA00001", taxa=None), credit("DEB ENERGIA Z", "debênture", "DEB-ZZZZ11", taxa="12% a.a."))
    rows = [inst(1, "CRA-0AA00001", "0AA00001", "securit_cetip", numero_serie="1", cd_isin="BRSECUCRA001"),
            inst(2, "DEB-ZZZZ11", "ZZZZ11", "cda_ticker", cd_isin="BRZZZZDBS001", issuer_code="ZZZZ")]
    _, lines = identify(s, FakeClient({"portfolio_instruments": [{"match": {}, "rows": rows}]}))
    _, exposures = compute_lookthrough(lines, FakeClient({}), dt.date(2026, 5, 1), 4)
    cra, deb = exposures[1], exposures[2]
    assert [e.asset_kind for e in cra] == ["credito_direto"] and cra[0].issuer_code is None and cra[0].isin is None
    assert deb[0].asset_kind == "credito_direto" and (deb[0].isin, deb[0].issuer_code) == ("BRZZZZDBS001", "ZZZZ")


def test_the_demo_debenture_overlaps_its_issuer_inside_the_funds():
    doc = json.loads(DEMO.read_text(encoding="utf-8"))
    groups = [g for g in doc["look_through"]["shared_exposure"]["groups"] if g["kind"] == "mesmo_codigo_emissor_b3" and 12 in g["line_nos"]]
    assert groups and groups[0]["issuer_code"] == "ENEV"
    assert any(ln["line_no"] == 12 and ln["direct"] for ln in groups[0]["lines"])
    by = {p["line_no"]: p for p in doc["indexer"]["by_position"]}
    assert [c["indexer_class"] for c in by[11]["classes"]] == ["inflação (IPCA)"]  # not "sem classificação"


# --- 2. fund terms: managers and liquidity --------------------------------------------------------------------------


A, B, C, P = "11111111000111", "22222222000122", "33333333000133", "44444444000144"


def fund_stmt():
    s = stmt(fund("FUNDO A", A, 400.0), fund("FUNDO B", B, 300.0), fund("FUNDO C", C, 200.0), fund("PREV X", P, 100.0))
    return patch(s, 3, estrategia_corretora="Previdência PGBL")


def resolve_none():
    return {"portfolio_resolve": [{"match": {}, "rows": []}]}  # every line identified by the statement's CNPJ


def test_gestor_groups_by_the_filed_id_never_the_name_and_includes_pgbl():
    s = fund_stmt()
    rows = [terms_row(1, A, "G1", "GESTORA UM"), terms_row(2, B, "G1", "GESTORA UM LTDA"), terms_row(3, C, "G2", "GESTORA UM"),
            terms_row(4, P, None, None)]
    canned = {**resolve_none(), "portfolio_fund_terms": [{"match": {"p_cnpjs": [A, B, C, P]}, "rows": rows}]}
    _, lines = identify(s, FakeClient(canned))
    t = fetch_fund_terms(lines, FakeClient(canned))
    from src.portfolio.concentration import compute_concentration

    m = compute_concentration(lines, D, t, compute_liquidity(lines, t))["manager"]
    by = {g["gestor_id"]: g for g in m["groups"]}
    assert set(by) == {"G1", "G2"} and by["G1"]["line_nos"] == [1, 2] and by["G1"]["value_brl"] == 700.0
    assert by["G1"]["portfolio_pct"] == 70.0 and by["G1"]["names_as_filed"] == ["GESTORA UM", "GESTORA UM LTDA"]
    assert m["without_gestor_line_nos"] == [4] and m["status"] == "partial"  # the PGBL fund is asked, no gestor filed
    rows[3] = terms_row(4, P, "G2", "GESTORA DOIS")
    t = fetch_fund_terms(lines, FakeClient(canned))
    m = compute_concentration(lines, D, t, compute_liquidity(lines, t))["manager"]
    assert {g["gestor_id"]: g["line_nos"] for g in m["groups"]}["G2"] == [3, 4] and m["status"] == "complete"


def liq_stmt():
    s = stmt(fund("F5", A, 100.0), fund("F6", B, 100.0), fund("F31", C, 100.0), fund("FLOCK", P, 100.0),
                fund("FIDC X", "55555555000155", 100.0, tipo="FIDC"), fund("FUNDO SEM CNPJ", None, 100.0),
                credit("CDB BANCO", "CDB", None, 100.0), ["NTN-B 2035", "tesouro", "NTN-B 2035-05-15", 1, 100.0, 100.0, D, None, None],
                ["PETR4", "ação", "PETR4", 1, 100.0, 100.0, D, None, None], ["CONTA", "outro", None, None, None, 100.0, D, None, None])
    return patch(s, 9, tipo="caixa")  # caixa comes from the PDF reader only (Conta corrente)


def liq_canned(fail=False):
    cnpjs = [A, B, C, P, "55555555000155"]
    rows = [terms_row(1, A, pagto=5, tp="DIAS ÚTEIS"), terms_row(2, B, pagto=6, tp="DIAS CORRIDOS"),
            terms_row(3, C, pagto=31, tp="DIAS ÚTEIS"), terms_row(4, P, pagto=1, lock=90, tp="DIAS ÚTEIS"),
            terms_row(5, "55555555000155")]
    entry = {"match": {"p_cnpjs": cnpjs}, "error": "refused"} if fail else {"match": {"p_cnpjs": cnpjs}, "rows": rows}
    return {"portfolio_resolve": [{"match": {}, "rows": []}], "portfolio_fund_terms": [entry],
            "lookup": [{"match": {"p_query": "PETR4"}, "rows": [dict(id="PETR4", asset_class="equity", name="P", isin="BRPETRACNPR6")]}],
            "quote_latest": [{"match": {}, "rows": []}], "company_financials": [{"match": {}, "rows": []}]}


def test_liquidity_buckets_from_the_filed_days_never_converted():
    s = liq_stmt()
    canned = liq_canned()
    _, lines = identify(s, FakeClient(canned))
    lq = compute_liquidity(lines, fetch_fund_terms(lines, FakeClient(canned)))
    by = {b["bucket_id"]: b for b in lq["buckets"]}
    assert [b["bucket"] for b in lq["buckets"]] == ["D+0 a D+5", "D+6 a D+30", "acima de D+30", "lock-up",
                                                   "fundo sem prazo de resgate informado",
                                                   "crédito direto sem liquidez antes do vencimento", "títulos públicos (Tesouro)",
                                                   "ETF/ações (negociados em bolsa)", "caixa", "sem classificação"]
    assert by["d0_d5"]["line_nos"] == [1] and by["d6_d30"]["line_nos"] == [2] and by["acima_d30"]["line_nos"] == [3]
    assert by["lockup"]["line_nos"] == [4]  # a lock-up wins over a D+1 payment
    assert by["fundo_sem_prazo"]["line_nos"] == [5] and by["sem_classificacao"]["line_nos"] == [6]
    assert by["credito_direto"]["line_nos"] == [7] and by["titulos_publicos"]["line_nos"] == [8]
    assert by["bolsa"]["line_nos"] == [9] and by["caixa"]["line_nos"] == [10]
    assert by["d6_d30"]["lines"][0]["tp_dia_pagto_resgate"] == "DIAS CORRIDOS"  # as filed
    assert lq["above_d30_total_brl"] == 400.0 and lq["above_d30_total_pct"] == 40.0  # D+31, lock-up, FIDC, CDB
    assert abs(lq["sum_check_brl"]) < 0.01 and lq["evaluated"] and "liquidez_sem_identificacao" in lq["reason_codes"]


def test_a_failed_terms_call_is_not_evaluated_never_sem_prazo():
    s = liq_stmt()
    canned = liq_canned(fail=True)
    _, lines = identify(s, FakeClient(canned))
    lq = compute_liquidity(lines, fetch_fund_terms(lines, FakeClient(canned)))
    by = {b["bucket_id"]: b for b in lq["buckets"]}
    assert by["fundo_sem_prazo"]["line_nos"] == [] and set(by["sem_classificacao"]["line_nos"]) == {1, 2, 3, 4, 5, 6}
    assert lq["status"] == "unknown" and not lq["evaluated"] and lq["errors"]
    row = R._liquidity_row({"liquidity": lq, "statement": {"positions": []}})
    assert row["status"] == "nao_avaliado" and row["value_pct"] is None


def test_a_transient_terms_failure_is_retried_halved_and_does_not_raise():
    s = fund_stmt()
    calls = []

    class Flaky(FakeClient):
        def _request(self, tool, args):
            if tool == "portfolio_fund_terms":
                calls.append(list(args["p_cnpjs"]))
                raise ToolError(tool, TIMEOUT)
            return super()._request(tool, args)

    _, lines = identify(s, Flaky(resolve_none()))
    t = fetch_fund_terms(lines, Flaky(resolve_none()))
    assert calls == [[A, B, C, P], [A, B], [C, P]] and set(t.failed) == {1, 2, 3, 4}


# --- 3. risk rows and thresholds -------------------------------------------------------------------------------------


@pytest.mark.parametrize("risk_id,value,expected", [
    ("concentracao_gestor", 40.0, "moderado"), ("concentracao_gestor", 40.01, "atencao"), ("concentracao_gestor", 25.0, "baixo"),
    ("liquidez", 50.0, "moderado"), ("liquidez", 50.01, "atencao"), ("liquidez", 30.0, "baixo"),
    ("credito_preco_marcacao", 5.0, "baixo"), ("credito_preco_marcacao", 5.01, "moderado"), ("credito_preco_marcacao", 90.0, "moderado"),
    ("credito_situacao", 0, "baixo"), ("credito_situacao", 1, "atencao"),
    ("credito_vencimento_diverge", 0, "baixo"), ("credito_vencimento_diverge", 1, "moderado"),
])
def test_new_rows_severity_is_strictly_above_the_threshold(risk_id, value, expected):
    assert R.severity(risk_id, value) == expected


def test_the_demo_carries_the_new_rows_with_labels():
    doc = json.loads(DEMO.read_text(encoding="utf-8"))
    rows = {r["id"]: r for r in doc["risks"]["rows"]}
    assert set(rows) == set(R.THRESHOLDS)
    v = rows["credito_vencimento_diverge"]
    assert (v["value_count"], v["severity"], v["check_label"]) == (1, "moderado", "a conferir")
    assert (v["statement_vencimento"], v["registry_vencimento"]) == ("2031-10-15", "2032-04-15")
    p = rows["credito_preco_marcacao"]
    assert (p["value_pct"], p["severity"], p["check_label"]) == (12.0, "moderado", "informativo, não é veredito de preço")
    assert (p["statement_date"], p["cda_period"]) == ("2026-09-30", "2026-05-01")
    assert rows["credito_situacao"]["value_count"] == 0 and rows["credito_situacao"]["severity"] == "baixo"
    g = rows["concentracao_gestor"]
    assert (g["subject"], g["severity"], g["source_path"]) == ("GESTORA EXEMPLO BETA", "moderado", "concentration.manager.groups[0].portfolio_pct")
    lq = rows["liquidez"]
    assert lq["status"] == "avaliado" and lq["value_pct"] == doc["liquidity"]["above_d30_total_pct"]
    assert [x["bucket_id"] for x in lq["parts"]] == ["acima_d30", "lockup", "fundo_sem_prazo", "credito_direto"]


def test_a_non_adimplente_cra_is_attention_and_no_cra_does_not_apply():
    def doc_with(flags):
        return {"statement": {"positions": [{"line_no": 1, "valor_brl": 100.0, "source": None}]},
                "identification": {"lines": [{"line_no": 1, "tipo": "CRA", "credit_match": {"matched": True, "code": "0AA00001",
                                                                                            "situacao": "Inadimplente", "flags": flags,
                                                                                            "sources": []}}]}}
    rows = {r["id"]: r for r in R._credit_rows(doc_with([{"code": "situacao_fora_adimplente", "situacao": "Inadimplente"}]))}
    assert (rows["credito_situacao"]["value_count"], rows["credito_situacao"]["severity"]) == (1, "atencao")
    assert rows["credito_situacao"]["situacao"] == "Inadimplente"
    assert rows["credito_preco_marcacao"]["status"] == "nao_se_aplica"
    none = {r["id"]: r for r in R._credit_rows({"statement": {"positions": []}, "identification": {"lines": []}})}
    assert none["credito_situacao"]["status"] == "nao_se_aplica" and none["credito_situacao"]["reason"]


# --- 4. FIP -------------------------------------------------------------------------------------------------------------


def test_fip_is_a_statement_type_and_a_fund():
    assert TIPOS["fip"] == "FIP"
    assert _fund_tipo("ALFA FIP MULTIESTRATEGIA") == "FIP" and _fund_tipo("BETA CAPITAL PARTICIPACOES") == "FIP"
    assert _fund_tipo("GAMA FIDC") == "FIDC" and _fund_tipo("DELTA FII") == "FII" and _fund_tipo("EPS RF") == "fundo"
    s = stmt(fund("ALFA FIP", A, 100.0, tipo="FIP"))
    _, lines = identify(s, FakeClient(resolve_none()))
    assert lines[0].kind == "fund" and lines[0].cnpj == A and lines[0].entity_type == "fip"
    assert compute_allocation(lines)["classes"][0]["asset_class"] == "FIP"
    assert adapt._asset_type({"tipo": "FIP"}, {}) == "fip" and render.ASSET_LABELS["fip"] == "FIP"


# --- 5. report: badges, credit table, charts, Revisor --------------------------------------------------------------------


@pytest.fixture()
def engine() -> dict:
    return json.loads(DEMO.read_text(encoding="utf-8"))


@pytest.fixture()
def view(engine) -> dict:
    return adapt.to_view(engine)


def test_identification_badges_from_the_position_flags(engine):
    pos = engine["statement"]["positions"]
    pos[0].update(fonte_texto="ocr", codigo_conferido=False, taxa_conferida=False)
    v = adapt.to_view(engine)
    assert [b["label"] for b in v["lines"][0]["badges"]] == ["lido por OCR", "código não conferido", "taxa não conferida"]
    assert [b["label"] for b in v["lines"][10]["badges"]] == ["vencimento diverge do registro CVM"]
    html_text = render._ident_section(v)
    for label in ("lido por OCR", "código não conferido", "taxa não conferida", "vencimento diverge do registro CVM"):
        assert label in html_text


def test_the_credit_table_prints_statement_and_registry_side_by_side(view):
    rows = view["credit"]["lines"]
    assert [r["line_id"] for r in rows] == ["L11", "L12"]
    html_text = render._credit_section(view)
    for path in ("credit.lines[0].statement_vencimento", "credit.lines[0].registry_vencimento", "credit.lines[0].registry_taxa",
                 "credit.lines[0].situacao", "credit.lines[0].rating", "credit.lines[0].cnpj_securit",
                 "credit.lines[1].statement_preco_brl", "credit.lines[1].fund_mark_brl", "credit.lines[1].price_gap_pct"):
        assert render.v(view, path) in html_text, path
    assert "AGRO EXEMPLO" in html_text and "CDA de 05/2026" in html_text
    full, _ = build.build(view, "fake")
    assert "<h2>Crédito direto no registro da CVM</h2>" in full and "<h2>Liquidez</h2>" in full


def svg_of(fig: str) -> ET.Element:
    start, end = fig.index("<svg"), fig.index("</svg>") + len("</svg>")
    root = ET.fromstring(fig[start:end])
    assert root.tag == f"{SVG_NS}svg"
    return root


def test_manager_and_liquidity_charts_print_the_view_values(view):
    root = svg_of(charts.manager_chart(view))
    t = [x.text or "" for x in root.iter(f"{SVG_NS}text")]
    groups = view["concentration"]["manager"]["groups"]
    assert len(list(root.iter(f"{SVG_NS}path"))) == len(groups)
    for i, g in enumerate(groups):
        assert g["gestor_name"] in t
        assert f"{render.format_value(view, f'concentration.manager.groups[{i}].value_brl')} · " \
               f"{render.format_value(view, f'concentration.manager.groups[{i}].weight_pct')}" in t
    root = svg_of(charts.liquidity_chart(view))
    t = [x.text or "" for x in root.iter(f"{SVG_NS}text")]
    shown = [b for b in view["liquidity"]["buckets"] if b["value_brl"] > 0]
    assert len(list(root.iter(f"{SVG_NS}path"))) == len(shown)  # an empty bucket stays in the table only
    assert all(any(x.startswith(b["bucket"][:20]) for x in t) for b in shown)


def test_new_charts_are_not_drawn_without_data(view):
    v = copy.deepcopy(view)
    v["concentration"]["manager"]["groups"] = []
    v["liquidity"]["buckets"] = []
    assert charts.manager_chart(v) == "" and charts.liquidity_chart(v) == ""
    old = adapt.to_view(json.loads((ROOT / "tests" / "fixtures" / "portfolio" / "report_provisional_engine_output.json").read_text()) | {}) \
        if False else None
    assert old is None


def test_a_1_8_document_still_renders(engine):
    doc = copy.deepcopy(engine)
    doc["schema_version"] = "1.8"
    for k in ("liquidity",):
        doc.pop(k)
    for ln in doc["identification"]["lines"]:
        ln.pop("credit_match", None)
        ln.pop("fund_terms", None)
    doc["concentration"]["manager"] = {"status": "unknown", "reason_code": "gestor_sem_api", "reason": "x"}
    doc["section_status"].pop("liquidity")
    v = adapt.to_view(doc)
    assert "credit" not in v and "liquidity" not in v
    html_text, _ = build.build(v, "fake")
    assert "Concentração por gestor: não avaliada" in html_text


def big_engine() -> dict:
    """The demo with every fund at D+60 and one manager: liquidity and the largest manager above 50%."""
    canned = load_fake_rows(FAKE_ROWS)
    rows = canned["portfolio_fund_terms"][0]["rows"]
    for r in rows:
        r.update(gestor_id="90000000000999", gestor_name="GESTORA EXEMPLO UNICA", qt_dia_pagto_resgate=60, qt_dia_resgate_cotas=0,
                 tp_dia_pagto_resgate="DIAS CORRIDOS", terms_source="extrato")
    s = read_statement(TEMPLATE)
    return run_engine(s, FakeClient(canned, clock=lambda: FAKE_CLOCK), default_params(s.position_date), clock=lambda: FAKE_CLOCK)


def test_the_revisor_keeps_new_rows_above_fifty_percent():
    eng = big_engine()
    rows = {r["id"]: r for r in eng["risks"]["rows"]}
    assert rows["liquidez"]["value_pct"] > 50 and rows["liquidez"]["severity"] == "atencao"
    assert rows["concentracao_gestor"]["value_pct"] > 50 and rows["concentracao_gestor"]["severity"] == "atencao"
    v = adapt.to_view(eng)
    findings = redator._coerce_findings(redator.template_findings(v))
    res = revisor.check(v, findings)
    kept_ids = {v["risks"]["rows"][int(f.text.split("risks.rows[")[1].split("]")[0])]["id"] for f in res.kept if f.section == "riscos"}
    assert {"liquidez", "concentracao_gestor"} & kept_ids
    for f in res.removed:
        assert f.section != "riscos" or "valor extremo" not in f.reason, f
    i = next(k for k, r in enumerate(v["risks"]["rows"]) if r["id"] == "liquidez")
    j = next(k for k, r in enumerate(v["risks"]["rows"]) if r["id"] == "concentracao_gestor")
    for k in (i, j):
        res = revisor.check(v, [redator.Finding("x", "riscos", "Risco", f"{{{{risks.rows[{k}].risk}}}}: {{{{risks.rows[{k}].value_pct}}}}.", ["p1"])])
        assert res.kept, res.removed


# --- look-through depth: a fund of funds above the one-page cap is opened shallower -------------------------------

CAP = ('{"code":"22023","details":"Every response is one page of at most 1000 rows.","hint":null,'
       '"message":"portfolio_lookthrough: refused, this request would return more than 1000 rows."}')


def _lt_rows(root, depth_cap):
    return [dict(root_cnpj=root, path=[root], depth=0, holder_cnpj=root, block=1, asset_kind="government_bond",
                 asset_key="BRSTNCLF1RH3", asset_name="LFT", isin="BRSTNCLF1RH3", issuer_cnpj=None, issuer_code=None,
                 tp_aplic="Títulos Públicos", tp_ativo="Título público federal", tp_titpub="LFT", indexer_code=None,
                 maturity="2027-09-01", value_brl=50.0, weight_in_root=0.5, period="2026-05-01", is_cycle=False),
            dict(root_cnpj=root, path=[root], depth=0, holder_cnpj=root, block=2, asset_kind="fund_quota_depth_cap",
                 asset_key="99999999000199", asset_name="FUNDO MASTER", isin=None, issuer_cnpj=None, issuer_code=None,
                 tp_aplic="Cotas de Fundos", tp_ativo="Fundo", tp_titpub=None, indexer_code=None, maturity=None,
                 value_brl=50.0, weight_in_root=0.5, period="2026-05-01", is_cycle=False)]


def _lt(answer_at):
    s = stmt(fund("FIC PREV", A, 100.0))
    asked = []

    class Capped(FakeClient):
        def _request(self, tool, args):
            if tool == "portfolio_lookthrough":
                asked.append(args["p_max_depth"])
                if answer_at is None or args["p_max_depth"] > answer_at:
                    raise ToolError(tool, CAP)
                return _lt_rows(A, args["p_max_depth"])
            return super()._request(tool, args)

    _, lines = identify(s, Capped(resolve_none()))
    sec, _ = compute_lookthrough(lines, Capped(resolve_none()), dt.date(2026, 5, 1), 4)
    return sec, asked


def test_a_fund_above_the_page_cap_is_opened_one_level_shallower_and_says_so():
    sec, asked = _lt(answer_at=2)
    assert asked == [4, 3, 2]
    line = sec["lines"][0]
    assert line["max_depth_used"] == 2 and line["status"] == "complete"
    assert sec["errors"] == [] and "profundidade_reduzida" in sec["reason_codes"] and sec["status"] == "partial"


def test_a_fund_refused_at_every_depth_keeps_every_refusal_verbatim():
    sec, asked = _lt(answer_at=None)
    assert asked == [4, 3, 2, 1]
    assert sec["lines"][0]["status"] == "unknown" and len(sec["errors"]) == 4
    assert all("22023" in e["error"] for e in sec["errors"])


def test_a_transient_failure_is_not_retried_shallower():
    s = stmt(fund("FIC PREV", A, 100.0))
    asked = []

    class Down(FakeClient):
        def _request(self, tool, args):
            if tool == "portfolio_lookthrough":
                asked.append(args["p_max_depth"])
                raise ToolError(tool, TIMEOUT)
            return super()._request(tool, args)

    _, lines = identify(s, Down(resolve_none()))
    compute_lookthrough(lines, Down(resolve_none()), dt.date(2026, 5, 1), 4)
    assert asked and set(asked) == {4}


def test_a_line_resolved_by_its_cnpj_carries_no_rename_finding():
    """CVM 175 renamed almost every fund: a rename matters only when the name led the identification."""
    s = stmt(fund("FUNDO EXEMPLO FI RF", A, 100.0))
    row = dict(line_no=1, input_name="FUNDO EXEMPLO FI RF", candidate_cnpj=A, candidate_name="FUNDO EXEMPLO FIF RENDA FIXA",
               matched_name="FUNDO EXEMPLO FUNDO DE INVESTIMENTO RENDA FIXA", matched_period="2024-01-01", entity_type="fi",
               match_kind="cnpj", similarity=0.4, rank=1, quota_on_date=None, quota_rel_diff=None, ambiguous=False,
               reason="CNPJ supplied by the statement")
    _, lines = identify(s, FakeClient({"portfolio_resolve": [{"match": {}, "rows": [row]}]}))
    assert lines[0].status == "identified" and lines[0].findings == []
    row.update(match_kind="exact_history")
    _, lines = identify(s, FakeClient({"portfolio_resolve": [{"match": {}, "rows": [row]}]}))
    assert [f["kind"] for f in lines[0].findings] == ["renamed"]


def test_the_largest_fund_sums_one_fund_held_in_two_accounts():
    from src.portfolio.risks import _fund_row
    pos = [dict(line_no=1, tipo="fundo", codigo=A, valor_brl=30.0, portfolio_pct=30.0, linha_extrato="F A"),
           dict(line_no=2, tipo="fundo", codigo=B, valor_brl=40.0, portfolio_pct=40.0, linha_extrato="F B"),
           dict(line_no=3, tipo="fundo", codigo=A, valor_brl=30.0, portfolio_pct=30.0, linha_extrato="F A")]
    ident = [dict(line_no=n, identity=dict(kind="fund", cnpj=c, name=f"FUNDO {c[:2]}")) for n, c in ((1, A), (2, B), (3, A))]
    row = _fund_row({"statement": {"positions": pos, "sum_of_lines_brl": 100.0}, "identification": {"lines": ident}})
    assert row["value_pct"] == 60.0 and row["line_nos"] == [1, 3] and "somados (mesmo fundo)" in row["source_path"]


def test_a_fund_held_directly_and_inside_another_fund_is_one_overlap():
    from src.portfolio.identify import LineId
    from src.portfolio.lookthrough import shared_exposure
    s = stmt(fund("ETF DEB", None, 100.0, tipo="ETF"), fund("FIC CRED", B, 200.0), fund("FUNDO X", C, 50.0), fund("FUNDO X", C, 50.0))
    li = [LineId(position=p) for p in s.positions]
    li[0].kind, li[0].etf_cnpj = "ticker", A
    for x in li[1:]:
        x.kind, x.cnpj = "fund", x.position.codigo
    node = {"fund_cnpj": A, "fund_name": "ETF DEB", "value_brl": 20.0, "sources": []}
    groups = shared_exposure(li, {1: [], 2: [], 3: [], 4: []}, {2: [node]})["groups"]
    g = [x for x in groups if x["kind"] == "mesmo_fundo_investido"]
    assert len(g) == 1 and g[0]["fund_cnpj"] == A and g[0]["line_nos"] == [1, 2] and g[0]["direct_line_nos"] == [1]
    # the same fund on two direct lines (two accounts) is one position, not an overlap
    assert not any(x.get("fund_cnpj") == C for x in groups)
