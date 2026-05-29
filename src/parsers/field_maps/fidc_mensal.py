"""FIDC monthly snapshot field map.

Source CSV: inf_mensal_fidc_{year}{month:02d}.csv (monthly ZIP, tab_IV CSV).
Target table: cvm_fidc_mensal.

Historical data (pre-2025) uses tab_II (assets) / tab_III (liabilities) which
are joined by the ingest_fidc module; this map covers the current (2025+) format
only.  The inadimplencia field has multiple historical candidates.
"""

TABLE = "cvm_fidc_mensal"
CONFLICT = ("cnpj", "period")

FIELD_MAP = {
    "cnpj":          (["CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"],                             "cnpj"),
    "period":        (["DT_COMPTC"],                                                    "date"),
    "vl_total":      (["VL_TOTAL", "VL_CARTEIRA_TOTAL", "TAB_IV_A_VL_CARTEIRA"],       "numeric"),
    "vl_quota":      (["VL_QUOTA"],                                                     "numeric"),
    "vl_patrim_liq": (["TAB_IV_A_VL_PL", "VL_PATRIM_LIQ"],                             "numeric"),
    "vl_inadimpl":   (["TAB_VI_B_VL_DIRCRED_INAD", "TAB_VI_B_VL_TOTAL",
                       "TAB_VI_VL_TOTAL_INAD"],                                         "numeric"),
    "nr_cotst":      (["NR_COTST"],                                                     "int"),
}
