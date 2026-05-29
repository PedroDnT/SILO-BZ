"""Fund registry (cadastral) field map.

Source CSV: cad_fi.csv | cad_fii.csv (static CVM cadastral files, not yearly).
Target table: cvm_fund_registry.

entity_type ('fi' | 'fii' | 'fidc' etc.) is injected by the ingest module —
not from the CSV, so it is not in FIELD_MAP.
"""

TABLE = "cvm_fund_registry"
CONFLICT = ("cnpj", "entity_type")

FIELD_MAP = {
    "cnpj":      (["CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"],              "cnpj"),
    "fund_name": (["DENOM_SOCIAL", "NM_FUNDO"],                      "text"),
    "status":    (["SIT", "SITUACAO"],                               "text"),
    "tp_fundo":  (["TP_FUNDO_CLASSE", "TP_FUNDO"],                   "text"),
    "dt_reg":    (["DT_REG", "DT_CONST"],                            "date"),
    "dt_cancel": (["DT_CANCEL"],                                     "date"),
}
