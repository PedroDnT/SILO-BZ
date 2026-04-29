"""
Unit tests for B3 CALC service — data format validation.

Mocks httpx so no network access is required. Verifies that each API
response format (JSON array, {data:[...]}, {lines:[...]}, {raw:...})
is correctly parsed into the expected Pydantic schema, and that the
sample-data fallback is triggered and correctly flagged.
"""

import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date

from src.b3_calc_api.services import B3CalcService
from src.b3_calc_api.config import SecurityType, SAMPLE_DEBENTURES, SAMPLE_CRAS, SAMPLE_CRIS


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _mock_response(json_data, status=200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


async def _make_service() -> B3CalcService:
    svc = B3CalcService()
    svc._client = MagicMock(spec=httpx.AsyncClient)
    return svc


# ─── Security type detection ──────────────────────────────────────────────────

class TestDetectSecurityType:
    def test_debenture_pattern(self):
        svc = B3CalcService()
        assert svc._detect_security_type("VALE12") == SecurityType.DEBENTURE
        assert svc._detect_security_type("PETR14") == SecurityType.DEBENTURE
        assert svc._detect_security_type("ABCD99") == SecurityType.DEBENTURE

    def test_cra_pattern(self):
        svc = B3CalcService()
        result = svc._detect_security_type("22A0001234-11")
        assert result in (SecurityType.CRA, SecurityType.CRI)

    def test_cri_pattern(self):
        svc = B3CalcService()
        result = svc._detect_security_type("22A0001111-20")
        assert result in (SecurityType.CRA, SecurityType.CRI)

    def test_unknown_pattern(self):
        svc = B3CalcService()
        assert svc._detect_security_type("UNKNOWN_CODE_XYZ") is None
        assert svc._detect_security_type("") is None


# ─── _parse_security_list response formats ────────────────────────────────────

class TestParseSecurityList:
    """Verify all four API response shapes produce valid SecurityInfo objects."""

    def _svc(self):
        return B3CalcService()

    def test_json_array_format(self):
        raw = [
            {"code": "VALE12", "name": "Vale Debenture", "issuer": "Vale S.A."},
            {"code": "PETR14", "name": "Petrobras Debenture"},
        ]
        result = self._svc()._parse_security_list(raw, SecurityType.DEBENTURE)
        assert len(result) == 2
        assert result[0].code == "VALE12"
        assert result[0].name == "Vale Debenture"
        assert result[0].security_type == "debentures"

    def test_data_key_format(self):
        raw = {"data": [{"code": "22A0001234-11", "name": "CRA Example"}]}
        result = self._svc()._parse_security_list(raw, SecurityType.CRA)
        assert len(result) == 1
        assert result[0].code == "22A0001234-11"
        assert result[0].security_type == "cra"

    def test_lines_key_format(self):
        raw = {"lines": ["VALE12;Vale Debenture", "PETR14;Petrobras", ""]}
        result = self._svc()._parse_security_list(raw, SecurityType.DEBENTURE)
        # empty lines are filtered
        assert len(result) == 2
        assert result[0].code == "VALE12"
        assert result[0].name == "Vale Debenture"

    def test_raw_key_format(self):
        raw = {"raw": "VALE12\nPETR14\n22A0001234-11"}
        result = self._svc()._parse_security_list(raw, SecurityType.DEBENTURE)
        assert len(result) == 3
        assert result[0].code == "VALE12"

    def test_empty_response(self):
        result = self._svc()._parse_security_list({}, SecurityType.DEBENTURE)
        assert result == []

    def test_securities_key_format(self):
        raw = {"securities": [{"code": "VALE12"}]}
        result = self._svc()._parse_security_list(raw, SecurityType.DEBENTURE)
        assert len(result) == 1
        assert result[0].code == "VALE12"


# ─── Sample data fallback ─────────────────────────────────────────────────────

class TestSampleDataFallback:
    """Verify fallback triggers on network errors and responses are correctly flagged."""

    @pytest.mark.asyncio
    async def test_list_securities_falls_back_on_network_error(self):
        svc = await _make_service()
        svc._client.get = AsyncMock(side_effect=httpx.NetworkError("unreachable"))

        result = await svc.list_securities(SecurityType.DEBENTURE)

        assert result.securities, "Should return sample securities"
        assert result.securities[0].code == SAMPLE_DEBENTURES[0]["code"]
        assert result.securities[0].security_type == "debentures"

    @pytest.mark.asyncio
    async def test_list_securities_falls_back_on_timeout(self):
        svc = await _make_service()
        svc._client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        result = await svc.list_securities(SecurityType.CRA)
        assert result.securities[0].code == SAMPLE_CRAS[0]["code"]

    @pytest.mark.asyncio
    async def test_get_price_falls_back_on_network_error(self):
        svc = await _make_service()
        svc._client.get = AsyncMock(side_effect=httpx.NetworkError("unreachable"))

        result = await svc.get_security_price("VALE12", SecurityType.DEBENTURE)

        assert result.code == "VALE12"
        assert result.price is not None
        raw = result.raw_response
        assert raw is not None and raw.get("_sample") is True, \
            "Sample price response must include _sample=True"

    @pytest.mark.asyncio
    async def test_sample_debenture_schema(self):
        """Sample data must satisfy SecurityInfo field types."""
        svc = await _make_service()
        svc._client.get = AsyncMock(side_effect=httpx.NetworkError("down"))

        result = await svc.list_securities(SecurityType.DEBENTURE)

        for sec in result.securities:
            assert isinstance(sec.code, str) and sec.code
            assert sec.security_type == "debentures"

    @pytest.mark.asyncio
    async def test_sample_cri_schema(self):
        svc = await _make_service()
        svc._client.get = AsyncMock(side_effect=httpx.NetworkError("down"))

        result = await svc.list_securities(SecurityType.CRI)
        assert result.securities[0].security_type == "cri"


# ─── Price response parsing ───────────────────────────────────────────────────

class TestParsePriceResponse:
    """Verify _parse_price_response maps API fields to PriceCalculationResult."""

    def test_pu_field_parsed(self):
        svc = B3CalcService()
        raw = {"pu": 1050.123456, "taxaRetorno": 12.5, "duration": 720.0, "dv01": 0.25}
        result = svc._parse_price_response(raw, "2024-01-15")
        assert result.pu == pytest.approx(1050.123456)
        assert result.settlement_date == "2024-01-15"

    def test_non_dict_returns_minimal(self):
        svc = B3CalcService()
        result = svc._parse_price_response("not a dict", "2024-01-01")
        assert result.settlement_date == "2024-01-01"
        assert result.pu is None

    def test_sample_price_schema(self):
        svc = B3CalcService()
        raw = svc._generate_sample_price("VALE12", SecurityType.DEBENTURE)
        assert raw["_sample"] is True
        assert isinstance(raw["pu"], float)
        assert isinstance(raw["taxaRetorno"], float)
        assert isinstance(raw["duration"], float)
        assert isinstance(raw["dv01"], float)
        # Settlement date matches today
        assert raw["dataLiquidacao"] == date.today().isoformat()


# ─── Indexes response ─────────────────────────────────────────────────────────

class TestIndexesResponse:
    @pytest.mark.asyncio
    async def test_indexes_live_response_parsed(self):
        """When API returns {CDI: {...}, SELIC: {...}, IPCA: {...}}, assemble IndexesResponse."""
        svc = await _make_service()
        mock_json = {
            "CDI": {"value": 11.15, "change": 0.0},
            "SELIC": {"value": 11.25, "change": 0.0},
            "IPCA": {"value": 4.5, "change": 0.0},
        }
        svc._client.get = AsyncMock(return_value=_mock_response(mock_json))

        result = await svc.get_indexes()

        assert hasattr(result, "indexes")
        assert hasattr(result, "reference_date")
        assert "CDI" in result.indexes
        assert result.indexes["CDI"]["value"] == pytest.approx(11.15)

    @pytest.mark.asyncio
    async def test_indexes_falls_back_on_error(self):
        svc = await _make_service()
        svc._client.get = AsyncMock(side_effect=httpx.NetworkError("down"))

        result = await svc.get_indexes()
        # Should return sample indexes without raising
        assert result is not None
        assert "CDI" in result.indexes
        assert "SELIC" in result.indexes
        assert "IPCA" in result.indexes
