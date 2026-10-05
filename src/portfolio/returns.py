"""Block 16 (engine 1.10): return per position over 12 and 6 months, against the CDI, with the fee's weight.

Owner's resolution of #610 (2026-10-05), on the inputs of #606 (``portfolio-return-coverage.md``) and #631
(``quota-net-of-fees.md``). A fact per asset: no threshold, no portfolio total, no ranking, no recommendation.

Series, routed by the line's type and identity (never a fallback from one source to another):

* a fund (``fundo``, CVM family ``fi``): the month quota of ``fund_nav``. The CVM quota is net of the fund's
  administration, management, distribution and provisioned performance fees and of its other expenses
  (Res. CVM 175 Art. 117 § 2; Anexo I Art. 28 §§ 5-6), gross of income tax and of entry and exit fees.
  ``fund_nav`` serves the month, not the quota's day, and is called without ``p_to``, so it ends at the family's
  latest COMPLETE period: a month that is not served is "série incompleta", never a mid-month quota;
* a share: ``close_total_return`` of ``quote_history`` (dividends and JCP reinvested on the ex session, JCP gross
  of withholding). A null value is shown with its reason, never replaced by the price return;
* an ETF on the B3 cash tape and an FII: the raw ``close`` (``quote_history`` refuses the adjusted close for
  them), flagged "sem proventos";
* a fixed-income ETF (identified through SILO's ETF registry, not on the cash tape): ``last_price`` of
  ``trade_consolidated_history``. When that tool is unknown or refuses, the line is "não avaliado"; ``ref_price``
  is never read as a close;
* everything else (Tesouro, CDB, LCI, LCA, CRA, CRI, debênture, a FIDC with no known tranche, a FIP, cash, an
  unidentified line): "não avaliado" with a fixed reason code.

Windows end at the month of the position date when that date is the month's last calendar day, else at the month
before (``movement.default_movement_month``). The month-end value is a fund's month quota, or a ticker's last
session in the month on or before the position date. Every window needs all its month-ends (13 for 12 months,
7 for 6); one missing makes the window "não avaliado".

Per window: net return; the CDI over the same dates (``macro_series('CDI')``, B3's DI-factor convention: daily
factors ``1 + rate/100`` truncated at 16 decimals, product over the rates dated from the base date inclusive to
the end date exclusive, rounded to 8); "% do CDI" (engine 1.13, #606 Q36) only for a fund whose own filed benchmark
is CDI or DI (``benchmark.py``, the versioned spelling list) and only when the CDI over the window is above zero, else
a reason code and only the difference in percentage points; volatility (sample standard deviation of the monthly returns, × √12);
maximum drawdown on month-end values; and, when the fee block has a single disclosed administration fee
(headline ``fixa`` or ``lamina_mais_recente``, or ``etf_site`` counted as a cost), the estimated gross return
(net + the annual fee; half of it for 6 months), the fee per point of gross return and the Sharpe drag
(annual fee ÷ annualized volatility). The 6-month figures are for their period, never annualized.
"""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Any

from src.portfolio import benchmark
from src.portfolio.client import SiloClient
from src.portfolio.common import (
    STATUS_NOT_APPLICABLE,
    Call,
    Section,
    add_months,
    as_date,
    brl,
    call_tool,
    dec,
    iso,
    pct,
    ratio,
    statement_source,
)
from src.portfolio.fees import _perf_filed
from src.portfolio.identify import LineId
from src.portfolio.movement import default_movement_month

EVALUATED = "avaliado"
NOT_EVALUATED = "nao_avaliado"
STATUS_LABELS = {EVALUATED: "avaliado", NOT_EVALUATED: "não avaliado"}

# (id, months, share of the annual fee charged in the window, volatility note)
WINDOWS = (
    ("12m", 12, Decimal(1), "12 observações; estimativa ruidosa"),
    ("6m", 6, Decimal("0.5"), "6 observações; muito ruidosa"),
)
SQRT12 = Decimal(12).sqrt()
CDI_FACTOR_PLACES = Decimal(1).scaleb(-16)
CDI_PRODUCT_PLACES = Decimal(1).scaleb(-8)

FUND = "cota_fundo"
TOTAL_RETURN = "close_total_return"
CLOSE = "close_sem_proventos"
FIXED_INCOME_ETF = "last_price_etf_renda_fixa"
BASIS_LABELS = {
    FUND: "cota mensal do fundo (fund_nav): líquida das taxas do fundo, bruta de IR",
    TOTAL_RETURN: "fechamento com dividendos e JCP reinvestidos (close_total_return); JCP bruto de IR",
    CLOSE: "fechamento sem proventos (close): variação de preço",
    FIXED_INCOME_ETF: "último preço do arquivo consolidado da B3 (last_price), sem proventos",
}
TOOLS = {
    FUND: "fund_nav",
    TOTAL_RETURN: "quote_history",
    CLOSE: "quote_history",
    FIXED_INCOME_ETF: "trade_consolidated_history",
}
VALUE_FIELD = {TOTAL_RETURN: "close_total_return", CLOSE: "close", FIXED_INCOME_ETF: "last_price"}

USABLE_FEE_KINDS = ("fixa", "lamina_mais_recente")

NOTE_FUND = (
    "Cota líquida das taxas de administração, gestão, distribuição e da performance provisionada e dos encargos do "
    "fundo (Res. CVM 175, Art. 117 § 2); bruta de IR e de taxas de ingresso e saída."
)
NOTE_FUND_DATES = (
    "fund_nav serve a cota do mês (último informe diário arquivado no mês), não o dia: as datas do CDI são o último "
    "dia útil do mês no calendário do próprio CDI."
)
NOTE_SHARE = "Dividendos e JCP reinvestidos na data ex; JCP bruto de IR. Ação não tem taxa de administração."
NOTE_ETF = (
    "Sem proventos: para um ETF que distribui rendimentos, o retorno fica subestimado; para um que reinveste, muda pouco."
)
NOTE_FII = "Sem proventos: só a variação de preço da cota; os rendimentos distribuídos pelo FII não entram."
NOTE_PERFORMANCE = (
    "o retorno líquido já desconta a performance provisionada; a taxa por ponto mostrada considera só a administração"
)
NOTE_GROSS = (
    "estimativa: retorno líquido mais a taxa de administração divulgada (metade dela na janela de 6 meses); não "
    "inclui IR, taxas de ingresso e saída nem a performance"
)
NOTE_FEE_PER_POINT = "taxa do período dividida pelo retorno bruto estimado do período"
NOTE_FEE_PER_POINT_NEGATIVE = (
    "retorno bruto estimado negativo: valor mostrado como calculado, nunca entra em média, mediana ou ranking"
)
NOTE_SHARPE = (
    "quanto de Sharpe a taxa come: Sharpe bruto menos Sharpe líquido = taxa anual dividida pela volatilidade anualizada"
)
# Owner, 2026-10-05 (Q17): below 1% annual volatility (a cash-like fund) fee / volatility explodes and says nothing
# the fee per point does not; a fixed rule, never tuned per fund.
SHARPE_MIN_VOL = Decimal("0.01")
NOTE_SHARPE_LOW_VOL = "não aplicável: volatilidade anualizada abaixo de 1% a.a. (fundo tipo caixa); veja a taxa por ponto"
NOTE_DRAWDOWN = "em fechamentos mensais; quedas dentro do mês não aparecem"
NOTE_SIX_MONTHS = "retorno do período de 6 meses, não anualizado"
NOT_A_RECOMMENDATION = (
    "Fato por ativo sobre um período passado: sem limiar, sem total da carteira e sem ranking; não é previsão nem "
    "recomendação."
)
DEFINITION = (
    "Retorno líquido = valor de fim de mês final dividido pelo do mês base, menos 1. CDI composto pela convenção do "
    "fator DI da B3 (fatores diários truncados em 16 casas, produto arredondado em 8), das taxas da data base, "
    "inclusive, à data final, exclusive. Volatilidade = desvio padrão amostral dos retornos mensais vezes raiz de 12. "
    "Queda máxima = maior perda de um fechamento mensal para um fechamento posterior, na janela."
)

# A line that no series covers: the fixed code, by type.
NO_SERIES_BY_TIPO = {
    "tesouro": "retorno_tesouro_sem_serie",
    "CDB": "retorno_credito_sem_serie",
    "LCI": "retorno_credito_sem_serie",
    "LCA": "retorno_credito_sem_serie",
    "CRA": "retorno_credito_sem_serie",
    "CRI": "retorno_credito_sem_serie",
    "debênture": "retorno_credito_sem_serie",
    "caixa": "retorno_caixa",
    "FIDC": "retorno_fidc_sem_classe",
    "FIP": "retorno_fip_sem_serie",
}
REASONS = {
    "retorno_tesouro_sem_serie": "título do Tesouro: o SILO não tem série de preços",
    "retorno_credito_sem_serie": "crédito direto (CDB, LCI, LCA, CRA, CRI, debênture): sem série de preços no SILO",
    "retorno_caixa": "saldo em conta corrente: sem série",
    "retorno_fidc_sem_classe": "FIDC: o extrato não diz qual classe ou série de cotas a linha detém",
    "retorno_fip_sem_serie": "FIP: sem cota mensal no SILO",
    "retorno_sem_ticker": "FII ou ETF sem ticker identificado: sem série de preços",
    "retorno_sem_regra": "tipo de linha sem série de retorno definida",
    "retorno_linha_nao_identificada": "linha não identificada: sem série",
    "etf_rf_sem_api": "ETF de renda fixa: o SILO ainda não serve a sua série de preços por uma API pública",
    "serie_incompleta": "falta um fechamento mensal da janela",
    "retorno_total_nulo": "retorno total sem valor no fechamento usado; sem recurso à variação de preço",
    "consulta_falhou": "consulta ao SILO falhou ou foi recusada",
    "resposta_inconsistente": "resposta do SILO inconsistente; a linha não foi avaliada",
}
# engine 1.13: why a window has no "% do CDI" (fixed Portuguese text in common.REASON_TEXT)
PCT_CDI_ONLY_FUNDS = "pct_cdi_so_fundos"
PCT_CDI_NOT_SERVED = "referencia_nao_servida"
PCT_CDI_NOT_POSITIVE = "cdi_nao_positivo"
NOTE_PCT_OF_CDI = (
    "% do CDI = retorno líquido dividido pelo CDI das mesmas datas, vezes 100; só para fundo cujo índice de referência "
    "arquivado (Extrato ou lâmina) é CDI ou DI, e só com CDI do período acima de zero"
)


def compute_returns(
    lines: list[LineId],
    fees: dict[str, Any],
    client: SiloClient,
    position_date: dt.date,
    portfolio_total: Decimal,
) -> dict[str, Any]:
    sec = Section()
    end_month = default_movement_month(position_date)
    base_month = add_months(end_month, -12)
    months = [add_months(base_month, i) for i in range(13)]
    cdi = _Cdi.fetch(client, base_month, position_date, sec)
    fee_by = {f["line_no"]: f for f in fees.get("lines", [])}
    cache: dict[str, tuple[dict[dt.date, dict[str, Any]] | None, Call | None, str | None]] = {}

    out = []
    for li in lines:
        out.append(_line(li, fee_by.get(li.line_no), client, months, position_date, cdi, cache, sec))

    routed = [ln for ln in out if ln["basis"] is not None]
    failed = [ln for ln in routed if ln["reason_code"] == "consulta_falhou"]
    if not routed:
        sec.status = STATUS_NOT_APPLICABLE
        sec.reason = "Nenhuma linha com série de preços ou cotas no SILO."
    elif len(failed) == len(routed):
        sec.fail("Todas as consultas de série falharam (erro literal em errors).", code="consulta_falhou")
    if routed and any(ln["status"] == NOT_EVALUATED for ln in out) and sec.status != "unknown":
        sec.degrade("Há linhas sem retorno avaliado; cada linha informa o motivo.", code="linhas_sem_retorno")
    if cdi.error_code and routed:
        sec.degrade("CDI do período indisponível; a comparação com o CDI não foi feita.", code="cdi_indisponivel")

    coverage = {}
    for wid, _n, _f, _note in WINDOWS:
        covered = sum(
            (Decimal(str(ln["valor_brl"])) for ln in out if ln["windows"][wid]["status"] == EVALUATED), Decimal("0")
        )
        coverage[wid] = {
            "evaluated_value_brl": brl(covered),
            "coverage_portfolio_value_pct": pct(covered, portfolio_total),
            "n_evaluated": sum(ln["windows"][wid]["status"] == EVALUATED for ln in out),
        }
    return {
        **sec.head(),
        "position_date": iso(position_date),
        "end_month": iso(end_month),
        "windows": [
            {
                "id": wid,
                "months": n,
                "base_month": iso(add_months(end_month, -n)),
                "end_month": iso(end_month),
                "annualized": False,
                "fee_share_of_annual": float(frac),
                "volatility_note": note,
                "note": NOTE_SIX_MONTHS if n == 6 else None,
            }
            for wid, n, frac, note in WINDOWS
        ],
        "definition": DEFINITION,
        "gross_note": NOTE_GROSS,
        "sharpe_drag_note": NOTE_SHARPE,
        "drawdown_note": NOTE_DRAWDOWN,
        "performance_note": NOTE_PERFORMANCE,
        "pct_of_cdi_note": NOTE_PCT_OF_CDI,  # engine 1.13
        "note": NOT_A_RECOMMENDATION,
        "cdi": cdi.as_dict(),
        "lines": out,
        "n_lines": len(out),
        "n_evaluated": sum(ln["status"] == EVALUATED for ln in out),
        "n_not_evaluated": sum(ln["status"] == NOT_EVALUATED for ln in out),
        "coverage": coverage,
    }


# ---------------------------------------------------------------------------
# CDI
# ---------------------------------------------------------------------------


class _Cdi:
    def __init__(self, rates: list[tuple[dt.date, Decimal]], call: Call | None, error_code: str | None):
        self.rates = rates
        self.call = call
        self.error_code = error_code

    @classmethod
    def fetch(cls, client: SiloClient, base_month: dt.date, position_date: dt.date, sec: Section) -> "_Cdi":
        args = {"p_series": "CDI", "p_from": base_month.isoformat(), "p_to": position_date.isoformat()}
        call = call_tool(client, "macro_series", args, sec.errors)
        if not call.ok:
            return cls([], call, "consulta_falhou")
        rates = []
        for r in call.rows or []:
            d, v = as_date(r.get("reference_date")), dec(r.get("value"))
            if d is None or v is None or (r.get("series") not in (None, "CDI")):
                return cls([], call, "resposta_inconsistente")
            rates.append((d, v))
        rates.sort()
        if len({d for d, _ in rates}) != len(rates):
            return cls([], call, "resposta_inconsistente")
        if not rates:
            return cls([], call, "cdi_indisponivel")
        return cls(rates, call, None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "series": "CDI",
            "sgs_code": 12,
            "unit": "% ao dia útil",
            "convention": (
                "fator DI da B3: produto de (1 + taxa/100), cada fator truncado em 16 casas, das taxas datadas da data "
                "base, inclusive, à data final, exclusive; produto arredondado em 8 casas"
            ),
            "n_rates": len(self.rates),
            "first_date": iso(self.rates[0][0]) if self.rates else None,
            "last_date": iso(self.rates[-1][0]) if self.rates else None,
            "status": "ok" if self.error_code is None else NOT_EVALUATED,
            "reason_code": self.error_code,
            "sources": [self.call.src(self.rates[-1][0] if self.rates else None)] if self.call else [],
        }

    def month_end(self, month: dt.date) -> dt.date | None:
        """The last business day of ``month`` in the CDI's own calendar, when the series shows the month is over."""
        inside = [d for d, _ in self.rates if d.year == month.year and d.month == month.month]
        if not inside:
            return None
        last = inside[-1]
        nxt = add_months(month, 1)
        if any(d >= nxt for d, _ in self.rates) or last >= _last_weekday(month):
            return last
        return None

    def compound(self, start: dt.date, end: dt.date) -> tuple[Decimal | None, int]:
        """B3's DI factor from ``start`` inclusive to ``end`` exclusive, minus 1; None when the series does not reach ``end``."""
        if not self.rates or self.rates[0][0] > start or self.rates[-1][0] < end:
            return None, 0
        factor = Decimal(1)
        n = 0
        for d, v in self.rates:
            if start <= d < end:
                factor *= (1 + v / 100).quantize(CDI_FACTOR_PLACES, rounding=ROUND_DOWN)
                n += 1
        return factor.quantize(CDI_PRODUCT_PLACES, rounding=ROUND_HALF_UP) - 1, n


def _last_weekday(month: dt.date) -> dt.date:
    d = add_months(month, 1) - dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


# ---------------------------------------------------------------------------
# One line
# ---------------------------------------------------------------------------


def _route(li: LineId) -> tuple[str | None, str | None]:
    """(basis, None) for a line with a series, or (None, reason code) for one without."""
    tipo = li.position.tipo
    if tipo in NO_SERIES_BY_TIPO:  # by type, identified or not: no series exists for it
        return None, NO_SERIES_BY_TIPO[tipo]
    if li.status != "identified":
        return None, "retorno_linha_nao_identificada"
    if tipo == "ação" or (tipo == "outro" and li.ticker and li.asset_class == "equity" and not li.etf_cnpj):
        return (TOTAL_RETURN, None) if li.ticker else (None, "retorno_sem_ticker")
    if tipo == "FII":
        return (CLOSE, None) if li.ticker else (None, "retorno_sem_ticker")
    if tipo == "ETF" or (tipo == "outro" and li.etf_cnpj):
        if not li.ticker:
            return None, "retorno_sem_ticker"
        # on the cash tape (lookup found its ISIN) -> close; known only from the ETF registry -> fixed-income file
        return (CLOSE, None) if li.isin else (FIXED_INCOME_ETF, None)
    if tipo == "fundo":
        if li.kind != "fund" or not li.cnpj:
            return None, "retorno_linha_nao_identificada"
        if li.entity_type == "fidc":
            return None, "retorno_fidc_sem_classe"
        if li.entity_type == "fip":
            return None, "retorno_fip_sem_serie"
        if li.entity_type not in (None, "fi"):
            return None, "retorno_sem_regra"
        return FUND, None
    if tipo == "outro":
        return None, "retorno_credito_sem_serie" if li.kind == "credito" else "retorno_sem_regra"
    return None, "retorno_sem_regra"


def _empty_window(code: str | None, reason: str | None) -> dict[str, Any]:
    return {
        "status": NOT_EVALUATED,
        "status_label": STATUS_LABELS[NOT_EVALUATED],
        "reason_code": code,
        "reason": reason,
        "base_month": None,
        "end_month": None,
        "base_date": None,
        "end_date": None,
        "base_value": None,
        "end_value": None,
        "n_observations": None,
        "net_return_pct": None,
        "cdi_pct": None,
        "cdi_base_date": None,
        "cdi_end_date": None,
        "cdi_n_rates": None,
        "cdi_reason_code": None,
        "net_minus_cdi_pp": None,
        "cdi_like": None,  # engine 1.13: the line's filed benchmark is CDI or DI (benchmark.py)
        "pct_of_cdi": None,  # engine 1.13: net / CDI x 100, only when cdi_like and the CDI is above zero
        "pct_of_cdi_reason_code": None,
        "volatility_annual_pct": None,
        "volatility_note": None,
        "max_drawdown_pct": None,
        "max_drawdown_peak_month": None,
        "max_drawdown_trough_month": None,
        "max_drawdown_note": NOTE_DRAWDOWN,
        "fee_status": None,
        "fee_reason_code": None,
        "fee_pct_period": None,
        "gross_return_est_pct": None,
        "gross_label": "estimativa",
        "fee_per_point": None,
        "fee_per_point_excluded_from_aggregates": None,
        "fee_per_point_note": None,
        "sharpe_drag": None,
        "sharpe_drag_note": None,
        "notes": [],
        "sources": [],
    }


def _line(
    li: LineId,
    fee_line: dict[str, Any] | None,
    client: SiloClient,
    months: list[dt.date],
    position_date: dt.date,
    cdi: _Cdi,
    cache: dict,
    sec: Section,
) -> dict[str, Any]:
    p = li.position
    basis, code = _route(li)
    rec: dict[str, Any] = {
        "line_no": li.line_no,
        "linha_extrato": p.linha_extrato,
        "tipo": p.tipo,
        "cnpj": li.cnpj if basis == FUND else None,
        "ticker": li.ticker if basis in (TOTAL_RETURN, CLOSE, FIXED_INCOME_ETF) else None,
        "name": li.name,
        "valor_brl": brl(p.valor),
        "basis": basis,
        "basis_label": BASIS_LABELS.get(basis),
        "without_distributions": basis in (CLOSE, FIXED_INCOME_ETF),
        "status": NOT_EVALUATED,
        "status_label": STATUS_LABELS[NOT_EVALUATED],
        "reason_code": None,
        "reason": None,
        "fee": None,
        "benchmark": None,  # engine 1.13: the filed benchmark and whether it is CDI-like
        "performance_fee_filed": False,
        "notes": [],
        "month_ends": [],
        "windows": {},
        "sources": [statement_source(li.line_no, p.data_posicao)],
    }
    if basis is None:
        rec.update(reason_code=code, reason=REASONS[code])
        rec["windows"] = {wid: _empty_window(code, REASONS[code]) for wid, *_ in WINDOWS}
        return rec

    rec["notes"] = _basis_notes(basis, p.tipo)
    fee = _fee(li, basis, fee_line)
    rec["fee"] = fee
    bench = _benchmark(basis, fee_line)
    rec["benchmark"] = bench
    rec["performance_fee_filed"] = bool(fee_line and _perf_filed(fee_line))
    if rec["performance_fee_filed"]:
        rec["notes"].append(NOTE_PERFORMANCE)

    points, call, err = _series(li.cnpj, li.ticker, li.line_no, basis, client, months, position_date, cache, sec)
    if call is not None:
        rec["sources"].append(call.src(_last_date(points) or position_date))
    if points is None:
        reason = REASONS[err]
        if basis == FIXED_INCOME_ETF and err != "resposta_inconsistente":
            err, reason = "etf_rf_sem_api", REASONS["etf_rf_sem_api"]
        rec.update(reason_code=err, reason=reason)
        rec["windows"] = {wid: _empty_window(err, reason) for wid, *_ in WINDOWS}
        return rec
    rec["month_ends"] = [
        {"month": iso(m), "date": iso(points[m]["date"]) if m in points else None,
         "value": ratio(points[m]["value"], 8) if m in points else None,
         "null_reason": points[m].get("null_reason") if m in points else None}
        for m in months
    ]
    for wid, n, frac, vol_note in WINDOWS:
        rec["windows"][wid] = _window(months[-(n + 1):], n, frac, vol_note, points, basis, fee, cdi, call, bench)
    if any(w["status"] == EVALUATED for w in rec["windows"].values()):
        rec.update(status=EVALUATED, status_label=STATUS_LABELS[EVALUATED])
    else:
        first = rec["windows"]["12m"]
        rec.update(reason_code=first["reason_code"], reason=first["reason"])
    return rec


def _no_benchmark(code: str) -> dict[str, Any]:
    return {"cdi_like": False, "reason_code": code, "extrato": None, "lamina": None, "lamina_n": None,
            "extrato_as_of": None, "lamina_as_of": None, "matched": [], "rule_version": None, "sources": []}


def _benchmark(basis: str, fee_line: dict[str, Any] | None) -> dict[str, Any]:
    """The filed benchmark the fee block read (catalog v68), classified by the versioned spelling list."""
    if basis != FUND:
        return _no_benchmark(PCT_CDI_ONLY_FUNDS)
    filed = (fee_line or {}).get("benchmark_as_filed")
    if not filed:
        return _no_benchmark(PCT_CDI_NOT_SERVED)
    verdict = benchmark.classify(filed.get("extrato"), filed.get("lamina"), filed.get("lamina_n"))
    return {
        "cdi_like": verdict["cdi_like"],
        "reason_code": verdict["reason_code"],
        "extrato": filed.get("extrato"),  # as filed, never normalized in the output
        "lamina": filed.get("lamina"),
        "lamina_n": filed.get("lamina_n"),
        "extrato_as_of": filed.get("extrato_as_of"),
        "lamina_as_of": filed.get("lamina_as_of"),
        "matched": verdict["matched"],
        "rule_version": verdict["rule_version"],
        "sources": list(filed.get("sources") or []),
    }


def _basis_notes(basis: str, tipo: str) -> list[str]:
    if basis == FUND:
        return [NOTE_FUND, NOTE_FUND_DATES]
    if basis == TOTAL_RETURN:
        return [NOTE_SHARE]
    if tipo == "FII":
        return [NOTE_FII]
    return [NOTE_ETF]


def _fee(li: LineId, basis: str, fee_line: dict[str, Any] | None) -> dict[str, Any]:
    """The administration fee the fee block already shows for the line; never fetched or estimated here."""
    if basis == TOTAL_RETURN:
        return {"status": "nao_se_aplica", "reason_code": "taxa_nao_aplicavel", "rate_pct_year": None, "kind": None,
                "origin": None, "as_of": None, "sources": []}
    h = (fee_line or {}).get("headline") or {}
    kind = h.get("kind")
    rate = dec(h.get("rate_pct_year"))
    usable = rate is not None and rate > 0 and (
        kind in USABLE_FEE_KINDS or (kind == "etf_site" and h.get("counted_as_cost") is True)
    )
    if not usable:
        return {"status": NOT_EVALUATED, "reason_code": "sem_taxa_utilizavel", "rate_pct_year": None, "kind": kind,
                "fee_status": (fee_line or {}).get("fee_status"), "origin": h.get("origin"), "as_of": h.get("as_of"),
                "sources": list(h.get("sources") or [])}
    return {"status": "ok", "reason_code": None, "rate_pct_year": ratio(rate, 4), "kind": kind,
            "fee_status": (fee_line or {}).get("fee_status"), "origin": h.get("origin"), "as_of": h.get("as_of"),
            "sources": list(h.get("sources") or [])}


# ---------------------------------------------------------------------------
# Series
# ---------------------------------------------------------------------------


def _series(
    cnpj: str | None,
    ticker: str | None,
    line_no: int | None,
    basis: str,
    client: SiloClient,
    months: list[dt.date],
    position_date: dt.date,
    cache: dict,
    sec: Section,
) -> tuple[dict[dt.date, dict[str, Any]] | None, Call | None, str | None]:
    """Month -> {date, value[, null_reason]} for the 13 months, or (None, call, reason code)."""
    base = months[0]
    if basis == FUND:
        args = {"p_cnpj": cnpj, "p_from": base.isoformat(), "p_entity_type": "fi"}
    elif basis == FIXED_INCOME_ETF:
        args = {"p_ticker": ticker, "p_from": base.isoformat(), "p_to": position_date.isoformat()}
    else:
        fields = ["close_total_return", "close_total_return_null_reason"] if basis == TOTAL_RETURN else ["close"]
        args = {"p_ticker": ticker, "p_from": base.isoformat(), "p_to": position_date.isoformat(), "p_fields": fields}
    tool = TOOLS[basis]
    key = f"{tool}:{sorted(args.items())}"
    if key in cache:
        return cache[key]
    call = call_tool(client, tool, args, sec.errors)
    if not call.ok:
        if basis != FIXED_INCOME_ETF:
            sec.degrade(f"{tool} falhou para {_who(line_no, ticker)} (erro literal em errors).", code="consulta_falhou")
        result = (None, call, "consulta_falhou")
    else:
        pts = _fund_points(call.rows or [], months) if basis == FUND else _tape_points(call.rows or [], months, position_date, basis)
        if pts is None:
            sec.degrade(f"{tool} devolveu resposta inconsistente para {_who(line_no, ticker)}.", code="resposta_inconsistente")
            result = (None, call, "resposta_inconsistente")
        else:
            result = (pts, call, None)
    cache[key] = result
    return result


def _who(line_no: int | None, ticker: str | None) -> str:
    return f"a linha {line_no}" if line_no is not None else f"o ticker {ticker}"


def _fund_points(rows: list[dict], months: list[dt.date]) -> dict[dt.date, dict[str, Any]] | None:
    out: dict[dt.date, dict[str, Any]] = {}
    for r in rows:
        if r.get("entity_type") not in (None, "fi"):
            continue
        d = as_date(r.get("period"))
        if d is None:
            return None
        m = d.replace(day=1)
        if m in out:
            return None  # two quotas for one month: not a month-end series
        q = dec(r.get("quota"))
        if q is not None and q <= 0:
            q = None
        out[m] = {"date": None, "value": q}
    return {m: v for m, v in out.items() if m in months and v["value"] is not None}


def _tape_points(rows: list[dict], months: list[dt.date], position_date: dt.date, basis: str) -> dict[dt.date, dict[str, Any]] | None:
    field = VALUE_FIELD[basis]
    by_month: dict[dt.date, tuple[dt.date, dict]] = {}
    seen: set[dt.date] = set()
    for r in rows:
        d = as_date(r.get("trade_date"))
        if d is None:
            return None
        if d in seen:
            return None
        seen.add(d)
        if d > position_date:
            continue
        m = d.replace(day=1)
        if m not in by_month or d > by_month[m][0]:
            by_month[m] = (d, r)
    out: dict[dt.date, dict[str, Any]] = {}
    for m in months:
        if m not in by_month:
            continue
        d, r = by_month[m]
        v = dec(r.get(field))
        if v is not None and v <= 0:
            v = None
        out[m] = {"date": d, "value": v}
        if v is None and basis == TOTAL_RETURN:
            out[m]["null_reason"] = r.get("close_total_return_null_reason")
    return out


def _last_date(points: dict[dt.date, dict[str, Any]] | None) -> dt.date | None:
    if not points:
        return None
    dates = [v["date"] for v in points.values() if v.get("date")]
    return max(dates) if dates else None


# ---------------------------------------------------------------------------
# One window
# ---------------------------------------------------------------------------


def _window(
    months: list[dt.date],
    n: int,
    frac: Decimal,
    vol_note: str,
    points: dict[dt.date, dict[str, Any]],
    basis: str,
    fee: dict[str, Any],
    cdi: _Cdi,
    call: Call | None,
    bench: dict[str, Any] | None = None,
) -> dict[str, Any]:
    missing = [m for m in months if m not in points]
    nulls = [m for m in months if m in points and points[m]["value"] is None]
    if missing:
        w = _empty_window("serie_incompleta", REASONS["serie_incompleta"])
        w.update(base_month=iso(months[0]), end_month=iso(months[-1]), missing_months=[iso(m) for m in missing])
        return w
    if nulls:
        w = _empty_window("retorno_total_nulo" if basis == TOTAL_RETURN else "serie_incompleta",
                          REASONS["retorno_total_nulo" if basis == TOTAL_RETURN else "serie_incompleta"])
        w.update(base_month=iso(months[0]), end_month=iso(months[-1]), missing_months=[iso(m) for m in nulls],
                 null_reasons=[points[m].get("null_reason") for m in nulls])
        return w

    values = [points[m]["value"] for m in months]
    net = values[-1] / values[0] - 1
    monthly = [values[i] / values[i - 1] - 1 for i in range(1, len(values))]
    mean = sum(monthly, Decimal(0)) / len(monthly)
    var = sum(((r - mean) ** 2 for r in monthly), Decimal(0)) / (len(monthly) - 1)
    vol = var.sqrt() * SQRT12
    dd, peak_i, trough_i = _max_drawdown(values)

    w = _empty_window(None, None)
    w.update(
        status=EVALUATED,
        status_label=STATUS_LABELS[EVALUATED],
        base_month=iso(months[0]),
        end_month=iso(months[-1]),
        base_date=iso(points[months[0]]["date"]),
        end_date=iso(points[months[-1]]["date"]),
        base_value=ratio(values[0], 8),
        end_value=ratio(values[-1], 8),
        n_observations=len(monthly),
        net_return_pct=ratio(net * 100, 6),
        volatility_annual_pct=ratio(vol * 100, 6),
        volatility_note=vol_note,
        max_drawdown_pct=ratio(-dd * 100, 6),
        max_drawdown_peak_month=iso(months[peak_i]) if dd > 0 else None,
        max_drawdown_trough_month=iso(months[trough_i]) if dd > 0 else None,
        notes=[NOTE_SIX_MONTHS] if n == 6 else [],
        sources=[call.src(points[months[-1]]["date"] or months[-1])] if call else [],
    )

    # CDI over the same dates: a fund's are the CDI calendar's month-ends, a ticker's are its sessions.
    cdi_period: Decimal | None = None
    if basis == FUND:
        c_start, c_end = cdi.month_end(months[0]), cdi.month_end(months[-1])
    else:
        c_start, c_end = points[months[0]]["date"], points[months[-1]]["date"]
    if cdi.error_code:
        w["cdi_reason_code"] = "cdi_indisponivel"
    elif c_start is None or c_end is None:
        w["cdi_reason_code"] = "cdi_indisponivel"
    else:
        c, k = cdi.compound(c_start, c_end)
        if c is None:
            w["cdi_reason_code"] = "cdi_indisponivel"
        else:
            w.update(cdi_pct=ratio(c * 100, 6), cdi_base_date=iso(c_start), cdi_end_date=iso(c_end), cdi_n_rates=k,
                     net_minus_cdi_pp=ratio((net - c) * 100, 6))
            if cdi.call:
                w["sources"].append(cdi.call.src(c_end))
            cdi_period = c

    # engine 1.13 (#606 Q36): "% do CDI" only for a fund whose own filed benchmark is CDI or DI
    if bench is not None:
        w["cdi_like"] = bool(bench.get("cdi_like"))
        if not bench.get("cdi_like"):
            w["pct_of_cdi_reason_code"] = bench.get("reason_code")
        elif cdi_period is None:
            w["pct_of_cdi_reason_code"] = "cdi_indisponivel"
        elif cdi_period <= 0:
            w["pct_of_cdi_reason_code"] = PCT_CDI_NOT_POSITIVE
        else:
            w["pct_of_cdi"] = ratio(net / cdi_period * 100, 4)
            w["sources"].extend(bench.get("sources") or [])

    # The fee's weight: from the fee block's headline only.
    w["fee_status"] = fee["status"]
    w["fee_reason_code"] = fee["reason_code"]
    rate = dec(fee.get("rate_pct_year")) if fee["status"] == "ok" else None
    if rate is not None:
        fee_period = rate / 100 * frac
        gross = net + fee_period
        w.update(fee_pct_period=ratio(fee_period * 100, 6), gross_return_est_pct=ratio(gross * 100, 6))
        w["sources"].extend(fee["sources"])
        if gross == 0:
            w.update(fee_per_point=None, fee_per_point_excluded_from_aggregates=True,
                     fee_per_point_note="retorno bruto estimado zero: taxa por ponto indefinida")
        else:
            w.update(fee_per_point=ratio(fee_period / gross, 6), fee_per_point_excluded_from_aggregates=gross < 0,
                     fee_per_point_note=NOTE_FEE_PER_POINT_NEGATIVE if gross < 0 else NOTE_FEE_PER_POINT)
        if vol >= SHARPE_MIN_VOL:
            w.update(sharpe_drag=ratio(rate / 100 / vol, 4), sharpe_drag_note=NOTE_SHARPE)
        else:
            w.update(sharpe_drag=None, sharpe_drag_note=NOTE_SHARPE_LOW_VOL)
    return w


def _max_drawdown(values: list[Decimal]) -> tuple[Decimal, int, int]:
    """Largest fall from a month-end to a later one, as a positive fraction, with the peak and trough indexes."""
    best, peak_i, trough_i = Decimal(0), 0, 0
    run_peak_i = 0
    for i, v in enumerate(values):
        if v > values[run_peak_i]:
            run_peak_i = i
        fall = 1 - v / values[run_peak_i]
        if fall > best:
            best, peak_i, trough_i = fall, run_peak_i, i
    return best, peak_i, trough_i

