"""
Unit tests for BACEN data pipeline — data format validation.

Mocks asyncio.to_thread (used by BacenClient) to return canned DataFrames.
Verifies that NaN→None, Timestamps→ISO strings, numpy types→native Python,
and that assembled response models have correct field types.
"""

import pytest
import numpy as np
import pandas as pd
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

from src.clients.bacen_client import _df_to_records, BacenClient
from src.bacen_api.services import BacenService
from src.bacen_api.config import WELL_KNOWN_SGS, EXPECTATIVAS_ENDPOINTS


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_sgs_dataframe():
    """Single-series SGS DataFrame with a DatetimeIndex."""
    idx = pd.DatetimeIndex(["2024-01-01", "2024-02-01", "2024-03-01"], name="Date")
    return pd.DataFrame({"IPCA": [0.42, 0.83, np.nan]}, index=idx)


@pytest.fixture
def sample_multi_sgs_dataframe():
    """Multi-series SGS DataFrame."""
    idx = pd.DatetimeIndex(["2024-01-01", "2024-02-01"], name="Date")
    return pd.DataFrame({"IPCA": [0.42, 0.83], "CDI": [10.5, 10.5]}, index=idx)


@pytest.fixture
def sample_ptax_dataframe():
    """PTAX DataFrame as returned by python-bcb."""
    idx = pd.DatetimeIndex(["2024-01-31"], name="DateTime")
    return pd.DataFrame(
        {"cotacaoCompra": [5.01], "cotacaoVenda": [5.02]}, index=idx
    )


@pytest.fixture
def sample_expectativas_dataframe():
    """Expectativas DataFrame."""
    idx = pd.RangeIndex(2)
    return pd.DataFrame(
        {
            "Indicador": ["IPCA", "IPCA"],
            "Data": ["2024-01-26", "2024-02-02"],
            "Mediana": [3.9, 4.0],
            "Media": [3.88, 3.99],
            "DesvioPadrao": [0.12, np.nan],
        },
        index=idx,
    )


# ─── _df_to_records helper ────────────────────────────────────────────────────

class TestDfToRecords:
    """Verify the DataFrame→dict conversion rules."""

    def test_nan_becomes_none(self, sample_sgs_dataframe):
        records = _df_to_records(sample_sgs_dataframe)
        assert len(records) == 3
        # Third row has NaN → None
        assert records[2]["IPCA"] is None

    def test_timestamp_becomes_iso_string(self, sample_sgs_dataframe):
        records = _df_to_records(sample_sgs_dataframe)
        date_val = records[0]["Date"]
        assert isinstance(date_val, str)
        assert date_val.startswith("2024-01-01")

    def test_numpy_float_becomes_python_float(self, sample_sgs_dataframe):
        records = _df_to_records(sample_sgs_dataframe)
        val = records[0]["IPCA"]
        assert isinstance(val, float)
        assert not isinstance(val, np.floating)

    def test_empty_dataframe_returns_empty_list(self):
        result = _df_to_records(pd.DataFrame())
        assert result == []

    def test_none_dataframe_returns_empty_list(self):
        result = _df_to_records(None)
        assert result == []

    def test_multi_series_all_columns_preserved(self, sample_multi_sgs_dataframe):
        records = _df_to_records(sample_multi_sgs_dataframe)
        assert "IPCA" in records[0]
        assert "CDI" in records[0]
        assert isinstance(records[0]["IPCA"], float)
        assert isinstance(records[0]["CDI"], float)

    def test_numpy_integer_becomes_python_int(self):
        df = pd.DataFrame({"count": pd.array([1, 2, 3], dtype="int64")})
        records = _df_to_records(df)
        assert isinstance(records[0]["count"], int)
        assert not isinstance(records[0]["count"], np.integer)

    def test_expectativas_nan_in_std_dev(self, sample_expectativas_dataframe):
        records = _df_to_records(sample_expectativas_dataframe)
        assert records[0]["DesvioPadrao"] == pytest.approx(0.12)
        assert records[1]["DesvioPadrao"] is None


# ─── BacenService response assembly ──────────────────────────────────────────

class TestBacenServiceSGS:
    @pytest.mark.asyncio
    async def test_get_sgs_series_response_schema(self, sample_sgs_dataframe):
        """SGSSeriesResponse must have correct field types after assembly."""
        svc = BacenService()
        with patch.object(
            svc._client, "get_sgs_series", new=AsyncMock(return_value=_df_to_records(sample_sgs_dataframe))
        ):
            result = await svc.get_sgs_series(series_code=433, label="IPCA")

        assert result.series_code == 433
        assert result.series_label == "IPCA"
        assert result.total_records == 3
        assert len(result.data) == 3
        # date field is ISO string
        assert isinstance(result.data[0]["Date"], str)
        # NaN converted to None
        assert result.data[2]["IPCA"] is None
        # timestamp is UTC ISO string
        assert "T" in result.timestamp

    @pytest.mark.asyncio
    async def test_get_sgs_multi_parses_codes_string(self, sample_multi_sgs_dataframe):
        svc = BacenService()
        with patch.object(
            svc._client, "get_sgs_series",
            new=AsyncMock(return_value=_df_to_records(sample_multi_sgs_dataframe))
        ):
            result = await svc.get_sgs_multi("IPCA:433,CDI:12")

        assert result.codes == {"IPCA": 433, "CDI": 12}
        assert result.total_records == 2

    @pytest.mark.asyncio
    async def test_get_sgs_multi_raises_on_bad_pair(self):
        svc = BacenService()
        with pytest.raises(ValueError, match="LABEL:CODE"):
            await svc.get_sgs_multi("IPCA433")

    def test_get_well_known_series(self):
        svc = BacenService()
        result = svc.get_well_known_series()
        assert result.series == WELL_KNOWN_SGS
        assert len(result.series) > 0
        # All values are ints (series codes)
        for label, code in result.series.items():
            assert isinstance(code, int)


class TestBacenServicePTAX:
    @pytest.mark.asyncio
    async def test_ptax_dolar_response_schema(self, sample_ptax_dataframe):
        svc = BacenService()
        records = _df_to_records(sample_ptax_dataframe)
        with patch.object(svc._client, "get_ptax_dolar_dia", new=AsyncMock(return_value=records)):
            result = await svc.get_ptax_dolar("2024-01-31")

        assert result.query_type == "CotacaoDolarDia"
        assert result.total_records == 1
        assert len(result.data) == 1
        # bid/ask are floats
        row = result.data[0]
        assert isinstance(row["cotacaoCompra"], float)
        assert isinstance(row["cotacaoVenda"], float)

    @pytest.mark.asyncio
    async def test_ptax_moeda_adds_currency_code(self, sample_ptax_dataframe):
        svc = BacenService()
        records = _df_to_records(sample_ptax_dataframe)
        with patch.object(svc._client, "get_ptax_moeda_dia", new=AsyncMock(return_value=records)):
            result = await svc.get_ptax_moeda("EUR", "2024-01-31")

        assert result.moeda == "EUR"
        assert result.query_type == "CotacaoMoedaDia"


class TestBacenServiceExpectativas:
    def test_list_expectativas(self):
        svc = BacenService()
        result = svc.list_expectativas()
        assert result.endpoints == EXPECTATIVAS_ENDPOINTS
        assert len(result.endpoints) > 0

    @pytest.mark.asyncio
    async def test_get_expectativas_response_schema(self, sample_expectativas_dataframe):
        svc = BacenService()
        records = _df_to_records(sample_expectativas_dataframe)
        with patch.object(svc._client, "get_expectativas", new=AsyncMock(return_value=records)):
            result = await svc.get_expectativas(
                endpoint_name=EXPECTATIVAS_ENDPOINTS[0],
                indicador="IPCA",
            )

        assert result.endpoint == EXPECTATIVAS_ENDPOINTS[0]
        assert result.indicador == "IPCA"
        assert result.total_records == 2
        # NaN in DesvioPadrao becomes None
        assert result.data[0]["DesvioPadrao"] == pytest.approx(0.12)
        assert result.data[1]["DesvioPadrao"] is None

    @pytest.mark.asyncio
    async def test_get_expectativas_rejects_unknown_endpoint(self):
        svc = BacenService()
        with pytest.raises(ValueError, match="Unknown endpoint"):
            await svc.get_expectativas("NonExistentEndpoint")
