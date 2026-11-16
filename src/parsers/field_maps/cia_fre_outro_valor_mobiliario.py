"""CIA_ABERTA FRE "outros valores mobiliários" field map (#1164).

Source CSV: fre_cia_aberta_outro_valor_mobiliario_{YYYY}.csv (one member of
            the yearly FRE ZIP, latin-1, ; delimited, quoted multi-line text).
URL:        {base}/CIA_ABERTA/DOC/FRE/DADOS/fre_cia_aberta_{YYYY}.zip
Target:     cvm_fre_outro_valor_mobiliario  (UNIQUE on cnpj_cia, data_refer,
            versao, id_documento, row_hash — migration 86)

Header (identical in the 2010, 2016, 2025 and 2026 archives, checked
2026-11-16):
    CNPJ_Companhia;Data_Referencia;Versao;ID_Documento;Nome_Companhia;
    Valor_Mobiliario;Identificacao_Valor_Mobiliario;Data_Emissao;
    Data_Vencimento;Quantidade;Valor;Quantidade_Pessoa_Fisica;
    Quantidade_Pessoa_Juridica;Quantidade_Investidor_Institucional;
    Saldo_Devedor;Restricao_Circulacao;Descricao_Restricao_Circulacao;
    Conversibilidade;Condicao_Conversibilidade_Efeito_Capital_Social;
    Resgatavel;Hipotese_Resgate_Formula_Calculo;
    Caracteristicas_Valores_Mobiliarios_Divida;Condicao_Alteracao_Direitos;
    Outras_Caracteristicas_Relevantes

Notes
-----
* One row is one issue as the company describes it (often several series
  in one row). No ticker, ISIN or series code is published.
* The file has no unique row key: in the 2025 archive the document id plus
  the issue name repeat for 47 rows, and even seven descriptive columns
  together repeat for 9. ``row_hash`` (sha256 of the source row) ends the
  key, as for the FII property register. 4 rows are exact repeats and
  collapse into one.
* Rate and indexer exist only in the free text
  ``Caracteristicas_Valores_Mobiliarios_Divida``, written differently by
  each company. The text is stored as filed and is never parsed.
* The three flags hold "Sim" or nothing; nothing stays NULL.
* Long free-text columns not mapped here fall through to ``raw``.
"""

TABLE = "cvm_fre_outro_valor_mobiliario"
CONFLICT = ("cnpj_cia", "data_refer", "versao", "id_documento", "row_hash")

FIELD_MAP = {
    "cnpj_cia":               (["CNPJ_Companhia"],                             "cnpj"),
    "data_refer":             (["Data_Referencia"],                            "date"),
    "versao":                 (["Versao"],                                     "int"),
    "id_documento":           (["ID_Documento"],                               "text"),
    "nome_companhia":         (["Nome_Companhia"],                             "text"),
    "valor_mobiliario":       (["Valor_Mobiliario"],                           "text"),
    "identificacao":          (["Identificacao_Valor_Mobiliario"],             "text"),
    "data_emissao":           (["Data_Emissao"],                               "date"),
    "data_vencimento":        (["Data_Vencimento"],                            "date"),
    "quantidade":             (["Quantidade"],                                 "numeric"),
    "valor":                  (["Valor"],                                      "numeric"),
    "saldo_devedor":          (["Saldo_Devedor"],                              "numeric"),
    "restricao_circulacao":   (["Restricao_Circulacao"],                       "bool"),
    "conversibilidade":       (["Conversibilidade"],                           "bool"),
    "resgatavel":             (["Resgatavel"],                                 "bool"),
    "caracteristicas_divida": (["Caracteristicas_Valores_Mobiliarios_Divida"], "text"),
}
