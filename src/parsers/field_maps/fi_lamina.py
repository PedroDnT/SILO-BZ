"""FI lamina (CVM fi-doc-lamina) field map.

Source CSV: lamina_fi_{year}{month:02d}.csv, the main member of
lamina_fi_{year}{month:02d}.zip (latin-1, ';'-delimited, 78 columns).
Target table: cvm_fi_lamina.

Read from the real files, not guessed: the dictionary meta_lamina_fi.txt and the
headers of lamina_fi_202608.csv and lamina_fi_202409.csv, printed by the
read-only probe `.github/workflows/lamina_header_probe.yml` (run 37084697408,
2026-10-03 UTC). The header is identical in both files.

Natural key, measured by the same probe:
  * (CNPJ_FUNDO_CLASSE, DT_COMPTC, ID_SUBCLASSE) is unique in 2026-08 (1,051 rows).
    Without ID_SUBCLASSE the pair collides once (1,050 distinct for 1,051 rows).
  * ID_SUBCLASSE is empty on 1,048 of the 1,051 rows, so it is a NULL key column
    (the table's unique key is NULLS NOT DISTINCT) and is never filled with a
    placeholder.
  * In 2024-09 the three-column key still collides once (5,605 distinct for 5,606
    rows). Both rows are the same fund and month; the ingest keeps the last one
    and logs the collision.

Units. The dictionary states none for the fee columns. TAXA_ADM, TAXA_ADM_MIN,
TAXA_ADM_MAX, TAXA_ENTR, TAXA_SAIDA and PR_PL_DESPESA are numeric(14,6); the
2026-08 sample reads as percent per year (TAXA_ADM 0.5 next to TAXA_ADM_OBS
"0,5% do patrimônio líquido ao ano"). The column comments say "as filed".

TAXA_PERFM is TEXT in the source (varchar 500: "Não há", "20,00% do que exceder
100,00% do CDI.", a paragraph). It stays text. No number is parsed out of it.

Only the columns the diagnosis needs are typed. The rest (the prose columns
OBJETIVO, POLIT_INVEST, the *_EXEMPLO figures, the 5-year return block, contact
columns) fall through to the residual `raw`.
"""

TABLE = "cvm_fi_lamina"
# id_subclasse is NULL for most rows; the constraint is UNIQUE NULLS NOT DISTINCT
# (migration 65), so this ON CONFLICT column list resolves to it.
CONFLICT = ("cnpj", "dt_comptc", "id_subclasse")

FIELD_MAP = {
    # ---- natural key -------------------------------------------------------
    "cnpj":         (["CNPJ_FUNDO_CLASSE"],  "cnpj"),
    "dt_comptc":    (["DT_COMPTC"],          "date"),
    "id_subclasse": (["ID_SUBCLASSE"],       "text"),

    # ---- identity ----------------------------------------------------------
    "tp_fundo_classe": (["TP_FUNDO_CLASSE"], "text"),
    "denom_social":    (["DENOM_SOCIAL"],    "text"),
    "nm_fantasia":     (["NM_FANTASIA"],     "text"),
    "publico_alvo":    (["PUBLICO_ALVO"],    "text"),
    "indice_refer":    (["INDICE_REFER"],    "text"),
    "classe_risco_admin": (["CLASSE_RISCO_ADMIN"], "numeric"),
    "vl_patrim_liq":   (["VL_PATRIM_LIQ"],   "numeric"),

    # ---- fees --------------------------------------------------------------
    "tp_taxa_adm":  (["TP_TAXA_ADM"],  "text"),       # Fixa | Variável
    "taxa_adm":     (["TAXA_ADM"],     "numeric"),
    "taxa_adm_min": (["TAXA_ADM_MIN"], "numeric"),
    "taxa_adm_max": (["TAXA_ADM_MAX"], "numeric"),
    "taxa_adm_obs": (["TAXA_ADM_OBS"], "text"),
    "taxa_perfm":   (["TAXA_PERFM"],   "text"),       # text in the source: never coerced
    "taxa_entr":    (["TAXA_ENTR"],    "numeric"),
    "condic_entr":  (["CONDIC_ENTR"],  "text"),
    "taxa_saida":   (["TAXA_SAIDA"],   "numeric"),
    "qt_dia_saida": (["QT_DIA_SAIDA"], "numeric"),
    "condic_saida": (["CONDIC_SAIDA"], "text"),
    "pr_pl_despesa": (["PR_PL_DESPESA"], "numeric"),  # expenses paid, % of average daily NAV
    "dt_ini_despesa": (["DT_INI_DESPESA"], "date"),
    "dt_fim_despesa": (["DT_FIM_DESPESA"], "date"),

    # ---- minimums ----------------------------------------------------------
    "invest_inicial_min": (["INVEST_INICIAL_MIN"], "numeric"),
    "invest_adic":        (["INVEST_ADIC"],        "numeric"),
    "resgate_min":        (["RESGATE_MIN"],        "numeric"),
    "vl_min_perman":      (["VL_MIN_PERMAN"],      "numeric"),

    # ---- redemption terms --------------------------------------------------
    "hora_aplic_resgate":  (["HORA_APLIC_RESGATE"], "text"),
    "qt_dia_caren":        (["QT_DIA_CAREN"],       "numeric"),
    "condic_caren":        (["CONDIC_CAREN"],       "text"),
    "conversao_cota_compra":        (["CONVERSAO_COTA_COMPRA"],        "text"),
    "qt_dia_conversao_cota_compra": (["QT_DIA_CONVERSAO_COTA_COMPRA"], "numeric"),
    "conversao_cota_canc":          (["CONVERSAO_COTA_CANC"],          "text"),
    "qt_dia_conversao_cota_resgate": (["QT_DIA_CONVERSAO_COTA_RESGATE"], "numeric"),
    "tp_dia_pagto_resgate": (["TP_DIA_PAGTO_RESGATE"], "text"),  # Dias Úteis | Dias Corridos
    "qt_dia_pagto_resgate": (["QT_DIA_PAGTO_RESGATE"], "numeric"),
}
