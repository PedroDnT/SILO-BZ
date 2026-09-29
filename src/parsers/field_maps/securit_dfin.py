"""SECURIT financial statements field map (dfin_cra, dfin_cri).

Source CSV: dfin_cra_{year}.csv | dfin_cri_{year}.csv (yearly CSV).
Target table: cvm_securit_dfin.

This dataset is a filing register: one row per certificate's statements, with
a link to the document. instrument_type and period_year are injected by the
ingest module, and so is `occurrence` (see ingest_securit._number_occurrences).
Everything not mapped here stays in the `raw` residual.

Header audit (real 2019, 2022 and 2026 files, dados.cvm.gov.br), migration 52:
  * One row is one certificate's statements for one reference date:
    (Codigo_Identificacao_Certificado, Data_Referencia), unique in every file
    measured. The old key (instrument_type, period_year, cnpj_securit) with a
    NULL CNPJ kept ONE row per year of each type (2026: 302 CRA and 933 CRI
    filings stored as 1 and 1). Issue #349.
  * The securitizer is `CNPJ_Emissora`, which no candidate named (#350). It is
    an attribute, not part of the key, for the reason securit_mensal gives.
  * Versao is stored, not keyed: each yearly file carries one version.
"""

TABLE = "cvm_securit_dfin"
GROUP = ("instrument_type", "codigo_identificacao", "data_referencia")
CONFLICT = GROUP + ("occurrence",)

FIELD_MAP = {
    "cnpj_securit":         (["CNPJ_Emissora", "CNPJ_Securitizadora", "CNPJ_securit",
                              "CNPJ_FUNDO", "CNPJ"],                                     "cnpj"),
    "codigo_identificacao": (["Codigo_Identificacao_Certificado"],                       "text"),
    "data_referencia":      (["Data_Referencia"],                                         "date"),
    "versao":               (["Versao"],                                                  "int"),
}
