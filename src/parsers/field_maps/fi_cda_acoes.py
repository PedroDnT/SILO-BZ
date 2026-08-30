"""FI equity holdings (CDA block 4) field map.

Source CSV: cda_fi_BLC_4_{year}{month:02d}.csv, inside the same monthly ZIP the
`cda` dataset already downloads. Target table: cvm_fi_cda_acoes.

WHY THIS BLOCK. cvm_fi_cda stores the portfolio AGGREGATED by asset class — one
number per (fund, month, tp_aplic, tp_ativo). Block 4 is the holdings themselves,
and it carries CD_ATIVO: the B3 ticker. That is the column that joins the fund
universe to the quote tape, so "which funds hold PETR4, and how did that change"
becomes answerable. Nothing else in the warehouse provides that edge.

UNIQUE-KEY AUDIT, against the real cda_fi_BLC_4_202606.csv (165,963 rows):

    cnpj + period + cd_ativo                       3,972 collisions
    cnpj + period + cd_ativo + tp_negoc            3,970 collisions
    cnpj + period + tp_aplic + cd_ativo + tp_negoc UNIQUE

TP_APLIC is load-bearing and easy to miss: it is NOT constant within the block.
The same fund holds the same ticker under six different application types
(Ações, BDR, "Ações e outros TVM cedidos em empréstimo", "Compras a termo a
receber", …), and those are genuinely different positions with different
quantities — 3,883 groups differ in VL_MERC_POS_FINAL. Dropping TP_APLIC from
the key would silently collapse them and lose position value on upsert.

Do not narrow this key without re-running that audit on a real file.
"""

TABLE = "cvm_fi_cda_acoes"
CONFLICT = ("cnpj", "period", "tp_aplic", "cd_ativo", "tp_negoc")

FIELD_MAP = {
    "cnpj":                (["CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"], "cnpj"),
    # period is recomputed by the ingest module as first-of-month; DT_COMPTC is
    # listed so it is consumed rather than duplicated into raw.
    "period":              (["DT_COMPTC"],                       "date"),
    "tp_aplic":            (["TP_APLIC"],                        "text"),
    "tp_ativo":            (["TP_ATIVO"],                        "text"),
    "tp_negoc":            (["TP_NEGOC"],                        "text"),
    "cd_ativo":            (["CD_ATIVO"],                        "text"),
    "cd_isin":             (["CD_ISIN"],                         "text"),
    "ds_ativo":            (["DS_ATIVO"],                        "text"),
    "emissor_ligado":      (["EMISSOR_LIGADO"],                  "text"),
    "qt_pos_final":        (["QT_POS_FINAL"],                    "numeric"),
    "vl_merc_pos_final":   (["VL_MERC_POS_FINAL"],               "numeric"),
    "vl_custo_pos_final":  (["VL_CUSTO_POS_FINAL"],              "numeric"),
    "qt_aquis_negoc":      (["QT_AQUIS_NEGOC"],                  "numeric"),
    "vl_aquis_negoc":      (["VL_AQUIS_NEGOC"],                  "numeric"),
    "qt_venda_negoc":      (["QT_VENDA_NEGOC"],                  "numeric"),
    "vl_venda_negoc":      (["VL_VENDA_NEGOC"],                  "numeric"),
}
