"""In-process job registry for the Flask control plane.

Jobs are stored in memory only — restarting the Flask process loses history.
The pipeline already writes a durable audit row to `cvm_ingest_log` for every
ingest run, so this registry is purely the live view; resilience is delegated
to that table.

Capacity-bounded: the registry keeps the most recent _MAX_JOBS jobs and
silently evicts older ones (oldest by `created_at`).
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_MAX_JOBS = 500


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
    id: str
    kind: str                          # "ingest" | "ingest_range" | "daily" | "verify"
    params: Dict[str, Any]
    status: str = "queued"             # queued | running | done | failed
    created_at: str = field(default_factory=_now)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    rows_inserted: int = 0
    table: Optional[str] = None
    error: Optional[Dict[str, Any]] = None
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    children: List[str] = field(default_factory=list)
    parent: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, kind: str, params: Dict[str, Any], *, parent: Optional[str] = None) -> Job:
        job = Job(id=str(uuid.uuid4()), kind=kind, params=params, parent=parent)
        with self._lock:
            self._jobs[job.id] = job
            if parent and parent in self._jobs:
                self._jobs[parent].children.append(job.id)
            self._evict_locked()
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, limit: int = 100) -> List[Job]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    def update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            for k, v in fields.items():
                setattr(job, k, v)

    def add_warning(self, job_id: str, warning: Dict[str, Any]) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.warnings.append(warning)

    def mark_running(self, job_id: str) -> None:
        self.update(job_id, status="running", started_at=_now())

    def mark_done(self, job_id: str, rows: int) -> None:
        self.update(job_id, status="done", rows_inserted=rows, finished_at=_now())

    def mark_failed(self, job_id: str, error: Dict[str, Any]) -> None:
        self.update(job_id, status="failed", error=error, finished_at=_now())

    def _evict_locked(self) -> None:
        if len(self._jobs) <= _MAX_JOBS:
            return
        ordered = sorted(self._jobs.values(), key=lambda j: j.created_at)
        for old in ordered[: len(self._jobs) - _MAX_JOBS]:
            if old.status in ("queued", "running"):
                continue
            self._jobs.pop(old.id, None)


_registry: Optional[JobRegistry] = None
_registry_lock = threading.Lock()


def get_registry() -> JobRegistry:
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = JobRegistry()
        return _registry


def reset_registry_for_tests() -> None:
    """Discard the singleton — only call from pytest."""
    global _registry
    with _registry_lock:
        _registry = None
