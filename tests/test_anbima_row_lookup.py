"""ANBIMA type-level sheets must be located by label, not by fixed row offset.

_parse_type_sheet used to read rows 73/74/75 verbatim. Those offsets are correct
in current boletins, which is precisely why this never surfaced — but if ANBIMA
inserts a fund type above them, the offsets still resolve to *valid rows of a
different category*, whose numbers would be stored labelled 'ETF'. That is silent
data corruption, strictly worse than reading nothing.

These tests shift the sheet and assert the parser follows the labels.
"""

from datetime import datetime

import pytest

from src.pipeline.anbima_etf_pipeline import (
    _parse_type_sheet,
    find_etf_rows,
    match_etf_label,
)


class TestMatchEtfLabel:
    def test_aggregate_only_on_exact_etf(self):
        assert match_etf_label("ETF") == (None, "ETF")
        assert match_etf_label("  etf  ") == (None, "ETF")

    def test_subcategories(self):
        assert match_etf_label("ETF Renda Fixa") == (225, "ETF Renda Fixa")
        assert match_etf_label("ETF Renda Variável") == (226, "ETF Renda Variável")
        # prefix match tolerates suffixes/accents drift
        assert match_etf_label("etf renda fixa longa")[0] == 225

    def test_non_etf_and_non_strings(self):
        for v in ("Renda Fixa", "Ações", "FIDC", None, 42, ""):
            assert match_etf_label(v) is None


class TestFindEtfRows:
    def _sheet(self, offset: int):
        """A sheet with `offset` filler rows before the ETF block."""
        rows = [["filler", f"Other Category {i}"] for i in range(offset)]
        rows += [
            [None, "ETF"],
            [225, "ETF Renda Fixa"],
            [226, "ETF Renda Variável"],
        ]
        return rows

    def test_finds_at_the_historical_offset(self):
        found = find_etf_rows(self._sheet(73))
        assert [(i, t) for i, t, _ in found] == [(73, None), (74, 225), (75, 226)]

    def test_follows_a_shifted_sheet(self):
        # ANBIMA inserts two new categories above the ETF block.
        found = find_etf_rows(self._sheet(75))
        assert [i for i, _, _ in found] == [75, 76, 77]
        assert [n for _, _, n in found] == [
            "ETF", "ETF Renda Fixa", "ETF Renda Variável"]

    def test_no_etf_rows_returns_empty(self):
        assert find_etf_rows([["x", "Renda Fixa"], ["y", "Ações"]]) == []

    def test_ignores_short_rows(self):
        assert find_etf_rows([[], ["only-one-cell"]]) == []

    def test_sheet_type_id_wins_over_label(self, caplog):
        # If ANBIMA renumbers a category, trust the sheet and say so.
        with caplog.at_level("WARNING"):
            found = find_etf_rows([[999, "ETF Renda Fixa"]])
        assert found == [(0, 999, "ETF Renda Fixa")]
        assert "trusting the sheet" in caplog.text


class _FakeWS:
    def __init__(self, rows, title="Pág. 5 - PL por Tipo"):
        self._rows, self.title = rows, title

    def iter_rows(self, min_row=1):
        class _C:
            def __init__(self, v): self.value = v
        for r in self._rows[min_row - 1:]:
            yield [_C(v) for v in r]


class _FakeWB:
    def __init__(self, ws): self._ws, self.sheetnames = ws, [ws.title]
    def __getitem__(self, name): return self._ws


class TestParseTypeSheetIsPositionIndependent:
    def _rows(self, offset):
        # Monthly values live in columns 2..16, paired positionally with the date
        # objects in the header row, so the fixture puts both at columns 2 and 3.
        header = [None, None, datetime(2026, 5, 1), datetime(2026, 6, 1)]
        rows = [[None, None] for _ in range(5)]          # rows 0-4
        rows.append(header)                               # row 5: header
        rows += [[None, f"Other {i}"] for i in range(offset)]
        rows += [
            [None,  "ETF",                10.0, 11.0],
            [225,   "ETF Renda Fixa",      1.0,  2.0],
            [226,   "ETF Renda Variável",  3.0,  4.0],
        ]
        return rows

    def _parse(self, offset):
        wb = _FakeWB(_FakeWS(self._rows(offset)))
        return _parse_type_sheet(
            wb, "Pág. 5", "Pág. 5 - PL por Tipo",
            monthly_metric="pl_brl_mm", ytd_metric="", twelvem_metric="",
            boletim_ref="b.xlsx",
        )

    def test_same_records_regardless_of_position(self):
        """The whole point: shifting the sheet must not change the output."""
        at_historical = self._parse(67)   # ETF block lands at the old indices
        shifted = self._parse(70)         # three new categories inserted above
        strip = lambda rs: sorted(
            (r["anbima_type_name"], r["metric"], str(r["reference_date"]), r["value"])
            for r in rs
        )
        assert strip(at_historical) == strip(shifted)
        assert at_historical, "expected records"

    def test_values_attach_to_the_right_category(self):
        recs = self._parse(70)
        by_name = {}
        for r in recs:
            by_name.setdefault(r["anbima_type_name"], []).append(r["value"])
        assert sorted(by_name["ETF Renda Fixa"]) == [1.0, 2.0]
        assert sorted(by_name["ETF Renda Variável"]) == [3.0, 4.0]
        assert sorted(by_name["ETF"]) == [10.0, 11.0]

    def test_missing_etf_rows_yields_nothing_rather_than_wrong_rows(self):
        rows = [[None, None] for _ in range(5)]
        rows.append([None, None, datetime(2026, 6, 1)])
        rows += [[None, "Renda Fixa", None, 9.0]]
        wb = _FakeWB(_FakeWS(rows))
        assert _parse_type_sheet(
            wb, "Pág. 5", "lbl", monthly_metric="pl_brl_mm",
            ytd_metric="", twelvem_metric="", boletim_ref="b",
        ) == []
