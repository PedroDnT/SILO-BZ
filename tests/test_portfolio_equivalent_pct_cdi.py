"""Engine 1.12: "% do CDI" by the filed benchmark (#606 Q36) and the market equivalent (#609), offline.

Synthetic data only: canned rows for FakeClient and the demo engine fixture; no real statement or portfolio is read.
The SQL side (api.portfolio_equivalents and the benchmark columns of api.portfolio_fees) is executed in
tests/sql/portfolio_behaviour.sql.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import re
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from src.portfolio import benchmark
from src.portfolio.client import FakeClient
from src.portfolio.common import REASON_TEXT
from src.portfolio.fees import _fee_record
from src.portfolio.common import Call
from src.portfolio.market_equivalent import EQ_LABEL, compute_equivalents
from src.portfolio.report import adapt, build, revisor, values
from src.portfolio.report.redator import Finding
from tests.test_portfolio_returns import (
    D,
    MONTHS,
    cdi_rows,
    fund_line,
    lines_for,
    month_end,
    nav_rows,
    path,
    run,
)

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "tests" / "fixtures" / "portfolio" / "demo_engine_output.json"
FUND = "08935128000159"
SMALL = "AÇÕES - ATIVO - SMALL CAPS"
RF = "RENDA FIXA SIMPLES"
RF_INDICES = ["TEVA LFT Curto Prazo", "TEVA Tesouro Selic", "Tesouro Selic (LFT)", "Tesouro Selic B3"]


# --- the rule file -----------------------------------------------------------------------------------------------------


def test_the_accepted_spellings_are_exactly_the_reviewed_list():
    rules = benchmark.load_rules()
    assert rules.accepted == {"CDI", "DI1 - DI DE UM DIA", "CDI252", "CDI 100%", "DI-CETIP", "CDI DIARIO", "(CDI252+0%)"}
    assert {"SELIC", "105%CDI252", "CDI + 1%", "OUTROS", "CDI_I"} <= rules.rejected
    doc = yaml.safe_load(benchmark.RULES.read_text(encoding="utf-8"))
    assert doc["measured_on"] == "2026-10-05" and doc["version"] == rules.version


def test_normalize_only_trims_collapses_and_upper_cases():
    assert benchmark.normalize("  di1 -  DI de um dia ") == "DI1 - DI DE UM DIA"
    assert benchmark.normalize("Índice  Brasil") == "ÍNDICE BRASIL"  # accents stay
    assert benchmark.normalize("   ") is None and benchmark.normalize(None) is None


@pytest.mark.parametrize("extrato,lamina", [
    ("CDI", None), (None, "cdi"), (None, "DI1 - DI de um dia"), (None, "CDI252"), (None, "CDI 100%"),
    (None, "DI-CETIP"), (None, "CDI DIARIO"), (None, "(CDI252+0%)"), ("CDI", "CDI252"),
])
def test_an_accepted_spelling_is_cdi_like(extrato, lamina):
    v = benchmark.classify(extrato, lamina, 1 if lamina else None)
    assert v["cdi_like"] is True and v["reason_code"] is None


@pytest.mark.parametrize("spelling", ["SELIC", "105%CDI252", "CDI + 1%", "IBOVESPA", "OUTROS", "CDI_I", "CDI ANO",
                                      "Ibovespa", "something never seen"])
def test_a_rejected_or_unknown_spelling_is_not_cdi_like(spelling):
    v = benchmark.classify(spelling, None, None)
    assert v["cdi_like"] is False and v["reason_code"] == "referencia_nao_cdi"


def test_no_benchmark_and_divergent_benchmarks_are_not_cdi_like():
    assert benchmark.classify(None, None, 0)["reason_code"] == "referencia_nao_informada"
    assert benchmark.classify("  ", "", None)["reason_code"] == "referencia_nao_informada"
    assert benchmark.classify("CDI", "IBOVESPA", 1)["reason_code"] == "referencia_diverge"
    assert benchmark.classify("OUTROS", "CDI", 1)["reason_code"] == "referencia_diverge"
    assert benchmark.classify(None, None, 2)["reason_code"] == "referencia_diverge"  # the lâmina's classes differ
    # some classes filed CDI and some nothing: benchmark_lamina is NULL with one distinct value, not "não informado"
    assert benchmark.classify(None, None, 1)["reason_code"] == "referencia_diverge"
    assert benchmark.classify("CDI", None, 1)["reason_code"] == "referencia_diverge"
    for code in ("referencia_nao_informada", "referencia_nao_cdi", "referencia_diverge"):
        assert code in REASON_TEXT


@pytest.mark.parametrize("doc,msg", [
    ({"version": 1, "accepted": [{"spelling": "cdi"}], "rejected": [{"spelling": "X"}]}, "normalized"),
    ({"version": 1, "accepted": [{"spelling": "CDI"}], "rejected": [{"spelling": "CDI"}]}, "both"),
    ({"accepted": [{"spelling": "CDI"}], "rejected": [{"spelling": "X"}]}, "version"),
    ({"version": 1, "accepted": [], "rejected": [{"spelling": "X"}]}, "non-empty"),
])
def test_a_malformed_rule_file_is_refused(doc, msg):
    with pytest.raises(benchmark.BenchmarkRuleError, match=msg):
        benchmark.parse_rules(doc)


# --- "% do CDI" in the return block ------------------------------------------------------------------------------------


def bench_fees(extrato=None, lamina=None, lamina_n=None):
    src = {"tool": "portfolio_fees", "call_id": 99, "args": {}, "data_date": "2026-08-01"}
    return {"lines": [{"line_no": 1, "headline": {"kind": "fixa", "rate_pct_year": 0.5, "origin": "extrato",
                                                  "as_of": "2026-07-31", "sources": [src]},
                       "disclosed": {"perf_as_filed": None, "terms_as_filed": None}, "fee_status": "divulgada",
                       "benchmark_as_filed": {"extrato": extrato, "lamina": lamina, "lamina_n": lamina_n,
                                              "extrato_as_of": "2026-06-30", "lamina_as_of": None, "sources": [src]}}]}


def fund_run(fees, rate=0.05):
    values = path(1.0, [1.0] * 12)
    canned = {"fund_nav": [{"match": {}, "rows": nav_rows(FUND, values)}],
              "macro_series": [{"match": {"p_series": "CDI"}, "rows": cdi_rows(rate)}]}
    from src.portfolio.returns import compute_returns
    client = FakeClient(canned)
    return compute_returns(lines_for(fund_line()), fees, client, D, Decimal(100))["lines"][0]


def test_pct_of_cdi_is_net_over_cdi_for_a_cdi_like_fund():
    ln = fund_run(bench_fees(lamina="CDI", lamina_n=1))
    assert ln["benchmark"]["cdi_like"] is True and ln["benchmark"]["lamina"] == "CDI"
    for w in ln["windows"].values():
        assert w["cdi_like"] is True and w["pct_of_cdi_reason_code"] is None
        assert w["pct_of_cdi"] == pytest.approx(w["net_return_pct"] / w["cdi_pct"] * 100, abs=1e-3)
        assert w["net_minus_cdi_pp"] is not None  # the p.p. difference stays beside it
        assert not any("% do CDI" in n for n in w["notes"])  # the definition is the block's pct_of_cdi_note


@pytest.mark.parametrize("fees,code", [
    (bench_fees(extrato="IBOVESPA"), "referencia_nao_cdi"),
    (bench_fees(), "referencia_nao_informada"),
    (bench_fees(extrato="CDI", lamina="IBOVESPA", lamina_n=1), "referencia_diverge"),
    ({"lines": []}, "referencia_nao_servida"),
])
def test_a_fund_that_is_not_cdi_like_keeps_only_the_difference(fees, code):
    ln = fund_run(fees)
    for w in ln["windows"].values():
        assert w["pct_of_cdi"] is None and w["pct_of_cdi_reason_code"] == code
        assert w["net_minus_cdi_pp"] is not None and code in REASON_TEXT


@pytest.mark.parametrize("rate", [0.0, -0.01])
def test_a_cdi_at_or_below_zero_gives_no_pct_of_cdi(rate):
    ln = fund_run(bench_fees(extrato="CDI"), rate=rate)
    for w in ln["windows"].values():
        assert w["cdi_like"] is True and w["pct_of_cdi"] is None and w["pct_of_cdi_reason_code"] == "cdi_nao_positivo"


def test_a_share_never_gets_pct_of_cdi():
    tape = [dict(ticker="ABCD3", trade_date=month_end(m).isoformat(), close_total_return=v)
            for m, v in zip(MONTHS, path(10.0, [1.0] * 12))]
    sec, _ = run(lines_for(("ação", dict(status="identified", kind="ticker", ticker="ABCD3", asset_class="equity"))),
                 {"quote_history": [{"match": {}, "rows": tape}]})
    w = sec["lines"][0]["windows"]["12m"]
    assert w["pct_of_cdi"] is None and w["pct_of_cdi_reason_code"] == "pct_cdi_so_fundos"


def test_the_fee_record_carries_the_filed_benchmark_as_served():
    call = Call("portfolio_fees", {}, 7, [], None)
    row = {"benchmark_extrato": "CDI", "benchmark_lamina": None, "benchmark_lamina_n": 0, "extrato_as_of": "2026-06-30",
           "lamina_as_of": "2026-08-01", "disclosed_origin": "extrato", "disclosed_source": "cvm_fi_extrato"}
    rec = _fee_record(row, Decimal(100), call, dt.date(2026, 8, 1))
    assert rec["benchmark_as_filed"]["extrato"] == "CDI" and rec["benchmark_as_filed"]["lamina_n"] == 0
    # a pre-v67 row has no benchmark keys: not read as "not filed"
    assert _fee_record({"disclosed_origin": "extrato"}, Decimal(100), call, dt.date(2026, 8, 1))["benchmark_as_filed"] is None


# --- the market equivalent ---------------------------------------------------------------------------------------------


def eq_row(cls, ticker, pl, rank, segment="equities_br", indices=("SMLL (Small Cap)",), status="found", fee=0.5, eqv=None):
    return dict(classe_anbima=cls, class_indices=list(indices) if indices else None, n_etfs=2, ticker=ticker,
                etf_cnpj="90000000000911" if ticker else None, etf_name="ETF EXEMPLO" if ticker else None,
                underlying_index=indices[0] if indices and ticker else None, segment=segment if ticker else None,
                pl_brl=pl, pl_as_of="2026-10-01" if pl else None, fee_pct_year=fee if ticker else None,
                fee_as_of="2026-10-01" if fee is not None and ticker else None, snapshot_source="etfsbrasil",
                pl_rank=rank, is_equivalent=(rank == 1) if eqv is None else eqv, status=status, reason="sintético")


def dist_rows(cls, fc="N", status="evaluated", n=40):
    out = []
    for w, (p25, med, p75) in ((12, (8.0, 12.0, 15.0)), (6, (4.0, 6.0, 7.5))):
        out.append(dict(classe_anbima=cls, fundo_cotas=fc, window_months=w,
                        start_month=MONTHS[12 - w].isoformat(), end_month=MONTHS[-1].isoformat(), month_complete=True,
                        n_universe=n + 2, n_funds=n, n_excluded_no_quota=2, n_excluded_subclass=0,
                        p25_pct=p25 if status == "evaluated" else None, median_pct=med if status == "evaluated" else None,
                        p75_pct=p75 if status == "evaluated" else None, min_funds=30, status=status, reason="sintético"))
    return out


def close_rows(ticker, values, field="close"):
    return [dict(ticker=ticker, trade_date=month_end(m).isoformat(), **{field: v}) for m, v in zip(MONTHS, values)]


def eq_run(cls=SMALL, eq_rows=None, extra=None, fc="N", comparison=None, fund_values=None):
    lines = lines_for(fund_line())
    fund_values = fund_values or path(1.0, [1.0] * 12)
    ret, _ = run(lines, {"fund_nav": [{"match": {}, "rows": nav_rows(FUND, fund_values)}]})
    cmp_line = comparison if comparison is not None else {"line_no": 1, "classe_anbima": cls, "fundo_cotas": fc,
                                                          "etf_peer_tickers": ["SMXX11"]}
    fees = {"lines": [], "comparison": {"lines": [cmp_line]}}
    canned = {"portfolio_equivalents": [{"match": {}, "rows": eq_rows if eq_rows is not None else [
                  eq_row(cls, "SMXX11", 2.5e9, 1), eq_row(cls, "SMYY11", 9.0e7, 2)]}],
              "class_return_distribution": [{"match": {"p_classe_anbima": cls}, "rows": dist_rows(cls, fc)}],
              "quote_history": [{"match": {"p_ticker": "SMXX11"}, "rows": close_rows("SMXX11", path(100.0, [1.5] * 12))}],
              **(extra or {})}
    client = FakeClient(canned)
    sec = compute_equivalents(lines, fees, ret, client, D, dt.date(2026, 10, 5), Decimal(100))
    return sec, client


def test_a_mapped_class_gets_the_largest_etf_by_pl_set_beside_the_class():
    sec, client = eq_run()
    ln = sec["lines"][0]
    assert ln["status"] == "encontrado" and ln["reason_code"] is None and ln["label"] == EQ_LABEL == sec["label"]
    etf = ln["etf"]
    assert etf["ticker"] == "SMXX11" and etf["pl_brl"] == 2.5e9 and etf["pl_as_of"] == "2026-10-01"
    assert etf["fee_pct_year"] == 0.5 and etf["in_fee_peers"] is True and "terceiros" in etf["fee_label"]
    assert etf["basis"] == "close_sem_proventos" and etf["without_distributions"] is True
    w12, w6 = ln["windows"]
    assert w12["id"] == "12m" and w12["etf_net_return_pct"] == pytest.approx((1.015 ** 12 - 1) * 100, abs=1e-4)
    assert w12["fund_net_return_pct"] == pytest.approx((1.01 ** 12 - 1) * 100, abs=1e-4)
    assert (w12["class_p25_pct"], w12["class_median_pct"], w12["class_p75_pct"], w12["class_n_funds"]) == (8.0, 12.0, 15.0, 40)
    assert w12["etf_band"] == "acima_p75" and w12["fund_band"] == "mediana_p75"
    assert w12["etf_minus_median_pp"] == pytest.approx(w12["etf_net_return_pct"] - 12.0, abs=1e-5)
    assert w6["etf_band"] == "acima_p75"  # 6 months of 1.5% = 9.34% > 7.5
    # the calls: one equivalents call, the class distribution at the return block's end month, the raw close only
    calls = {p.tool: p.args for p in client.provenance}
    assert calls["portfolio_equivalents"] == {"p_classes": [SMALL], "p_as_of": "2026-10-05"}
    assert calls["class_return_distribution"] == {"p_classe_anbima": SMALL, "p_fundo_cotas": "N", "p_month": "2026-09-01"}
    assert calls["quote_history"]["p_fields"] == ["close"]
    assert not any(k in json.dumps([p.args for p in client.provenance]) for k in ("ref_price", "close_adj"))


def test_a_fixed_income_etf_reads_last_price_of_the_consolidated_file():
    rows = [eq_row(RF, "EXLF11", 4.2e9, 1, segment="fixed_income_br", indices=RF_INDICES)]
    tc = [{"match": {"p_ticker": "EXLF11"}, "rows": close_rows("EXLF11", path(100.0, [1.1] * 12), "last_price")}]
    sec, client = eq_run(RF, rows, {"trade_consolidated_history": tc,
                                    "class_return_distribution": [{"match": {}, "rows": dist_rows(RF)}]})
    ln = sec["lines"][0]
    assert ln["etf"]["basis"] == "last_price_etf_renda_fixa" and ln["windows"][0]["etf_status"] == "avaliado"
    assert "trade_consolidated_history" in {p.tool for p in client.provenance}
    assert "quote_history" not in {p.tool for p in client.provenance}


@pytest.mark.parametrize("status,code", [("sem_par", "equivalente_sem_par"), ("sem_etf", "equivalente_sem_etf"),
                                         ("sem_pl", "equivalente_sem_pl")])
def test_no_pair_no_etf_or_no_pl_is_a_fixed_reason(status, code):
    cls = "Ações Livre" if status == "sem_par" else SMALL
    idx = None if status == "sem_par" else ("SMLL (Small Cap)",)
    ticker = "SMXX11" if status == "sem_pl" else None
    rows = [eq_row(cls, ticker, None, None, indices=idx, status=status, eqv=False)]
    sec, client = eq_run(cls, rows)
    ln = sec["lines"][0]
    assert ln["status"] == "sem_equivalente" and ln["reason_code"] == code and ln["reason"] == REASON_TEXT[code]
    assert ln["etf"] is None and ln["windows"] == [] and code in sec["reason_codes"]
    assert "class_return_distribution" not in {p.tool for p in client.provenance}


def test_an_etf_without_a_full_series_has_no_return_and_says_why():
    short = close_rows("SMXX11", path(100.0, [1.5] * 12))[:-1]  # the last month-end is missing
    sec, _ = eq_run(extra={"quote_history": [{"match": {"p_ticker": "SMXX11"}, "rows": short}]})
    w12 = sec["lines"][0]["windows"][0]
    assert w12["etf_net_return_pct"] is None and w12["etf_reason_code"] == "equivalente_sem_retorno"
    assert w12["etf_series_reason_code"] == "serie_incompleta" and w12["etf_band"] is None
    assert w12["fund_band"] is not None  # the fund is still set beside its class


def test_a_fixed_income_etf_with_no_served_series_is_not_evaluated():
    rows = [eq_row(RF, "EXLF11", 4.2e9, 1, segment="fixed_income_br", indices=RF_INDICES)]
    sec, _ = eq_run(RF, rows, {"class_return_distribution": [{"match": {}, "rows": dist_rows(RF)}]})
    w = sec["lines"][0]["windows"][0]
    assert w["etf_reason_code"] == "equivalente_sem_retorno" and w["etf_series_reason_code"] == "etf_rf_sem_api"


def test_a_class_distribution_not_evaluated_gives_no_percentiles():
    sec, _ = eq_run(extra={"class_return_distribution": [{"match": {}, "rows": dist_rows(SMALL, status="nao_avaliado", n=17)}]})
    w = sec["lines"][0]["windows"][0]
    assert w["class_reason_code"] == "distribuicao_classe_nao_avaliada" and w["class_median_pct"] is None
    assert w["etf_band"] is None and w["fund_band"] is None and w["etf_net_return_pct"] is not None


def test_served_pairs_decide_a_deploy_lag_is_flagged_and_the_flag_must_be_the_largest():
    ok = eq_run()[0]["lines"][0]
    assert ok["pairs_match_rules"] is True and ok["class_indices_rules"] == ["SMLL (Small Cap)"]
    lag = [eq_row(SMALL, "SMXX11", 2.5e9, 1, indices=("SMLL (Small Cap)", "OUTRO INDICE"))]
    ln = eq_run(eq_rows=lag)[0]["lines"][0]
    assert ln["status"] == "encontrado" and ln["pairs_match_rules"] is False
    not_largest = [eq_row(SMALL, "SMXX11", 1.0e8, 1), eq_row(SMALL, "SMYY11", 9.0e9, 2)]
    assert eq_run(eq_rows=not_largest)[0]["lines"][0]["reason_code"] == "resposta_inconsistente"


@pytest.mark.parametrize("cmp_code", ["sem_linha_comparacao", "resposta_inconsistente"])
def test_a_class_is_read_only_from_a_comparison_row_the_fee_block_accepted(cmp_code):
    sec, client = eq_run(comparison={"line_no": 1, "classe_anbima": SMALL, "fundo_cotas": "X", "reason_code": cmp_code})
    assert sec["lines"][0]["reason_code"] == "equivalente_sem_comparacao"
    assert "portfolio_equivalents" not in {p.tool for p in client.provenance}
    sec, _ = eq_run(comparison={"line_no": 99})  # no comparison row for the line
    assert sec["lines"][0]["reason_code"] == "equivalente_sem_comparacao"


def test_a_window_not_compared_degrades_the_section():
    sec, _ = eq_run(extra={"class_return_distribution": [{"match": {}, "error": "boom"}]})
    assert sec["status"] == "partial" and "consulta_falhou" in sec["reason_codes"]
    assert sec["lines"][0]["windows"][0]["class_reason_code"] == "consulta_falhou"


def test_a_fund_without_a_class_or_a_failed_call_says_why():
    sec, client = eq_run(comparison={"line_no": 1, "classe_anbima": None, "reason_code": "sem_extrato_comparavel"})
    assert sec["lines"][0]["reason_code"] == "equivalente_sem_classe"
    assert "portfolio_equivalents" not in {p.tool for p in client.provenance}
    sec, _ = eq_run(extra={"portfolio_equivalents": [{"match": {}, "error": "boom"}]})
    assert sec["lines"][0]["reason_code"] == "consulta_falhou" and sec["status"] == "unknown"


# --- the demo and the report -------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def engine() -> dict:
    return json.loads(ENGINE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def view(engine) -> dict:
    return adapt.to_view(engine)


def test_the_demo_carries_both_and_every_gap_has_a_fixed_text(engine):
    assert engine["schema_version"] == "1.12" and list(engine).index("equivalents") == list(engine).index("tax") + 1
    eqs = engine["equivalents"]
    assert {ln["status"] for ln in eqs["lines"]} == {"encontrado", "sem_equivalente"}
    for ln in eqs["lines"]:
        assert ln["status"] == "encontrado" or ln["reason"] == REASON_TEXT[ln["reason_code"]]
    pct = [w["pct_of_cdi"] for ln in engine["returns"]["lines"] for w in ln["windows"].values() if w["pct_of_cdi"] is not None]
    assert pct and all(ln["tipo"] == "fundo" for ln in engine["returns"]["lines"]
                       if any(w["pct_of_cdi"] is not None for w in ln["windows"].values()))
    text = json.dumps(eqs, ensure_ascii=False).lower()
    assert "melhor" not in text and "recomendamos" not in text


def test_the_report_shows_the_equivalent_and_pct_of_cdi_where_the_engine_wrote_them(view):
    html = build.build(view, "fake")[0]
    sec = html.split("<h2>Equivalente de mercado</h2>")[1].split("</section>")[0]
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", sec))
    for needle in ("equivalente de mercado; não é recomendação", "EXLF11", "R$ 4,20 bilhões", "01/10/2026",
                   "fonte de terceiros", "sem proventos", "mediana", REASON_TEXT["equivalente_sem_par"],
                   REASON_TEXT["equivalente_sem_classe"]):
        assert needle in txt, needle
    assert "melhor" not in txt.lower()
    ret = html.split("<h2>Retorno por posição</h2>")[1].split("</section>")[0]
    rtxt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", ret.split("<table")[1].split("</table>")[0]))
    shown = re.findall(r"\d+,\d+% do CDI", rtxt)
    expected = [values.format_value(view, f"returns.lines[{i}].windows[{j}].pct_of_cdi")
                for i, ln in enumerate(view["returns"]["lines"]) for j, w in enumerate(ln["windows"])
                if w.get("pct_of_cdi") is not None]
    assert shown == expected and len(expected) == 4  # two CDI-like funds, two windows each
    assert REASON_TEXT["referencia_nao_cdi"] in rtxt and REASON_TEXT["referencia_nao_informada"] in rtxt


def F(text, section, cites=("p43",)):
    return Finding("f1", section, "Título", text, list(cites))


def _idx(view, line_id):
    return next(i for i, ln in enumerate(view["returns"]["lines"]) if ln["line_id"] == line_id)


def test_pct_of_cdi_is_kept_only_where_the_engine_wrote_it(view):
    i = _idx(view, "L5")
    ok = f"A linha {{{{returns.lines[{i}].line_id}}}} rendeu {{{{returns.lines[{i}].windows[0].pct_of_cdi}}}}."
    assert revisor.check(view, [F(ok, "retornos")]).removed == []
    j = _idx(view, "L3")  # the equity fund: benchmark Ibovespa, so the engine wrote no pct_of_cdi
    res = revisor.check(view, [F(f"Rendeu {{{{returns.lines[{j}].windows[0].pct_of_cdi}}}}.", "retornos")])
    assert res.kept == [] and "nulo" in res.removed[0].reason
    # the cdi_like flag is checked too, not only the value
    v = copy.deepcopy(view)
    v["returns"]["lines"][j]["windows"][0]["pct_of_cdi"] = 55.5
    res = revisor.check(v, [F(f"Rendeu {{{{returns.lines[{j}].windows[0].pct_of_cdi}}}}.", "retornos")])
    assert res.kept == [] and "índice de referência" in res.removed[0].reason


@pytest.mark.parametrize("text,why", [
    ("Rendeu {{returns.lines[4].windows[0].net_return_pct}}% do CDI.", "pct_of_cdi"),
    ("Rendeu {{returns.lines[4].windows[0].net_return_pct}} do CDI.", "não é o CDI"),
    ("Rendeu o equivalente a noventa e cinco por cento do CDI.", "pct_of_cdi"),
    ("Rendeu {{returns.lines[4].windows[0].pct_of_cdi}} do CDI.", "não é o CDI"),
    ("Rendeu {{returns.total_pct_of_cdi}}.", "sem caminho"),
])
def test_a_pct_of_cdi_the_engine_did_not_write_is_rejected(view, text, why):
    res = revisor.check(view, [F(text, "retornos")])
    assert res.kept == [] and why in res.removed[0].reason


@pytest.mark.parametrize("text", [
    "O ETF rendeu 14% em doze meses.",
    "A mediana da classe foi de 14,05%.",
    "O ETF tem patrimônio de R$ 4 bilhões.",
])
def test_an_invented_number_in_the_equivalent_section_is_rejected(view, text):
    res = revisor.check(view, [F(text, "equivalentes")])
    assert res.kept == [] and any(r.reason == "algarismo fora de marcador" for r in res.removed)


def test_engine_values_in_the_equivalent_section_are_kept(view):
    k = next(i for i, ln in enumerate(view["equivalents"]["lines"]) if ln["status"] == "encontrado")
    q = f"equivalents.lines[{k}]"
    text = (f"O ETF {{{{{q}.etf.ticker}}}} rendeu {{{{{q}.windows[0].etf_net_return_pct}}}}; a mediana da classe foi "
            f"{{{{{q}.windows[0].class_median_pct}}}} ({{{{equivalents.label}}}}).")
    assert revisor.check(view, [F(text, "equivalentes")]).removed == []
    res = revisor.check(view, [F(f"Taxa: {{{{{q}.etf.ranking_pct}}}}.", "equivalentes")])
    assert res.kept == [] and "sem caminho" in res.removed[0].reason
