"""FIDC tranche-level characteristics field map.

Source CSVs: tab_X_2 (quota quantity/value) joined with tab_X_3 (returns) and
tab_X_6 (performance).  The ingest_fidc module does the three-way join before
calling apply_map; the combined row is treated as a single source dict.
Target table: cvm_fidc_tranche.
"""

TABLE = "cvm_fidc_tranche"
CONFLICT = ("cnpj", "period", "classe_serie")

FIELD_MAP = {
    "cnpj":               (["CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"],  "cnpj"),
    "period":             (["DT_COMPTC"],                         "date"),
    "classe_serie":       (["TAB_X_CLASSE_SERIE"],                "text"),
    "qt_cota":            (["TAB_X_QT_COTA"],                     "numeric"),
    "vl_cota":            (["TAB_X_VL_COTA"],                     "numeric"),
    "vl_rentab_mes":      (["TAB_X_VL_RENTAB_MES"],               "numeric"),
    "pr_desemp_esperado": (["TAB_X_PR_DESEMP_ESPERADO"],          "numeric"),
    "pr_desemp_real":     (["TAB_X_PR_DESEMP_REAL"],              "numeric"),
}
