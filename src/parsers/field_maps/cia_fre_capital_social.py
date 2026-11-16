"""CIA_ABERTA FRE capital social field map — share counts per capital type.

Source CSV: fre_cia_aberta_capital_social_{YYYY}.csv (one member of the
            yearly FRE ZIP, latin-1, ; delimited). Published from 2010.
Target:     cia_fre_capital (UNIQUE NULLS NOT DISTINCT on cnpj_cia,
            data_refer, versao, id_capital_social; migration 86, #1161)

Header (verified live 2026-11-16 against fre_cia_aberta_2010.zip):
    CNPJ_Companhia;Data_Referencia;Versao;ID_Documento;Nome_Companhia;
    ID_Capital_Social;Tipo_Capital;Data_Autorizacao_Aprovacao;Valor_Capital;
    Prazo_Integralizacao;Quantidade_Acoes_Ordinarias;
    Quantidade_Acoes_Preferenciais;Quantidade_Total_Acoes

Notes
-----
* One FRE lists one row per capital type (Capital Emitido, Capital Subscrito,
  Capital Integralizado, Capital Autorizado). Every row is kept as filed;
  tipo_capital says which.
* Data_Referencia is the form's reference date (the first day of the year in
  2010), not a filing date. Every Versao is kept; consumers take the max.
* Nome_Companhia is denormalised and falls through to raw.
"""

TABLE = "cia_fre_capital"
CONFLICT = ("cnpj_cia", "data_refer", "versao", "id_capital_social")

FIELD_MAP = {
    "cnpj_cia":          (["CNPJ_Companhia"],                 "cnpj"),
    "data_refer":        (["Data_Referencia"],                "date"),
    "versao":            (["Versao"],                         "int"),
    "id_documento":      (["ID_Documento"],                   "text"),
    "id_capital_social": (["ID_Capital_Social"],              "text"),
    "tipo_capital":      (["Tipo_Capital"],                   "text"),
    "dt_autorizacao":    (["Data_Autorizacao_Aprovacao"],     "date"),
    "valor_capital":     (["Valor_Capital"],                  "numeric"),
    "prazo_integralizacao": (["Prazo_Integralizacao"],        "text"),
    "qt_ordin":          (["Quantidade_Acoes_Ordinarias"],    "int"),
    "qt_pref":           (["Quantidade_Acoes_Preferenciais"], "int"),
    "qt_total":          (["Quantidade_Total_Acoes"],         "int"),
}
