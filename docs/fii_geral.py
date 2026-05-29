"""FII inf_mensal — GERAL subtype.

Source CSV: inf_mensal_fii_geral_{year}.csv (latin-1, ';'-delimited).
Target table: cvm_fii_mensal, discriminated by doc_subtype='geral'.

NOTE (for W1 agent): the `geral` member is essentially fund-registry data repeated
monthly (ISIN, segment, administrator, address). The architecturally cleaner move is
to route these static attributes to a fund dimension (cvm_fund_registry, see W2) and
keep cvm_fii_mensal for time-varying metrics only. For now this map targets the
existing table; columns not present in cvm_fii_mensal fall through to residual `raw`.
"""

TABLE = "cvm_fii_mensal"
DOC_SUBTYPE = "geral"
CONFLICT = ("cnpj", "period", "doc_subtype")

FIELD_MAP = {
    "cnpj":           (["CNPJ_Fundo_Classe", "CNPJ_FUNDO_CLASSE"], "cnpj"),
    "period":         (["Data_Referencia"],                        "date"),
    "tp_fundo":       (["Tipo_Fundo_Classe"],                      "text"),
    "cotas_emitidas": (["Quantidade_Cotas_Emitidas"],              "numeric"),
    # Remaining geral fields (Nome_Fundo_Classe, Codigo_ISIN, Segmento_Atuacao,
    # Tipo_Gestao, Mandato, Publico_Alvo, Nome_Administrador, CNPJ_Administrador,
    # address block, contact block) are NOT modeled in cvm_fii_mensal and remain in
    # residual `raw`. Promote them to cvm_fund_registry in W2 rather than here.
}
