"""FIDC SCR risk-rating ladder field map (tab_X).

Source CSV: tab_X inside the monthly FIDC ZIP (2025+) and the yearly HIST ZIP.
The member exists from 2023-10 (measured month by month; 2013-01..2023-09 have
tab_X_1..X_6 but no tab_X) and its header has not changed since. Not to be
confused with tab_X_1..7,
which are the per-tranche members — the fetcher's csv_name_pattern names
`tab_X_{yyyymm}` so the period suffix disambiguates.
Target table: cvm_fidc_scr.

Two ladders of the BACEN SCR grades AA..H: the value of receivables by the
DEBTOR's rating and by the OPERATION's rating, plus the fund's tax liabilities.
Wide, like cvm_fidc_aging: one row per (fund, month) in the source.
"""

TABLE = "cvm_fidc_scr"
# Unique-key audit (real inf_mensal_fidc_tab_X_202607.csv): 4,382 rows, zero
# duplicates on (CNPJ_FUNDO_CLASSE, DT_COMPTC).
CONFLICT = ("cnpj", "period")

FIELD_MAP = {
    "cnpj":   (["CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"], "cnpj"),
    "period": (["DT_COMPTC"],                        "date"),
    "vl_devedor_aa": (["TAB_X_SCR_RISCO_DEVEDOR_AA"], "numeric"),
    "vl_devedor_a":  (["TAB_X_SCR_RISCO_DEVEDOR_A"],  "numeric"),
    "vl_devedor_b":  (["TAB_X_SCR_RISCO_DEVEDOR_B"],  "numeric"),
    "vl_devedor_c":  (["TAB_X_SCR_RISCO_DEVEDOR_C"],  "numeric"),
    "vl_devedor_d":  (["TAB_X_SCR_RISCO_DEVEDOR_D"],  "numeric"),
    "vl_devedor_e":  (["TAB_X_SCR_RISCO_DEVEDOR_E"],  "numeric"),
    "vl_devedor_f":  (["TAB_X_SCR_RISCO_DEVEDOR_F"],  "numeric"),
    "vl_devedor_g":  (["TAB_X_SCR_RISCO_DEVEDOR_G"],  "numeric"),
    "vl_devedor_h":  (["TAB_X_SCR_RISCO_DEVEDOR_H"],  "numeric"),
    "vl_oper_aa":    (["TAB_X_SCR_RISCO_OPER_AA"],    "numeric"),
    "vl_oper_a":     (["TAB_X_SCR_RISCO_OPER_A"],     "numeric"),
    "vl_oper_b":     (["TAB_X_SCR_RISCO_OPER_B"],     "numeric"),
    "vl_oper_c":     (["TAB_X_SCR_RISCO_OPER_C"],     "numeric"),
    "vl_oper_d":     (["TAB_X_SCR_RISCO_OPER_D"],     "numeric"),
    "vl_oper_e":     (["TAB_X_SCR_RISCO_OPER_E"],     "numeric"),
    "vl_oper_f":     (["TAB_X_SCR_RISCO_OPER_F"],     "numeric"),
    "vl_oper_g":     (["TAB_X_SCR_RISCO_OPER_G"],     "numeric"),
    "vl_oper_h":     (["TAB_X_SCR_RISCO_OPER_H"],     "numeric"),
    "vl_debito_tribut": (["TAB_X_DEBITO_TRIBUT"],     "numeric"),
}
