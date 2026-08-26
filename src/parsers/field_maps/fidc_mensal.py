"""FIDC monthly snapshot field map.

Source CSV: inf_mensal_fidc_{year}{month:02d}.csv (monthly ZIP, tab_IV CSV).
Target table: cvm_fidc_mensal.

Historical data (pre-2025) uses tab_II (assets) / tab_III (liabilities) which
are joined by the ingest_fidc module; this map covers the current (2025+) format
only.  The inadimplencia field has multiple historical candidates.

Header audit (real inf_mensal_fidc_tab_IV_202607.csv) — tab_IV ships exactly
six columns: TP_FUNDO_CLASSE, CNPJ_FUNDO_CLASSE, DENOM_SOCIAL, DT_COMPTC,
TAB_IV_A_VL_PL, TAB_IV_B_VL_PL_MEDIO.  So `vl_inadimpl` is NOT in this file at
all: its TAB_VI_* candidates live in tab_VI of the same monthly ZIP.  Leaving
that to the map alone left `cvm_fidc_mensal.vl_inadimpl` NULL for every 2025+
month, which silently blanked every delinquency metric downstream
(delinquency_trend, top_delinquent, the fraud screens, the ranking functions).
`ingest_fidc_mensal` now merges the tab_VI total in on (cnpj, period) — same
ZIP, same grain, real provenance.

`vl_total`, `vl_quota` and `nr_cotst` have no tab_IV counterpart either and are
deliberately left NULL rather than guessed: the closest candidates live at a
different grain (tab_X_1 reports NR_COTST per tranche, not per fund), and this
pipeline never synthesises a value it cannot source directly.
"""

TABLE = "cvm_fidc_mensal"
# Unique-key audit (real inf_mensal_fidc_tab_IV_202606.csv): no ID_SUBCLASSE;
# 4,321 rows, zero duplicates on (CNPJ_FUNDO_CLASSE, DT_COMPTC). TP_FUNDO_CLASSE
# is Classe (4,302) vs Fundo (19) on *different* CNPJs, not a collision.
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
