"""FII inf_mensal — COMPLEMENTO subtype field map (key metrics + cotistas breakdown).

Source CSV: inf_mensal_fii_complemento_{year}.csv (latin-1, ';'-delimited).
Target table: cvm_fii_mensal, discriminated by doc_subtype='complemento'.

This subtype carries the headline financial metrics (PL, asset value, quota value,
returns, dividend yield) — i.e. most of what cvm_fii_mensal's typed columns were
made for.  The cotistas-by-investor-type breakdown remains in residual `raw`
unless the UI needs it typed.
"""

TABLE = "cvm_fii_mensal"
DOC_SUBTYPE = "complemento"
CONFLICT = ("cnpj", "period", "doc_subtype")

FIELD_MAP = {
    "cnpj":                   (["CNPJ_Fundo_Classe", "CNPJ_FUNDO_CLASSE"],                    "cnpj"),
    "period":                 (["Data_Referencia", "DT_COMPTC"],                              "date"),
    "vl_patrim_liq":          (["Patrimonio_Liquido", "VL_PATRIM_LIQ"],                       "numeric"),
    "vl_ativo":               (["Valor_Ativo"],                                               "numeric"),
    "cotas_emitidas":         (["Cotas_Emitidas"],                                            "numeric"),
    "vl_patrimonial_cotas":   (["Valor_Patrimonial_Cotas"],                                   "numeric"),
    "nr_cotst":               (["Total_Numero_Cotistas"],                                     "int"),
    "pct_rentab_efetiva_mes": (["Percentual_Rentabilidade_Efetiva_Mes"],                      "pct"),
    "pct_rentab_patrimonial": (["Percentual_Rentabilidade_Patrimonial_Mes"],                  "pct"),
    "pct_dividend_yield_mes": (["Percentual_Dividend_Yield_Mes"],                             "pct"),
    "pct_amortizacao_mes":    (["Percentual_Amortizacao_Cotas_Mes"],                          "pct"),
    # Cotistas-by-type columns remain in residual raw.
}
