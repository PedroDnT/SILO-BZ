"""An archive that exists but has not released a block is 'skipped', not 'error'.

THE ROWS THIS EXISTS FOR. DB Health run 33558708450 (2026-09-01) failed on two
cvm_ingest_log slices that will never heal on their own:

    fi | cda_debentures | 2026 | 8    ZIP member 'cda_fi_BLC_6_202608.csv' not found
    fi | cda_debentures | 2005 |      ZIP member 'cda_fi_BLC_6_2005.csv'   not found

Both archives exist and were downloaded fine. cda_fi_202608.zip is CVM's
partial current-month publication — three blocks in, block 6 not yet — and
the 2005 HIST archive predates block 6 entirely. The fetcher was right to
refuse falling back to another member (a fallback is how FII `trimestral`
ingested property-sale records for years). It was wrong to let that read as a
failure: `_log_finish` mapped only a 404 to 'skipped', so a block CVM has not
published logged 'error', and the 2026-08 row would have gone red on every
daily run until CVM added the member.

The distinction has to be earned, not assumed. A member can also be missing
because it was RENAMED — source drift the audit log must flag. So the fetcher
says "not published in this archive" only when sibling CDA blocks for the same
period are present, which proves the archive is the one we meant. No siblings,
no proof: the original fatal wording stands and the slice stays 'error'.
"""

import io
import zipfile

import pytest

from src.fetchers.cvm_fetcher import CVMFetcher, _cda_sibling_blocks
from src.pipeline.cvm_pipeline import CVMIngestor, _classify_finish


def _zip_with(members) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name in members:
            zf.writestr(name, f"A;B\n{name};1\n".encode("latin-1"))
    return buf.getvalue()


# The real member list of cda_fi_202608.zip on 2026-09-01: three blocks, no 6.
PARTIAL_MONTH = ["cda_fi_BLC_1_202608.csv", "cda_fi_BLC_2_202608.csv", "cda_fi_BLC_4_202608.csv"]


class TestFetcherWording:
    def test_a_block_missing_beside_its_siblings_is_reported_as_not_published(self):
        fetcher = CVMFetcher()
        with pytest.raises(ValueError) as exc:
            fetcher._extract_csv_from_zip(_zip_with(PARTIAL_MONTH), "cda_fi_BLC_6_{year}{month:02d}.csv", 2026, 8)
        msg = str(exc.value)
        assert "not published in this archive" in msg
        assert "3 sibling block(s)" in msg
        assert "not found in archive" not in msg

    def test_a_missing_member_with_no_siblings_keeps_the_fatal_wording(self):
        """A renamed member is source drift, and must still read as an error."""
        fetcher = CVMFetcher()
        renamed = ["cda_fi_BLOCO_6_202608.csv", "cda_fi_PL_202608.csv"]
        with pytest.raises(ValueError) as exc:
            fetcher._extract_csv_from_zip(_zip_with(renamed), "cda_fi_BLC_6_{year}{month:02d}.csv", 2026, 8)
        msg = str(exc.value)
        assert "not found in archive" in msg
        assert "not published" not in msg

    def test_siblings_must_share_the_period_not_just_the_family(self):
        """BLC_1 for July is not proof that August's archive is the right one."""
        assert _cda_sibling_blocks(["cda_fi_BLC_1_202607.csv"], "cda_fi_BLC_6_202608.csv") == []
        assert _cda_sibling_blocks(["cda_fi_BLC_1_202608.csv"], "cda_fi_BLC_6_202608.csv") == [
            "cda_fi_BLC_1_202608.csv"
        ]

    def test_the_yearly_hist_shape_is_recognised_too(self):
        """2005's archive has blocks 1..5 and no 6: publication, not drift."""
        members = [f"cda_fi_BLC_{n}_2005.csv" for n in range(1, 6)]
        assert len(_cda_sibling_blocks(members, "cda_fi_BLC_6_2005.csv")) == 5

    def test_non_cda_datasets_get_no_sibling_reasoning(self):
        """Only the BLC_<n>_<period> shape is told apart; everything else is as before."""
        fetcher = CVMFetcher()
        with pytest.raises(ValueError) as exc:
            fetcher._extract_csv_from_zip(
                _zip_with(["inf_trimestral_fii_geral_2025.csv"]), "inf_trimestral_fii_{year}.csv", 2025, None
            )
        assert "not found in archive" in str(exc.value)

    def test_nothing_ever_falls_back(self):
        """Both wordings raise. The point of the original fix is untouched."""
        fetcher = CVMFetcher()
        with pytest.raises(ValueError):
            fetcher._extract_csv_from_zip(_zip_with(PARTIAL_MONTH), "cda_fi_BLC_6_{year}{month:02d}.csv", 2026, 8)


class TestAuditClassification:
    def test_a_404_is_skipped(self):
        assert _classify_finish("ValueError: Data not found at https://x/y.zip", None, 0)[0] == "skipped"

    def test_an_unpublished_block_is_skipped(self):
        msg = "ValueError: ZIP member 'cda_fi_BLC_6_202608.csv' not published in this archive — 3 sibling block(s) …"
        status, kept = _classify_finish(msg, None, 0)
        assert status == "skipped"
        assert kept == msg, "the reason must be stored with the row, not discarded"

    def test_a_renamed_member_is_still_an_error(self):
        msg = "ValueError: ZIP member 'cda_fi_BLC_6_202608.csv' not found in archive — refusing to fall back"
        assert _classify_finish(msg, None, 0)[0] == "error"

    def test_the_fetched_but_nothing_landed_contract_is_unchanged(self):
        """cvm_fiagro_mensal sat empty behind 34 'ok' slices once. Never again."""
        status, msg = _classify_finish(None, fetched=1200, rows=0)
        assert status == "error"
        assert "fetched 1200 source row(s) but upserted 0" in msg

    def test_an_empty_published_file_is_ok(self):
        assert _classify_finish(None, fetched=0, rows=0) == ("ok", None)

    def test_rows_landed_is_ok(self):
        assert _classify_finish(None, fetched=10, rows=10) == ("ok", None)


class TestSkipLedger:
    """The CLI zero-row guard must be able to tell skip from fetch-failure."""

    def _ingestor(self):
        ing = CVMIngestor.__new__(CVMIngestor)
        ing._supabase = None
        return ing

    def test_unpublished_block_is_a_skip_not_a_failure(self):
        ing = self._ingestor()
        ing._log_start("r", "fi", "cda_debentures", 2005, None)
        msg = (
            "ValueError: ZIP member 'cda_fi_BLC_6_2005.csv' not published in "
            "this archive — 5 sibling block(s)"
        )
        ing._log_finish("r", 0, msg)
        assert ing.failures == []
        assert len(ing.skips) == 1
        assert ing.skips[0].year == 2005
        assert ing.skips[0].month is None
        assert "not published" in ing.skips[0].error

    def test_renamed_member_is_still_a_failure(self):
        ing = self._ingestor()
        ing._log_start("r", "fi", "cda_debentures", 2005, None)
        ing._log_finish(
            "r", 0,
            "ValueError: ZIP member 'cda_fi_BLC_6_2005.csv' not found in "
            "archive — refusing to fall back",
        )
        assert len(ing.failures) == 1
        assert ing.skips == []

    def test_a_404_is_also_a_skip(self):
        ing = self._ingestor()
        ing._log_start("r", "fi", "cda_debentures", 2026, 8)
        ing._log_finish("r", 0, "ValueError: Data not found at https://x/y.zip")
        assert ing.failures == []
        assert len(ing.skips) == 1
        assert ing.skips[0].month == 8
