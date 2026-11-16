"""CIA_ABERTA composição do capital field map — issued and treasury share counts.

Source CSV: itr_cia_aberta_composicao_capital_{YYYY}.csv and
            dfp_cia_aberta_composicao_capital_{YYYY}.csv (one member of the
            yearly ITR / DFP ZIP, latin-1, ; delimited). Published from 2020.
Target:     cia_share_count (UNIQUE NULLS NOT DISTINCT on cnpj_cia, doc_type,
            dt_refer, versao; migration 86, #1161)

Header (verified live 2026-11-16 against the ITR 2025 and DFP 2025 ZIPs):
    CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;QT_ACAO_ORDIN_CAP_INTEGR;
    QT_ACAO_PREF_CAP_INTEGR;QT_ACAO_TOTAL_CAP_INTEGR;QT_ACAO_ORDIN_TESOURO;
    QT_ACAO_PREF_TESOURO;QT_ACAO_TOTAL_TESOURO

Notes
-----
* The counts are as filed: CVM's own ON / PN / total split of the paid-in
  capital, and the treasury shares. Nothing is added or derived.
* doc_type (itr | dfp) is not a CSV column; the ingest sets it from the slice.
* DENOM_CIA is denormalised (cia_company holds the name) and falls through
  to raw.
"""

TABLE = "cia_share_count"
CONFLICT = ("cnpj_cia", "doc_type", "dt_refer", "versao")

FIELD_MAP = {
    "cnpj_cia":        (["CNPJ_CIA"],                "cnpj"),
    "dt_refer":        (["DT_REFER"],                "date"),
    "versao":          (["VERSAO"],                  "int"),
    "qt_ordin":        (["QT_ACAO_ORDIN_CAP_INTEGR"], "int"),
    "qt_pref":         (["QT_ACAO_PREF_CAP_INTEGR"],  "int"),
    "qt_total":        (["QT_ACAO_TOTAL_CAP_INTEGR"], "int"),
    "qt_ordin_tesouro": (["QT_ACAO_ORDIN_TESOURO"],   "int"),
    "qt_pref_tesouro":  (["QT_ACAO_PREF_TESOURO"],    "int"),
    "qt_total_tesouro": (["QT_ACAO_TOTAL_TESOURO"],   "int"),
}
