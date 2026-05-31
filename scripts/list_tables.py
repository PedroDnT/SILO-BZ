#!/usr/bin/env python3
"""
List every schema / table / row-count / column in a Postgres database.

Usage:
    python scripts/list_tables.py                  # uses POSTGRES_URL (or DATABASE_URL) from .env
    python scripts/list_tables.py --columns        # also dump columns per table
    python scripts/list_tables.py --url "postgresql://..."     # explicit URL
    SUPABASE_DB_PASSWORD=xxx python scripts/list_tables.py --supabase   # build Supabase URL

The pooled Supabase URL uses port 6543; introspection works fine on either, but we
rewrite :6543 -> :5432 (session mode) to be safe for ad-hoc queries.
"""
import argparse
import asyncio
import os
import re
import sys

import asyncpg
from dotenv import load_dotenv

# Supabase project from the pasted connection string.
SUPABASE_HOST = "db.zcjbtpxuhdekpwcxmepn.supabase.co"


def resolve_url(args) -> str:
    if args.url:
        return args.url
    if args.supabase:
        pw = os.environ.get("SUPABASE_DB_PASSWORD")
        if not pw:
            sys.exit(
                "ERROR: --supabase needs the DB password.\n"
                "  export SUPABASE_DB_PASSWORD='your-db-password'\n"
                "(Supabase Dashboard -> Project Settings -> Database -> Connection string)"
            )
        return f"postgresql://postgres:{pw}@{SUPABASE_HOST}:5432/postgres?sslmode=require"
    url = os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("ERROR: no --url, no --supabase, and POSTGRES_URL/DATABASE_URL not set.")
    return url


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="explicit postgres URL")
    ap.add_argument("--supabase", action="store_true", help="build URL for the Supabase project")
    ap.add_argument("--columns", action="store_true", help="also list columns per table")
    args = ap.parse_args()

    load_dotenv()
    url = re.sub(r":6543/", ":5432/", "".join(resolve_url(args).split()))

    safe = re.sub(r"://([^:]+):[^@]+@", r"://\1:***@", url)
    print(f"Connecting -> {safe}")
    try:
        conn = await asyncpg.connect(url, timeout=20)
    except Exception as exc:
        sys.exit(f"CONNECTION FAILED: {exc!r}")
    print("Connection: OK\n")

    rows = await conn.fetch(
        """
        SELECT n.nspname AS schema, c.relname AS table,
               COALESCE(c.reltuples::bigint, 0) AS est_rows
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r', 'p')
          AND n.nspname NOT IN ('pg_catalog', 'information_schema')
          AND n.nspname NOT LIKE 'pg_temp%'
        ORDER BY n.nspname, c.relname
        """
    )

    if not rows:
        print("No user tables found in any non-system schema.")
        await conn.close()
        return

    current = None
    for r in rows:
        if r["schema"] != current:
            current = r["schema"]
            print(f"=== schema: {current} ===")
        # exact count (est_rows is stale for never-analyzed tables)
        n = await conn.fetchval(f'SELECT COUNT(*) FROM "{r["schema"]}"."{r["table"]}"')
        flag = "✓" if n else "(empty)"
        print(f"  {r['table']:<42} {n:>12,} {flag}")
        if args.columns:
            cols = await conn.fetch(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = $1 AND table_name = $2
                ORDER BY ordinal_position
                """,
                r["schema"], r["table"],
            )
            for c in cols:
                null = "" if c["is_nullable"] == "YES" else " NOT NULL"
                print(f"        - {c['column_name']:<30} {c['data_type']}{null}")

    await conn.close()
    print(f"\nDone. {len(rows)} table(s).")


if __name__ == "__main__":
    asyncio.run(main())
