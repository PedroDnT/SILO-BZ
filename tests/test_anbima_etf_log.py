"""ANBIMA ingest-log regression tests.

Guards the bug found on 2026-07-25: the ANBIMA table was empty and cvm_ingest_log
had no `anbima_etf` rows at all, even though parsing the live boletim yields
thousands of records.

Cause: `_log_start` sent a `notes` key and `_log_finish` sent `error_message`.
Neither is a real cvm_ingest_log column, and upsert_rows builds
`INSERT INTO ... (<dict keys>)` with no filtering against the table, so the
insert raised "column does not exist". `_log_start` is called *outside* the
upsert try/except, so it propagated out of daily_update() and run_daily's
catch-all downgraded it to a warning — the ingest was skipped every day.

The column list below mirrors the live table, so sending a non-existent column
fails a test instead of silently disabling the ingest in production.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.pipeline.anbima_pipeline import TABLE, AnbimaIngestor

# Exactly the columns of public.cvm_ingest_log (verified against Silo).
INGEST_LOG_COLUMNS = {
    "id", "run_id", "entity", "doc_type", "period_year", "period_month",
    "rows_upserted", "status", "error_msg", "started_at", "finished_at",
    "git_sha", "parser_version",  # lineage, migration 44
}


def _ingestor():
    with patch("src.pipeline.anbima_pipeline.get_pg_client", return_value=MagicMock()):
        return AnbimaIngestor()


RECORDS = [{
    "reference_date": "2026-06-01",
    "anbima_category": "ETF",
    "anbima_type_id": None,
    "anbima_type_name": "ETF",
    "metric": "pl_brl_mm",
    "value": 3747.24,
    "level": "category",
    "source_sheet": "Pág. 4 - PL por Classe",
    "boletim_ref": "b.xlsx",
}]


def _run_daily_update(parsed=None, fetch_error=None):
    """Run daily_update with network and DB mocked; return the cvm_ingest_log writes.

    Each item is {"rows": [...], "conflict": <conflict_columns>}.
    """
    ing = _ingestor()
    sent = []

    def _fake_upsert(conn, table, rows, **kw):
        if table == "cvm_ingest_log":
            sent.append({"rows": rows, "conflict": kw.get("conflict_columns")})
        return len(rows)

    fetch_kw = ({"side_effect": fetch_error} if fetch_error is not None
                else {"return_value": ("http://x/b.xlsx", "b.xlsx")})
    with patch("src.pipeline.anbima_pipeline.fetch_latest_boletim_url", **fetch_kw), \
         patch("src.pipeline.anbima_pipeline.download_xlsx", return_value=b"xx"), \
         patch("src.pipeline.anbima_pipeline.parse_boletim", return_value=parsed or RECORDS), \
         patch("src.pipeline.anbima_pipeline.upsert_rows", side_effect=_fake_upsert):
        try:
            asyncio.run(ing.daily_update())
        except RuntimeError:
            pass
    return sent


class TestLogColumns:
    """The audit rows ANBIMA writes must satisfy the real cvm_ingest_log table."""

    def test_audit_rows_send_only_real_columns(self):
        for write in _run_daily_update():
            unknown = set(write["rows"][0]) - INGEST_LOG_COLUMNS
            assert not unknown, f"non-existent cvm_ingest_log column(s): {unknown}"

    def test_start_row_satisfies_not_null_columns(self):
        # entity, doc_type, rows_upserted, status, started_at are NOT NULL.
        row = _run_daily_update()[0]["rows"][0]
        for col in ("run_id", "entity", "doc_type", "rows_upserted", "status", "started_at"):
            assert row.get(col) is not None, f"{col} is NOT NULL in the table"
        assert row["status"] == "running"

    def test_finish_does_not_clobber_started_at(self):
        # ON CONFLICT DO UPDATE sets every supplied column, so sending started_at
        # here would overwrite the real start time and zero out every duration.
        row = _run_daily_update()[-1]["rows"][0]
        assert row["status"] == "ok"
        assert "started_at" not in row
        assert row["finished_at"] is not None

    def test_a_failure_is_carried_in_error_msg(self):
        row = _run_daily_update(fetch_error=RuntimeError("boom"))[-1]["rows"][0]
        assert row["error_msg"] == "RuntimeError: boom"
        assert row["status"] == "error"

    def test_conflict_key_is_run_id(self):
        assert {w["conflict"] for w in _run_daily_update()} == {"run_id"}

    def test_the_start_and_finish_rows_share_one_run_id(self):
        start, finish = (w["rows"][0] for w in _run_daily_update())
        assert start["run_id"] == finish["run_id"]


class TestDailyUpdate:
    """End-to-end with network + DB mocked: records must reach the table and the
    run must be logged 'ok' (not the old 'success', which coverage checks ignore).
    """

    RECORDS = RECORDS

    @pytest.mark.asyncio
    async def test_records_upserted_and_logged_ok(self):
        ing = _ingestor()
        sent = []

        def _fake_upsert(conn, table, rows, **kw):
            sent.append({"table": table, "rows": rows, "conflict": kw.get("conflict_columns")})
            return len(rows)

        with patch("src.pipeline.anbima_pipeline.fetch_latest_boletim_url",
                   return_value=("http://x/b.xlsx", "b.xlsx")), \
             patch("src.pipeline.anbima_pipeline.download_xlsx", return_value=b"xx"), \
             patch("src.pipeline.anbima_pipeline.parse_boletim", return_value=self.RECORDS), \
             patch("src.pipeline.anbima_pipeline.upsert_rows", side_effect=_fake_upsert):
            result = await ing.daily_update()

        assert result == {"anbima_etf": 1}
        tables = [s["table"] for s in sent]
        assert TABLE == "anbima_class_monthly"
        assert TABLE in tables, "records never reached the data table"
        # last log write must be the 'ok' finish
        log_rows = [s["rows"][0] for s in sent if s["table"] == "cvm_ingest_log"]
        assert log_rows[-1]["status"] == "ok"
        assert log_rows[-1]["rows_upserted"] == 1

    @pytest.mark.asyncio
    async def test_upsert_conflict_key_matches_the_table_primary_key(self):
        """The widened PK. Keying on (date, type_name, metric) as before would let
        the 'Cambial'/'FIP'/'FIAGRO' ANBIMA types overwrite the class aggregates
        of the very same name — the collision this table was reshaped to prevent.
        """
        ing = _ingestor()
        sent = []

        def _fake_upsert(conn, table, rows, **kw):
            sent.append({"table": table, "conflict": kw.get("conflict_columns")})
            return len(rows)

        with patch("src.pipeline.anbima_pipeline.fetch_latest_boletim_url",
                   return_value=("http://x/b.xlsx", "b.xlsx")), \
             patch("src.pipeline.anbima_pipeline.download_xlsx", return_value=b"xx"), \
             patch("src.pipeline.anbima_pipeline.parse_boletim", return_value=self.RECORDS), \
             patch("src.pipeline.anbima_pipeline.upsert_rows", side_effect=_fake_upsert):
            await ing.daily_update()

        data_write = [s for s in sent if s["table"] == TABLE][0]
        assert data_write["conflict"] == (
            "reference_date,anbima_category,anbima_type_name,metric,level")

    def test_records_carry_every_key_column(self):
        # A record missing `level` (or the category) cannot satisfy the NOT NULL
        # primary key, and upsert_rows sends the dict keys verbatim.
        for col in ("reference_date", "anbima_category", "anbima_type_name",
                    "metric", "level"):
            assert self.RECORDS[0].get(col) is not None, col

    @staticmethod
    def _log_rows(sent):
        return [s["rows"][0] for s in sent if s["table"] == "cvm_ingest_log"]

    @pytest.mark.asyncio
    async def test_empty_parse_raises_and_logs_an_error_row(self):
        """Rule 3 and rule 1: nothing parsed is one audit row, never 'ok'
        (coverage counts status='ok' even at 0 rows), and not a silent 0."""
        ing = _ingestor()
        sent = []

        def _fake_upsert(conn, table, rows, **kw):
            sent.append({"table": table, "rows": rows})
            return len(rows)

        with patch("src.pipeline.anbima_pipeline.fetch_latest_boletim_url",
                   return_value=("http://x/b.xlsx", "b.xlsx")), \
             patch("src.pipeline.anbima_pipeline.download_xlsx", return_value=b"xx"), \
             patch("src.pipeline.anbima_pipeline.parse_boletim", return_value=[]), \
             patch("src.pipeline.anbima_pipeline.upsert_rows", side_effect=_fake_upsert):
            with pytest.raises(RuntimeError, match="No records parsed"):
                await ing.daily_update()

        assert [s["table"] for s in sent] == ["cvm_ingest_log", "cvm_ingest_log"]
        last = self._log_rows(sent)[-1]
        assert last["status"] == "error"
        assert last["rows_upserted"] == 0
        assert "No records parsed" in last["error_msg"]

    @pytest.mark.asyncio
    async def test_fetch_failure_logs_an_error_row_and_reraises(self):
        """Rule 3: a boletim that cannot be fetched used to leave no row."""
        ing = _ingestor()
        sent = []

        def _fake_upsert(conn, table, rows, **kw):
            sent.append({"table": table, "rows": rows})
            return len(rows)

        with patch("src.pipeline.anbima_pipeline.fetch_latest_boletim_url",
                   side_effect=RuntimeError("boletim page is down")), \
             patch("src.pipeline.anbima_pipeline.upsert_rows", side_effect=_fake_upsert):
            with pytest.raises(RuntimeError, match="boletim page is down"):
                await ing.daily_update()

        last = self._log_rows(sent)[-1]
        assert last["status"] == "error"
        assert "RuntimeError: boletim page is down" == last["error_msg"]

    @pytest.mark.asyncio
    async def test_a_failed_start_write_does_not_stop_the_ingest(self):
        """The start row is best-effort; finish upserts, so the row still lands."""
        ing = _ingestor()
        sent = []

        def _fake_upsert(conn, table, rows, **kw):
            if table == "cvm_ingest_log" and rows[0]["status"] == "running":
                raise RuntimeError("audit table unavailable")
            sent.append({"table": table, "rows": rows})
            return len(rows)

        with patch("src.pipeline.anbima_pipeline.fetch_latest_boletim_url",
                   return_value=("http://x/b.xlsx", "b.xlsx")), \
             patch("src.pipeline.anbima_pipeline.download_xlsx", return_value=b"xx"), \
             patch("src.pipeline.anbima_pipeline.parse_boletim", return_value=self.RECORDS), \
             patch("src.pipeline.anbima_pipeline.upsert_rows", side_effect=_fake_upsert):
            assert await ing.daily_update() == {"anbima_etf": 1}

        assert self._log_rows(sent)[-1]["status"] == "ok"
