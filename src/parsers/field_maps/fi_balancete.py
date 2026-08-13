"""Field map for FI BALANCETE (monthly balance sheet).

Source: https://dados.cvm.gov.br/dados/FI/DOC/BALANCETE/DADOS/balancete_fi_{YYYYMM}.zip
        → balancete_fi_{YYYYMM}.csv  (latin-1, ';'-delimited)

Actual CSV headers confirmed from 2025-01 sample:
    TP_FUNDO_CLASSE ; CNPJ_FUNDO_CLASSE ; DT_COMPTC
    PLANO_CONTA_BALCTE ; CD_CONTA_BALCTE ; VL_SALDO_BALCTE

One row per fund × reference date × account code.
Natural key: (cnpj, dt_comptc, cd_conta_balcte).

Unique-key audit (real balancete_fi_202606.csv): header is exactly the six
columns above — no ID_SUBCLASSE. 2,178,163 rows, zero same-key dual
TP_FUNDO_CLASSE labels. Do not widen the key without a new CVM header.
"""

TABLE = "cvm_fi_balancete"

# Tuple of column names used in ON CONFLICT (must match UNIQUE constraint)
CONFLICT = ("cnpj", "dt_comptc", "cd_conta_balcte")

# db_column: (["CSV_CANDIDATE_NAMES", ...], "coerce_type")
# coerce_type: cnpj | text | int | numeric | date | pct | bool
FIELD_MAP = {
    "cnpj":               (["CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"],       "cnpj"),
    "dt_comptc":          (["DT_COMPTC"],                              "date"),
    "plano_conta_balcte": (["PLANO_CONTA_BALCTE"],                     "text"),
    "cd_conta_balcte":    (["CD_CONTA_BALCTE"],                        "text"),
    "vl_saldo_balcte":    (["VL_SALDO_BALCTE"],                        "numeric"),
    "tp_fundo_classe":    (["TP_FUNDO_CLASSE", "TP_FUNDO"],            "text"),
}
