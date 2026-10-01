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

# The account-level table. Retired by migration 62 (emptied once
# cvm_fi_balancete_resumo covered every stored month); the ingest no longer
# writes it, and only scripts/backfill_balancete_summary.py reads it.
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

# cvm_fi_balancete_resumo (migration 59): one row per fund and month, holding
# the COFI group totals and the administrative-expense accounts. Code ->
# column. An account the fund did not file stays NULL. The codes, their
# source and the identities they satisfy are in migration 59.
RESUMO_TABLE = "cvm_fi_balancete_resumo"
RESUMO_CONFLICT = ("cnpj", "dt_comptc")
RESUMO_ACCOUNTS = {
    "10000007": "vl_ativo",
    "30000001": "vl_compensacao_ativa",
    "40000008": "vl_passivo",
    "60000002": "vl_patrimonio_sem_resultado",
    "70000009": "vl_receitas",
    "80000006": "vl_despesas",
    "90000003": "vl_compensacao_passiva",
    "81700006": "vl_desp_administrativas",
    "81754007": "vl_desp_servicos_financeiros",
    "81763005": "vl_desp_servicos_tecnicos",
    "81781001": "vl_taxa_administracao",
    "81781056": "vl_taxa_adm_efetiva",
    "81781104": "vl_taxa_gestao",
    "81781252": "vl_taxa_distribuicao",
    "81782000": "vl_taxa_performance",
    "81783009": "vl_taxa_ingresso_saida",
}
