"""schema.sql must apply to a database that already exists.

THE BUG THIS EXISTS FOR. Migration 33 added `tp_fundo` to cvm_fi_cda_acoes and
schema.sql was updated to create the widened unique index over it. Applied to a
FRESH database that works: CREATE TABLE really creates the table, column
included. Applied to production it failed with

    ERROR: column "tp_fundo" does not exist

because `CREATE TABLE IF NOT EXISTS` is a **no-op** on an existing table, and CI
runs schema.sql BEFORE the migrations — so the index referenced a column that
nothing had added yet. It took down the schema gate, which every ingest job
needs, so an entire backfill dispatch ran zero jobs.

The local verification that missed it applied schema.sql to an empty database.
That is not what production is. This module checks the shape that matters: a
column referenced by an index must be reachable from schema.sql ALONE on a table
that already exists — i.e. it must be added by a guarded ALTER, not only by the
CREATE TABLE.

This is a static check on purpose: it runs in the normal offline suite in
milliseconds, with no database, so it fires on every commit rather than only in
the job that has Postgres.
"""

import re
from pathlib import Path

import pytest

SCHEMA = Path(__file__).resolve().parents[1] / "src/store/schema.sql"


def _strip_sql_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return re.sub(r"--[^\n]*", "", sql)


@pytest.fixture(scope="module")
def sql() -> str:
    return _strip_sql_comments(SCHEMA.read_text())


def _columns_by_table(sql: str) -> dict[str, set[str]]:
    """Every column reachable from schema.sql, per table.

    A column counts if it is in the CREATE TABLE body or added later by an
    ALTER TABLE ... ADD COLUMN. Both are what an existing database will have
    after schema.sql runs against it.
    """
    cols: dict[str, set[str]] = {}

    for m in re.finditer(
        r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+(\w+)\s*\((.*?)\n\)\s*;", sql, re.S
    ):
        table, body = m.group(1), m.group(2)
        found = set()
        for line in body.split("\n"):
            line = line.strip().lstrip("(")
            cm = re.match(r"(\w+)\s+[A-Za-z]", line)
            if cm and cm.group(1).upper() not in {
                "CONSTRAINT", "PRIMARY", "UNIQUE", "FOREIGN", "CHECK", "LIKE",
            }:
                found.add(cm.group(1).lower())
        cols.setdefault(table.lower(), set()).update(found)

    for m in re.finditer(
        r"ALTER TABLE\s+(?:IF EXISTS\s+)?(\w+)\s+ADD COLUMN(?:\s+IF NOT EXISTS)?\s+(\w+)",
        sql, re.I,
    ):
        cols.setdefault(m.group(1).lower(), set()).add(m.group(2).lower())

    # Multi-column ALTER: "ADD COLUMN IF NOT EXISTS a TEXT,\n ADD COLUMN ... b"
    for m in re.finditer(r"ALTER TABLE\s+(?:IF EXISTS\s+)?(\w+)(.*?);", sql, re.S | re.I):
        for c in re.findall(r"ADD COLUMN(?:\s+IF NOT EXISTS)?\s+(\w+)", m.group(2), re.I):
            cols.setdefault(m.group(1).lower(), set()).add(c.lower())

    return cols


def _index_refs(sql: str):
    """(index_name, table, [columns]) for every CREATE INDEX in schema.sql."""
    out = []
    for m in re.finditer(
        r"CREATE\s+(?:UNIQUE\s+)?INDEX(?:\s+IF NOT EXISTS)?\s+(\w+)\s+ON\s+(\w+)\s*(?:USING\s+\w+\s*)?\(([^)]*)\)",
        sql, re.I,
    ):
        name, table, cols = m.group(1), m.group(2).lower(), m.group(3)
        # Column list entries may carry DESC/ASC/NULLS FIRST or be expressions.
        parsed = []
        for part in cols.split(","):
            part = part.strip()
            cm = re.match(r"^(\w+)\b", part)
            if cm and "(" not in part:
                parsed.append(cm.group(1).lower())
        out.append((name, table, parsed))
    return out


def test_every_indexed_column_is_reachable_from_schema_alone(sql: str):
    """The exact failure that broke the backfill gate.

    On an existing database CREATE TABLE IF NOT EXISTS does nothing, so a column
    that appears only inside the CREATE TABLE body is invisible to an index
    created later in the same file. It must also have a guarded ALTER.
    """
    cols = _columns_by_table(sql)
    problems = []
    for name, table, refs in _index_refs(sql):
        known = cols.get(table)
        if known is None:
            continue  # index over a table declared elsewhere (a partition child)
        for c in refs:
            if c not in known:
                problems.append(f"{name}: {table}.{c}")
    assert not problems, (
        "index columns not reachable from schema.sql on an EXISTING database "
        f"(add a guarded ALTER TABLE ... ADD COLUMN IF NOT EXISTS): {problems}"
    )


@pytest.mark.parametrize("table,column", [
    ("cvm_fi_cda_acoes", "tp_fundo"),
    ("cvm_fi_cda_cotas", "tp_fundo"),
    ("cvm_fi_cda_cotas", "tp_negoc"),
    ("cvm_fip_periodic", "period"),
    ("cvm_fip_periodic", "classe_cota"),
    ("cvm_fip_periodic", "row_hash"),
])
def test_the_columns_that_broke_production_are_guarded(sql: str, table, column):
    """Named explicitly so a future edit cannot quietly drop the guard.

    Each of these is a key column added by a migration after its table shipped.
    Without the ALTER in schema.sql, the schema gate dies and every ingest job
    that needs it is skipped.
    """
    pattern = (
        rf"ALTER TABLE\s+(?:IF EXISTS\s+)?{table}\s+ADD COLUMN\s+IF NOT EXISTS\s+{column}\b"
    )
    assert re.search(pattern, sql, re.I), (
        f"{table}.{column} is part of a unique index but has no guarded ALTER in "
        "schema.sql — this is the exact shape that failed in production"
    )


def test_a_replaced_unique_index_is_dropped_first(sql: str):
    """Widening a key must drop the old index, or CREATE ... IF NOT EXISTS wins.

    IF NOT EXISTS matches on NAME, not definition, so re-creating a widened
    index under its old name silently keeps the narrow one — and the narrow key
    is what was losing rows.
    """
    for name in ("uq_fi_cda_acoes", "uq_fi_cda_cotas", "uq_fip_periodic"):
        drop = sql.find(f"DROP INDEX IF EXISTS {name}")
        create = sql.find(f"INDEX IF NOT EXISTS {name}")
        assert drop != -1, f"{name} is re-created without a preceding DROP"
        assert drop < create, f"{name} is dropped after it is created"


def test_cotas_duplicates_are_cleared_before_the_unique_index(sql: str):
    """The schema gate went down on this (2026-08-31, run 33449184287).

    Migration 33's CREATE UNIQUE INDEX uq_fi_cda_cotas failed three times with
    a duplicate key whose tp_fundo and tp_negoc were both NULL. NULLS NOT
    DISTINCT makes every such row collide, and 33's repair-from-`raw` reports
    UPDATE 0 because upsert_rows strips a key out of `raw` once a typed column
    of the same name exists — so the fallback is gone for exactly the rows that
    need it.

    A failing migration blocks every later one, so the de-duplication has to
    happen in schema.sql, which runs FIRST. If it is ever moved into a
    migration numbered above 33, the gate breaks again and nothing later runs.
    """
    dedup = sql.find("PARTITION BY cnpj, period, tp_fundo, cnpj_cota, tp_aplic, tp_negoc")
    create = sql.find("INDEX IF NOT EXISTS uq_fi_cda_cotas")
    assert dedup != -1, (
        "schema.sql no longer de-duplicates cvm_fi_cda_cotas before building "
        "uq_fi_cda_cotas — migration 33 will fail on legacy NULL-key rows and "
        "take the whole schema gate down with it"
    )
    assert dedup < create, "the de-duplication must run BEFORE the index is created"


def test_the_cotas_dedup_keeps_the_newest_row():
    """Last write wins — the row ON CONFLICT DO UPDATE would itself have kept.

    Ordering by fetched_at DESC is the whole justification for deleting
    anything here: it reproduces the upsert's own semantics rather than making
    an arbitrary choice about which real position to discard.
    """
    text = SCHEMA.read_text()
    assert "ORDER BY fetched_at DESC, id DESC" in text, (
        "the dedup must keep the newest row per key; any other ordering "
        "discards data arbitrarily instead of restoring the upsert's outcome"
    )
    assert "RAISE NOTICE" in text, "the removed count must be visible in the apply log"
