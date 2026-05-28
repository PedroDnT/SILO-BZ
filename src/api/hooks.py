"""Post-job error classifier and inefficiency detector.

Runs after every `ingest` / `daily` / `verify` job. Inspects the captured
exception (if any), job duration, and row count, then appends structured
entries to `job.warnings` and `job.error`.

Hooks do not retry — they only categorise. Retry is an operator decision
(re-POST the same payload).
"""

from __future__ import annotations

import logging
import socket
import traceback
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ---- Error classification ------------------------------------------------

def classify_error(exc: BaseException) -> Dict[str, Any]:
    """Map an exception to a stable error_type string + safe metadata."""
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    msg = str(exc)
    err_type = _classify_type(exc, msg)
    return {
        "type": err_type,
        "exception": type(exc).__name__,
        "message": msg[:500],
        "traceback": tb[-2000:],
    }


def _classify_type(exc: BaseException, msg: str) -> str:
    mod = type(exc).__module__
    name = type(exc).__name__
    lower = msg.lower()

    # Network / DNS / timeout
    if isinstance(exc, (TimeoutError, socket.gaierror)):
        return "network"
    if mod.startswith("aiohttp"):
        return "network"
    if "timeout" in lower or "connection" in lower or "dns" in lower:
        return "network"

    # Supabase / Postgrest write
    if mod.startswith("postgrest") or mod.startswith("supabase"):
        if "column" in lower and ("does not exist" in lower or "schema" in lower):
            return "schema_mismatch"
        if "permission" in lower or "rls" in lower or "row-level security" in lower:
            return "supabase_write"
        return "supabase_write"
    if "duplicate key" in lower or "on_conflict" in lower:
        return "supabase_write"

    # CSV / encoding / parsing
    if isinstance(exc, (UnicodeDecodeError, KeyError)):
        return "csv_parse"
    if name in ("ParserError", "EmptyDataError"):
        return "csv_parse"
    if "csv" in lower or "encoding" in lower:
        return "csv_parse"

    return "unknown"


# ---- Inefficiency / no-data heuristics -----------------------------------

def inspect_outcome(
    *,
    rows: int,
    started_at: Optional[str],
    finished_at: Optional[str],
    raised: bool,
) -> list[Dict[str, Any]]:
    """Return structured warnings about job efficiency / data availability."""
    warnings: list[Dict[str, Any]] = []
    duration = _duration_seconds(started_at, finished_at)

    if not raised and rows == 0:
        warnings.append({
            "type": "no_data_published",
            "message": (
                "Ingest completed but inserted 0 rows. CVM may not have published "
                "this period yet, or the dataset is empty. Retry later or pick a "
                "different (year, month)."
            ),
            "duration_seconds": duration,
        })

    if duration is not None and duration > 300 and rows < 1000:
        warnings.append({
            "type": "slow_ingest",
            "message": (
                f"Ingest took {duration:.0f}s for {rows} rows. Likely upstream "
                f"slowness or DNS rotation. Inspect logs for retry messages."
            ),
            "duration_seconds": duration,
            "rows": rows,
        })

    return warnings


# ---- Audit-log correlation -----------------------------------------------

def fetch_audit_warning(
    supabase: Any, entity: str, doc_type: str, year: int, month: Optional[int]
) -> Optional[Dict[str, Any]]:
    """Look up the latest `cvm_ingest_log` row for this slice and surface its
    `error_msg` field (if any) as a warning. The API doc_type alias (e.g.
    "tranche") differs from the pipeline's per-CVM-file doc_type ("mensal_tab_x2")
    — we filter on entity + period only and then pick the most recent row. Failure
    here is non-fatal."""
    try:
        sql = (
            "SELECT run_id, status, doc_type, error_msg, finished_at, rows_upserted"
            " FROM cvm_ingest_log WHERE entity=%s AND period_year=%s"
        )
        params: list = [entity, year]
        if month is not None:
            sql += " AND period_month=%s"
            params.append(month)
        sql += " ORDER BY finished_at DESC LIMIT 5"
        with supabase.cursor() as cur:
            cur.execute(sql, tuple(params))
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        for row in rows:
            if row.get("error_msg"):
                return {
                    "type": "audit_log_error",
                    "message": row["error_msg"][:500],
                    "run_id": row.get("run_id"),
                    "doc_type": row.get("doc_type"),
                    "finished_at": row.get("finished_at"),
                    "rows_upserted": row.get("rows_upserted"),
                }
        return None
    except Exception as exc:
        logger.debug("audit log lookup failed: %s", exc)
        return None


# ---- helpers --------------------------------------------------------------

def _duration_seconds(started: Optional[str], finished: Optional[str]) -> Optional[float]:
    if not started or not finished:
        return None
    try:
        s = datetime.fromisoformat(started)
        f = datetime.fromisoformat(finished)
        return (f - s).total_seconds()
    except Exception:
        return None
