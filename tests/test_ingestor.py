"""
Unit tests for src/ingestor/ — CVMIngestor, BacenIngestor, supabase_client helpers.

All Supabase and external HTTP calls are mocked so these run offline.
"""

import pytest
from typing import Any, Dict, List
from unittest.mock import MagicMock, AsyncMock, patch


# ---------------------------------------------------------------------------
# supabase_client helpers
# ---------------------------------------------------------------------------

class TestUpsertRows:
    """Tests for the supabase_client.upsert_rows chunking helper."""

    def _make_client(self, captured: list):
        """Build a mock Supabase client that records upserted rows."""
        mock_exec  = MagicMock(return_value=MagicMock())
        mock_upsert = MagicMock(return_value=MagicMock(execute=mock_exec))
        mock_table  = MagicMock(return_value=MagicMock(upsert=mock_upsert))
        client = MagicMock()
        client.table = mock_table

        # Track what was upserted
        def _capture_upsert(rows, **kwargs):
            captured.extend(rows)
            return MagicMock(execute=mock_exec)
        mock_table.return_value.upsert.side_effect = _capture_upsert
        return client

    def test_upsert_empty_rows_returns_zero(self):
        from src.ingestor.supabase_client import upsert_rows
        captured = []
        client = self._make_client(captured)
        assert upsert_rows(client, "test_table", []) == 0
        assert captured == []

    def test_upsert_small_batch_single_call(self):
        from src.ingestor.supabase_client import upsert_rows
        captured = []
        client = self._make_client(captured)
        rows = [{"id": i} for i in range(10)]
        result = upsert_rows(client, "test_table", rows)
        assert result == 10
        assert len(captured) == 10

    def test_upsert_large_batch_chunked(self):
        """Rows > 500 should be split into multiple upsert calls."""
        from src.ingestor.supabase_client import upsert_rows
        call_sizes: List[int] = []

        mock_exec = MagicMock(return_value=MagicMock())
        client = MagicMock()

        def _fake_upsert(rows, **kwargs):
            call_sizes.append(len(rows))
            return MagicMock(execute=mock_exec)

        client.table.return_value.upsert.side_effect = _fake_upsert

        rows = [{"id": i} for i in range(1100)]
        result = upsert_rows(client, "big_table", rows)

        assert result == 1100
        # Should be split: 500 + 500 + 100
        assert len(call_sizes) == 3
        assert call_sizes[0] == 500
        assert call_sizes[1] == 500
        assert call_sizes[2] == 100


# ---------------------------------------------------------------------------
# cvm_ingestor helpers
# ---------------------------------------------------------------------------

class TestCVMIngestorHelpers:
    """Tests for field extraction and CNPJ normalisation helpers."""

    def test_normalize_cnpj_strips_punctuation(self):
        from src.ingestor.cvm_ingestor import _normalize_cnpj
        assert _normalize_cnpj("12.345.678/0001-90") == "12345678000190"

    def test_normalize_cnpj_already_digits(self):
        from src.ingestor.cvm_ingestor import _normalize_cnpj
        assert _normalize_cnpj("12345678000190") == "12345678000190"

    def test_normalize_cnpj_empty_string(self):
        from src.ingestor.cvm_ingestor import _normalize_cnpj
        assert _normalize_cnpj("") == ""

    def test_find_field_first_match(self):
        from src.ingestor.cvm_ingestor import _find_field
        row = {"DENOM_SOCIAL": "FUNDO X", "NM_FUNDO": "FUNDO Y"}
        assert _find_field(row, "DENOM_SOCIAL", "NM_FUNDO") == "FUNDO X"

    def test_find_field_fallback_match(self):
        from src.ingestor.cvm_ingestor import _find_field
        row = {"NM_FUNDO": "FUNDO Y"}
        assert _find_field(row, "DENOM_SOCIAL", "NM_FUNDO") == "FUNDO Y"

    def test_find_field_none_when_missing(self):
        from src.ingestor.cvm_ingestor import _find_field
        row = {"OTHER": "value"}
        assert _find_field(row, "DENOM_SOCIAL") is None

    def test_find_field_empty_string_returns_none(self):
        from src.ingestor.cvm_ingestor import _find_field
        row = {"DENOM_SOCIAL": ""}
        assert _find_field(row, "DENOM_SOCIAL") is None

    def test_find_cnpj_field_prefers_fundo_suffix(self):
        from src.ingestor.cvm_ingestor import _find_cnpj_field
        row = {"CNPJ_SECURIT": "11111111000111", "CNPJ_FUNDO": "22222222000122"}
        assert _find_cnpj_field(row, prefer_suffix="fundo") == "22222222000122"

    def test_find_cnpj_field_fallback_any_cnpj(self):
        from src.ingestor.cvm_ingestor import _find_cnpj_field
        row = {"CNPJ_FUNDO": "12345678000190"}
        assert _find_cnpj_field(row, prefer_suffix="securit") == "12345678000190"

    def test_find_inadimpl_matches_inadimpl_key(self):
        from src.ingestor.cvm_ingestor import _find_inadimpl
        row = {"VL_INADIMPL": "5000.00", "VL_QUOTA": "100"}
        assert _find_inadimpl(row) == "5000.00"

    def test_find_inadimpl_returns_none_when_absent(self):
        from src.ingestor.cvm_ingestor import _find_inadimpl
        row = {"VL_QUOTA": "100", "VL_PATRIM_LIQ": "1000000"}
        assert _find_inadimpl(row) is None


# ---------------------------------------------------------------------------
# CVMIngestor — ingest_cadastral (mocked service + Supabase)
# ---------------------------------------------------------------------------

class TestCVMIngestorCadastral:
    """Smoke tests for CVMIngestor.ingest_cadastral with mocked dependencies."""

    def _make_data_response(self, rows: List[Dict], has_next: bool = False):
        from src.cvm_api.models import DataResponse, PaginationInfo
        return DataResponse(
            entity="fidc",
            doc_type="cadastral",
            data=rows,
            pagination=PaginationInfo(
                page=1,
                page_size=len(rows),
                total_items=len(rows),
                total_pages=1,
                has_next=has_next,
                has_previous=False,
            ),
        )

    @pytest.mark.asyncio
    async def test_ingest_cadastral_basic(self):
        from src.ingestor.cvm_ingestor import CVMIngestor

        sample_rows = [
            {
                "CNPJ_FUNDO": "12.345.678/0001-90",
                "DENOM_SOCIAL": "FUNDO EXEMPLO",
                "DT_REG": "2020-01-15",
                "DT_CANCEL": "",
                "SIT": "ATIVO",
                "TP_FUNDO": "FIDC",
            }
        ]
        mock_resp = self._make_data_response(sample_rows)

        upserted: List[Dict] = []
        mock_supabase = MagicMock()
        mock_supabase.table.return_value.upsert.side_effect = (
            lambda rows, **kw: (upserted.extend(rows), MagicMock(execute=MagicMock()))[-1]
        )

        with patch("src.ingestor.cvm_ingestor.CVMCreditDataService") as mock_svc_cls, \
             patch("src.ingestor.cvm_ingestor.get_supabase_client", return_value=mock_supabase):
            mock_svc = mock_svc_cls.return_value
            mock_svc.get_data = AsyncMock(return_value=mock_resp)

            ingestor = CVMIngestor()
            count = await ingestor.ingest_cadastral("fidc", 2024)

        assert count == 1
        assert len(upserted) == 1
        row = upserted[0]
        assert row["entity"] == "fidc"
        assert row["year"] == 2024
        assert row["cnpj"] == "12345678000190"
        assert row["denom_social"] == "FUNDO EXEMPLO"
        assert row["sit"] == "ATIVO"
        assert "raw" in row

    @pytest.mark.asyncio
    async def test_ingest_cadastral_empty_response_returns_zero(self):
        from src.ingestor.cvm_ingestor import CVMIngestor
        from src.cvm_api.models import DataResponse, PaginationInfo

        # Empty data — use page_size=1 to satisfy Pydantic ge=1 constraint
        mock_resp = DataResponse(
            entity="fidc", doc_type="cadastral", data=[],
            pagination=PaginationInfo(
                page=1, page_size=1, total_items=0,
                total_pages=0, has_next=False, has_previous=False,
            ),
        )
        mock_supabase = MagicMock()

        with patch("src.ingestor.cvm_ingestor.CVMCreditDataService") as mock_svc_cls, \
             patch("src.ingestor.cvm_ingestor.get_supabase_client", return_value=mock_supabase):
            mock_svc = mock_svc_cls.return_value
            mock_svc.get_data = AsyncMock(return_value=mock_resp)
            ingestor = CVMIngestor()
            count = await ingestor.ingest_cadastral("fidc", 2024)

        assert count == 0

    @pytest.mark.asyncio
    async def test_ingest_cadastral_network_error_returns_zero(self):
        from src.ingestor.cvm_ingestor import CVMIngestor

        mock_supabase = MagicMock()

        with patch("src.ingestor.cvm_ingestor.CVMCreditDataService") as mock_svc_cls, \
             patch("src.ingestor.cvm_ingestor.get_supabase_client", return_value=mock_supabase):
            mock_svc = mock_svc_cls.return_value
            mock_svc.get_data = AsyncMock(side_effect=Exception("Network error"))
            ingestor = CVMIngestor()
            count = await ingestor.ingest_cadastral("fidc", 2024)

        assert count == 0


# ---------------------------------------------------------------------------
# CVMIngestor — ingest_mensal
# ---------------------------------------------------------------------------

class TestCVMIngestorMensal:
    def _make_mensal_response(self, rows: List[Dict]):
        from src.cvm_api.models import DataResponse, PaginationInfo
        return DataResponse(
            entity="fidc",
            doc_type="mensal",
            data=rows,
            pagination=PaginationInfo(
                page=1, page_size=len(rows), total_items=len(rows),
                total_pages=1, has_next=False, has_previous=False,
            ),
        )

    @pytest.mark.asyncio
    async def test_ingest_mensal_extracts_financial_fields(self):
        from src.ingestor.cvm_ingestor import CVMIngestor

        rows = [
            {
                "CNPJ_FUNDO": "12345678000190",
                "DT_COMPTC": "2024-01-31",
                "VL_TOTAL": "5000000.00",
                "VL_QUOTA": "1234.56",
                "VL_PATRIM_LIQ": "4900000.00",
                "VL_INADIMPL": "50000.00",
                "NR_COTST": "42",
            }
        ]
        mock_resp = self._make_mensal_response(rows)
        upserted: List[Dict] = []
        mock_supabase = MagicMock()
        mock_supabase.table.return_value.upsert.side_effect = (
            lambda r, **kw: (upserted.extend(r), MagicMock(execute=MagicMock()))[-1]
        )

        with patch("src.ingestor.cvm_ingestor.CVMCreditDataService") as mock_svc_cls, \
             patch("src.ingestor.cvm_ingestor.get_supabase_client", return_value=mock_supabase):
            mock_svc = mock_svc_cls.return_value
            mock_svc.get_data = AsyncMock(return_value=mock_resp)
            ingestor = CVMIngestor()
            count = await ingestor.ingest_mensal("fidc", 2024, 1)

        assert count == 1
        row = upserted[0]
        assert row["cnpj"] == "12345678000190"
        assert row["period"] == "2024-01-31"
        assert row["vl_total"] == "5000000.00"
        assert row["vl_quota"] == "1234.56"
        assert row["vl_inadimpl"] == "50000.00"


# ---------------------------------------------------------------------------
# BacenIngestor — ingest_sgs
# ---------------------------------------------------------------------------

class TestBacenIngestorSGS:
    @pytest.mark.asyncio
    async def test_ingest_sgs_flattens_multi_series(self):
        from src.ingestor.bacen_ingestor import BacenIngestor

        # BacenClient returns one record per date with all series as columns
        mock_records = [
            {
                "date": "2024-01-31",
                "SELIC_META": 11.75,
                "CDI": 11.65,
                "IPCA": 4.51,
                # Other series absent from this record — should be skipped
            }
        ]
        upserted: List[Dict] = []
        mock_supabase = MagicMock()
        mock_supabase.table.return_value.upsert.side_effect = (
            lambda r, **kw: (upserted.extend(r), MagicMock(execute=MagicMock()))[-1]
        )

        with patch("src.ingestor.bacen_ingestor.BacenClient") as mock_client_cls, \
             patch("src.ingestor.bacen_ingestor.get_supabase_client", return_value=mock_supabase):
            mock_client = mock_client_cls.return_value
            mock_client.get_sgs_series = AsyncMock(return_value=mock_records)
            ingestor = BacenIngestor()
            count = await ingestor.ingest_sgs("2024-01-01", "2024-01-31")

        # 3 series present in mock record → 3 rows
        assert count == 3
        codes_seen = {r["series_name"] for r in upserted}
        assert codes_seen == {"SELIC_META", "CDI", "IPCA"}
        selic_row = next(r for r in upserted if r["series_name"] == "SELIC_META")
        assert selic_row["reference_date"] == "2024-01-31"
        assert selic_row["value"] == pytest.approx(11.75)

    @pytest.mark.asyncio
    async def test_ingest_sgs_empty_response_returns_zero(self):
        from src.ingestor.bacen_ingestor import BacenIngestor

        mock_supabase = MagicMock()
        with patch("src.ingestor.bacen_ingestor.BacenClient") as mock_client_cls, \
             patch("src.ingestor.bacen_ingestor.get_supabase_client", return_value=mock_supabase):
            mock_client = mock_client_cls.return_value
            mock_client.get_sgs_series = AsyncMock(return_value=[])
            ingestor = BacenIngestor()
            count = await ingestor.ingest_sgs("2024-01-01")

        assert count == 0

    @pytest.mark.asyncio
    async def test_ingest_sgs_fetch_error_returns_zero(self):
        from src.ingestor.bacen_ingestor import BacenIngestor

        mock_supabase = MagicMock()
        with patch("src.ingestor.bacen_ingestor.BacenClient") as mock_client_cls, \
             patch("src.ingestor.bacen_ingestor.get_supabase_client", return_value=mock_supabase):
            mock_client = mock_client_cls.return_value
            mock_client.get_sgs_series = AsyncMock(side_effect=Exception("BCB unreachable"))
            ingestor = BacenIngestor()
            count = await ingestor.ingest_sgs("2024-01-01")

        assert count == 0


# ---------------------------------------------------------------------------
# BacenIngestor — ingest_ptax
# ---------------------------------------------------------------------------

class TestBacenIngestorPTAX:
    @pytest.mark.asyncio
    async def test_ingest_ptax_usd_maps_rates(self):
        from src.ingestor.bacen_ingestor import BacenIngestor

        mock_records = [
            {"date": "2024-01-31", "cotacaoCompra": 4.9765, "cotacaoVenda": 4.9770}
        ]
        upserted: List[Dict] = []
        mock_supabase = MagicMock()
        mock_supabase.table.return_value.upsert.side_effect = (
            lambda r, **kw: (upserted.extend(r), MagicMock(execute=MagicMock()))[-1]
        )

        with patch("src.ingestor.bacen_ingestor.BacenClient") as mock_client_cls, \
             patch("src.ingestor.bacen_ingestor.get_supabase_client", return_value=mock_supabase), \
             patch("src.ingestor.bacen_ingestor.PTAX_CURRENCIES", ["USD"]):
            mock_client = mock_client_cls.return_value
            mock_client.get_ptax_dolar_periodo = AsyncMock(return_value=mock_records)
            ingestor = BacenIngestor()
            count = await ingestor.ingest_ptax("2024-01-01", "2024-01-31")

        assert count == 1
        row = upserted[0]
        assert row["currency"] == "USD"
        assert row["buy_rate"] == pytest.approx(4.9765)
        assert row["sell_rate"] == pytest.approx(4.9770)
