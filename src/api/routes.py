"""Flask blueprint exposing CVMIngestor as a job-driven HTTP control plane.

All routes return JSON. Background work runs on daemon threads; each thread
wraps `asyncio.run(...)` around the ingestor coroutine, then invokes
`hooks` to classify the outcome before flipping the job to `done` / `failed`.

This is intended for localhost only — no auth.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request

from src.api import dispatch, hooks
from src.api.jobs import Job, get_registry

logger = logging.getLogger(__name__)

bp = Blueprint("api", __name__)

# Lazily-built ingestor singletons — heavy (open aiohttp session, supabase client).
_cvm_ingestor: Any = None
_bacen_ingestor: Any = None
_cvm_lock = threading.Lock()
_bacen_lock = threading.Lock()


def _get_cvm_ingestor():
    global _cvm_ingestor
    with _cvm_lock:
        if _cvm_ingestor is None:
            from src.pipeline.cvm_pipeline import CVMIngestor
            _cvm_ingestor = CVMIngestor()
        return _cvm_ingestor


def _get_bacen_ingestor():
    global _bacen_ingestor
    with _bacen_lock:
        if _bacen_ingestor is None:
            from src.pipeline.bacen_pipeline import BacenIngestor
            _bacen_ingestor = BacenIngestor()
        return _bacen_ingestor


# Test seam — pytest patches these with mocks so no live Supabase / network.
def _ingestor_factory():
    return _get_cvm_ingestor()


def _bacen_factory():
    return _get_bacen_ingestor()


# ---------------------------------------------------------------------------
# Health / status
# ---------------------------------------------------------------------------

@bp.get("/healthz")
def healthz():
    db_status = "ok"
    db_detail: Optional[str] = None
    try:
        ing = _ingestor_factory()
        with ing._supabase.cursor() as cur:
            cur.execute("SELECT run_id FROM cvm_ingest_log LIMIT 1")
    except Exception as exc:
        db_status = "error"
        db_detail = str(exc)[:300]
    postgres_url = os.getenv("POSTGRES_URL", "")
    safe_url = postgres_url.split("@")[-1] if "@" in postgres_url else postgres_url
    return jsonify({
        "status": "ok" if db_status == "ok" else "degraded",
        "postgres": db_status,
        "postgres_detail": db_detail,
        "postgres_host": safe_url,
    })


# Tables reported by GET /api/status. Module-level so tests and operators can
# read the list without re-deriving it.
STATUS_TABLES = [
    "cvm_fi_diario", "cvm_fi_cda", "cvm_fi_perfil",
    "cvm_fidc_mensal", "cvm_fidc_tranche", "cvm_fidc_tranche_flows", "cvm_fidc_aging",
    "cvm_fiagro_mensal",
    "cvm_fip_periodic", "cvm_fii_mensal", "cvm_fii_periodic", "cvm_fii_imovel",
    "cvm_securit_mensal", "cvm_securit_serie", "cvm_securit_fluxo", "cvm_securit_dfin",
    "b3_cotahist",
]


@bp.get("/api/status")
def status():
    """Per-table row counts + latest entry in `cvm_ingest_log`."""
    try:
        conn = _ingestor_factory()._supabase
    except Exception as exc:
        return jsonify({"error": "db_init", "detail": str(exc)}), 503

    counts: Dict[str, Any] = {}
    for t in STATUS_TABLES:
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM {t}")
                counts[t] = cur.fetchone()[0]
        except Exception as exc:
            counts[t] = {"error": str(exc)[:200]}

    last_log: Optional[Any] = None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT run_id, entity, doc_type, period_year, period_month,"
                " status, rows_upserted, finished_at, error_msg"
                " FROM cvm_ingest_log ORDER BY finished_at DESC LIMIT 5"
            )
            cols = [d[0] for d in cur.description]
            last_log = [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as exc:
        last_log = {"error": str(exc)[:200]}

    return jsonify({"row_counts": counts, "recent_runs": last_log})


@bp.get("/api/dispatch")
def dispatch_table():
    """Return all valid (entity, doc_type) pairs grouped by entity."""
    return jsonify({"entities": dispatch.all_pairs()})


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

@bp.post("/api/ingest")
def ingest_one():
    payload = request.get_json(silent=True) or {}
    entity = payload.get("entity")
    doc_type = payload.get("doc_type")
    year = payload.get("year")
    month = payload.get("month")

    if not entity or not doc_type or year is None:
        return jsonify({"error": "missing_field", "required": ["entity", "doc_type", "year"]}), 400
    try:
        year = int(year)
    except (TypeError, ValueError):
        return jsonify({"error": "year must be integer"}), 400
    if month is not None:
        try:
            month = int(month)
        except (TypeError, ValueError):
            return jsonify({"error": "month must be integer 1-12 or omitted"}), 400

    try:
        resolved = dispatch.resolve(entity, doc_type)
    except KeyError as exc:
        return jsonify({"error": "unknown_pair", "detail": str(exc)}), 404
    if resolved.needs_month and month is None:
        return jsonify({"error": "missing_month", "detail": f"{resolved.method_name} requires month"}), 400

    registry = get_registry()
    job = registry.create("ingest", {
        "entity": entity, "doc_type": doc_type, "year": year, "month": month,
        "table": resolved.table, "method": resolved.method_name,
    })
    job.table = resolved.table
    registry.update(job.id, table=resolved.table)

    threading.Thread(
        target=_run_ingest_job,
        args=(job.id, resolved, year, month, entity, doc_type),
        daemon=True,
        name=f"ingest-{job.id[:8]}",
    ).start()
    return jsonify({"job_id": job.id, "status": job.status, "table": resolved.table}), 202


@bp.post("/api/ingest/range")
def ingest_range():
    """Spawn one parent + N child jobs covering a year range (and month range
    for monthly conventions). Child jobs run sequentially in one worker thread
    so we don't fan out network calls to CVM."""
    payload = request.get_json(silent=True) or {}
    entity = payload.get("entity")
    doc_type = payload.get("doc_type")
    year_start = payload.get("year_start")
    year_end = payload.get("year_end")
    months = payload.get("months")  # optional list[int]

    if not entity or not doc_type or year_start is None or year_end is None:
        return jsonify({
            "error": "missing_field",
            "required": ["entity", "doc_type", "year_start", "year_end"],
        }), 400
    try:
        year_start = int(year_start)
        year_end = int(year_end)
    except (TypeError, ValueError):
        return jsonify({"error": "year_start / year_end must be integers"}), 400
    if year_end < year_start:
        return jsonify({"error": "year_end < year_start"}), 400
    try:
        resolved = dispatch.resolve(entity, doc_type)
    except KeyError as exc:
        return jsonify({"error": "unknown_pair", "detail": str(exc)}), 404

    slices: list[tuple[int, Optional[int]]] = []
    if resolved.needs_month:
        ms = months if months else list(range(1, 13))
        for y in range(year_start, year_end + 1):
            for m in ms:
                slices.append((y, int(m)))
    else:
        for y in range(year_start, year_end + 1):
            slices.append((y, None))

    registry = get_registry()
    parent = registry.create("ingest_range", {
        "entity": entity, "doc_type": doc_type,
        "year_start": year_start, "year_end": year_end,
        "months": months, "slice_count": len(slices), "table": resolved.table,
    })
    registry.update(parent.id, table=resolved.table)

    threading.Thread(
        target=_run_range_job,
        args=(parent.id, resolved, slices, entity, doc_type),
        daemon=True,
        name=f"range-{parent.id[:8]}",
    ).start()
    return jsonify({"job_id": parent.id, "status": parent.status, "slice_count": len(slices)}), 202


@bp.post("/api/daily")
def daily():
    registry = get_registry()
    job = registry.create("daily", {})
    threading.Thread(
        target=_run_daily_job, args=(job.id,), daemon=True, name=f"daily-{job.id[:8]}",
    ).start()
    return jsonify({"job_id": job.id, "status": job.status}), 202


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

@bp.get("/api/jobs")
def list_jobs():
    limit = request.args.get("limit", default=50, type=int)
    return jsonify({"jobs": [j.to_dict() for j in get_registry().list(limit=limit)]})


@bp.get("/api/jobs/<job_id>")
def get_job(job_id: str):
    job = get_registry().get(job_id)
    if not job:
        return jsonify({"error": "not_found"}), 404
    return jsonify(job.to_dict())


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------

@bp.post("/api/verify")
def verify():
    """Run a small subset of `scripts/verify_pipeline.py`: per-table counts
    and null-rate sentinels from docs/PLAN.md Quality Gates. Synchronous
    (fast) so we return the report inline instead of a job."""
    try:
        sup = _ingestor_factory()._supabase
    except Exception as exc:
        return jsonify({"error": "supabase_init", "detail": str(exc)}), 503

    report = _verify_report(sup)
    return jsonify(report)


def _verify_report(sup) -> Dict[str, Any]:
    gates = [
        ("cvm_fidc_mensal",  "vl_patrim_liq",            0.01),
        ("cvm_fidc_tranche", "vl_rentab_mes",            0.05),
        ("cvm_fidc_aging",   "vl_total_inad",            0.05),
        ("cvm_fii_mensal",   "vl_patrim_liq",            0.01),
        ("cvm_fii_mensal",   "pct_dividend_yield_mes",   0.05),
        ("cvm_securit_serie","situacao",                 0.01),
    ]
    results = []
    for table, field, max_null_rate in gates:
        try:
            with sup.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                total = cur.fetchone()[0] or 0
                cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {field} IS NULL")
                nulls = cur.fetchone()[0] or 0
            rate = (nulls / total) if total else None
            passing = rate is not None and rate <= max_null_rate
            results.append({
                "table": table, "field": field,
                "total_rows": total, "null_rows": nulls,
                "null_rate": rate, "max_allowed": max_null_rate,
                "status": "pass" if passing else ("empty" if total == 0 else "fail"),
            })
        except Exception as exc:
            results.append({
                "table": table, "field": field,
                "error": str(exc)[:200], "status": "error",
            })
    return {"quality_gates": results}


# ---------------------------------------------------------------------------
# Worker functions
# ---------------------------------------------------------------------------

def _run_ingest_job(
    job_id: str, resolved: dispatch.Resolved, year: int, month: Optional[int],
    entity: str, doc_type: str,
) -> int:
    registry = get_registry()
    registry.mark_running(job_id)
    raised = False
    rows = 0
    try:
        ingestor = _ingestor_factory()
        thunk = dispatch.build_call(ingestor, resolved, year, month)
        rows = asyncio.run(thunk())
        registry.mark_done(job_id, rows=rows)
    except BaseException as exc:                # noqa: BLE001 - we re-classify
        raised = True
        registry.mark_failed(job_id, error=hooks.classify_error(exc))
        logger.exception("ingest job %s failed", job_id)

    job = registry.get(job_id)
    if job:
        for w in hooks.inspect_outcome(
            rows=rows, started_at=job.started_at,
            finished_at=job.finished_at, raised=raised,
        ):
            registry.add_warning(job_id, w)
        try:
            sup = _ingestor_factory()._supabase
            audit = hooks.fetch_audit_warning(sup, entity, doc_type, year, month)
            if audit:
                registry.add_warning(job_id, audit)
        except Exception:
            pass
    return rows


def _run_range_job(
    parent_id: str, resolved: dispatch.Resolved,
    slices: list[tuple[int, Optional[int]]], entity: str, doc_type: str,
) -> None:
    registry = get_registry()
    registry.mark_running(parent_id)
    total_rows = 0
    failed = 0
    try:
        for y, m in slices:
            child = registry.create("ingest", {
                "entity": entity, "doc_type": doc_type, "year": y, "month": m,
                "table": resolved.table, "method": resolved.method_name,
            }, parent=parent_id)
            registry.update(child.id, table=resolved.table)
            rows = _run_ingest_job(child.id, resolved, y, m, entity, doc_type)
            total_rows += rows
            cj = registry.get(child.id)
            if cj and cj.status == "failed":
                failed += 1
        registry.mark_done(parent_id, rows=total_rows)
        if failed:
            registry.add_warning(parent_id, {
                "type": "partial_failure",
                "message": f"{failed}/{len(slices)} child slices failed — see children for details",
                "failed_count": failed, "total_count": len(slices),
            })
    except BaseException as exc:                # noqa: BLE001
        registry.mark_failed(parent_id, error=hooks.classify_error(exc))
        logger.exception("range job %s failed", parent_id)


def _run_daily_job(job_id: str) -> None:
    registry = get_registry()
    registry.mark_running(job_id)
    try:
        ingestor = _ingestor_factory()
        result = asyncio.run(ingestor.daily_update())
        total = sum(v for v in result.values() if isinstance(v, int))
        registry.update(job_id, params={**(registry.get(job_id).params if registry.get(job_id) else {}), "per_table": result})
        registry.mark_done(job_id, rows=total)
    except BaseException as exc:                # noqa: BLE001
        registry.mark_failed(job_id, error=hooks.classify_error(exc))
        logger.exception("daily job %s failed", job_id)
