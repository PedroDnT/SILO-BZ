"""SECURIT financial statements field map (dfin_cra, dfin_cri).

Source CSV: inf_dfin_cra_{year}.csv | inf_dfin_cri_{year}.csv (yearly CSV).
Target table: cvm_securit_dfin.

This dataset is sparsely structured — the main interest is the CNPJ.
instrument_type and period_year are injected by the ingest module.
All other fields fall through to residual `raw` until the schema is extended.
"""

TABLE = "cvm_securit_dfin"
CONFLICT = ("instrument_type", "period_year", "cnpj_securit")

FIELD_MAP = {
    "cnpj_securit": (["CNPJ_Securitizadora", "CNPJ_securit", "CNPJ_FUNDO", "CNPJ"], "cnpj"),
}
