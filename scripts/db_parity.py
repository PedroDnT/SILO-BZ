"""Report all user tables/views in a Postgres DB with row-count estimates.

Use it to confirm schema + data parity between two databases: run it against a
reference DB, then against the target after `apply_schema.py` + re-ingest, and
compare.

Row counts are fast planner estimates (pg_class.reltuples), refreshed by the
pipeline's post-ingest ANALYZE — accurate enough to confirm "data present"
without scanning multi-million-row tables. Pass --exact for true COUNT(*).

Usage:
    POSTGRES_URL=... python scripts/db_parity.py
    POSTGRES_URL=... python scripts/db_parity.py --exact
    python scripts/db_parity.py --url postgresql://...

A :6543 (transaction pooler) URL is rewritten to :5432 (session) for stability,
matching scripts/_check_conn.py.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

import psycopg2
from psycopg2 import sql

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _resolve_url(cli_url: str | None) -> str:
    url = cli_url or os.environ.get("POSTGRES_URL")
    if not url:
        sys.exit("Set POSTGRES_URL (or pass --url).")
    url = "".join(url.split())
    return re.sub(r":6543/", ":5432/", url)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="target connection string (else $POSTGRES_URL)")
    ap.add_argument("--exact", action="store_true", help="exact COUNT(*) instead of estimate")
    args = ap.parse_args()

    conn = psycopg2.connect(_resolve_url(args.url))
    conn.autocommit = True
    with conn.cursor() as cur:
        # Base tables + their estimated live rows (excludes partitions' parent
        # double-counting by reporting each relation independently).
        cur.execute(
            """
            SELECT c.relname,
                   CASE c.relkind WHEN 'r' THEN 'table'
                                  WHEN 'p' THEN 'partitioned'
                                  WHEN 'v' THEN 'view'
                                  WHEN 'm' THEN 'matview' END AS kind,
                   c.reltuples::bigint AS est_rows
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relkind IN ('r', 'p', 'v', 'm')
            ORDER BY c.relkind, c.relname
            """
        )
        rows = cur.fetchall()

        print(f"{'object':<40} {'kind':<12} {'rows':>14}")
        print("-" * 68)
        n_tables = n_views = 0
        for name, kind, est in rows:
            if kind in ("table", "partitioned", "matview"):
                n_tables += 1
                if args.exact:
                    cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(name)))
                    est = cur.fetchone()[0]
                shown = f"{est:>14,}"
            else:
                n_views += 1
                shown = f"{'(view)':>14}"
            print(f"{name:<40} {kind:<12} {shown}")
        print("-" * 68)
        print(f"{n_tables} tables/matviews, {n_views} views"
              f"  ({'exact' if args.exact else 'estimated'} counts)")
    conn.close()


if __name__ == "__main__":
    main()
