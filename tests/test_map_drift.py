"""Tests for field-map drift detection (map_coverage / assert_map_matches).

Motivation: `apply_map` returns None per unmatched candidate and cannot report
"this FIELD_MAP no longer fits the source". That blind spot is how the FIAGRO map
went stale — CVM-175 renamed the headers, zero candidates matched, every row was
dropped for a missing natural key, and the ingest returned 0 rows without raising
(34 slices logged 'ok' behind an empty table).

Drift is a property of the HEADER, not of the values, so these helpers ignore
values entirely.
"""

import pytest

from src.parsers.mapping import (
    FieldMapMismatch,
    assert_map_matches,
    map_coverage,
)

MAP = {
    "cnpj":   (["CNPJ_Classe", "CNPJ_FUNDO"], "cnpj"),
    "period": (["Data_Referencia", "DT_COMPTC"], "date"),
    "value":  (["Patrimonio_Liquido"], "numeric"),
}


class TestMapCoverage:
    def test_all_matched(self):
        cov = map_coverage(
            ["CNPJ_Classe", "Data_Referencia", "Patrimonio_Liquido"], MAP)
        assert cov.unmatched == frozenset()
        assert cov.ratio == 1.0

    def test_legacy_candidate_also_counts(self):
        cov = map_coverage(["CNPJ_FUNDO", "DT_COMPTC", "Patrimonio_Liquido"], MAP)
        assert cov.unmatched == frozenset()

    def test_partial(self):
        cov = map_coverage(["CNPJ_Classe", "Unrelated"], MAP)
        assert cov.matched == frozenset({"cnpj"})
        assert cov.unmatched == frozenset({"period", "value"})
        assert cov.ratio == pytest.approx(1 / 3)

    def test_none_matched(self):
        cov = map_coverage(["Totally", "Different"], MAP)
        assert cov.matched == frozenset()
        assert cov.ratio == 0.0

    def test_matching_is_case_and_space_insensitive(self):
        # _norm lowercases and strips spaces — CVM ships header variants.
        cov = map_coverage([" cnpj_classe ", "DATA_REFERENCIA",
                            "patrimonio_liquido"], MAP)
        assert cov.unmatched == frozenset()

    def test_presence_not_value_decides(self):
        # An empty value still counts as matched: the column exists and other
        # rows may populate it. Only an absent header means "can never populate".
        cov = map_coverage(["CNPJ_Classe", "Data_Referencia",
                            "Patrimonio_Liquido"], MAP)
        assert cov.ratio == 1.0


class TestAssertMapMatches:
    def _row(self, **kw):
        base = {"CNPJ_Classe": "1", "Data_Referencia": "2026-01-01",
                "Patrimonio_Liquido": "2"}
        base.update(kw)
        return base

    def test_healthy_header_passes(self):
        cov = assert_map_matches([self._row()], MAP, dataset="d",
                                 required=("cnpj", "period"))
        assert cov.ratio == 1.0

    def test_missing_required_column_raises(self):
        rows = [{"Renamed_Cnpj": "1", "Renamed_Date": "2026-01-01"}]
        with pytest.raises(FieldMapMismatch) as exc:
            assert_map_matches(rows, MAP, dataset="fiagro/mensal",
                               required=("cnpj", "period"))
        msg = str(exc.value)
        assert "fiagro/mensal" in msg
        assert "cnpj" in msg and "period" in msg
        assert "field_maps" in msg  # points the operator at the fix

    def test_one_missing_required_column_is_enough(self):
        rows = [{"CNPJ_Classe": "1", "Renamed_Date": "x"}]
        with pytest.raises(FieldMapMismatch):
            assert_map_matches(rows, MAP, dataset="d",
                               required=("cnpj", "period"))

    def test_empty_rows_is_not_drift(self):
        # A genuinely empty slice must not be reported as a schema change.
        cov = assert_map_matches([], MAP, dataset="d", required=("cnpj", "period"))
        assert cov.matched == frozenset()

    def test_unmatched_non_required_column_only_warns(self, caplog):
        # Several maps legitimately list candidates for multiple tab/format
        # variants, so sparse coverage must not be fatal.
        rows = [{"CNPJ_Classe": "1", "Data_Referencia": "2026-01-01"}]
        with caplog.at_level("WARNING"):
            cov = assert_map_matches(rows, MAP, dataset="d",
                                     required=("cnpj", "period"))
        assert cov.unmatched == frozenset({"value"})  # no raise

    def test_low_ratio_warns(self, caplog):
        big_map = dict(MAP, extra1=(["A"], "text"), extra2=(["B"], "text"),
                       extra3=(["C"], "text"))
        rows = [{"CNPJ_Classe": "1", "Data_Referencia": "2026-01-01"}]
        with caplog.at_level("WARNING"):
            assert_map_matches(rows, big_map, dataset="d", required=("cnpj",))
        assert "possible source" in caplog.text.lower() or "drift" in caplog.text.lower()

    def test_ragged_rows_union_their_keys(self):
        # Header is taken from a union of the first rows, so a source shipping
        # ragged dicts doesn't produce a false positive.
        rows = [{"CNPJ_Classe": "1"}, {"Data_Referencia": "2026-01-01"}]
        cov = assert_map_matches(rows, MAP, dataset="d",
                                 required=("cnpj", "period"))
        assert {"cnpj", "period"} <= cov.matched
