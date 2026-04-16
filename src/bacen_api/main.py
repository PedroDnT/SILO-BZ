"""
BACEN FastAPI application.

Endpoints:
  GET /health
  GET /api/v1/bacen/sgs/well-known                         — list well-known series
  GET /api/v1/bacen/sgs/{series_code}                      — single SGS series
  GET /api/v1/bacen/sgs/multi                              — multiple SGS series
  GET /api/v1/bacen/ptax/dolar                             — USD/BRL for a date
  GET /api/v1/bacen/ptax/dolar/periodo                     — USD/BRL date range
  GET /api/v1/bacen/ptax/moeda/{moeda}                     — any currency/date
  GET /api/v1/bacen/ptax/moeda/{moeda}/periodo             — any currency range
  GET /api/v1/bacen/ptax/moedas                            — list all PTAX currencies
  GET /api/v1/bacen/expectativas                           — list available endpoints
  GET /api/v1/bacen/expectativas/{endpoint_name}           — query expectations
  GET /api/v1/bacen/taxas_juros/{endpoint_name}            — query interest rates

Run:
  uvicorn src.bacen_api.main:app --host 0.0.0.0 --port 8002 --reload
"""

import os
from contextlib import asynccontextmanager
from datetime import datetime, date, timezone
from typing import Optional
import logging

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

if __package__:
    from .config import (
        API_TITLE, API_VERSION, API_DESCRIPTION,
        WELL_KNOWN_SGS, EXPECTATIVAS_ENDPOINTS,
    )
    from .models import (
        HealthResponse, ErrorResponse,
        SGSSeriesResponse, WellKnownSeriesResponse,
        PTAXRateResponse, PTAXMoedasResponse,
        ExpectativasResponse, AvailableExpectativasResponse,
        TaxaJurosResponse,
    )
    from ..clients.bacen_client import BacenClient
else:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
    from src.bacen_api.config import (
        API_TITLE, API_VERSION, API_DESCRIPTION,
        WELL_KNOWN_SGS, EXPECTATIVAS_ENDPOINTS,
    )
    from src.bacen_api.models import (
        HealthResponse, ErrorResponse,
        SGSSeriesResponse, WellKnownSeriesResponse,
        PTAXRateResponse, PTAXMoedasResponse,
        ExpectativasResponse, AvailableExpectativasResponse,
        TaxaJurosResponse,
    )
    from src.clients.bacen_client import BacenClient

logger = logging.getLogger(__name__)

# Lazy DB import: engine disposal only if DB is configured
_db_engine = None
try:
    if __package__:
        from .db import engine as _db_engine
    else:
        from db import engine as _db_engine
except KeyError:
    # DATABASE_URL not set — running without DB (local dev without postgres)
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "DATABASE_URL not set — DB engine not initialized. "
        "Set BACEN_DATABASE_URL env var to enable database connectivity."
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup: engine created at module load, nothing to do here
    yield
    # shutdown: dispose engine to close all pool connections cleanly
    if _db_engine is not None:
        await _db_engine.dispose()


app = FastAPI(
    title=API_TITLE,
    version=API_VERSION,
    description=API_DESCRIPTION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting configuration
def get_rate_limit_key(request: Request) -> str:
    """Get rate limit key from request - supports X-Forwarded-For for proxied requests"""
    return get_remote_address(request)

rate_limit_enabled = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
rate_limit_requests = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
rate_limit_window = int(os.getenv("RATE_LIMIT_WINDOW", "60"))

limiter = Limiter(key_func=get_rate_limit_key)
app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Handle rate limit exceeded errors"""
    return JSONResponse(
        status_code=429,
        content={
            "error": "Rate limit exceeded",
            "status_code": 429,
            "detail": str(exc.detail),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    )

_client = BacenClient()


# ─── Exception handlers ───────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def generic_exception_handler(request, exc):
    logger.error("Unhandled error: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error=str(exc),
            status_code=500,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ).model_dump(),
    )


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health():
    """Service health check."""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now(timezone.utc).isoformat(),
        version=API_VERSION,
    )


# ─── SGS ──────────────────────────────────────────────────────────────────────

@app.get(
    "/api/v1/bacen/sgs/well-known",
    response_model=WellKnownSeriesResponse,
    tags=["SGS"],
    summary="List well-known SGS series codes",
)
@limiter.limit(f"{rate_limit_requests}/{rate_limit_window} seconds" if rate_limit_enabled else "1000/minute")
async def list_well_known_sgs(request: Request):
    """Return a dictionary of well-known SGS series labels and their codes."""
    return WellKnownSeriesResponse(
        series=WELL_KNOWN_SGS,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get(
    "/api/v1/bacen/sgs/{series_code}",
    response_model=SGSSeriesResponse,
    tags=["SGS"],
    summary="Fetch a single SGS time series",
)
@limiter.limit(f"{rate_limit_requests}/{rate_limit_window} seconds" if rate_limit_enabled else "1000/minute")
async def get_sgs_series(request: Request,
    series_code: int,
    label: str = Query("value", description="Column label for the series"),
    start: Optional[str] = Query(None, description="Start date ISO YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="End date ISO YYYY-MM-DD"),
    last: Optional[int] = Query(None, ge=1, le=5000, description="Return last N observations"),
):
    """
    Fetch a single BCB/SGS time series by its numeric code.

    Popular codes: SELIC=11, CDI=12, IPCA=433, IGP-M=189, USD/BRL=1.
    """
    try:
        data = await _client.get_sgs_series(
            codes={label: series_code},
            start=start,
            end=end,
            last=last,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"BCB SGS error: {exc}") from exc

    return SGSSeriesResponse(
        series_code=series_code,
        series_label=label,
        total_records=len(data),
        data=data,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get(
    "/api/v1/bacen/sgs/multi",
    response_model=SGSSeriesResponse,
    tags=["SGS"],
    summary="Fetch multiple SGS time series in one request",
)
@limiter.limit(f"{rate_limit_requests}/{rate_limit_window} seconds" if rate_limit_enabled else "1000/minute")
async def get_sgs_multi(request: Request,
    codes: str = Query(
        ...,
        description=(
            'Comma-separated label:code pairs. '
            'Example: "IPCA:433,CDI:12,SELIC:11"'
        ),
    ),
    start: Optional[str] = Query(None, description="Start date ISO YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="End date ISO YYYY-MM-DD"),
    last: Optional[int] = Query(None, ge=1, le=5000, description="Return last N observations"),
):
    """
    Fetch multiple SGS series in a single call. Returns aligned DataFrame (rows = dates).
    """
    try:
        codes_dict: dict[str, int] = {}
        for pair in codes.split(","):
            pair = pair.strip()
            if ":" not in pair:
                raise ValueError(f"Invalid pair '{pair}'. Use 'LABEL:CODE'.")
            lbl, code_str = pair.split(":", 1)
            codes_dict[lbl.strip()] = int(code_str.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        data = await _client.get_sgs_series(
            codes=codes_dict, start=start, end=end, last=last
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"BCB SGS error: {exc}") from exc

    return SGSSeriesResponse(
        codes=codes_dict,
        total_records=len(data),
        data=data,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ─── PTAX ─────────────────────────────────────────────────────────────────────

@app.get(
    "/api/v1/bacen/ptax/dolar",
    response_model=PTAXRateResponse,
    tags=["PTAX"],
    summary="USD/BRL PTAX closing rate for a specific date",
)
@limiter.limit(f"{rate_limit_requests}/{rate_limit_window} seconds" if rate_limit_enabled else "1000/minute")
async def ptax_dolar_dia(request: Request,
    date: str = Query(..., description="Date ISO YYYY-MM-DD"),
):
    """Return the USD/BRL PTAX closing rate (compra/venda) for the given date."""
    try:
        data = await _client.get_ptax_dolar_dia(date)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"PTAX error: {exc}") from exc

    return PTAXRateResponse(
        query_type="CotacaoDolarDia",
        total_records=len(data),
        data=data,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get(
    "/api/v1/bacen/ptax/dolar/periodo",
    response_model=PTAXRateResponse,
    tags=["PTAX"],
    summary="USD/BRL PTAX closing rates for a date range",
)
@limiter.limit(f"{rate_limit_requests}/{rate_limit_window} seconds" if rate_limit_enabled else "1000/minute")
async def ptax_dolar_periodo(request: Request,
    start: str = Query(..., description="Start date ISO YYYY-MM-DD"),
    end: str = Query(..., description="End date ISO YYYY-MM-DD"),
):
    """Return daily USD/BRL PTAX rates for [start, end] inclusive."""
    try:
        data = await _client.get_ptax_dolar_periodo(start, end)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"PTAX error: {exc}") from exc

    return PTAXRateResponse(
        query_type="CotacaoDolarPeriodo",
        total_records=len(data),
        data=data,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get(
    "/api/v1/bacen/ptax/moeda/{moeda}",
    response_model=PTAXRateResponse,
    tags=["PTAX"],
    summary="Exchange rate vs BRL for a specific currency and date",
)
async def ptax_moeda_dia(
    moeda: str,
    date: str = Query(..., description="Date ISO YYYY-MM-DD"),
):
    """Return the PTAX closing rate for {moeda}/BRL on the given date."""
    try:
        data = await _client.get_ptax_moeda_dia(moeda.upper(), date)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"PTAX error: {exc}") from exc

    return PTAXRateResponse(
        query_type="CotacaoMoedaDia",
        moeda=moeda.upper(),
        total_records=len(data),
        data=data,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get(
    "/api/v1/bacen/ptax/moeda/{moeda}/periodo",
    response_model=PTAXRateResponse,
    tags=["PTAX"],
    summary="Exchange rate vs BRL for a specific currency and date range",
)
async def ptax_moeda_periodo(
    moeda: str,
    start: str = Query(..., description="Start date ISO YYYY-MM-DD"),
    end: str = Query(..., description="End date ISO YYYY-MM-DD"),
):
    """Return daily {moeda}/BRL PTAX rates for [start, end] inclusive."""
    try:
        data = await _client.get_ptax_moeda_periodo(moeda.upper(), start, end)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"PTAX error: {exc}") from exc

    return PTAXRateResponse(
        query_type="CotacaoMoedaPeriodo",
        moeda=moeda.upper(),
        total_records=len(data),
        data=data,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get(
    "/api/v1/bacen/ptax/moedas",
    response_model=PTAXMoedasResponse,
    tags=["PTAX"],
    summary="List all currencies available in PTAX",
)
async def ptax_moedas():
    """Return the full list of currencies available in the PTAX system."""
    try:
        data = await _client.get_ptax_moedas()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"PTAX error: {exc}") from exc

    return PTAXMoedasResponse(
        total_records=len(data),
        currencies=data,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ─── Expectativas ─────────────────────────────────────────────────────────────

@app.get(
    "/api/v1/bacen/expectativas",
    response_model=AvailableExpectativasResponse,
    tags=["Expectativas"],
    summary="List available market expectations endpoints",
)
async def list_expectativas():
    """List all Expectativas (Focus/RDMercado) endpoint names that can be queried."""
    return AvailableExpectativasResponse(
        endpoints=EXPECTATIVAS_ENDPOINTS,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get(
    "/api/v1/bacen/expectativas/{endpoint_name}",
    response_model=ExpectativasResponse,
    tags=["Expectativas"],
    summary="Query BACEN market expectations (Focus bulletin)",
)
async def get_expectativas(
    endpoint_name: str,
    indicador: Optional[str] = Query(None, description="Filter by indicator (e.g. IPCA, Selic)"),
    start: Optional[str] = Query(None, description="Filter Data >= this ISO date"),
    limit: int = Query(100, ge=1, le=1000, description="Max rows to return"),
):
    """
    Query one of the Focus/RDMercado expectation datasets.

    Common indicators: IPCA, IGP-M, Selic, PIB Total, Câmbio.
    """
    if endpoint_name not in EXPECTATIVAS_ENDPOINTS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown endpoint '{endpoint_name}'. "
                   f"Valid options: {EXPECTATIVAS_ENDPOINTS}",
        )

    try:
        data = await _client.get_expectativas(
            endpoint_name=endpoint_name,
            indicador=indicador,
            start=start,
            limit=limit,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Expectativas error: {exc}") from exc

    return ExpectativasResponse(
        endpoint=endpoint_name,
        indicador=indicador,
        start_date=start,
        total_records=len(data),
        data=data,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ─── TaxaJuros ────────────────────────────────────────────────────────────────

@app.get(
    "/api/v1/bacen/taxas_juros/{endpoint_name}",
    response_model=TaxaJurosResponse,
    tags=["TaxaJuros"],
    summary="Query BACEN interest-rate data",
)
async def get_taxas_juros(
    endpoint_name: str = "TaxasJurosMercadoImobiliario",
    limit: int = Query(100, ge=1, le=1000, description="Max rows to return"),
):
    """Query BACEN TaxaJuros OData API (e.g. mortgage interest rates by institution)."""
    try:
        data = await _client.get_taxas_juros(endpoint_name=endpoint_name, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"TaxaJuros error: {exc}") from exc

    return TaxaJurosResponse(
        endpoint=endpoint_name,
        total_records=len(data),
        data=data,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    if __package__:
        from .config import HOST, PORT, LOG_LEVEL
    else:
        from src.bacen_api.config import HOST, PORT, LOG_LEVEL  # type: ignore[no-redef]
    uvicorn.run("src.bacen_api.main:app", host=HOST, port=PORT, log_level=LOG_LEVEL, reload=True)
