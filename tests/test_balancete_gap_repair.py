"""Targeted FI gap repair: month selection, gap detection, and failing loudly.

Background — the 2026-08-27 fi/balancete backfill upserted ~81.7M rows, exited
0, and left 32 published months missing. Three separate defects made that
possible and each is pinned here:

  1. gap detection that trusts the audit log (2026-06's newest audit row says
     'error' while the table holds 2,178,163 rows from an earlier 'ok');
  2. a repair that re-fetches the whole range to reach a handful of months;
  3. a run that reports success while slices failed.

All offline: no DB, no network.
"""

from __future__ import annotations

import asyncio
from datetime import date
from unittest.mock import AsyncMock

import pytest

from src.pipeline.cvm_pipeline import CVMIngestor, SliceFailure
from src.pipeline.gaps import MonthGap, missing_fi_months
from src.pipeline.run_backfill import ensure_no_failed_slices, parse_months


# ---------------------------------------------------------------------------
# Fake pg client: answers the two queries gaps.py issues
# ---------------------------------------------------------------------------

class _FakeCursor:
    def __init__(self, present_months, skipped_months):
        self._present = present_months
        self._skipped = skipped_months
        self._result = None

    def execute(self, sql, params=None):
        if "cvm_ingest_log" in sql:
            self._result = [tuple(m) for m in sorted(self._skipped)]
        else:
            # EXISTS probe; params is (first_of_month, first_of_next_month)
            first = params[0]
            self._result = [((first.year, first.month) in self._present,)]

    def fetchall(self):
        return self._result

    def fetchone(self):
        return self._result[0]


class FakeClient:
    """Stands in for _PgClient. present/skipped are sets of (year, month)."""

    def __init__(self, present, skipped=()):
        self.present = set(present)
        self.skipped = set(skipped)
        self.queries = 0

    def cursor(self):
        client = self

        class _Ctx:
            def __enter__(self_inner):
                client.queries += 1
                return _FakeCursor(client.present, client.skipped)

            def __exit__(self_inner, *exc):
                return False

        return _Ctx()


# ---------------------------------------------------------------------------
# Gap detection reads the TABLE, not the audit log
# ---------------------------------------------------------------------------

class TestGapDetection:
    def test_finds_months_with_no_rows(self):
        present = {(2019, m) for m in range(1, 13)} - {(2019, 4), (2019, 7)}
        gaps = missing_fi_months(
            FakeClient(present), "balancete",
            start_year=2019, end_year=2019, today=date(2026, 8, 27),
        )
        assert gaps == [MonthGap(2019, 4), MonthGap(2019, 7)]

    def test_a_month_with_rows_is_not_a_gap_even_if_its_latest_audit_says_error(self):
        # The 2026-06 case. gaps.py never reads status for presence, so a fresh
        # failed retry over a complete month cannot resurrect it as a gap.
        gaps = missing_fi_months(
            FakeClient(present={(2026, 6)}), "balancete",
            start_year=2026, end_year=2026, today=date(2026, 8, 27),
        )
        assert MonthGap(2026, 6) not in gaps

    def test_unpublished_months_are_not_gaps(self):
        # 2026-08 has only 'skipped' audit rows (CVM 404). Absent from the
        # table, but not a gap — nothing exists upstream to fetch.
        client = FakeClient(present=set(), skipped={(2026, 6)})
        gaps = missing_fi_months(
            client, "balancete",
            start_year=2026, end_year=2026, today=date(2026, 8, 27),
        )
        assert MonthGap(2026, 6) not in gaps
        assert MonthGap(2026, 5) in gaps      # absent and published -> a gap

    def test_publication_lag_bounds_the_scan(self):
        # Today is 2026-08-27 and CVM lags ~2 months, so 2026-07 and 2026-08
        # are never probed: reporting them would be a permanent phantom gap.
        gaps = missing_fi_months(
            FakeClient(present=set()), "balancete",
            start_year=2026, end_year=2026, today=date(2026, 8, 27),
        )
        months = {(g.year, g.month) for g in gaps}
        assert (2026, 6) in months
        assert (2026, 7) not in months
        assert (2026, 8) not in months

    def test_rejects_an_unknown_doc_type(self):
        with pytest.raises(ValueError, match="unsupported doc_type"):
            missing_fi_months(FakeClient(set()), "not_a_doc_type")

    @pytest.mark.parametrize(
        "doc_type,table,date_col",
        [
            ("balancete", "cvm_fi_balancete", "dt_comptc"),
            ("perfil_mensal", "cvm_fi_perfil", "period"),
            ("cda", "cvm_fi_cda", "period"),
            ("inf_diario", "cvm_fi_diario", "dt_comptc"),
        ],
    )
    def test_probes_the_right_table_and_date_column(self, doc_type, table, date_col):
        # A doc_type pointed at the wrong table would report every month as a
        # gap and trigger a full re-download.
        client = FakeClient(present=set())
        client.seen = []
        base_cursor = client.cursor

        def spying_cursor():
            ctx = base_cursor()
            outer = ctx.__enter__

            class _Spy:
                def __enter__(self_inner):
                    cur = outer()
                    real_execute = cur.execute

                    def execute(sql, params=None):
                        client.seen.append(sql)
                        return real_execute(sql, params)

                    cur.execute = execute
                    return cur

                def __exit__(self_inner, *exc):
                    return ctx.__exit__(*exc)

            return _Spy()

        client.cursor = spying_cursor
        missing_fi_months(client, doc_type, 2025, 2025, today=date(2026, 8, 27))

        probes = [q for q in client.seen if "cvm_ingest_log" not in q]
        assert probes, "no EXISTS probe was issued"
        assert all(table in q and date_col in q for q in probes)


# ---------------------------------------------------------------------------
# --months parsing
# ---------------------------------------------------------------------------

class TestParseMonths:
    def test_parses_sorts_and_dedupes(self):
        assert parse_months("2023-01,2019-04,2019-04") == [(2019, 4), (2023, 1)]

    def test_single_digit_month_is_accepted(self):
        assert parse_months("2019-4") == [(2019, 4)]

    def test_none_means_full_range(self):
        assert parse_months(None) is None

    @pytest.mark.parametrize("bad", ["2019", "2019/04", "abc", "2019-13", "19-04"])
    def test_malformed_input_is_fatal(self, bad):
        # Never silently drop a month the operator named — they would believe
        # the gap was closed.
        with pytest.raises(SystemExit):
            parse_months(bad)


# ---------------------------------------------------------------------------
# Month selection: schedule exactly what was asked for
# ---------------------------------------------------------------------------

def _ingestor_with_stubs():
    ing = CVMIngestor.__new__(CVMIngestor)
    ing.ingest_fi_balancete = AsyncMock(return_value=1000)
    ing.ingest_fi_diario = AsyncMock(return_value=1)
    ing.ingest_fi_cda = AsyncMock(return_value=1)
    ing.ingest_fi_perfil = AsyncMock(return_value=1)
    ing.ingest_fi_hist_diario = AsyncMock(return_value=1)
    ing.ingest_fi_hist_cda = AsyncMock(return_value=1)
    return ing


async def _run_serially(tasks, _concurrency, totals, _label):
    for task in tasks:
        totals[task.table] += await task.operation


class TestMonthSelection:
    @pytest.mark.asyncio
    async def test_months_schedules_exactly_those_slices(self):
        ing = _ingestor_with_stubs()
        ing._run_task_batches = _run_serially

        totals = await ing.backfill(
            start_year=2019, end_year=2026,
            entity_filter="fi", doc_type_filter="balancete",
            months=[(2019, 4), (2023, 1), (2025, 10)],
        )

        assert ing.ingest_fi_balancete.await_count == 3
        called = {c.args for c in ing.ingest_fi_balancete.await_args_list}
        assert called == {(2019, 4), (2023, 1), (2025, 10)}
        assert totals["cvm_fi_balancete"] == 3000

    @pytest.mark.asyncio
    async def test_months_does_not_touch_the_other_fi_documents(self):
        ing = _ingestor_with_stubs()
        ing._run_task_batches = _run_serially

        await ing.backfill(
            start_year=2019, end_year=2026,
            entity_filter="fi", doc_type_filter="balancete",
            months=[(2023, 1)],
        )

        assert ing.ingest_fi_diario.await_count == 0
        assert ing.ingest_fi_cda.await_count == 0
        assert ing.ingest_fi_perfil.await_count == 0

    @pytest.mark.asyncio
    async def test_months_skips_the_yearly_hist_archives(self):
        # Those are whole-year downloads; a month repair must not drag them in.
        ing = _ingestor_with_stubs()
        ing._run_task_batches = _run_serially

        await ing.backfill(
            start_year=2019, end_year=2020,
            entity_filter="fi", doc_type_filter="inf_diario",
            months=[(2021, 3)],
        )

        assert ing.ingest_fi_hist_diario.await_count == 0
        assert ing.ingest_fi_hist_cda.await_count == 0

    @pytest.mark.asyncio
    async def test_months_requires_a_doc_type(self):
        # "these months, all four FI documents" quietly quadruples the work.
        ing = _ingestor_with_stubs()
        with pytest.raises(ValueError, match="months requires doc_type_filter"):
            await ing.backfill(entity_filter="fi", months=[(2023, 1)])

    @pytest.mark.asyncio
    async def test_full_range_is_unchanged_when_months_is_none(self):
        ing = _ingestor_with_stubs()
        ing._run_task_batches = _run_serially

        await ing.backfill(
            start_year=2021, end_year=2021,
            entity_filter="fi", doc_type_filter="balancete",
        )
        assert ing.ingest_fi_balancete.await_count == 12


# ---------------------------------------------------------------------------
# The run must fail when a requested slice failed
# ---------------------------------------------------------------------------

class TestFailLoudly:
    def test_error_status_enters_the_ledger(self):
        ing = CVMIngestor.__new__(CVMIngestor)
        ing._supabase = None
        ing._log_start("run-1", "fi", "balancete", 2023, 1)
        # _log_finish's audit write is best-effort and _supabase is None here;
        # the ledger decision happens before it and must still be recorded.
        ing._log_finish("run-1", 0, "TimeoutError")

        assert len(ing.failures) == 1
        failure = ing.failures[0]
        assert (failure.entity, failure.doc_type) == ("fi", "balancete")
        assert (failure.year, failure.month) == (2023, 1)
        assert "TimeoutError" in failure.error

    def test_skipped_404_never_enters_the_ledger(self):
        # An unpublished month is a non-event, not a failure — otherwise every
        # daily run would go red on its own trailing window.
        ing = CVMIngestor.__new__(CVMIngestor)
        ing._supabase = None
        ing._log_start("run-2", "fi", "balancete", 2026, 8)
        ing._log_finish("run-2", 0, "ValueError: Data not found at https://...")

        assert ing.failures == []

    def test_success_never_enters_the_ledger(self):
        ing = CVMIngestor.__new__(CVMIngestor)
        ing._supabase = None
        ing._log_start("run-3", "fi", "balancete", 2025, 6)
        ing._log_finish("run-3", 2_144_523, fetched=2_144_523)

        assert ing.failures == []

    def test_fetched_rows_but_zero_upserted_is_a_failure(self):
        # The existing per-slice data contract; it must reach the ledger too.
        ing = CVMIngestor.__new__(CVMIngestor)
        ing._supabase = None
        ing._log_start("run-4", "fi", "balancete", 2025, 6)
        ing._log_finish("run-4", 0, fetched=1000)

        assert len(ing.failures) == 1
        assert "upserted 0" in ing.failures[0].error

    def test_ledger_is_per_instance(self):
        a, b = CVMIngestor.__new__(CVMIngestor), CVMIngestor.__new__(CVMIngestor)
        a._supabase = None
        a._log_start("r", "fi", "balancete", 2023, 1)
        a._log_finish("r", 0, "TimeoutError")
        assert len(a.failures) == 1
        assert b.failures == []

    def test_cli_exits_non_zero_with_failures(self):
        failures = [SliceFailure("fi", "balancete", 2023, 1, "TimeoutError")]
        with pytest.raises(SystemExit) as exc:
            ensure_no_failed_slices(failures)
        assert exc.value.code == 1

    def test_cli_exits_clean_with_none(self):
        ensure_no_failed_slices([])       # must not raise

    def test_failure_renders_the_slice_identity(self):
        text = str(SliceFailure("fi", "balancete", 2023, 1, "TimeoutError"))
        assert "fi/balancete" in text and "2023-01" in text and "TimeoutError" in text

    @pytest.mark.asyncio
    async def test_partial_failure_still_counts_the_successful_siblings(self):
        # The rows that landed are real; the run fails because the range is
        # incomplete, not because the successes are suspect.
        ing = CVMIngestor.__new__(CVMIngestor)
        ing._supabase = None
        ing._run_task_batches = _run_serially

        async def flaky(year, month):
            run_id = f"r-{year}-{month}"
            ing._log_start(run_id, "fi", "balancete", year, month)
            if month == 4:
                ing._log_finish(run_id, 0, "TimeoutError")
                return 0
            ing._log_finish(run_id, 100, fetched=100)
            return 100

        ing.ingest_fi_balancete = flaky
        totals = await ing.backfill(
            start_year=2019, end_year=2019,
            entity_filter="fi", doc_type_filter="balancete",
            months=[(2019, 4), (2019, 5), (2019, 6)],
        )

        assert totals["cvm_fi_balancete"] == 200
        assert len(ing.failures) == 1
        assert ing.failures[0].month == 4
        with pytest.raises(SystemExit):
            ensure_no_failed_slices(ing.failures)

    @pytest.mark.asyncio
    async def test_a_task_that_raises_is_also_recorded(self):
        # Escaping the ingest method entirely bypasses _log_finish, so
        # _run_task_batches has to catch it or the run still exits 0.
        ing = CVMIngestor.__new__(CVMIngestor)
        ing._supabase = None

        async def boom(year, month):
            raise RuntimeError("connection reset")

        ing.ingest_fi_balancete = boom
        await ing.backfill(
            start_year=2019, end_year=2019,
            entity_filter="fi", doc_type_filter="balancete",
            months=[(2019, 4)],
        )
        assert len(ing.failures) == 1
        assert "connection reset" in ing.failures[0].error


# ---------------------------------------------------------------------------
# One audit row per attempt (integrity rule 3)
# ---------------------------------------------------------------------------

class TestAuditProvenance:
    @pytest.mark.asyncio
    async def test_each_repaired_month_logs_exactly_one_start_and_one_finish(self):
        ing = CVMIngestor.__new__(CVMIngestor)
        ing._supabase = None
        ing._run_task_batches = _run_serially
        starts, finishes = [], []

        real_start, real_finish = ing._log_start, ing._log_finish
        ing._log_start = lambda rid, e, d, y, m: (
            starts.append((e, d, y, m)), real_start(rid, e, d, y, m))[1]
        ing._log_finish = lambda rid, rows, error=None, fetched=None: (
            finishes.append(rid), real_finish(rid, rows, error, fetched))[1]

        async def ok(year, month):
            rid = f"r-{year}-{month}"
            ing._log_start(rid, "fi", "balancete", year, month)
            ing._log_finish(rid, 10, fetched=10)
            return 10

        ing.ingest_fi_balancete = ok
        await ing.backfill(
            start_year=2019, end_year=2019,
            entity_filter="fi", doc_type_filter="balancete",
            months=[(2019, 4), (2019, 7)],
        )

        assert starts == [("fi", "balancete", 2019, 4), ("fi", "balancete", 2019, 7)]
        assert len(finishes) == 2 and len(set(finishes)) == 2


# ---------------------------------------------------------------------------
# _store keeps the event loop responsive
# ---------------------------------------------------------------------------

class TestStoreOffloadsBlockingWork:
    @pytest.mark.asyncio
    async def test_a_blocking_store_does_not_stall_the_loop(self):
        """The starvation fix, measured.

        Before _store, a multi-minute psycopg2 upsert ran on the loop and any
        co-scheduled download's ClientTimeout(total=) — a wall-clock timer —
        simply expired. Here a 'blocking upsert' sleeps while a co-scheduled
        coroutine ticks; if the loop were blocked the ticker would not advance.
        """
        import time as _time

        ing = CVMIngestor.__new__(CVMIngestor)
        ticks = 0

        def blocking_upsert(_client, _rows):
            _time.sleep(0.3)          # stands in for execute_values
            return 42

        async def ticker():
            nonlocal ticks
            for _ in range(20):
                await asyncio.sleep(0.01)
                ticks += 1

        rows, _ = await asyncio.gather(
            ing._store(blocking_upsert, None, []),
            ticker(),
        )

        assert rows == 42
        assert ticks == 20, (
            f"event loop was starved: ticker advanced only {ticks}/20 times "
            "while the blocking store ran"
        )
