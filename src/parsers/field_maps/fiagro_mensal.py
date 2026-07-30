"""FIAGRO monthly snapshot field map.

Source CSV: inf_mensal_fiagro_{year}{month:02d}.csv (monthly ZIP, from 2025-05).
Target table: cvm_fiagro_mensal.

Header format: the published file is CVM-175 style — Title_Case_With_Underscores
(`CNPJ_Classe`, `Data_Referencia`, `Patrimonio_Liquido`), NOT the legacy
uppercase FIDC style (`CNPJ_FUNDO`, `DT_COMPTC`, `VL_PATRIM_LIQ`). This map had
only the legacy names, so no field ever matched: every row parsed to all-None,
was dropped for a missing cnpj/period, and the slice logged 'ok' with 0 rows
(34 such slices before this fix). New name first, legacy name kept as a
fallback — same ordering as fii_geral.py.

Note FIAGRO keys on `CNPJ_Classe` (not `CNPJ_Fundo_Classe` as FII does).

The sibling `inf_mensal_fiagro_subclasse_*.csv` member in the same ZIP is a
different grain (per-subclass) and is not ingested here.
"""

TABLE = "cvm_fiagro_mensal"
CONFLICT = ("cnpj", "period")

FIELD_MAP = {
    "cnpj":          (["CNPJ_Classe", "CNPJ_Fundo_Classe",
                       "CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"],            "cnpj"),
    "period":        (["Data_Referencia", "DT_COMPTC"],                "date"),
    "tp_fundo":      (["Tipo_Fundo_Classe", "TP_FUNDO_CLASSE"],        "text"),
    "vl_total":      (["Valor_Ativo", "VL_TOTAL", "VL_CARTEIRA_TOTAL"], "numeric"),
    # Per schema.sql, vl_quota holds Valor_Patrimonial_Cotas — which CVM
    # publishes as a total, not a unit price.
    "vl_quota":      (["Valor_Patrimonial_Cotas", "VL_QUOTA"],         "numeric"),
    "vl_patrim_liq": (["Patrimonio_Liquido", "VL_PATRIM_LIQ",
                       "TAB_IV_A_VL_PL"],                              "numeric"),
    # Delinquency: `Vencidos` is the total overdue balance (the file also
    # carries Vencidos_* aging buckets, which stay in residual raw).
    "vl_inadimpl":   (["Vencidos", "TAB_VI_B_VL_DIRCRED_INAD",
                       "TAB_VI_B_VL_TOTAL", "TAB_VI_VL_TOTAL_INAD"],   "numeric"),
    "nr_cotst":      (["Numero_Cotistas", "NR_COTST"],                 "int"),
}
