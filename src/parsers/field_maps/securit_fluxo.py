"""SECURIT monthly cash flows by tranche field map (fluxo_caixa CSV).

Source CSV: inf_cra_fluxo_{year}.csv | inf_cri_fluxo_{year}.csv |
            inf_ots_fluxo_{year}.csv (yearly ZIPs).
Target table: cvm_securit_fluxo.

instrument_type is injected by the ingest module.
"""

TABLE = "cvm_securit_fluxo"
CONFLICT = ("instrument_type", "cnpj_securit", "codigo_identificacao", "data_referencia")

FIELD_MAP = {
    "cnpj_securit":                      (["CNPJ_Securitizadora", "CNPJ_securit",
                                           "CNPJ_FUNDO", "CNPJ"],                                "cnpj"),
    "codigo_identificacao":              (["Codigo_Identificacao", "CNPJ_Fundo"],                "text"),
    "data_referencia":                   (["Data_Referencia", "DT_COMPETENCIA"],                 "date"),
    "recebimentos_direitos_creditorios": (["Recebimentos_Direitos_Creditorios"],                  "numeric"),
    "pagamentos_despesas":               (["Pagamentos_Despesas"],                               "numeric"),
    "pagamentos_classe_senior":          (["Pagamentos_Classe_Senior"],                          "numeric"),
    "pagamentos_senior_principal":       (["Pagamentos_Classe_Senior_Principal",
                                           "Pagamentos_Senior_Principal"],                       "numeric"),
    "pagamentos_senior_juros":           (["Pagamentos_Classe_Senior_Juros",
                                           "Pagamentos_Senior_Juros"],                           "numeric"),
    "pagamentos_mezanino":               (["Pagamentos_Classe_Subordinada_Mezanino"],            "numeric"),
    "pagamentos_mezanino_principal":     (["Pagamentos_Classe_Subordinada_Mezanino_Principal"],  "numeric"),
    "pagamentos_mezanino_juros":         (["Pagamentos_Classe_Subordinada_Mezanino_Juros"],      "numeric"),
    "pagamentos_junior":                 (["Pagamentos_Classe_Subordinada_Junior"],              "numeric"),
    "pagamentos_junior_principal":       (["Pagamentos_Classe_Subordinada_Junior_Principal"],    "numeric"),
    "pagamentos_junior_juros":           (["Pagamentos_Classe_Subordinada_Junior_Juros"],        "numeric"),
    "variacao_liquida_caixa":            (["Variacao_Liquida_Caixa"],                            "numeric"),
}
