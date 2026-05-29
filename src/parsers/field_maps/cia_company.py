"""CIA_ABERTA company registry field map (W6).

Source CSV: cad_cia_aberta.csv (single, static, latin-1, ; delimited).
URL:        {base}/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv
Target:     cia_company  (PK = cd_cvm)

Header (verified live 2026-05-29 against the production CVM endpoint):
    CNPJ_CIA;DENOM_SOCIAL;DENOM_COMERC;DT_REG;DT_CONST;DT_CANCEL;
    MOTIVO_CANCEL;SIT;DT_INI_SIT;CD_CVM;SETOR_ATIV;TP_MERC;CATEG_REG;
    DT_INI_CATEG;SIT_EMISSOR;DT_INI_SIT_EMISSOR;CONTROLE_ACIONARIO;
    TP_ENDER;LOGRADOURO;COMPL;BAIRRO;MUN;UF;PAIS;CEP;DDD_TEL;TEL;
    DDD_FAX;FAX;EMAIL;TP_RESP;RESP;DT_INI_RESP;... (responsible/auditor
    contact fields fall through to raw JSONB).

Notes
-----
* The DDL schema column ``segmento`` has no direct source column in CAD.
  We map it from ``CATEG_REG`` (registry category — "Categoria A" / "B"),
  which is the closest analog to a market-segment identifier in this feed.
  ``CONTROLE_ACIONARIO`` (PRIVADO / ESTATAL / ESTRANGEIRO) is preserved
  in raw for downstream use.
* ``situacao`` maps from ``SIT`` (registry status); ``SIT_EMISSOR`` is
  more granular but reflects the issuer-state machine and is kept in raw.
* ``cd_cvm`` is the natural primary key; rows missing it are dropped by
  the ingest function.
"""

TABLE = "cia_company"
CONFLICT = ("cd_cvm",)

FIELD_MAP = {
    "cd_cvm":    (["CD_CVM"],                "text"),
    "cnpj_cia":  (["CNPJ_CIA"],              "cnpj"),
    "denom_cia": (["DENOM_SOCIAL"],          "text"),
    "setor":     (["SETOR_ATIV"],            "text"),
    "segmento":  (["CATEG_REG"],             "text"),
    "situacao":  (["SIT"],                   "text"),
}
