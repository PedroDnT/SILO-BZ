"""CIA_ABERTA FRE distribuição do capital field map — the free float.

Source CSV: fre_cia_aberta_distribuicao_capital_{YYYY}.csv (one member of the
            yearly FRE ZIP, latin-1, ; delimited). Published from 2010.
Target:     cia_fre_free_float (UNIQUE NULLS NOT DISTINCT on cnpj_cia,
            data_refer, versao; migration 87, #1161)

Header (verified live 2026-11-16 against fre_cia_aberta_2010.zip and
fre_cia_aberta_2025.zip):
    CNPJ_Companhia;Data_Referencia;Versao;ID_Documento;Nome_Companhia;
    Quantidade_Acionistas_PF;Quantidade_Acionistas_PJ;
    Quantidade_Acionistas_Investidores_Institucionais;
    Quantidade_Acoes_Ordinarias_Circulacao;Percentual_Acoes_Ordinarias_Circulacao;
    Quantidade_Acoes_Preferenciais_Circulacao;Percentual_Acoes_Preferenciais_Circulacao;
    Quantidade_Total_Acoes_Circulacao;Percentual_Total_Acoes_Circulacao;
    Data_Ultima_Assembleia

Notes
-----
* "Ações em circulação" is CVM's free float: shares not held by the
  controller, its related parties, management or in treasury. The counts and
  percentages are as filed; SILO does not recompute them.
* Data_Referencia is the form's reference date, not a filing date.
* Nome_Companhia is denormalised and falls through to raw.
"""

TABLE = "cia_fre_free_float"
CONFLICT = ("cnpj_cia", "data_refer", "versao")

FIELD_MAP = {
    "cnpj_cia":          (["CNPJ_Companhia"],                                   "cnpj"),
    "data_refer":        (["Data_Referencia"],                                  "date"),
    "versao":            (["Versao"],                                           "int"),
    "id_documento":      (["ID_Documento"],                                     "text"),
    "n_acionistas_pf":   (["Quantidade_Acionistas_PF"],                         "int"),
    "n_acionistas_pj":   (["Quantidade_Acionistas_PJ"],                         "int"),
    "n_acionistas_inst": (["Quantidade_Acionistas_Investidores_Institucionais"], "int"),
    "qt_ordin_circ":     (["Quantidade_Acoes_Ordinarias_Circulacao"],           "int"),
    "pct_ordin_circ":    (["Percentual_Acoes_Ordinarias_Circulacao"],           "pct"),
    "qt_pref_circ":      (["Quantidade_Acoes_Preferenciais_Circulacao"],        "int"),
    "pct_pref_circ":     (["Percentual_Acoes_Preferenciais_Circulacao"],        "pct"),
    "qt_total_circ":     (["Quantidade_Total_Acoes_Circulacao"],                "int"),
    "pct_total_circ":    (["Percentual_Total_Acoes_Circulacao"],                "pct"),
    "dt_ultima_assembleia": (["Data_Ultima_Assembleia"],                        "date"),
}
