"""CVM Extrato das Informacoes (fi-doc-extrato) dataset: config, field map, ingest, wiring.

The fixture tests/fixtures/fi_extrato/extrato_fi_rows.csv is SYNTHETIC. Its header
line is the real 117-column header of extrato_fi.csv, copied verbatim from the
read-only probe's log (issue #524, run 37090491647, job 111109593283, 2026-10-03);
its six data rows are invented (CNPJs with a valid checksum but belonging to no
fund, names saying SINTETICO) because the probe printed no full real row. The
value shapes they exercise are real: a punctuated CNPJ, '.' decimals
(0.300000), a filed 0, a value above 5 (14638.38 is the real maximum), a fund
with a performance fee, two versions of one CNPJ, and a repeated
(cnpj, dt_comptc). The real file is latin-1; the fixture is UTF-8 because the
fetcher decodes before parsing.
"""

import csv
import re
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from src.fetchers.cvm_config import DatasetConfig
from src.parsers.field_maps import fi_extrato
from src.parsers.mapping import FieldMapMismatch, apply_map, map_coverage
from src.pipeline import gaps
from src.pipeline.ingest_fi import ingest_fi_extrato

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/fi_extrato/extrato_fi_rows.csv"


def _rows():
    with FIXTURE.open(encoding="utf-8", newline="") as fh:
        return [dict(r) for r in csv.DictReader(fh, delimiter=";")]


def _capture(rows, source="extrato_fi.csv"):
    captured = {}

    def _fake_upsert(conn, table, recs, **kw):
        captured["table"] = table
        captured["recs"] = recs
        captured["conflict"] = kw.get("conflict_columns")
        return len(recs)

    with patch("src.pipeline.ingest_fi.upsert_rows", side_effect=_fake_upsert):
        n = ingest_fi_extrato(object(), rows, source)
    return n, captured


class TestFixture:
    def test_is_the_real_117_column_header(self):
        rows = _rows()
        assert len(rows) == 6
        assert len(rows[0]) == 117
        assert list(rows[0])[:5] == [
            "TP_FUNDO_CLASSE", "CNPJ_FUNDO_CLASSE", "DENOM_SOCIAL", "DT_COMPTC", "CONDOM",
        ]
        assert list(rows[0])[-1] == "PR_COTA_FICFIP_MAX"

    def test_rows_are_labelled_synthetic(self):
        assert all("SINTETICO" in r["DENOM_SOCIAL"] for r in _rows())


class TestFieldMap:
    def test_every_candidate_header_exists_in_the_real_header(self):
        cov = map_coverage(set(_rows()[0]), fi_extrato.FIELD_MAP)
        assert not cov.unmatched, sorted(cov.unmatched)

    def test_conflict_columns_are_mapped_columns(self):
        assert set(fi_extrato.CONFLICT) <= set(fi_extrato.FIELD_MAP)

    def test_the_performance_fee_is_numeric_and_the_exit_payment_flag_is_text(self):
        # The dictionary: TAXA_PERFM numeric(27,12); TAXA_SAIDA_PAGTO_RESGATE is S/N.
        assert fi_extrato.FIELD_MAP["taxa_perfm"][1] == "numeric"
        assert fi_extrato.FIELD_MAP["taxa_saida_pagto_resgate"][1] == "text"

    def test_dot_decimals_are_read_exactly(self):
        typed, _ = apply_map(_rows()[0], fi_extrato.FIELD_MAP)
        assert typed["taxa_adm"] == 0.3            # 0.300000, not 300000
        assert typed["cnpj"] == "11000001000152"   # punctuation stripped
        assert typed["dt_comptc"] == date(2025, 6, 30)

    def test_typed_fee_and_term_values(self):
        typed, residual = apply_map(_rows()[3], fi_extrato.FIELD_MAP)
        assert typed["tp_fundo_classe"] == "CLASSES - FIF"
        assert typed["taxa_adm"] == 2.0
        assert typed["existe_taxa_perfm"] == "S"
        assert typed["taxa_perfm"] == 20.0
        assert typed["param_taxa_perfm"] == "IBOVESPA"
        assert typed["calc_taxa_perfm"] == "LINEAR"
        assert typed["inf_taxa_perfm"].startswith("20% do que exceder")
        assert typed["existe_taxa_saida"] == "S" and typed["taxa_saida_pr"] == 1.5
        assert typed["taxa_ingresso_pr"] is None
        assert typed["qt_dia_resgate_cotas"] == 30
        assert typed["qt_dia_conversao_cota"] == 1 and typed["qt_dia_pagto_resgate"] == 3
        assert typed["tp_dia_pagto_resgate"] == "Dias Úteis"
        assert typed["classe_anbima"] == "AÇÕES - ATIVO - LIVRE"
        # The exposure limits stay in raw; mapped columns leave it.
        assert "PR_ACAO_MAX" in residual and "POLIT_INVEST" in residual
        assert "TAXA_ADM" not in residual


class TestConfig:
    def test_current_file_is_a_static_csv_with_no_year_or_month(self):
        cfg = DatasetConfig.FI_DATASETS["extrato"]
        assert cfg["is_zip"] is False
        assert cfg["url_pattern"].format(base_url="B") == "B/FI/DOC/EXTRATO/DADOS/extrato_fi.csv"
        assert "{year}" not in cfg["url_pattern"] and "{month" not in cfg["url_pattern"]

    def test_yearly_file_takes_only_the_year(self):
        cfg = DatasetConfig.FI_DATASETS["extrato_ano"]
        assert cfg["is_zip"] is False
        assert cfg["url_pattern"].format(base_url="B", year=2025) == (
            "B/FI/DOC/EXTRATO/DADOS/extrato_fi_2025.csv"
        )
        assert "{month" not in cfg["url_pattern"]


class TestIngest:
    def test_upserts_on_the_source_key_with_raw_and_the_source_file(self):
        n, cap = _capture(_rows())
        assert n == 6                    # the fake upsert does not dedupe: six rows in, six out
        assert cap["table"] == "cvm_fi_extrato"
        assert cap["conflict"] == "cnpj,dt_comptc"
        for rec in cap["recs"]:
            assert rec["source_file"] == "extrato_fi.csv"
            assert "POLIT_INVEST" in rec["raw"]
            assert "_unparsed" not in rec["raw"]
        # DT_COMPTC is stored as filed, not moved to a month start.
        assert cap["recs"][0]["dt_comptc"] == date(2025, 6, 30)

    def test_a_filed_zero_and_an_implausible_value_are_stored_as_filed(self):
        _, cap = _capture(_rows())
        by_cnpj = {r["cnpj"]: r for r in cap["recs"]}
        assert by_cnpj["11000002000105"]["taxa_adm"] == 0.0     # not NULL, not rewritten
        assert by_cnpj["11000003000141"]["taxa_adm"] == 14638.38  # not clipped, not rejected

    def test_two_versions_of_one_cnpj_are_both_kept(self):
        _, cap = _capture(_rows())
        keys = {(r["cnpj"], r["dt_comptc"]) for r in cap["recs"]}
        assert ("11000004000196", date(2026, 3, 31)) in keys
        assert ("11000004000196", date(2025, 1, 31)) in keys

    def test_a_repeated_key_reaches_upsert_in_file_order_so_the_last_row_wins(self):
        # upsert_rows dedupes on the conflict columns, last write wins (its docstring
        # and tests/test_pg_client*); the ingest passes the rows in file order.
        _, cap = _capture(_rows())
        dup = [r for r in cap["recs"]
               if r["cnpj"] == "11000001000152" and r["dt_comptc"] == date(2025, 6, 30)]
        assert [r["taxa_adm"] for r in dup] == [0.3, 0.35]

    def test_an_unparseable_number_is_kept_in_raw_not_guessed(self):
        rows = _rows()
        # edit of a fixture row: a fee cell that is free text (the XML standard allows it
        # for qualified-investor funds)
        rows[0]["TAXA_ADM"] = "Conforme regulamento"
        _, cap = _capture(rows)
        rec = cap["recs"][0]
        assert rec["taxa_adm"] is None
        assert rec["raw"]["_unparsed"] == {"TAXA_ADM": "Conforme regulamento"}
        assert "_unparsed" not in cap["recs"][1]["raw"]

    def test_the_yearly_file_name_is_the_provenance(self):
        _, cap = _capture(_rows(), source="extrato_fi_2025.csv")
        assert {r["source_file"] for r in cap["recs"]} == {"extrato_fi_2025.csv"}

    def test_drops_an_invalid_cnpj_and_an_undated_row(self):
        rows = _rows()[:2]
        rows[0]["CNPJ_FUNDO_CLASSE"] = "11.111.111/1111-11"   # edit: repeated digits
        rows[1]["DT_COMPTC"] = "não informado"                # edit: no parseable date
        n, cap = _capture(rows)
        assert n == 0 and "recs" not in cap

    def test_empty_slice_is_not_an_error(self):
        assert _capture([])[0] == 0

    def test_a_header_that_lost_the_key_raises(self):
        rows = [{k: v for k, v in r.items() if k != "CNPJ_FUNDO_CLASSE"} for r in _rows()]
        with patch("src.pipeline.ingest_fi.upsert_rows", side_effect=AssertionError("no upsert")):
            with pytest.raises(FieldMapMismatch):
                ingest_fi_extrato(object(), rows, "extrato_fi.csv")


class TestWiring:
    def test_gap_repair_lists_the_table_but_refuses_a_month_scan(self):
        assert gaps.FI_MONTHLY_TABLES["extrato"] == ("cvm_fi_extrato", "dt_comptc", None)
        assert "extrato" in gaps.SNAPSHOT_DOC_TYPES
        with pytest.raises(ValueError, match="no monthly files"):
            gaps.missing_fi_months(object(), "extrato")

    def test_audit_keys_match_what_the_methods_log(self):
        src = (ROOT / "src/pipeline/cvm_pipeline.py").read_text()
        # exactly one audit row per slice: the current file and each yearly file
        assert 'self._log_start(run_id, "fi", "extrato", None, None)' in src
        assert 'self._log_start(run_id, "fi", "extrato_ano", year, None)' in src
        assert '"cvm_fi_extrato"' in re.search(r"_ALL_TABLES: List\[str\] = \[.*?\]", src, re.S).group(0)

    def test_the_daily_run_plans_the_current_file(self):
        src = (ROOT / "src/pipeline/cvm_pipeline.py").read_text()
        assert re.search(
            r'IngestTask\(\s*"cvm_fi_extrato",\s*"fi/extrato",\s*self\.ingest_fi_extrato\(\),', src
        )

    def test_the_extrato_job_is_in_the_analyze_list_and_the_coverage_audit(self):
        daily = (ROOT / ".github/workflows/daily_ingest.yml").read_text()
        assert "cvm_fi_extrato" in daily
        audit = (ROOT / "scripts/audit_coverage.py").read_text()
        assert '("cvm_fi_extrato",' in audit

    def test_migration_and_schema_agree_on_the_table_and_the_view(self):
        mig = (ROOT / "src/store/migrations/66_fi_extrato.sql").read_text()
        schema = (ROOT / "src/store/schema.sql").read_text()
        for sql in (mig, schema):
            assert "CREATE TABLE IF NOT EXISTS cvm_fi_extrato" in sql
            assert "CONSTRAINT uq_fi_extrato UNIQUE (cnpj, dt_comptc)" in sql
            assert "CREATE OR REPLACE VIEW vw_fi_extrato_latest" in sql
        assert "REVOKE ALL ON cvm_fi_extrato FROM anon, authenticated" in mig
        assert "REVOKE ALL ON vw_fi_extrato_latest FROM anon, authenticated" in mig

    def test_every_typed_column_of_the_map_is_a_table_column(self):
        mig = (ROOT / "src/store/migrations/66_fi_extrato.sql").read_text()
        body = re.search(r"CREATE TABLE IF NOT EXISTS cvm_fi_extrato \((.*?)\n\);", mig, re.S).group(1)
        cols = {m.group(1) for m in re.finditer(r"^\s{4}(\w+)\s+[A-Z]", body, re.M)}
        assert set(fi_extrato.FIELD_MAP) <= cols
        assert "source_file" in cols


class TestBackfill:
    @staticmethod
    def _ingestor(calls):
        from unittest.mock import AsyncMock

        from src.pipeline.cvm_pipeline import CVMIngestor

        ing = CVMIngestor.__new__(CVMIngestor)

        async def ano(year):
            calls.append(("ano", year))
            return 1

        async def current():
            calls.append(("current",))
            return 1

        ing.ingest_fi_extrato_ano = ano
        ing.ingest_fi_extrato = current
        ing._run_task_batches = AsyncMock()
        return ing

    @pytest.mark.asyncio
    async def test_a_month_repair_of_extrato_is_refused_not_scheduled_as_nothing(self):
        ing = self._ingestor([])
        with pytest.raises(ValueError, match="no monthly files"):
            await ing.backfill(
                start_year=2025, end_year=2025, entity_filter="fi",
                doc_type_filter="extrato", months=[(2025, 6)],
            )

    @pytest.mark.asyncio
    async def test_only_the_job_that_reaches_the_current_year_reads_the_current_file(self):
        year = date.today().year
        for start, end, expected in (
            (2019, 2020, []),                                  # before the first yearly file
            (2022, 2022, [("ano", 2022)]),                     # a yearly job: no current file
            (year, year, [("ano", year), ("current",)]),       # the current-year job
        ):
            calls = []
            ing = self._ingestor(calls)
            await ing.backfill(
                start_year=start, end_year=end, entity_filter="fi", doc_type_filter="extrato",
            )
            assert calls == expected, (start, end)
