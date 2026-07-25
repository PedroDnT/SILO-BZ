"""FIAGRO monthly field-map regression tests.

Guards the bug found on 2026-07-25: the map carried only legacy uppercase
FIDC-style headers (CNPJ_FUNDO / DT_COMPTC / VL_PATRIM_LIQ) while CVM publishes
inf_mensal_fiagro_*.csv in CVM-175 Title_Case style (CNPJ_Classe /
Data_Referencia / Patrimonio_Liquido). Nothing matched, so every row was dropped
for a missing cnpj/period and the ingest returned 0 rows *without raising* —
34 slices logged 'ok' with an empty table behind them.

The header row below is verbatim from the real 2025-09 file (subset of its 133
columns), so a future header rename breaks these tests instead of silently
emptying the table again.
"""

from unittest.mock import patch

from src.parsers.field_maps import fiagro_mensal as fiagro
from src.parsers.mapping import apply_map
from src.pipeline.ingest_misc import ingest_fiagro_mensal

# Verbatim CVM-175 header names + values shaped like the real file.
CVM175_ROW = {
    "CNPJ_Classe": "17198500000182",
    "Nome_Classe": "SB FI NAS CADEIAS PRODUTIVAS AGROINDUSTRIAIS FIAGRO",
    "Data_Referencia": "2025-09-01",
    "Numero_Cotistas": "1",
    "Valor_Ativo": "149400536.14",
    "Patrimonio_Liquido": "149336019.78",
    "Valor_Patrimonial_Cotas": "1691.87",
    "Vencidos": "0",
    "Debentures": "123.45",  # unmapped → must land in residual raw
}

# The pre-CVM-175 shape, still accepted via the fallback candidates.
LEGACY_ROW = {
    "CNPJ_FUNDO": "28152777000190",
    "DT_COMPTC": "2025-08-31",
    "NR_COTST": "115813",
    "VL_TOTAL": "628191661.74",
    "VL_PATRIM_LIQ": "620257779.96",
    "VL_QUOTA": "10.21",
}


class TestFieldMap:
    def test_cvm175_headers_map(self):
        typed, _raw = apply_map(CVM175_ROW, fiagro.FIELD_MAP)
        assert typed["cnpj"] == "17198500000182"
        assert str(typed["period"]) == "2025-09-01"
        assert typed["nr_cotst"] == 1
        assert typed["vl_total"] == 149400536.14
        assert typed["vl_patrim_liq"] == 149336019.78
        assert typed["vl_quota"] == 1691.87
        assert typed["vl_inadimpl"] == 0.0

    def test_legacy_headers_still_map(self):
        typed, _raw = apply_map(LEGACY_ROW, fiagro.FIELD_MAP)
        assert typed["cnpj"] == "28152777000190"
        assert str(typed["period"]) == "2025-08-31"
        assert typed["nr_cotst"] == 115813
        assert typed["vl_patrim_liq"] == 620257779.96

    def test_unmapped_columns_go_to_residual(self):
        _typed, raw = apply_map(CVM175_ROW, fiagro.FIELD_MAP)
        assert raw["Debentures"] == "123.45"
        assert "Patrimonio_Liquido" not in raw  # consumed by the map

    def test_conflict_key_matches_table_constraint(self):
        assert fiagro.TABLE == "cvm_fiagro_mensal"
        assert fiagro.CONFLICT == ("cnpj", "period")


class TestIngest:
    def test_cvm175_rows_are_upserted_not_dropped(self):
        captured = {}

        def _fake_upsert(conn, table, rows, **kw):
            captured["table"] = table
            captured["rows"] = rows
            captured["conflict"] = kw.get("conflict_columns")
            return len(rows)

        with patch("src.pipeline.ingest_misc.upsert_rows", side_effect=_fake_upsert):
            n = ingest_fiagro_mensal(object(), [CVM175_ROW, LEGACY_ROW])

        assert n == 2, "CVM-175 rows must survive parsing (regression: silently 0)"
        assert captured["table"] == "cvm_fiagro_mensal"
        assert captured["conflict"] == "cnpj,period"
        assert {r["cnpj"] for r in captured["rows"]} == {
            "17198500000182", "28152777000190",
        }

    def test_row_without_keys_is_dropped(self):
        # A genuinely unusable row is still skipped — the guard stays intact.
        with patch("src.pipeline.ingest_misc.upsert_rows",
                   side_effect=AssertionError("should not upsert")):
            assert ingest_fiagro_mensal(object(), [{"Nome_Classe": "no keys"}]) == 0
