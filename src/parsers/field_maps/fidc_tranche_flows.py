"""FIDC per-tranche cash flows (captacoes / resgates) field map.

Source CSV: tab_X_4 inside the monthly FIDC ZIP.
Target table: cvm_fidc_tranche_flows.
"""

TABLE = "cvm_fidc_tranche_flows"
CONFLICT = ("cnpj", "period", "classe_serie", "tp_oper")

FIELD_MAP = {
    "cnpj":         (["CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"], "cnpj"),
    "period":       (["DT_COMPTC"],                        "date"),
    "classe_serie": (["TAB_X_CLASSE_SERIE"],               "text"),
    "tp_oper":      (["TAB_X_TP_OPER"],                    "text"),
    "vl_total":     (["TAB_X_VL_TOTAL"],                   "numeric"),
    "qt_cota":      (["TAB_X_QT_COTA"],                    "numeric"),
}
