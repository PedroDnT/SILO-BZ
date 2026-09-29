"""SECURIT per-series status, rating and yield field map (classe CSV).

Source CSV: inf_cra_classe_{year}.csv | inf_cri_classe_{year}.csv |
            inf_ots_classe_{year}.csv (yearly ZIPs).
Target table: cvm_securit_serie.

instrument_type is injected by the ingest module (_resolve_securit_instrument_type),
and so is `occurrence` (see ingest_securit._number_occurrences).
codigo_identificacao is the primary security identifier (certificate code or CNPJ_Fundo
depending on year/instrument).

Header audit (real 2019, 2022 and 2026 files, dados.cvm.gov.br), migration 52:
  * One row is one series of one certificate in one monthly report. The old key
    (instrument_type, cnpj_securit, codigo_identificacao, data_referencia,
    numero_serie) had no Classe, so a senior and a subordinated class sharing a
    series number collapsed (2026: 10 CRA, 185 CRI, 211 OTS rows lost). #349.
  * Even with Classe, CVM files several different rows for one series and
    class (2026: 66 CRI and 33 OTS groups, up to 16 rows), and no column tells
    them apart. `occurrence` numbers them, ordered by content. Byte-identical
    repeats (CRI 2026: 54) are the same series filed twice and are kept once.
  * The securitizer is `CNPJ_Emissora` on CRA/CRI, which no candidate named, so
    cnpj_securit was NULL on every CRA/CRI row (#350). It is an attribute, not
    part of the key, for the reason securit_mensal gives.
  * Versao is stored, not keyed: each yearly file carries one version.
"""

TABLE = "cvm_securit_serie"
GROUP = ("instrument_type", "codigo_identificacao", "data_referencia", "numero_serie", "classe")
CONFLICT = GROUP + ("occurrence",)

FIELD_MAP = {
    "cnpj_securit":              (["CNPJ_Emissora", "CNPJ_Securitizadora", "CNPJ_securit",
                                   "CNPJ_FUNDO", "CNPJ"],                                        "cnpj"),
    "codigo_identificacao":      (["Codigo_Identificacao_Certificado",
                                   "Codigo_Identificacao", "CNPJ_Fundo"],                        "text"),
    "data_referencia":           (["Data_Referencia", "DT_COMPETENCIA"],                         "date"),
    "versao":                    (["Versao"],                                                     "int"),
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
