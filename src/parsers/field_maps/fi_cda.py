"""FI portfolio composition (CDA) field map.

Source CSV: inf_cda_fi_{year}{month:02d}.csv (monthly ZIP, multiple CSVs inside).
Also covers hist_cda (yearly HIST/ ZIPs pre-2023).
Target table: cvm_fi_cda.

period is derived as first-of-month from DT_COMPTC; the ingest module
truncates any full date to YYYY-MM-01 before writing.
"""

TABLE = "cvm_fi_cda"
# UNIQUE-KEY AUDIT (migration 49, re-run 2026-09-26 on real yearly and monthly
# files after the old key was found collapsing rows). Block 1 is one row per
# government bond a fund holds, and TP_ATIVO reads "Título público federal" for
# every bond, so the old key (cnpj, period, tp_aplic, tp_ativo) kept ONE
# arbitrary bond per application type — upsert_rows dedupes same-key rows,
# last write wins, with no error:
#
#     file         source rows   old keys   distinct rows lost
#     HIST 2015        310,674    100,785              209,889
#     HIST 2020        413,549    140,120              273,429
#     202306            42,134     15,943               26,191
#     202608            28,740      9,858               18,882
#
# The earlier comment here claimed a June-2026 audit found no same-key rows.
# It was wrong. Shipped key, measured duplicates:
#
#     key                                             2005  2010  2015  2020  202306  202608
#     + cd_isin, tp_negoc                              144     0     0     0       0       0
#     + cd_isin, tp_negoc, tp_fundo  (shipped)           0     0     0     0       0       0
#
# CD_ISIN and TP_NEGOC are filled on every row of every layout checked. TP_FUNDO
# settles the 2005 filings where one CNPJ filed as both FI and FIF (the same
# reason block 4 carries it). NULLS DISTINCT like the old key: legacy FIIM rows
# with NULL parts sit in this table (migration 49), and no block-1 row has one. Do not narrow this key without re-running
# the audit on real yearly files.
CONFLICT = ("cnpj", "period", "tp_fundo", "tp_aplic", "tp_ativo", "cd_isin", "tp_negoc")
# uq_fi_cda is NULLS DISTINCT (migration 49). The per-fund replace of a
# re-read month (pg_client.replace_scoped_rows) compares keys the same way.
NULLS_DISTINCT = True

FIELD_MAP = {
    "cnpj":               (["CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"],    "cnpj"),
    "tp_fundo":           (["TP_FUNDO_CLASSE", "TP_FUNDO"],        "text"),
    # period is computed by the ingest module (DT_COMPTC -> first-of-month),
    # but we include DT_COMPTC here so it is consumed and not duplicated in raw.
    "period":             (["DT_COMPTC"],                           "date"),
    "tp_aplic":           (["TP_APLIC"],                            "text"),
    "tp_ativo":           (["TP_ATIVO"],                            "text"),
    "tp_negoc":           (["TP_NEGOC"],                            "text"),
    # The bond itself: ISIN, SELIC code, title family (NTN-B, LFT, ...) and
    # maturity. NTN-B and NTN-B Principal differ here, not in TP_ATIVO.
    "cd_isin":            (["CD_ISIN"],                             "text"),
    "cd_selic":           (["CD_SELIC"],                            "text"),
    "tp_titpub":          (["TP_TITPUB"],                           "text"),
    "dt_venc":            (["DT_VENC"],                             "date"),
    "qt_pos_final":       (["QT_POS_FINAL"],                        "numeric"),
    "vl_merc_pos_final":  (["VL_MERC_POS_FINAL"],                   "numeric"),
}
