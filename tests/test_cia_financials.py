"""Unit tests for W7 cia_account + cia_filing field maps and ingest paths.

Covers:
  * Field-map projection from representative ITR/DFP statement + summary rows.
  * cd_cvm zero-strip normalisation (ITR/DFP pad to 6 digits).
  * BPA (balance-sheet) row tolerating the absent DT_INI_EXERC column.
  * ESCALA_MOEDA scaling of VL_CONTA to absolute reais at ingest.
  * grupo / escopo / doc_type injected from the CIAMember, not the CSV.
  * residual (GRUPO_DFP etc.) -> raw on cia_account; cia_filing has no raw.
  * Drop-row rules (missing cd_cvm / cd_conta / dt_refer).
  * Upsert call shape (table + conflict columns) and one-call-per-member.

All tests are offline — no HTTP, no Postgres.
"""

import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest
from unittest.mock import MagicMock, patch

from src.parsers.field_maps import cia_account as _account_map
from src.parsers.field_maps import cia_filing as _filing_map
from src.parsers.mapping import apply_map, coerce
from src.pipeline.ingest_cia import (
    ingest_cia_account,
    ingest_cia_filing,
    _scale_factor,
)


# ---------------------------------------------------------------------------
# Representative rows (verified live 2026-05-29 against dfp_cia_aberta_2023.zip)
# ---------------------------------------------------------------------------

# DRE member row — has both DT_INI_EXERC and DT_FIM_EXERC.
DRE_ROW = {
    "CNPJ_CIA": "00.000.000/0001-91",
    "DT_REFER": "2023-12-31",
    "VERSAO": "1",
    "DENOM_CIA": "BCO BRASIL S.A.",
    "CD_CVM": "001023",
    "GRUPO_DFP": "DF Consolidado - Demonstração do Resultado",
    "MOEDA": "REAL",
    "ESCALA_MOEDA": "MIL",
    "ORDEM_EXERC": "ÚLTIMO",
    "DT_INI_EXERC": "2023-01-01",
    "DT_FIM_EXERC": "2023-12-31",
    "CD_CONTA": "3.01",
    "DS_CONTA": "Receitas de Intermediação Financeira",
    "VL_CONTA": "236549051.0000000000",
    "ST_CONTA_FIXA": "S",
}

# BPA (balance-sheet) member row — point-in-time, NO DT_INI_EXERC column.
BPA_ROW = {
    "CNPJ_CIA": "00.000.000/0001-91",
    "DT_REFER": "2023-12-31",
    "VERSAO": "1",
    "DENOM_CIA": "BCO BRASIL S.A.",
    "CD_CVM": "001023",
    "GRUPO_DFP": "DF Consolidado - Balanço Patrimonial Ativo",
    "MOEDA": "REAL",
    "ESCALA_MOEDA": "MIL",
    "ORDEM_EXERC": "ÚLTIMO",
    "DT_FIM_EXERC": "2023-12-31",
    "CD_CONTA": "1",
    "DS_CONTA": "Ativo Total",
    "VL_CONTA": "2284844184.0000000000",
    "ST_CONTA_FIXA": "S",
}

# Summary header row -> cia_filing.
SUMMARY_ROW = {
    "CNPJ_CIA": "00.000.000/0001-91",
    "DT_REFER": "2023-12-31",
    "VERSAO": "1",
    "DENOM_CIA": "BCO BRASIL S.A.",
    "CD_CVM": "001023",
    "CATEG_DOC": "DFP",
    "ID_DOC": "133944",
    "DT_RECEB": "2024-02-08",
    "LINK_DOC": "http://www.rad.cvm.gov.br/ENETCONSULTA/frmDownloadDocumento.aspx?...",
}


@dataclass
class FakeMember:
    """Duck-typed stand-in for CIAFetcher.CIAMember."""

    grupo: str
    escopo: Optional[str]
    rows: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def is_account_data(self) -> bool:
        return self.escopo is not None

    @property
    def is_summary(self) -> bool:
        return self.grupo == "_summary"


# ---------------------------------------------------------------------------
# Field-map projection
# ---------------------------------------------------------------------------

class TestCiaAccountFieldMap:
    def test_metadata(self):
        assert _account_map.TABLE == "cia_account"
        # Conflict key must match uq_cia_account exactly. Two columns are in it
        # only because leaving them out silently destroyed rows:
        #   coluna_df    — migration 05, DMPL equity components (~85% collapse)
        #   dt_ini_exerc — migration 29, ITR quarter vs year-to-date (40% of
        #                  DRE_con rows in itr_cia_aberta_2025.zip)
        assert _account_map.CONFLICT == (
            "cd_cvm", "doc_type", "grupo", "escopo",
            "dt_refer", "ordem_exerc", "coluna_df", "dt_ini_exerc",
            "cd_conta", "versao",
        )

    def test_dmpl_row_captures_coluna_df(self):
        # DMPL members carry COLUNA_DF (equity component); it must be a typed
        # column (part of the natural key), not residual.
        dmpl_row = {**DRE_ROW, "COLUNA_DF": "Reservas de Lucro"}
        typed, raw = apply_map(dmpl_row, _account_map.FIELD_MAP)
        assert typed["coluna_df"] == "Reservas de Lucro"
        assert "COLUNA_DF" not in raw
        # Non-DMPL rows leave coluna_df NULL.
        typed2, _ = apply_map(DRE_ROW, _account_map.FIELD_MAP)
        assert typed2["coluna_df"] is None

    def test_projects_dre_row(self):
        typed, _raw = apply_map(DRE_ROW, _account_map.FIELD_MAP)
        assert typed["cd_cvm"] == "1023"             # zero-stripped
        assert typed["cnpj_cia"] == "00000000000191"
        assert typed["dt_refer"] == datetime.date(2023, 12, 31)
        assert typed["versao"] == 1
        assert typed["cd_conta"] == "3.01"
        assert typed["vl_conta"] == 236549051.0        # pre-scale (numeric)
        assert typed["escala_moeda"] == "MIL"
        assert typed["dt_ini_exerc"] == datetime.date(2023, 1, 1)
        assert typed["dt_fim_exerc"] == datetime.date(2023, 12, 31)

    def test_bpa_row_tolerates_missing_dt_ini(self):
        # The map must NOT include grupo/escopo/doc_type (injected by ingest).
        typed, _raw = apply_map(BPA_ROW, _account_map.FIELD_MAP)
        assert typed["dt_ini_exerc"] is None           # column absent in BPA
        assert typed["dt_fim_exerc"] == datetime.date(2023, 12, 31)
        assert "grupo" not in typed
        assert "escopo" not in typed
        assert "doc_type" not in typed

    def test_residual_preserves_unmapped_fields(self):
        _typed, raw = apply_map(DRE_ROW, _account_map.FIELD_MAP)
        # Descriptive / denormalised fields fall through to raw JSONB.
        assert "GRUPO_DFP" in raw
        assert "MOEDA" in raw
        assert "DENOM_CIA" in raw


class TestCiaFilingFieldMap:
    def test_metadata(self):
        assert _filing_map.TABLE == "cia_filing"
        assert _filing_map.CONFLICT == ("cd_cvm", "doc_type", "dt_refer", "versao")

    def test_projects_summary_row(self):
        typed, _raw = apply_map(SUMMARY_ROW, _filing_map.FIELD_MAP)
        assert typed["cd_cvm"] == "1023"
        assert typed["dt_refer"] == datetime.date(2023, 12, 31)
        assert typed["versao"] == 1
        assert typed["id_doc"] == "133944"
        assert typed["dt_receb"] == datetime.date(2024, 2, 8)
        assert typed["link_doc"].startswith("http")


# ---------------------------------------------------------------------------
# coerce / scaling helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    @pytest.mark.parametrize("raw,expected", [
        ("001023", "1023"),
        ("25224", "25224"),
        ("000000", None),
        ("", None),
        ("  001023 ", "1023"),
    ])
    def test_cd_cvm_coerce(self, raw, expected):
        assert coerce(raw, "cd_cvm") == expected

    @pytest.mark.parametrize("escala,factor", [
        ("MIL", 1_000.0),
        ("mil", 1_000.0),
        ("MILHAO", 1_000_000.0),
        ("MILHÃO", 1_000_000.0),
        ("UNIDADE", 1.0),
        (None, 1.0),
        ("BOGUS", 1.0),
    ])
    def test_scale_factor(self, escala, factor):
        assert _scale_factor(escala) == factor


# ---------------------------------------------------------------------------
# Ingest unit tests — injection, scaling, drop-row, upsert call shape
# ---------------------------------------------------------------------------

@pytest.fixture
def captured_upserts():
    """Patch upsert_rows in ingest_cia and capture each call."""
    calls: List[dict] = []

    def _fake(client, table, rows, conflict_columns=None):
        calls.append({"table": table, "rows": rows, "conflict_columns": conflict_columns})
        return len(rows)

    with patch("src.pipeline.ingest_cia.upsert_rows", side_effect=_fake):
        yield calls


class TestIngestCiaAccount:
    def test_happy_path_injects_and_scales(self, captured_upserts):
        member = FakeMember(grupo="DRE", escopo="con", rows=[DRE_ROW])
        n = ingest_cia_account(MagicMock(), [member], "dfp")
        assert n == 1
        call = captured_upserts[0]
        assert call["table"] == "cia_account"
        assert call["conflict_columns"] == ",".join(_account_map.CONFLICT)
        rec = call["rows"][0]
        assert rec["grupo"] == "DRE"
        assert rec["escopo"] == "con"
        assert rec["doc_type"] == "dfp"
        # 236549051 (MIL) scaled to absolute reais.
        assert rec["vl_conta"] == 236549051.0 * 1_000.0
        assert rec["escala_moeda"] == "MIL"            # original kept for audit
        assert isinstance(rec["raw"], dict) and "GRUPO_DFP" in rec["raw"]

    def test_one_upsert_call_per_account_member(self, captured_upserts):
        members = [
            FakeMember(grupo="DRE", escopo="con", rows=[DRE_ROW]),
            FakeMember(grupo="BPA", escopo="ind", rows=[BPA_ROW]),
        ]
        n = ingest_cia_account(MagicMock(), members, "itr")
        assert n == 2
        assert len(captured_upserts) == 2
        assert {c["rows"][0]["grupo"] for c in captured_upserts} == {"DRE", "BPA"}

    def test_skips_non_account_members(self, captured_upserts):
        members = [
            FakeMember(grupo="_summary", escopo=None, rows=[SUMMARY_ROW]),
            FakeMember(grupo="composicao_capital", escopo=None, rows=[DRE_ROW]),
            FakeMember(grupo="parecer", escopo=None, rows=[DRE_ROW]),
        ]
        n = ingest_cia_account(MagicMock(), members, "dfp")
        assert n == 0
        assert captured_upserts == []

    def test_drops_rows_missing_natural_key(self, captured_upserts):
        no_conta = {**DRE_ROW, "CD_CONTA": ""}
        no_cd_cvm = {**DRE_ROW, "CD_CVM": ""}
        no_dt = {**DRE_ROW, "DT_REFER": ""}
        member = FakeMember(grupo="DRE", escopo="con",
                            rows=[DRE_ROW, no_conta, no_cd_cvm, no_dt])
        n = ingest_cia_account(MagicMock(), [member], "dfp")
        assert n == 1                                  # only the good row survives
        assert len(captured_upserts[0]["rows"]) == 1

    def test_null_vl_conta_not_scaled(self, captured_upserts):
        null_vl = {**DRE_ROW, "VL_CONTA": ""}
        member = FakeMember(grupo="DRE", escopo="con", rows=[null_vl])
        ingest_cia_account(MagicMock(), [member], "dfp")
        assert captured_upserts[0]["rows"][0]["vl_conta"] is None


class TestIngestCiaFiling:
    def test_happy_path(self, captured_upserts):
        n = ingest_cia_filing(MagicMock(), [SUMMARY_ROW], "dfp")
        assert n == 1
        call = captured_upserts[0]
        assert call["table"] == "cia_filing"
        assert call["conflict_columns"] == "cd_cvm,doc_type,dt_refer,versao"
        rec = call["rows"][0]
        assert rec["cd_cvm"] == "1023"
        assert rec["doc_type"] == "dfp"
        assert rec["id_doc"] == "133944"
        # cia_filing has NO raw column — ingest must not emit one.
        assert "raw" not in rec

    def test_drops_rows_missing_key(self, captured_upserts):
        no_cd = {**SUMMARY_ROW, "CD_CVM": ""}
        no_dt = {**SUMMARY_ROW, "DT_REFER": ""}
        n = ingest_cia_filing(MagicMock(), [SUMMARY_ROW, no_cd, no_dt], "itr")
        assert n == 1
        assert len(captured_upserts[0]["rows"]) == 1

    def test_empty_input_short_circuits(self, captured_upserts):
        assert ingest_cia_filing(MagicMock(), [], "dfp") == 0
        assert captured_upserts == []


# ---------------------------------------------------------------------------
# Parametrised PK smoke test (mirrors test_cia_field_maps style)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "field_map_module,row,expected_col,expected_val",
    [
        (_account_map, DRE_ROW, "cd_cvm", "1023"),
        (_filing_map, SUMMARY_ROW, "cd_cvm", "1023"),
    ],
)
def test_field_map_yields_normalised_cd_cvm(field_map_module, row, expected_col, expected_val):
    typed, _raw = apply_map(row, field_map_module.FIELD_MAP)
    assert typed[expected_col] == expected_val
