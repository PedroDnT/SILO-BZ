"""
Apply schema.sql then run each migration file in src/store/migrations/ in
lexicographic order.  All DDL is idempotent (IF NOT EXISTS / IF EXISTS guards).

Usage:
    python scripts/apply_schema.py

Requires: POSTGRES_URL in .env (postgresql://... format)
Falls back to manual instructions if connection fails.

Migration order:
  1. schema.sql          — CREATE TABLE IF NOT EXISTS statements (base schema)
  2. migrations/01_*.sql — Funds domain column additions + precision widening
  3. migrations/02_*.sql — BACEN tables (placeholder)
  4. migrations/NN_*.sql — Future workstream migrations (add here, never edit old)
"""

import os
import sys
import glob

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCHEMA_SQL = os.path.join(_REPO_ROOT, "src", "store", "schema.sql")
_MIGRATIONS_DIR = os.path.join(_REPO_ROOT, "src", "store", "migrations")


def _load_migration_files():
    """Return list of (label, sql) tuples in lexicographic order."""
    pattern = os.path.join(_MIGRATIONS_DIR, "*.sql")
    files = sorted(glob.glob(pattern))
    result = []
    for path in files:
        label = os.path.basename(path)
        with open(path, "r", encoding="utf-8") as f:
            result.append((label, f.read()))
    return result


def _load_schema_sql():
    with open(_SCHEMA_SQL, "r", encoding="utf-8") as f:
        return f.read()


def _build_migration_list():
    """Build the ordered list of (label, sql) to apply."""
    migrations = []

    # Step 1: base schema
    migrations.append(("schema.sql (base tables)", _load_schema_sql()))

    # Step 2+: per-file migrations in order
    migrations.extend(_load_migration_files())

    return migrations


# ---------------------------------------------------------------------------
# Legacy inline MIGRATIONS kept for backward compatibility
# (these are now superseded by src/store/migrations/ files)
# ---------------------------------------------------------------------------

# Kept to avoid breaking any direct MIGRATIONS imports from old scripts
MIGRATIONS = []


def apply_via_psycopg2(db_url: str, migrations):
    import psycopg2  # type: ignore
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()
    ok = err = 0
    for name, sql in migrations:
        # Split on semicolons to handle multi-statement files robustly.
        # Each non-empty statement is executed separately.
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        for stmt in statements:
            try:
                cur.execute(stmt)
            except Exception as e:
                # Report but continue — many ALTERs are no-ops on fresh DBs
                print(f"  ! {name}: {e!s:.120}")
                err += 1
                break
        else:
            print(f"  ok {name}")
            ok += 1
    cur.close()
    conn.close()
    return ok, err


def apply_via_asyncpg(db_url: str, migrations):
    import asyncio
    import asyncpg  # type: ignore

    async def _run():
        conn = await asyncpg.connect(db_url)
        ok = err = 0
        for name, sql in migrations:
            try:
                await conn.execute(sql.strip())
                print(f"  ok {name}")
                ok += 1
            except Exception as e:
                print(f"  ! {name}: {e!s:.120}")
                err += 1
        await conn.close()
        return ok, err

    return asyncio.run(_run())


def print_manual_instructions(migrations):
    print("\n  ── MANUAL FALLBACK ──────────────────────────────────────────────")
    print("  Paste the following SQL blocks into your DB SQL editor:")
    print()
    for name, sql in migrations:
        print(f"  -- {name}")
        print(sql.strip())
        print()


def main():
    print("=" * 68)
    print("  CVM SCHEMA MIGRATION")
    print("=" * 68)

    db_url = os.environ.get("POSTGRES_URL")
    if not db_url:
        print("  POSTGRES_URL not set.")
        migrations = _build_migration_list()
        print_manual_instructions(migrations)
        return

    migrations = _build_migration_list()
    print(f"  DB URL: {db_url[:40]}...")
    print(f"  Applying {len(migrations)} migration steps...\n")

    for driver, fn in [
        ("psycopg2", lambda url: apply_via_psycopg2(url, migrations)),
        ("asyncpg",  lambda url: apply_via_asyncpg(url, migrations)),
    ]:
        try:
            __import__(driver.replace("psycopg2", "psycopg2"))
            ok, err = fn(db_url)
            print(f"\n  Done: {ok} OK, {err} errors  (driver: {driver})")
            return
        except ImportError:
            continue
        except Exception as e:
            print(f"  Connection failed ({driver}): {e}")
            break

    print("\n  No PostgreSQL driver available. Falling back to manual instructions.")
    print_manual_instructions(migrations)


if __name__ == "__main__":
    main()
