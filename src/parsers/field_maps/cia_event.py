"""CIA_ABERTA IPE (material facts) field map (W6).

Source CSV: ipe_cia_aberta_{YYYY}.csv (single CSV inside the yearly zip,
            latin-1, ; delimited).
URL:        {base}/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_{YYYY}.zip
Target:     cia_event  (UNIQUE on protocolo, versao)

Header (verified live 2026-05-29 against ipe_cia_aberta_2024.zip):
    CNPJ_Companhia;Nome_Companhia;Codigo_CVM;Data_Referencia;
    Categoria;Tipo;Especie;Assunto;Data_Entrega;
    Tipo_Apresentacao;Protocolo_Entrega;Versao;Link_Download

Notes
-----
* ``Nome_Companhia`` is denormalised against ``Codigo_CVM`` / ``CNPJ_Companhia``
  and is not stored as a typed column — it falls through to raw and the
  authoritative name lives in cia_company (joinable by cd_cvm).
* ``Tipo_Apresentacao`` (e.g. "AP - Apresentação", "RE - Reapresentação
  Espontânea") is preserved in raw for now; it can be promoted later if a
  filter UI requires it.
* The natural key is (Protocolo_Entrega, Versao). The PK on cia_event is a
  surrogate BIGSERIAL; the UNIQUE constraint enforces idempotency.
"""

TABLE = "cia_event"
CONFLICT = ("protocolo", "versao")

FIELD_MAP = {
    "cd_cvm":        (["Codigo_CVM"],         "cd_cvm"),
    "cnpj_cia":      (["CNPJ_Companhia"],     "cnpj"),
    "data_refer":    (["Data_Referencia"],    "date"),
    "data_entrega":  (["Data_Entrega"],       "date"),
    "categoria":     (["Categoria"],          "text"),
    "tipo":          (["Tipo"],               "text"),
    "especie":       (["Especie"],            "text"),
    "assunto":       (["Assunto"],            "text"),
    "protocolo":     (["Protocolo_Entrega"],  "text"),
    "versao":        (["Versao"],             "int"),
    "link_download": (["Link_Download"],      "text"),
}
