"""FI fund-of-fund holdings (CDA block 2) field map.

Source CSV: cda_fi_BLC_2_{year}{month:02d}.csv, inside the same monthly ZIP the
`cda` dataset already downloads. Target table: cvm_fi_cda_cotas.

WHY THIS BLOCK. It carries CNPJ_FUNDO_CLASSE_COTA — the CNPJ of the fund being
held. That turns the fund universe into a graph rather than a list: who feeds
whom, and how much. EMISSOR_LIGADO ('S'/'N') says whether the held fund belongs
to the same economic group, which is the published signal behind the
captive-vehicle screen in 15_fraud_screens.sql — currently inferred from AUM and
investor counts rather than read from the filing.

COLUMN NAMES DRIFT. The 2023+ monthly files use CNPJ_FUNDO_CLASSE /
CNPJ_FUNDO_CLASSE_COTA / NM_FUNDO_CLASSE_SUBCLASSE_COTA / TP_FUNDO_CLASSE; the
yearly HIST archives (2005-2022) use CNPJ_FUNDO / CNPJ_FUNDO_COTA /
NM_FUNDO_COTA / TP_FUNDO. Without the fallbacks below every historical row
would fail the cnpj_cota check and be dropped — the whole block, silently, as
"no rows".

UNIQUE-KEY AUDIT across four real files (collisions are groups; "differ" means
the positions are not identical):

    key                                          2005  2015    2022  202606
    cnpj+period+cnpj_cota                          46     3       1  UNIQUE
    + tp_aplic + tp_negoc                          35     0       1  UNIQUE
    + tp_aplic + tp_negoc + tp_fundo (shipped)  UNIQUE  UNIQUE  UNIQUE  UNIQUE

The monthly file alone reports the bare key as UNIQUE, which is how the first
version of this map came to ship with it. On the yearly files a fund holds the
same fund under two application types ("Cotas de fundos de renda fixa" vs
"Cotas de fundos de investimento - Instrução Nº 409") and under two trading
intents, with different positions; and in 2005 one CNPJ filed as both FI and
FIF. All four columns are needed, and together they are exactly unique.

ID_SUBCLASSE is deliberately not in the key: it is empty in every row of every
audited file, so it would buy nothing today and change the grain the moment
CVM starts populating it.
"""

TABLE = "cvm_fi_cda_cotas"
CONFLICT = ("cnpj", "period", "tp_fundo", "cnpj_cota", "tp_aplic", "tp_negoc")

FIELD_MAP = {
    "cnpj":                (["CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"],   "cnpj"),
    "tp_fundo":            (["TP_FUNDO_CLASSE", "TP_FUNDO"],       "text"),
    # Recomputed as first-of-month by the ingest module; listed so DT_COMPTC is
    # consumed rather than duplicated into raw.
    "period":              (["DT_COMPTC"],                          "date"),
    "cnpj_cota":           (["CNPJ_FUNDO_CLASSE_COTA",
                            "CNPJ_FUNDO_COTA"],                  "cnpj"),
    "nm_fundo_cota":       (["NM_FUNDO_CLASSE_SUBCLASSE_COTA",
                            "NM_FUNDO_COTA"],                    "text"),
    "tp_aplic":            (["TP_APLIC"],                           "text"),
    "tp_ativo":            (["TP_ATIVO"],                           "text"),
    "tp_negoc":            (["TP_NEGOC"],                           "text"),
    "emissor_ligado":      (["EMISSOR_LIGADO"],                     "text"),
    "qt_pos_final":        (["QT_POS_FINAL"],                       "numeric"),
    "vl_merc_pos_final":   (["VL_MERC_POS_FINAL"],                  "numeric"),
    "vl_custo_pos_final":  (["VL_CUSTO_POS_FINAL"],                 "numeric"),
    "qt_aquis_negoc":      (["QT_AQUIS_NEGOC"],                     "numeric"),
    "vl_aquis_negoc":      (["VL_AQUIS_NEGOC"],                     "numeric"),
    "qt_venda_negoc":      (["QT_VENDA_NEGOC"],                     "numeric"),
    "vl_venda_negoc":      (["VL_VENDA_NEGOC"],                     "numeric"),
}
