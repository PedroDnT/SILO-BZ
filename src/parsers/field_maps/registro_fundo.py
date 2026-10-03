"""CVM 175 fund level: registro_fundo.csv (member of registro_fundo_classe.zip).

Target table: cvm_registro_fundo (migration 67), one row per ID_Registro_Fundo.

The same file also feeds cvm_fund_registry (field map fund_registry.py), keyed
on (cnpj, entity_type). That table cannot hold the hierarchy: CVM reuses the
fund's CNPJ for its single class, so the class row lands on the fund's key and
replaces its `raw`, and the fund's ID_Registro_Fundo is lost (132 of 36,770
class rows found their fund on 2026-10-03). This table keeps the registry's own
identifier as the key, so a class reaches its fund by ID_Registro_Fundo and
never by a guessed CNPJ match.

Columns as published by CVM (dados.cvm.gov.br/pages/novidades, 2024-10-07):
ID_Registro_Fundo, CNPJ_Fundo, Codigo_CVM, Data_Registro, Data_Constituicao,
Tipo_Fundo, Denominacao_Social, Data_Cancelamento, Situacao, ... Everything not
mapped here stays in `raw`.
"""

TABLE = "cvm_registro_fundo"
CONFLICT = ("id_registro_fundo",)
REQUIRED = ("id_registro_fundo",)

FIELD_MAP = {
    "id_registro_fundo":  (["ID_Registro_Fundo"],  "text"),
    "cnpj_fundo":         (["CNPJ_Fundo"],         "cnpj"),
    "codigo_cvm":         (["Codigo_CVM"],         "text"),
    "tipo_fundo":         (["Tipo_Fundo"],         "text"),
    "denominacao_social": (["Denominacao_Social"], "text"),
    "situacao":           (["Situacao"],           "text"),
    "data_registro":      (["Data_Registro"],      "date"),
    "data_cancelamento":  (["Data_Cancelamento"],  "date"),
}
