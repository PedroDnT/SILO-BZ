"""SECURIT monthly emissions field map (cra_mensal, cri_mensal, ots_mensal).

Source CSV: inf_mensal_cra_{year}.csv | inf_mensal_cri_{year}.csv |
            inf_mensal_ots_{year}.csv (yearly ZIPs).
Target table: cvm_securit_mensal.

instrument_type and period_year are injected by the ingest module.
cnpj_securit prefers the 'securit' suffix since these are securitisation vehicle
CNPJs, not fund CNPJs.
"""

TABLE = "cvm_securit_mensal"
CONFLICT = ("instrument_type", "period_year", "cnpj_securit", "dt_emissao", "dt_vencto", "vl_emissao")

FIELD_MAP = {
    "cnpj_securit":  (["CNPJ_Securitizadora", "CNPJ_securit", "CNPJ_FUNDO", "CNPJ"],   "cnpj"),
    "dt_emissao":    (["Data_Referencia", "DT_EMISSAO"],                                "date"),
    "dt_vencto":     (["DT_VENCTO", "DT_VENCIMENTO"],                                  "date"),
    "vl_emissao":    (["Valor_Atualizado_Emissao", "VL_EMISSAO"],                       "numeric"),
    "vl_unit":       (["VL_UNIT", "PU_EMISSAO", "VL_PU_EMISSAO"],                       "numeric"),
    "qt_titulos":    (["QT_TITULOS"],                                                   "numeric"),
    "vl_total":      (["Ativo", "VL_TOTAL"],                                            "numeric"),
    "tp_ativo":      (["TP_ATIVO"],                                                     "text"),
}
