"""
Unified API Gateway for Brazilian Financial Data API.

Single public entry point routing to three backend services:
- CVM  : Credit market data (FIDC, FIP, FIAGRO, SECURIT)
- BACEN: Central Bank data (SGS, PTAX, Focus expectations)
- B3   : Fixed income pricing (debentures, CRA, CRI)

Run:
  uvicorn src.gateway.main:app --host 0.0.0.0 --port 8080 --reload
"""

import os
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, HTTPException, Query, Path, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Service URLs — override via env vars when running in Docker
CVM_URL = os.getenv("CVM_API_URL", "http://localhost:8000")
B3_URL = os.getenv("B3_CALC_API_URL", "http://localhost:8001")
BACEN_URL = os.getenv("BACEN_API_URL", "http://localhost:8002")

_client: httpx.AsyncClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client
    _client = httpx.AsyncClient(timeout=300.0)
    yield
    await _client.aclose()


app = FastAPI(
    title="Brazilian Financial Data API",
    description=(
        "Unified gateway for Brazilian financial market data.\n\n"
        "- **/api/v1/cvm/...** — CVM credit funds (FIDC, FIP, FIAGRO, SECURIT)\n"
        "- **/api/v1/bacen/...** — BACEN (SGS rates, PTAX FX, Focus expectations)\n"
        "- **/api/v1/b3/...** — B3 fixed income pricing (debentures, CRA, CRI)"
    ),
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting
rate_limit_enabled = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
rate_limit_requests = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
rate_limit_window = int(os.getenv("RATE_LIMIT_WINDOW", "60"))

limiter = Limiter(key_func=get_remote_address)
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

_LIMIT = f"{rate_limit_requests}/{rate_limit_window} seconds" if rate_limit_enabled else "1000/minute"


async def _proxy(url: str, request: Request) -> dict:
    """Forward a GET request to a backend service, preserving query params."""
    try:
        resp = await _client.get(url, params=dict(request.query_params))
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text) from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"Backend unreachable: {exc}") from exc


async def _health_check(url: str, name: str) -> dict:
    try:
        resp = await _client.get(f"{url}/health", timeout=5.0)
        return {"status": "healthy" if resp.status_code == 200 else "degraded"}
    except Exception:
        return {"status": "unreachable"}


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/health", tags=["Gateway"])
async def health_check():
    cvm, b3, bacen = (
        await _health_check(CVM_URL, "cvm"),
        await _health_check(B3_URL, "b3"),
        await _health_check(BACEN_URL, "bacen"),
    )
    statuses = [cvm["status"], b3["status"], bacen["status"]]
    overall = "healthy" if all(s == "healthy" for s in statuses) else "degraded"
    return {
        "status": overall,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "2.0.0",
        "services": {"cvm": cvm, "b3": b3, "bacen": bacen},
    }


# ─── CVM proxy ────────────────────────────────────────────────────────────────

@app.get("/api/v1/cvm/endpoints", tags=["CVM"])
@limiter.limit(_LIMIT)
async def cvm_endpoints(request: Request):
    return await _proxy(f"{CVM_URL}/api/v1/endpoints", request)


@app.get("/api/v1/cvm/cnpj/{cnpj}", tags=["CVM"])
@limiter.limit(_LIMIT)
async def cvm_cnpj(request: Request, cnpj: str = Path(...)):
    return await _proxy(f"{CVM_URL}/api/v1/cnpj/{cnpj}", request)


@app.get("/api/v1/cvm/{entity}/{doc_type}", tags=["CVM"])
@limiter.limit(_LIMIT)
async def cvm_data(
    request: Request,
    entity: str = Path(..., description="fidc | fip | fiagro | securit"),
    doc_type: str = Path(...),
):
    return await _proxy(f"{CVM_URL}/api/v1/{entity}/{doc_type}", request)


# ─── BACEN proxy ──────────────────────────────────────────────────────────────

@app.get("/api/v1/bacen/sgs/well-known", tags=["BACEN"])
@limiter.limit(_LIMIT)
async def bacen_sgs_well_known(request: Request):
    return await _proxy(f"{BACEN_URL}/api/v1/bacen/sgs/well-known", request)


@app.get("/api/v1/bacen/sgs/multi", tags=["BACEN"])
@limiter.limit(_LIMIT)
async def bacen_sgs_multi(request: Request):
    return await _proxy(f"{BACEN_URL}/api/v1/bacen/sgs/multi", request)


@app.get("/api/v1/bacen/sgs/{series_code}", tags=["BACEN"])
@limiter.limit(_LIMIT)
async def bacen_sgs(request: Request, series_code: int = Path(...)):
    return await _proxy(f"{BACEN_URL}/api/v1/bacen/sgs/{series_code}", request)


@app.get("/api/v1/bacen/ptax/dolar/periodo", tags=["BACEN"])
@limiter.limit(_LIMIT)
async def bacen_ptax_dolar_periodo(request: Request):
    return await _proxy(f"{BACEN_URL}/api/v1/bacen/ptax/dolar/periodo", request)


@app.get("/api/v1/bacen/ptax/dolar", tags=["BACEN"])
@limiter.limit(_LIMIT)
async def bacen_ptax_dolar(request: Request):
    return await _proxy(f"{BACEN_URL}/api/v1/bacen/ptax/dolar", request)


@app.get("/api/v1/bacen/ptax/moeda/{moeda}/periodo", tags=["BACEN"])
@limiter.limit(_LIMIT)
async def bacen_ptax_moeda_periodo(request: Request, moeda: str = Path(...)):
    return await _proxy(f"{BACEN_URL}/api/v1/bacen/ptax/moeda/{moeda}/periodo", request)


@app.get("/api/v1/bacen/ptax/moeda/{moeda}", tags=["BACEN"])
@limiter.limit(_LIMIT)
async def bacen_ptax_moeda(request: Request, moeda: str = Path(...)):
    return await _proxy(f"{BACEN_URL}/api/v1/bacen/ptax/moeda/{moeda}", request)


@app.get("/api/v1/bacen/ptax/moedas", tags=["BACEN"])
@limiter.limit(_LIMIT)
async def bacen_ptax_moedas(request: Request):
    return await _proxy(f"{BACEN_URL}/api/v1/bacen/ptax/moedas", request)


@app.get("/api/v1/bacen/expectativas", tags=["BACEN"])
@limiter.limit(_LIMIT)
async def bacen_expectativas_list(request: Request):
    return await _proxy(f"{BACEN_URL}/api/v1/bacen/expectativas", request)


@app.get("/api/v1/bacen/expectativas/{endpoint_name}", tags=["BACEN"])
@limiter.limit(_LIMIT)
async def bacen_expectativas(request: Request, endpoint_name: str = Path(...)):
    return await _proxy(f"{BACEN_URL}/api/v1/bacen/expectativas/{endpoint_name}", request)


@app.get("/api/v1/bacen/taxas_juros/{endpoint_name}", tags=["BACEN"])
@limiter.limit(_LIMIT)
async def bacen_taxas_juros(request: Request, endpoint_name: str = Path(...)):
    return await _proxy(f"{BACEN_URL}/api/v1/bacen/taxas_juros/{endpoint_name}", request)


# ─── B3 proxy ─────────────────────────────────────────────────────────────────

@app.get("/api/v1/b3/indexes", tags=["B3"])
@limiter.limit(_LIMIT)
async def b3_indexes(request: Request):
    return await _proxy(f"{B3_URL}/api/v1/indexes", request)


@app.get("/api/v1/b3/market-data", tags=["B3"])
@limiter.limit(_LIMIT)
async def b3_market_data(request: Request):
    return await _proxy(f"{B3_URL}/api/v1/market-data", request)


@app.get("/api/v1/b3/securities/{security_type}", tags=["B3"])
@limiter.limit(_LIMIT)
async def b3_securities(request: Request, security_type: str = Path(...)):
    return await _proxy(f"{B3_URL}/api/v1/securities/{security_type}", request)


@app.get("/api/v1/b3/prices/{symbol}", tags=["B3"])
@limiter.limit(_LIMIT)
async def b3_price(request: Request, symbol: str = Path(...)):
    return await _proxy(f"{B3_URL}/api/v1/prices/{symbol}", request)


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.gateway.main:app", host="0.0.0.0", port=8080, reload=True)
