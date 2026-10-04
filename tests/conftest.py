"""
Pytest configuration and shared fixtures for Brazilian Financial Data Infrastructure tests
"""

import pytest
import asyncio
import shutil
import subprocess

# Test data fixtures
@pytest.fixture
def sample_fidc_cadastral_records():
    """Sample FIDC cadastral records for testing"""
    return [
        {
            "CNPJ_FUNDO": "12.345.678/0001-90",
            "DENOM_SOCIAL": "FUNDO EXEMPLO FIDC",
            "DT_REG": "2020-01-15",
            "DT_CANCEL": None,
            "SIT": "ATIVO",
            "TP_FUNDO": "FIDC"
        },
        {
            "CNPJ_FUNDO": "98.765.432/0001-10",
            "DENOM_SOCIAL": "FUNDO TESTE FIDC",
            "DT_REG": "2019-06-20",
            "DT_CANCEL": "2023-12-31",
            "SIT": "CANCELADO",
            "TP_FUNDO": "FIDC"
        }
    ]

@pytest.fixture
def sample_validation_config():
    """Sample validation configuration"""
    return {
        "required_fields": ["CNPJ_FUNDO", "DENOM_SOCIAL", "DT_REG"],
        "field_types": {
            "CNPJ_FUNDO": "cnpj",
            "DT_REG": "date",
            "VL_PATRIMONIO": "numeric"
        },
        "business_rules": []
    }

# Pytest configuration
def pytest_configure(config):
    """Configure pytest with custom markers"""
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "slow: Slow running tests")
    config.addinivalue_line("markers", "cvm: CVM API tests")
    config.addinivalue_line("markers", "validation: Data validation tests")
    config.addinivalue_line("markers", "parsing: CSV parsing tests")

# Async test support
@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

# Exactly the columns of public.cvm_ingest_log (verified against Silo). Every
# audit writer's rows must be a subset: the 2026-07-25 ANBIMA incident sent
# `notes`/`error_message`, which do not exist, and ingest was silently disabled.
INGEST_LOG_COLUMNS = frozenset({
    "id", "run_id", "entity", "doc_type", "period_year", "period_month",
    "rows_upserted", "status", "error_msg", "started_at", "finished_at",
    # Lineage, migration 44: which code produced the slice.
    "git_sha", "parser_version",
    # Stored rows a per-fund replace removed, migration 68.
    "rows_deleted",
})


@pytest.fixture
def ingest_log_columns():
    return INGEST_LOG_COLUMNS


@pytest.fixture(scope="session")
def gnu_date():
    """Skip unless bash runs a GNU `date`.

    backfill.yml's "Validate FNET inputs" step checks each date with
    `date -u -d`. macOS ships BSD `date`, which rejects `-d`, so a guard that
    only looked for a `date` on PATH ran the step there and failed every
    valid date. Probe the step's own call instead.
    """
    if shutil.which("bash") is None:
        pytest.skip("needs bash + GNU date")
    probe = subprocess.run(["bash", "-c", "date -u -d 2026-01-01 +%F"], capture_output=True, text=True)
    if probe.stdout.strip() != "2026-01-01":
        pytest.skip("needs bash + GNU date")


@pytest.fixture
def audit_log(monkeypatch):
    """The audit rows a pipeline writes through src.pipeline.ingest_log.

    Stands in for ``ingest_log.start`` / ``finish`` (the one writer, tested in
    test_ingest_log_writer.py), so a test reads each run's terminal row
    (``audit_log.finished``: doc_type, status, rows, error, period_*) without
    a database or a mocked wrapper on the pipeline. ``started`` holds the
    ``running`` rows.
    """
    from types import SimpleNamespace

    from src.pipeline import ingest_log

    log = SimpleNamespace(started=[], finished=[])

    def start(client, run_id, entity, doc_type, **kw):
        log.started.append({"run_id": run_id, "entity": entity, "doc_type": doc_type, **kw})

    def finish(client, run_id, entity, doc_type, *, status, rows, error=None, **kw):
        log.finished.append({"run_id": run_id, "entity": entity, "doc_type": doc_type,
                             "status": status, "rows": rows, "error": error, **kw})

    monkeypatch.setattr(ingest_log, "start", start)
    monkeypatch.setattr(ingest_log, "finish", finish)
    return log
