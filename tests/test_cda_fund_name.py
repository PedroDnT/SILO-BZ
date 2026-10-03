"""cvm_fi_cda_fund_name (migration 60): the CDA fund name once per fund and month."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from src.pipeline import ingest_fi
from src.pipeline.ingest_fi import take_fund_names

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "src/store/migrations/60_fi_cda_fund_name.sql"
SCHEMA = ROOT / "src/store/schema.sql"
WORKFLOW = ROOT / ".github/workflows/daily_ingest.yml"


def _rec(cnpj, period, raw):
    return {"cnpj": cnpj, "period": period, "raw": dict(raw)}


def test_take_fund_names_pops_the_name_and_keeps_the_rest_of_raw():
    recs = [
        _rec("11111111000111", date(2026, 5, 1), {"DENOM_SOCIAL": "FUNDO A", "DT_CONFID_APLIC": None}),
        _rec("11111111000111", date(2026, 5, 1), {"DENOM_SOCIAL": "FUNDO A"}),
        _rec("22222222000122", date(2026, 5, 1), {"QT_AQUIS_NEGOC": "5"}),
    ]
    names = take_fund_names(recs)
    assert names == {("11111111000111", date(2026, 5, 1), "FUNDO A")}
    assert recs[0]["raw"] == {"DT_CONFID_APLIC": None}
    assert recs[1]["raw"] == {}
    assert recs[2]["raw"] == {"QT_AQUIS_NEGOC": "5"}


def test_two_names_for_one_fund_month_are_both_kept():
    recs = [
        _rec("11111111000111", date(2026, 5, 1), {"DENOM_SOCIAL": "FUNDO A"}),
        _rec("11111111000111", date(2026, 5, 1), {"DENOM_SOCIAL": "FUNDO A FIF"}),
    ]
    assert len(take_fund_names(recs)) == 2


def _ingest_holdings(rows):
    calls = []

    def fake_upsert(conn, table, recs, conflict_columns=None, **kw):
        calls.append((table, [dict(r) for r in recs], conflict_columns))
        return len(recs)

    # The holdings of a month go through the per-fund replace; same capture.
    saved = ingest_fi.upsert_rows, ingest_fi.replace_scoped_rows
    ingest_fi.upsert_rows = ingest_fi.replace_scoped_rows = fake_upsert
    try:
        ingest_fi.ingest_fi_cda_cotas(object(), rows, 2026, 5)
    finally:
        ingest_fi.upsert_rows, ingest_fi.replace_scoped_rows = saved
    return calls


def test_the_name_is_written_once_before_the_holdings_without_it():
    row = {
        "TP_FUNDO_CLASSE": "CLASSES - FIF", "CNPJ_FUNDO_CLASSE": "11.111.111/0001-11",
        "DENOM_SOCIAL": "FUNDO A", "DT_COMPTC": "2026-05-31",
        "TP_APLIC": "Cotas de Fundos", "TP_ATIVO": "Cotas de Fundos",
        "CNPJ_FUNDO_CLASSE_COTA": "22.222.222/0001-22", "VL_MERC_POS_FINAL": "10.00",
    }
    calls = _ingest_holdings([row])
    tables = [c[0] for c in calls]
    assert tables == ["cvm_fi_cda_fund_name", "cvm_fi_cda_cotas"]
    holding = calls[1][1][0]
    assert "DENOM_SOCIAL" not in holding["raw"]
    assert calls[0][1] == [{"cnpj": "11111111000111", "period": date(2026, 5, 1),
                            "denom_social": "FUNDO A"}]
    assert calls[0][2] == "cnpj,period,denom_social"


def _create_block(text: str) -> str:
    m = re.search(r"CREATE TABLE IF NOT EXISTS cvm_fi_cda_fund_name \((.*?)\n\);", text, re.S)
    assert m, "table definition missing"
    return re.sub(r"\s+", " ", m.group(1)).strip()


def test_schema_and_migration_define_the_same_table():
    block = _create_block(MIGRATION.read_text())
    assert block == _create_block(SCHEMA.read_text())
    assert "CONSTRAINT uq_fi_cda_fund_name UNIQUE (cnpj, period, denom_social)" in block


def test_strip_script_copies_before_it_removes_and_upserts():
    from scripts import strip_cda_fund_name as s

    assert s.TABLES == ("cvm_fi_cda_cotas", "cvm_fi_cda_acoes", "cvm_fi_cda")
    assert "ON CONFLICT ON CONSTRAINT uq_fi_cda_fund_name DO UPDATE" in s.COPY_SQL
    assert "raw - 'DENOM_SOCIAL'" in s.STRIP_SQL
    for sql in (s.COPY_SQL, s.STRIP_SQL):
        assert "ctid >= %(lo)s::tid AND ctid < %(hi)s::tid" in sql
    assert list(s.batches(45_000, 20_000)) == [
        ("(0,0)", "(20000,0)"), ("(20000,0)", "(40000,0)"), ("(40000,0)", "(45000,0)"),
    ]
    src = Path(s.__file__).read_text()
    assert src.index("cur.execute(copy_sql") < src.index("cur.execute(strip_sql")


def test_daily_ingest_offers_the_strip_as_its_own_mode():
    wf = WORKFLOW.read_text()
    assert "- cda-fund-name" in wf
    assert "mode == 'cda-fund-name' }}" in wf
    assert "python scripts/strip_cda_fund_name.py" in wf
