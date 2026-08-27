"""No-op ADD COLUMN IF NOT EXISTS must not take AccessExclusiveLock.

Daily ingest re-applies schema.sql + every migration. PostgreSQL acquires
AccessExclusiveLock for ADD COLUMN IF NOT EXISTS *before* noticing the column
already exists, so a concurrent SELECT (Vercel Evidence build) fails the
apply. See scripts/guard_noop_ddl.py and Actions run 33034222521.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from guard_noop_ddl import (  # noqa: E402
    GUARD_TAG,
    guard_add_column_sql,
    iter_wrappable,
    split_sql_statements,
    wrap_add_column_statement,
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
    out = guard_add_column_sql(src)
    assert list(iter_wrappable(out)) == []
    # Named dollar-quote DO blocks in the source must survive untouched
    if "$anbima_compat_view$" in src:
        assert "$anbima_compat_view$" in out
    # Guarded retypes (migration 03 / 01) stay as their original DO blocks
    if "03_precision" in path.name:
        assert "ALTER COLUMN qt_titulos TYPE" in out
        assert out.count(f"DO ${GUARD_TAG}$") == 0
    # Idempotent
    assert guard_add_column_sql(out) == out
