"""Fund registry (cadastral) field map.

Source CSV: cad_fi.csv | cad_fii.csv (static CVM cadastral files, not yearly).
Target table: cvm_fund_registry.

entity_type ('fi' | 'fii' | 'fidc' etc.) is injected by the ingest module —
not from the CSV, so it is not in FIELD_MAP.
"""

TABLE = "cvm_fund_registry"
CONFLICT = ("cnpj", "entity_type")

FIELD_MAP = {
    # Candidates cover legacy cad_fi/cad_fii columns AND the CVM-175
    # registro_fundo / registro_classe columns (Denominacao_Social, Situacao, …).
    "cnpj":      (["CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO", "CNPJ_Classe", "CNPJ_Fundo"], "cnpj"),
    "fund_name": (["DENOM_SOCIAL", "NM_FUNDO", "Denominacao_Social"],               "text"),
    "status":    (["SIT", "SITUACAO", "Situacao"],                                  "text"),
    "tp_fundo":  (["TP_FUNDO_CLASSE", "TP_FUNDO", "Tipo_Classe", "Tipo_Fundo"],     "text"),
    "dt_reg":    (["DT_REG", "DT_CONST", "Data_Registro"],                          "date"),
    "dt_cancel": (["DT_CANCEL", "Data_Cancelamento"],                              "date"),
}
