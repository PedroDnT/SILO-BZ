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
    # Administrator / manager (gestor) — service providers. Source columns:
    #   legacy cad_fi:        CNPJ_ADMIN, ADMIN, CPF_CNPJ_GESTOR, GESTOR
    #   CVM-175 registro_fundo: CNPJ_Administrador, Administrador, CPF_CNPJ_Gestor, Gestor
    # admin_cnpj is always a 14-digit PJ → cnpj coerce; gestor_id may be a CPF
    # (PF gestor) or CNPJ, so keep it as text to preserve the source value.
    "admin_cnpj":  (["CNPJ_ADMIN", "CNPJ_Administrador"],   "cnpj"),
    "admin_name":  (["ADMIN", "Administrador"],             "text"),
    "gestor_id":   (["CPF_CNPJ_GESTOR", "CPF_CNPJ_Gestor"], "text"),
    "gestor_name": (["GESTOR", "Gestor"],                   "text"),
}
