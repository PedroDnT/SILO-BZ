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
from datetime import datetime, timezone
from typing import Optional
import logging

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

if __package__:
    from .config import API_TITLE, API_VERSION, API_DESCRIPTION
    from .models import HealthResponse, ErrorResponse
    from .services import BacenService
else:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
    from src.bacen_api.config import API_TITLE, API_VERSION, API_DESCRIPTION
    from src.bacen_api.models import HealthResponse, ErrorResponse
    from src.bacen_api.services import BacenService

logger = logging.getLogger(__name__)

# Lazy DB import: engine disposal only if DB is configured
_db_engine = None
try:
    if __package__:
        from .db import engine as _db_engine
    else:
        from db import engine as _db_engine
except KeyError:
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "DATABASE_URL not set — DB engine not initialized. "
        "Set BACEN_DATABASE_URL env var to enable database connectivity."
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
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

# Rate limiting
def get_rate_limit_key(request: Request) -> str:
    return get_remote_address(request)

rate_limit_enabled = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
rate_limit_requests = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
rate_limit_window = int(os.getenv("RATE_LIMIT_WINDOW", "60"))

limiter = Limiter(key_func=get_rate_limit_key)
app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={
            "error": "Rate limit exceeded",
            "status_code": 429,
            "detail": str(exc.detail),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )

_service = BacenService()


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
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now(timezone.utc).isoformat(),
        version=API_VERSION,
    )


# ─── SGS ──────────────────────────────────────────────────────────────────────

@app.get(
    "/api/v1/bacen/sgs/well-known",
    tags=["SGS"],
    summary="List well-known SGS series codes",
)
@limiter.limit(f"{rate_limit_requests}/{rate_limit_window} seconds" if rate_limit_enabled else "1000/minute")
async def list_well_known_sgs(request: Request):
    return _service.get_well_known_series()


@app.get(
    "/api/v1/bacen/sgs/{series_code}",
    tags=["SGS"],
    summary="Fetch a single SGS time series",
)
@limiter.limit(f"{rate_limit_requests}/{rate_limit_window} seconds" if rate_limit_enabled else "1000/minute")
async def get_sgs_series(
    request: Request,
    series_code: int,
    label: str = Query("value", description="Column label for the series"),
    start: Optional[str] = Query(None, description="Start date ISO YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="End date ISO YYYY-MM-DD"),
    last: Optional[int] = Query(None, ge=1, le=5000, description="Return last N observations"),
):
    """Popular codes: SELIC=11, CDI=12, IPCA=433, IGP-M=189, USD/BRL=1."""
    try:
        return await _service.get_sgs_series(
            series_code=series_code, label=label, start=start, end=end, last=last
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"BCB SGS error: {exc}") from exc


@app.get(
    "/api/v1/bacen/sgs/multi",
    tags=["SGS"],
    summary="Fetch multiple SGS time series in one request",
)
@limiter.limit(f"{rate_limit_requests}/{rate_limit_window} seconds" if rate_limit_enabled else "1000/minute")
async def get_sgs_multi(
    request: Request,
    codes: str = Query(
        ...,
        description='Comma-separated label:code pairs. Example: "IPCA:433,CDI:12,SELIC:11"',
    ),
    start: Optional[str] = Query(None, description="Start date ISO YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="End date ISO YYYY-MM-DD"),
    last: Optional[int] = Query(None, ge=1, le=5000, description="Return last N observations"),
):
    try:
        return await _service.get_sgs_multi(codes_str=codes, start=start, end=end, last=last)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"BCB SGS error: {exc}") from exc


# ─── PTAX ─────────────────────────────────────────────────────────────────────

@app.get(
    "/api/v1/bacen/ptax/dolar",
    tags=["PTAX"],
    summary="USD/BRL PTAX closing rate for a specific date",
)
@limiter.limit(f"{rate_limit_requests}/{rate_limit_window} seconds" if rate_limit_enabled else "1000/minute")
async def ptax_dolar_dia(
    request: Request,
    date: str = Query(..., description="Date ISO YYYY-MM-DD"),
):
    try:
        return await _service.get_ptax_dolar(date)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"PTAX error: {exc}") from exc


@app.get(
    "/api/v1/bacen/ptax/dolar/periodo",
    tags=["PTAX"],
    summary="USD/BRL PTAX closing rates for a date range",
)
@limiter.limit(f"{rate_limit_requests}/{rate_limit_window} seconds" if rate_limit_enabled else "1000/minute")
async def ptax_dolar_periodo(
    request: Request,
    start: str = Query(..., description="Start date ISO YYYY-MM-DD"),
    end: str = Query(..., description="End date ISO YYYY-MM-DD"),
):
    try:
        return await _service.get_ptax_dolar_periodo(start, end)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"PTAX error: {exc}") from exc


@app.get(
    "/api/v1/bacen/ptax/moeda/{moeda}",
    tags=["PTAX"],
    summary="Exchange rate vs BRL for a specific currency and date",
)
async def ptax_moeda_dia(
    moeda: str,
    date: str = Query(..., description="Date ISO YYYY-MM-DD"),
):
    try:
        return await _service.get_ptax_moeda(moeda, date)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"PTAX error: {exc}") from exc


@app.get(
    "/api/v1/bacen/ptax/moeda/{moeda}/periodo",
    tags=["PTAX"],
    summary="Exchange rate vs BRL for a specific currency and date range",
)
async def ptax_moeda_periodo(
    moeda: str,
    start: str = Query(..., description="Start date ISO YYYY-MM-DD"),
    end: str = Query(..., description="End date ISO YYYY-MM-DD"),
):
    try:
        return await _service.get_ptax_moeda_periodo(moeda, start, end)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"PTAX error: {exc}") from exc


@app.get(
    "/api/v1/bacen/ptax/moedas",
    tags=["PTAX"],
    summary="List all currencies available in PTAX",
)
async def ptax_moedas():
    try:
        return await _service.get_ptax_moedas()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"PTAX error: {exc}") from exc


# ─── Expectativas ─────────────────────────────────────────────────────────────

@app.get(
    "/api/v1/bacen/expectativas",
    tags=["Expectativas"],
    summary="List available market expectations endpoints",
)
async def list_expectativas():
    return _service.list_expectativas()


@app.get(
    "/api/v1/bacen/expectativas/{endpoint_name}",
    tags=["Expectativas"],
    summary="Query BACEN market expectations (Focus bulletin)",
)
async def get_expectativas(
    endpoint_name: str,
    indicador: Optional[str] = Query(None, description="Filter by indicator (e.g. IPCA, Selic)"),
    start: Optional[str] = Query(None, description="Filter Data >= this ISO date"),
    limit: int = Query(100, ge=1, le=1000, description="Max rows to return"),
):
    """Common indicators: IPCA, IGP-M, Selic, PIB Total, Câmbio."""
    try:
        return await _service.get_expectativas(
            endpoint_name=endpoint_name, indicador=indicador, start=start, limit=limit
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Expectativas error: {exc}") from exc


# ─── TaxaJuros ────────────────────────────────────────────────────────────────

@app.get(
    "/api/v1/bacen/taxas_juros/{endpoint_name}",
    tags=["TaxaJuros"],
    summary="Query BACEN interest-rate data",
)
async def get_taxas_juros(
    endpoint_name: str = "TaxasJurosMercadoImobiliario",
    limit: int = Query(100, ge=1, le=1000, description="Max rows to return"),
):
    """Query BACEN TaxaJuros OData API (e.g. mortgage interest rates by institution)."""
    try:
        return await _service.get_taxas_juros(endpoint_name=endpoint_name, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"TaxaJuros error: {exc}") from exc


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    if __package__:
        from .config import HOST, PORT, LOG_LEVEL
    else:
        from src.bacen_api.config import HOST, PORT, LOG_LEVEL  # type: ignore[no-redef]
    uvicorn.run("src.bacen_api.main:app", host=HOST, port=PORT, log_level=LOG_LEVEL, reload=True)
