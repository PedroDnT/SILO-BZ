import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Path, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Optional, List, Any
import logging
from datetime import datetime, timezone
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

if __package__:
    from .config import config, SecurityType
    from .models import (
        HealthResponse,
        ErrorResponse,
        SecurityListResponse,
        SecurityPriceResponse,
        IndexesResponse,
        MarketDataResponse,
        AvailableEndpointsResponse,
    )
    from .services import B3CalcService
else:
    from config import config, SecurityType
    from models import (
        HealthResponse,
        ErrorResponse,
        SecurityListResponse,
        SecurityPriceResponse,
        IndexesResponse,
        MarketDataResponse,
        AvailableEndpointsResponse,
    )
    from services import B3CalcService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
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
        "Set B3_CALC_DATABASE_URL env var to enable database connectivity."
    )

# Global service instance
b3_calc_service: Optional[B3CalcService] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage service lifecycle"""
    global b3_calc_service
    logger.info("Starting B3 CALC API...")
    b3_calc_service = B3CalcService()
    await b3_calc_service.initialize()
    logger.info("B3 CALC API started successfully")
    yield
    if b3_calc_service:
        await b3_calc_service.close()
        logger.info("B3 CALC API shut down")
    # shutdown: dispose engine to close all pool connections cleanly
    if _db_engine is not None:
        await _db_engine.dispose()


# Initialize FastAPI app
app = FastAPI(
    title=config.API_TITLE,
    version=config.API_VERSION,
    description=config.API_DESCRIPTION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting configuration
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
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    )

# Health check endpoint
@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Check the health status of the B3 CALC API service"
)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now(timezone.utc).isoformat(),
        version=config.API_VERSION
    )

# Available endpoints
@app.get(
    "/api/v1/",
    response_model=AvailableEndpointsResponse,
    summary="Available endpoints",
    description="List all available API endpoints"
)
@limiter.limit(f"{rate_limit_requests}/{rate_limit_window} seconds" if rate_limit_enabled else "1000/minute")
async def get_available_endpoints(request: Request):
    """Get list of available endpoints"""
    endpoints = [
        {
            "path": "/api/v1/prices/{symbol}",
            "method": "GET",
            "description": "Get price data for a specific security symbol",
            "parameters": ["symbol", "security_type (optional)", "settlement_date (optional)"]
        },
        {
            "path": "/api/v1/indexes",
            "method": "GET",
            "description": "Get current financial indexes",
            "parameters": []
        },
        {
            "path": "/api/v1/market-data",
            "method": "GET",
            "description": "Get general market data",
            "parameters": []
        },
        {
            "path": "/api/v1/securities/{security_type}",
            "method": "GET",
            "description": "List securities of a specific type",
            "parameters": ["security_type", "page (optional)", "page_size (optional)", "search (optional)"]
        }
    ]

    return AvailableEndpointsResponse(
        endpoints=endpoints,
        version=config.API_VERSION
    )

# Get price data for a symbol
@app.get(
    "/api/v1/prices/{symbol}",
    response_model=SecurityPriceResponse,
    summary="Get price data for a symbol",
    description="Calculate and return price data for a fixed income security symbol"
)
@limiter.limit(f"{rate_limit_requests}/{rate_limit_window} seconds" if rate_limit_enabled else "1000/minute")
async def get_price_data(
    request: Request,
    symbol: str = Path(..., description="Security symbol/code"),
    security_type: Optional[SecurityType] = Query(
        None,
        description="Security type (debentures, cra, cri). Auto-detected if not provided."
    ),
    settlement_date: Optional[str] = Query(
        None,
        description="Settlement date in YYYY-MM-DD format (defaults to today)",
        example="2024-01-15",
    ),
):
    """Get price data for a security symbol"""
    if b3_calc_service is None:
        raise HTTPException(
            status_code=503,
            detail="B3 CALC service is not available"
        )

    try:
        result = await b3_calc_service.get_security_price(
            code=symbol.upper(),
            security_type=security_type,
            settlement_date=settlement_date,
        )
        return result
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc)
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.exception(f"Error calculating price for {symbol}: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to calculate price for {symbol}: {str(exc)}"
        ) from exc

# Get available indexes
@app.get(
    "/api/v1/indexes",
    response_model=IndexesResponse,
    summary="Get financial indexes",
    description="Returns current values for Brazilian financial indexes used in fixed income calculations"
)
@limiter.limit(f"{rate_limit_requests}/{rate_limit_window} seconds" if rate_limit_enabled else "1000/minute")
async def get_indexes(request: Request):
    """Get current financial indexes"""
    if b3_calc_service is None:
        raise HTTPException(
            status_code=503,
            detail="B3 CALC service is not available"
        )

    try:
        return await b3_calc_service.get_indexes()
    except Exception as exc:
        logger.exception(f"Error fetching indexes: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch indexes: {str(exc)}"
        ) from exc

# Get general market data
@app.get(
    "/api/v1/market-data",
    response_model=MarketDataResponse,
    summary="Get market data",
    description="Returns general market data including indexes and market status"
)
@limiter.limit(f"{rate_limit_requests}/{rate_limit_window} seconds" if rate_limit_enabled else "1000/minute")
async def get_market_data(request: Request):
    """Get general market data"""
    if b3_calc_service is None:
        raise HTTPException(
            status_code=503,
            detail="B3 CALC service is not available"
        )

    try:
        return await b3_calc_service.get_market_data()
    except Exception as exc:
        logger.exception(f"Error fetching market data: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch market data: {str(exc)}"
        ) from exc

# List securities by type
@app.get(
    "/api/v1/securities/{security_type}",
    response_model=SecurityListResponse,
    summary="List securities by type",
    description="Returns a list of securities of the specified type (debentures, cra, cri)"
)
@limiter.limit(f"{rate_limit_requests}/{rate_limit_window} seconds" if rate_limit_enabled else "1000/minute")
async def list_securities(
    request: Request,
    security_type: SecurityType = Path(..., description="Security type"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(
        config.DEFAULT_PAGE_SIZE,
        ge=1,
        le=config.MAX_PAGE_SIZE,
        description="Number of records per page"
    ),
    search: Optional[str] = Query(None, description="Search term to filter securities"),
):
    """List securities of a given type"""
    if b3_calc_service is None:
        raise HTTPException(
            status_code=503,
            detail="B3 CALC service is not available"
        )

    try:
        result = await b3_calc_service.list_securities(
            security_type=security_type,
            page=page,
            page_size=page_size,
            search=search,
        )
        return result
    except Exception as exc:
        logger.exception(f"Error listing {security_type.value}: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list {security_type.value}: {str(exc)}"
        ) from exc

# Exception handlers
@app.exception_handler(404)
async def not_found_handler(request, exc):
    """Handle 404 Not Found errors"""
    return JSONResponse(
        status_code=404,
        content=ErrorResponse(
            error="not_found",
            message=f"The requested resource was not found: {request.url.path}",
            status_code=404,
            timestamp=datetime.now(timezone.utc).isoformat()
        ).model_dump()
    )

@app.exception_handler(422)
async def validation_error_handler(request, exc):
    """Handle validation errors"""
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error="validation_error",
            message="Request validation failed",
            status_code=422,
            timestamp=datetime.now(timezone.utc).isoformat()
        ).model_dump()
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle general exceptions"""
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="internal_server_error",
            message="An internal server error occurred",
            status_code=500,
            timestamp=datetime.now(timezone.utc).isoformat()
        ).model_dump()
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.b3_calc_api.main:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        log_level="info"
    )