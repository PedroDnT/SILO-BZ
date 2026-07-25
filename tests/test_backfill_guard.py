"""Tests for the silent-zero backfill guard and ingest-log finish resilience.

Both fixes come from the 2026-06-10 backfill post-mortem: CVM refused every
download from a blocked runner for 4h, run_backfill printed "0 total rows" and
exited 0 (CI green, cvm_fi_diario 2024/2025 left empty), and the audit-log
finish UPDATEs died with the idled-out DB connection, leaving slices stuck
'running' forever.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.pipeline.run_backfill import ensure_rows_landed
from src.pipeline.cvm_pipeline import CVMIngestor


class TestEnsureRowsLanded:
    def test_zero_rows_exits_nonzero(self):
        with pytest.raises(SystemExit) as excinfo:
            ensure_rows_landed(0)
        assert excinfo.value.code == 1

    def test_positive_rows_pass(self):
        assert ensure_rows_landed(1) is None
        assert ensure_rows_landed(5_000_000) is None


class _FakeCursor:
    """Context-manager cursor whose execute() fails a configurable number of times."""

    def __init__(self, state):
        self._state = state

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._state["executes"] += 1
        if self._state["fail_remaining"] > 0:
            self._state["fail_remaining"] -= 1
            raise RuntimeError("connection already closed")
        self._state["done"] = True


class _FakeClient:
    def __init__(self, fail_times, reconnect_raises=False):
        self.state = {"executes": 0, "fail_remaining": fail_times, "done": False}
        self.reconnects = 0
        self._reconnect_raises = reconnect_raises

    def cursor(self):
        return _FakeCursor(self.state)

    def reconnect(self):
        self.reconnects += 1
        if self._reconnect_raises:
            raise RuntimeError("still unreachable")


def _ingestor_with(client):
    with patch("src.pipeline.cvm_pipeline.get_pg_client", return_value=MagicMock()):
        ingestor = CVMIngestor()
    ingestor._supabase = client
    return ingestor


class TestLogFinishRetry:
    def test_reconnects_and_retries_once(self):
        client = _FakeClient(fail_times=1)
        _ingestor_with(client)._log_finish("run-1", 42)
        assert client.reconnects == 1
        assert client.state["executes"] == 2
        assert client.state["done"] is True

    def test_gives_up_after_second_failure(self):
        # Both attempts fail: no exception escapes (finish stays best-effort).
        client = _FakeClient(fail_times=2)
        _ingestor_with(client)._log_finish("run-1", 0, error="boom")
        assert client.reconnects == 1
        assert client.state["executes"] == 2
        assert client.state["done"] is False

    def test_reconnect_failure_is_swallowed(self):
        client = _FakeClient(fail_times=1, reconnect_raises=True)
        _ingestor_with(client)._log_finish("run-1", 0)
        assert client.reconnects == 1
        assert client.state["executes"] == 1  # no second attempt without a connection

    def test_no_retry_when_first_attempt_succeeds(self):
        client = _FakeClient(fail_times=0)
        _ingestor_with(client)._log_finish("run-1", 7)
        assert client.reconnects == 0
        assert client.state["executes"] == 1
