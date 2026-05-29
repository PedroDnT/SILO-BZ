"""FII inf_mensal — ATIVO_PASSIVO subtype (balance sheet).

Source CSV: inf_mensal_fii_ativo_passivo_{year}.csv (latin-1, ';'-delimited).
Target table: cvm_fii_mensal, discriminated by doc_subtype='ativo_passivo'.

The headline aggregates are mapped to existing typed columns; the ~45 granular
balance-sheet line items remain in residual `raw`. If the UI needs the full balance
sheet, the W1 agent should either add typed columns for them or split ativo_passivo
into its own properly-typed table (see docs/planning/02 §1 and 04 W1).
"""

TABLE = "cvm_fii_mensal"
DOC_SUBTYPE = "ativo_passivo"
CONFLICT = ("cnpj", "period", "doc_subtype")

FIELD_MAP = {
    "cnpj":                  (["CNPJ_Fundo_Classe"], "cnpj"),
    "period":                (["Data_Referencia"],   "date"),
    # Total_Investido is the asset total for this subtype.
    "vl_ativo":              (["Total_Investido"],   "numeric"),
    "rendimentos_distribuir":(["Rendimentos_Distribuir"], "numeric"),
    # Headline line items worth typing now (extend as needed):
    # "total_passivo":       (["Total_Passivo"],     "numeric"),
    # "disponibilidades":    (["Disponibilidades"],  "numeric"),
    # "direitos_bens_imoveis":(["Direitos_Bens_Imoveis"], "numeric"),
    # All other line items (Titulos_Publicos, CRI, LCI, ... ) remain in residual raw.
}
