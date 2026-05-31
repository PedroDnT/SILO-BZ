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
import shutil
import subprocess

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


def _build_migration_list():
    """Build the ordered list of (label, path) to apply: base schema first,
    then every migration file in lexicographic order."""
    items = [("schema.sql (base tables)", _SCHEMA_SQL)]
    for path in sorted(glob.glob(os.path.join(_MIGRATIONS_DIR, "*.sql"))):
        items.append((os.path.basename(path), path))
    return items


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Legacy inline MIGRATIONS kept for backward compatibility
# (these are now superseded by src/store/migrations/ files)
# ---------------------------------------------------------------------------

# Kept to avoid breaking any direct MIGRATIONS imports from old scripts
MIGRATIONS = []


def _resolve_psql():
    """Return a usable psql executable path, or None."""
    found = shutil.which("psql")
    if found:
        return found
    keg = "/opt/homebrew/opt/libpq/bin/psql"
    return keg if os.path.exists(keg) else None


def apply_via_psql(psql: str, db_url: str, items):
    """Apply each file with `psql -v ON_ERROR_STOP=1 -f`. This is the canonical
    path (same as the GitHub workflows): psql parses dollar-quoted DO $$ ... $$
    blocks correctly and returns a real exit code per file."""
    ok = err = 0
    for name, path in items:
        rc = subprocess.call(
            [psql, db_url, "-v", "ON_ERROR_STOP=1", "-q", "-f", path],
            stdout=subprocess.DEVNULL,
        )
        if rc == 0:
            print(f"  ok {name}")
            ok += 1
        else:
            print(f"  ! {name}: psql exited {rc}")
            err += 1
    return ok, err


def _apply_whole_files(execute, items):
    """Execute each file's FULL contents in a single call — never split on ';',
    so dollar-quoted DO $$ ... $$ blocks stay intact."""
    ok = err = 0
    for name, path in items:
        try:
            execute(_read(path))
            print(f"  ok {name}")
            ok += 1
        except Exception as e:  # noqa: BLE001 — report and continue
            print(f"  ! {name}: {e!s:.120}")
            err += 1
    return ok, err


def apply_via_psycopg2(db_url: str, items):
    import psycopg2  # type: ignore
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    try:
        def execute(sql):
            with conn.cursor() as cur:
                cur.execute(sql)
        return _apply_whole_files(execute, items)
    finally:
        conn.close()


def apply_via_asyncpg(db_url: str, items):
    import asyncio
    import asyncpg  # type: ignore

    async def _run():
        conn = await asyncpg.connect(db_url)
        ok = err = 0
        for name, path in items:
            try:
                await conn.execute(_read(path))
                print(f"  ok {name}")
                ok += 1
            except Exception as e:  # noqa: BLE001
                print(f"  ! {name}: {e!s:.120}")
                err += 1
        await conn.close()
        return ok, err

    return asyncio.run(_run())


def print_manual_instructions(items):
    print("\n  ── MANUAL FALLBACK ──────────────────────────────────────────────")
    print("  Paste the following SQL blocks into your DB SQL editor:")
    print()
    for name, path in items:
        print(f"  -- {name}")
        print(_read(path).strip())
        print()


def main():
    print("=" * 68)
    print("  CVM SCHEMA MIGRATION")
    print("=" * 68)

    items = _build_migration_list()
    db_url = os.environ.get("POSTGRES_URL")
    if not db_url:
        print("  POSTGRES_URL not set.")
        print_manual_instructions(items)
        return
    db_url = "".join(db_url.split())

    print(f"  Applying {len(items)} migration steps...\n")

    # Prefer psql (handles dollar-quoted blocks exactly like the CI workflows).
    psql = _resolve_psql()
    if psql:
        try:
            ok, err = apply_via_psql(psql, db_url, items)
            print(f"\n  Done: {ok} OK, {err} errors  (driver: psql)")
            sys.exit(1 if err else 0)
        except Exception as e:  # noqa: BLE001
            print(f"  psql path failed ({e}); trying a Python driver...")

    # Fall back to a Python driver, executing each file whole (no ';' split).
    for driver, fn in [
        ("psycopg2", apply_via_psycopg2),
        ("asyncpg",  apply_via_asyncpg),
    ]:
        try:
            __import__(driver)
            ok, err = fn(db_url, items)
            print(f"\n  Done: {ok} OK, {err} errors  (driver: {driver})")
            sys.exit(1 if err else 0)
        except ImportError:
            continue
        except Exception as e:  # noqa: BLE001
            print(f"  Connection failed ({driver}): {e}")
            break

    print("\n  No PostgreSQL client available. Falling back to manual instructions.")
    print_manual_instructions(items)


if __name__ == "__main__":
    main()
