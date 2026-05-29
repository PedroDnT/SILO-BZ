"""FI daily snapshot field map.

Source CSV: inf_diario_fi_{year}{month:02d}.csv (latin-1, ';'-delimited).
Also covers hist_inf_diario (yearly HIST/ ZIPs pre-2021) which uses the same
column names.
Target table: cvm_fi_diario (partitioned by dt_comptc year).

CVM renamed CNPJ_FUNDO -> CNPJ_FUNDO_CLASSE in 2023+ files, and
TP_FUNDO -> TP_FUNDO_CLASSE around the same time.  Both appear in the candidate
lists so the map works across all years.
"""

TABLE = "cvm_fi_diario"
CONFLICT = ("cnpj", "dt_comptc")

FIELD_MAP = {
    # db_column        ([csv_candidates],                            coerce_type)
    "cnpj":            (["CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"],        "cnpj"),
    "tp_fundo":        (["TP_FUNDO_CLASSE", "TP_FUNDO"],            "text"),
    "dt_comptc":       (["DT_COMPTC"],                              "date"),
    "vl_total":        (["VL_TOTAL"],                               "numeric"),
    "vl_quota":        (["VL_QUOTA"],                               "numeric"),
    "vl_patrim_liq":   (["VL_PATRIM_LIQ"],                          "numeric"),
    "captc_dia":       (["CAPTC_DIA"],                              "numeric"),
    "resg_dia":        (["RESG_DIA"],                               "numeric"),
    "nr_cotst":        (["NR_COTST"],                               "int"),
}
