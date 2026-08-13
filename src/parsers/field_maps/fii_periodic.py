"""FII periodic reports field map (anual, dfin).

Source CSV: inf_anual_fii_geral_{year}.csv (member of the yearly INF_ANUAL ZIP)
            dfin_fii_{year}.csv (plain yearly CSV).
Target table: cvm_fii_periodic.

doc_type and period_year are injected by the ingest module (not from the CSV),
so they are not in FIELD_MAP.

The INF_TRIMESTRAL members no longer use this map — each has its own
(fii_trimestral_geral.py, fii_trimestral_complemento.py, fii_imovel.py), because
they are separate tables inside the archive with separate headers.

data_referencia is part of the uniqueness key (migration 15): dfin ships several
filings per fund per year (e.g. 00.332.266/0001-31 files for both 2025-07-31 and
2025-12-31 in dfin_fii_2025.csv), and the old year-grain key kept only the last
one to be upserted.
"""

TABLE = "cvm_fii_periodic"
CONFLICT = ("cnpj", "doc_type", "period_year", "data_referencia")

FIELD_MAP = {
    "cnpj":      (["CNPJ_Fundo_Classe", "CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"], "cnpj"),
    # data_referencia is present in some periodic subtypes
    "data_referencia": (["Data_Referencia", "DT_COMPTC"],                    "date"),
}
