"""Reader text the report derives from the engine's codes and values (engine 2.0).

Until engine 1.15 the return, tax and market-equivalent blocks wrote this text into the engine JSON
(``status_label``, ``basis_label``, ``gross_label``, ``rate_text``, ``pl_label``, ``*_band_label``...). It is
presentation, not computation: since 2.0 the engine writes only the codes and figures, and ``adapt`` adds the text
here, at the same view paths, so the renderer and the Redator's placeholders read it where they always did. A
wording change is a change to this file alone. The text is the engine's as it was, word for word.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

# Returns (engine 1.10): the status of a line or a window, the series a return is read from, the gross estimate.
RETURN_STATUS = {"avaliado": "avaliado", "nao_avaliado": "não avaliado"}
RETURN_BASIS = {
    "cota_fundo": "cota mensal do fundo (fund_nav): líquida das taxas do fundo, bruta de IR",
    "close_total_return": "fechamento com dividendos e JCP reinvestidos (close_total_return); JCP bruto de IR",
    "close_sem_proventos": "fechamento sem proventos (close): variação de preço",
    "last_price_etf_renda_fixa": "último preço do arquivo consolidado da B3 (last_price), sem proventos",
    "curva_securitizadora": "valor na curva informado pela securitizadora (informe mensal à CVM); não é preço de mercado",
    "debenture_fundos_mediana": "marcação mediana mensal dos fundos (CDA bloco 4); sem fluxo de cupom ou amortização",
}
RETURN_METHOD = {
    "cota_fundo": "Cota do fundo",
    "close_total_return": "Preço com proventos",
    "close_sem_proventos": "Preço sem proventos",
    "last_price_etf_renda_fixa": "Último preço B3",
    "curva_securitizadora": "A · Curva da securitizadora",
    "debenture_fundos_mediana": "B · Mediana dos fundos",
}
GROSS_LABEL = "estimativa"

# Market equivalent (engine 1.13): the third-party PL and fee, and where a return sits in its class distribution.
EQUIVALENT_PL = "patrimônio líquido do site etfsbrasil.com.br (fonte de terceiros), não um documento da CVM"
EQUIVALENT_FEE = ("taxa de administração do site etfsbrasil.com.br (fonte de terceiros), a mesma fonte das taxas de ETF "
                  "na comparação de taxas; não é taxa divulgada à CVM")
BANDS = {
    "abaixo_p25": "abaixo do p25 da classe",
    "p25_mediana": "entre o p25 e a mediana da classe",
    "mediana_p75": "entre a mediana e o p75 da classe",
    "acima_p75": "acima do p75 da classe",
}

# Tax (engine 1.11): the status of a line's tax, the exemption, and the pension plan's fixed sentences.
EXEMPT = "isento"
TAX_STATUS = {
    "sem_regra": "sem regra",
    "previdencia": "dois regimes, nenhum indicado",
    "isento": EXEMPT,
    "faixa": "a conferir",
    "condicional": "a conferir",
    "candidatos": "a conferir",
    "aliquota_hoje": "alíquota de hoje",
}
PENSION_REGIME = "opção do participante; não informada"
PENSION_BASE = "PGBL: o imposto incide sobre o valor total do resgate. VGBL: só sobre o rendimento."
PENSION_IRREVOCABLE = (
    "A opção pelo regime regressivo ou progressivo pode ser exercida até o primeiro benefício ou resgate e é "
    "irretratável (Lei 11.053, art. 1º §6º). O relatório mostra os dois regimes e não indica nenhum."
)


def pct_text(rate_pct: Any) -> str | None:
    """22.5 -> '22,5%'; 20.0 -> '20%' (a rate in percent, in the form the law prints it). None stays None."""
    if rate_pct is None:
        return None
    return format(Decimal(str(rate_pct)).normalize(), "f").replace(".", ",") + "%"


def tax_rate_text(tax: dict) -> str | None:
    """The rate in force as text: "isento" for an exemption, the rate of today, or None (a bracket, no rule)."""
    if tax.get("status") == "isento":
        return EXEMPT
    return pct_text(tax.get("rate_today_pct"))


def tax_instrument_label(tax: dict) -> str | None:
    """The rule file's label of the one instrument the line was taxed as (the candidate of that instrument)."""
    if not tax.get("instrument"):
        return None
    return next((c.get("label") for c in tax.get("candidates") or [] if c.get("instrument") == tax["instrument"]), None)
