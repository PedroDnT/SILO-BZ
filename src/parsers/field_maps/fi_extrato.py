"""FI Extrato das Informacoes (CVM fi-doc-extrato) field map.

Source CSV: extrato_fi.csv (the current file: the latest version of every fund
or class, one row per CNPJ, refreshed daily) and extrato_fi_YYYY.csv (every
version filed in a year, refreshed weekly). Both latin-1, ';'-delimited, 117
columns, the same header in extrato_fi.csv and the 2020..2026 yearly files.
Target table: cvm_fi_extrato.

Read from the real files, not guessed. The header, the file facts and the fill
rates were printed on a GitHub Actions runner on 2026-10-03 (UTC) by the
read-only probe of issue #524 (run 37090491647, branch research/extrato-coverage,
never merged); the types come from the dictionary
https://dados.cvm.gov.br/dados/FI/DOC/EXTRATO/META/meta_extrato_fi.txt. Facts
that shaped this map:

  * The header starts TP_FUNDO_CLASSE;CNPJ_FUNDO_CLASSE;DENOM_SOCIAL;DT_COMPTC;
    CONDOM;... and has 117 columns. There is no subclass column: a CVM 175 row is
    the CLASS, and a fee that differs by subclass cannot be seen.
  * The current file has 38,796 rows and 38,796 distinct CNPJ, CNPJ punctuated
    (##.###.###/####-##); `coerce("cnpj")` strips and zero-pads it.
  * The yearly files hold versions: in 2025, 10,399 CNPJ over 13,590 rows (up to
    20 rows per CNPJ). Whether (CNPJ, DT_COMPTC) is unique inside them was NOT
    measured; the ingest dedupes on it (last row in the file wins), counts the
    collapsed rows and logs them.
  * Decimals use '.', as in TAXA_ADM 0.300000, so `coerce("numeric")` is exact.
  * TAXA_SAIDA_PAGTO_RESGATE is S/N in the dictionary ("is there an exit fee on
    the payment of redemptions"), not a rate: it is text here.

Units. The dictionary states none. TAXA_ADM is decimal(15,6); the XML standard
behind the file says "% ao ano (base 252)" for investors that are not qualified,
and the median balancete estimate over TAXA_ADM is 0.994, so it reads as percent
per year. The column comments say "as filed".

TAXA_ADM is stored exactly as filed. 16.7% of the values are exactly 0 (read as
"not informed" by the API, not rewritten here) and 115 of 21,962 are above 5 with
a maximum of 14,638.38 (scale errors, rejected by the API, not clipped here). A
cell that is not a number (the standard lets a qualified-investor fund file free
text) is kept in raw['_unparsed'], never guessed.

Typed: the key, the identity, every fee and the redemption terms. The regulation
exposure limits (the 70 PR_*_MIN / PR_*_MAX columns), the derivative and
overseas flags, the prose columns (POLIT_INVEST, DISTRIB, PRAZO, COTA_EMISSAO,
COTA_PL) and VL_CUPOM fall through to the residual `raw`.
"""

TABLE = "cvm_fi_extrato"
# One row per fund or class and per DT_COMPTC (migration 66).
CONFLICT = ("cnpj", "dt_comptc")

FIELD_MAP = {
    # ---- natural key -------------------------------------------------------
    "cnpj":      (["CNPJ_FUNDO_CLASSE"], "cnpj"),
    "dt_comptc": (["DT_COMPTC"],         "date"),

    # ---- identity ----------------------------------------------------------
    "tp_fundo_classe": (["TP_FUNDO_CLASSE"], "text"),   # FI | CLASSES - FIF
    "denom_social":    (["DENOM_SOCIAL"],    "text"),
    "condom":          (["CONDOM"],          "text"),   # ABERTO | FECHADO
    "publico_alvo":    (["PUBLICO_ALVO"],    "text"),
    "reg_anbima":      (["REG_ANBIMA"],      "text"),   # S/N
    "classe_anbima":   (["CLASSE_ANBIMA"],   "text"),
    "fundo_cotas":     (["FUNDO_COTAS"],     "text"),   # S/N

    # ---- fees --------------------------------------------------------------
    "taxa_adm":          (["TAXA_ADM"],          "numeric"),  # as filed: 0 and >5 included
    "taxa_custodia_max": (["TAXA_CUSTODIA_MAX"], "numeric"),
    "existe_taxa_perfm": (["EXISTE_TAXA_PERFM"], "text"),     # S/N
    "taxa_perfm":        (["TAXA_PERFM"],        "numeric"),  # numeric here, text in the lamina
    "param_taxa_perfm":  (["PARAM_TAXA_PERFM"],  "text"),
    "pr_indice_refer_taxa_perfm": (["PR_INDICE_REFER_TAXA_PERFM"], "numeric"),
    "calc_taxa_perfm":   (["CALC_TAXA_PERFM"],   "text"),
    "inf_taxa_perfm":    (["INF_TAXA_PERFM"],    "text"),
    "existe_taxa_ingresso": (["EXISTE_TAXA_INGRESSO"], "text"),  # S/N
    "taxa_ingresso_real":   (["TAXA_INGRESSO_REAL"],   "numeric"),
    "taxa_ingresso_pr":     (["TAXA_INGRESSO_PR"],     "numeric"),
    "existe_taxa_saida":    (["EXISTE_TAXA_SAIDA"],    "text"),  # S/N
    "taxa_saida_real":      (["TAXA_SAIDA_REAL"],      "numeric"),
    "taxa_saida_pr":        (["TAXA_SAIDA_PR"],        "numeric"),
    "taxa_saida_pagto_resgate": (["TAXA_SAIDA_PAGTO_RESGATE"], "text"),  # S/N, not a rate

    # ---- terms -------------------------------------------------------------
    "aplic_min":              (["APLIC_MIN"],              "numeric"),
    "qt_dia_conversao_cota":  (["QT_DIA_CONVERSAO_COTA"],  "numeric"),  # business days
    "qt_dia_pagto_cota":      (["QT_DIA_PAGTO_COTA"],      "numeric"),  # business days
    "qt_dia_resgate_cotas":   (["QT_DIA_RESGATE_COTAS"],   "numeric"),  # lock-up days
    "qt_dia_pagto_resgate":   (["QT_DIA_PAGTO_RESGATE"],   "numeric"),
    "tp_dia_pagto_resgate":   (["TP_DIA_PAGTO_RESGATE"],   "text"),
}
