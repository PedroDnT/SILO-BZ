"""FIP periodic reports field map.

Source CSV: inf_trimestral_fip_{year}.csv (2010-2023) or
           inf_quadrimestral_fip_{year}.csv (2024+).
Target table: cvm_fip_periodic.

doc_type and period_year are injected by the ingest module (not from the CSV),
so they are not in FIELD_MAP.
"""

TABLE = "cvm_fip_periodic"
CONFLICT = ("cnpj", "doc_type", "period_year")

FIELD_MAP = {
    "cnpj":          (["CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"],  "cnpj"),
    "vl_patrim_liq": (["VL_PATRIM_LIQ"],                    "numeric"),
}
