"""CIA_ABERTA FCA valores-mobiliários field map — the published CNPJ↔ticker map.

Source CSV: fca_cia_aberta_valor_mobiliario_{YYYY}.csv (one member of the
            yearly FCA ZIP, latin-1, ; delimited).
URL:        {base}/CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_{YYYY}.zip
Target:     cia_ticker  (UNIQUE on cnpj_cia, data_refer, versao,
            valor_mobiliario, codneg, mercado — NULLS NOT DISTINCT)

Header (verified live 2026-08-27 against fca_cia_aberta_2026.zip):
    CNPJ_Companhia;Data_Referencia;Versao;ID_Documento;Nome_Empresarial;
    Valor_Mobiliario;Sigla_Classe_Acao_Preferencial;Classe_Acao_Preferencial;
    Codigo_Negociacao;Composicao_BDR_Unit;Mercado;
    Sigla_Entidade_Administradora;Entidade_Administradora;
    Data_Inicio_Negociacao;Data_Fim_Negociacao;Segmento;
    Data_Inicio_Listagem;Data_Fim_Listagem

Notes
-----
* This is the ONLY sanctioned company↔ticker join in the warehouse: both
  sides come from the same published CVM row, so no identity is synthesized
  (integrity rule 3). ``vw_company_ticker`` (migration 25) dedupes to the
  newest (data_refer, versao) per (cnpj, codneg).
* ``Codigo_Negociacao`` can be empty (unlisted securities, some Balcão
  rows); those rows are kept — they still describe the company's securities
  — but the bridge view naturally skips them.
* ``Versao`` is part of the key, like cia_event: CVM re-files FCA documents
  and every published version is preserved; consumers take the max.
* ``Nome_Empresarial`` is denormalised (authoritative name in cia_company)
  and falls through to raw.
"""

TABLE = "cia_ticker"
CONFLICT = (
    "cnpj_cia",
    "data_refer",
    "versao",
    "valor_mobiliario",
    "codneg",
    "mercado",
)

FIELD_MAP = {
    "cnpj_cia":         (["CNPJ_Companhia"],                 "cnpj"),
    "data_refer":       (["Data_Referencia"],                "date"),
    "versao":           (["Versao"],                         "int"),
    "id_documento":     (["ID_Documento"],                   "text"),
    "valor_mobiliario": (["Valor_Mobiliario"],               "text"),
    "sigla_classe":     (["Sigla_Classe_Acao_Preferencial"], "text"),
    "codneg":           (["Codigo_Negociacao"],              "text"),
    "mercado":          (["Mercado"],                        "text"),
    "segmento":         (["Segmento"],                       "text"),
    "dt_inicio_neg":    (["Data_Inicio_Negociacao"],         "date"),
    "dt_fim_neg":       (["Data_Fim_Negociacao"],            "date"),
    "dt_inicio_list":   (["Data_Inicio_Listagem"],           "date"),
    "dt_fim_list":      (["Data_Fim_Listagem"],              "date"),
}
