"""FI fund-of-fund holdings (CDA block 2) field map.

Source CSV: cda_fi_BLC_2_{year}{month:02d}.csv, inside the same monthly ZIP the
`cda` dataset already downloads. Target table: cvm_fi_cda_cotas.

WHY THIS BLOCK. It carries CNPJ_FUNDO_CLASSE_COTA — the CNPJ of the fund being
held. That turns the fund universe into a graph rather than a list: who feeds
whom, and how much. EMISSOR_LIGADO ('S'/'N') says whether the held fund belongs
to the same economic group, which is the published signal behind the
captive-vehicle screen in 15_fraud_screens.sql — currently inferred from AUM and
investor counts rather than read from the filing.

UNIQUE-KEY AUDIT, against the real cda_fi_BLC_2_202606.csv (81,899 rows):

    cnpj + period + cnpj_cota                   UNIQUE
    cnpj + period + cnpj_cota + id_subclasse    UNIQUE

The shorter key is already unique, so it is the one used: adding ID_SUBCLASSE
would buy nothing today and would change the grain the moment CVM starts
populating a column that is empty in every row of the audited file.

Note this block does NOT need TP_APLIC in its key, unlike block 4 — a fund
cannot hold the same fund under two application types in the audited data. If a
future file collides, re-run the audit before widening.
"""

TABLE = "cvm_fi_cda_cotas"
CONFLICT = ("cnpj", "period", "cnpj_cota")

FIELD_MAP = {
    "cnpj":                (["CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"],   "cnpj"),
    # Recomputed as first-of-month by the ingest module; listed so DT_COMPTC is
    # consumed rather than duplicated into raw.
    "period":              (["DT_COMPTC"],                          "date"),
    "cnpj_cota":           (["CNPJ_FUNDO_CLASSE_COTA"],             "cnpj"),
    "nm_fundo_cota":       (["NM_FUNDO_CLASSE_SUBCLASSE_COTA"],     "text"),
    "tp_aplic":            (["TP_APLIC"],                           "text"),
    "tp_ativo":            (["TP_ATIVO"],                           "text"),
    "emissor_ligado":      (["EMISSOR_LIGADO"],                     "text"),
    "qt_pos_final":        (["QT_POS_FINAL"],                       "numeric"),
    "vl_merc_pos_final":   (["VL_MERC_POS_FINAL"],                  "numeric"),
    "vl_custo_pos_final":  (["VL_CUSTO_POS_FINAL"],                 "numeric"),
    "qt_aquis_negoc":      (["QT_AQUIS_NEGOC"],                     "numeric"),
    "vl_aquis_negoc":      (["VL_AQUIS_NEGOC"],                     "numeric"),
    "qt_venda_negoc":      (["QT_VENDA_NEGOC"],                     "numeric"),
    "vl_venda_negoc":      (["VL_VENDA_NEGOC"],                     "numeric"),
}
