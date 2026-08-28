"""No-op ADD COLUMN IF NOT EXISTS must not take AccessExclusiveLock.

Daily ingest re-applies schema.sql + every migration. PostgreSQL acquires
AccessExclusiveLock for ADD COLUMN IF NOT EXISTS *before* noticing the column
already exists, so a concurrent SELECT (Vercel Evidence build) fails the
apply. See scripts/guard_noop_ddl.py and Actions run 33034222521.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from guard_noop_ddl import (  # noqa: E402
    GUARD_TAG,
    guard_add_column_sql,
    guard_matview_sql,
    guard_noop_ddl,
    iter_wrappable,
    iter_wrappable_matview,
    split_sql_statements,
    wrap_add_column_statement,
    wrap_matview_statement,
)

SCHEMA = REPO / "src" / "store" / "schema.sql"
MIGRATIONS = REPO / "src" / "store" / "migrations"


def test_wraps_top_level_add_column():
    sql = (
        "CREATE TABLE t (id int);\n"
        "ALTER TABLE t ADD COLUMN IF NOT EXISTS foo TEXT;\n"
        "CREATE INDEX IF NOT EXISTS idx_t_foo ON t (foo);\n"
    )
    out = guard_add_column_sql(sql)
    assert f"DO ${GUARD_TAG}$" in out
    assert "to_regclass('t')" in out
    assert "('foo')" in out
    assert "ADD COLUMN IF NOT EXISTS foo TEXT" in out
    assert "CREATE TABLE t (id int);" in out
    assert "CREATE INDEX IF NOT EXISTS idx_t_foo ON t (foo);" in out
    # original top-level ALTER is gone; only the copy inside the DO remains
    top_level = [
        s for s in split_sql_statements(out) if wrap_add_column_statement(s)
    ]
    assert top_level == []


def test_wraps_multi_column_alter():
    sql = """
ALTER TABLE cvm_fii_mensal
    ADD COLUMN IF NOT EXISTS nr_cotst               INT,
    ADD COLUMN IF NOT EXISTS vl_ativo               NUMERIC(20,6);
"""
    out = guard_add_column_sql(sql)
    assert "('nr_cotst')" in out
    assert "('vl_ativo')" in out
    assert "to_regclass('cvm_fii_mensal')" in out
    assert "ADD COLUMN IF NOT EXISTS nr_cotst" in out


def test_does_not_wrap_add_column_inside_do_block():
    sql = """
DO $$
BEGIN
  ALTER TABLE t ADD COLUMN IF NOT EXISTS foo TEXT;
END
$$;
"""
    out = guard_add_column_sql(sql)
    assert GUARD_TAG not in out
    assert sql.strip() in out.strip()


def test_does_not_wrap_named_dollar_do_block():
    sql = """
DO $anbima_compat_view$
BEGIN
  ALTER TABLE t ADD COLUMN IF NOT EXISTS foo TEXT;
END
$anbima_compat_view$;
"""
    out = guard_add_column_sql(sql)
    assert GUARD_TAG not in out


def test_does_not_wrap_alter_column_type():
    sql = "ALTER TABLE t ALTER COLUMN foo TYPE NUMERIC(28,2);"
    assert guard_add_column_sql(sql) == sql


def test_does_not_wrap_add_column_without_if_not_exists():
    sql = "ALTER TABLE t ADD COLUMN foo TEXT;"
    assert guard_add_column_sql(sql) == sql


def test_does_not_wrap_mixed_alter():
    sql = (
        "ALTER TABLE t ADD COLUMN IF NOT EXISTS foo TEXT, "
        "ALTER COLUMN bar TYPE TEXT;"
    )
    assert guard_add_column_sql(sql) == sql


def test_inner_semicolon_in_comment_does_not_split():
    sql = (
        "-- note: don't split on ;\n"
        "ALTER TABLE t ADD COLUMN IF NOT EXISTS foo TEXT;\n"
    )
    out = guard_add_column_sql(sql)
    assert f"DO ${GUARD_TAG}$" in out
    assert "-- note: don't split on ;" in out


def test_wrap_is_idempotent():
    sql = "ALTER TABLE t ADD COLUMN IF NOT EXISTS foo TEXT;\n"
    once = guard_add_column_sql(sql)
    twice = guard_add_column_sql(once)
    assert once == twice


def test_schema_sql_failing_statement_is_wrapped():
    """The exact statement that killed Daily CVM Ingest #167 (schema.sql:268)."""
    sql = SCHEMA.read_text(encoding="utf-8")
    wrappable = list(iter_wrappable(sql))
    assert wrappable, "schema.sql must still have top-level ADD COLUMN IF NOT EXISTS"
    assert any(
        "cvm_fii_mensal" in w and "nr_cotst" in w for w in wrappable
    ), wrappable[:3]
    out = guard_add_column_sql(sql)
    assert list(iter_wrappable(out)) == []
    assert "to_regclass('cvm_fii_mensal')" in out
    assert "('nr_cotst')" in out
    # CREATE TABLE / indexes stay as-is so a fresh DB still bootstraps
    assert "CREATE TABLE IF NOT EXISTS cvm_ingest_log" in out
    assert "CREATE TABLE IF NOT EXISTS cvm_fii_mensal" in out


def test_migration_14_perfil_add_column_is_wrapped():
    """The statement that hung 4m20s on 2026-08-26 22:41 UTC."""
    sql = (MIGRATIONS / "14_fi_perfil_columns.sql").read_text(encoding="utf-8")
    wrappable = list(iter_wrappable(sql))
    assert any("cvm_fi_perfil" in w and "nr_cotst_pf_varejo" in w for w in wrappable)
    out = guard_add_column_sql(sql)
    assert list(iter_wrappable(out)) == []
    assert "to_regclass('cvm_fi_perfil')" in out
    # CREATE INDEX stays top-level (ShareLock, not blocked by SELECT)
    assert "CREATE INDEX IF NOT EXISTS idx_fi_perfil_pf_varejo" in out


@pytest.mark.parametrize("path", [SCHEMA, *sorted(MIGRATIONS.glob("*.sql"))])
def test_every_sql_file_wraps_cleanly(path: Path):
    src = path.read_text(encoding="utf-8")
    out = guard_noop_ddl(src)
    assert list(iter_wrappable(out)) == []
    assert list(iter_wrappable_matview(out)) == []
    # Named dollar-quote DO blocks in the source must survive untouched
    if "$anbima_compat_view$" in src:
        assert "$anbima_compat_view$" in out
    # Guarded retypes (migration 03 / 01) stay as their original DO blocks
    if "03_precision" in path.name:
        assert "ALTER COLUMN qt_titulos TYPE" in out
        assert out.count(f"DO ${GUARD_TAG}$") == 0
    # Idempotent
    assert guard_noop_ddl(out) == out


def test_appends_with_no_data_to_create_matview():
    sql = (
        "CREATE TABLE t (id int);\n"
        "CREATE MATERIALIZED VIEW IF NOT EXISTS mv AS SELECT 1 AS x;\n"
        "CREATE INDEX IF NOT EXISTS idx_mv ON mv (x);\n"
    )
    out = guard_matview_sql(sql)
    assert "CREATE TABLE t (id int);" in out
    assert "WITH NO DATA" in out
    assert "CREATE INDEX IF NOT EXISTS idx_mv ON mv (x);" in out
    assert list(iter_wrappable_matview(out)) == []


def test_does_not_double_with_no_data():
    sql = "CREATE MATERIALIZED VIEW IF NOT EXISTS mv AS SELECT 1 AS x WITH NO DATA;\n"
    assert guard_matview_sql(sql) == sql
    assert wrap_matview_statement(sql) is None


def test_rewrites_explicit_with_data_to_with_no_data():
    sql = "CREATE MATERIALIZED VIEW IF NOT EXISTS mv AS SELECT 1 AS x WITH DATA;\n"
    out = guard_matview_sql(sql)
    assert "WITH NO DATA" in out
    assert re.search(r"(?<!NO )WITH DATA", out, re.I) is None


def test_does_not_wrap_matview_inside_do_block():
    sql = """
DO $$
BEGIN
  CREATE MATERIALIZED VIEW IF NOT EXISTS mv AS SELECT 1 AS x;
END
$$;
"""
    out = guard_matview_sql(sql)
    assert "WITH NO DATA" not in out
    assert wrap_matview_statement(sql) is None


def test_schema_sql_matview_create_is_with_no_data():
    """Daily CVM Ingest #184 (run 33180429771) died on this CREATE WITH DATA."""
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS mv_b3_isin_subtype" in sql
    assert "WITH NO DATA" in sql
    # CREATE must not populate: that holds pg_type for the b3_cotahist scan.
    create = sql.split("CREATE MATERIALIZED VIEW IF NOT EXISTS mv_b3_isin_subtype", 1)[1]
    create = create.split(";", 1)[0]
    assert "WITH NO DATA" in create
    assert "REFRESH MATERIALIZED VIEW" not in create
    # Population is a later statement, so the type commit is visible to a
    # concurrent apply's IF NOT EXISTS check.
    rest = sql.split("CREATE MATERIALIZED VIEW IF NOT EXISTS mv_b3_isin_subtype", 1)[1]
    rest = rest.split(";", 1)[1]
    assert "REFRESH MATERIALIZED VIEW public.mv_b3_isin_subtype" in rest
    assert "$silo_refresh_mv_b3_isin_subtype$" in rest
    # Rewriter is a no-op on the already-safe CREATE.
    assert list(iter_wrappable_matview(sql)) == []


def test_migration_27_rewritten_to_with_no_data():
    """Historical migrations are not edited; apply-time rewrite must catch #184."""
    sql = (MIGRATIONS / "27_b3_instrument_typed_v3.sql").read_text(encoding="utf-8")
    wrappable = list(iter_wrappable_matview(sql))
    assert any("mv_b3_isin_subtype" in w for w in wrappable), wrappable
    # Source keeps the original WITH DATA (implicit) text.
    src_create = sql.split("CREATE MATERIALIZED VIEW IF NOT EXISTS mv_b3_isin_subtype", 1)[1]
    src_create = src_create.split(";", 1)[0]
    assert "WITH NO DATA" not in src_create
    out = guard_noop_ddl(sql)
    assert list(iter_wrappable_matview(out)) == []
    out_create = out.split("CREATE MATERIALIZED VIEW IF NOT EXISTS mv_b3_isin_subtype", 1)[1]
    out_create = out_create.split(";", 1)[0]
    assert "WITH NO DATA" in out_create
    # BEGIN/COMMIT and the view replace survive.
    assert "BEGIN;" in out
    assert "CREATE OR REPLACE VIEW vw_b3_instrument_typed" in out


def test_guard_noop_ddl_is_idempotent_on_schema():
    src = SCHEMA.read_text(encoding="utf-8")
    once = guard_noop_ddl(src)
    assert guard_noop_ddl(once) == once
