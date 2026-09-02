"""A backfill that upserted nothing because the source published nothing is not a failure.

THE RUN THIS EXISTS FOR. Backfill 33659046190 asked for exactly one slice,
fi / cda_debentures / 2005, to confirm #184's classification live. The fetcher
did precisely what #184 built it to do:

    ValueError: ZIP member 'cda_fi_BLC_6_2005.csv' not published in this
    archive — 5 sibling block(s) for the same period are present
    (['cda_fi_BLC_1_2005.csv', 'cda_fi_BLC_2_2005.csv', 'cda_fi_BLC_3_2005.csv',
      'cda_fi_BLC_4_2005.csv', 'cda_fi_BLC_8_2005.csv']), so the archive is the
    right one and this block has not been released yet.

_classify_finish resolved that to 'skipped', the audit row is correct, and no
slice entered the failure ledger. Then ensure_rows_landed saw 0 total rows and
exited 1 with:

    Backfill upserted 0 rows across all slices — treating as failure
    (every fetch likely failed; check network/CVM availability)

Every clause of which was false. The fetch succeeded, the network was fine, and
CVM was available — it simply has no block 6 for 2005 and never will. That is
the same defect #184 fixed at the audit-log layer, surviving one layer up in the
CLI: a correct non-event rendered as a failure. A red run that means "working as
intended" is how people learn to ignore red runs.

The guard still has to catch the failure it was built for (2026-06-10: four
hours of refused downloads, "0 total rows", exit 0, CI green, partitions empty),
so the three zeros are told apart rather than collapsed.
"""

import logging

import pytest

from src.pipeline.cvm_pipeline import CVMIngestor
from src.pipeline.run_backfill import ensure_rows_landed


class TestZeroRowsGuard:
    def test_rows_landed_never_fails(self):
        ensure_rows_landed(1_234, skips=[], failures=[])

    def test_an_unexplained_zero_is_still_fatal(self):
        """The 2026-06-10 shape, minus a failure ledger. Must stay loud."""
        with pytest.raises(SystemExit) as exc:
            ensure_rows_landed(0, skips=[], failures=[])
        assert exc.value.code == 1

    def test_a_zero_explained_entirely_by_skips_is_not_a_failure(self):
        """Run 33659046190. The whole point."""
        ensure_rows_landed(
            0,
            skips=["fi/cda_debentures 2005: ZIP member … not published in this archive"],
            failures=[],
        )

    def test_the_skipped_slices_are_named_in_the_log(self, caplog):
        """An operator reading a green run must see WHY it landed nothing."""
        with caplog.at_level(logging.INFO, logger="run_backfill"):
            ensure_rows_landed(0, skips=["fi/cda_debentures 2005: not published"], failures=[])
        text = caplog.text
        assert "fi/cda_debentures 2005" in text
        assert "not a failure" in text.lower()
        assert "network" not in text.lower(), "the false diagnosis must be gone"

    def test_a_zero_with_failures_defers_rather_than_guessing(self):
        """ensure_no_failed_slices names them; this must not pre-empt it with a guess."""
        ensure_rows_landed(0, skips=[], failures=["fi/balancete 2021-04: TimeoutError"])

    def test_a_zero_with_both_defers_to_the_failures(self):
        ensure_rows_landed(0, skips=["fi/cda_debentures 2005: not published"],
                           failures=["fi/balancete 2021-04: TimeoutError"])

    def test_the_guard_still_defaults_to_fatal_when_called_with_only_a_count(self):
        """Older call sites pass one argument. They must keep the strict behaviour."""
        with pytest.raises(SystemExit):
            ensure_rows_landed(0)


class TestSkipLedger:
    """The ledger feeding the guard, recorded exactly where 'skipped' is decided."""

    def _ingestor(self) -> CVMIngestor:
        # As elsewhere in the suite: no DB connection, the audit path still works.
        return CVMIngestor.__new__(CVMIngestor)

    def test_a_skip_is_recorded_with_its_slice_and_reason(self):
        ing = self._ingestor()
        ing._slice_of_run["run-1"] = ("fi", "cda_debentures", 2005, None)
        ing._record_skip("run-1", "ZIP member not published in this archive")
        assert ing.skips == [
            "fi/cda_debentures 2005: ZIP member not published in this archive"
        ]

    def test_a_monthly_slice_renders_its_month(self):
        ing = self._ingestor()
        ing._slice_of_run["run-2"] = ("fi", "cda_debentures", 2026, 8)
        ing._record_skip("run-2", "not published")
        assert ing.skips == ["fi/cda_debentures 2026-08: not published"]

    def test_an_undated_slice_renders_no_period(self):
        ing = self._ingestor()
        ing._slice_of_run["run-3"] = ("fi", "registry", None, None)
        ing._record_skip("run-3", "not published")
        assert ing.skips == ["fi/registry: not published"]

    def test_the_ledgers_are_per_instance(self):
        """Two ingestors must not share state — same rule as `failures`."""
        a, b = self._ingestor(), self._ingestor()
        a._slice_of_run["r"] = ("fi", "cda", 2005, None)
        a._record_skip("r", "not published")
        assert a.skips and b.skips == []

    def test_a_skip_is_never_a_failure(self):
        ing = self._ingestor()
        ing._slice_of_run["r"] = ("fi", "cda_debentures", 2005, None)
        ing._record_skip("r", "not published")
        assert ing.failures == [], "a skip must never enter the failure ledger"


class TestLogFinishWiring:
    """The ledger must fill from _log_finish itself, not from a caller remembering to.

    That is why _record_failure lives there: 'the ledger cannot drift from the
    audit table'. A skip ledger populated anywhere else would drift the same way.
    """

    # The real message from run 33659046190, trimmed to what _classify_finish reads.
    REAL_MSG = (
        "ValueError: ZIP member 'cda_fi_BLC_6_2005.csv' not published in this archive "
        "— 5 sibling block(s) for the same period are present, so the archive is the "
        "right one and this block has not been released yet."
    )

    def _ingestor(self):
        from unittest.mock import MagicMock, patch

        class _Cur:
            def __enter__(self): return self
            def __exit__(self, *e): return False
            def execute(self, sql, params=None): pass

        class _Client:
            def cursor(self): return _Cur()

        with patch("src.pipeline.cvm_pipeline.get_pg_client", return_value=MagicMock()):
            ing = CVMIngestor()
        ing._supabase = _Client()
        return ing

    def test_the_real_unpublished_block_message_lands_in_skips(self):
        ing = self._ingestor()
        ing._slice_of_run["run-1"] = ("fi", "cda_debentures", 2005, None)
        ing._log_finish("run-1", 0, error=self.REAL_MSG)
        assert len(ing.skips) == 1
        assert ing.skips[0].startswith("fi/cda_debentures 2005:")
        assert ing.failures == []

    def test_a_404_also_lands_in_skips(self):
        ing = self._ingestor()
        ing._slice_of_run["run-2"] = ("fi", "cda_debentures", 2026, 9)
        ing._log_finish("run-2", 0, error="ValueError: Data not found at https://x/y.zip")
        assert len(ing.skips) == 1 and ing.failures == []

    def test_a_real_error_lands_in_failures_and_not_in_skips(self):
        ing = self._ingestor()
        ing._slice_of_run["run-3"] = ("fi", "cda_debentures", 2026, 8)
        ing._log_finish(
            "run-3", 0,
            error="ValueError: ZIP member 'x.csv' not found in archive — refusing to fall back",
        )
        assert len(ing.failures) == 1 and ing.skips == []

    def test_a_successful_slice_touches_neither_ledger(self):
        ing = self._ingestor()
        ing._slice_of_run["run-4"] = ("fi", "cda_debentures", 2025, None)
        ing._log_finish("run-4", 253_563, fetched=253_563)
        assert ing.skips == [] and ing.failures == []
