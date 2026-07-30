"""Per-slice data contract in CVMIngestor._log_finish.

Motivation: a slice that fetched real source rows but upserted none was logged
'ok'. That is exactly how cvm_fiagro_mensal sat empty behind 34 'ok' slices — the
audit log asserted success while the table stayed empty.

Contract:
  fetched > 0 and rows == 0  -> 'error' (every row dropped: stale map / bad layout)
  fetched == 0               -> 'ok'    (genuinely empty published file)
  "Data not found" error     -> 'skipped' (not-yet-published month; unchanged)
  any other error            -> 'error'  (unchanged)
"""

from unittest.mock import MagicMock, patch

from src.pipeline.cvm_pipeline import CVMIngestor


class _Cur:
    def __init__(self, sink): self.sink = sink
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params=None): self.sink.append(params)


class _Client:
    def __init__(self): self.calls = []
    def cursor(self): return _Cur(self.calls)
    def reconnect(self): pass


def _finish(**kw):
    """Call _log_finish and return the status written to cvm_ingest_log."""
    with patch("src.pipeline.cvm_pipeline.get_pg_client", return_value=MagicMock()):
        ing = CVMIngestor()
    client = _Client()
    ing._supabase = client
    ing._log_finish("run-1", **kw)
    assert client.calls, "no UPDATE issued"
    params = client.calls[-1]
    # UPDATE ... SET rows_upserted=%s, status=%s, error_msg=%s, finished_at=%s
    return {"rows": params[0], "status": params[1], "error": params[2]}


class TestSliceContract:
    def test_fetched_rows_but_none_upserted_is_error(self):
        out = _finish(rows=0, fetched=125)
        assert out["status"] == "error"
        assert "125" in out["error"]
        assert "upserted 0" in out["error"]

    def test_error_message_points_at_the_likely_cause(self):
        out = _finish(rows=0, fetched=10)
        assert "field map" in out["error"].lower()

    def test_rows_upserted_is_ok(self):
        assert _finish(rows=500, fetched=500)["status"] == "ok"

    def test_partial_drop_is_still_ok(self):
        # Some rows failing validation is normal and counted, not fatal.
        assert _finish(rows=90, fetched=100)["status"] == "ok"

    def test_genuinely_empty_source_is_ok(self):
        # An empty published file is not a defect; only fetched>0 & rows==0 is.
        assert _finish(rows=0, fetched=0)["status"] == "ok"

    def test_unknown_fetched_count_stays_ok(self):
        # Call sites that cannot report a fetched count keep the old behaviour.
        assert _finish(rows=0)["status"] == "ok"
        assert _finish(rows=0, fetched=None)["status"] == "ok"

    def test_not_yet_published_is_skipped_not_error(self):
        out = _finish(rows=0, error="Data not found at https://...", fetched=0)
        assert out["status"] == "skipped"

    def test_not_yet_published_wins_over_the_contract(self):
        # A 404 must stay 'skipped' even if a fetched count is supplied.
        out = _finish(rows=0, error="Data not found at https://...", fetched=7)
        assert out["status"] == "skipped"

    def test_real_error_is_preserved_verbatim(self):
        out = _finish(rows=0, error="No CSV file found in ZIP", fetched=5)
        assert out["status"] == "error"
        assert out["error"] == "No CSV file found in ZIP"
