"""FII INF_TRIMESTRAL — COMPLEMENTO member field map.

Source CSV: inf_trimestral_fii_complemento_{year}.csv, inside
            inf_trimestral_fii_{year}.zip (latin-1, ';'-delimited, 48 fields).
Target table: cvm_fii_periodic, doc_type='trimestral_complemento'.

GRAIN: one row per (fund, quarter) — 4,577 rows / 4,577 distinct
(CNPJ_Fundo_Classe, Data_Referencia) in the real 2025 archive.

WHAT IS LIFTED
--------------
The member's 48 fields are three families:
  * a 12-bucket receivable maturity ladder (Percentual_Vencimento_*), each bucket
    reported twice — once as a share of contract value, once as a share of FII
    revenue,
  * inflation-indexer exposure (IGPM / INPC / IPCA / INCC), same double reporting,
  * the liquidity block (Ativo_Liquidez_Valor_*), in BRL.

The liquidity block and the four indexer value shares are typed here because
they answer "how is this FII's income indexed, and how much of its book is
actually liquid". The 24 maturity-ladder columns stay in residual `raw` — a
ladder is better modelled as a long fact than as 24 wide columns (see
docs/DATA_MODELING.md), and nothing queries it yet.
"""

TABLE = "cvm_fii_periodic"
DOC_TYPE = "trimestral_complemento"
CONFLICT = ("cnpj", "doc_type", "period_year", "data_referencia")

FIELD_MAP = {
    "cnpj":            (["CNPJ_Fundo_Classe", "CNPJ_FUNDO_CLASSE", "CNPJ_Fundo"], "cnpj"),
    "data_referencia": (["Data_Referencia", "DT_COMPTC"], "date"),
    "versao":          (["Versao"],                        "int"),

    # Inflation-indexer exposure, as a share of total contract value
    "pr_indexador_igpm": (["Percentual_Indexador_Valor_Total_IGPM"], "pct"),
    "pr_indexador_inpc": (["Percentual_Indexador_Valor_Total_INPC"], "pct"),
    "pr_indexador_ipca": (["Percentual_Indexador_Valor_Total_IPCA"], "pct"),
    "pr_indexador_incc": (["Percentual_Indexador_Valor_Total_INCC"], "pct"),

    # Liquidity block (BRL)
    "ativo_liquidez_disponibilidades":  (["Ativo_Liquidez_Valor_Disponibilidades"],  "numeric"),
    "ativo_liquidez_titulos_publicos":  (["Ativo_Liquidez_Valor_Titulos_Publicos"],  "numeric"),
    "ativo_liquidez_titulos_privados":  (["Ativo_Liquidez_Valor_Titulos_Privados"],  "numeric"),
    "ativo_liquidez_fundos_renda_fixa": (["Ativo_Liquidez_Valor_Fundos_Renda_Fixa"], "numeric"),
}
