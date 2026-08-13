"""FII INF_TRIMESTRAL — GERAL member field map.

Source CSV: inf_trimestral_fii_geral_{year}.csv, inside
            inf_trimestral_fii_{year}.zip (latin-1, ';'-delimited, 39 fields).
Target table: cvm_fii_periodic, doc_type='trimestral_geral'.

GRAIN: one row per (fund, quarter). Verified on the real 2025 archive —
4,577 rows, 4,577 distinct (CNPJ_Fundo_Classe, Data_Referencia) pairs over
1,329 funds and 5 reference dates. That is why data_referencia is part of the
uniqueness key: the old (cnpj, doc_type, period_year) key would have kept one
quarter out of four.

This member replaces the old `trimestral` doc_type, which pointed at
inf_trimestral_fii_{year}.csv — a member that does not exist in the archive.

Address/contact fields (Logradouro..Email) and the market-listing flags stay in
residual `raw`: they are registry attributes, and cvm_fund_registry is where
they belong.
"""

TABLE = "cvm_fii_periodic"
DOC_TYPE = "trimestral_geral"
CONFLICT = ("cnpj", "doc_type", "period_year", "data_referencia")

FIELD_MAP = {
    "cnpj":            (["CNPJ_Fundo_Classe", "CNPJ_FUNDO_CLASSE", "CNPJ_Fundo"], "cnpj"),
    "data_referencia": (["Data_Referencia", "DT_COMPTC"],       "date"),
    "versao":          (["Versao"],                              "int"),
    "data_entrega":    (["Data_Entrega"],                        "date"),
    "nome_fundo":      (["Nome_Fundo_Classe", "Nome_Fundo"],     "text"),
    "tp_fundo":        (["Tipo_Fundo_Classe", "TP_FUNDO_CLASSE"], "text"),
    "publico_alvo":    (["Publico_Alvo"],                        "text"),
    "codigo_isin":     (["Codigo_ISIN"],                         "text"),
    "cotas_emitidas":  (["Quantidade_Cotas_Emitidas"],           "numeric"),
    "fundo_exclusivo": (["Fundo_Exclusivo"],                     "bool"),
    "mandato":         (["Mandato"],                             "text"),
    "segmento_atuacao": (["Segmento_Atuacao"],                   "text"),
    "tipo_gestao":     (["Tipo_Gestao"],                         "text"),
    "prazo_duracao":   (["Prazo_Duracao"],                       "text"),
    "nome_administrador": (["Nome_Administrador"],               "text"),
    "cnpj_administrador": (["CNPJ_Administrador"],               "cnpj"),
}
