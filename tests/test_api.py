"""Flask control plane — black-box tests against the Blueprint via test_client.

The CVMIngestor is fully mocked: no live Supabase, no live CVM.
We patch `src.api.routes._ingestor_factory` to inject a stub whose methods
return preset values or raise preset exceptions.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from src.api import create_app, dispatch
from src.api.hooks import classify_error
from src.api.jobs import reset_registry_for_tests


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class StubCursor:
    """Minimal psycopg2 cursor stub."""

    def __init__(self, rows=None, description=None):
        self._rows = rows or []
        self.description = description or []

    def execute(self, sql, params=None):
        pass

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


class StubSupabase:
    """Minimal psycopg2-compatible connection stub."""

    def __init__(self) -> None:
        self._cursor_rows: list = []
        self._cursor_description: list = []

    def queue(self, data: Any = None, count: int = 0) -> None:
        # kept for backward compat in tests that set up healthz expectations
        self._cursor_rows = [[count]]

    def cursor(self):
        return StubCursor(rows=self._cursor_rows, description=self._cursor_description)


class StubIngestor:
    """Mimics CVMIngestor's relevant surface. ingest_* methods are async
    callables we can configure per-test via `set_method`."""

    def __init__(self) -> None:
        self._supabase = StubSupabase()
        self._async_results: Dict[str, Any] = {}

    def set_method(self, name: str, *, returns: int = 0, raises: Exception | None = None):
        async def _impl(*args, **kwargs):
            if raises is not None:
                raise raises
            return returns
        self._async_results[name] = _impl
        setattr(self, name, _impl)

    async def daily_update(self) -> Dict[str, int]:
        return {"cvm_fi_diario": 42, "cvm_fidc_tranche": 3}


@pytest.fixture
def stub():
    reset_registry_for_tests()
    return StubIngestor()


@pytest.fixture
def client(stub):
    app = create_app()
    app.config["TESTING"] = True
    with patch("src.api.routes._ingestor_factory", return_value=stub):
        with app.test_client() as c:
            yield c


def _wait_for_status(client, job_id: str, target: set[str], timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/jobs/{job_id}")
        body = resp.get_json()
        if body.get("status") in target:
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not reach {target} in {timeout}s; last={body}")


# ---------------------------------------------------------------------------
# Dispatch coverage
# ---------------------------------------------------------------------------

def test_dispatch_covers_all_15_methods():
    """Every CVMIngestor.ingest_* method must be reachable via dispatch."""
    expected = {
        "ingest_fi_diario", "ingest_fi_cda", "ingest_fi_perfil",
        "ingest_fidc_mensal", "ingest_fidc_tranche", "ingest_fidc_tranche_flows", "ingest_fidc_aging",
        "ingest_fiagro_mensal",
        "ingest_fip_periodic",
        "ingest_fii_mensal", "ingest_fii_periodic",
        "ingest_securit_mensal", "ingest_securit_serie", "ingest_securit_fluxo", "ingest_securit_dfin",
    }
    seen = {entry["method"] for rows in dispatch.all_pairs().values() for entry in rows}
    assert expected <= seen, f"missing: {expected - seen}"


def test_dispatch_resolve_needs_month_only_for_monthly():
    assert dispatch.resolve("fidc", "tranche").needs_month is True
    assert dispatch.resolve("fii", "mensal_geral").needs_month is False
    assert dispatch.resolve("securit", "dfin_cra").needs_month is False


def test_dispatch_unknown_pair_raises():
    with pytest.raises(KeyError):
        dispatch.resolve("fi", "diariou")
    with pytest.raises(KeyError):
        dispatch.resolve("xyz", "anything")


# ---------------------------------------------------------------------------
# Healthz / dispatch endpoint / status
# ---------------------------------------------------------------------------

def test_healthz_returns_ok_when_supabase_responsive(client, stub):
    stub._supabase.queue(data=[], count=0)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_dispatch_endpoint_lists_entities(client):
    resp = client.get("/api/dispatch")
    body = resp.get_json()
    assert resp.status_code == 200
    assert set(body["entities"].keys()) >= {"fi", "fidc", "fiagro", "fip", "fii", "securit"}


def test_status_endpoint_returns_row_counts(client, stub):
    for _ in range(15):
        stub._supabase.queue(count=100)
    stub._supabase.queue(data=[])  # recent_runs
    resp = client.get("/api/status")
    body = resp.get_json()
    assert resp.status_code == 200
    assert "row_counts" in body and len(body["row_counts"]) == 15


# ---------------------------------------------------------------------------
# Ingest happy path
# ---------------------------------------------------------------------------

def test_ingest_happy_path_marks_done_with_rows(client, stub):
    stub.set_method("ingest_fidc_tranche", returns=123)
    resp = client.post("/api/ingest", json={
        "entity": "fidc", "doc_type": "tranche", "year": 2024, "month": 5,
    })
    assert resp.status_code == 202
    job_id = resp.get_json()["job_id"]
    body = _wait_for_status(client, job_id, {"done", "failed"})
    assert body["status"] == "done"
    assert body["rows_inserted"] == 123
    assert body["table"] == "cvm_fidc_tranche"


def test_ingest_yearly_doc_type_does_not_require_month(client, stub):
    stub.set_method("ingest_fii_mensal", returns=7)
    resp = client.post("/api/ingest", json={
        "entity": "fii", "doc_type": "mensal_geral", "year": 2024,
    })
    assert resp.status_code == 202
    job_id = resp.get_json()["job_id"]
    body = _wait_for_status(client, job_id, {"done", "failed"})
    assert body["status"] == "done"
    assert body["rows_inserted"] == 7


def test_ingest_monthly_without_month_is_400(client):
    resp = client.post("/api/ingest", json={
        "entity": "fidc", "doc_type": "tranche", "year": 2024,
    })
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "missing_month"


def test_ingest_unknown_pair_is_404(client):
    resp = client.post("/api/ingest", json={
        "entity": "nope", "doc_type": "nada", "year": 2024,
    })
    assert resp.status_code == 404


def test_ingest_missing_fields_is_400(client):
    resp = client.post("/api/ingest", json={"entity": "fidc"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Failures + hooks
# ---------------------------------------------------------------------------

def test_ingest_failure_classifies_error_type(client, stub):
    stub.set_method(
        "ingest_fidc_tranche",
        raises=TimeoutError("connection timed out after 30s"),
    )
    resp = client.post("/api/ingest", json={
        "entity": "fidc", "doc_type": "tranche", "year": 1900, "month": 1,
    })
    job_id = resp.get_json()["job_id"]
    body = _wait_for_status(client, job_id, {"done", "failed"})
    assert body["status"] == "failed"
    assert body["error"]["type"] == "network"


def test_zero_rows_triggers_no_data_warning(client, stub):
    stub.set_method("ingest_fidc_tranche", returns=0)
    resp = client.post("/api/ingest", json={
        "entity": "fidc", "doc_type": "tranche", "year": 2030, "month": 12,
    })
    job_id = resp.get_json()["job_id"]
    body = _wait_for_status(client, job_id, {"done", "failed"})
    assert body["status"] == "done"
    warn_types = {w["type"] for w in body["warnings"]}
    assert "no_data_published" in warn_types


# ---------------------------------------------------------------------------
# Range
# ---------------------------------------------------------------------------

def test_range_job_spawns_children_and_aggregates(client, stub):
    stub.set_method("ingest_fidc_tranche", returns=10)
    resp = client.post("/api/ingest/range", json={
        "entity": "fidc", "doc_type": "tranche",
        "year_start": 2023, "year_end": 2023, "months": [5, 6],
    })
    assert resp.status_code == 202
    parent_id = resp.get_json()["job_id"]
    body = _wait_for_status(client, parent_id, {"done", "failed"}, timeout=10)
    assert body["status"] == "done"
    assert len(body["children"]) == 2
    assert body["rows_inserted"] == 20


def test_range_rejects_inverted_years(client):
    resp = client.post("/api/ingest/range", json={
        "entity": "fidc", "doc_type": "tranche",
        "year_start": 2024, "year_end": 2020,
    })
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Jobs listing
# ---------------------------------------------------------------------------

def test_jobs_list_returns_recent_first(client, stub):
    stub.set_method("ingest_fidc_tranche", returns=1)
    for _ in range(3):
        client.post("/api/ingest", json={
            "entity": "fidc", "doc_type": "tranche", "year": 2024, "month": 5,
        })
    resp = client.get("/api/jobs?limit=2")
    body = resp.get_json()
    assert len(body["jobs"]) == 2


def test_get_unknown_job_is_404(client):
    resp = client.get("/api/jobs/does-not-exist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Error classification — unit
# ---------------------------------------------------------------------------

def test_classify_timeout_is_network():
    assert classify_error(TimeoutError("x"))["type"] == "network"


def test_classify_unicode_decode_is_csv_parse():
    err = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")
    assert classify_error(err)["type"] == "csv_parse"


def test_classify_keyerror_is_csv_parse():
    assert classify_error(KeyError("CNPJ_FUNDO"))["type"] == "csv_parse"


def test_classify_unknown_fallback():
    class Weird(Exception):
        pass
    assert classify_error(Weird("???"))["type"] == "unknown"
