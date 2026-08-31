"""FI equity holdings (CDA block 4) field map.

Source CSV: cda_fi_BLC_4_{year}{month:02d}.csv, inside the same monthly ZIP the
`cda` dataset already downloads. Target table: cvm_fi_cda_acoes.

WHY THIS BLOCK. cvm_fi_cda stores the portfolio AGGREGATED by asset class — one
number per (fund, month, tp_aplic, tp_ativo). Block 4 is the holdings themselves,
and it carries CD_ATIVO: the B3 ticker. That is the column that joins the fund
universe to the quote tape, so "which funds hold PETR4, and how did that change"
becomes answerable. Nothing else in the warehouse provides that edge.

COLUMN NAMES DRIFT. The 2023+ monthly files use CNPJ_FUNDO_CLASSE /
TP_FUNDO_CLASSE; the yearly HIST archives (2005-2022) use CNPJ_FUNDO /
TP_FUNDO. Headers are otherwise byte-identical across 2005, 2015 and 2022, so
one field map with fallback lists serves both formats.

UNIQUE-KEY AUDIT — re-run across four real files after the monthly-only audit
turned out to be too narrow. Collisions are groups, and "differ" counts the
groups whose QT_POS_FINAL / VL_MERC_POS_FINAL are not identical, i.e. real
position value an upsert would destroy:

    key                                              2005    2015     2022  202606
    cnpj+period+cd_ativo                           16,070  84,432  185,654   3,972
    cnpj+period+tp_aplic+cd_ativo+tp_negoc            395       1       33  UNIQUE
    + tp_ativo                                        390       1       25  UNIQUE
    + tp_ativo + tp_fundo  (shipped)                    7  UNIQUE       25  UNIQUE

TP_APLIC is load-bearing and easy to miss: the same fund holds the same ticker
under six application types (Ações, BDR, "Ações e outros TVM cedidos em
empréstimo", …) with different quantities.

TP_ATIVO is load-bearing for a different reason: a BDR ticker appears twice in
the same fund and month as "BDR não patrocinado" and "BDR nível I" — different
instruments, different positions, same CD_ATIVO.

TP_FUNDO settles the 2005-era filings where one CNPJ filed as both FI and FIF
with different DT_CONFID_APLIC — two genuine filings, 383 of the 390 groups.

RESIDUAL, stated rather than hidden: 7 groups remain in 2005 and 25 in 2022.
All 25 of the 2022 ones differ only in DS_ATIVO whitespace and DT_INI_VIGENCIA
with identical positions; six of the seven 2005 ones are byte-identical rows.
Exactly ONE group in 372,832 rows (2005) loses a distinct position to the
upsert. That is the measured cost of a natural key here; the alternative is the
row_hash treatment block 6 needs, which trades provenance for completeness.

Do not narrow this key without re-running that audit on real yearly files —
the monthly files alone report the shipped key as UNIQUE and will mislead you.
"""

TABLE = "cvm_fi_cda_acoes"
CONFLICT = ("cnpj", "period", "tp_fundo", "tp_aplic", "tp_ativo", "cd_ativo", "tp_negoc")

FIELD_MAP = {
    "cnpj":                (["CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"], "cnpj"),
    "tp_fundo":            (["TP_FUNDO_CLASSE", "TP_FUNDO"],     "text"),
    # period is recomputed by the ingest module as first-of-month; DT_COMPTC is
    # listed so it is consumed rather than duplicated into raw.
    "period":              (["DT_COMPTC"],                       "date"),
    "tp_aplic":            (["TP_APLIC"],                        "text"),
    "tp_ativo":            (["TP_ATIVO"],                        "text"),
    "tp_negoc":            (["TP_NEGOC"],                        "text"),
    "cd_ativo":            (["CD_ATIVO"],                        "text"),
    "cd_isin":             (["CD_ISIN"],                         "text"),
    "ds_ativo":            (["DS_ATIVO"],                        "text"),
    "emissor_ligado":      (["EMISSOR_LIGADO"],                  "text"),
    "qt_pos_final":        (["QT_POS_FINAL"],                    "numeric"),
    "vl_merc_pos_final":   (["VL_MERC_POS_FINAL"],               "numeric"),
    "vl_custo_pos_final":  (["VL_CUSTO_POS_FINAL"],              "numeric"),
    "qt_aquis_negoc":      (["QT_AQUIS_NEGOC"],                  "numeric"),
    "vl_aquis_negoc":      (["VL_AQUIS_NEGOC"],                  "numeric"),
    "qt_venda_negoc":      (["QT_VENDA_NEGOC"],                  "numeric"),
    "vl_venda_negoc":      (["VL_VENDA_NEGOC"],                  "numeric"),
}
