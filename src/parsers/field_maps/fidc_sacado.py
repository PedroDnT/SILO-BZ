"""FIDC largest-sacado concentration field map (tab_VIII).

Source CSV: tab_VIII inside the monthly FIDC ZIP (2025+) and the yearly HIST
ZIP (2013-2024). Six columns from 2013-01 (every HIST archive opened): the
fund key, SEQUENCIAL and VALOR. SEQUENCIAL runs 1..25 and VALOR is
the exposure to that sacado — the 25 largest debtors, anonymized. CVM's own
dictionary (META/meta_inf_mensal_fidc_tab_VIII.txt) ships both columns with a
blank description; the reading above is the file's shape (rank ceiling exactly
25, values descending on 2,978 of 3,043 funds in 2026-07) and the disclosure
Uqbar reported CVM confirming in 2026-09.
Target table: cvm_fidc_sacado.

Stored as filed: the rank is CVM's, never recomputed here, and the funds whose
values are not monotonic stay as they were filed.
"""

TABLE = "cvm_fidc_sacado"
# Unique-key audit (real inf_mensal_fidc_tab_VIII_202607.csv): 41,225 rows,
# zero duplicates on (CNPJ_FUNDO_CLASSE, DT_COMPTC, SEQUENCIAL).
CONFLICT = ("cnpj", "period", "seq")

FIELD_MAP = {
    "cnpj":   (["CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"], "cnpj"),
    "period": (["DT_COMPTC"],                        "date"),
    "seq":    (["SEQUENCIAL"],                       "int"),
    "valor":  (["VALOR"],                            "numeric"),
}
