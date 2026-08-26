"""SECURIT monthly cash flows by tranche field map (fluxo_caixa CSV).

Source CSV: inf_mensal_cra_fluxo_caixa_{year}.csv |
            inf_mensal_cri_fluxo_caixa_{year}.csv |
            inf_mensal_ots_fluxo_caixa_{year}.csv (yearly ZIPs).
Target table: cvm_securit_fluxo.

instrument_type is injected by the ingest module.

Header audit (real 2026 files, fetched from dados.cvm.gov.br):
  * The issuer CNPJ column is `CNPJ_Emissora` for CRA/CRI and
    `CNPJ_Securitizadora` for OTS — both are carried as candidates.
  * The certificate id ships as `Codigo_Identificacao_Certificado`, not the
    bare `Codigo_Identificacao` this map used to expect. That is the required
    key, so the whole dataset failed `assert_map_matches` and never landed a
    single row.
  * Principal legs are `..._Amortizacao_Principal`, not `..._Principal`.
  * Receivables are `Recebimentos_Direitos_Creditorios` on CRA and
    `Recebimentos_Creditos` on CRI/OTS.
Columns CVM ships that we do not model (Versao, Recebimentos_Alienacao_Caixa,
Aquisicao_*, Outros_*) fall through to the `raw` JSONB residual.
"""

TABLE = "cvm_securit_fluxo"
CONFLICT = ("instrument_type", "cnpj_securit", "codigo_identificacao", "data_referencia")

FIELD_MAP = {
    "cnpj_securit":                      (["CNPJ_Emissora", "CNPJ_Securitizadora",
                                           "CNPJ_securit", "CNPJ_FUNDO", "CNPJ"],               "cnpj"),
    "codigo_identificacao":              (["Codigo_Identificacao_Certificado",
                                           "Codigo_Identificacao"],                             "text"),
    "data_referencia":                   (["Data_Referencia", "DT_COMPETENCIA"],                "date"),
    "recebimentos_direitos_creditorios": (["Recebimentos_Direitos_Creditorios",
                                           "Recebimentos_Creditos"],                            "numeric"),
    "pagamentos_despesas":               (["Pagamentos_Despesas"],                              "numeric"),
    "pagamentos_classe_senior":          (["Pagamentos_Classe_Senior"],                         "numeric"),
    "pagamentos_senior_principal":       (["Pagamentos_Classe_Senior_Amortizacao_Principal",
                                           "Pagamentos_Classe_Senior_Principal",
                                           "Pagamentos_Senior_Principal"],                      "numeric"),
    "pagamentos_senior_juros":           (["Pagamentos_Classe_Senior_Juros",
                                           "Pagamentos_Senior_Juros"],                          "numeric"),
    "pagamentos_mezanino":               (["Pagamentos_Classe_Subordinada_Mezanino"],           "numeric"),
    "pagamentos_mezanino_principal":     (["Pagamentos_Classe_Subordinada_Mezanino_Amortizacao_Principal",
                                           "Pagamentos_Classe_Subordinada_Mezanino_Principal"], "numeric"),
    "pagamentos_mezanino_juros":         (["Pagamentos_Classe_Subordinada_Mezanino_Juros"],     "numeric"),
    "pagamentos_junior":                 (["Pagamentos_Classe_Subordinada_Junior"],             "numeric"),
    "pagamentos_junior_principal":       (["Pagamentos_Classe_Subordinada_Junior_Amortizacao_Principal",
                                           "Pagamentos_Classe_Subordinada_Junior_Principal"],   "numeric"),
    "pagamentos_junior_juros":           (["Pagamentos_Classe_Subordinada_Junior_Juros"],       "numeric"),
    "variacao_liquida_caixa":            (["Variacao_Liquida_Caixa"],                           "numeric"),
}
