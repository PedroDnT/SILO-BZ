"""FII filings keep every CVM version (migration 43, plan item 2d).

cvm_fii_mensal and cvm_fii_periodic used to key without CVM's ``Versao``, so a
restatement overwrote the original. These tests pin the four places that must
move together:

  1. the field maps map ``Versao`` and carry ``versao`` in CONFLICT,
  2. ingest validates it (int >= 1, else drop + count) and lets two versions of
     one filing through as two rows,
  3. migration 43 / schema.sql put versao in both unique keys, idempotently,
  4. every reader reads ONE row per former key — the latest version — through
     vw_fii_mensal_latest / vw_fii_periodic_latest, never the table (lockstep).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from src.parsers.field_maps import (
    fii_ativo_passivo,
    fii_complemento,
    fii_geral,
    fii_periodic,
    fii_trimestral_complemento,
    fii_trimestral_geral,
)
from src.parsers.mapping import apply_map
from src.parsers.validation import parse_versao
from src.pipeline.ingest_fii import ingest_fii_mensal, ingest_fii_periodic

ROOT = Path(__file__).resolve().parent.parent
MIGRATION = ROOT / "src/store/migrations/43_fii_versions.sql"
SCHEMA = ROOT / "src/store/schema.sql"
MIGRATION_15 = ROOT / "src/store/migrations/15_fii_trimestral_members.sql"

MENSAL_MAPS = (fii_geral, fii_ativo_passivo, fii_complemento)
PERIODIC_MAPS = (fii_periodic, fii_trimestral_geral, fii_trimestral_complemento)

MENSAL_OLD_KEY = ("cnpj", "period", "doc_subtype")
PERIODIC_OLD_KEY = ("cnpj", "doc_type", "period_year", "data_referencia")


def _sql_code(text: str) -> str:
    """SQL with -- comments and '...' literals removed (reader scans)."""
    text = re.sub(r"--[^\n]*", "", text)
    return re.sub(r"'(?:[^']|'')*'", "''", text)


# ---------------------------------------------------------------------------
# 1. Field maps
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("mod", MENSAL_MAPS + PERIODIC_MAPS, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_every_fii_map_maps_versao(mod):
    candidates, type_ = mod.FIELD_MAP["versao"]
    assert "Versao" in candidates
    # text, not int: ingest validates strictly (the int coercion reads "1.5" as 15)
    assert type_ == "text"
    typed, residual = apply_map({"CNPJ_Fundo_Classe": "1", "Versao": "3"}, mod.FIELD_MAP)
    assert typed["versao"] == "3"
    assert "Versao" not in residual  # consumed, so it no longer sits in raw


@pytest.mark.parametrize("mod", MENSAL_MAPS, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_mensal_conflict_is_old_key_plus_versao(mod):
    assert mod.TABLE == "cvm_fii_mensal"
    assert mod.CONFLICT == MENSAL_OLD_KEY + ("versao",)


@pytest.mark.parametrize("mod", PERIODIC_MAPS, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_periodic_conflict_is_old_key_plus_versao(mod):
    assert mod.TABLE == "cvm_fii_periodic"
    assert mod.CONFLICT == PERIODIC_OLD_KEY + ("versao",)


# ---------------------------------------------------------------------------
# 2. Validation + ingest
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("value, expected", [
    ("1", (True, 1)), (" 2 ", (True, 2)), (7, (True, 7)),
    (None, (True, None)), ("", (True, None)), ("  ", (True, None)),
    ("0", (False, None)), ("-1", (False, None)), ("1.5", (False, None)),
    ("2a", (False, None)), ("1,0", (False, None)),
])
def test_parse_versao(value, expected):
    assert parse_versao(value) == expected


def _complemento_row(versao, pl):
    return {
        "CNPJ_Fundo_Classe": "12.345.678/0001-90",
        "Data_Referencia": "2024-01-01",
        "Versao": versao,
        "Patrimonio_Liquido": pl,
        "Total_Numero_Cotistas": "150",
    }


def _capture():
    captured: list = []

    def fake_upsert(conn, table, rows, conflict_columns=None):
        captured.append({"table": table, "conflict": conflict_columns, "rows": rows})
        return len(rows)

    return captured, fake_upsert


def test_mensal_two_versions_are_two_rows():
    captured, fake = _capture()
    rows = [_complemento_row("1", "1000.00"), _complemento_row("2", "1100.00")]
    with patch("src.pipeline.ingest_fii.upsert_rows", fake):
        n = ingest_fii_mensal(None, rows, "mensal_complemento")
    assert n == 2
    call = captured[0]
    assert call["table"] == "cvm_fii_mensal"
    assert call["conflict"] == "cnpj,period,doc_subtype,versao"
    assert [(r["versao"], r["vl_patrim_liq"]) for r in call["rows"]] == [(1, 1000.0), (2, 1100.0)]
    assert all("Versao" not in r["raw"] for r in call["rows"])


def test_mensal_malformed_versao_is_dropped_and_counted(caplog):
    captured, fake = _capture()
    rows = [
        _complemento_row("1", "1"),
        _complemento_row("0", "2"),
        _complemento_row("1.5", "3"),
        _complemento_row("x", "4"),
        _complemento_row("", "5"),  # no version published: kept, NULL
    ]
    with caplog.at_level(logging.WARNING, logger="src.pipeline.ingest_fii"):
        with patch("src.pipeline.ingest_fii.upsert_rows", fake):
            n = ingest_fii_mensal(None, rows, "mensal_complemento")
    assert n == 2
    assert [r["versao"] for r in captured[0]["rows"]] == [1, None]
    assert any("dropped 3 row(s) with a malformed Versao" in m for m in caplog.messages)


def test_periodic_without_versao_column_keeps_null():
    """dfin/anual files that carry no Versao still land, keyed as before."""
    captured, fake = _capture()
    rows = [{"CNPJ_Fundo_Classe": "00.332.266/0001-31", "Data_Referencia": "2025-12-31"}]
    with patch("src.pipeline.ingest_fii.upsert_rows", fake):
        n = ingest_fii_periodic(None, rows, "dfin", 2025)
    assert n == 1
    assert captured[0]["rows"][0]["versao"] is None
    assert captured[0]["conflict"] == "cnpj,doc_type,period_year,data_referencia,versao"


def test_periodic_malformed_versao_is_dropped(caplog):
    captured, fake = _capture()
    rows = [
        {"CNPJ_Fundo_Classe": "00.332.266/0001-31", "Data_Referencia": "2025-12-31", "Versao": "2"},
        {"CNPJ_Fundo_Classe": "00.332.266/0001-31", "Data_Referencia": "2025-12-31", "Versao": "-3"},
    ]
    with caplog.at_level(logging.WARNING, logger="src.pipeline.ingest_fii"):
        with patch("src.pipeline.ingest_fii.upsert_rows", fake):
            n = ingest_fii_periodic(None, rows, "anual", 2025)
    assert n == 1
    assert captured[0]["rows"][0]["versao"] == 2
    assert any("dropped 1 row(s) with a malformed Versao" in m for m in caplog.messages)


# ---------------------------------------------------------------------------
# 3. Migration 43 + schema.sql
# ---------------------------------------------------------------------------
MIG = MIGRATION.read_text(encoding="utf-8")
MIG_CODE = _sql_code(MIG)
SCHEMA_CODE = _sql_code(SCHEMA.read_text(encoding="utf-8"))

MENSAL_KEY_RE = re.compile(
    r"ADD\s+CONSTRAINT\s+uq_fii_mensal\s+UNIQUE\s+NULLS\s+NOT\s+DISTINCT\s*"
    r"\(\s*cnpj\s*,\s*period\s*,\s*doc_subtype\s*,\s*versao\s*\)", re.I)
PERIODIC_KEY_RE = re.compile(
    r"ADD\s+CONSTRAINT\s+uq_fii_periodic\s+UNIQUE\s+NULLS\s+NOT\s+DISTINCT\s*"
    r"\(\s*cnpj\s*,\s*doc_type\s*,\s*period_year\s*,\s*data_referencia\s*,\s*versao\s*\)", re.I)


def _top_level(code: str) -> str:
    """Code outside DO $$ ... $$ blocks."""
    return re.sub(r"DO\s+\$\$.*?\$\$\s*;", "", code, flags=re.S)


def test_migration_number_is_43_not_44():
    assert MIGRATION.exists()
    assert not list((ROOT / "src/store/migrations").glob("44_fii*"))


@pytest.mark.parametrize("code", [MIG_CODE, SCHEMA_CODE], ids=["migration_43", "schema.sql"])
def test_keys_include_versao_nulls_not_distinct(code):
    assert MENSAL_KEY_RE.search(code)
    assert PERIODIC_KEY_RE.search(code)
    assert re.search(r"ALTER\s+TABLE\s+cvm_fii_mensal\s+ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+versao\s+INT", code, re.I)


@pytest.mark.parametrize("code", [MIG_CODE, SCHEMA_CODE], ids=["migration_43", "schema.sql"])
def test_key_swaps_are_catalog_guarded(code):
    """Idempotent: each swap sits in a DO block that skips once the key names versao."""
    for table, con in (("cvm_fii_mensal", "uq_fii_mensal"), ("cvm_fii_periodic", "uq_fii_periodic")):
        guard = re.search(
            rf"DO\s+\$\$.*?conrelid\s*=\s*''::regclass.*?conname\s*=\s*''.*?"
            rf"pg_get_constraintdef\(oid\)\s+ILIKE\s+''.*?ALTER\s+TABLE\s+{table}\s+DROP\s+CONSTRAINT\s+IF\s+EXISTS\s+{con}"
            rf".*?\$\$\s*;",
            code, re.S | re.I,
        )
        assert guard, f"{table}: key swap is not inside a catalog-guarded DO block"
    # and the guard literal really is versao (literals are blanked in *_CODE)
    raw = MIG if code is MIG_CODE else SCHEMA.read_text(encoding="utf-8")
    assert raw.count("pg_get_constraintdef(oid) ILIKE '%versao%'") >= 2
    # no unconditional DROP/ADD of the FII keys outside a DO block
    top = _top_level(code)
    assert not re.search(r"DROP\s+CONSTRAINT\s+IF\s+EXISTS\s+uq_fii_(mensal|periodic)", top, re.I)
    assert not re.search(r"ADD\s+CONSTRAINT\s+uq_fii_(mensal|periodic)", top, re.I)


def test_migration_15_no_longer_re_adds_the_narrow_key_unconditionally():
    """Once two versions are stored, an unconditional re-ADD of the pre-43 key
    would fail with a duplicate and stop every schema apply."""
    code = _sql_code(MIGRATION_15.read_text(encoding="utf-8"))
    top = _top_level(code)
    assert not re.search(r"ADD\s+CONSTRAINT\s+uq_fii_periodic", top, re.I)
    assert not re.search(r"DROP\s+CONSTRAINT\s+IF\s+EXISTS\s+uq_fii_periodic", top, re.I)
    assert "pg_get_constraintdef(oid) ILIKE '%data_referencia%'" in MIGRATION_15.read_text(encoding="utf-8")


def test_backfill_reads_raw_versao_once():
    for table in ("cvm_fii_mensal", "cvm_fii_periodic"):
        block = re.search(
            rf"DO\s+\$\$.*?col_description\('{table}'::regclass.*?NOT LIKE '%migration 43%'"
            rf".*?UPDATE\s+{table}\s+SET\s+versao\s*=\s*btrim\(raw ->> 'Versao'\)::int.*?"
            rf"raw\s*=\s*raw - 'Versao'.*?WHERE\s+versao\s+IS\s+NULL.*?\$\$;",
            MIG, re.S,
        )
        assert block, f"{table}: backfill is missing or not marker-guarded"
        # the marker the guard looks for is set by the COMMENT that follows
        assert re.search(rf"COMMENT ON COLUMN {table}\.versao IS\s*'[^']*migration 43", MIG)
    # the marker comment must NOT be mirrored in schema.sql: schema.sql runs
    # first, and would mark the live table as backfilled before 43 ran.
    assert "COMMENT ON COLUMN cvm_fii_mensal.versao" not in SCHEMA.read_text(encoding="utf-8")
    assert "COMMENT ON COLUMN cvm_fii_periodic.versao" not in SCHEMA.read_text(encoding="utf-8")


def test_latest_views_distinct_on_the_former_key():
    mensal = re.search(
        r"CREATE OR REPLACE VIEW vw_fii_mensal_latest\s+WITH \(security_invoker = true\) AS\s+"
        r"SELECT DISTINCT ON \(m\.cnpj, m\.period, m\.doc_subtype\) m\.\*\s+FROM cvm_fii_mensal m\s+"
        r"ORDER BY m\.cnpj, m\.period, m\.doc_subtype,\s+m\.versao DESC NULLS LAST, m\.fetched_at DESC, m\.id DESC;",
        MIG,
    )
    assert mensal
    periodic = re.search(
        r"CREATE OR REPLACE VIEW vw_fii_periodic_latest\s+WITH \(security_invoker = true\) AS\s+"
        r"SELECT DISTINCT ON \(p\.cnpj, p\.doc_type, p\.period_year, p\.data_referencia\) p\.\*\s+"
        r"FROM cvm_fii_periodic p\s+ORDER BY p\.cnpj, p\.doc_type, p\.period_year, p\.data_referencia,\s+"
        r"p\.versao DESC NULLS LAST, p\.fetched_at DESC, p\.id DESC;",
        MIG,
    )
    assert periodic
    # not in schema.sql: migration 01 retypes cvm_fii_mensal after schema.sql
    # on a fresh database, and a view over m.* would block the ALTER.
    assert "vw_fii_mensal_latest" not in SCHEMA_CODE


def test_latest_views_are_client_invisible():
    grants = (ROOT / "src/store/analytical/12_grants_and_rls.sql").read_text(encoding="utf-8")
    for v in ("vw_fii_mensal_latest", "vw_fii_periodic_latest"):
        assert re.search(rf"REVOKE ALL ON TABLE {v}\s+FROM anon, authenticated;", grants)
    assert "REVOKE ALL ON vw_fii_mensal_latest, vw_fii_periodic_latest FROM anon, authenticated" in MIG
    assert not re.search(r"GRANT\s+SELECT\s+ON\s+vw_fii_(mensal|periodic)_latest", grants, re.I)


# ---------------------------------------------------------------------------
# 4. Readers lockstep — nobody reads the multi-version tables directly
# ---------------------------------------------------------------------------
_READ_RE = re.compile(r"\b(?:from|join)\s+(?:public\.)?(cvm_fii_mensal|cvm_fii_periodic)\b", re.I)

# Files allowed to name the tables in FROM/JOIN, and why.
_ALLOWED = {
    # Landing-table freshness for /ops: max(period) over the table is the same
    # over every version, and the row estimate is pg_class's, by design.
    "dashboard/sources/supabase/ops_table_freshness.sql",
    # Historical migration: instrument_activity is re-created by migration 43
    # (applied after 07 on every run) reading vw_fii_mensal_latest.
    "src/store/migrations/07_lifecycle.sql",
    # Defines the latest views themselves.
    "src/store/migrations/43_fii_versions.sql",
}


def _reader_files():
    globs = (
        "src/store/analytical/*.sql",
        "src/store/migrations/*.sql",
        "dashboard/sources/**/*.sql",
        "webapp/sources/**/*.sql",
    )
    for g in globs:
        for p in sorted(ROOT.glob(g)):
            if "node_modules" in p.parts:
                continue
            yield p


def test_no_reader_reads_the_versioned_tables_directly():
    offenders = []
    for p in _reader_files():
        rel = p.relative_to(ROOT).as_posix()
        if rel in _ALLOWED:
            continue
        for m in _READ_RE.finditer(_sql_code(p.read_text(encoding="utf-8"))):
            offenders.append(f"{rel}: {m.group(0)}")
    assert not offenders, (
        "read FII filings through vw_fii_mensal_latest / vw_fii_periodic_latest "
        "(one row per former key, latest CVM version):\n  " + "\n  ".join(offenders)
    )


# Every reader repointed by migration 43's change. If one of these stops reading
# the view (rewritten, renamed), this fails and the list gets reviewed.
_REPOINTED = (
    "src/store/analytical/01_dim_fund.sql",
    "src/store/analytical/04_fact_fund_monthly.sql",
    "src/store/analytical/15_fraud_screens.sql",
    "dashboard/sources/supabase/fii_mensal_coverage.sql",
    "dashboard/sources/supabase/fii_payout_coverage.sql",
    "dashboard/sources/supabase/fii_payout_trend.sql",
    "dashboard/sources/supabase/top_fii_yield.sql",
    "dashboard/sources/supabase/yield_distribution.sql",
)


@pytest.mark.parametrize("rel", _REPOINTED)
def test_repointed_reader_uses_latest_view(rel):
    code = _sql_code((ROOT / rel).read_text(encoding="utf-8"))
    assert re.search(r"\b(?:from|join)\s+vw_fii_mensal_latest\b", code, re.I), rel


def test_instrument_activity_recreated_over_latest_view():
    ia = re.search(r"CREATE OR REPLACE VIEW instrument_activity AS(.*?)FROM activity;", MIG, re.S)
    assert ia, "migration 43 must re-create instrument_activity"
    assert re.search(r"SELECT 'fii'.*?FROM vw_fii_mensal_latest", ia.group(1), re.S)
    assert "cvm_fii_mensal" not in ia.group(1)
    # 43 sorts after 07, so its definition is the one that survives every apply
    assert sorted(["07_lifecycle.sql", "43_fii_versions.sql"])[-1] == "43_fii_versions.sql"
