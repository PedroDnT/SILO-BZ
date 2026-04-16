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
    from .config import config, dataset_config, EntityType, FIDCDocType, FIPDocType, FIAGRODocType, SECURITDocType
    from .models import HealthResponse, ErrorResponse, DataResponse, AvailableEndpointsResponse, EntityInfo, CNPJRegistryResponse
    from .services import CVMCreditDataService
else:
    from config import config, dataset_config, EntityType, FIDCDocType, FIPDocType, FIAGRODocType, SECURITDocType
    from models import HealthResponse, ErrorResponse, DataResponse, AvailableEndpointsResponse, EntityInfo, CNPJRegistryResponse
    from services import CVMCreditDataService

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
        "Set CVM_DATABASE_URL env var to enable database connectivity."
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup: engine created at module load, nothing to do here
    yield
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

# Initialize service
data_service = CVMCreditDataService()

@app.get("/", response_model=Dict[str, str])
async def root():
    """Root endpoint with API information"""
    return {
        "service": config.API_TITLE,
        "version": config.API_VERSION,
        "documentation": "/docs",
        "health": "/health",
        "endpoints": "/api/v1/endpoints"
    }

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now(timezone.utc).isoformat(),
        version=config.API_VERSION
    )

@app.get("/api/v1/endpoints", response_model=AvailableEndpointsResponse)
@limiter.limit(f"{rate_limit_requests}/{rate_limit_window} seconds" if rate_limit_enabled else "1000/minute")
async def get_available_endpoints(request: Request):
    """Get all available endpoints and their descriptions"""
    entities = [
        EntityInfo(
            entity="fidc",
            name="FIDC - Fundos de Investimento em Direitos Creditórios",
            doc_types=dataset_config.get_available_doc_types("fidc"),
            description="Investment funds in credit rights"
        ),
        EntityInfo(
            entity="fip",
            name="FIP - Fundos de Investimento em Participações",
            doc_types=dataset_config.get_available_doc_types("fip"),
            description="Private equity investment funds"
        ),
        EntityInfo(
            entity="fiagro",
            name="FIAGRO - Fundos de Investimento nas Cadeias Produtivas Agroindustriais",
            doc_types=dataset_config.get_available_doc_types("fiagro"),
            description="Agroindustrial investment funds"
        ),
        EntityInfo(
            entity="securit",
            name="SECURIT - Securitizadoras",
            doc_types=dataset_config.get_available_doc_types("securit"),
            description="Securitization companies"
        )
    ]
    
    return AvailableEndpointsResponse(
        entities=entities,
        base_url="/api/v1/{entity}/{doc_type}",
        version=config.API_VERSION
    )

@app.get("/api/v1/fidc/{doc_type}", response_model=DataResponse)
@limiter.limit(f"{rate_limit_requests}/{rate_limit_window} seconds" if rate_limit_enabled else "1000/minute")
async def get_fidc_data(request: Request,
    doc_type: FIDCDocType = Path(..., description="Type of FIDC document"),
    year: Optional[int] = Query(None, description="Year for the data (required for periodic reports)"),
    month: Optional[int] = Query(None, ge=1, le=12, description="Month for the data (required for periodic reports)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(config.DEFAULT_PAGE_SIZE, ge=1, le=config.MAX_PAGE_SIZE, description="Items per page")
):
    """Get FIDC data by document type"""
    try:
        logger.info(f"Request: FIDC {doc_type.value} - year={year}, month={month}, page={page}, page_size={page_size}")
        
        result = await data_service.get_data(
            entity="fidc",
            doc_type=doc_type.value,
            year=year,
            month=month,
            page=page,
            page_size=page_size
        )
        
        return result
        
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error processing FIDC request: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/api/v1/fip/{doc_type}", response_model=DataResponse)
@limiter.limit(f"{rate_limit_requests}/{rate_limit_window} seconds" if rate_limit_enabled else "1000/minute")
async def get_fip_data(request: Request,
    doc_type: FIPDocType = Path(..., description="Type of FIP document"),
    year: Optional[int] = Query(None, description="Year for the data (required for periodic reports)"),
    month: Optional[int] = Query(None, ge=1, le=12, description="Month for the data (required for periodic reports)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(config.DEFAULT_PAGE_SIZE, ge=1, le=config.MAX_PAGE_SIZE, description="Items per page")
):
    """Get FIP data by document type"""
    try:
        logger.info(f"Request: FIP {doc_type.value} - year={year}, month={month}, page={page}, page_size={page_size}")
        
        result = await data_service.get_data(
            entity="fip",
            doc_type=doc_type.value,
            year=year,
            month=month,
            page=page,
            page_size=page_size
        )
        
        return result
        
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error processing FIP request: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/api/v1/fiagro/{doc_type}", response_model=DataResponse)
@limiter.limit(f"{rate_limit_requests}/{rate_limit_window} seconds" if rate_limit_enabled else "1000/minute")
async def get_fiagro_data(request: Request,
    doc_type: FIAGRODocType = Path(..., description="Type of FIAGRO document"),
    year: Optional[int] = Query(None, description="Year for the data (required for periodic reports)"),
    month: Optional[int] = Query(None, ge=1, le=12, description="Month for the data (required for periodic reports)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(config.DEFAULT_PAGE_SIZE, ge=1, le=config.MAX_PAGE_SIZE, description="Items per page")
):
    """Get FIAGRO data by document type"""
    try:
        logger.info(f"Request: FIAGRO {doc_type.value} - year={year}, month={month}, page={page}, page_size={page_size}")
        
        result = await data_service.get_data(
            entity="fiagro",
            doc_type=doc_type.value,
            year=year,
            month=month,
            page=page,
            page_size=page_size
        )
        
        return result
        
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error processing FIAGRO request: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/api/v1/securit/{doc_type}", response_model=DataResponse)
@limiter.limit(f"{rate_limit_requests}/{rate_limit_window} seconds" if rate_limit_enabled else "1000/minute")
async def get_securit_data(request: Request,
    doc_type: SECURITDocType = Path(..., description="Type of SECURIT document"),
    year: Optional[int] = Query(None, description="Year for the data (required for periodic reports)"),
    month: Optional[int] = Query(None, ge=1, le=12, description="Month for the data (required for monthly reports)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(config.DEFAULT_PAGE_SIZE, ge=1, le=config.MAX_PAGE_SIZE, description="Items per page")
):
    """Get SECURIT data by document type"""
    try:
        logger.info(f"Request: SECURIT {doc_type.value} - year={year}, month={month}, page={page}, page_size={page_size}")
        
        result = await data_service.get_data(
            entity="securit",
            doc_type=doc_type.value,
            year=year,
            month=month,
            page=page,
            page_size=page_size
        )
        
        return result
        
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error processing SECURIT request: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/api/v1/cnpj/{cnpj}", response_model=CNPJRegistryResponse)
async def get_cnpj_registry(
    cnpj: str = Path(..., description="CNPJ to look up (digits only or formatted XX.XXX.XXX/XXXX-XX)"),
    year: int = Query(..., ge=2000, le=2030, description="Year for cadastral and emission data"),
    month: Optional[int] = Query(None, ge=1, le=12, description="Month for periodic financial data (quota price, NAV, delinquency). When omitted, only cadastral and SECURIT emission data are returned."),
):
    """
    Full cross-entity CNPJ lookup for fraud detection.

    Returns three data planes in a single call:

    - **registrations** — cadastral data (FIDC, FIP, FIAGRO): fund name, status,
      registration/cancellation dates, fund type, all raw fields.
    - **periodic_snapshots** — mensal financial data (FIDC, FIAGRO) for `year+month`:
      quota/unit price, NAV (patrimônio líquido), delinquency value, all raw fields.
      Only populated when `month` is supplied.
    - **emissions** — SECURIT emission records (CRA, CRI, LCA, LCI) where this CNPJ
      is the issuer: emission price, unit price, maturity, quantity, all raw fields.
      Always fetched for the given `year`.

    All downloads are cached on disk (24 h TTL) so repeated lookups for the same
    period are served instantly.
    """
    cnpj_digits = ''.join(filter(str.isdigit, cnpj))
    if len(cnpj_digits) != 14:
        raise HTTPException(status_code=400, detail="CNPJ must have 14 digits")

    try:
        result = await data_service.get_cnpj_registry(cnpj=cnpj, year=year, month=month)
        return CNPJRegistryResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error processing CNPJ registry request: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Custom HTTP exception handler"""
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=exc.detail,
            status_code=exc.status_code,
            timestamp=datetime.now(timezone.utc).isoformat()
        ).model_dump()
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """General exception handler"""
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="Internal server error",
            status_code=500,
            timestamp=datetime.now(timezone.utc).isoformat()
        ).model_dump()
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)