"""SECURIT monthly emissions field map (cra_mensal, cri_mensal, ots_mensal).

Source CSV: inf_mensal_cra_ativo_passivo_{year}.csv |
            inf_mensal_cri_ativo_passivo_{year}.csv |
            inf_mensal_ots_ativo_passivo_{year}.csv (members of the yearly ZIPs).
Target table: cvm_securit_mensal.

instrument_type and period_year are injected by the ingest module, and so is
`occurrence` (see ingest_securit._number_occurrences).

Header audit (real 2019, 2022 and 2026 files, dados.cvm.gov.br), migration 52:
  * One row is one monthly report of one certificate:
    (Codigo_Identificacao_Certificado, Data_Referencia). The old key had no
    certificate at all, so reports sharing a month and an issue value collapsed
    (2026: 347 CRA, 575 CRI, 2 OTS rows lost). Issue #349.
  * The securitizer is `CNPJ_Emissora` on CRA/CRI and `CNPJ_Securitizadora` on
    OTS. Only the second was a candidate, so cnpj_securit was NULL on every
    CRA/CRI row. Issue #350. It stays out of the key: in every file measured a
    certificate-month names one securitizer, and certificates do change
    securitizer over the years (318 CRI codes), which is an attribute, not a
    new document.
  * Versao is stored, not keyed. Each yearly file carries one version of each
    report, so keying on it would keep a restated v1 beside its v2.
  * dt_emissao holds Data_Referencia, the report month (a legacy name).
  * The report has no maturity column in any layout, so dt_vencto stays NULL.
    Series maturity is cvm_securit_serie.data_vencimento.
"""

TABLE = "cvm_securit_mensal"
# One report per certificate-month. `occurrence` numbers the reports CVM files
# twice for the same certificate-month with different values (OTS 2026: 1).
GROUP = ("instrument_type", "codigo_identificacao", "dt_emissao")
CONFLICT = GROUP + ("occurrence",)

FIELD_MAP = {
    "cnpj_securit":         (["CNPJ_Emissora", "CNPJ_Securitizadora", "CNPJ_securit",
                              "CNPJ_FUNDO", "CNPJ"],                                     "cnpj"),
    "codigo_identificacao": (["Codigo_Identificacao_Certificado"],                       "text"),
    "versao":               (["Versao"],                                                  "int"),
    "dt_emissao":           (["Data_Referencia", "DT_EMISSAO"],                           "date"),
    "dt_vencto":            (["DT_VENCTO", "DT_VENCIMENTO"],                              "date"),
    "vl_emissao":           (["Valor_Atualizado_Emissao", "VL_EMISSAO"],                  "numeric"),
    "vl_unit":              (["VL_UNIT", "PU_EMISSAO", "VL_PU_EMISSAO"],                  "numeric"),
    "qt_titulos":           (["QT_TITULOS"],                                              "numeric"),
    "vl_total":             (["Ativo", "VL_TOTAL"],                                       "numeric"),
    "tp_ativo":             (["TP_ATIVO"],                                                "text"),
}
