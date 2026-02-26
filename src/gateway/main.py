"""
Unified API Gateway for Brazilian Financial Data API.

This gateway provides a single entry point to all services:
- CVM (port 8000): Credit market data
- BACEN (port 8002): Central Bank data
- B3 CALC (port 8001): Fixed income pricing

The OpenAPI spec is defined in openapi.yaml and rendered with Redocly.

Run:
  python -m uvicorn src.gateway.main:app --reload --host 0.0.0.0 --port 8000
"""

import httpx
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Path, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Service URLs
CVM_SERVICE_URL = "http://localhost:8000"
B3_CALC_SERVICE_URL = "http://localhost:8001"
BACEN_SERVICE_URL = "http://localhost:8002"

# Initialize FastAPI app with OpenAPI spec from YAML
app = FastAPI(
    title="Brazilian Financial Data API",
    description="""
Unified API for accessing Brazilian financial market data from public sources.

## Services
- **CVM** (port 8000): Credit market data - FIDC, FIP, FIAGRO, SECURIT
- **BACEN** (port 8002): Central Bank data - SGS, PTAX, Focus expectations
- **B3 CALC** (port 8001): Fixed income pricing - debentures, CRA, CRI

## Authentication
All endpoints are publicly accessible (no authentication required).
    """,
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.yaml",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# HTTP client for proxying requests
_client = httpx.AsyncClient(timeout=300.0)


# ─── Health Endpoints ───────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    """Gateway health check"""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "2.0.0",
        "services": {
            "cvm": CVM_SERVICE_URL,
            "b3_calc": B3_CALC_SERVICE_URL,
            "bacen": BACEN_SERVICE_URL
        }
    }


# ─── Redirects for OpenAPI ──────────────────────────────────────────────────

@app.get("/openapi.json")
async def get_openapi_json():
    """Redirect to YAML spec"""
    return RedirectResponse(url="/openapi.yaml")


# ─── CVM Endpoints (Proxy) ──────────────────────────────────────────────────

@app.get("/api/v1/cvm/endpoints")
async def get_cvm_endpoints():
    """Proxy to CVM service for available endpoints"""
    try:
        response = await _client.get(f"{CVM_SERVICE_URL}/api/v1/endpoints")
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        logger.error(f"CVM service error: {e}")
        raise HTTPException(status_code=503, detail=f"CVM service unavailable: {str(e)}")


@app.get("/api/v1/cvm/{entity}/{doc_type}")
async def get_cvm_data(
    entity: str = Path(..., description="Entity type (fidc, fip, fiagro, securit)"),
    doc_type: str = Path(..., description="Document type"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(100, ge=1, le=10000, description="Items per page")
):
    """Proxy to CVM service for data"""
    try:
        response = await _client.get(
            f"{CVM_SERVICE_URL}/api/v1/{entity}/{doc_type}",
            params={"page": page, "page_size": page_size}
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        logger.error(f"CVM service error: {e}")
        raise HTTPException(status_code=503, detail=f"CVM service unavailable: {str(e)}")


# ─── BACEN Endpoints (Proxy) ─────────────────────────────────────────────────

@app.get("/api/v1/bacen/sgs/well-known")
async def get_well_known_sgs():
    """Proxy to BACEN service for well-known SGS series"""
    try:
        response = await _client.get(f"{BACEN_SERVICE_URL}/api/v1/bacen/sgs/well-known")
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        logger.error(f"BACEN service error: {e}")
        raise HTTPException(status_code=503, detail=f"BACEN service unavailable: {str(e)}")


@app.get("/api/v1/bacen/sgs/{series_code}")
async def get_sgs_series(
    series_code: int = Path(..., description="SGS series code"),
    data_inicio: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    data_fim: Optional[str] = Query(None, description="End date (YYYY-MM-DD)")
):
    """Proxy to BACEN service for SGS series"""
    try:
        params = {}
        if data_inicio:
            params["data_inicio"] = data_inicio
        if data_fim:
            params["data_fim"] = data_fim
        response = await _client.get(
            f"{BACEN_SERVICE_URL}/api/v1/bacen/sgs/{series_code}",
            params=params
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        logger.error(f"BACEN service error: {e}")
        raise HTTPException(status_code=503, detail=f"BACEN service unavailable: {str(e)}")


@app.post("/api/v1/bacen/sgs/multi")
async def get_multi_sgs_series(request: Request):
    """Proxy to BACEN service for multiple SGS series"""
    try:
        body = await request.json()
        response = await _client.post(
            f"{BACEN_SERVICE_URL}/api/v1/bacen/sgs/multi",
            json=body
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        logger.error(f"BACEN service error: {e}")
        raise HTTPException(status_code=503, detail=f"BACEN service unavailable: {str(e)}")


@app.get("/api/v1/bacen/ptax/dolar")
async def get_ptax_dolar(data: Optional[str] = Query(None, description="Date (YYYY-MM-DD)")):
    """Proxy to BACEN service for USD/BRL exchange rate"""
    try:
        params = {}
        if data:
            params["data"] = data
        response = await _client.get(
            f"{BACEN_SERVICE_URL}/api/v1/bacen/ptax/dolar",
            params=params
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        logger.error(f"BACEN service error: {e}")
        raise HTTPException(status_code=503, detail=f"BACEN service unavailable: {str(e)}")


@app.get("/api/v1/bacen/ptax/dolar/periodo")
async def get_ptax_dolar_period(
    data_inicio: str = Query(..., description="Start date (YYYY-MM-DD)"),
    data_fim: str = Query(..., description="End date (YYYY-MM-DD)")
):
    """Proxy to BACEN service for USD/BRL exchange rate period"""
    try:
        response = await _client.get(
            f"{BACEN_SERVICE_URL}/api/v1/bacen/ptax/dolar/periodo",
            params={"data_inicio": data_inicio, "data_fim": data_fim}
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        logger.error(f"BACEN service error: {e}")
        raise HTTPException(status_code=503, detail=f"BACEN service unavailable: {str(e)}")


@app.get("/api/v1/bacen/ptax/moedas")
async def get_ptax_moedas():
    """Proxy to BACEN service for available PTAX currencies"""
    try:
        response = await _client.get(f"{BACEN_SERVICE_URL}/api/v1/bacen/ptax/moedas")
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        logger.error(f"BACEN service error: {e}")
        raise HTTPException(status_code=503, detail=f"BACEN service unavailable: {str(e)}")


@app.get("/api/v1/bacen/ptax/moeda/{moeda}")
async def get_ptax_moeda(
    moeda: str = Path(..., description="Currency code"),
    data: Optional[str] = Query(None, description="Date (YYYY-MM-DD)")
):
    """Proxy to BACEN service for specific currency exchange rate"""
    try:
        params = {}
        if data:
            params["data"] = data
        response = await _client.get(
            f"{BACEN_SERVICE_URL}/api/v1/bacen/ptax/moeda/{moeda}",
            params=params
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        logger.error(f"BACEN service error: {e}")
        raise HTTPException(status_code=503, detail=f"BACEN service unavailable: {str(e)}")


@app.get("/api/v1/bacen/expectativas")
async def get_expectativas_endpoints():
    """Proxy to BACEN service for available expectativas endpoints"""
    try:
        response = await _client.get(f"{BACEN_SERVICE_URL}/api/v1/bacen/expectativas")
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        logger.error(f"BACEN service error: {e}")
        raise HTTPException(status_code=503, detail=f"BACEN service unavailable: {str(e)}")


@app.get("/api/v1/bacen/expectativas/{endpoint_name}")
async def get_expectativas(
    endpoint_name: str = Path(..., description="Expectativas endpoint name"),
    indicador: Optional[str] = Query(None),
    data: Optional[str] = Query(None),
    topx: int = Query(5, ge=1, le=100)
):
    """Proxy to BACEN service for market expectations"""
    try:
        params = {"topx": topx}
        if indicador:
            params["indicador"] = indicador
        if data:
            params["data"] = data
        response = await _client.get(
            f"{BACEN_SERVICE_URL}/api/v1/bacen/expectativas/{endpoint_name}",
            params=params
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        logger.error(f"BACEN service error: {e}")
        raise HTTPException(status_code=503, detail=f"BACEN service unavailable: {str(e)}")


@app.get("/api/v1/bacen/taxas_juros/{endpoint_name}")
async def get_taxas_juros(endpoint_name: str = Path(..., description="Taxa juros endpoint")):
    """Proxy to BACEN service for interest rate data"""
    try:
        response = await _client.get(
            f"{BACEN_SERVICE_URL}/api/v1/bacen/taxas_juros/{endpoint_name}"
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        logger.error(f"BACEN service error: {e}")
        raise HTTPException(status_code=503, detail=f"BACEN service unavailable: {str(e)}")


# ─── B3 Endpoints (Proxy) ────────────────────────────────────────────────────

@app.get("/api/v1/b3/debentures")
async def get_debentures(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100)
):
    """Proxy to B3 CALC service for debenture data"""
    try:
        response = await _client.get(
            f"{B3_CALC_SERVICE_URL}/api/v1/debentures",
            params={"page": page, "page_size": page_size}
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        logger.error(f"B3 CALC service error: {e}")
        raise HTTPException(status_code=503, detail=f"B3 CALC service unavailable: {str(e)}")


@app.get("/api/v1/b3/cras")
async def get_cras(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100)
):
    """Proxy to B3 CALC service for CRA data"""
    try:
        response = await _client.get(
            f"{B3_CALC_SERVICE_URL}/api/v1/cras",
            params={"page": page, "page_size": page_size}
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        logger.error(f"B3 CALC service error: {e}")
        raise HTTPException(status_code=503, detail=f"B3 CALC service unavailable: {str(e)}")


@app.get("/api/v1/b3/cris")
async def get_cris(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100)
):
    """Proxy to B3 CALC service for CRI data"""
    try:
        response = await _client.get(
            f"{B3_CALC_SERVICE_URL}/api/v1/cris",
            params={"page": page, "page_size": page_size}
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        logger.error(f"B3 CALC service error: {e}")
        raise HTTPException(status_code=503, detail=f"B3 CALC service unavailable: {str(e)}")


# ─── Exception Handlers ──────────────────────────────────────────────────────

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail.get("error", "HTTPError"),
            "message": exc.detail.get("message", str(exc.detail)),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "path": str(request.url)
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "InternalServerError",
            "message": "An unexpected error occurred",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "path": str(request.url)
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)