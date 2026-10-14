#!/usr/bin/env python3
"""
List every schema / table / estimated row count (pg_class.reltuples) / column
in a Postgres database.

Usage:
    python scripts/list_tables.py                  # uses POSTGRES_URL (or DATABASE_URL) from .env
    python scripts/list_tables.py --columns        # also dump columns per table
    python scripts/list_tables.py --url "postgresql://..."     # explicit URL
    SUPABASE_DB_PASSWORD=xxx python scripts/list_tables.py --supabase   # build Supabase URL

The pooled Supabase URL uses port 6543; introspection works fine on either, but we
rewrite :6543 -> :5432 (session mode) to be safe for ad-hoc queries.
"""
import argparse
import os
import re
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.store import pg_client  # noqa: E402

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


def main() -> None:
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
        conn = pg_client.connect(url, connect_timeout=20)
    except Exception as exc:
        sys.exit(f"CONNECTION FAILED: {exc!r}")
    print("Connection: OK\n")

    cur = conn.cursor()
    cur.execute(
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
    rows = [dict(zip(("schema", "table", "est_rows"), r)) for r in cur.fetchall()]

    if not rows:
        print("No user tables found in any non-system schema.")
        conn.close()
        return

    current = None
    for r in rows:
        if r["schema"] != current:
            current = r["schema"]
            print(f"=== schema: {current} ===")
        # pg_class.reltuples estimate, never a COUNT(*) (AGENTS.md, #947):
        # -1 means never analyzed; a partitioned parent holds 0 and its
        # partitions are listed on their own rows.
        n = r["est_rows"]
        if n < 0:
            print(f"  {r['table']:<42} {'?':>12} (never analyzed)")
        else:
            flag = "✓" if n else "(empty)"
            print(f"  {r['table']:<42} {n:>12,} {flag}")
        if args.columns:
            cur.execute(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
                """,
                (r["schema"], r["table"]),
            )
            for column_name, data_type, is_nullable in cur.fetchall():
                null = "" if is_nullable == "YES" else " NOT NULL"
                print(f"        - {column_name:<30} {data_type}{null}")

    conn.close()
    print(f"\nDone. {len(rows)} table(s).")


if __name__ == "__main__":
    main()
