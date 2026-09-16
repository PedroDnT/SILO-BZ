"""FIDC named-cedente concentration field map (tab_I, the cedente slots only).

Source CSV: tab_I inside the monthly FIDC ZIP (2025+) and the yearly HIST ZIP
(2013-2024). The 36 cedente slot columns exist from 2019-11 (measured month by
month; 2013-01..2019-10 is a 67-column form with one TAB_I2B1_* block of
placeholder values and a different block meaning, and is not ingested here —
see _FIDC_TAB_FIRST_PERIOD in src/pipeline/cvm_pipeline.py). From 2019-11 the
header is stable across the HIST/monthly archive boundary; only the fund key
column is CNPJ_FUNDO through 2019 and CNPJ_FUNDO_CLASSE after, which the
candidate list covers. This map takes the fund key and:

    TAB_I2A12_CPF_CNPJ_CEDENTE_1..9 / TAB_I2A12_PR_CEDENTE_1..9   (block A)
    TAB_I2B12_CPF_CNPJ_CEDENTE_1..9 / TAB_I2B12_PR_CEDENTE_1..9   (block B)

Block A is the receivables acquired WITH substantial retention of risks and
benefits by the cedente (TAB_I2A_VL_DIRCRED_RISCO); block B is WITHOUT
(TAB_I2B_VL_DIRCRED_SEM_RISCO). The slot carries the originator's own CPF or
CNPJ — a real identifier, not the anonymized rank of tab_VIII — and its share
of that block in percent. ingest_fidc_cedente unpivots the slots into one row
per (fund, month, block, slot), emitting only slots whose identifier
validates: placeholders (all-zero, all-nine — 2,959 slots in 2024-12, none in
2026-07) are dropped and counted, and a short identifier is kept only when
zero-padding yields a CNPJ or CPF whose check digits verify. The share
(PR_CEDENTE) is stored as filed and is dirty the way CVM's percentage fields
are (9% of slots above 100 in 2026-07); readers range-check it.

The remaining ~70 tab_I columns (asset composition, admin, condomínio,
derivatives) are not modeled here; see docs/DATA_INVENTORY.md §2.
Target table: cvm_fidc_cedente.
"""

TABLE = "cvm_fidc_cedente"
CONFLICT = ("cnpj", "period", "bloco", "seq")

BLOCKS = ("A", "B")
SLOTS = range(1, 10)


def _slot_columns():
    cols = {}
    for blk in BLOCKS:
        for i in SLOTS:
            # `text`, not `cnpj`: the column is CPF_CNPJ and 36 of the 2026-07
            # block-A first slots hold an 11-digit CPF, which `cnpj` would
            # zero-pad into a fake CNPJ. Digits are stripped at ingest.
            cols[f"cedente_{blk.lower()}_{i}"] = ([f"TAB_I2{blk}12_CPF_CNPJ_CEDENTE_{i}"], "text")
            cols[f"pr_{blk.lower()}_{i}"] = ([f"TAB_I2{blk}12_PR_CEDENTE_{i}"], "numeric")
    return cols


FIELD_MAP = {
    "cnpj":   (["CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"], "cnpj"),
    "period": (["DT_COMPTC"],                        "date"),
    **_slot_columns(),
}
