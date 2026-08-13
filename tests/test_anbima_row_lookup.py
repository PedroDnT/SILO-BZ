"""The ANBIMA boletim parser must read the sheets by SHAPE, never by offset.

ANBIMA reflows these workbooks between editions: it inserts fund types, grows the
monthly window, and moves the YTD / 12-month columns. A hardcoded offset does not
fail loudly when that happens — it keeps resolving to *valid rows (or columns) of
a different category* whose numbers then get stored under the wrong label. That
is silent data corruption, strictly worse than reading nothing.

These tests shift sheets around and assert the parser follows the labels and the
header dates, and they pin the hierarchy rules that make the widened primary key
(reference_date, anbima_category, anbima_type_name, metric, level) collision-free.
"""

from datetime import date, datetime

import pytest

from src.pipeline.anbima_pipeline import (
    LEVEL_CATEGORY,
    LEVEL_TOTAL,
    LEVEL_TYPE,
    TOTAL_CATEGORY,
    canonical_category,
    canonical_total,
    classify_type_row,
    dedupe_records,
    find_class_header,
    find_type_header,
    is_total_label,
    map_type_columns,
    parse_class_sheet,
    parse_type_sheet,
    strip_footnote,
)


# ── fakes ─────────────────────────────────────────────────────────────────────

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


# ── label normalisation ───────────────────────────────────────────────────────

class TestLabelNormalisation:
    def test_footnote_markers_are_stripped(self):
        # Markers migrate between editions; leaving them in the name would fork
        # the primary key on the next boletim.
        assert strip_footnote("FIAGRO (11)") == "FIAGRO"
        assert strip_footnote("Renda Fixa (3)") == "Renda Fixa"
        assert strip_footnote("Tipos ANBIMA(10)") == "Tipos ANBIMA"
        assert strip_footnote("Previdência Renda Fixa Duração Alta Crédito Livre (1)") == (
            "Previdência Renda Fixa Duração Alta Crédito Livre")

    def test_whitespace_is_collapsed(self):
        assert strip_footnote("  Total  doméstico  ") == "Total doméstico"

    def test_non_strings_and_blanks(self):
        for v in (None, 42, "", "   "):
            assert strip_footnote(v) is None

    def test_every_published_spelling_maps_to_one_category(self):
        # The same class is spelled differently on different sheets.
        assert canonical_category("Renda Fixa") == "Renda Fixa"
        assert canonical_category("Renda fixa") == "Renda Fixa"
        assert canonical_category("Renda Fixa (3)") == "Renda Fixa"
        assert canonical_category("OFF-SHORE") == "Off Shore"
        assert canonical_category("Off shore") == "Off Shore"
        assert canonical_category("FIAGRO (11)") == "FIAGRO"
        assert canonical_category("ETF") == "ETF"
        assert canonical_category("Ações") == "Ações"

    def test_unknown_labels_are_not_categories(self):
        for v in ("ETF Renda Fixa", "Total geral", "Obs.: qualquer coisa", None):
            assert canonical_category(v) is None

    def test_total_rows_are_recognised_and_canonicalised(self):
        assert is_total_label("Total geral")
        assert is_total_label("Total doméstico ")
        assert not is_total_label("Renda Fixa")
        # Pág. 5 and Pág. 9 spell the same total differently.
        assert canonical_total("Total Fundos de Investimentos") == "Total Fundos de Investimento"
        assert canonical_total("Total fundos de investimento") == "Total Fundos de Investimento"
        assert canonical_total("Total geral") == "Total Geral"
        # An unknown total keeps its published label rather than being dropped.
        assert canonical_total("Total novo agregado") == "Total novo agregado"


# ── type-sheet header + column discovery ──────────────────────────────────────

class TestTypeColumnDiscovery:
    def test_header_row_is_found_by_its_dates(self):
        rows = [[None, "banner"], [None, None], [None, "Tipos ANBIMA", datetime(2026, 6, 1)]]
        assert find_type_header(rows) == 2

    def test_no_header_row(self):
        assert find_type_header([[None, "banner"], [None, "Obs."]]) == -1

    def test_columns_are_classified_from_the_header(self):
        header = [
            None, "Tipos ANBIMA",
            datetime(2026, 5, 1), datetime(2026, 6, 1), "jul-26",
            "Total Captação Líquida -jul/25 até jul/26",   # rolling: ambiguous
            "Total Captação Líquida - no ano",
            "Total Captação Líquida - 12 meses",
        ]
        months, ytd, twelve = map_type_columns(header)
        assert months == {2: date(2026, 5, 1), 3: date(2026, 6, 1), 4: date(2026, 7, 1)}
        assert ytd == [6]
        assert twelve == [7]

    def test_a_longer_monthly_block_moves_the_totals(self):
        """The July-2026 boletim grew from 16 to 19 month columns. Fixed offsets
        silently slid onto plain monthly values and stored them as YTD."""
        header = [None, "Tipos ANBIMA"] + [datetime(2025, m, 1) for m in range(1, 13)]
        header += ["Total rentabilidade - ano", "Total rentabilidade - 12 meses"]
        months, ytd, twelve = map_type_columns(header)
        assert len(months) == 12
        assert ytd == [14] and twelve == [15]


# ── type-sheet row classification (the hierarchy) ─────────────────────────────

class TestClassifyTypeRow:
    def test_category_row_sets_the_class(self):
        assert classify_type_row([None, "Renda fixa"], None, True) == (
            LEVEL_CATEGORY, None, "Renda Fixa", "Renda Fixa")

    def test_category_row_without_values_still_counts(self):
        """Pág. 11 prints the class rows as bare labels with no numbers; the
        types beneath them would otherwise have no class to belong to."""
        assert classify_type_row([None, "Ações"], None, False) == (
            LEVEL_CATEGORY, None, "Ações", "Ações")

    def test_type_row_inherits_the_current_class(self):
        assert classify_type_row([225, "ETF Renda Fixa"], "ETF", True) == (
            LEVEL_TYPE, 225, "ETF Renda Fixa", "ETF")

    def test_total_rows_never_become_the_current_class(self):
        level, type_id, name, cat = classify_type_row([None, "Total geral"], "Off Shore", True)
        assert (level, type_id, name, cat) == (LEVEL_TOTAL, None, "Total Geral", TOTAL_CATEGORY)

    def test_banners_headers_and_footnotes_are_skipped(self):
        for label in ("Tipos ANBIMA", "Fundos estruturados ", "Fundos off shore",
                      "Classes de Investimento de Estruturados",
                      "10. Tipos ANBIMA compostos apenas por CICs",
                      "Obs.: Dados sujeitos à retificação",
                      "ANBIMA – Informação Pública", None, ""):
            assert classify_type_row([None, label], "ETF", False) is None

    def test_unnumbered_row_under_its_own_class_is_a_type(self):
        # Pág. 9 prints the FII types with no ANBIMA id.
        assert classify_type_row([None, "FII Tijolo Renda Gestão Ativa"], "FII", True) == (
            LEVEL_TYPE, None, "FII Tijolo Renda Gestão Ativa", "FII")

    def test_unknown_row_with_values_becomes_its_own_category(self, caplog):
        # Loudly its own class, never silently filed under the previous one.
        with caplog.at_level("WARNING"):
            out = classify_type_row([None, "Cripto"], "ETF", True)
        assert out == (LEVEL_CATEGORY, None, "Cripto", "Cripto")
        assert "not a known class" in caplog.text

    def test_type_before_any_category_is_skipped_not_guessed(self, caplog):
        with caplog.at_level("WARNING"):
            assert classify_type_row([225, "ETF Renda Fixa"], None, True) is None
        assert "before any class row" in caplog.text


# ── type sheet: position independence + the collision case ────────────────────

class TestParseTypeSheet:
    def _rows(self, offset):
        header = [None, "Tipos ANBIMA", datetime(2026, 5, 1), datetime(2026, 6, 1)]
        rows = [[None, None] for _ in range(5)]
        rows.append(header)
        rows += [[None, f"Other {i}"] for i in range(offset)]
        rows += [
            [None,  "ETF",                10.0, 11.0],
            [225,   "ETF Renda Fixa",      1.0,  2.0],
            [226,   "ETF Renda Variável",  3.0,  4.0],
        ]
        return rows

    def _parse(self, rows):
        wb = _FakeWB(_FakeWS(rows))
        return parse_type_sheet(
            wb, "Pág. 5", "Pág. 5 - PL por Tipo",
            monthly_metric="pl_brl_mm", ytd_metric="", twelvem_metric="",
            boletim_ref="b.xlsx",
        )

    def test_same_records_regardless_of_position(self):
        strip = lambda rs: sorted(
            (r["anbima_type_name"], r["metric"], str(r["reference_date"]), r["value"])
            for r in rs
        )
        at_historical = self._parse(self._rows(67))
        shifted = self._parse(self._rows(70))
        assert strip(at_historical) == strip(shifted)
        assert at_historical, "expected records"

    def test_values_attach_to_the_right_row(self):
        by_name = {}
        for r in self._parse(self._rows(70)):
            by_name.setdefault(r["anbima_type_name"], []).append(r["value"])
        assert sorted(by_name["ETF Renda Fixa"]) == [1.0, 2.0]
        assert sorted(by_name["ETF Renda Variável"]) == [3.0, 4.0]
        assert sorted(by_name["ETF"]) == [10.0, 11.0]

    def test_etf_rows_keep_their_category_and_levels(self):
        recs = self._parse(self._rows(3))
        agg = [r for r in recs if r["anbima_type_name"] == "ETF"]
        typ = [r for r in recs if r["anbima_type_name"] == "ETF Renda Fixa"]
        assert {r["anbima_category"] for r in recs} == {"ETF"}
        assert {r["level"] for r in agg} == {LEVEL_CATEGORY}
        assert {r["anbima_type_id"] for r in agg} == {None}
        assert {r["level"] for r in typ} == {LEVEL_TYPE}
        assert {r["anbima_type_id"] for r in typ} == {225}

    def test_all_classes_are_captured_not_just_etf(self):
        """The whole point of the widening: every class in the sheet is stored."""
        header = [None, "Tipos ANBIMA", datetime(2026, 6, 1)]
        rows = [[None, None] for _ in range(5)] + [header]
        rows += [
            [None, "Renda fixa",     100.0],
            [272,  "Renda Fixa Simples", 10.0],
            [None, "Ações",          200.0],
            [287,  "Ações Indexados", 20.0],
            [None, "ETF",            300.0],
            [225,  "ETF Renda Fixa",  30.0],
            [None, "FIDC",           400.0],
            [None, "Off shore",      500.0],
        ]
        recs = self._parse(rows)
        assert {r["anbima_category"] for r in recs} == {
            "Renda Fixa", "Ações", "ETF", "FIDC", "Off Shore"}
        assert {r["anbima_type_name"] for r in recs} == {
            "Renda Fixa", "Renda Fixa Simples", "Ações", "Ações Indexados",
            "ETF", "ETF Renda Fixa", "FIDC", "Off Shore"}

    def test_category_and_type_of_the_same_name_stay_distinct_rows(self):
        """Cambial / FIP / FIAGRO are published BOTH as a class aggregate and as
        an ANBIMA type of the identical name. Under the old key
        (date, type_name, metric) the type row silently overwrote the class."""
        header = [None, "Tipos ANBIMA", datetime(2026, 6, 1)]
        rows = [[None, None] for _ in range(5)] + [header]
        rows += [
            [None, "Cambial",     7110.0],
            [251,  "Cambial",     7110.0],
            [None, "FIP",       863508.0],
            [238,  "FIP",       863508.0],
            [None, "FIAGRO (11)", 56642.0],
            [348,  "FIAGRO",      56642.0],
        ]
        recs = self._parse(rows)
        assert len(recs) == 6

        keys = {(r["reference_date"], r["anbima_category"], r["anbima_type_name"],
                 r["metric"], r["level"]) for r in recs}
        assert len(keys) == 6, "primary key must separate the aggregate from the type"

        for name, type_id in (("Cambial", 251), ("FIP", 238), ("FIAGRO", 348)):
            pair = [r for r in recs if r["anbima_type_name"] == name]
            assert len(pair) == 2, name
            by_level = {r["level"]: r for r in pair}
            assert by_level[LEVEL_CATEGORY]["anbima_type_id"] is None
            assert by_level[LEVEL_TYPE]["anbima_type_id"] == type_id
            # both sides keep the same owning category
            assert {r["anbima_category"] for r in pair} == {name}

        # And the old, narrower key really would have collided.
        old_keys = {(r["reference_date"], r["anbima_type_name"], r["metric"])
                    for r in recs}
        assert len(old_keys) == 3

    def test_total_rows_land_as_level_total(self):
        header = [None, "Tipos ANBIMA", datetime(2026, 6, 1)]
        rows = [[None, None] for _ in range(5)] + [header]
        rows += [
            [None, "ETF",             300.0],
            [225,  "ETF Renda Fixa",   30.0],
            [None, "Total geral", 11197132.7],
            # A type row after the total must still belong to ETF, not to 'Total'.
            [226,  "ETF Renda Variável", 270.0],
        ]
        recs = self._parse(rows)
        total = [r for r in recs if r["level"] == LEVEL_TOTAL]
        assert len(total) == 1
        assert total[0]["anbima_type_name"] == "Total Geral"
        assert total[0]["anbima_category"] == TOTAL_CATEGORY
        assert total[0]["anbima_type_id"] is None
        assert total[0]["value"] == 11197132.7

        after = [r for r in recs if r["anbima_type_name"] == "ETF Renda Variável"]
        assert [r["anbima_category"] for r in after] == ["ETF"]

    def test_missing_header_yields_nothing_rather_than_wrong_rows(self):
        rows = [[None, "banner"], [None, "Renda Fixa", 9.0]]
        assert self._parse(rows) == []

    def test_non_finite_cells_are_dropped(self):
        header = [None, "Tipos ANBIMA", datetime(2026, 6, 1), datetime(2026, 5, 1)]
        rows = [[None, None] for _ in range(5)] + [header]
        rows += [[None, "ETF", float("nan"), 5.0]]
        recs = self._parse(rows)
        assert [r["value"] for r in recs] == [5.0]


# ── class sheets ──────────────────────────────────────────────────────────────

class TestClassSheets:
    def _sheet(self, lead_rows):
        """Pág.4-shaped sheet: clean names, footnoted names, then the data."""
        return lead_rows + [
            [None, "Renda Fixa", "ETF", "FIAGRO", None],
            ["Período", "Renda Fixa (3)", "ETF", "FIAGRO (11)", "Total"],
            [datetime(2006, 12, 1), 510238.3, 2735.4, 0.0, 939626.1],
            [datetime(2026, 7, 1), 4780560.1, 120437.5, 56642.5, 11197132.7],
            ["Obs.: dados sujeitos à retificação", None, None, None, None],
        ]

    def _parse(self, rows, monthly="pl_brl_mm", annual="pl_brl_mm"):
        wb = _FakeWB(_FakeWS(rows, title="Pág. 4 - PL por Classe"))
        return parse_class_sheet(wb, "Pág. 4", "Pág. 4 - PL por Classe",
                                 monthly_metric=monthly, annual_metric=annual,
                                 boletim_ref="b.xlsx")

    def test_header_is_located_from_the_first_data_row(self):
        rows = self._sheet([[None] * 5 for _ in range(4)])
        first_data, header = find_class_header(rows)
        assert first_data == 6
        assert header[1] == "Renda Fixa"

    def test_the_first_published_year_is_not_dropped(self):
        """The old reader started at a hardcoded row and lost 2006 entirely."""
        recs = self._parse(self._sheet([[None] * 5 for _ in range(4)]))
        years = {r["reference_date"].year for r in recs}
        assert 2006 in years and 2026 in years

    def test_output_is_unchanged_when_the_sheet_shifts(self):
        strip = lambda rs: sorted((r["anbima_category"], str(r["reference_date"]),
                                   r["value"]) for r in rs)
        a = self._parse(self._sheet([[None] * 5 for _ in range(4)]))
        b = self._parse(self._sheet([[None] * 5 for _ in range(7)]))
        assert strip(a) == strip(b) and a

    def test_all_classes_are_captured_and_total_columns_ignored(self):
        recs = self._parse(self._sheet([[None] * 5 for _ in range(4)]))
        assert {r["anbima_category"] for r in recs} == {"Renda Fixa", "ETF", "FIAGRO"}
        assert all(r["level"] == LEVEL_CATEGORY for r in recs)
        assert all(r["anbima_type_id"] is None for r in recs)
        assert all(r["anbima_type_name"] == r["anbima_category"] for r in recs)
        assert not [r for r in recs if r["value"] == 11197132.7], "Total column stored"

    def test_etf_values_are_unchanged(self):
        recs = self._parse(self._sheet([[None] * 5 for _ in range(4)]))
        etf = {r["reference_date"]: r["value"] for r in recs if r["anbima_category"] == "ETF"}
        assert etf == {date(2006, 12, 1): 2735.4, date(2026, 7, 1): 120437.5}

    def test_pag8_annual_and_monthly_rows_get_different_metrics(self):
        """Pág. 8 interleaves whole-year rows (2025) with months (202501). The
        old reader read the month NUMBER as a year and stored it at year 0001."""
        rows = [[None] * 4 for _ in range(4)] + [
            [None, None, "ETF", None],
            [None, "Período", "ETF", "Total"],
            [2024, 2024, -1185.6, 121864.4],
            [2026, 2026, 34060.3, 208835.3],
            [202601, 1, 4701.1, 88244.2],
            [202607, 7, 1545.3, -25267.3],
        ]
        wb = _FakeWB(_FakeWS(rows, title="Pág. 8 - Cap. Líq. por Classe"))
        recs = parse_class_sheet(
            wb, "Pág. 8", "Pág. 8 - Cap. Líq. por Classe",
            monthly_metric="captacao_liquida_brl_mm",
            annual_metric="captacao_liquida_ytd_brl_mm",
            boletim_ref="b.xlsx")
        got = {(str(r["reference_date"]), r["metric"]): r["value"] for r in recs}
        assert got == {
            ("2024-12-01", "captacao_liquida_ytd_brl_mm"): -1185.6,
            ("2026-01-01", "captacao_liquida_ytd_brl_mm"): 34060.3,
            ("2026-01-01", "captacao_liquida_brl_mm"): 4701.1,
            ("2026-07-01", "captacao_liquida_brl_mm"): 1545.3,
        }
        assert not [r for r in recs if r["reference_date"].year < 1900]


# ── dedupe ────────────────────────────────────────────────────────────────────

class TestDedupe:
    def _rec(self, value, sheet, name="ETF"):
        return {
            "reference_date": date(2026, 7, 1), "anbima_category": "ETF",
            "anbima_type_id": None, "anbima_type_name": name, "metric": "pl_brl_mm",
            "value": value, "level": LEVEL_CATEGORY, "source_sheet": sheet,
            "boletim_ref": "b.xlsx",
        }

    def test_first_sheet_wins(self):
        out = dedupe_records([self._rec(1.0, "Pág. 4"), self._rec(1.0, "Pág. 5")])
        assert len(out) == 1 and out[0]["source_sheet"] == "Pág. 4"

    def test_disagreement_is_reported_not_hidden(self, caplog):
        with caplog.at_level("WARNING"):
            out = dedupe_records([self._rec(1.0, "Pág. 4"), self._rec(9.0, "Pág. 5")])
        assert len(out) == 1 and out[0]["value"] == 1.0
        assert "disagree" in caplog.text

    def test_distinct_keys_survive(self):
        out = dedupe_records([self._rec(1.0, "Pág. 4"), self._rec(2.0, "Pág. 5", "ETF Renda Fixa")])
        assert len(out) == 2
