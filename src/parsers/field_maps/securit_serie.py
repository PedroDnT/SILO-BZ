"""SECURIT per-series status, rating and yield field map (classe CSV).

Source CSV: inf_cra_classe_{year}.csv | inf_cri_classe_{year}.csv |
            inf_ots_classe_{year}.csv (yearly ZIPs).
Target table: cvm_securit_serie.

instrument_type is injected by the ingest module (_resolve_securit_instrument_type).
codigo_identificacao is the primary security identifier (certificate code or CNPJ_Fundo
depending on year/instrument).
"""

TABLE = "cvm_securit_serie"
CONFLICT = ("instrument_type", "cnpj_securit", "codigo_identificacao", "data_referencia", "numero_serie")

FIELD_MAP = {
    "cnpj_securit":              (["CNPJ_Securitizadora", "CNPJ_securit", "CNPJ_FUNDO", "CNPJ"], "cnpj"),
    "codigo_identificacao":      (["Codigo_Identificacao_Certificado",
                                   "Codigo_Identificacao", "CNPJ_Fundo"],                        "text"),
    "data_referencia":           (["Data_Referencia", "DT_COMPETENCIA"],                         "date"),
    "classe":                    (["Classe"],                                                     "text"),
    "numero_serie":              (["Numero_Serie"],                                               "int"),
    "tipo_oferta":               (["Tipo_Oferta"],                                               "text"),
    "codigo_cetip":              (["Codigo_CETIP"],                                              "text"),
    "codigo_isin":               (["Codigo_ISIN"],                                               "text"),
    "data_vencimento":           (["Data_Vencimento"],                                           "date"),
    "situacao":                  (["Situacao"],                                                   "text"),
    "valor_total_integralizado": (["Valor_Total_Integralizado"],                                  "numeric"),
    "taxa_juros":                (["Taxa_Juros"],                                                 "text"),
    "pagamento_periodicidade":   (["Pagamento_Periodicidade"],                                    "text"),
    "quantidade_certificados":   (["Quantidade_Certificados"],                                    "numeric"),
    "valor_certificados":        (["Valor_Certificados"],                                         "numeric"),
    "rendimentos":               (["Rendimentos"],                                                "numeric"),
    "amortizacoes":              (["Amortizacoes"],                                               "numeric"),
    "rentabilidade":             (["Rentabilidade"],                                              "numeric"),
    "classificacao_risco_atual": (["Classificacao_Risco_Atual"],                                  "text"),
    "indice_subordinacao_minimo":(["Indice_Subordinacao_Minimo"],                                 "numeric"),
}
