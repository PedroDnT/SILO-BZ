"""Block 16 (engine 1.10): return per position, offline. One test per rule of the owner's resolution of #610."""

from __future__ import annotations

import datetime as dt
import json
import math
from decimal import Decimal
from pathlib import Path

import pytest

from src.portfolio.client import FakeClient
from src.portfolio.common import REASON_TEXT
from src.portfolio.identify import LineId
from src.portfolio.returns import NOTE_DRAWDOWN, NOTE_ETF, NOTE_PERFORMANCE, compute_returns
from src.portfolio.statement import parse_rows

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "portfolio" / "demo_engine_output.json"
D = dt.date(2026, 9, 30)
FUND = "08935128000159"
MONTHS = [dt.date(2025 + (8 + i) // 12, (8 + i) % 12 + 1, 1) for i in range(13)]  # 2025-09 .. 2026-09


def month_end(m: dt.date) -> dt.date:
    nxt = dt.date(m.year + m.month // 12, m.month % 12 + 1, 1)
    d = nxt - dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def weekdays(start: dt.date, end: dt.date) -> list[dt.date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def path(start: float, monthly_pct: list[float]) -> list[float]:
    out = [start]
    for r in monthly_pct:
        out.append(out[-1] * (1 + r / 100))
    return out


FLAT = [1.0] * 12
CDI_DAYS = weekdays(dt.date(2025, 9, 1), D)


def cdi_rows(rate=0.05, end_rate=None):
    return [dict(reference_date=d.isoformat(), series="CDI", value=(end_rate if end_rate is not None and d == D else rate))
            for d in CDI_DAYS]


def nav_rows(cnpj, values, months=MONTHS):
    return [dict(cnpj=cnpj, period=m.isoformat(), entity_type="fi", quota=v) for m, v in zip(months, values)]


def tape_rows(ticker, values, field):
    """One session per month-end, plus a mid-month session that must not be used."""
    rows = []
    for m, v in zip(MONTHS, values):
        rows.append(dict(ticker=ticker, trade_date=(m + dt.timedelta(days=14)).isoformat(), **{field: 999.0}))
        rows.append(dict(ticker=ticker, trade_date=month_end(m).isoformat(), **{field: v}))
    rows.sort(key=lambda r: r["trade_date"])
    return rows


def lines_for(*specs):
    """specs: (tipo, LineId kwargs)."""
    stmt = parse_rows([["total_extrato", 100.0 * len(specs)],
                       ["linha_extrato", "tipo", "codigo", "quantidade", "preco_unitario", "valor", "data_posicao"],
                       *[[f"Linha {i}", tipo, None, 1, 100, 100.0, D] for i, (tipo, _) in enumerate(specs, start=1)]])
    return [LineId(p, **kw) for p, (_, kw) in zip(stmt.positions, specs)]


def fund_line(cnpj=FUND):
    return ("fundo", dict(status="identified", kind="fund", cnpj=cnpj, entity_type="fi", name="FUNDO"))


def fee_lines(rate=2.0, kind="fixa", perf=None, line_no=1, counted=None):
    h = {"kind": kind, "rate_pct_year": rate, "origin": "extrato", "as_of": "2026-07-31",
         "sources": [{"tool": "portfolio_fees", "call_id": 99, "args": {}, "data_date": "2026-08-01"}]}
    if counted is not None:
        h["counted_as_cost"] = counted
    disclosed = {"perf_as_filed": perf, "terms_as_filed": None}
    return {"lines": [{"line_no": line_no, "headline": h, "disclosed": disclosed, "fee_status": "divulgada"}]}


def run(lines, canned, fees=None, position_date=D):
    canned = {"macro_series": [{"match": {"p_series": "CDI"}, "rows": cdi_rows()}], **canned}
    client = FakeClient(canned)
    sec = compute_returns(lines, fees or {"lines": []}, client, position_date, Decimal(100 * len(lines)))
    return sec, client


def one(sec, line_no=1):
    return next(ln for ln in sec["lines"] if ln["line_no"] == line_no)


# 1. Windows ----------------------------------------------------------------------------------


def test_windows_are_12_and_6_months_ending_at_the_position_month_and_6m_is_not_annualized():
    values = path(100.0, [1.0] * 12)
    sec, client = run(lines_for(fund_line()), {"fund_nav": [{"match": {}, "rows": nav_rows(FUND, values)}]})
    assert [(w["id"], w["base_month"], w["end_month"], w["annualized"]) for w in sec["windows"]] == [
        ("12m", "2025-09-01", "2026-09-01", False), ("6m", "2026-03-01", "2026-09-01", False)]
    ln = one(sec)
    w12, w6 = ln["windows"]["12m"], ln["windows"]["6m"]
    assert (w12["n_observations"], w6["n_observations"]) == (12, 6)
    assert w6["net_return_pct"] == pytest.approx((1.01 ** 6 - 1) * 100, abs=1e-6)  # the period's return, not annualized
    assert "não anualizado" in w6["notes"][0]
    # the month-ends used are listed, and the fund call does not pin p_to (no partial month served)
    assert [m["month"] for m in ln["month_ends"]] == [m.isoformat() for m in MONTHS]
    assert client.provenance[1].args == {"p_cnpj": FUND, "p_from": "2025-09-01", "p_entity_type": "fi"}


def test_a_position_date_inside_a_month_ends_the_windows_at_the_month_before():
    sec, _ = run(lines_for(fund_line()), {"fund_nav": [{"match": {}, "rows": []}]}, position_date=dt.date(2026, 9, 15))
    assert sec["end_month"] == "2026-08-01" and sec["windows"][0]["base_month"] == "2025-08-01"


# 2. Net return, by type ---------------------------------------------------------------------------


def test_fund_net_return_is_from_the_month_quotas():
    values = path(10.0, [2.0, -1.0] * 6)
    sec, _ = run(lines_for(fund_line()), {"fund_nav": [{"match": {}, "rows": nav_rows(FUND, values)}]})
    w = one(sec)["windows"]["12m"]
    assert one(sec)["basis"] == "cota_fundo" and w["status"] == "avaliado"
    assert w["net_return_pct"] == pytest.approx((values[-1] / values[0] - 1) * 100, abs=1e-6)
    assert w["base_date"] is None  # fund_nav serves the month, not the quota's day


def test_share_uses_close_total_return_from_the_month_end_session():
    vals = path(30.0, [2.0] * 12)
    lines = lines_for(("ação", dict(status="identified", kind="ticker", ticker="PETR4", asset_class="equity")))
    sec, client = run(lines, {"quote_history": [{"match": {}, "rows": tape_rows("PETR4", vals, "close_total_return")}]})
    ln = one(sec)
    assert ln["basis"] == "close_total_return" and ln["without_distributions"] is False
    assert client.provenance[1].args["p_fields"] == ["close_total_return", "close_total_return_null_reason"]
    w = ln["windows"]["12m"]
    assert (w["base_date"], w["end_date"]) == ("2025-09-30", "2026-09-30")
    assert w["net_return_pct"] == pytest.approx((1.02 ** 12 - 1) * 100, abs=1e-6)
    assert ln["fee"]["reason_code"] == "taxa_nao_aplicavel" and w["gross_return_est_pct"] is None


def test_share_with_a_null_total_return_is_not_evaluated_and_never_falls_back_to_the_price():
    vals = path(30.0, [2.0] * 12)
    rows = tape_rows("PETR4", vals, "close_total_return")
    rows[-1]["close_total_return"] = None
    rows[-1]["close_total_return_null_reason"] = "dividend history not proven"
    lines = lines_for(("ação", dict(status="identified", kind="ticker", ticker="PETR4", asset_class="equity")))
    sec, client = run(lines, {"quote_history": [{"match": {}, "rows": rows}]})
    w = one(sec)["windows"]["12m"]
    assert w["status"] == "nao_avaliado" and w["reason_code"] == "retorno_total_nulo"
    assert w["null_reasons"] == ["dividend history not proven"]
    assert len(client.provenance) == 2  # CDI and one quote_history: no second call for the price


def test_etf_and_fii_use_the_close_without_distributions():
    vals = path(100.0, [1.0] * 12)
    lines = lines_for(("ETF", dict(status="identified", kind="ticker", ticker="BOVA11", isin="BRBOVACTF003", etf_cnpj="10406511000161")),
                      ("FII", dict(status="identified", kind="fund", ticker="HGLG11", cnpj="11728688000147", entity_type="fii")))
    canned = {"quote_history": [{"match": {"p_ticker": "BOVA11"}, "rows": tape_rows("BOVA11", vals, "close")},
                                {"match": {"p_ticker": "HGLG11"}, "rows": tape_rows("HGLG11", vals, "close")}]}
    sec, client = run(lines, canned)
    etf, fii = one(sec, 1), one(sec, 2)
    assert etf["basis"] == fii["basis"] == "close_sem_proventos"
    assert etf["without_distributions"] and fii["without_distributions"]
    assert NOTE_ETF in etf["notes"] and "subestimado" in NOTE_ETF and "reinveste, muda pouco" in NOTE_ETF
    assert all(p.args.get("p_fields") == ["close"] for p in client.provenance if p.tool == "quote_history")
    assert etf["windows"]["12m"]["status"] == "avaliado"


def test_fixed_income_etf_without_its_tool_is_not_evaluated_and_never_falls_back():
    # identified only through the ETF registry (no ISIN: not on the cash tape)
    lines = lines_for(("ETF", dict(status="identified", kind="ticker", ticker="IMAB11", etf_cnpj="31024153000100")))
    sec, client = run(lines, {})
    ln = one(sec)
    assert ln["basis"] == "last_price_etf_renda_fixa"
    assert ln["status"] == "nao_avaliado" and ln["reason_code"] == "etf_rf_sem_api"
    assert ln["windows"]["12m"]["reason_code"] == ln["windows"]["6m"]["reason_code"] == "etf_rf_sem_api"
    assert [p.tool for p in client.provenance] == ["macro_series", "trade_consolidated_history"]  # no quote_history
    assert "etf_rf_sem_api" in REASON_TEXT


def test_fixed_income_etf_reads_last_price_never_ref_price():
    vals = path(100.0, [1.0] * 12)
    rows = tape_rows("IMAB11", vals, "last_price")
    for r in rows:
        r["ref_price"] = 1.0
    lines = lines_for(("ETF", dict(status="identified", kind="ticker", ticker="IMAB11", etf_cnpj="31024153000100")))
    sec, _ = run(lines, {"trade_consolidated_history": [{"match": {"p_ticker": "IMAB11"}, "rows": rows}]})
    w = one(sec)["windows"]["12m"]
    assert w["status"] == "avaliado" and w["net_return_pct"] == pytest.approx((1.01 ** 12 - 1) * 100, abs=1e-6)


# 3. CDI ---------------------------------------------------------------------------------------------


def test_cdi_is_compounded_from_the_base_date_inclusive_to_the_end_date_exclusive():
    values = path(100.0, FLAT)
    canned = {"macro_series": [{"match": {"p_series": "CDI"}, "rows": cdi_rows(0.05, end_rate=9.0)}],
              "fund_nav": [{"match": {}, "rows": nav_rows(FUND, values)}]}
    sec, client = run(lines_for(fund_line()), canned)
    w = one(sec)["windows"]["12m"]
    assert (w["cdi_base_date"], w["cdi_end_date"]) == ("2025-09-30", "2026-09-30")
    n = len([d for d in CDI_DAYS if dt.date(2025, 9, 30) <= d < D])
    assert w["cdi_n_rates"] == n
    expected = (Decimal("1.0005") ** n).quantize(Decimal("1e-8")) - 1  # the 9 %/day rate on the end date is excluded
    assert w["cdi_pct"] == pytest.approx(float(expected * 100), abs=1e-6)
    assert w["net_minus_cdi_pp"] == pytest.approx(w["net_return_pct"] - w["cdi_pct"], abs=1e-6)
    assert client.provenance[0].args == {"p_series": "CDI", "p_from": "2025-09-01", "p_to": "2026-09-30"}


def test_cdi_failure_keeps_the_net_return_and_says_why():
    values = path(100.0, FLAT)
    canned = {"macro_series": [{"match": {}, "error": "boom"}], "fund_nav": [{"match": {}, "rows": nav_rows(FUND, values)}]}
    sec, _ = run(lines_for(fund_line()), canned)
    w = one(sec)["windows"]["12m"]
    assert w["status"] == "avaliado" and w["cdi_pct"] is None and w["cdi_reason_code"] == "cdi_indisponivel"
    assert "cdi_indisponivel" in sec["reason_codes"]


# 4. Gross return -------------------------------------------------------------------------------------


def test_gross_is_net_plus_the_fee_blocks_fee_and_half_of_it_for_six_months():
    values = path(100.0, FLAT)
    sec, client = run(lines_for(fund_line()), {"fund_nav": [{"match": {}, "rows": nav_rows(FUND, values)}]}, fees=fee_lines(2.0))
    w12, w6 = one(sec)["windows"]["12m"], one(sec)["windows"]["6m"]
    assert w12["gross_return_est_pct"] == pytest.approx(w12["net_return_pct"] + 2.0, abs=1e-6)
    assert w6["gross_return_est_pct"] == pytest.approx(w6["net_return_pct"] + 1.0, abs=1e-6)
    assert w12["fee_pct_period"] == 2.0 and w6["fee_pct_period"] == 1.0
    assert "gross_label" not in w12  # engine 2.0: the report labels the gross "estimativa" (report/labels.py)
    assert {"tool": "portfolio_fees", "call_id": 99, "args": {}, "data_date": "2026-08-01"} in w12["sources"]
    assert "portfolio_fees" not in [p.tool for p in client.provenance]  # never fetched again


@pytest.mark.parametrize("kind,rate,counted", [("faixa", None, None), ("zero_informado", None, False), ("etf_site", 0.5, False)])
def test_no_usable_fee_means_no_gross_and_no_fee_metrics(kind, rate, counted):
    values = path(100.0, FLAT)
    sec, _ = run(lines_for(fund_line()), {"fund_nav": [{"match": {}, "rows": nav_rows(FUND, values)}]},
                 fees=fee_lines(rate, kind=kind, counted=counted))
    w = one(sec)["windows"]["12m"]
    assert w["status"] == "avaliado" and w["fee_reason_code"] == "sem_taxa_utilizavel"
    assert w["gross_return_est_pct"] is w["fee_per_point"] is w["sharpe_drag"] is None


# 5. Fee per point ---------------------------------------------------------------------------------------


def test_fee_per_point_is_fee_over_gross():
    values = path(100.0, [1.0] * 12)
    sec, _ = run(lines_for(fund_line()), {"fund_nav": [{"match": {}, "rows": nav_rows(FUND, values)}]}, fees=fee_lines(2.0))
    w = one(sec)["windows"]["12m"]
    assert w["fee_per_point"] == pytest.approx(2.0 / w["gross_return_est_pct"], abs=1e-6)
    assert w["fee_per_point_excluded_from_aggregates"] is False


def test_negative_gross_return_shows_the_computed_negative_value_excluded_from_aggregates():
    values = path(100.0, [-1.0] * 12)
    sec, _ = run(lines_for(fund_line()), {"fund_nav": [{"match": {}, "rows": nav_rows(FUND, values)}]}, fees=fee_lines(2.0))
    w = one(sec)["windows"]["12m"]
    assert w["gross_return_est_pct"] < 0
    assert w["fee_per_point"] == pytest.approx(2.0 / w["gross_return_est_pct"], abs=1e-6) and w["fee_per_point"] < 0
    assert w["fee_per_point_excluded_from_aggregates"] is True
    assert "nunca entra em média, mediana ou ranking" in w["fee_per_point_note"]
    # no mean, median, ranking or portfolio total anywhere in the section
    assert not {k for k in sec if any(x in k for x in ("mean", "median", "rank", "total_return", "portfolio_return"))}


# 6. Volatility -------------------------------------------------------------------------------------------


def test_volatility_is_the_sample_sd_of_monthly_returns_times_root_12_with_its_notes():
    monthly = [3, -2, 1, 4, -1, 2, 0, 5, -3, 1, 2, -2]
    values = path(100.0, monthly)
    sec, _ = run(lines_for(fund_line()), {"fund_nav": [{"match": {}, "rows": nav_rows(FUND, values)}]})
    w12, w6 = one(sec)["windows"]["12m"], one(sec)["windows"]["6m"]
    r = [m / 100 for m in monthly]

    def sd(xs):
        mu = sum(xs) / len(xs)
        return math.sqrt(sum((x - mu) ** 2 for x in xs) / (len(xs) - 1))

    assert w12["volatility_annual_pct"] == pytest.approx(sd(r) * math.sqrt(12) * 100, abs=1e-5)
    assert w6["volatility_annual_pct"] == pytest.approx(sd(r[-6:]) * math.sqrt(12) * 100, abs=1e-5)
    assert w12["volatility_note"] == "12 observações; estimativa ruidosa"
    assert w6["volatility_note"] == "6 observações; muito ruidosa"


# 7. Sharpe drag ------------------------------------------------------------------------------------------


def test_sharpe_drag_is_the_annual_fee_over_the_annualized_volatility():
    values = path(100.0, [3, -2, 1, 4, -1, 2, 0, 5, -3, 1, 2, -2])
    sec, _ = run(lines_for(fund_line()), {"fund_nav": [{"match": {}, "rows": nav_rows(FUND, values)}]}, fees=fee_lines(1.5))
    for wid in ("12m", "6m"):
        w = one(sec)["windows"][wid]
        assert w["sharpe_drag"] == pytest.approx(1.5 / w["volatility_annual_pct"], abs=1e-4)
        assert "quanto de Sharpe a taxa come" in w["sharpe_drag_note"]


@pytest.mark.parametrize("values", [
    path(100.0, [0.9] * 12),  # constant return: zero volatility
    path(100.0, [0.9, 0.95, 0.9, 0.92, 0.88, 0.9, 0.91, 0.9, 0.93, 0.89, 0.9, 0.9]),  # cash-like, well under 1% a.a.
])
def test_sharpe_drag_is_not_applicable_below_one_percent_volatility(values):
    sec, _ = run(lines_for(fund_line()), {"fund_nav": [{"match": {}, "rows": nav_rows(FUND, values)}]}, fees=fee_lines(1.5))
    for wid in ("12m", "6m"):
        w = one(sec)["windows"][wid]
        assert w["volatility_annual_pct"] < 1
        assert w["sharpe_drag"] is None and w["sharpe_drag_note"].startswith("não aplicável: volatilidade")
        assert w["fee_per_point"] is not None  # the fee per point still answers


# 8. Max drawdown -----------------------------------------------------------------------------------------


def test_max_drawdown_on_month_end_values_with_its_note():
    values = [100, 110, 99, 105, 88, 120, 118, 119, 121, 117, 122, 125, 124]
    sec, _ = run(lines_for(fund_line()), {"fund_nav": [{"match": {}, "rows": nav_rows(FUND, values)}]})
    w = one(sec)["windows"]["12m"]
    assert w["max_drawdown_pct"] == pytest.approx(-20.0, abs=1e-6)  # 110 -> 88
    assert (w["max_drawdown_peak_month"], w["max_drawdown_trough_month"]) == ("2025-10-01", "2026-01-01")
    assert w["max_drawdown_note"] == NOTE_DRAWDOWN == "em fechamentos mensais; quedas dentro do mês não aparecem"


# 9. Performance fee --------------------------------------------------------------------------------------


def test_fund_with_a_performance_fee_uses_the_administration_fee_only_and_says_so():
    values = path(100.0, [1.0] * 12)
    sec, _ = run(lines_for(fund_line()), {"fund_nav": [{"match": {}, "rows": nav_rows(FUND, values)}]},
                 fees=fee_lines(2.0, perf="20% do que exceder 100% do Ibovespa"))
    ln = one(sec)
    assert ln["performance_fee_filed"] is True
    assert NOTE_PERFORMANCE in ln["notes"]
    assert NOTE_PERFORMANCE == ("o retorno líquido já desconta a performance provisionada; a taxa por ponto mostrada "
                                "considera só a administração")
    assert ln["windows"]["12m"]["fee_pct_period"] == 2.0  # administration only


# 10. Lines without a series ------------------------------------------------------------------------------


def test_lines_without_a_series_are_not_evaluated_with_a_fixed_code_and_no_call():
    lines = lines_for(
        ("tesouro", dict(status="identified", kind="tesouro")),
        ("CDB", dict(status="unknown")),
        ("LCA", dict(status="unknown")),
        ("CRA", dict(status="identified", kind="credito")),
        ("debênture", dict(status="identified", kind="credito")),
        ("FIDC", dict(status="identified", kind="fund", cnpj="32113885000121", entity_type="fidc")),
        ("fundo", dict(status="unknown")),
    )
    sec, client = run(lines, {})
    codes = [ln["reason_code"] for ln in sec["lines"]]
    # schema 2.1: a CDB or LCA points to its contracted return in the annex; a CRA with no register match is not
    # identified for method A; a debênture waits for its method (owner's threshold)
    assert codes == ["retorno_tesouro_sem_serie", "retorno_contratado_anexo", "retorno_contratado_anexo",
                     "retorno_linha_nao_identificada", "retorno_debenture_metodo_pendente", "retorno_fidc_sem_classe",
                     "retorno_linha_nao_identificada"]
    assert all(ln["status"] == "nao_avaliado" and ln["basis"] is None for ln in sec["lines"])
    assert all(c in REASON_TEXT for c in codes)
    assert [p.tool for p in client.provenance] == ["macro_series"]
    assert sec["status"] == "not_applicable"


def test_a_missing_month_end_makes_the_window_not_evaluated():
    values = path(100.0, FLAT)
    rows = [r for r in nav_rows(FUND, values) if r["period"] != "2026-09-01"]  # September not yet complete
    sec, _ = run(lines_for(fund_line()), {"fund_nav": [{"match": {}, "rows": rows}]})
    ln = one(sec)
    assert ln["status"] == "nao_avaliado" and ln["reason_code"] == "serie_incompleta"
    assert ln["windows"]["12m"]["missing_months"] == ["2026-09-01"]
    assert sec["status"] == "partial" and "linhas_sem_retorno" in sec["reason_codes"]


def test_a_failed_series_call_is_recorded_and_the_line_is_not_evaluated():
    sec, _ = run(lines_for(fund_line()), {"fund_nav": [{"match": {}, "error": "22023: refused"}]})
    assert one(sec)["reason_code"] == "consulta_falhou"
    assert sec["status"] == "unknown" and sec["errors"][0]["error"] == "22023: refused"


# The demo -------------------------------------------------------------------------------------------------


def test_demo_return_block():
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    r = doc["returns"]
    assert doc["schema_version"] == "2.1" and list(doc).index("returns") == list(doc).index("risks") + 1
    by = {ln["line_no"]: ln for ln in r["lines"]}
    assert {n for n, ln in by.items() if ln["status"] == "avaliado"} == {2, 3, 4, 5, 7, 8, 11}
    assert by[1]["reason_code"] == "retorno_tesouro_sem_serie" and by[6]["reason_code"] == "retorno_fidc_sem_classe"
    # schema 2.1: the CDB and LCA point to their contracted return (the demo prints no initial date, so it is not
    # computed); the CRA is on the securitizer's curve; the debênture waits for its method
    assert by[9]["reason_code"] == by[10]["reason_code"] == "retorno_contratado_anexo"
    assert by[9]["contracted"]["reason_code"] == "contratado_sem_data_inicial"
    assert by[11]["basis"] == "curva_securitizadora" and by[11]["windows"]["12m"]["pct_of_cdi_reason_code"] == "credito_nao_cdi"
    assert by[12]["reason_code"] == "retorno_debenture_metodo_pendente"
    # Geração FIA: performance filed, negative 6-month gross shown and excluded
    assert by[3]["performance_fee_filed"] and by[3]["windows"]["6m"]["fee_per_point_excluded_from_aggregates"] is True
    assert by[3]["windows"]["6m"]["fee_per_point"] < 0
    assert by[4]["fee"]["reason_code"] == "sem_taxa_utilizavel"  # a range, not a single fee
    assert by[8]["without_distributions"] is True
    assert doc["section_status"]["returns"]["reason_codes"] == r["reason_codes"]


# 6. Retroactive contribution (engine 1.15) ------------------------------------------------------


def _fake_line(no, value, r):
    w = {"status": "avaliado", "net_return_pct": r} if r is not None else {"status": "nao_avaliado", "net_return_pct": None}
    return {"line_no": no, "linha_extrato": f"L{no}", "valor_brl": value, "windows": {"12m": w, "6m": dict(w)}}


def test_contribution_is_back_cast_from_todays_values_and_sums_to_the_return_of_the_evaluated_part():
    from src.portfolio.returns import CONTRIBUTION_LABEL, _contribution

    # 110 now after +10% means 100 at the start; 90 now after -10% means 100 at the start
    lines = [_fake_line(1, 110.0, 10.0), _fake_line(2, 90.0, -10.0), _fake_line(3, 500.0, None)]
    cov = {w: {"coverage_portfolio_value_pct": 28.57} for w in ("12m", "6m")}
    c = _contribution(lines, cov)
    assert c["label"] == CONTRIBUTION_LABEL == "contribuição retroativa"
    w = c["windows"]["12m"]
    assert [(x["line_no"], x["start_value_brl"], x["start_weight_pct"], x["contribution_pp"]) for x in w["lines"]] == [
        (1, 100.0, 50.0, 5.0), (2, 100.0, 50.0, -5.0)]
    assert w["covered_return_pct"] == 0.0 and w["start_value_brl"] == 200.0 and w["end_value_brl"] == 200.0
    assert w["n_lines"] == 2 and w["coverage_portfolio_value_pct"] == 28.57  # the line without a return is not in it


def test_contribution_without_an_evaluated_line_says_so_and_has_no_return():
    from src.portfolio.returns import _contribution

    c = _contribution([_fake_line(1, 50.0, None)], {w: {"coverage_portfolio_value_pct": 0.0} for w in ("12m", "6m")})
    w = c["windows"]["12m"]
    assert w["status"] == "nao_avaliado" and w["reason_code"] == "linhas_sem_retorno"
    assert w["covered_return_pct"] is None and w["lines"] == []


def test_demo_contribution_sums_to_the_covered_return_and_the_weights_to_100():
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    c = doc["returns"]["contribution"]
    assert "retroativa" in c["label"] and "nunca da carteira inteira" in c["note"]
    for wid in ("12m", "6m"):
        w = c["windows"][wid]
        assert w["status"] == "avaliado"
        assert sum(x["contribution_pp"] for x in w["lines"]) == pytest.approx(w["covered_return_pct"], abs=1e-3)
        assert sum(x["start_weight_pct"] for x in w["lines"]) == pytest.approx(100.0, abs=1e-3)
        # schema 2.1: the CRA on the curve is left out of the sum, and out of the share it covers
        assert [x["line_no"] for x in w["excluded_lines"]] == [11]
        assert w["coverage_portfolio_value_pct"] < doc["returns"]["coverage"][wid]["coverage_portfolio_value_pct"]
        evaluated = [ln["line_no"] for ln in doc["returns"]["lines"]
                     if ln["windows"][wid]["status"] == "avaliado" and ln["basis"] != "curva_securitizadora"]
        assert [x["line_no"] for x in w["lines"]] == evaluated  # statement order, nothing ranked
