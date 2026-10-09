"""Compare schema.sql alone with schema.sql followed by every migration.

The comparison is deliberately structural: column names and constraint names
are the contract called out by issue #685. Expected differences belong in the
checked-in allowlist, with a reason for each entry.
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import closing
from pathlib import Path

import psycopg2


ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "tests" / "fixtures" / "schema_migration_parity_allowlist.json"


def _columns(conn) -> set[tuple[str, str, str]]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT table_schema, table_name, column_name
                 FROM information_schema.columns
                WHERE table_schema = 'public'"""
        )
        return set(cur.fetchall())


def _constraints(conn) -> set[tuple[str, str, str]]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT n.nspname, c.relname, con.conname
                 FROM pg_constraint con
                 JOIN pg_class c ON c.oid = con.conrelid
                 JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'"""
        )
        return set(cur.fetchall())


def _actual_differences(schema_url: str, migrated_url: str) -> dict[str, set[tuple[str, ...]]]:
    with closing(psycopg2.connect(schema_url)) as schema_conn, closing(
        psycopg2.connect(migrated_url)
    ) as migrated_conn:
        schema_columns = _columns(schema_conn)
        migrated_columns = _columns(migrated_conn)
        schema_constraints = _constraints(schema_conn)
        migrated_constraints = _constraints(migrated_conn)
    return {
        "columns_only_in_schema": schema_columns - migrated_columns,
        "columns_only_after_migrations": migrated_columns - schema_columns,
        "constraints_only_in_schema": schema_constraints - migrated_constraints,
        "constraints_only_after_migrations": migrated_constraints - schema_constraints,
    }


def _load_allowlist() -> dict[str, list[dict[str, object]]]:
    data = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    expected_keys = {
        "columns_only_in_schema",
        "columns_only_after_migrations",
        "constraints_only_in_schema",
        "constraints_only_after_migrations",
    }
    if set(data) != expected_keys:
        raise ValueError(f"allowlist keys must be exactly {sorted(expected_keys)}")
    for category, entries in data.items():
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("reason"):
                raise ValueError(f"every {category} allowlist entry needs a reason")
    return data


def _allowed(entries: list[dict[str, object]]) -> set[tuple[str, ...]]:
    return {tuple(entry["object"]) for entry in entries}


def main() -> int:
    schema_url = os.environ.get("SCHEMA_ONLY_URL")
    migrated_url = os.environ.get("SCHEMA_MIGRATED_URL")
    if not schema_url or not migrated_url:
        print("SCHEMA_ONLY_URL and SCHEMA_MIGRATED_URL are required", file=sys.stderr)
        return 2

    allowlist = _load_allowlist()
    differences = _actual_differences(schema_url, migrated_url)
    failed = False
    for category, actual in differences.items():
        expected = _allowed(allowlist[category])
        unexpected = actual - expected
        stale = expected - actual
        if unexpected or stale:
            failed = True
            for item in sorted(unexpected):
                print(f"unexpected {category}: {item}")
            for item in sorted(stale):
                print(f"stale allowlist entry in {category}: {item}")
    if failed:
        print(f"Update {ALLOWLIST.relative_to(ROOT)} only after reviewing each difference.")
        return 1
    print("schema.sql and schema.sql + migrations match on public columns and constraint names")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
