"""CVM lamina (fi-doc-lamina) dataset: config, field map, ingest, wiring.

The fixture tests/fixtures/fi_lamina/lamina_fi_202608_rows.csv is the header and
the first two data rows of the real lamina_fi_202608.csv, copied verbatim from the
read-only probe's log (.github/workflows/lamina_header_probe.yml, run 37084697408,
2026-10-03). Rows built in the tests are edits of those rows, marked as such.
"""

import csv
import re
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from src.fetchers.cvm_config import DatasetConfig
from src.parsers.field_maps import fi_lamina
from src.parsers.mapping import FieldMapMismatch, apply_map, map_coverage
from src.pipeline import gaps
from src.pipeline.ingest_fi import ingest_fi_lamina

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/fi_lamina/lamina_fi_202608_rows.csv"


def _rows():
    with FIXTURE.open(encoding="utf-8", newline="") as fh:
        return [dict(r) for r in csv.DictReader(fh, delimiter=";")]


def _capture(rows):
    captured = {}

    def _fake_upsert(conn, table, recs, **kw):
        captured["table"] = table
        captured["recs"] = recs
        captured["conflict"] = kw.get("conflict_columns")
        return len(recs)

    with patch("src.pipeline.ingest_fi.upsert_rows", side_effect=_fake_upsert):
        n = ingest_fi_lamina(object(), rows)
    return n, captured


class TestFixture:
    def test_is_the_real_78_column_header(self):
        rows = _rows()
        assert len(rows) == 2
        assert len(rows[0]) == 78
        assert rows[0]["TP_FUNDO_CLASSE"] == "CLASSES - FIF"
        assert rows[0]["DT_COMPTC"] == "2026-08-31"


class TestFieldMap:
    def test_every_candidate_header_exists_in_the_real_file(self):
        cov = map_coverage(set(_rows()[0]), fi_lamina.FIELD_MAP)
        assert not cov.unmatched, sorted(cov.unmatched)

    def test_conflict_columns_are_mapped_columns(self):
        assert set(fi_lamina.CONFLICT) <= set(fi_lamina.FIELD_MAP)

    def test_performance_fee_is_text_and_never_numeric(self):
        assert fi_lamina.FIELD_MAP["taxa_perfm"][1] == "text"

    def test_typed_fee_and_redemption_values(self):
        typed, residual = apply_map(_rows()[0], fi_lamina.FIELD_MAP)
        assert typed["cnpj"] == "00280302000160"
        assert typed["dt_comptc"] == date(2026, 8, 31)
        assert typed["id_subclasse"] is None
        assert typed["tp_taxa_adm"] == "Fixa"
        assert typed["taxa_adm"] == 0.5
        assert typed["taxa_adm_min"] == 0.0 and typed["taxa_adm_max"] == 0.0
        assert typed["taxa_adm_obs"] == "0,5% do patrimônio líquido ao ano"
        assert typed["taxa_perfm"] is None          # the source cell is empty
        assert typed["pr_pl_despesa"] == 0.13
        assert typed["qt_dia_conversao_cota_resgate"] == 0
        assert typed["qt_dia_pagto_resgate"] == 0
        assert typed["tp_dia_pagto_resgate"] == "Dias Úteis"
        assert typed["invest_inicial_min"] == 2000000.0
        assert typed["indice_refer"] == "CDI"
        # Unmapped columns stay in raw; mapped ones leave it.
        assert "OBJETIVO" in residual
        assert "TAXA_ADM" not in residual


class TestConfig:
    def test_dataset_points_at_the_main_member_of_the_monthly_zip(self):
        cfg = DatasetConfig.FI_DATASETS["lamina"]
        assert cfg["is_zip"] is True
        assert cfg["url_pattern"].format(base_url="B", year=2026, month=8) == (
            "B/FI/DOC/LAMINA/DADOS/lamina_fi_202608.zip"
        )
        member = cfg["csv_name_pattern"].format(year=2026, month=8)
        assert member == "lamina_fi_202608.csv"      # not _carteira_, _rentab_ano_, _rentab_mes_


class TestIngest:
    def test_upserts_on_the_source_key_with_raw(self):
        n, cap = _capture(_rows())
        assert n == 2
        assert cap["table"] == "cvm_fi_lamina"
        assert cap["conflict"] == "cnpj,dt_comptc,id_subclasse"
        for rec in cap["recs"]:
            assert rec["raw"]["OBJETIVO"]
            assert rec["dt_comptc"] == date(2026, 8, 31)   # as filed, not first of month

    def test_performance_fee_text_is_kept_as_filed(self):
        rows = _rows()
        # edit of the fixture row: a filled TAXA_PERFM
        rows[0]["TAXA_PERFM"] = "20,00% do que exceder 100,00% do CDI."
        _, cap = _capture(rows)
        assert cap["recs"][0]["taxa_perfm"] == "20,00% do que exceder 100,00% do CDI."

    def test_an_unparseable_number_is_kept_in_raw_not_guessed(self):
        rows = _rows()
        # edit of the fixture row: a fee cell that is not a number
        rows[0]["TAXA_ADM"] = "1,5% ao ano + 0,2%"
        _, cap = _capture(rows)
        rec = cap["recs"][0]
        assert rec["taxa_adm"] is None
        assert rec["raw"]["_unparsed"] == {"TAXA_ADM": "1,5% ao ano + 0,2%"}
        assert "_unparsed" not in cap["recs"][1]["raw"]

    def test_drops_an_invalid_cnpj_and_an_undated_row(self):
        rows = _rows()
        rows[0]["CNPJ_FUNDO_CLASSE"] = "11.111.111/1111-11"   # edit: fails the checksum
        rows[1]["DT_COMPTC"] = "não informado"                # edit: no parseable date
        n, cap = _capture(rows)
        assert n == 0 and "recs" not in cap

    def test_subclass_rows_of_one_fund_are_both_kept(self):
        rows = _rows()
        sub = dict(rows[0])
        sub["ID_SUBCLASSE"] = "HDFA61753286584"               # edit: a subclass id
        _, cap = _capture([rows[0], sub])
        keys = {(r["cnpj"], r["id_subclasse"]) for r in cap["recs"]}
        assert keys == {("00280302000160", None), ("00280302000160", "HDFA61753286584")}

    def test_empty_slice_is_not_an_error(self):
        assert _capture([])[0] == 0

    def test_a_header_that_lost_the_key_raises(self):
        rows = [{k: v for k, v in r.items() if k != "CNPJ_FUNDO_CLASSE"} for r in _rows()]
        with patch("src.pipeline.ingest_fi.upsert_rows", side_effect=AssertionError("no upsert")):
            with pytest.raises(FieldMapMismatch):
                ingest_fi_lamina(object(), rows)


class TestWiring:
    def test_gap_repair_knows_the_table(self):
        assert gaps.FI_MONTHLY_TABLES["lamina"] == ("cvm_fi_lamina", "dt_comptc", None)

    def test_daily_window_has_a_spec_whose_log_keys_match_the_ingest(self):
        src = (ROOT / "src/pipeline/cvm_pipeline.py").read_text()
        assert re.search(
            r'\("cvm_fi_lamina", "fi", "lamina", "lamina", self\.ingest_fi_lamina\)', src
        )
        # The spec's (entity, doc_type) must be what the method logs, or the
        # gap-aware window never sees the month as loaded.
        assert 'self._audited("fi", "lamina", year, month, work)' in src
        assert '"cvm_fi_lamina"' in re.search(r"_ALL_TABLES: List\[str\] = \[.*?\]", src, re.S).group(0)

    def test_migration_and_schema_agree_on_the_table_and_the_view(self):
        mig = (ROOT / "src/store/migrations/65_fi_lamina.sql").read_text()
        schema = (ROOT / "src/store/schema.sql").read_text()
        for sql in (mig, schema):
            assert "CREATE TABLE IF NOT EXISTS cvm_fi_lamina" in sql
            assert "UNIQUE NULLS NOT DISTINCT (cnpj, dt_comptc, id_subclasse)" in sql
            assert "CREATE OR REPLACE VIEW vw_fi_lamina_latest" in sql
        assert "REVOKE ALL ON cvm_fi_lamina FROM anon, authenticated" in mig

    def test_every_typed_column_of_the_map_is_a_table_column(self):
        mig = (ROOT / "src/store/migrations/65_fi_lamina.sql").read_text()
        body = re.search(r"CREATE TABLE IF NOT EXISTS cvm_fi_lamina \((.*?)\n\);", mig, re.S).group(1)
        cols = {m.group(1) for m in re.finditer(r"^\s{4}(\w+)\s+[A-Z]", body, re.M)}
        assert set(fi_lamina.FIELD_MAP) <= cols
