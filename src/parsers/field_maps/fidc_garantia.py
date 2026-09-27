"""FIDC collateral field map (tab_X_7).

Source CSV: tab_X_7 inside the monthly FIDC ZIP (2025+) and the yearly HIST
ZIP. The member exists from 2019-11 (every HIST archive 2013-2024 opened:
2013-01..2019-10 ship tab_X_1..X_6 and no tab_X_7). Two headers, measured on
all 82 published months 2019-11..2026-08:

  2019-11..2020-10  CNPJ_FUNDO;DENOM_SOCIAL;DT_COMPTC;
                    TAB_X_VL_GARANTIA_DIRCRED;TAB_X_PR_GARANTIA_DIRCRED
  2020-11..2026-08  TP_FUNDO_CLASSE;CNPJ_FUNDO_CLASSE;DENOM_SOCIAL;DT_COMPTC;
                    TAB_X_VL_GARANTIA_DIRCRED;TAB_X_PR_GARANTIA_DIRCRED

Target table: cvm_fidc_garantia. Wide, one row per (fund, month), like
cvm_fidc_scr.

What the two values mean: the value of guarantees on the fund's credit rights
(VL) and a percentage (PR). CVM's dictionary
(META/meta_inf_mensal_fidc_tab_X_7.txt) ships a BLANK description for both,
typed numeric(17,2). The denominator of PR is not stated and does not
reconcile to one sibling total: VL / (PR/100) lands within 2% of tab_II
TAB_II_VL_CARTEIRA on 6 of 28 filers in 2026-08 and 19 of 42 in 2025-12. So PR
is stored as filed, never recomputed. 51 of 188,476 rows file PR > 100 (113.42
in 2026-08; 562,714,580.15 in 2020-12) and are kept as filed, like the tranche
and cedente percentages: readers range-check, the ingest does not guess.
"""

TABLE = "cvm_fidc_garantia"
# Unique-key audit, all 188,476 rows 2019-11..2026-08: 211 rows (0.11%) repeat
# (CNPJ_FUNDO_CLASSE, DT_COMPTC). Every one repeats the same VL and PR: 210 are
# a 'Fundo' + 'Classe' pair of the same CNPJ, 1 is a byte-identical line
# (37.606.580/0001-75, 2025-09). Adding TP_FUNDO_CLASSE would still leave that
# one and would store the same fund twice, so the key is the sibling tabs' own.
CONFLICT = ("cnpj", "period")

FIELD_MAP = {
    "cnpj":        (["CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"], "cnpj"),
    "period":      (["DT_COMPTC"],                        "date"),
    "vl_garantia": (["TAB_X_VL_GARANTIA_DIRCRED"],        "numeric"),
    "pr_garantia": (["TAB_X_PR_GARANTIA_DIRCRED"],        "numeric"),
}
