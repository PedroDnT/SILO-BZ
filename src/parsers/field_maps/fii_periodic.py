"""FII periodic reports field map (trimestral, anual, dfin).

Source CSV: inf_trimestral_fii_{year}.csv | inf_anual_fii_{year}.csv |
            inf_dfin_fii_{year}.csv (yearly ZIPs).
Target table: cvm_fii_periodic.

doc_type and period_year are injected by the ingest module (not from the CSV),
so they are not in FIELD_MAP.
"""

TABLE = "cvm_fii_periodic"
CONFLICT = ("cnpj", "doc_type", "period_year")

FIELD_MAP = {
    "cnpj":      (["CNPJ_Fundo_Classe", "CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"], "cnpj"),
    # data_referencia is present in some periodic subtypes
    "data_referencia": (["Data_Referencia", "DT_COMPTC"],                    "date"),
}
