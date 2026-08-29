"""Ingest-staleness check for the headless watchdog.

The pipeline normally runs once a day via the 06:00 UTC GitHub Actions cron
(`.github/workflows/daily_ingest.yml`). If that run is delayed, fails, or is
skipped, data silently goes stale. The `watchdog.yml` workflow runs a couple of
hours later, calls this module, and — if a slice is stale **or** the health
gate's unhealed-error query would fire — re-runs the daily ingest to self-heal.

This is deliberately a plain GitHub-Actions job (reusing the existing
`POSTGRES_URL` secret) rather than a DB-side pg_cron+pg_net trigger: it keeps all
logic in the repo (testable, no GitHub PAT stored in the database).

Staleness is measured against `cvm_ingest_log`, which carries exactly one row per
ingest run (`_log_start`/`_log_finish` in `src/pipeline/cvm_pipeline.py`). A slice
is *fresh* when its most recent `status='ok'` row finished within the threshold.

Exit codes (consumed by the workflow's `if:` steps):
    0   — everything fresh (no-op)
    10  — the daily FI slice is stale, or unhealed ingest errors remain → re-run daily ingest
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

# Same window as health.yml MAX_INGEST_ERROR_HOURS. Unhealed error slices in
# this window are exactly what turns DB Health red; the watchdog must retry
# them, including on weekends.
UNHEALED_ERROR_HOURS = 26

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


def unhealed_error_slices(conn: Any, hours: float = UNHEALED_ERROR_HOURS) -> int:
    """Count ingest slices whose latest attempt in the window is still ``error``.

    Same predicate as ``.github/workflows/health.yml`` check 1: a later ``ok``
    or ``skipped`` heals; ``IS NOT DISTINCT FROM`` matches NULL period keys
    (yearly FII/SECURIT). Watchdog recovery on 2026-08-29 no-op'd because
    ``fi/inf_diario`` still had Friday's ``ok`` and Saturday is weekday-gated,
    while DB Health failed on 44 unhealed ``CVMHostUnreachable`` slices from
    the 06:00 run (33237536770). Those are a failed cron, not a quiet weekend.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) FROM (
              SELECT DISTINCT entity, doc_type, period_year, period_month
                FROM cvm_ingest_log e
               WHERE e.status = 'error'
                 AND e.started_at > now() - (%s * interval '1 hour')
                 AND NOT EXISTS (
                       SELECT 1 FROM cvm_ingest_log s
                        WHERE s.status IN ('ok', 'skipped')
                          AND s.entity       IS NOT DISTINCT FROM e.entity
                          AND s.doc_type     IS NOT DISTINCT FROM e.doc_type
                          AND s.period_year  IS NOT DISTINCT FROM e.period_year
                          AND s.period_month IS NOT DISTINCT FROM e.period_month
                          AND s.started_at   > e.started_at)
            ) unhealed
            """,
            (hours,),
        )
        row = cur.fetchone()
    return int(row[0] if row and row[0] is not None else 0)


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
        unhealed = unhealed_error_slices(conn, UNHEALED_ERROR_HOURS)
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
    print(f"[staleness] unhealed ingest errors ({UNHEALED_ERROR_HOURS}h): {unhealed}")

    # Unhealed errors first, and never weekend-gated. weekday_only exists so a
    # quiet Saturday does not look like a missed cron; 44 CVMHostUnreachable
    # rows from a Saturday 06:00 that DID fire are the opposite.
    if unhealed > 0:
        print("[staleness] -> unhealed ingest errors; recovery required")
        return EXIT_DAILY_STALE
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
