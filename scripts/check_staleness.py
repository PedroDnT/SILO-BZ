"""Ingest-staleness check for the headless watchdog.

The pipeline normally runs once a day via the 06:00 UTC GitHub Actions cron
(`.github/workflows/daily_ingest.yml`). If that run is delayed, fails, or is
skipped, data silently goes stale. The `watchdog.yml` workflow runs a couple of
hours later, calls this module, and — if a slice is stale — re-runs the daily
ingest to self-heal.

This is deliberately a plain GitHub-Actions job (reusing the existing
`POSTGRES_URL` secret) rather than a DB-side pg_cron+pg_net trigger: it keeps all
logic in the repo (testable, no GitHub PAT stored in the database).

Staleness is measured against `cvm_ingest_log`, which carries exactly one row per
ingest run (`_log_start`/`_log_finish` in `src/pipeline/cvm_pipeline.py`). A slice
is *fresh* when its most recent `status='ok'` row finished within the threshold.

Exit codes (consumed by the workflow's `if:` steps):
    0   — everything fresh (no-op)
    10  — the daily FI slice is stale → re-run daily ingest
    11  — only the monthly ANBIMA/ETF slice is stale → re-run daily ingest

Run standalone:
    POSTGRES_URL=... python scripts/check_staleness.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any, Optional

# Reuse the single sanctioned DB entry point — never open a raw connection here
# (data-integrity rule: all DB access goes through pg_client).
from src.store.pg_client import get_pg_client

# Proxy slices. The daily FI snapshot is the canonical "did the daily run happen"
# signal; re-running run_daily recovers every daily slice (FI/FIDC/FIAGRO/ETF
# registry + ANBIMA). ANBIMA is monthly, so it gets a much longer threshold.
DAILY_ENTITY, DAILY_DOC = "fi", "inf_diario"
DAILY_THRESHOLD_HOURS = 26          # one cron period + slack

MONTHLY_ENTITY, MONTHLY_DOC = "anbima_etf", "boletim_mensal"
MONTHLY_THRESHOLD_HOURS = 35 * 24   # ~35 days — boletim is published monthly

EXIT_FRESH = 0
EXIT_DAILY_STALE = 10
EXIT_MONTHLY_STALE = 11


def last_success_age_hours(
    conn: Any, entity: str, doc_type: str
) -> Optional[float]:
    """Hours since the most recent successful ingest of (entity, doc_type).

    Returns None when no successful run has ever been recorded (treated as
    stale by callers — a slice that never ran needs attention).
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MAX(finished_at) FROM cvm_ingest_log "
            "WHERE entity = %s AND doc_type = %s "
            "AND status = 'ok' AND finished_at IS NOT NULL",
            (entity, doc_type),
        )
        row = cur.fetchone()

    last = row[0] if row else None
    if last is None:
        return None
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last).total_seconds() / 3600.0


def is_stale(
    conn: Any,
    entity: str,
    doc_type: str,
    threshold_hours: float,
    weekday_only: bool = True,
) -> bool:
    """True when (entity, doc_type) has no successful run within threshold_hours.

    weekday_only suppresses false positives on weekends, when CVM publishes no
    new data and a re-run would be redundant. Mon–Fri are weekdays 0–4 (UTC).
    """
    if weekday_only and datetime.now(timezone.utc).weekday() >= 5:
        return False
    age = last_success_age_hours(conn, entity, doc_type)
    return age is None or age > threshold_hours


def main() -> int:
    conn = get_pg_client()
    try:
        daily_stale = is_stale(
            conn, DAILY_ENTITY, DAILY_DOC, DAILY_THRESHOLD_HOURS,
            weekday_only=True,
        )
        # ANBIMA is monthly and published any day — don't weekday-gate it.
        monthly_stale = is_stale(
            conn, MONTHLY_ENTITY, MONTHLY_DOC, MONTHLY_THRESHOLD_HOURS,
            weekday_only=False,
        )
    finally:
        try:
            conn.close()
        except Exception:
            pass

    daily_age = "fresh" if not daily_stale else "STALE"
    monthly_age = "fresh" if not monthly_stale else "STALE"
    print(f"[staleness] daily ({DAILY_ENTITY}/{DAILY_DOC}): {daily_age}")
    print(f"[staleness] monthly ({MONTHLY_ENTITY}/{MONTHLY_DOC}): {monthly_age}")

    if daily_stale:
        print("[staleness] -> daily ingest is stale; recovery required")
        return EXIT_DAILY_STALE
    if monthly_stale:
        print("[staleness] -> monthly ANBIMA/ETF slice is stale; recovery required")
        return EXIT_MONTHLY_STALE
    print("[staleness] -> all slices fresh; no action")
    return EXIT_FRESH


if __name__ == "__main__":
    sys.exit(main())
