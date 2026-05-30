"""Unit tests for W6 cia_company + cia_event field maps and ingest paths.

Covers:
  * Field-map projection from representative CAD / IPE rows.
  * Ingest functions drop rows that lack the natural key.
  * apply_map residual matches the spec for the IPE feed (which has no
    raw JSONB column, so the ingest module discards it).

All tests are offline — no HTTP, no Postgres.
"""

import datetime

import pytest
from unittest.mock import MagicMock, patch

from src.parsers.field_maps import cia_company as _company_map
from src.parsers.field_maps import cia_event as _event_map
from src.parsers.mapping import apply_map
from src.pipeline.ingest_cia import ingest_cia_company, ingest_cia_event


# ---------------------------------------------------------------------------
# Representative rows (verified live 2026-05-29 against the CVM endpoints)
# ---------------------------------------------------------------------------

CAD_ROW = {
    "CNPJ_CIA": "08.773.135/0001-00",
    "DENOM_SOCIAL": "2W ECOBANK S.A. - EM RECUPERAÇÃO JUDICIAL",
    "DENOM_COMERC": "2W ECOBANK S.A.",
    "DT_REG": "2020-10-29",
    "DT_CONST": "2007-03-23",
    "DT_CANCEL": "",
    "MOTIVO_CANCEL": "",
    "SIT": "SUSPENSO(A) - DECISÃO ADM",
    "DT_INI_SIT": "2026-05-19",
    "CD_CVM": "25224",
    "SETOR_ATIV": "Energia Elétrica",
    "TP_MERC": "",
    "CATEG_REG": "Categoria A",
    "DT_INI_CATEG": "2020-10-29",
    "SIT_EMISSOR": "EM RECUPERAÇÃO JUDICIAL OU EQUIVALENTE",
    "DT_INI_SIT_EMISSOR": "2025-04-23",
    "CONTROLE_ACIONARIO": "PRIVADO",
    "TP_ENDER": "SEDE",
    "EMAIL": "ri@2wecobank.com.br",
    "AUDITOR": "GRANT THORNTON AUDITORES INDEPENDENTES LTDA.",
}

IPE_ROW = {
    "CNPJ_Companhia": "00.000.000/0001-91",
    "Nome_Companhia": "BANCO DO BRASIL S.A.",
    "Codigo_CVM": "1023",
    "Data_Referencia": "2024-02-02",
    "Categoria": "Assembleia",
    "Tipo": "AGE",
    "Especie": "Ata",
    "Assunto": "",
    "Data_Entrega": "2024-02-19",
    "Tipo_Apresentacao": "RE - Reapresentação Espontânea",
    "Protocolo_Entrega": "001023IPE020220240204533710-05",
    "Versao": "2",
    "Link_Download": "https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx?Tela=ext&descTipo=IPE&CodigoInstituicao=1&numProtocolo=1196371&numSequencia=721097&numVersao=2",
}


# ---------------------------------------------------------------------------
# Field-map tests
# ---------------------------------------------------------------------------

class TestCiaCompanyFieldMap:
    def test_metadata(self):
        assert _company_map.TABLE == "cia_company"
        assert _company_map.CONFLICT == ("cd_cvm",)

    def test_projects_all_typed_columns(self):
        typed, raw = apply_map(CAD_ROW, _company_map.FIELD_MAP)
        assert typed["cd_cvm"] == "25224"
        assert typed["cnpj_cia"] == "08773135000100"   # zero-padded 14-digit
        assert typed["denom_cia"] == "2W ECOBANK S.A. - EM RECUPERAÇÃO JUDICIAL"
        assert typed["setor"] == "Energia Elétrica"
        assert typed["segmento"] == "Categoria A"
        assert typed["situacao"] == "SUSPENSO(A) - DECISÃO ADM"

    def test_residual_preserves_unmapped_fields(self):
        _typed, raw = apply_map(CAD_ROW, _company_map.FIELD_MAP)
        # Unmapped fields stay available for audit / future promotion.
        assert "SIT_EMISSOR" in raw
        assert raw["SIT_EMISSOR"] == "EM RECUPERAÇÃO JUDICIAL OU EQUIVALENTE"
        assert "CONTROLE_ACIONARIO" in raw
        assert "AUDITOR" in raw
        # Mapped sources MUST be consumed (not present in residual).
        assert "CD_CVM" not in raw
        assert "DENOM_SOCIAL" not in raw
        assert "SETOR_ATIV" not in raw
        assert "CATEG_REG" not in raw
        assert "SIT" not in raw
        assert "CNPJ_CIA" not in raw


class TestCiaEventFieldMap:
    def test_metadata(self):
        assert _event_map.TABLE == "cia_event"
        assert _event_map.CONFLICT == ("protocolo", "versao")

    def test_projects_all_typed_columns(self):
        typed, _raw = apply_map(IPE_ROW, _event_map.FIELD_MAP)
        assert typed["cd_cvm"] == "1023"
        assert typed["cnpj_cia"] == "00000000000191"
        assert typed["data_refer"] == datetime.date(2024, 2, 2)
        assert typed["data_entrega"] == datetime.date(2024, 2, 19)
        assert typed["categoria"] == "Assembleia"
        assert typed["tipo"] == "AGE"
        assert typed["especie"] == "Ata"
        assert typed["assunto"] is None      # empty string normalised to None
        assert typed["protocolo"] == "001023IPE020220240204533710-05"
        assert typed["versao"] == 2
        assert typed["link_download"].startswith("https://www.rad.cvm.gov.br/")

    def test_residual_unused_by_ingest(self):
        _typed, raw = apply_map(IPE_ROW, _event_map.FIELD_MAP)
        # Nome_Companhia and Tipo_Apresentacao are intentionally NOT mapped.
        # They should land in the residual — even though the ingest function
        # discards it (cia_event has no raw column).
        assert "Nome_Companhia" in raw
        assert "Tipo_Apresentacao" in raw


# ---------------------------------------------------------------------------
# Ingest unit tests — drop-row semantics and upsert call shape
# ---------------------------------------------------------------------------

@pytest.fixture
def captured_upserts():
    """Patch upsert_rows in ingest_cia and capture each call."""
    calls: list[dict] = []

    def _fake(client, table, rows, conflict_columns=None):
        calls.append({
            "table": table,
            "rows": rows,
            "conflict_columns": conflict_columns,
        })
        return len(rows)

    with patch("src.pipeline.ingest_cia.upsert_rows", side_effect=_fake):
        yield calls


class TestIngestCiaCompany:
    def test_happy_path(self, captured_upserts):
        n = ingest_cia_company(MagicMock(), [CAD_ROW])
        assert n == 1
        assert len(captured_upserts) == 1
        call = captured_upserts[0]
        assert call["table"] == "cia_company"
        assert call["conflict_columns"] == "cd_cvm"
        rec = call["rows"][0]
        assert rec["cd_cvm"] == "25224"
        assert rec["cnpj_cia"] == "08773135000100"
        assert "raw" in rec and isinstance(rec["raw"], dict)

    def test_drops_rows_without_cd_cvm(self, captured_upserts):
        bad = {**CAD_ROW, "CD_CVM": ""}
        n = ingest_cia_company(MagicMock(), [CAD_ROW, bad])
        assert n == 1                     # only the good row makes it through
        assert len(captured_upserts) == 1
        assert len(captured_upserts[0]["rows"]) == 1

    def test_empty_input_short_circuits(self, captured_upserts):
        assert ingest_cia_company(MagicMock(), []) == 0
        assert captured_upserts == []


class TestIngestCiaEvent:
    def test_happy_path(self, captured_upserts):
        n = ingest_cia_event(MagicMock(), [IPE_ROW])
        assert n == 1
        call = captured_upserts[0]
        assert call["table"] == "cia_event"
        assert call["conflict_columns"] == "protocolo,versao"
        rec = call["rows"][0]
        assert rec["protocolo"] == "001023IPE020220240204533710-05"
        assert rec["versao"] == 2
        # cia_event has NO raw column in the DDL — ingest must not emit one.
        assert "raw" not in rec

    def test_drops_rows_without_protocolo(self, captured_upserts):
        bad = {**IPE_ROW, "Protocolo_Entrega": ""}
        n = ingest_cia_event(MagicMock(), [bad])
        assert n == 0
        assert captured_upserts == []

    def test_drops_rows_without_versao(self, captured_upserts):
        bad = {**IPE_ROW, "Versao": ""}
        n = ingest_cia_event(MagicMock(), [bad])
        assert n == 0

    def test_drops_rows_without_cd_cvm(self, captured_upserts):
        bad = {**IPE_ROW, "Codigo_CVM": ""}
        n = ingest_cia_event(MagicMock(), [bad])
        assert n == 0


# ---------------------------------------------------------------------------
# Parametrised smoke test mirroring existing test_cvm_fetch_parse style
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "field_map_module,row,expected_pk_col,expected_pk_val",
    [
        (_company_map, CAD_ROW, "cd_cvm", "25224"),
        (_event_map, IPE_ROW, "protocolo", "001023IPE020220240204533710-05"),
    ],
)
def test_field_map_yields_primary_key(field_map_module, row, expected_pk_col, expected_pk_val):
    typed, _raw = apply_map(row, field_map_module.FIELD_MAP)
    assert typed[expected_pk_col] == expected_pk_val
