"""Move DENOM_SOCIAL out of `raw` on the stored CDA rows (migration 60).

The ingest stopped writing the fund name into `raw` on cvm_fi_cda,
cvm_fi_cda_acoes and cvm_fi_cda_cotas; it goes to cvm_fi_cda_fund_name once
per fund, month and name. This script does the same for the rows already
stored, in batches of physical pages (ctid ranges, so no batch scans the whole
table). Each batch is one transaction: the names are copied into
cvm_fi_cda_fund_name first, then removed from `raw`. Re-running is safe: a row
without the key is skipped and the copy is an upsert.

An UPDATE writes a new row version and WAL, so a plain VACUUM runs between
chunks of batches to let the next updates reuse the space; the table still
carries about one chunk of bloat at a time. Run this only once the balancete
account table is dropped (docs/planning/OPEN_ITEMS.md item 10): with the disk
near 86% that transient growth could trip DB Health's 90% alarm or a disk
expansion. The space only goes back to the operating system with
--vacuum-full, which rewrites each table under an exclusive lock and needs
free disk about the size of the table.

A run that stops midway (a job timeout) is resumed by running it again: rows
already stripped are skipped.

    python scripts/strip_cda_fund_name.py                    # all three tables
    python scripts/strip_cda_fund_name.py --table cvm_fi_cda_cotas
    python scripts/strip_cda_fund_name.py --vacuum-full

Runs in GitHub Actions as `daily_ingest` mode=cda-fund-name.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logger = logging.getLogger("strip_cda_fund_name")

TABLES = ("cvm_fi_cda_cotas", "cvm_fi_cda_acoes", "cvm_fi_cda")
NAME_TABLE = "cvm_fi_cda_fund_name"
PAGES_PER_BATCH = 20_000      # 160 MB of heap
BATCHES_PER_VACUUM = 10

COPY_SQL = """
INSERT INTO {name_table} (cnpj, period, denom_social)
SELECT DISTINCT cnpj, period, raw->>'DENOM_SOCIAL'
FROM {table}
WHERE ctid >= %(lo)s::tid AND ctid < %(hi)s::tid
  AND raw ? 'DENOM_SOCIAL'
ON CONFLICT ON CONSTRAINT uq_fi_cda_fund_name DO UPDATE
    SET denom_social = EXCLUDED.denom_social
"""

STRIP_SQL = """
UPDATE {table} SET raw = raw - 'DENOM_SOCIAL'
WHERE ctid >= %(lo)s::tid AND ctid < %(hi)s::tid
  AND raw ? 'DENOM_SOCIAL'
"""


def batches(n_pages: int, size: int = PAGES_PER_BATCH):
    """(lo, hi) ctid bounds covering pages 0 .. n_pages-1."""
    for start in range(0, n_pages, size):
        yield f"({start},0)", f"({min(start + size, n_pages)},0)"


def strip_table(client, table: str) -> int:
    if table not in TABLES:
        raise ValueError(f"not a CDA table with a fund name in raw: {table}")
    with client.cursor() as cur:
        cur.execute("SELECT pg_relation_size(%s::regclass) / current_setting('block_size')::int",
                    (table,))
        n_pages = int(cur.fetchone()[0])
    logger.info("%s: %d pages", table, n_pages)

    copy_sql = COPY_SQL.format(name_table=NAME_TABLE, table=table)
    strip_sql = STRIP_SQL.format(table=table)
    stripped = 0
    for i, (lo, hi) in enumerate(batches(n_pages), start=1):
        with client.cursor() as cur:
            cur.execute("SET statement_timeout = '30min'")
            cur.execute("BEGIN")
            try:
                cur.execute(copy_sql, {"lo": lo, "hi": hi})
                names = cur.rowcount
                cur.execute(strip_sql, {"lo": lo, "hi": hi})
                rows = cur.rowcount
                cur.execute("COMMIT")
            except Exception:
                cur.execute("ROLLBACK")
                raise
        stripped += rows
        logger.info("%s pages %s..%s: %d rows stripped, %d name rows upserted",
                    table, lo, hi, rows, names)
        if i % BATCHES_PER_VACUUM == 0:
            with client.cursor() as cur:
                cur.execute("SET statement_timeout = 0")
                cur.execute(f"VACUUM {table}")

    with client.cursor() as cur:
        cur.execute("SET statement_timeout = 0")
        cur.execute(f"VACUUM {table}")
        cur.execute(f"SELECT count(*) FROM {table} WHERE raw ? 'DENOM_SOCIAL'")
        left = cur.fetchone()[0]
    logger.info("%s: %d rows stripped, %d still carry the name", table, stripped, left)
    if left:
        raise RuntimeError(f"{table}: {left} rows still carry DENOM_SOCIAL in raw")
    return stripped


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--table", choices=TABLES, help="one table (default: all three)")
    ap.add_argument("--vacuum-full", action="store_true",
                    help="rewrite each table afterwards to return the space (needs free disk)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from src.store.pg_client import get_pg_client

    client = get_pg_client()
    try:
        for table in ([args.table] if args.table else TABLES):
            strip_table(client, table)
            if args.vacuum_full:
                with client.cursor() as cur:
                    cur.execute("SET statement_timeout = 0")
                    cur.execute(f"VACUUM FULL {table}")
                logger.info("%s: rewritten", table)
    finally:
        client.closeall()
    return 0


if __name__ == "__main__":
    sys.exit(main())
