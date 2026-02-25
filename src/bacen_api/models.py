"""
Pydantic models for the BACEN API service.
All models use Pydantic v2 syntax (model_config = ConfigDict(...)).
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Generic ──────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = Field(..., description="Service health status")
    timestamp: str = Field(..., description="Current UTC timestamp")
    version: str = Field(..., description="API version")


class ErrorResponse(BaseModel):
    error: str = Field(..., description="Error message")
    status_code: int = Field(..., description="HTTP status code")
    timestamp: str = Field(..., description="Error timestamp")


# ─── SGS ──────────────────────────────────────────────────────────────────────

class SGSDataPoint(BaseModel):
    """Single observation from an SGS time series."""
    model_config = ConfigDict(extra="allow")

    date: Optional[str] = Field(None, description="Observation date (ISO format)")


class SGSSeriesResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "series_code": 433,
                "series_label": "IPCA",
                "total_records": 3,
                "data": [
                    {"date": "2024-01-01", "IPCA": 0.42},
                    {"date": "2024-02-01", "IPCA": 0.83},
                    {"date": "2024-03-01", "IPCA": 0.16},
                ],
                "timestamp": "2024-06-01T00:00:00",
            }
        }
    )

    series_code: Optional[int] = Field(None, description="SGS series code")
    series_label: Optional[str] = Field(None, description="Series label / name")
    codes: Optional[Dict[str, int]] = Field(
        None, description="All series codes when fetching multiple series"
    )
    total_records: int = Field(..., description="Number of data points returned")
    data: List[Dict[str, Any]] = Field(..., description="Observation list")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Response timestamp",
    )


class WellKnownSeriesResponse(BaseModel):
    """List of well-known SGS series codes."""
    series: Dict[str, int] = Field(..., description="Label → code mapping")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Response timestamp",
    )


# ─── PTAX ─────────────────────────────────────────────────────────────────────

class PTAXRateResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query_type": "CotacaoDolarDia",
                "total_records": 1,
                "data": [{"cotacaoCompra": 5.01, "cotacaoVenda": 5.02, "dataHoraCotacao": "2024-01-31T13:11:10.577"}],
                "timestamp": "2024-06-01T00:00:00",
            }
        }
    )

    query_type: str = Field(..., description="PTAX endpoint used")
    moeda: Optional[str] = Field(None, description="Currency code (if not USD)")
    total_records: int = Field(..., description="Number of records returned")
    data: List[Dict[str, Any]] = Field(..., description="Rate data")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Response timestamp",
    )


class PTAXMoedasResponse(BaseModel):
    """List of all currencies available in PTAX."""
    total_records: int = Field(..., description="Number of currencies")
    currencies: List[Dict[str, Any]] = Field(..., description="Currency metadata")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Response timestamp",
    )


# ─── Expectativas ─────────────────────────────────────────────────────────────

class ExpectativasResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "endpoint": "ExpectativasMercadoAnuais",
                "indicador": "IPCA",
                "total_records": 5,
                "data": [],
                "timestamp": "2024-06-01T00:00:00",
            }
        }
    )

    endpoint: str = Field(..., description="Expectativas endpoint queried")
    indicador: Optional[str] = Field(None, description="Indicator filter applied")
    start_date: Optional[str] = Field(None, description="Start date filter applied")
    total_records: int = Field(..., description="Number of records returned")
    data: List[Dict[str, Any]] = Field(..., description="Expectation data")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Response timestamp",
    )


class AvailableExpectativasResponse(BaseModel):
    """List of available Expectativas endpoint names."""
    endpoints: List[str] = Field(..., description="Available endpoint names")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Response timestamp",
    )


# ─── TaxaJuros ────────────────────────────────────────────────────────────────

class TaxaJurosResponse(BaseModel):
    endpoint: str = Field(..., description="TaxaJuros endpoint queried")
    total_records: int = Field(..., description="Number of records returned")
    data: List[Dict[str, Any]] = Field(..., description="Interest-rate data")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Response timestamp",
    )
