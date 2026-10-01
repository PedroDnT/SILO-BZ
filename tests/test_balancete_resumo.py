"""cvm_fi_balancete_resumo (migration 59): one row per fund and month of COFI group totals."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from unittest.mock import patch

from src.parsers.field_maps import fi_balancete as _balancete
from src.pipeline import ingest_fi
from src.pipeline.ingest_fi import balancete_resumo

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "src/store/migrations/59_fi_balancete_resumo.sql"
SCHEMA = ROOT / "src/store/schema.sql"
WORKFLOW = ROOT / ".github/workflows/daily_ingest.yml"


def _row(cnpj, code, value, dt=date(2026, 6, 30)):
    return {
        "TP_FUNDO_CLASSE": "CLASSES - FIF",
        "CNPJ_FUNDO_CLASSE": cnpj,
        "DT_COMPTC": dt.isoformat(),
        "PLANO_CONTA_BALCTE": "COFI",
        "CD_CONTA_BALCTE": code,
        "VL_SALDO_BALCTE": value,
    }


# A fund whose groups satisfy assets = liabilities + equity + revenue + expenses
# (1000 = 100 + 800 + 150 - 50), plus detail accounts that are not groups.
FUND_A = [
    _row("11.111.111/0001-11", "10000007", "1000.00"),
    _row("11.111.111/0001-11", "40000008", "100.00"),
    _row("11.111.111/0001-11", "60000002", "800.00"),
    _row("11.111.111/0001-11", "70000009", "150.00"),
    _row("11.111.111/0001-11", "80000006", "-50.00"),
    _row("11.111.111/0001-11", "30000001", "7000.00"),
    _row("11.111.111/0001-11", "90000003", "7000.00"),
    _row("11.111.111/0001-11", "71100001", "150.00"),
    # administrative expenses inside group 8: admin fee 30, performance fee 20
    _row("11.111.111/0001-11", "81700006", "-50.00"),
    _row("11.111.111/0001-11", "81781001", "-30.00"),
    _row("11.111.111/0001-11", "81782000", "-20.00"),
]
# A fund that filed no liabilities group: that column must stay NULL, not 0.
FUND_B = [
    _row("22.222.222/0001-22", "10000007", "500.00"),
    _row("22.222.222/0001-22", "60000002", "500.00"),
]


def _ingest(rows):
    calls = {}

    def fake_upsert(conn, table, recs, conflict_columns=None):
        calls[table] = (list(recs), conflict_columns)
        return len(recs)

    with patch.object(ingest_fi, "upsert_rows", side_effect=fake_upsert):
        n = ingest_fi.ingest_fi_balancete(object(), rows)
    return n, calls


def test_ingest_writes_accounts_and_one_summary_row_per_fund_month():
    n, calls = _ingest(FUND_A + FUND_B)
    assert n == len(FUND_A) + len(FUND_B)
    resumo, conflict = calls[_balancete.RESUMO_TABLE]
    assert conflict == "cnpj,dt_comptc"
    by_cnpj = {r["cnpj"]: r for r in resumo}
    assert set(by_cnpj) == {"11111111000111", "22222222000122"}

    a = by_cnpj["11111111000111"]
    assert a["dt_comptc"] == date(2026, 6, 30)
    assert float(a["vl_ativo"]) == 1000.0
    assert float(a["vl_passivo"]) == 100.0
    assert float(a["vl_patrim_liq"]) == 800.0
    assert float(a["vl_receitas"]) == 150.0
    assert float(a["vl_despesas"]) == -50.0
    assert float(a["vl_compensacao_ativa"]) == float(a["vl_compensacao_passiva"]) == 7000.0
    assert float(a["vl_desp_administrativas"]) == -50.0
    assert float(a["vl_taxa_administracao"]) == -30.0
    assert float(a["vl_taxa_performance"]) == -20.0
    assert a["vl_taxa_gestao"] is None  # not filed by this fund
    assert a["n_contas"] == 11
    assert a["plano_conta_balcte"] == "COFI"
    assert a["tp_fundo_classe"] == "CLASSES - FIF"
    total = (a["vl_passivo"] + a["vl_patrim_liq"] + a["vl_receitas"] + a["vl_despesas"])
    assert float(a["vl_ativo"]) == float(total)


def test_a_group_the_fund_did_not_file_is_null_never_zero():
    _, calls = _ingest(FUND_B)
    (b,) = calls[_balancete.RESUMO_TABLE][0]
    assert b["vl_passivo"] is None
    assert b["vl_receitas"] is None
    assert b["n_contas"] == 2


def test_a_repeated_code_counts_once_with_its_last_value():
    recs = [
        {"cnpj": "33333333000133", "dt_comptc": date(2026, 6, 30),
         "cd_conta_balcte": "10000007", "vl_saldo_balcte": 1},
        {"cnpj": "33333333000133", "dt_comptc": date(2026, 6, 30),
         "cd_conta_balcte": "10000007", "vl_saldo_balcte": 2},
    ]
    (r,) = balancete_resumo(recs)
    assert r["vl_ativo"] == 2
    assert r["n_contas"] == 1


def test_no_rows_writes_nothing():
    n, calls = _ingest([])
    assert n == 0 and calls == {}


def _create_block(text: str) -> str:
    m = re.search(r"CREATE TABLE IF NOT EXISTS cvm_fi_balancete_resumo \((.*?)\n\);", text, re.S)
    assert m, "table definition missing"
    return re.sub(r"\s+", " ", m.group(1)).strip()


def test_schema_and_migration_define_the_same_table():
    assert _create_block(MIGRATION.read_text()) == _create_block(SCHEMA.read_text())


def test_every_group_column_exists_in_the_table():
    block = _create_block(MIGRATION.read_text())
    for col in _balancete.RESUMO_ACCOUNTS.values():
        assert re.search(rf"\b{col}\b NUMERIC", block), col
    assert "CONSTRAINT uq_fi_balancete_resumo UNIQUE (cnpj, dt_comptc)" in block


def test_backfill_sql_uses_the_same_code_map_and_upserts():
    from scripts.backfill_balancete_summary import build_upsert_sql, _months

    sql = build_upsert_sql()
    for code, col in _balancete.RESUMO_ACCOUNTS.items():
        assert f"cd_conta_balcte = '{code}') AS {col}" in sql
        assert f"{col} = EXCLUDED.{col}" in sql
    assert "ON CONFLICT ON CONSTRAINT uq_fi_balancete_resumo DO UPDATE" in sql
    assert "dt_comptc >= %(lo)s AND dt_comptc < %(hi)s" in sql

    months = list(_months(date(2025, 11, 1), date(2026, 2, 1)))
    assert months == [
        (date(2025, 11, 1), date(2025, 12, 1)),
        (date(2025, 12, 1), date(2026, 1, 1)),
        (date(2026, 1, 1), date(2026, 2, 1)),
        (date(2026, 2, 1), date(2026, 3, 1)),
    ]


def test_daily_ingest_offers_the_backfill_as_its_own_mode():
    wf = WORKFLOW.read_text()
    assert "- balancete-summary" in wf
    assert "mode == 'balancete-summary' }}" in wf
    assert "python scripts/backfill_balancete_summary.py" in wf
