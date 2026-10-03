"""Per-fund replace of a re-read CDA month (gap 2 of PR #554).

The daily run re-reads the four CDA blocks of every month until M+5 ends. Re-reads
used to be upsert-only, so a position a fund dropped in a re-filing stayed stored,
and a changed block-6 row (key ends in row_hash) landed beside the old one. Now
every fund PRESENT in the new file ends up holding exactly the rows the file
carries for it; a fund absent from the file is never touched.

No database: `_FakeDB` plays Postgres for the handful of statements
`replace_scoped_rows` sends, honouring the transaction (BEGIN / COMMIT /
ROLLBACK), the comparison operator the DELETE asks for, and each arbiter's NULL
semantics. The same SQL was run once against a real PostgreSQL 16 while this was
written (scenarios below, plus a failed second batch); that run is not repeated
here because CI has no database.
"""
from __future__ import annotations

import asyncio
import copy
import re
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import src.store.pg_client as pg_client
from src.parsers.field_maps import fi_cda as _cda
from src.parsers.field_maps import fi_cda_acoes as _acoes
from src.parsers.field_maps import fi_cda_cotas as _cotas
from src.parsers.field_maps import fi_cda_debentures as _deb
from src.pipeline import ingest_fi

ROOT = Path(__file__).resolve().parents[1]

A = "00.102.322/0001-41"
B = "00.068.305/0001-35"
A14, B14 = "00102322000141", "00068305000135"

# The arbiter of each table: True when its unique key is NULLS DISTINCT.
_NULLS_DISTINCT = {
    "cvm_fi_cda": True,
    "cvm_fi_cda_acoes": False,
    "cvm_fi_cda_cotas": False,
    "cvm_fi_cda_debentures": False,
    "cvm_fi_cda_fund_name": True,
}


class _FakeDB:
    def __init__(self):
        self.tables = {t: [] for t in _NULLS_DISTINCT}
        self.snapshot = None
        self.keys_cols = None
        self.keys = []
        self.log = []          # every statement, in order
        self.fail_on = None    # (table, nth upsert) that raises

    # -- what a cursor does ---------------------------------------------------
    def execute(self, cur, sql, params=None):
        self.log.append(sql.split()[0] if sql.split() else sql)
        if sql == "BEGIN":
            self.snapshot = copy.deepcopy(self.tables)
        elif sql == "COMMIT":
            self.snapshot = None
        elif sql == "ROLLBACK":
            self.tables, self.snapshot = self.snapshot, None
        elif sql.startswith("CREATE TEMP TABLE _replace_keys"):
            cols = re.search(r"SELECT (.*?) FROM", sql).group(1)
            self.keys_cols = [c.strip() for c in cols.split(",")]
            self.keys = []
        elif sql.startswith("ANALYZE"):
            pass
        elif sql.startswith("DELETE FROM"):
            table = sql.split()[2]
            not_distinct = "IS NOT DISTINCT FROM" in sql
            keys = [dict(zip(self.keys_cols, k)) for k in self.keys]
            scopes = {(k["cnpj"], k["period"]) for k in keys}

            def same(stored, new):
                for c in self.keys_cols:
                    a, b = stored.get(c), new.get(c)
                    if a is None or b is None:
                        if not (not_distinct and a is None and b is None):
                            return False
                    elif a != b:
                        return False
                return True

            kept, gone = [], 0
            for row in self.tables[table]:
                if (row["cnpj"], row["period"]) in scopes and not any(same(row, k) for k in keys):
                    gone += 1
                else:
                    kept.append(row)
            self.tables[table] = kept
            cur.rowcount = gone
        else:
            raise AssertionError(f"unexpected SQL: {sql[:80]}")

    def execute_values(self, cur, sql, values, page_size=None):
        if sql.startswith("INSERT INTO _replace_keys"):
            self.log.append("KEYS")
            self.keys.extend(values)
            return
        m = re.match(r"INSERT INTO (\w+) \((.*?)\) VALUES %s ON CONFLICT \((.*?)\)", sql)
        table, cols, conflict = m.group(1), m.group(2).split(", "), m.group(3).split(",")
        self.log.append(f"UPSERT {table} {len(values)}")
        if self.fail_on and self.fail_on[0] == table:
            self.fail_on = (table, self.fail_on[1] - 1)
            if self.fail_on[1] == 0:
                raise RuntimeError("boom")
        distinct = _NULLS_DISTINCT[table]
        for v in values:
            new = dict(zip(cols, v))
            key = [new.get(c) for c in conflict]
            hit = None
            if not (distinct and any(x is None for x in key)):
                for row in self.tables[table]:
                    if [row.get(c) for c in conflict] == key:
                        hit = row
                        break
            if hit is None:
                self.tables[table].append(new)
            else:
                hit.update(new)

    # -- what pg_client sees ----------------------------------------------------
    @contextmanager
    def cursor(self):
        db = self

        class _Cur:
            rowcount = -1

            def execute(self, sql, params=None):
                db.execute(self, sql, params)

        yield _Cur()

    def reconnect(self):
        pass

    def held(self, table, col):
        return sorted((r["cnpj"], r.get(col)) for r in self.tables[table])


@pytest.fixture
def db(monkeypatch):
    fake = _FakeDB()
    monkeypatch.setattr(
        pg_client.psycopg2.extras, "execute_values",
        lambda cur, sql, values, page_size=None: fake.execute_values(cur, sql, values, page_size),
    )
    return fake


def _acao(cnpj, ticker, qt="1"):
    return {
        "CNPJ_FUNDO_CLASSE": cnpj, "DT_COMPTC": "2026-06-30", "TP_FUNDO_CLASSE": "FI",
        "TP_APLIC": "Ações", "TP_ATIVO": "Ação ordinária", "TP_NEGOC": "Para negociação",
        "CD_ATIVO": ticker, "QT_POS_FINAL": qt, "VL_MERC_POS_FINAL": "10.0",
    }


def _debenture(cnpj, value):
    return {
        "CNPJ_FUNDO_CLASSE": cnpj, "DT_COMPTC": "2026-06-30", "TP_FUNDO_CLASSE": "FI",
        "TP_APLIC": "Debêntures", "TP_ATIVO": "Debênture simples",
        "CPF_CNPJ_EMISSOR": "33.000.167/0001-01", "PF_PJ_EMISSOR": "PJ",
        "DT_VENC": "2030-01-15", "TP_NEGOC": "Para negociação", "VL_MERC_POS_FINAL": value,
    }


def _bond(cnpj):
    return {
        "CNPJ_FUNDO_CLASSE": cnpj, "DT_COMPTC": "2026-06-30", "TP_FUNDO_CLASSE": "FI",
        "TP_APLIC": "Títulos Públicos", "TP_ATIVO": "Título público federal",
        "CD_ISIN": "BRSTNCLF1RU6", "TP_NEGOC": "Para negociação", "VL_MERC_POS_FINAL": "5",
    }


# ── the four scenarios the owner asked for ───────────────────────────────────

def test_a_fund_that_drops_a_position_loses_it(db):
    ingest_fi.ingest_fi_cda_acoes(db, [_acao(A, "ITUB3"), _acao(A, "PETR4"), _acao(B, "VALE3")], 2026, 6)
    stats = {}
    ingest_fi.ingest_fi_cda_acoes(db, [_acao(A, "ITUB3", "2"), _acao(B, "VALE3")], 2026, 6, stats)
    assert db.held("cvm_fi_cda_acoes", "cd_ativo") == [(B14, "VALE3"), (A14, "ITUB3")]
    assert stats == {"rows_deleted": 1}


def test_a_fund_absent_from_the_new_file_keeps_its_rows(db):
    """A partial or truncated file must never erase the funds it does not carry."""
    ingest_fi.ingest_fi_cda_acoes(db, [_acao(A, "ITUB3"), _acao(B, "VALE3"), _acao(B, "ABEV3")], 2026, 6)
    stats = {}
    ingest_fi.ingest_fi_cda_acoes(db, [_acao(A, "ITUB3")], 2026, 6, stats)
    assert db.held("cvm_fi_cda_acoes", "cd_ativo") == [
        (B14, "ABEV3"), (B14, "VALE3"), (A14, "ITUB3"),
    ]
    assert stats == {"rows_deleted": 0}


def test_a_refiled_block6_row_replaces_the_old_one(db):
    """Block 6 keys on row_hash: without the replace the changed row lands beside the old."""
    ingest_fi.ingest_fi_cda_debentures(db, [_debenture(A, "100.0"), _debenture(B, "50.0")], 2026, 6)
    stats = {}
    ingest_fi.ingest_fi_cda_debentures(db, [_debenture(A, "101.0"), _debenture(B, "50.0")], 2026, 6, stats)
    held = sorted((r["cnpj"], r["vl_merc_pos_final"]) for r in db.tables["cvm_fi_cda_debentures"])
    assert held == [(B14, 50.0), (A14, 101.0)]
    assert stats == {"rows_deleted": 1}


def test_a_parse_failure_deletes_nothing(db, monkeypatch):
    """The replace runs only after the whole file parsed: a failure mid-file writes nothing."""
    ingest_fi.ingest_fi_cda_acoes(db, [_acao(A, "ITUB3"), _acao(A, "PETR4")], 2026, 6)
    db.log.clear()
    real = ingest_fi.apply_map
    calls = {"n": 0}

    def flaky(row, field_map):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ValueError("malformed row")
        return real(row, field_map)

    monkeypatch.setattr(ingest_fi, "apply_map", flaky)
    with pytest.raises(ValueError):
        ingest_fi.ingest_fi_cda_acoes(db, [_acao(A, "ITUB3"), _acao(A, "BBAS3")], 2026, 6)
    assert db.log == [], "no statement may reach the database before the file has parsed"
    assert db.held("cvm_fi_cda_acoes", "cd_ativo") == [(A14, "ITUB3"), (A14, "PETR4")]


def test_a_failed_slice_logs_no_deletion_when_nothing_was_written(monkeypatch):
    """Pipeline level: a fetch or parse error finishes the slice with rows_deleted unset."""
    from src.pipeline.cvm_pipeline import CVMIngestor

    ing = CVMIngestor.__new__(CVMIngestor)
    ing._supabase = object()
    finished = []
    monkeypatch.setattr(ing, "_log_start", lambda *a: None, raising=False)
    monkeypatch.setattr(ing, "_log_finish", lambda *a, **k: finished.append((a, k)), raising=False)
    monkeypatch.setattr(ing, "_fetch_all_pages", AsyncMock(return_value=[_acao(A, "ITUB3")]), raising=False)

    def broken(conn, rows, year, month, stats):
        raise ValueError("malformed")

    assert asyncio.run(ing._ingest_cda_block("cda_acoes", broken, 2026, 6)) == 0
    (args, kwargs), = finished
    assert "malformed" in args[2]
    assert kwargs["deleted"] is None


def test_the_slice_reports_what_the_replace_removed(monkeypatch):
    from src.pipeline.cvm_pipeline import CVMIngestor

    ing = CVMIngestor.__new__(CVMIngestor)
    ing._supabase = object()
    finished = []
    monkeypatch.setattr(ing, "_log_start", lambda *a: None, raising=False)
    monkeypatch.setattr(ing, "_log_finish", lambda *a, **k: finished.append((a, k)), raising=False)
    monkeypatch.setattr(ing, "_fetch_all_pages", AsyncMock(return_value=[{}, {}]), raising=False)

    def store(conn, rows, year, month, stats):
        stats["rows_deleted"] += 3
        return 2

    assert asyncio.run(ing._ingest_cda_block("cda_debentures", store, 2026, 6)) == 2
    (args, kwargs), = finished
    assert args[1] == 2 and kwargs == {"fetched": 2, "deleted": 3}


# ── the transaction shape ──────────────────────────────────────────────────

def test_a_fund_never_straddles_two_transactions(db, monkeypatch):
    """Batches are whole funds: a delete in one transaction must not hit rows another carries."""
    monkeypatch.setenv("CVM_UPSERT_CHUNK_SIZE", "1")
    rows = [_acao(A, "ITUB3"), _acao(A, "BBAS3"), _acao(A, "WEGE3"), _acao(B, "VALE3")]
    ingest_fi.ingest_fi_cda_acoes(db, rows, 2026, 6)
    txns = [s for s in db.log if s.startswith("UPSERT cvm_fi_cda_acoes")]
    assert txns == ["UPSERT cvm_fi_cda_acoes 3", "UPSERT cvm_fi_cda_acoes 1"]
    assert db.log.count("BEGIN") == db.log.count("COMMIT") == 2


def test_each_batch_runs_delete_then_upsert_in_one_transaction(db):
    ingest_fi.ingest_fi_cda_acoes(db, [_acao(A, "ITUB3")], 2026, 6)
    body = [s for s in db.log if not s.startswith("UPSERT cvm_fi_cda_fund_name")]
    assert body == ["BEGIN", "CREATE", "KEYS", "ANALYZE", "DELETE",
                    "UPSERT cvm_fi_cda_acoes 1", "COMMIT"]


def test_a_failed_batch_rolls_back_and_earlier_deletes_still_count(db, monkeypatch):
    ingest_fi.ingest_fi_cda_acoes(db, [_acao(A, "ITUB3"), _acao(B, "VALE3")], 2026, 6)
    monkeypatch.setenv("CVM_UPSERT_CHUNK_SIZE", "1")
    db.fail_on = ("cvm_fi_cda_acoes", 2)   # A's batch commits, B's raises
    stats = {}
    with pytest.raises(RuntimeError):
        ingest_fi.ingest_fi_cda_acoes(db, [_acao(A, "XPTO3"), _acao(B, "ABEV3")], 2026, 6, stats)
    assert "ROLLBACK" in db.log
    assert db.held("cvm_fi_cda_acoes", "cd_ativo") == [(B14, "VALE3"), (A14, "XPTO3")]
    assert stats == {"rows_deleted": 1}


def test_block1_null_key_row_is_replaced_not_duplicated(db):
    """uq_fi_cda is NULLS DISTINCT: a key with a NULL never conflicts, so without
    the replace such a row is re-inserted beside itself on every re-read."""
    db.tables["cvm_fi_cda"].append({
        "cnpj": A14, "period": date(2026, 6, 1), "tp_fundo": None,
        "tp_aplic": "Títulos Públicos", "tp_ativo": None, "cd_isin": None, "tp_negoc": None,
    })
    first, second = {}, {}
    ingest_fi.ingest_fi_cda(db, [_bond(A)], 2026, 6, first)
    ingest_fi.ingest_fi_cda(db, [_bond(A)], 2026, 6, second)
    assert db.held("cvm_fi_cda", "cd_isin") == [(A14, "BRSTNCLF1RU6")]
    assert (first, second) == ({"rows_deleted": 1}, {"rows_deleted": 0})


def test_a_yearly_archive_is_only_upserted(db):
    """HIST files are final and carry twelve months: no replace there."""
    rows = [dict(_acao(A, "ITUB3"), DT_COMPTC="2020-03-31")]
    ingest_fi.ingest_fi_cda_acoes(db, rows, 2020, None)
    assert "DELETE" not in db.log and "BEGIN" not in db.log


# ── the comparison must match each arbiter ─────────────────────────────────

def _arbiter_is_nulls_not_distinct(table: str) -> bool:
    schema = (ROOT / "src/store/schema.sql").read_text(encoding="utf-8")
    m = re.search(rf"CREATE UNIQUE INDEX IF NOT EXISTS uq_{table[4:]}\s+ON {table}\b(.*?);", schema, re.S)
    if m:
        return "NULLS NOT DISTINCT" in m.group(1)
    m = re.search(rf"CONSTRAINT uq_{table[4:]} UNIQUE(.*?)\)", schema, re.S)
    assert m, f"no arbiter for {table} in schema.sql"
    return "NULLS NOT DISTINCT" in m.group(0)


@pytest.mark.parametrize("fm", [_cda, _acoes, _cotas, _deb])
def test_nulls_distinct_matches_each_tables_arbiter(fm):
    """A stored row must survive exactly when the upsert will land on it."""
    assert fm.NULLS_DISTINCT is (not _arbiter_is_nulls_not_distinct(fm.TABLE)), fm.TABLE


@pytest.mark.parametrize("nulls_distinct, op", [(True, "k.tp_negoc = t.tp_negoc"),
                                                (False, "k.tp_negoc IS NOT DISTINCT FROM t.tp_negoc")])
def test_the_delete_uses_the_arbiters_comparison(db, nulls_distinct, op):
    sent = []
    db.execute = lambda cur, sql, params=None: sent.append(sql)
    pg_client.replace_scoped_rows(
        db, "cvm_fi_cda_acoes",
        [{"cnpj": A14, "period": date(2026, 6, 1), "tp_negoc": None, "cd_ativo": "X"}],
        "cnpj,period,cd_ativo,tp_negoc", nulls_distinct=nulls_distinct,
    )
    (delete,) = [s for s in sent if s.startswith("DELETE")]
    assert op in delete
    assert "k.cnpj = t.cnpj AND k.period = t.period" in delete


def test_scope_columns_must_be_part_of_the_key(db):
    with pytest.raises(ValueError):
        pg_client.replace_scoped_rows(
            db, "cvm_fi_cda_acoes", [{"cnpj": A14, "cd_ativo": "X"}],
            "cnpj,cd_ativo", nulls_distinct=False,
        )


# ── the audit column ───────────────────────────────────────────────────────

def test_rows_deleted_reaches_schema_and_migration_68():
    alter = "ALTER TABLE cvm_ingest_log ADD COLUMN IF NOT EXISTS rows_deleted INT;"
    assert alter in (ROOT / "src/store/schema.sql").read_text(encoding="utf-8")
    mig = (ROOT / "src/store/migrations/68_ingest_log_rows_deleted.sql").read_text(encoding="utf-8")
    assert alter in mig
    for line in mig.splitlines():
        if line.lstrip().startswith("--"):
            assert ";" not in line, "no semicolons in migration comments (psql-clean)"


def test_the_finish_update_writes_rows_deleted_only_when_given():
    from unittest.mock import MagicMock
    from src.pipeline.cvm_pipeline import CVMIngestor

    ing = CVMIngestor.__new__(CVMIngestor)
    cur = MagicMock()
    cur.__enter__ = lambda s: s
    cur.__exit__ = MagicMock(return_value=False)
    cur.rowcount = 1
    ing._supabase = MagicMock()
    ing._supabase.cursor.return_value = cur

    ing._log_finish("r1", 7)
    sql, params = cur.execute.call_args[0]
    assert "rows_deleted" not in sql and params[-1] == "r1"

    ing._log_finish("r2", 7, fetched=7, deleted=4)
    sql, params = cur.execute.call_args[0]
    assert "rows_deleted=%s WHERE run_id=%s" in sql
    assert params[-2:] == (4, "r2")
