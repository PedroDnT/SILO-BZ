"""FI portfolio composition (CDA) field map.

Source CSV: inf_cda_fi_{year}{month:02d}.csv (monthly ZIP, multiple CSVs inside).
Also covers hist_cda (yearly HIST/ ZIPs pre-2023).
Target table: cvm_fi_cda.

period is derived as first-of-month from DT_COMPTC; the ingest module
truncates any full date to YYYY-MM-01 before writing.
"""

TABLE = "cvm_fi_cda"
CONFLICT = ("cnpj", "period", "tp_aplic", "tp_ativo")

FIELD_MAP = {
    "cnpj":               (["CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"],    "cnpj"),
    # period is computed by the ingest module (DT_COMPTC -> first-of-month),
    # but we include DT_COMPTC here so it is consumed and not duplicated in raw.
    "period":             (["DT_COMPTC"],                           "date"),
    "tp_aplic":           (["TP_APLIC"],                            "text"),
    "tp_ativo":           (["TP_ATIVO"],                            "text"),
    "vl_merc_pos_final":  (["VL_MERC_POS_FINAL"],                   "numeric"),
}
