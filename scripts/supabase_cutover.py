#!/usr/bin/env python3
"""
Verify the Supabase cutover: connect with POSTGRES_URL, confirm the rebuilt
schema is present, and report row counts. Run this right after putting the
Supabase DB password into .env (replacing [SUPABASE_DB_PASSWORD]).

    .venv/bin/python scripts/supabase_cutover.py

If the session-pooler host can't be resolved, it transparently falls back to
the direct host (db.<ref>.supabase.co:5432) so a wrong aws-0/aws-1 guess still
works for local runs.
"""
import os
import re
import sys

import psycopg2
from dotenv import load_dotenv

PROJECT_REF = "zcjbtpxuhdekpwcxmepn"
DIRECT_HOST = f"db.{PROJECT_REF}.supabase.co"


def candidate_urls(url: str):
    yield url
    # Fallback: rewrite a pooler URL to the direct connection.
    if "pooler.supabase.com" in url:
        direct = re.sub(r"@[^/]+/", f"@{DIRECT_HOST}:5432/", url)
        direct = direct.replace(f"postgres.{PROJECT_REF}:", "postgres:")
        yield direct


def main() -> None:
    load_dotenv()
    url = os.environ.get("POSTGRES_URL", "")
    if not url or "[SUPABASE_DB_PASSWORD]" in url or "<password>" in url:
        sys.exit(
            "POSTGRES_URL still has the database password placeholder.\n"
            "Edit .env and paste the real Supabase database password first."
        )
    url = "".join(url.split())

    conn = last_err = None
    for cand in candidate_urls(url):
        try:
            conn = psycopg2.connect(cand, connect_timeout=20)
            safe = re.sub(r":[^:@/]+@", ":***@", cand)
            print(f"Connection OK -> {safe}")
            break
        except Exception as exc:
            last_err = exc
    if conn is None:
        sys.exit(f"CONNECTION FAILED: {last_err!r}")

    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT current_database(), current_user, version()")
        db, user, ver = cur.fetchone()
        print(f"  db={db} user={user}")
        print(f"  {ver.split(',')[0]}")
        cur.execute(
            """
            SELECT c.relname, COALESCE(c.reltuples::bigint, 0)
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relkind IN ('r','p')
            ORDER BY c.relname
            """
        )
        rows = cur.fetchall()
    print(f"\n{len(rows)} tables in public:")
    total = 0
    for name, est in rows:
        if est > 0:
            print(f"  {name:<40} {est:>12,}  (est.)")
        total += max(est, 0)
    print(f"\nTotal rows across all tables: ~{total:,}  (pg_class estimates)")
    if total == 0:
        print("Schema is present but EMPTY — ready for fresh ingestion.")
    conn.close()


if __name__ == "__main__":
    main()
