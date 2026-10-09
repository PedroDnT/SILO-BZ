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
* a CRA or CRI identified in the CVM register (schema 2.1, #766, method A): the securitizer's value on the curve,
  ``portfolio_credit_returns``, one call for every such line: month factor (PU + paid) / previous PU, a month with a
  flag (not filed, repeated value, a fall with no payment filed, quantity changed...) makes the window "não avaliado";
* a CDB, LCI, LCA or CDCA (schema 2.1, method C): no measured return; the rate the statement prints, applied to the
  CDI or IPCA of the window, is the "retorno contratado" in ``contracted``, apart from every measured figure and total;
* everything else (Tesouro, debênture, a FIDC with no known tranche, a FIP, cash, an unidentified line): "não
  avaliado" with a fixed reason code.

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
import re
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Any

from src.portfolio import benchmark, contracted
from src.portfolio.client import SiloClient
from src.portfolio.contracted import compute_contracted
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
CURVE = "curva_securitizadora"  # schema 2.1 (#766), method A
CONTRACTED = "retorno_contratado"  # schema 2.1 (#766), method C: never a line's basis, only its ``contracted`` block
# A month-end value whose day is not served: the CDI dates are the CDI calendar's month-ends.
MONTH_BASES = (FUND, CURVE)
# The reader text of a status or a basis is the report's (src/portfolio/report/labels.py, engine 2.0).
TOOLS = {
    FUND: "fund_nav",
    TOTAL_RETURN: "quote_history",
    CLOSE: "quote_history",
    FIXED_INCOME_ETF: "trade_consolidated_history",
    CURVE: "portfolio_credit_returns",
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
    "CDB": "retorno_contratado_anexo",
    "LCI": "retorno_contratado_anexo",
    "LCA": "retorno_contratado_anexo",
    "debênture": "retorno_debenture_metodo_pendente",
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
    "retorno_contratado_anexo": "crédito bancário sem série de preços: o retorno contratado está no anexo",
    "retorno_debenture_metodo_pendente": "debênture: método pendente (meses de cupom na marcação dos fundos)",
}
# schema 2.1 (#766): the month flags of portfolio_credit_returns, as a window's reason code ('mes_ausente' is the
# existing 'serie_incompleta')
CURVE_FLAGS = ("serie_ambigua", "mes_ausente", "valor_invalido", "quantidade_mudou", "pu_repetido",
               "queda_sem_evento_arquivado", "pagamento_acima_do_pu", "pagamento_incompativel")
CURVE_REASONS = {
    "serie_ambigua": "mais de uma série ou classe para o código e nenhuma indicada",
    "valor_invalido": "quantidade ou valor não positivo no informe",
    "quantidade_mudou": "a quantidade de certificados mudou na janela",
    "pu_repetido": "o informe repete o valor do mês anterior",
    "queda_sem_evento_arquivado": "o valor na curva cai sem pagamento arquivado",
    "pagamento_acima_do_pu": "pagamento arquivado acima do valor do certificado",
    "pagamento_incompativel": "o retorno do mês de pagamento não é compatível com os meses sem evento",
}
NOTE_CURVE = (
    "Retorno na curva informada pela securitizadora (CVM, cvm_securit_serie): o valor unitário do mês mais os pagamentos "
    "do mês por certificado, sobre o valor unitário do mês anterior, composto. É o valor na curva, não preço de mercado; "
    "não mede risco de crédito nem marcação."
)
TAXA_NOT_CDI = "taxa_nao_cdi"
TAXA_NOT_FILED = "taxa_nao_informada"
# engine 1.13: why a window has no "% do CDI" (fixed Portuguese text in common.REASON_TEXT)
PCT_CDI_ONLY_FUNDS = "pct_cdi_so_fundos"
PCT_CDI_NOT_SERVED = "referencia_nao_servida"
PCT_CDI_NOT_POSITIVE = "cdi_nao_positivo"
NOTE_PCT_OF_CDI = (
    "% do CDI = retorno líquido dividido pelo CDI das mesmas datas, vezes 100; só para fundo cujo índice de referência "
    "arquivado (Extrato ou lâmina) é CDI ou DI, e só com CDI do período acima de zero"
)
# schema 2.1 (#766): direct credit
PCT_CDI_CREDIT_NOT_CDI = "credito_nao_cdi"
PCT_CDI_CREDIT_NO_RATE = "taxa_nao_informada"
NOTE_PCT_OF_CDI_CREDIT = (
    "Crédito direto: '% do CDI' só quando a taxa impressa no extrato contém CDI; para papel atrelado a IPCA ou "
    "prefixado, n/a, e a comparação é a diferença para o CDI em pontos percentuais"
)
NOTE_CURVE = (
    "Valor na curva informado pela securitizadora no informe mensal à CVM (cvm_securit_serie): PU = valor dos "
    "certificados / quantidade; juros e amortização pagos no mês somados ao PU do mês. Não é preço de mercado e não "
    "mostra evento de crédito que o informe não traga; bruto de IR."
)
NOTE_CURVE_COUPON = (
    "No mês do pagamento, o valor pago entra pelo valor de face, sem reinvestimento até o fim do mês: o retorno daquele "
    "mês fica um pouco abaixo do contratado."
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
    _curve_fetch(lines, client, end_month, cache, sec)  # schema 2.1: one call for every CRA / CRI line
    ipca = contracted.Ipca.fetch(lines, client, months, sec)  # schema 2.1: only when a contracted rate is on IPCA

    out = []
    for li in lines:
        rec = _line(li, fee_by.get(li.line_no), client, months, position_date, cdi, cache, sec)
        rec["contracted"] = contracted.compute(li, months, cdi, ipca)  # schema 2.1, method C; None when not eligible
        out.append(rec)

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
        # schema 2.1: the contracted return is never a measured return; its share is counted apart
        contr = [ln for ln in out if ln["contracted"] and ln["contracted"]["windows"][wid]["status"] == EVALUATED]
        contr_value = sum((Decimal(str(ln["valor_brl"])) for ln in contr), Decimal("0"))
        coverage[wid] = {
            "evaluated_value_brl": brl(covered),
            "coverage_portfolio_value_pct": pct(covered, portfolio_total),
            "n_evaluated": sum(ln["windows"][wid]["status"] == EVALUATED for ln in out),
            "contracted_value_brl": brl(contr_value),
            "contracted_coverage_portfolio_value_pct": pct(contr_value, portfolio_total),
            "n_contracted": len(contr),
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
        "pct_of_cdi_credit_note": NOTE_PCT_OF_CDI_CREDIT,  # schema 2.1
        "contracted_note": contracted.NOTE,  # schema 2.1
        "note": NOT_A_RECOMMENDATION,
        "cdi": cdi.as_dict(),
        "lines": out,
        "n_lines": len(out),
        "n_evaluated": sum(ln["status"] == EVALUATED for ln in out),
        "n_not_evaluated": sum(ln["status"] == NOT_EVALUATED for ln in out),
        "coverage": coverage,
        "contribution": _contribution(out, coverage, portfolio_total),  # engine 1.15
    }


# ---------------------------------------------------------------------------
# Retroactive contribution (engine 1.15)
# ---------------------------------------------------------------------------

CONTRIBUTION_LABEL = "contribuição retroativa"
# schema 2.1 (owner's rule, #766: never mix methods in a total): the securitizer's value on the curve is not a market
# value, so a CRA / CRI line is listed in excluded_lines and stays out of the sum
CONTRIBUTION_EXCLUDED = (CURVE,)
NOTE_CONTRIBUTION = (
    "Contribuição retroativa: o extrato dá as posições em uma data e nenhum fluxo. O valor no início da janela de cada "
    "linha é o valor atual dividido por 1 mais o retorno líquido da janela; o peso é esse valor sobre a soma dos valores "
    "iniciais das linhas avaliadas; a contribuição é o peso vezes o retorno. Supõe que não houve aporte nem resgate. A "
    "soma é o retorno só da parte avaliada, nunca da carteira inteira. CRA e CRI avaliados pelo valor na curva da "
    "securitizadora ficam fora da soma: não é valor de mercado, e métodos diferentes não se somam."
)


def _contribution(lines: list[dict[str, Any]], coverage: dict[str, Any],
                  portfolio_total: Decimal | None = None) -> dict[str, Any]:
    """Per window: each evaluated line's share of the return of the evaluated part, back-cast from today's values.

    start value = value / (1 + r); weight = start value / sum of the start values; contribution = weight x r. The sum of
    the contributions is the return of the evaluated lines taken together, exactly (sum of the end values over the sum
    of the start values, minus 1). Lines are in statement order; nothing is ranked."""
    out: dict[str, Any] = {}
    for wid, _n, _f, _note in WINDOWS:
        rows = []
        excluded = []
        for ln in lines:
            w = ln["windows"][wid]
            r, value = dec(w.get("net_return_pct")), dec(ln.get("valor_brl"))
            if w["status"] != EVALUATED or r is None or value is None or r <= Decimal(-100):
                continue
            if ln.get("basis") in CONTRIBUTION_EXCLUDED:  # schema 2.1: a value on the curve never enters a market total
                excluded.append({"line_no": ln["line_no"], "basis": ln.get("basis"), "reason_code": "metodo_fora_do_total"})
                continue
            rows.append((ln, value, r, value / (1 + r / 100)))
        start_total = sum((s for *_x, s in rows), Decimal("0"))
        end_total = sum((v for _l, v, _r, _s in rows), Decimal("0"))
        if not rows or start_total <= 0:
            out[wid] = {"status": NOT_EVALUATED, "reason_code": "linhas_sem_retorno", "covered_return_pct": None,
                        "n_lines": 0, "lines": [], "excluded_lines": excluded,
                        **_cov(coverage, wid, excluded, end_total, portfolio_total)}
            continue
        out[wid] = {
            "status": EVALUATED,
            "reason_code": None,
            "covered_return_pct": float(((end_total / start_total - 1) * 100).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
            "start_value_brl": brl(start_total),
            "end_value_brl": brl(end_total),
            "n_lines": len(rows),
            "excluded_lines": excluded,  # schema 2.1
            **_cov(coverage, wid, excluded, end_total, portfolio_total),
            "lines": [
                {
                    "line_no": ln["line_no"],
                    "linha_extrato": ln["linha_extrato"],
                    "valor_brl": ln["valor_brl"],
                    "net_return_pct": float(r),
                    "start_value_brl": brl(s),
                    "start_weight_pct": pct(s, start_total),
                    "contribution_pp": float((s / start_total * r).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
                }
                for ln, _v, r, s in rows
            ],
        }
    return {"label": CONTRIBUTION_LABEL, "note": NOTE_CONTRIBUTION, "windows": out}


def _cov(coverage: dict[str, Any], wid: str, excluded: list | None = None, summed: Decimal | None = None,
         portfolio_total: Decimal | None = None) -> dict[str, Any]:
    """The share of the portfolio the contribution covers: the block's coverage, or, when a line is left out of the
    sum (schema 2.1), only the value of the lines summed."""
    if excluded and portfolio_total:
        return {"coverage_portfolio_value_pct": pct(summed or Decimal("0"), portfolio_total)}
    return {"coverage_portfolio_value_pct": coverage[wid]["coverage_portfolio_value_pct"]}


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
    if tipo in ("CRA", "CRI"):  # schema 2.1 (#766), method A: the CVM register's series the identification matched
        credit = li.credit or {}
        if li.status != "identified" or credit.get("match_kind") != "securit_cetip" or not credit.get("code"):
            return None, "retorno_linha_nao_identificada"
        return CURVE, None
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
        if contracted.is_bank_credit(li.position):  # a CDCA the statement prints as such (schema 2.1)
            return None, "retorno_contratado_anexo"
        return None, "retorno_credito_sem_serie" if li.kind == "credito" else "retorno_sem_regra"
    return None, "retorno_sem_regra"


def _empty_window(code: str | None, reason: str | None) -> dict[str, Any]:
    return {
        "status": NOT_EVALUATED,
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
        "credit_code": (li.credit or {}).get("code") if basis == CURVE else None,  # schema 2.1: the CETIP code read
        "name": li.name,
        "valor_brl": brl(p.valor),
        "basis": basis,
        "without_distributions": basis in (CLOSE, FIXED_INCOME_ETF),
        "status": NOT_EVALUATED,
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
    bench = _credit_benchmark(p.taxa_texto) if basis == CURVE else _benchmark(basis, fee_line)
    rec["benchmark"] = bench
    rec["performance_fee_filed"] = bool(fee_line and _perf_filed(fee_line))
    if rec["performance_fee_filed"]:
        rec["notes"].append(NOTE_PERFORMANCE)

    if basis == CURVE:
        return _curve_line(rec, li, months, cdi, cache, fee, bench)
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
        rec["status"] = EVALUATED
    else:
        first = rec["windows"]["12m"]
        rec.update(reason_code=first["reason_code"], reason=first["reason"])
    return rec


def _no_benchmark(code: str) -> dict[str, Any]:
    return {"cdi_like": False, "reason_code": code, "extrato": None, "lamina": None, "lamina_n": None,
            "extrato_as_of": None, "lamina_as_of": None, "matched": [], "rule_version": None, "sources": []}


def _benchmark(basis: str, fee_line: dict[str, Any] | None) -> dict[str, Any]:
    """The filed benchmark the fee block read (catalog v68), classified by the versioned spelling list."""
    if basis == CURVE:
        return _no_benchmark(TAXA_NOT_FILED)  # replaced per window by _curve_bench, from the rate the securitizer filed
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
    if basis == CURVE:
        return [NOTE_CURVE, NOTE_CURVE_COUPON]
    if basis == FUND:
        return [NOTE_FUND, NOTE_FUND_DATES]
    if basis == CURVE:
        return [NOTE_CURVE]
    if basis == TOTAL_RETURN:
        return [NOTE_SHARE]
    if tipo == "FII":
        return [NOTE_FII]
    return [NOTE_ETF]


def _fee(li: LineId, basis: str, fee_line: dict[str, Any] | None) -> dict[str, Any]:
    """The administration fee the fee block already shows for the line; never fetched or estimated here."""
    if basis in (TOTAL_RETURN, CURVE):
        return {"status": "nao_se_aplica", "reason_code": "taxa_nao_aplicavel", "rate_pct_year": None, "kind": None,
                "origin": None, "as_of": None, "sources": []}
    if basis == CURVE:  # schema 2.1: a CRA / CRI has no administration fee; its spread is not published
        return {"status": "nao_se_aplica", "reason_code": "taxa_credito_sem_taxa_adm", "rate_pct_year": None,
                "kind": None, "origin": None, "as_of": None, "sources": []}
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
# Method A: CRA and CRI on the securitizer's curve (engine 2.1, #766)
# ---------------------------------------------------------------------------


def _curve_code(li: LineId) -> str:
    return (li.position.codigo or "").strip().upper()


def _fetch_curves(lines: list[LineId], client: SiloClient, months: list[dt.date], cache: dict, sec: Section) -> None:
    """One ``portfolio_credit_curve`` call for every CRA and CRI of the statement (split above 40 codes). The rows go
    to ``cache`` by code as (rows by month, call, error code); the lines read them, nothing is fetched per line."""
    codes = sorted({_curve_code(li) for li in lines if _route(li)[0] == CURVE})
    for i in range(0, len(codes), CURVE_MAX_CODES):
        chunk = codes[i:i + CURVE_MAX_CODES]
        args = {"p_codes": chunk, "p_from": months[0].isoformat(), "p_to": months[-1].isoformat()}
        call = call_tool(client, CURVE_TOOL, args, sec.errors)
        if not call.ok:
            sec.degrade(f"{CURVE_TOOL} falhou (erro literal em errors).", code="consulta_falhou")
            for c in chunk:
                cache[("curve", c)] = (None, call, "consulta_falhou")
            continue
        by_code: dict[str, dict[dt.date, dict]] = {c: {} for c in chunk}
        bad = False
        for r in call.rows or []:  # by line_no: the function returns the code normalized (CRA- stripped)
            m = as_date(r.get("month"))
            k = r.get("line_no")
            c = chunk[k - 1] if isinstance(k, int) and 1 <= k <= len(chunk) else None
            if m is None or c is None or m in by_code[c]:
                bad = True
                break
            by_code[c][m] = r
        for c in chunk:
            if bad or set(by_code[c]) != set(months):
                sec.degrade(f"{CURVE_TOOL} devolveu resposta inconsistente para {c}.", code="resposta_inconsistente")
                cache[("curve", c)] = (None, call, "resposta_inconsistente")
            else:
                cache[("curve", c)] = (by_code[c], call, None)


def _curve_line(rec: dict, li: LineId, fee: dict, months: list[dt.date], cdi: "_Cdi", cache: dict) -> dict:
    rows, call, err = cache.get(("curve", _curve_code(li)), (None, None, "consulta_falhou"))
    rec["code"] = _curve_code(li)
    if call is not None:
        rec["sources"].append(call.src(months[-1]))
    if rows is None:
        rec.update(reason_code=err, reason=REASONS[err])
        rec["windows"] = {wid: _empty_window(err, REASONS[err]) for wid, *_ in WINDOWS}
        return rec
    rec["month_ends"] = [
        {"month": iso(m), "date": None, "value": ratio(dec(rows[m].get("pu")), 8) if rows[m].get("pu") is not None else None,
         "null_reason": rows[m].get("month_flag")}
        for m in months
    ]
    for wid, n, frac, vol_note in WINDOWS:
        rec["windows"][wid] = _curve_window(months[-(n + 1):], n, frac, vol_note, rows, fee, cdi, call)
    if any(w["status"] == EVALUATED for w in rec["windows"].values()):
        rec["status"] = EVALUATED
    else:
        first = rec["windows"]["12m"]
        rec.update(reason_code=first["reason_code"], reason=first["reason"])
    return rec


BASE_MONTH_FLAGS = ("mes_ausente", "mais_de_uma_serie", "valor_nao_informado")


def _curve_bench(rows: dict[dt.date, dict], months: list[dt.date], call: Call) -> dict[str, Any]:
    """CDI-like only when the rate the securitizer filed names the CDI in every month of the window (#766: the text
    changes between months of one series, so every month is read)."""
    taxas = [rows[m].get("taxa_juros") for m in months]
    if any(not (t or "").strip() for t in taxas):
        b = _no_benchmark(TAXA_NOT_FILED)
    elif all("CDI" in t.upper() for t in taxas):
        b = {**_no_benchmark(None), "cdi_like": True}
    else:
        b = _no_benchmark(TAXA_NOT_CDI)
    b["taxa_juros_as_filed"] = taxas[-1]
    b["sources"] = [call.src(months[-1])]
    return b


def _curve_window(months: list[dt.date], n: int, frac: Decimal, vol_note: str, rows: dict[dt.date, dict],
                  fee: dict, cdi: "_Cdi", call: Call) -> dict[str, Any]:
    """The window from the function's factors: the base month needs a pu, every later month a factor. A flagged month
    makes the window not evaluated with that month's code; nothing is filled in."""
    base = rows[months[0]]
    unknown = [(months[0], base.get("month_flag"))] if base.get("month_flag") in BASE_MONTH_FLAGS or base.get("pu") is None else []
    unknown += [(m, rows[m].get("month_flag") or "mes_ausente") for m in months[1:] if rows[m].get("factor") is None]
    if unknown:
        code = "curva_" + unknown[0][1]
        w = _empty_window(code, REASONS.get(code, REASONS["serie_incompleta"]))
        w.update(base_month=iso(months[0]), end_month=iso(months[-1]),
                 unknown_months=[{"month": iso(m), "flag": f} for m, f in unknown])
        return w
    index, points = Decimal(1), {months[0]: {"date": None, "value": Decimal(1)}}
    for m in months[1:]:
        index *= dec(rows[m]["factor"])
        points[m] = {"date": None, "value": index}
    w = _window(months, n, frac, vol_note, points, CURVE, fee, cdi, call, _curve_bench(rows, months, call))
    w["notes"] = [NOTE_CURVE] + w["notes"]
    return w


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
# Method A: CRA / CRI on the securitizer's curve (schema 2.1, #766)
# ---------------------------------------------------------------------------

_CDI_IN_RATE = re.compile(r"(?<![A-Z])CDI(?![A-Z])")


def _credit_benchmark(taxa_texto: str | None) -> dict[str, Any]:
    """"% do CDI" for direct credit: only when the rate the statement prints contains CDI (owner, #766). The CVM
    register's free-text rate is never read for it: it changes spelling between months of one series."""
    if not taxa_texto or not str(taxa_texto).strip():
        code, like = PCT_CDI_CREDIT_NO_RATE, False
    else:
        like = bool(_CDI_IN_RATE.search(str(taxa_texto).upper()))
        code = None if like else PCT_CDI_CREDIT_NOT_CDI
    return {"cdi_like": like, "reason_code": code, "taxa_texto": taxa_texto, "source": "taxa impressa no extrato",
            "extrato": None, "lamina": None, "lamina_n": None, "extrato_as_of": None, "lamina_as_of": None,
            "matched": [], "rule_version": None, "sources": []}


def _curve_args(group: list[LineId], end_month: dt.date) -> dict[str, Any]:
    return {
        "p_codes": [str(li.credit["code"]) for li in group],
        "p_end_month": end_month.isoformat(),
        "p_series": [_int_or_none(li.credit.get("numero_serie")) for li in group],
        "p_classes": [li.credit.get("classe") for li in group],
    }


def _int_or_none(v: Any) -> int | None:
    try:
        return int(str(v).strip()) if v is not None and str(v).strip() else None
    except ValueError:
        return None


def _curve_fetch(lines: list[LineId], client: SiloClient, end_month: dt.date, cache: dict, sec: Section) -> None:
    """One ``portfolio_credit_returns`` call for every CRA / CRI line (at most 70 per call: one page)."""
    group = [li for li in lines if _route(li)[0] == CURVE]
    for i in range(0, len(group), 70):
        part = group[i:i + 70]
        args = _curve_args(part, end_month)
        call = call_tool(client, TOOLS[CURVE], args, sec.errors)
        if not call.ok:
            sec.degrade(f"{TOOLS[CURVE]} falhou para as linhas de CRA e CRI (erro literal em errors).", code="consulta_falhou")
        by_line: dict[int, list[dict]] = {}
        bad = not call.ok
        for r in call.rows or []:
            k = r.get("line_no")
            if not isinstance(k, int) or not 1 <= k <= len(part):
                bad = True
                break
            by_line.setdefault(k, []).append(r)
        if call.ok and bad:
            sec.degrade(f"{TOOLS[CURVE]} devolveu resposta inconsistente.", code="resposta_inconsistente")
        for k, li in enumerate(part, start=1):
            err = "consulta_falhou" if not call.ok else ("resposta_inconsistente" if bad else None)
            cache[("curve", li.line_no)] = (by_line.get(k, []), call, err)


def _curve_line(rec: dict[str, Any], li: LineId, months: list[dt.date], cdi: _Cdi, cache: dict,
                fee: dict[str, Any], bench: dict[str, Any]) -> dict[str, Any]:
    rows, call, err = cache.get(("curve", li.line_no), ([], None, "consulta_falhou"))
    if call is not None:
        rec["sources"].append(call.src(months[-1]))
    by_month: dict[dt.date, dict] = {}
    for r in rows:
        m = as_date(r.get("month"))
        if err is None and (m is None or m in by_month or m not in months
                            or str(r.get("code") or "").upper() != str(li.credit.get("code") or "").upper()):
            err = "resposta_inconsistente"
        if m is not None:
            by_month[m] = r
    if err is None and set(by_month) != set(months):
        err = "resposta_inconsistente"
    if err is not None:
        rec.update(reason_code=err, reason=REASONS[err])
        rec["windows"] = {wid: _empty_window(err, REASONS[err]) for wid, *_ in WINDOWS}
        return rec
    rec["month_ends"] = [
        {"month": iso(m), "date": None, "value": ratio(dec(by_month[m].get("pu")), 8) if dec(by_month[m].get("pu")) else None,
         "null_reason": None, "data_referencia": by_month[m].get("data_referencia"),
         "paid_per_unit": ratio(dec(by_month[m].get("paid_per_unit")), 8) if dec(by_month[m].get("paid_per_unit")) is not None else None,
         "factor": ratio(dec(by_month[m].get("factor")), 12) if dec(by_month[m].get("factor")) is not None else None,
         "month_flag": by_month[m].get("month_flag"), "taxa_juros": by_month[m].get("taxa_juros")}
        for m in months
    ]
    rec["series"] = {"numero_serie": by_month[months[-1]].get("numero_serie"), "classe": by_month[months[-1]].get("classe"),
                     "reason": by_month[months[-1]].get("reason")}
    for wid, n, frac, vol_note in WINDOWS:
        wm = months[-(n + 1):]
        flags = _curve_flags(wm, by_month)
        if flags:
            code = "serie_incompleta" if flags[0]["flag"] == "mes_ausente" else flags[0]["flag"]
            w = _empty_window(code, CURVE_REASONS.get(code) or REASONS["serie_incompleta"])
            w.update(base_month=iso(wm[0]), end_month=iso(wm[-1]), month_flags=flags,
                     missing_months=[f["month"] for f in flags if f["flag"] == "mes_ausente"])
            rec["windows"][wid] = w
            continue
        # the index of the window: 1 at its base month, times each month's factor
        points: dict[dt.date, dict[str, Any]] = {}
        idx = Decimal(1)
        for i, m in enumerate(wm):
            if i:
                idx *= dec(by_month[m]["factor"])
            points[m] = {"date": None, "value": idx}
        w = _window(wm, n, frac, vol_note, points, CURVE, fee, cdi, call, bench)
        w["month_flags"] = []
        rec["windows"][wid] = w
    if any(w["status"] == EVALUATED for w in rec["windows"].values()):
        rec["status"] = EVALUATED
    else:
        first = rec["windows"]["12m"]
        rec.update(reason_code=first["reason_code"], reason=first["reason"])
    return rec


def _curve_flags(wm: list[dt.date], by_month: dict[dt.date, dict]) -> list[dict[str, Any]]:
    """The months that make a window unknown: the base month only by its own value; every later month by its flag
    (the SQL compares it with the month before) or a missing factor."""
    out = []
    base = by_month[wm[0]]
    base_flag = base.get("month_flag")
    if base_flag in ("serie_ambigua", "mes_ausente", "valor_invalido") or dec(base.get("pu")) is None:
        out.append({"month": iso(wm[0]), "flag": base_flag or "valor_invalido"})
    for m in wm[1:]:
        r = by_month[m]
        flag = r.get("month_flag")
        if flag is None and dec(r.get("factor")) is None:
            flag = "valor_invalido"
        if flag is not None:
            out.append({"month": iso(m), "flag": flag if flag in CURVE_FLAGS else "valor_invalido"})
    return out


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
    if basis in MONTH_BASES:
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

