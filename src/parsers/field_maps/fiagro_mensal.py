"""FIAGRO monthly snapshot field map.

Source CSV: inf_mensal_fiagro_{year}{month:02d}.csv (monthly ZIP, from 2025-05).
Target table: cvm_fiagro_mensal.

FIAGRO structure mirrors FIDC closely — same field names, same inadimplencia
candidates.
"""

TABLE = "cvm_fiagro_mensal"
CONFLICT = ("cnpj", "period")

FIELD_MAP = {
    "cnpj":          (["CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"],                     "cnpj"),
    "period":        (["DT_COMPTC"],                                            "date"),
    "vl_total":      (["VL_TOTAL", "VL_CARTEIRA_TOTAL"],                        "numeric"),
    "vl_quota":      (["VL_QUOTA"],                                             "numeric"),
    "vl_patrim_liq": (["VL_PATRIM_LIQ", "TAB_IV_A_VL_PL"],                     "numeric"),
    "vl_inadimpl":   (["TAB_VI_B_VL_DIRCRED_INAD", "TAB_VI_B_VL_TOTAL",
                       "TAB_VI_VL_TOTAL_INAD"],                                 "numeric"),
    "nr_cotst":      (["NR_COTST"],                                             "int"),
}
