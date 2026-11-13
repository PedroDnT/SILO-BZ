"""Print what a backfill starts from, after closing stale audit rows.

backfill.yml's inspect-coverage job runs this once per dispatch, before any
ingest job. It was an inline heredoc in the workflow that opened its own
psycopg2 connection (#1111); the connection now comes from
``src.store.pg_client``.

Two things, in order:

1. Marks every ``cvm_ingest_log`` row still ``running`` 24 hours after it
   started as ``error``, keeping any message it had. A run that old died
   without closing its row; left alone it reads as in progress forever.
2. Prints ``cvm_ingest_log`` by entity / doc type / year / status, then
   ``data_coverage`` for the last 90 days when that function exists.

A failed stale-row update raises (exit 1). A missing ``data_coverage`` is
printed and the report goes on: it is optional context, not the check.

    POSTGRES_URL=... python scripts/backfill_coverage_snapshot.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.store import pg_client  # noqa: E402

STALE_NOTE = "Marked stale by backfill coverage inspection after 24 hours"

MARK_STALE_SQL = f"""
    UPDATE cvm_ingest_log
    SET status = 'error',
        finished_at = COALESCE(finished_at, NOW()),
        error_msg = CONCAT_WS(
          '; ',
          NULLIF(error_msg, ''),
          '{STALE_NOTE}'
        )
    WHERE status = 'running'
      AND started_at < NOW() - INTERVAL '24 hours'
    RETURNING run_id
"""

LOG_SUMMARY_SQL = """
    SELECT entity, COALESCE(doc_type, ''), period_year,
           status, COUNT(*), COALESCE(SUM(rows_upserted), 0)
    FROM cvm_ingest_log
    GROUP BY 1, 2, 3, 4
    ORDER BY 1, 2, 3, 4
"""

COVERAGE_SQL = "SELECT * FROM data_coverage(NULL, CURRENT_DATE - 90, CURRENT_DATE)"


def _tsv(row: Iterable[Any]) -> str:
    return "\t".join(str(x) for x in row)


def run(conn: Any, out=print) -> int:
    """Mark stale rows, print the report, return how many rows were marked."""
    cur = conn.cursor()
    try:
        cur.execute(MARK_STALE_SQL)
        stale = cur.fetchall()
        conn.commit()
        out(f"Marked {len(stale)} stale running audit row(s) as error")

        out("=== cvm_ingest_log by entity / year / status ===")
        cur.execute(LOG_SUMMARY_SQL)
        out("entity\tdoc_type\tyear\tstatus\tn_runs\trows")
        for row in cur.fetchall():
            out(_tsv(row))

        out("=== data_coverage last 90 days (api) ===")
        try:
            cur.execute(COVERAGE_SQL)
            cols: Sequence[str] = [d[0] for d in cur.description]
            out(_tsv(cols))
            for row in cur.fetchall():
                out(_tsv(row))
        except Exception as e:  # printed, not swallowed: optional context only
            out(f"data_coverage unavailable: {e}")
            conn.rollback()
    finally:
        cur.close()
    return len(stale)


def main(environ: Optional[dict] = None) -> int:
    env = os.environ if environ is None else environ
    url = "".join((env.get("POSTGRES_URL") or "").split())
    if not url:
        print("POSTGRES_URL missing — cannot inspect coverage")
        return 0
    conn = pg_client.connect(url, connect_timeout=20)
    try:
        run(conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
