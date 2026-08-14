"""FIDC delinquency aging buckets field map.

Source CSV: tab_VI inside the monthly FIDC ZIP (credits without risk, by maturity
and delinquency band).  CVM uses multiple naming conventions across years.
Target table: cvm_fidc_aging.
"""

TABLE = "cvm_fidc_aging"
# Unique-key audit (real inf_mensal_fidc_tab_VI_202606.csv): no ID_SUBCLASSE;
# 4,321 rows, zero duplicates on (CNPJ_FUNDO_CLASSE, DT_COMPTC). Same Classe/
# Fundo split as tab_IV, on distinct CNPJs.
CONFLICT = ("cnpj", "period")

FIELD_MAP = {
    "cnpj":   (["CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"], "cnpj"),
    "period": (["DT_COMPTC"],                        "date"),
    # Maturity bands (days overdue: A = not yet delinquent)
    "vl_prazo_30":        (["TAB_VI_A1_VL_PRAZO_VENC_30",   "TAB_VI_A_VL_1",  "TAB_VI_VL_PRAZO_1_30"],        "numeric"),
    "vl_prazo_60":        (["TAB_VI_A2_VL_PRAZO_VENC_60",   "TAB_VI_A_VL_2",  "TAB_VI_VL_PRAZO_31_60"],       "numeric"),
    "vl_prazo_90":        (["TAB_VI_A3_VL_PRAZO_VENC_90",   "TAB_VI_A_VL_3",  "TAB_VI_VL_PRAZO_61_90"],       "numeric"),
    "vl_prazo_120":       (["TAB_VI_A4_VL_PRAZO_VENC_120",  "TAB_VI_A_VL_4",  "TAB_VI_VL_PRAZO_91_120"],      "numeric"),
    "vl_prazo_150":       (["TAB_VI_A5_VL_PRAZO_VENC_150",  "TAB_VI_A_VL_5",  "TAB_VI_VL_PRAZO_121_150"],     "numeric"),
    "vl_prazo_180":       (["TAB_VI_A6_VL_PRAZO_VENC_180",  "TAB_VI_A_VL_6",  "TAB_VI_VL_PRAZO_151_180"],     "numeric"),
    "vl_prazo_360":       (["TAB_VI_A7_VL_PRAZO_VENC_360",  "TAB_VI_A_VL_7",  "TAB_VI_VL_PRAZO_181_360"],     "numeric"),
    "vl_prazo_720":       (["TAB_VI_A8_VL_PRAZO_VENC_720",  "TAB_VI_A_VL_8",  "TAB_VI_VL_PRAZO_361_720"],     "numeric"),
    "vl_prazo_1080":      (["TAB_VI_A9_VL_PRAZO_VENC_1080", "TAB_VI_A_VL_9",  "TAB_VI_VL_PRAZO_721_1080"],    "numeric"),
    "vl_prazo_maior_1080":(["TAB_VI_A10_VL_PRAZO_VENC_MAIOR_1080", "TAB_VI_A_VL_10", "TAB_VI_VL_PRAZO_MAIS_1080"], "numeric"),
    # Delinquency bands (B = already delinquent)
    "vl_inad_30":         (["TAB_VI_B1_VL_INAD_30",   "TAB_VI_B_VL_1",  "TAB_VI_VL_INAD_1_30"],    "numeric"),
    "vl_inad_60":         (["TAB_VI_B2_VL_INAD_60",   "TAB_VI_B_VL_2",  "TAB_VI_VL_INAD_31_60"],   "numeric"),
    "vl_inad_90":         (["TAB_VI_B3_VL_INAD_90",   "TAB_VI_B_VL_3",  "TAB_VI_VL_INAD_61_90"],   "numeric"),
    "vl_inad_120":        (["TAB_VI_B4_VL_INAD_120",  "TAB_VI_B_VL_4",  "TAB_VI_VL_INAD_91_120"],  "numeric"),
    "vl_inad_150":        (["TAB_VI_B5_VL_INAD_150",  "TAB_VI_B_VL_5",  "TAB_VI_VL_INAD_121_150"], "numeric"),
    "vl_inad_180":        (["TAB_VI_B6_VL_INAD_180",  "TAB_VI_B_VL_6",  "TAB_VI_VL_INAD_151_180"], "numeric"),
    "vl_inad_360":        (["TAB_VI_B7_VL_INAD_360",  "TAB_VI_B_VL_7",  "TAB_VI_VL_INAD_181_360"], "numeric"),
    "vl_inad_720":        (["TAB_VI_B8_VL_INAD_720",  "TAB_VI_B_VL_8",  "TAB_VI_VL_INAD_361_720"], "numeric"),
    "vl_inad_1080":       (["TAB_VI_B9_VL_INAD_1080", "TAB_VI_B_VL_9",  "TAB_VI_VL_INAD_721_1080"],"numeric"),
    "vl_inad_maior_1080": (["TAB_VI_B10_VL_INAD_MAIOR_1080", "TAB_VI_B_VL_10", "TAB_VI_VL_INAD_MAIS_1080"], "numeric"),
    "vl_total_inad":      (["TAB_VI_B_VL_DIRCRED_INAD", "TAB_VI_B_VL_TOTAL", "TAB_VI_VL_TOTAL_INAD"], "numeric"),
}
