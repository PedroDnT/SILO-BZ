"""The one writer of ``cvm_ingest_log`` audit rows for non-CVM ingestors.

Integrity rule 3: every ingest writes exactly one audit row. By 2026-09-03
there were four hand-rolled copies of the start/finish helpers (CVM, B3,
ANBIMA, BACEN) with four different contracts on what happens when the audit
write itself fails, and drifting row shapes. This module is the single
contract:

* ``start`` and ``finish`` are **best-effort**: a failed audit write is
  logged loudly and never fails the ingest. The audit table must not be able
  to stop ingesting (CVM's stance), and a landed source must never be
  reported as failed because the bookkeeping hiccupped. Because ``finish``
  is an upsert keyed on ``run_id``, a finish whose start never landed still
  inserts a row, so a transient blip at start does not lose the record.
* ``audited`` brackets one unit of work: ``running`` → ``ok`` | ``error``.
  The finish row is written from a ``finally``, so cancellation and job
  timeouts (``BaseException``) leave an ``error`` row, not a permanent
  ``running`` one. The exception is re-raised unchanged; the audit never
  masks it.
* Writes go through ``asyncio.to_thread`` so the synchronous psycopg2 call
  (and ``upsert_rows``' blocking retry sleeps) never freeze the event loop
  that the sibling sources' HTTP fetches share.
* ``error_msg`` always carries the exception type (``describe``): ``str()``
  of an exception raised without arguments is empty, and an empty error
  column is a failure that is recorded but not diagnosable.
* A source that landed some rows before failing raises
  ``PartialIngestError(rows=n)`` and the error row records ``n``, so the
  audit reconciles against the landing table.

Period convention for range-fetched sources (a trailing window, not a
filing month): ``period_year``/``period_month`` = the window's **start
month**. A daily 30-day refresh lands inside DB Health check 1's lookback
window; a 2019 backfill lands in the historical backlog — the same split
CVM slices get, so a daily ``ok`` can never "heal" a failed deep backfill.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from src.store.pg_client import upsert_rows

# Every writer passes its own module's ``upsert_rows`` name (``upsert=``):
# tests mock that name per pipeline module, and audit rows must land in the
# same capture as the data rows or the mocks miss them and the real client's
# 75 s retry ladder runs against a MagicMock.
Upsert = Callable[..., int]

logger = logging.getLogger(__name__)

TABLE = "cvm_ingest_log"


class PartialIngestError(RuntimeError):
    """Some rows landed before the source failed; ``rows`` says how many."""

    def __init__(self, message: str, *, rows: int = 0) -> None:
        super().__init__(message)
        self.rows = int(rows)


def describe(exc: BaseException) -> str:
    """Render an exception for a log line and the ``error_msg`` column.

    ``str(exc)`` is the empty string for any exception raised without args,
    so a real failure would write an empty error column. Always carry the
    type.
    """
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def start(
    client: Any,
    run_id: str,
    entity: str,
    doc_type: str,
    *,
    period_year: Optional[int] = None,
    period_month: Optional[int] = None,
    upsert: Optional[Upsert] = None,
) -> None:
    """Write the ``running`` row. Raises on failure; callers decide the stance."""
    (upsert or upsert_rows)(
        client,
        TABLE,
        [{
            "run_id":        run_id,
            "entity":        entity,
            "doc_type":      doc_type,
            "period_year":   period_year,
            "period_month":  period_month,
            "rows_upserted": 0,          # NOT NULL — finish overwrites it
            "status":        "running",
            "started_at":    datetime.now(timezone.utc),
        }],
        conflict_columns="run_id",
    )


def finish(
    client: Any,
    run_id: str,
    entity: str,
    doc_type: str,
    *,
    status: str,
    rows: int,
    error: Optional[str] = None,
    period_year: Optional[int] = None,
    period_month: Optional[int] = None,
    upsert: Optional[Upsert] = None,
) -> None:
    """Write the terminal row (``ok`` | ``error`` | ``skipped``). Raises on failure.

    ``started_at`` is deliberately NOT sent: ``ON CONFLICT DO UPDATE`` sets
    every column present, and resending it would make every run look
    instantaneous. When the start row never landed this INSERTs instead and
    the column takes its ``NOW()`` default — a slightly-late start beats no
    record at all.
    """
    row = {
        "run_id":        run_id,
        "entity":        entity,
        "doc_type":      doc_type,
        "status":        status,
        "rows_upserted": int(rows),
        "finished_at":   datetime.now(timezone.utc),
        "error_msg":     error,
    }
    # The period key is sent only when the caller supplies it: ON CONFLICT DO
    # UPDATE sets every column present, so a finish that always sent NULLs
    # would erase the key the start row wrote. Callers that pass it (BACEN)
    # get a self-healing INSERT with the key when the start never landed.
    if period_year is not None or period_month is not None:
        row["period_year"] = period_year
        row["period_month"] = period_month
    (upsert or upsert_rows)(client, TABLE, [row], conflict_columns="run_id")


async def audited(
    client: Any,
    entity: str,
    doc_type: str,
    fn: Callable[[], Awaitable[int]],
    *,
    period_year: Optional[int] = None,
    period_month: Optional[int] = None,
    upsert: Optional[Upsert] = None,
) -> int:
    """Run ``fn()`` under an audit row: running → ok | error. Returns its rows.

    ``fn`` is a zero-arg factory, called only after the start row is
    attempted, so no coroutine is ever created and left un-awaited.
    The ingest exception — ``Exception`` or ``BaseException`` alike — is
    re-raised untouched; both audit writes are best-effort and off the loop.
    """
    run_id = str(uuid.uuid4())
    key = f"{entity}/{doc_type}"
    try:
        await asyncio.to_thread(
            start, client, run_id, entity, doc_type,
            period_year=period_year, period_month=period_month, upsert=upsert,
        )
    except Exception as exc:  # noqa: BLE001 — audit must not stop ingest
        logger.warning("%s: could not write the running row (%s); continuing", key, describe(exc))

    status, rows, error = "error", 0, None
    try:
        rows = int(await fn() or 0)
        status = "ok"
        return rows
    except BaseException as exc:
        rows = int(getattr(exc, "rows", 0) or 0)
        error = describe(exc)
        raise
    finally:
        try:
            await asyncio.to_thread(
                finish, client, run_id, entity, doc_type,
                status=status, rows=rows, error=error,
                period_year=period_year, period_month=period_month, upsert=upsert,
            )
        except Exception as log_exc:  # noqa: BLE001 — must not mask the ingest outcome
            logger.warning("%s: could not write the %s row (%s)", key, status, describe(log_exc))
