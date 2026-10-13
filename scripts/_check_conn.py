"""Bare connection check: connect, then print an estimated row count per table.

The counts are ``pg_class.reltuples`` estimates read in one catalog query, never
``COUNT(*)``: an unbounded count on ``cvm_fi_diario`` scans hundreds of millions
of rows (AGENTS.md, "Database"). ``reltuples`` is -1 for a table never analyzed,
and a partitioned parent holds 0, so a partitioned table sums its partitions.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.store import pg_client  # noqa: E402

TABLES = [
    "cvm_ingest_log", "cvm_fi_diario", "cvm_fidc_mensal",
    "cvm_fidc_tranche", "cvm_fidc_tranche_flows", "cvm_fidc_aging",
    "cvm_fidc_setor", "cvm_fidc_scr", "cvm_fidc_sacado", "cvm_fidc_cedente",
    "cvm_fidc_garantia",
    "cvm_fii_mensal", "cvm_securit_mensal",
    "cvm_securit_serie", "cvm_securit_fluxo",
]

# One row per listed table that exists in schema public. For a partitioned
# parent (relkind 'p') the estimate is the sum of its partitions' estimates,
# and it counts as never analyzed only when no partition has been analyzed.
ESTIMATE_SQL = """
SELECT c.relname,
       CASE WHEN c.relkind = 'p' THEN
            (SELECT COALESCE(SUM(GREATEST(p.reltuples, 0)), 0)
               FROM pg_inherits i JOIN pg_class p ON p.oid = i.inhrelid
              WHERE i.inhparent = c.oid)
            ELSE GREATEST(c.reltuples, 0)
       END::bigint AS est_rows,
       CASE WHEN c.relkind = 'p' THEN
            NOT EXISTS (SELECT 1
                          FROM pg_inherits i JOIN pg_class p ON p.oid = i.inhrelid
                         WHERE i.inhparent = c.oid AND p.reltuples >= 0)
            ELSE c.reltuples < 0
       END AS never_analyzed
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public'
   AND c.relkind IN ('r', 'p')
   AND c.relname = ANY(%s)
"""


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    pooler_url = os.environ["POSTGRES_URL"]
    session_url = re.sub(r":6543/", ":5432/", pooler_url)
    conn = pg_client.connect(session_url)
    try:
        print("Connection: OK")
        with conn.cursor() as cur:
            cur.execute(ESTIMATE_SQL, (TABLES,))
            found = {name: (est, never) for name, est, never in cur.fetchall()}
    finally:
        conn.close()

    print("Row counts are estimates (pg_class.reltuples), not exact.")
    for t in TABLES:
        if t not in found:
            print(f"  {t:<40} {'-':>10}   (missing)")
            continue
        est, never_analyzed = found[t]
        if never_analyzed:
            print(f"  {t:<40} {'?':>10}   (never analyzed)")
            continue
        flag = "✓" if est > 0 else "  (empty)"
        print(f"  {t:<40} ~{est:>9} {flag}")


if __name__ == "__main__":
    main()
