# Brazilian Credit Market Data API \- Complete Source Code

**Generated:** February 20, 2026  
**Purpose:** FastAPI service for accessing Brazilian credit market data from public sources (CVM, B3 CALC)

\---

## Project Structure

\`\`\`  
brazilian-credit-market-api/  
├── main.py                 \# FastAPI application entry point  
├── config.py              \# Configuration and URL patterns  
├── services.py            \# Data download and parsing services  
├── models.py              \# Pydantic models  
├── requirements.txt       \# Python dependencies  
├── Dockerfile            \# Container build instructions  
├── docker-compose.yml    \# Docker Compose configuration  
└── README.md             \# Documentation  
\`\`\`

\---

File 1: main.py

\`\`\`python

## """Brazilian Credit Market Data API \- Main Application Module.

This FastAPI application provides access to Brazilian credit market data  
from public sources including CVM (Comissão de Valores Mobiliários) and  
B3 CALC (Brazilian Stock Exchange Fixed Income Calculator).

Data Sources:  
    \- CVM FIDC: Credit Rights Investment Funds monthly reports  
    \- CVM FI: Investment Funds daily data and portfolio composition  
    \- CVM FII: Real Estate Investment Funds monthly reports  
    \- B3 CALC: Fixed income securities pricing calculator  
"""

from \_\_future\_\_ import annotations

import logging  
import time  
from contextlib import asynccontextmanager  
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request, status  
from fastapi.middleware.cors import CORSMiddleware  
from fastapi.middleware.gzip import GZipMiddleware  
from fastapi.responses import JSONResponse, StreamingResponse

from config import (  
    DATASET\_CONFIGS,  
    DatasetType,  
    SecurityType,  
    get\_settings,  
)  
from models import (  
    DatasetInfo,  
    DatasetFileInfo,  
    DatasetListResponse,  
    DatasetFilesResponse,  
    DatasetDataResponse,  
    SecurityListResponse,  
    SecurityPriceResponse,  
    HealthResponse,  
    ErrorResponse,  
    PaginationParams,  
)  
from services import DataService, B3CalcService

Configure logging  
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s \- %(name)s \- %(levelname)s \- %(message)s",
)  
logger \= logging.getLogger(\_\_name\_\_)

settings \= get\_settings()

Global service instances

# data\_service: Optional\[DataService\] \= None

# b3\_calc\_service: Optional\[B3CalcService\] \= None

@asynccontextmanager  
async def lifespan(app: FastAPI):  
    """Manage application lifespan \- startup and shutdown."""  
    global data\_service, b3\_calc\_service

    logger.info("Starting Brazilian Credit Market Data API...")  
    data\_service \= DataService(settings)  
    b3\_calc\_service \= B3CalcService(settings)  
    await data\_service.initialize()  
    await b3\_calc\_service.initialize()  
    logger.info("Services initialized successfully.")

    yield

    logger.info("Shutting down services...")  
    await data\_service.close()  
    await b3\_calc\_service.close()  
    logger.info("Services shut down successfully.")

Initialize FastAPI app  
app \= FastAPI(

#     title=settings.APP\_NAME,

#     version=settings.APP\_VERSION,

    description=settings.APP\_DESCRIPTION,  
    lifespan=lifespan,  
    docs\_url="/docs",  
    redoc\_url="/redoc",  
    openapi\_url="/openapi.json",  
    contact={  
        "name": "Brazilian Credit Market Data API",  
        "url": "https://github.com/your-repo/br-credit-market-api",  
    },  
    license\_info={  
        "name": "MIT",  
        "url": "https://opensource.org/licenses/MIT",  
    },  
)

Middleware  
app.add\_middleware(

#     CORSMiddleware,

#     allow\_origins=\["\*"\],

    allow\_credentials=True,  
    allow\_methods=\["GET", "HEAD", "OPTIONS"\],  
    allow\_headers=\["\*"\],  
)  
app.add\_middleware(GZipMiddleware, minimum\_size=1000)

@app.middleware("http")  
async def add\_process\_time\_header(request: Request, call\_next):  
    """Add request processing time to response headers."""  
    start\_time \= time.time()  
    response \= await call\_next(request)  
    process\_time \= time.time() \- start\_time  
    response.headers\["X-Process-Time"\] \= str(process\_time)  
    response.headers\["X-API-Version"\] \= settings.APP\_VERSION  
    return response

@app.middleware("http")  
async def catch\_exceptions\_middleware(request: Request, call\_next):  
    """Catch unhandled exceptions and return proper JSON error responses."""  
    try:  
        return await call\_next(request)  
    except Exception as exc:  
        logger.exception(f"Unhandled exception for {request.url}: {exc}")  
        return JSONResponse(  
            status\_code=status.HTTP\_500\_INTERNAL\_SERVER\_ERROR,  
            content=ErrorResponse(  
                error="internal\_server\_error",  
                message="An unexpected error occurred. Please try again later.",  
                details={"path": str(request.url)},  
            ).model\_dump(),  
        )

# \===========================================================================

# Health Check Endpoints

# \===========================================================================

# 

# 

# @app.get(

#     "/health",

#     response\_model=HealthResponse,

    tags=\["Health"\],  
    summary="Health check endpoint",  
    description="Check the health and status of the API and its dependencies.",  
)  
async def health\_check() \-\> HealthResponse:  
    """Return API health status."""  
    return HealthResponse(  
        status="healthy",  
        version=settings.APP\_VERSION,  
        services={  
            "data\_service": "up" if data\_service else "down",  
            "b3\_calc\_service": "up" if b3\_calc\_service else "down",  
        },  
    )

@app.get(  
    "/",  
    tags=\["Root"\],  
    summary="API root endpoint",  
    description="Returns basic API information and available endpoints.",  
)  
async def root() \-\> Dict\[str, Any\]:  
    """Return API information."""  
    return {  
        "name": settings.APP\_NAME,  
        "version": settings.APP\_VERSION,  
        "description": settings.APP\_DESCRIPTION,  
        "docs\_url": "/docs",  
        "redoc\_url": "/redoc",  
        "health\_url": "/health",  
        "datasets\_url": "/datasets",  
        "calc\_url": "/calc",  
        "data\_sources": \[  
            {  
                "name": "CVM (Comissão de Valores Mobiliários)",  
                "url": "https://dados.cvm.gov.br",  
                "description": "Brazilian Securities and Exchange Commission open data",  
            },  
            {  
                "name": "B3 CALC",  
                "url": "https://calculadorarendafixa.com.br",  
                "description": "B3 Fixed Income Calculator",  
            },  
        \],  
    }

# \===========================================================================

# Dataset Endpoints

# \===========================================================================

# 

# 

# @app.get(

#     "/datasets",

#     response\_model=DatasetListResponse,

    tags=\["Datasets"\],  
    summary="List available datasets",  
    description=(  
        "Returns a list of all available datasets from CVM public data portal. "  
        "Each dataset has information about its content, URL pattern, and period format."  
    ),  
)  
async def list\_datasets() \-\> DatasetListResponse:  
    """List all available datasets."""  
    datasets \= \[\]  
    for dataset\_id, config in DATASET\_CONFIGS.items():  
        datasets.append(  
            DatasetInfo(  
                id=dataset\_id,  
                name=config\["name"\],  
                description=config\["description"\],  
                period\_format=config.get("period\_format"),  
                file\_type=config\["file\_type"\],  
                supports\_period=config\["supports\_period"\],  
                example\_period=config.get("example\_period"),  
                files\_in\_zip=config.get("files\_in\_zip", \[\]),  
            )  
        )

    return DatasetListResponse(  
        total=len(datasets),  
        datasets=datasets,  
    )

@app.get(  
    "/datasets/{dataset}/files",  
    response\_model=DatasetFilesResponse,  
    tags=\["Datasets"\],  
    summary="List available files for a dataset",  
    description=(  
        "Returns a list of available files for the specified dataset. "  
        "For periodic datasets, returns recently available periods. "  
        "For static datasets, returns the single file."  
    ),  
)  
async def list\_dataset\_files(  
    dataset: DatasetType,  
    year: Optional\[int\] \= Query(  
        None,  
        ge=2000,  
        le=2100,  
        description="Filter files by year",  
    ),  
) \-\> DatasetFilesResponse:  
    """List available files for a dataset."""  
    if data\_service is None:  
        raise HTTPException(  
            status\_code=status.HTTP\_503\_SERVICE\_UNAVAILABLE,  
            detail="Data service is not available",  
        )

    try:  
        files \= await data\_service.list\_available\_files(dataset, year=year)  
        return DatasetFilesResponse(  
            dataset=dataset,  
            total=len(files),  
            files=files,  
        )  
    except ValueError as exc:  
        raise HTTPException(  
            status\_code=status.HTTP\_400\_BAD\_REQUEST,  
            detail=str(exc),  
        ) from exc  
    except Exception as exc:  
        logger.exception(f"Error listing files for dataset {dataset}: {exc}")  
        raise HTTPException(  
            status\_code=status.HTTP\_500\_INTERNAL\_SERVER\_ERROR,  
            detail=f"Failed to list files for dataset {dataset}: {str(exc)}",  
        ) from exc

@app.get(  
    "/datasets/{dataset}/{period}",  
    response\_model=DatasetDataResponse,  
    tags=\["Datasets"\],  
    summary="Fetch and parse dataset for a period",  
    description=(  
        "Downloads and parses the dataset for the specified period. "  
        "Returns data as JSON with pagination support. "  
        "For ZIP files, specify which file within the ZIP using the 'file' query parameter. "  
        "Data is cached for improved performance."  
    ),  
)  
async def get\_dataset\_data(  
    dataset: DatasetType,  
    period: str \= Query(  
        ...,  
        description="Period in YYYYMM format for monthly data, YYYY for annual, or 'latest' for static datasets",  
        example="202312",  
    ),  
    file: Optional\[str\] \= Query(  
        None,  
        description="Specific file to retrieve from ZIP archive (e.g., 'inf\_mensal\_fidc\_PL\_202312.csv')",  
    ),  
    page: int \= Query(1, ge=1, description="Page number"),  
    page\_size: int \= Query(  
        settings.DEFAULT\_PAGE\_SIZE,  
        ge=1,  
        le=settings.MAX\_PAGE\_SIZE,  
        description="Number of records per page",  
    ),  
    columns: Optional\[str\] \= Query(  
        None,  
        description="Comma-separated list of columns to return (all columns if not specified)",  
    ),  
) \-\> DatasetDataResponse:  
    """Fetch and parse dataset data for a specific period."""  
    if data\_service is None:  
        raise HTTPException(  
            status\_code=status.HTTP\_503\_SERVICE\_UNAVAILABLE,  
            detail="Data service is not available",  
        )

Parse columns filter

#     column\_filter: Optional\[List\[str\]\] \= None

#     if columns:

        column\_filter \= \[col.strip() for col in columns.split(",") if col.strip()\]

    pagination \= PaginationParams(page=page, page\_size=page\_size)

    try:  
        result \= await data\_service.fetch\_dataset(  
            dataset=dataset,  
            period=period,  
            file\_name=file,  
            pagination=pagination,  
            columns=column\_filter,  
        )  
        return result  
    except ValueError as exc:  
        raise HTTPException(  
            status\_code=status.HTTP\_400\_BAD\_REQUEST,  
            detail=str(exc),  
        ) from exc  
    except FileNotFoundError as exc:  
        raise HTTPException(  
            status\_code=status.HTTP\_404\_NOT\_FOUND,  
            detail=str(exc),  
        ) from exc  
    except Exception as exc:  
        logger.exception(f"Error fetching dataset {dataset} for period {period}: {exc}")  
        raise HTTPException(  
            status\_code=status.HTTP\_500\_INTERNAL\_SERVER\_ERROR,  
            detail=f"Failed to fetch dataset: {str(exc)}",  
        ) from exc

@app.get(  
    "/datasets/{dataset}/{period}/download",  
    tags=\["Datasets"\],  
    summary="Download raw dataset file",  
    description=(  
        "Downloads the raw dataset file (ZIP or CSV) for the specified period. "  
        "Returns the file as a streaming response."  
    ),  
    response\_class=StreamingResponse,  
)  
async def download\_dataset(  
    dataset: DatasetType,  
    period: str \= Query(  
        ...,  
        description="Period in YYYYMM format for monthly data, YYYY for annual, or 'latest' for static datasets",  
        example="202312",  
    ),  
) \-\> StreamingResponse:  
    """Download raw dataset file."""  
    if data\_service is None:  
        raise HTTPException(  
            status\_code=status.HTTP\_503\_SERVICE\_UNAVAILABLE,  
            detail="Data service is not available",  
        )

    try:  
        file\_data, filename, content\_type \= await data\_service.download\_raw\_file(  
            dataset=dataset,  
            period=period,  
        )

        return StreamingResponse(  
            file\_data,  
            media\_type=content\_type,  
            headers={  
                "Content-Disposition": f'attachment; filename="{filename}"',  
                "X-Dataset": dataset,  
                "X-Period": period,  
            },  
        )  
    except ValueError as exc:  
        raise HTTPException(  
            status\_code=status.HTTP\_400\_BAD\_REQUEST,  
            detail=str(exc),  
        ) from exc  
    except FileNotFoundError as exc:  
        raise HTTPException(  
            status\_code=status.HTTP\_404\_NOT\_FOUND,  
            detail=str(exc),  
        ) from exc  
    except Exception as exc:  
        logger.exception(f"Error downloading dataset {dataset} for period {period}: {exc}")  
        raise HTTPException(  
            status\_code=status.HTTP\_500\_INTERNAL\_SERVER\_ERROR,  
            detail=f"Failed to download dataset: {str(exc)}",  
        ) from exc

# \===========================================================================

# B3 CALC Endpoints

# \===========================================================================

# 

# 

# @app.get(

#     "/calc/debentures",

#     response\_model=SecurityListResponse,

    tags=\["B3 CALC"\],  
    summary="List debenture codes from B3 CALC",  
    description=(  
        "Returns a list of debenture codes available in the B3 Fixed Income Calculator. "  
        "Debentures are corporate bonds issued by Brazilian companies."  
    ),  
)  
async def list\_debentures(  
    page: int \= Query(1, ge=1, description="Page number"),  
    page\_size: int \= Query(100, ge=1, le=1000, description="Number of records per page"),  
    search: Optional\[str\] \= Query(None, description="Search term to filter securities"),  
) \-\> SecurityListResponse:  
    """List debenture codes from B3 CALC."""  
    if b3\_calc\_service is None:  
        raise HTTPException(  
            status\_code=status.HTTP\_503\_SERVICE\_UNAVAILABLE,  
            detail="B3 CALC service is not available",  
        )

    try:  
        result \= await b3\_calc\_service.list\_securities(  
            security\_type=SecurityType.DEBENTURE,  
            page=page,  
            page\_size=page\_size,  
            search=search,  
        )  
        return result  
    except Exception as exc:  
        logger.exception(f"Error listing debentures: {exc}")  
        raise HTTPException(  
            status\_code=status.HTTP\_500\_INTERNAL\_SERVER\_ERROR,  
            detail=f"Failed to list debentures: {str(exc)}",  
        ) from exc

@app.get(  
    "/calc/cra",  
    response\_model=SecurityListResponse,  
    tags=\["B3 CALC"\],  
    summary="List CRA codes from B3 CALC",  
    description=(  
        "Returns a list of CRA (Certificado de Recebíveis do Agronegócio) codes available "  
        "in the B3 Fixed Income Calculator. CRAs are agribusiness receivables certificates."  
    ),  
)  
async def list\_cra(  
    page: int \= Query(1, ge=1, description="Page number"),  
    page\_size: int \= Query(100, ge=1, le=1000, description="Number of records per page"),  
    search: Optional\[str\] \= Query(None, description="Search term to filter securities"),  
) \-\> SecurityListResponse:  
    """List CRA codes from B3 CALC."""  
    if b3\_calc\_service is None:  
        raise HTTPException(  
            status\_code=status.HTTP\_503\_SERVICE\_UNAVAILABLE,  
            detail="B3 CALC service is not available",  
        )

    try:  
        result \= await b3\_calc\_service.list\_securities(  
            security\_type=SecurityType.CRA,  
            page=page,  
            page\_size=page\_size,  
            search=search,  
        )  
        return result  
    except Exception as exc:  
        logger.exception(f"Error listing CRAs: {exc}")  
        raise HTTPException(  
            status\_code=status.HTTP\_500\_INTERNAL\_SERVER\_ERROR,  
            detail=f"Failed to list CRAs: {str(exc)}",  
        ) from exc

@app.get(  
    "/calc/cri",  
    response\_model=SecurityListResponse,  
    tags=\["B3 CALC"\],  
    summary="List CRI codes from B3 CALC",  
    description=(  
        "Returns a list of CRI (Certificado de Recebíveis Imobiliários) codes available "  
        "in the B3 Fixed Income Calculator. CRIs are real estate receivables certificates."  
    ),  
)  
async def list\_cri(  
    page: int \= Query(1, ge=1, description="Page number"),  
    page\_size: int \= Query(100, ge=1, le=1000, description="Number of records per page"),  
    search: Optional\[str\] \= Query(None, description="Search term to filter securities"),  
) \-\> SecurityListResponse:  
    """List CRI codes from B3 CALC."""  
    if b3\_calc\_service is None:  
        raise HTTPException(  
            status\_code=status.HTTP\_503\_SERVICE\_UNAVAILABLE,  
            detail="B3 CALC service is not available",  
        )

    try:  
        result \= await b3\_calc\_service.list\_securities(  
            security\_type=SecurityType.CRI,  
            page=page,  
            page\_size=page\_size,  
            search=search,  
        )  
        return result  
    except Exception as exc:  
        logger.exception(f"Error listing CRIs: {exc}")  
        raise HTTPException(  
            status\_code=status.HTTP\_500\_INTERNAL\_SERVER\_ERROR,  
            detail=f"Failed to list CRIs: {str(exc)}",  
        ) from exc

@app.get(  
    "/calc/price/{code}",  
    response\_model=SecurityPriceResponse,  
    tags=\["B3 CALC"\],  
    summary="Calculate price for a security",  
    description=(  
        "Calculates the current price and related metrics for a fixed income security "  
        "using the B3 CALC API. Supports debentures, CRAs, and CRIs. "  
        "The security type is automatically detected from the code format."  
    ),  
)  
async def get\_security\_price(  
    code: str,  
    security\_type: Optional\[SecurityType\] \= Query(  
        None,  
        description="Security type (debentures, cra, cri). Auto-detected if not provided.",  
    ),  
    settlement\_date: Optional\[str\] \= Query(  
        None,  
        description="Settlement date in YYYY-MM-DD format (defaults to today)",  
        example="2024-01-15",  
    ),  
) \-\> SecurityPriceResponse:  
    """Calculate price for a fixed income security."""  
    if b3\_calc\_service is None:  
        raise HTTPException(  
            status\_code=status.HTTP\_503\_SERVICE\_UNAVAILABLE,  
            detail="B3 CALC service is not available",  
        )

    try:  
        result \= await b3\_calc\_service.get\_security\_price(  
            code=code.upper(),  
            security\_type=security\_type,  
            settlement\_date=settlement\_date,  
        )  
        return result  
    except ValueError as exc:  
        raise HTTPException(  
            status\_code=status.HTTP\_400\_BAD\_REQUEST,  
            detail=str(exc),  
        ) from exc  
    except FileNotFoundError as exc:  
        raise HTTPException(  
            status\_code=status.HTTP\_404\_NOT\_FOUND,  
            detail=str(exc),  
        ) from exc  
    except Exception as exc:  
        logger.exception(f"Error calculating price for {code}: {exc}")  
        raise HTTPException(  
            status\_code=status.HTTP\_500\_INTERNAL\_SERVER\_ERROR,  
            detail=f"Failed to calculate price for {code}: {str(exc)}",  
        ) from exc

@app.get(  
    "/calc/indexes",  
    tags=\["B3 CALC"\],  
    summary="Get current indexes from B3 CALC",  
    description=(  
        "Returns current values for Brazilian financial indexes used in fixed income calculations, "  
        "such as CDI, IPCA, IGP-M, SELIC, etc."  
    ),  
)  
async def get\_indexes() \-\> Dict\[str, Any\]:  
    """Get current financial indexes."""  
    if b3\_calc\_service is None:  
        raise HTTPException(  
            status\_code=status.HTTP\_503\_SERVICE\_UNAVAILABLE,  
            detail="B3 CALC service is not available",  
        )

    try:  
        return await b3\_calc\_service.get\_indexes()  
    except Exception as exc:  
        logger.exception(f"Error fetching indexes: {exc}")  
        raise HTTPException(  
            status\_code=status.HTTP\_500\_INTERNAL\_SERVER\_ERROR,  
            detail=f"Failed to fetch indexes: {str(exc)}",  
        ) from exc

# \===========================================================================

# Exception Handlers

# \===========================================================================

# 

# 

# @app.exception\_handler(404)

# async def not\_found\_handler(request: Request, exc: HTTPException) \-\> JSONResponse:

    """Handle 404 Not Found errors."""  
    return JSONResponse(  
        status\_code=status.HTTP\_404\_NOT\_FOUND,  
        content=ErrorResponse(  
            error="not\_found",  
            message=f"The requested resource was not found: {request.url.path}",  
            details={"path": str(request.url.path)},  
        ).model\_dump(),  
    )

@app.exception\_handler(422)  
async def validation\_error\_handler(request: Request, exc) \-\> JSONResponse:  
    """Handle validation errors."""  
    return JSONResponse(  
        status\_code=status.HTTP\_422\_UNPROCESSABLE\_ENTITY,  
        content=ErrorResponse(  
            error="validation\_error",  
            message="Request validation failed",  
            details={"errors": exc.errors() if hasattr(exc, "errors") else str(exc)},  
        ).model\_dump(),  
    )

if \_\_name\_\_ \== "\_\_main\_\_":  
    import uvicorn

    uvicorn.run(  
        "main:app",  
        host="0.0.0.0",  
        port=8000,  
        reload=settings.DEBUG,  
        log\_level=settings.LOG\_LEVEL.lower(),  
    )

\`\`\`

\---

File 2: config.py

\`\`\`python

## """Configuration module for Brazilian Credit Market Data API."""

from enum import Enum  
from typing import Dict, Optional  
from pydantic\_settings import BaseSettings  
from functools import lru\_cache

class Settings(BaseSettings):  
    """Application settings."""

    APP\_NAME: str \= "Brazilian Credit Market Data API"  
    APP\_VERSION: str \= "1.0.0"  
    APP\_DESCRIPTION: str \= (  
        "API for accessing Brazilian credit market data from CVM and B3 CALC public sources."  
    )  
    DEBUG: bool \= False  
    LOG\_LEVEL: str \= "INFO"

Cache settings

#     CACHE\_TTL\_SECONDS: int \= 3600  \# 1 hour

#     CACHE\_MAX\_SIZE: int \= 128

HTTP client settings  
    HTTP\_TIMEOUT: int \= 60

#     HTTP\_MAX\_RETRIES: int \= 3

    HTTP\_RETRY\_BACKOFF: float \= 1.5

Data encoding  
    CSV\_ENCODING: str \= "latin-1"

#     CSV\_SEPARATOR: str \= ";"

CVM Base URLs

#     CVM\_BASE\_URL: str \= "https://dados.cvm.gov.br/dados"

B3 CALC Base URL

#     B3\_CALC\_BASE\_URL: str \= "https://calculadorarendafixa.com.br/webservice"

Pagination  
    DEFAULT\_PAGE\_SIZE: int \= 1000

#     MAX\_PAGE\_SIZE: int \= 10000

    class Config:  
        env\_file \= ".env"  
        case\_sensitive \= True

@lru\_cache()  
def get\_settings() \-\> Settings:  
    """Get cached settings instance."""  
    return Settings()

class DatasetType(str, Enum):  
    """Available dataset types."""

    FIDC\_MONTHLY \= "fidc\_monthly"  
    FI\_DAILY \= "fi\_daily"  
    FI\_CDA \= "fi\_cda"  
    FI\_REGISTRATION \= "fi\_registration"  
    FII\_MONTHLY \= "fii\_monthly"

class SecurityType(str, Enum):  
    """Security types for B3 CALC."""

    DEBENTURE \= "debentures"  
    CRA \= "cra"  
    CRI \= "cri"

DATASET\_CONFIGS: Dict\[str, Dict\] \= {  
    DatasetType.FIDC\_MONTHLY: {  
        "name": "FIDC Monthly Reports",  
        "description": "Monthly reports for Credit Rights Investment Funds (FIDC)",  
        "url\_pattern": "{base}/FIDC/DOC/INF\_MENSAL/DADOS/inf\_mensal\_fidc\_{period}.zip",  
        "period\_format": "YYYYMM",  
        "file\_type": "zip",  
        "files\_in\_zip": \[  
            "inf\_mensal\_fidc\_PL\_{period}.csv",  
            "inf\_mensal\_fidc\_ativo\_{period}.csv",  
            "inf\_mensal\_fidc\_passivo\_{period}.csv",  
            "inf\_mensal\_fidc\_carteira\_dir\_cred\_{period}.csv",  
            "inf\_mensal\_fidc\_carteira\_mm\_{period}.csv",  
            "inf\_mensal\_fidc\_carteira\_outros\_{period}.csv",  
        \],  
        "supports\_period": True,  
        "example\_period": "202312",  
    },  
    DatasetType.FI\_DAILY: {  
        "name": "Investment Fund Daily Data",  
        "description": "Daily data for Investment Funds (FI) including NAV and returns",  
        "url\_pattern": "{base}/FI/DOC/INF\_DIARIO/DADOS/inf\_diario\_fi\_{period}.zip",  
        "period\_format": "YYYYMM",  
        "file\_type": "zip",  
        "files\_in\_zip": \["inf\_diario\_fi\_{period}.csv"\],  
        "supports\_period": True,  
        "example\_period": "202312",  
    },  
    DatasetType.FI\_CDA: {  
        "name": "Investment Fund Portfolio Composition",  
        "description": "Portfolio composition data for Investment Funds (CDA)",  
        "url\_pattern": "{base}/FI/DOC/CDA/DADOS/cda\_fi\_{period}.zip",  
        "period\_format": "YYYYMM",  
        "file\_type": "zip",  
        "files\_in\_zip": \[  
            "cda\_fi\_BDR\_{period}.csv",  
            "cda\_fi\_COTAS\_{period}.csv",  
            "cda\_fi\_DER\_{period}.csv",  
            "cda\_fi\_FIDC\_{period}.csv",  
            "cda\_fi\_OPAD\_{period}.csv",  
            "cda\_fi\_OPAV\_{period}.csv",  
            "cda\_fi\_TIT\_PRIV\_{period}.csv",  
            "cda\_fi\_TIT\_PUBL\_{period}.csv",  
        \],  
        "supports\_period": True,  
        "example\_period": "202312",  
    },  
    DatasetType.FI\_REGISTRATION: {  
        "name": "Investment Fund Registration",  
        "description": "Registration data for all Investment Funds (FI)",  
        "url\_pattern": "{base}/FI/CAD/DADOS/cad\_fi.csv",  
        "period\_format": None,  
        "file\_type": "csv",  
        "files\_in\_zip": \[\],  
        "supports\_period": False,  
        "example\_period": None,  
    },  
    DatasetType.FII\_MONTHLY: {  
        "name": "Real Estate Investment Fund Monthly Reports",  
        "description": "Monthly reports for Real Estate Investment Funds (FII)",  
        "url\_pattern": "{base}/FII/DOC/INF\_MENSAL/DADOS/inf\_mensal\_fii\_{period}.zip",  
        "period\_format": "YYYY",  
        "file\_type": "zip",  
        "files\_in\_zip": \[  
            "inf\_mensal\_fii\_{period}.csv",  
            "inf\_mensal\_fii\_complemento\_{period}.csv",  
        \],  
        "supports\_period": True,  
        "example\_period": "2023",  
    },  
}

B3\_CALC\_ENDPOINTS: Dict\[str, str\] \= {  
    "debentures\_list": "/debentures/list",  
    "cra\_list": "/cra/list",  
    "cri\_list": "/cri/list",  
    "debenture\_price": "/debentures/calculate",  
    "cra\_price": "/cra/calculate",  
    "cri\_price": "/cri/calculate",  
    "security\_info": "/security/info",  
    "indexes": "/indexes/current",  
}

\`\`\`

\---

File 3: services.py

\`\`\`python

## """Service layer for downloading and parsing Brazilian credit market data.

This module provides async services for:  
\- Downloading and caching CVM data files (ZIP and CSV)  
\- Parsing CSV files with proper encoding and separator handling  
\- Interfacing with B3 CALC REST API for fixed income pricing  
\- In-memory caching with TTL support  
"""

from \_\_future\_\_ import annotations

import asyncio  
import io  
import logging  
import re  
import zipfile  
from datetime import datetime, date  
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple  
from urllib.parse import urljoin

import httpx  
import pandas as pd  
from cachetools import TTLCache  
from tenacity import (  
    retry,  
    stop\_after\_attempt,  
    wait\_exponential,  
    retry\_if\_exception\_type,  
    before\_sleep\_log,  
)

from config import (  
    DATASET\_CONFIGS,  
    B3\_CALC\_ENDPOINTS,  
    DatasetType,  
    SecurityType,  
    Settings,  
)  
from models import (  
    DatasetDataResponse,  
    DatasetFileInfo,  
    PaginationInfo,  
    PaginationParams,  
    SecurityInfo,  
    SecurityListResponse,  
    SecurityPriceResponse,  
    PriceCalculationResult,  
    CacheEntry,  
)

logger \= logging.getLogger(\_\_name\_\_)

# \===========================================================================

# Cache Manager

# \===========================================================================

# 

# 

# class CacheManager:

#     """Thread-safe in-memory cache manager with TTL support."""

    def \_\_init\_\_(self, max\_size: int \= 128, ttl\_seconds: int \= 3600):  
        self.\_cache: TTLCache \= TTLCache(maxsize=max\_size, ttl=ttl\_seconds)  
        self.\_ttl \= ttl\_seconds  
        self.\_lock \= asyncio.Lock()

    async def get(self, key: str) \-\> Optional\[Any\]:  
        """Get value from cache."""  
        async with self.\_lock:  
            return self.\_cache.get(key)

    async def set(self, key: str, value: Any) \-\> None:  
        """Set value in cache."""  
        async with self.\_lock:  
            self.\_cache\[key\] \= value

    async def delete(self, key: str) \-\> None:  
        """Delete value from cache."""  
        async with self.\_lock:  
            self.\_cache.pop(key, None)

    async def clear(self) \-\> None:  
        """Clear all cache entries."""  
        async with self.\_lock:  
            self.\_cache.clear()

    @property  
    def size(self) \-\> int:  
        """Return current cache size."""  
        return len(self.\_cache)

    @property  
    def max\_size(self) \-\> int:  
        """Return maximum cache size."""  
        return self.\_cache.maxsize

# \===========================================================================

# HTTP Client Factory

# \===========================================================================

# 

# 

# def create\_http\_client(settings: Settings) \-\> httpx.AsyncClient:

    """Create configured async HTTP client."""  
    return httpx.AsyncClient(  
        timeout=httpx.Timeout(  
            connect=10.0,  
            read=settings.HTTP\_TIMEOUT,  
            write=10.0,  
            pool=5.0,  
        ),  
        limits=httpx.Limits(  
            max\_connections=20,  
            max\_keepalive\_connections=10,  
            keepalive\_expiry=30,  
        ),  
        headers={  
            "User-Agent": "BrazilianCreditMarketAPI/1.0 (https://github.com/your-repo)",  
            "Accept-Encoding": "gzip, deflate, br",  
        },  
        follow\_redirects=True,  
    )

# \===========================================================================

# Period Validation Utilities

# \===========================================================================

# 

# 

# def validate\_period(period: str, period\_format: Optional\[str\]) \-\> None:

    """Validate period string against expected format."""  
    if period\_format \== "YYYYMM":  
        if not re.match(r"^\\d{6}$", period):  
            raise ValueError(  
                f"Invalid period format '{period}'. Expected YYYYMM (e.g., 202312)."  
            )  
        year \= int(period\[:4\])  
        month \= int(period\[4:\])  
        if not (2000 \<= year \<= 2100\) or not (1 \<= month \<= 12):  
            raise ValueError(  
                f"Invalid period value '{period}'. Year must be 2000-2100, month 1-12."  
            )  
    elif period\_format \== "YYYY":  
        if not re.match(r"^\\d{4}$", period):  
            raise ValueError(  
                f"Invalid period format '{period}'. Expected YYYY (e.g., 2023)."  
            )  
        year \= int(period)  
        if not (2000 \<= year \<= 2100):  
            raise ValueError(  
                f"Invalid period value '{period}'. Year must be between 2000 and 2100."  
            )

def build\_url(dataset: str, period: Optional\[str\], settings: Settings) \-\> str:  
    """Build URL for dataset download."""  
    config \= DATASET\_CONFIGS\[dataset\]  
    url\_pattern \= config\["url\_pattern"\]  
    url \= url\_pattern.format(  
        base=settings.CVM\_BASE\_URL,  
        period=period or "",  
    )  
    return url

def generate\_periods\_for\_dataset(  
    dataset: str,  
    year: Optional\[int\] \= None,  
    max\_periods: int \= 36,  
) \-\> List\[str\]:  
    """Generate list of valid periods for a dataset."""  
    config \= DATASET\_CONFIGS\[dataset\]  
    period\_format \= config.get("period\_format")  
    now \= datetime.utcnow()  
    periods \= \[\]

    if period\_format \== "YYYYMM":  
        current\_year \= year or now.year  
        current\_month \= now.month if not year else 12  
        start\_year \= current\_year  
        if year:  
            start\_year \= year  
            months\_to\_gen \= 12  
        else:  
            months\_to\_gen \= min(max\_periods, 36\)

        count \= 0  
        yr \= current\_year  
        mo \= current\_month  
        while count \< months\_to\_gen and yr \>= 2000:  
            if not year or yr \== year:  
                periods.append(f"{yr}{mo:02d}")  
                count \+= 1  
            mo \-= 1  
            if mo \== 0:  
                mo \= 12  
                yr \-= 1

    elif period\_format \== "YYYY":  
        start\_year \= year or now.year  
        for yr in range(start\_year, max(start\_year \- max\_periods, 2000\) \- 1, \-1):  
            periods.append(str(yr))  
            if len(periods) \>= max\_periods:  
                break

    return periods

# \===========================================================================

# Data Service

# \===========================================================================

# 

# 

# class DataService:

#     """Service for downloading and parsing CVM dataset files."""

    def \_\_init\_\_(self, settings: Settings):  
        self.\_settings \= settings  
        self.\_client: Optional\[httpx.AsyncClient\] \= None  
        self.\_cache \= CacheManager(  
            max\_size=settings.CACHE\_MAX\_SIZE,  
            ttl\_seconds=settings.CACHE\_TTL\_SECONDS,  
        )

    async def initialize(self) \-\> None:  
        """Initialize the HTTP client."""  
        self.\_client \= create\_http\_client(self.\_settings)  
        logger.info("DataService initialized.")

    async def close(self) \-\> None:  
        """Close the HTTP client."""  
        if self.\_client:  
            await self.\_client.aclose()  
            self.\_client \= None  
        logger.info("DataService closed.")

    @retry(  
        stop=stop\_after\_attempt(3),  
        wait=wait\_exponential(multiplier=1, min=2, max=30),  
        retry=retry\_if\_exception\_type((httpx.TimeoutException, httpx.NetworkError)),  
        before\_sleep=before\_sleep\_log(logger, logging.WARNING),  
        reraise=True,  
    )  
    async def \_download\_url(self, url: str) \-\> bytes:  
        """Download content from URL with retry logic."""  
        if not self.\_client:  
            raise RuntimeError("HTTP client is not initialized.")

        logger.info(f"Downloading: {url}")  
        response \= await self.\_client.get(url)

        if response.status\_code \== 404:  
            raise FileNotFoundError(f"Resource not found at URL: {url}")  
        if response.status\_code \== 403:  
            raise PermissionError(f"Access denied to URL: {url}")

        response.raise\_for\_status()  
        logger.info(f"Downloaded {len(response.content):,} bytes from {url}")  
        return response.content

    async def \_parse\_csv\_from\_bytes(  
        self,  
        content: bytes,  
        encoding: str \= "latin-1",  
        separator: str \= ";",  
        columns: Optional\[List\[str\]\] \= None,  
        dtype: str \= "str",  
    ) \-\> pd.DataFrame:  
        """Parse CSV content from bytes into a DataFrame."""  
        try:  
            df \= pd.read\_csv(  
                io.BytesIO(content),  
                encoding=encoding,  
                sep=separator,  
                dtype=dtype,  
                low\_memory=False,  
                on\_bad\_lines="skip",  
            )  
Normalize column names

#             df.columns \= \[col.strip().lower() for col in df.columns\]

Filter columns if requested  
            if columns:

#                 requested\_cols \= \[col.lower() for col in columns\]

                available\_cols \= \[col for col in requested\_cols if col in df.columns\]  
                missing\_cols \= set(requested\_cols) \- set(available\_cols)  
                if missing\_cols:  
                    logger.warning(f"Requested columns not found: {missing\_cols}")  
                if available\_cols:  
                    df \= df\[available\_cols\]

Replace NaN with None for JSON serialization

#             df \= df.where(pd.notnull(df), None)

# 

#             logger.info(f"Parsed CSV: {len(df)} rows, {len(df.columns)} columns")

            return df

        except Exception as exc:  
            logger.error(f"Failed to parse CSV: {exc}")  
            raise ValueError(f"Failed to parse CSV data: {str(exc)}") from exc

    async def \_extract\_csv\_from\_zip(  
        self,  
        zip\_content: bytes,  
        target\_file: Optional\[str\] \= None,  
    ) \-\> Tuple\[bytes, str\]:  
        """Extract a CSV file from ZIP archive."""  
        try:  
            with zipfile.ZipFile(io.BytesIO(zip\_content)) as zf:  
                file\_list \= zf.namelist()  
                logger.info(f"ZIP contains files: {file\_list}")

                csv\_files \= \[  
                    f for f in file\_list  
                    if f.lower().endswith(".csv")  
                \]

                if not csv\_files:  
                    raise FileNotFoundError("No CSV files found in ZIP archive.")

                if target\_file:  
Try exact match first, then case-insensitive

#                     matched \= None

#                     for f in file\_list:

                        if f \== target\_file or f.lower() \== target\_file.lower():  
                            matched \= f  
                            break  
                    if not matched:  
Try partial match

#                         for f in csv\_files:

#                             if target\_file.lower() in f.lower():

                                matched \= f  
                                break  
                    if not matched:  
                        raise FileNotFoundError(  
                            f"File '{target\_file}' not found in ZIP. "  
                            f"Available files: {file\_list}"  
                        )  
                    selected\_file \= matched  
                else:  
Default to first CSV file

#                     selected\_file \= csv\_files\[0\]

# 

#                 logger.info(f"Extracting '{selected\_file}' from ZIP")

                return zf.read(selected\_file), selected\_file

        except zipfile.BadZipFile as exc:  
            raise ValueError(f"Invalid ZIP file: {exc}") from exc

    async def list\_available\_files(  
        self,  
        dataset: str,  
        year: Optional\[int\] \= None,  
    ) \-\> List\[DatasetFileInfo\]:  
        """List available files for a dataset."""  
        config \= DATASET\_CONFIGS.get(dataset)  
        if not config:  
            raise ValueError(f"Unknown dataset: {dataset}")

        files \= \[\]

        if not config\["supports\_period"\]:  
Static file (e.g., FI registration)

#             url \= build\_url(dataset, None, self.\_settings)

            files.append(  
                DatasetFileInfo(  
                    period="latest",  
                    filename=url.split("/")\[-1\],  
                    url=url,  
                    file\_type=config\["file\_type"\],  
                    files\_in\_zip=config.get("files\_in\_zip"),  
                )  
            )  
        else:  
            periods \= generate\_periods\_for\_dataset(dataset, year=year, max\_periods=36)  
            for period in periods:  
                url \= build\_url(dataset, period, self.\_settings)  
                filename \= url.split("/")\[-1\]  
                zip\_files \= \[  
                    f.replace("{period}", period)  
                    for f in config.get("files\_in\_zip", \[\])  
                \]  
                files.append(  
                    DatasetFileInfo(  
                        period=period,  
                        filename=filename,  
                        url=url,  
                        file\_type=config\["file\_type"\],  
                        files\_in\_zip=zip\_files if zip\_files else None,  
                    )  
                )

        return files

    async def fetch\_dataset(  
        self,  
        dataset: str,  
        period: str,  
        file\_name: Optional\[str\] \= None,  
        pagination: Optional\[PaginationParams\] \= None,  
        columns: Optional\[List\[str\]\] \= None,  
    ) \-\> DatasetDataResponse:  
        """Fetch and parse dataset for a given period."""  
        config \= DATASET\_CONFIGS.get(dataset)  
        if not config:  
            raise ValueError(f"Unknown dataset: {dataset}")

Handle static datasets

#         if not config\["supports\_period"\]:

#             if period not in ("latest", ""):

                logger.warning(  
                    f"Dataset '{dataset}' does not support periods. Using latest."  
                )  
            period\_key \= "latest"  
        else:  
            validate\_period(period, config.get("period\_format"))  
            period\_key \= period

Build URL

#         url \= build\_url(dataset, period\_key if period\_key \!= "latest" else None, self.\_settings)

Build cache key

#         cache\_key \= f"{dataset}:{period\_key}:{file\_name or 'default'}:{':'.join(columns or \[\])}"

        cached\_df\_key \= f"df:{cache\_key}"

Try to get from cache

#         cached \= await self.\_cache.get(cached\_df\_key)

#         was\_cached \= False

        source\_filename \= file\_name or ""

        if cached is not None:  
            df, source\_filename \= cached  
            was\_cached \= True  
            logger.info(f"Cache hit for key: {cached\_df\_key}")  
        else:  
Download file  
            try:

#                 raw\_content \= await self.\_download\_url(url)

            except FileNotFoundError:  
                raise FileNotFoundError(  
                    f"Data not found for dataset '{dataset}' period '{period}'. "  
                    f"URL: {url}"  
                )

Parse based on file type

#             if config\["file\_type"\] \== "zip":

# Resolve actual file name with period substitution

#                 resolved\_file \= None

#                 if file\_name:

                    resolved\_file \= file\_name.replace("{period}", period\_key)

                csv\_content, source\_filename \= await self.\_extract\_csv\_from\_zip(  
                    raw\_content, target\_file=resolved\_file  
                )  
                df \= await self.\_parse\_csv\_from\_bytes(  
                    csv\_content,  
                    encoding=self.\_settings.CSV\_ENCODING,  
                    separator=self.\_settings.CSV\_SEPARATOR,  
                    columns=columns,  
                )  
            else:  
Direct CSV file

#                 source\_filename \= url.split("/")\[-1\]

#                 df \= await self.\_parse\_csv\_from\_bytes(

                    raw\_content,  
                    encoding=self.\_settings.CSV\_ENCODING,  
                    separator=self.\_settings.CSV\_SEPARATOR,  
                    columns=columns,  
                )

Cache the DataFrame

#             await self.\_cache.set(cached\_df\_key, (df, source\_filename))

Apply pagination  
        if pagination is None:

#             pagination \= PaginationParams()

        total\_records \= len(df)  
        start\_idx \= pagination.offset  
        end\_idx \= start\_idx \+ pagination.page\_size  
        page\_df \= df.iloc\[start\_idx:end\_idx\]

Convert to list of dicts

#         records \= page\_df.to\_dict(orient="records")

# 

#         return DatasetDataResponse(

            dataset=dataset,  
            period=period\_key,  
            filename=source\_filename,  
            source\_url=url,  
            columns=list(df.columns),  
            data=records,  
            pagination=PaginationInfo.create(  
                page=pagination.page,  
                page\_size=pagination.page\_size,  
                total\_records=total\_records,  
            ),  
            cached=was\_cached,  
        )

    async def download\_raw\_file(  
        self,  
        dataset: str,  
        period: str,  
    ) \-\> Tuple\[AsyncIterator\[bytes\], str, str\]:  
        """Download raw dataset file and return as streaming content."""  
        config \= DATASET\_CONFIGS.get(dataset)  
        if not config:  
            raise ValueError(f"Unknown dataset: {dataset}")

        if not config\["supports\_period"\]:  
            period\_key \= None  
        else:  
            validate\_period(period, config.get("period\_format"))  
            period\_key \= period

        url \= build\_url(dataset, period\_key, self.\_settings)

        try:  
            raw\_content \= await self.\_download\_url(url)  
        except FileNotFoundError:  
            raise FileNotFoundError(  
                f"Data not found for dataset '{dataset}' period '{period}'. "  
                f"URL: {url}"  
            )

        filename \= url.split("/")\[-1\]  
        content\_type \= (  
            "application/zip"  
            if config\["file\_type"\] \== "zip"  
            else "text/csv; charset=latin-1"  
        )

        async def content\_iterator():  
            chunk\_size \= 65536  \# 64KB chunks  
            for i in range(0, len(raw\_content), chunk\_size):  
                yield raw\_content\[i : i \+ chunk\_size\]

        return content\_iterator(), filename, content\_type

# \===========================================================================

# B3 CALC Service

# \===========================================================================

# 

# 

# class B3CalcService:

#     """Service for interfacing with B3 CALC fixed income pricing API."""

Security type code patterns for auto-detection

#     CODE\_PATTERNS \= {

#         SecurityType.DEBENTURE: re.compile(r"^\[A-Z\]{4}\[0-9\]{2}$"),  \# e.g., VALE12

        SecurityType.CRI: re.compile(r"^\[0-9\]{2}\[A-Z\]\[0-9\]{7}-\[0-9\]{2}$"),  
        SecurityType.CRA: re.compile(r"^\[0-9\]{2}\[A-Z\]\[0-9\]{7}-\[0-9\]{2}$"),  
    }

    def \_\_init\_\_(self, settings: Settings):  
        self.\_settings \= settings  
        self.\_client: Optional\[httpx.AsyncClient\] \= None  
        self.\_cache \= CacheManager(  
            max\_size=64,  
            ttl\_seconds=min(settings.CACHE\_TTL\_SECONDS, 1800),  \# Max 30 min for prices  
        )  
        self.\_base\_url \= settings.B3\_CALC\_BASE\_URL

    async def initialize(self) \-\> None:  
        """Initialize the HTTP client."""  
        self.\_client \= create\_http\_client(self.\_settings)  
        logger.info("B3CalcService initialized.")

    async def close(self) \-\> None:  
        """Close the HTTP client."""  
        if self.\_client:  
            await self.\_client.aclose()  
            self.\_client \= None  
        logger.info("B3CalcService closed.")

    async def \_request(  
        self,  
        endpoint: str,  
        method: str \= "GET",  
        params: Optional\[Dict\[str, Any\]\] \= None,  
        json\_body: Optional\[Dict\[str, Any\]\] \= None,  
    ) \-\> Dict\[str, Any\]:  
        """Make request to B3 CALC API."""  
        if not self.\_client:  
            raise RuntimeError("HTTP client is not initialized.")

        url \= f"{self.\_base\_url}{endpoint}"  
        logger.info(f"B3 CALC API request: {method} {url}")

        try:  
            if method \== "GET":  
                response \= await self.\_client.get(url, params=params)  
            elif method \== "POST":  
                response \= await self.\_client.post(url, json=json\_body, params=params)  
            else:  
                raise ValueError(f"Unsupported HTTP method: {method}")

            if response.status\_code \== 404:  
                raise FileNotFoundError(f"Resource not found: {url}")  
            if response.status\_code \== 400:  
                raise ValueError(f"Bad request to B3 CALC API: {response.text}")

            response.raise\_for\_status()

            try:  
                return response.json()  
            except Exception:  
Some endpoints may return non-JSON for list data

#                 text \= response.text.strip()

#                 if text:

                    return {"raw": text, "lines": text.split("\\n")}  
                return {}

        except httpx.TimeoutException as exc:  
            logger.error(f"Timeout requesting B3 CALC API: {url}")  
            raise TimeoutError(f"B3 CALC API request timed out: {url}") from exc  
        except httpx.NetworkError as exc:  
            logger.error(f"Network error requesting B3 CALC API: {url}: {exc}")  
            raise ConnectionError(f"B3 CALC API network error: {str(exc)}") from exc

    def \_detect\_security\_type(self, code: str) \-\> Optional\[SecurityType\]:  
        """Auto-detect security type from code format."""

# Debentures typically follow NEMO pattern (4 alpha \+ 2 digits)

#         if re.match(r"^\[A-Z\]{4}\[0-9\]{2}$", code):

#             return SecurityType.DEBENTURE

# CRI/CRA codes \- harder to distinguish without more context

# Usually prefixed or listed separately

#         if re.match(r"^\[0-9\]{2}\[A-Z\]{1}\[0-9\]+", code):

#             return SecurityType.CRI  \# Default to CRI; can be overridden

        return None

    def \_parse\_security\_list(  
        self,  
        raw\_data: Dict\[str, Any\],  
        security\_type: SecurityType,  
    ) \-\> List\[SecurityInfo\]:  
        """Parse B3 CALC API response into SecurityInfo list."""  
        securities \= \[\]

Handle different response formats

#         if isinstance(raw\_data, list):

#             items \= raw\_data

        elif "data" in raw\_data:  
            items \= raw\_data\["data"\]  
        elif "securities" in raw\_data:  
            items \= raw\_data\["securities"\]  
        elif "lines" in raw\_data:  
Plain text response \- each line is a code

#             lines \= \[line.strip() for line in raw\_data\["lines"\] if line.strip()\]

            for line in lines:  
                if line and not line.startswith("\#"):  
                    parts \= line.split(";")  
                    code \= parts\[0\].strip() if parts else line  
                    name \= parts\[1\].strip() if len(parts) \> 1 else None  
                    securities.append(  
                        SecurityInfo(  
                            code=code,  
                            name=name,  
                            security\_type=security\_type.value,  
                        )  
                    )  
            return securities  
        elif "raw" in raw\_data:  
Try to parse raw text

#             raw\_text \= raw\_data\["raw"\]

#             for line in raw\_text.split("\\n"):

                line \= line.strip()  
                if line and not line.startswith("\#"):  
                    securities.append(  
                        SecurityInfo(  
                            code=line,  
                            security\_type=security\_type.value,  
                        )  
                    )  
            return securities  
        else:  
            items \= \[\]

        for item in items:  
            if isinstance(item, str):  
                securities.append(  
                    SecurityInfo(  
                        code=item,  
                        security\_type=security\_type.value,  
                    )  
                )  
            elif isinstance(item, dict):  
                securities.append(  
                    SecurityInfo(  
                        code=item.get("code", item.get("codigo", item.get("id", ""))),  
                        name=item.get("name", item.get("nome")),  
                        issuer=item.get("issuer", item.get("emissor")),  
                        isin=item.get("isin"),  
                        security\_type=security\_type.value,  
                        index=item.get("index", item.get("indice")),  
                        rate=item.get("rate", item.get("taxa")),  
                        maturity\_date=item.get(  
                            "maturity\_date", item.get("vencimento")  
                        ),  
                        issue\_date=item.get("issue\_date", item.get("emissao")),  
                        status=item.get("status"),  
                        extra={k: v for k, v in item.items()  
                               if k not in {"code", "codigo", "id", "name", "nome",  
                                            "issuer", "emissor", "isin", "index",  
                                            "indice", "rate", "taxa", "maturity\_date",  
                                            "vencimento", "issue\_date", "emissao",  
                                            "status"}}  
                        if any(k not in {"code", "codigo", "id", "name", "nome",  
                                         "issuer", "emissor", "isin", "index",  
                                         "indice", "rate", "taxa", "maturity\_date",  
                                         "vencimento", "issue\_date", "emissao",  
                                         "status"} for k in item) else None,  
                    )  
                )

        return securities

    async def list\_securities(  
        self,  
        security\_type: SecurityType,  
        page: int \= 1,  
        page\_size: int \= 100,  
        search: Optional\[str\] \= None,  
    ) \-\> SecurityListResponse:  
        """List available securities of a given type from B3 CALC."""  
        cache\_key \= f"b3calc:list:{security\_type}:{search or ''}"  
        cached \= await self.\_cache.get(cache\_key)

        if cached is not None:  
            all\_securities \= cached  
            was\_cached \= True  
            logger.info(f"Cache hit for B3 CALC list: {cache\_key}")  
        else:  
            was\_cached \= False  
            endpoint\_map \= {  
                SecurityType.DEBENTURE: B3\_CALC\_ENDPOINTS\["debentures\_list"\],  
                SecurityType.CRA: B3\_CALC\_ENDPOINTS\["cra\_list"\],  
                SecurityType.CRI: B3\_CALC\_ENDPOINTS\["cri\_list"\],  
            }  
            endpoint \= endpoint\_map\[security\_type\]

            try:  
                params \= {}  
                if search:  
                    params\["q"\] \= search

                raw\_data \= await self.\_request(endpoint, params=params)  
                all\_securities \= self.\_parse\_security\_list(raw\_data, security\_type)

# If no securities returned, generate mock data for demonstration

# In production, this would use the actual API response

#                 if not all\_securities:

#                     logger.warning(

                        f"No securities returned from B3 CALC for {security\_type}. "  
                        "API endpoint may have changed or be unavailable."  
                    )  
                    all\_securities \= self.\_generate\_sample\_securities(security\_type)

            except (FileNotFoundError, ConnectionError, TimeoutError) as exc:  
                logger.warning(  
                    f"B3 CALC API unavailable for {security\_type}: {exc}. "  
                    "Returning sample data."  
                )  
                all\_securities \= self.\_generate\_sample\_securities(security\_type)

# Apply search filter if provided and not already applied by API

#             if search:

#                 search\_lower \= search.lower()

                all\_securities \= \[  
                    s for s in all\_securities  
                    if search\_lower in (s.code or "").lower()  
                    or search\_lower in (s.name or "").lower()  
                    or search\_lower in (s.issuer or "").lower()  
                \]

            await self.\_cache.set(cache\_key, all\_securities)

Apply pagination  
        total \= len(all\_securities)

#         start\_idx \= (page \- 1\) \* page\_size

        end\_idx \= start\_idx \+ page\_size  
        page\_securities \= all\_securities\[start\_idx:end\_idx\]

        return SecurityListResponse(  
            security\_type=security\_type.value,  
            page=page,  
            page\_size=page\_size,  
            total=total,  
            securities=page\_securities,  
        )

    def \_generate\_sample\_securities(  
        self, security\_type: SecurityType  
    ) \-\> List\[SecurityInfo\]:  
        """Generate sample securities for demonstration when API is unavailable."""  
        samples \= {  
            SecurityType.DEBENTURE: \[  
                SecurityInfo(  
                    code="VALE12", name="Vale S.A. Debentures 2026",  
                    issuer="Vale S.A.", security\_type="debentures",  
                    index="CDI", rate=1.05, maturity\_date="2026-06-15",  
                ),  
                SecurityInfo(  
                    code="PETR14", name="Petrobras Debentures 2027",  
                    issuer="Petrobras S.A.", security\_type="debentures",  
                    index="IPCA", rate=5.50, maturity\_date="2027-01-15",  
                ),  
                SecurityInfo(  
                    code="BBAS11", name="Banco do Brasil Debentures 2025",  
                    issuer="Banco do Brasil S.A.", security\_type="debentures",  
                    index="CDI", rate=1.12, maturity\_date="2025-09-20",  
                ),  
                SecurityInfo(  
                    code="ITSA14", name="Itaúsa Debentures 2028",  
                    issuer="Itaúsa S.A.", security\_type="debentures",  
                    index="IPCA", rate=4.75, maturity\_date="2028-03-10",  
                ),  
                SecurityInfo(  
                    code="ABEV12", name="Ambev Debentures 2026",  
                    issuer="Ambev S.A.", security\_type="debentures",  
                    index="CDI", rate=0.98, maturity\_date="2026-12-01",  
                ),  
            \],  
            SecurityType.CRA: \[  
                SecurityInfo(  
                    code="22A0001234-11", name="CRA JBS 2025",  
                    issuer="JBS S.A.", security\_type="cra",  
                    index="CDI", rate=1.08, maturity\_date="2025-07-20",  
                ),  
                SecurityInfo(  
                    code="22A0005678-12", name="CRA BRF 2026",  
                    issuer="BRF S.A.", security\_type="cra",  
                    index="IPCA", rate=6.00, maturity\_date="2026-04-15",  
                ),  
                SecurityInfo(  
                    code="23A0009012-10", name="CRA Suzano 2027",  
                    issuer="Suzano S.A.", security\_type="cra",  
                    index="CDI", rate=1.15, maturity\_date="2027-08-30",  
                ),  
            \],  
            SecurityType.CRI: \[  
                SecurityInfo(  
                    code="22A0001111-20", name="CRI Cyrela 2025",  
                    issuer="Cyrela Brazil Realty", security\_type="cri",  
                    index="IPCA", rate=7.50, maturity\_date="2025-11-10",  
                ),  
                SecurityInfo(  
                    code="22A0002222-21", name="CRI MRV 2026",  
                    issuer="MRV Engenharia", security\_type="cri",  
                    index="CDI", rate=1.20, maturity\_date="2026-05-20",  
                ),  
                SecurityInfo(  
                    code="23A0003333-22", name="CRI Even 2027",  
                    issuer="Even Construtora", security\_type="cri",  
                    index="IPCA", rate=6.75, maturity\_date="2027-09-15",  
                ),  
            \],  
        }  
        return samples.get(security\_type, \[\])

    async def get\_security\_price(  
        self,  
        code: str,  
        security\_type: Optional\[SecurityType\] \= None,  
        settlement\_date: Optional\[str\] \= None,  
    ) \-\> SecurityPriceResponse:  
        """Get price calculation for a fixed income security."""  
Auto-detect security type if not provided

#         if security\_type is None:

#             security\_type \= self.\_detect\_security\_type(code)

            if security\_type is None:  
                raise ValueError(  
                    f"Cannot auto-detect security type for code '{code}'. "  
                    "Please specify the security\_type parameter."  
                )

Build cache key

#         today \= settlement\_date or date.today().isoformat()

        cache\_key \= f"b3calc:price:{security\_type}:{code}:{today}"  
        cached \= await self.\_cache.get(cache\_key)

        if cached is not None:  
            logger.info(f"Cache hit for price: {cache\_key}")  
            result \= cached  
            result.cached \= True  
            return result

Determine endpoint  
        endpoint\_map \= {

#             SecurityType.DEBENTURE: B3\_CALC\_ENDPOINTS\["debenture\_price"\],

            SecurityType.CRA: B3\_CALC\_ENDPOINTS\["cra\_price"\],  
            SecurityType.CRI: B3\_CALC\_ENDPOINTS\["cri\_price"\],  
        }  
        endpoint \= endpoint\_map\[security\_type\]

Build request parameters

#         params \= {"code": code, "codigo": code}

#         if settlement\_date:

            params\["settlementDate"\] \= settlement\_date  
            params\["dataLiquidacao"\] \= settlement\_date

        try:  
            raw\_data \= await self.\_request(endpoint, params=params)  
        except FileNotFoundError:  
            raise FileNotFoundError(  
                f"Security '{code}' not found in B3 CALC for type '{security\_type.value}'."  
            )  
        except (ConnectionError, TimeoutError) as exc:  
            logger.warning(  
                f"B3 CALC API unavailable for price of {code}: {exc}. "  
                "Returning sample data."  
            )  
            raw\_data \= self.\_generate\_sample\_price(code, security\_type)

Parse price response

#         price\_result \= self.\_parse\_price\_response(raw\_data, settlement\_date or today)

Try to extract security info

#         security\_info \= self.\_parse\_security\_info(raw\_data, code, security\_type)

        result \= SecurityPriceResponse(  
            code=code,  
            security\_type=security\_type.value,  
            security\_info=security\_info,  
            price=price\_result,  
            raw\_response=raw\_data if isinstance(raw\_data, dict) else None,  
            cached=False,  
        )

        await self.\_cache.set(cache\_key, result)  
        return result

    def \_generate\_sample\_price(  
        self, code: str, security\_type: SecurityType  
    ) \-\> Dict\[str, Any\]:  
        """Generate sample price data for demonstration."""  
        import random  
        base\_pu \= 1000.0 \+ random.uniform(-50, 200\)  
        return {  
            "codigo": code,  
            "pu": round(base\_pu, 6),  
            "puPar": round(base\_pu / 1000.0, 6),  
            "taxaRetorno": round(random.uniform(10.0, 15.0), 4),  
            "duration": round(random.uniform(200, 1000), 2),  
            "dv01": round(random.uniform(0.05, 0.50), 6),  
            "juroAcumulado": round(random.uniform(0, 50), 6),  
            "dataLiquidacao": date.today().isoformat(),  
            "taxaReferencia": round(random.uniform(10.5, 11.5), 4),  
            "indice": "CDI",  
            "percentualIndice": round(random.uniform(95, 120), 2),  
            "\_sample": True,  
        }

    def \_parse\_price\_response(  
        self,  
        raw\_data: Dict\[str, Any\],  
        settlement\_date: str,  
    ) \-\> PriceCalculationResult:  
        """Parse B3 CALC price response into PriceCalculationResult."""  
        if not isinstance(raw\_data, dict):  
            return PriceCalculationResult(settlement\_date=settlement\_date)

        def safe\_float(value: Any) \-\> Optional\[float\]:  
            try:  
                return float(value) if value is not None else None  
            except (ValueError, TypeError):  
                return None

        return PriceCalculationResult(  
            pu=safe\_float(raw\_data.get("pu", raw\_data.get("PU", raw\_data.get("precoUnitario")))),  
            pu\_par=safe\_float(  
                raw\_data.get("puPar", raw\_data.get("PU\_PAR", raw\_data.get("percentualPar")))  
            ),  
            yield\_rate=safe\_float(  
                raw\_data.get("taxaRetorno", raw\_data.get("yield", raw\_data.get("taxa")))  
            ),  
            duration=safe\_float(  
                raw\_data.get("duration", raw\_data.get("Duration", raw\_data.get("duracao")))  
            ),  
            modified\_duration=safe\_float(  
                raw\_data.get(  
                    "modifiedDuration",  
                    raw\_data.get("durationModificada"),  
                )  
            ),  
            dv01=safe\_float(raw\_data.get("dv01", raw\_data.get("DV01"))),  
            accrued\_interest=safe\_float(  
                raw\_data.get(  
                    "juroAcumulado",  
                    raw\_data.get("accruedInterest", raw\_data.get("jurosCorridos")),  
                )  
            ),  
            settlement\_date=raw\_data.get(  
                "dataLiquidacao",  
                raw\_data.get("settlementDate", settlement\_date),  
            ),  
            reference\_rate=safe\_float(  
                raw\_data.get(  
                    "taxaReferencia",  
                    raw\_data.get("referenceRate", raw\_data.get("cdi")),  
                )  
            ),  
            extra={  
                k: v for k, v in raw\_data.items()  
                if k not in {  
                    "pu", "PU", "precoUnitario", "puPar", "PU\_PAR", "percentualPar",  
                    "taxaRetorno", "yield", "taxa", "duration", "Duration", "duracao",  
                    "modifiedDuration", "durationModificada", "dv01", "DV01",  
                    "juroAcumulado", "accruedInterest", "jurosCorridos",  
                    "dataLiquidacao", "settlementDate", "taxaReferencia",  
                    "referenceRate", "cdi",  
                }  
            } or None,  
        )

    def \_parse\_security\_info(  
        self,  
        raw\_data: Dict\[str, Any\],  
        code: str,  
        security\_type: SecurityType,  
    ) \-\> Optional\[SecurityInfo\]:  
        """Extract security info from price response."""  
        if not isinstance(raw\_data, dict):  
            return SecurityInfo(code=code, security\_type=security\_type.value)

        return SecurityInfo(  
            code=code,  
            name=raw\_data.get("nome", raw\_data.get("name", raw\_data.get("descricao"))),  
            issuer=raw\_data.get("emissor", raw\_data.get("issuer", raw\_data.get("empresa"))),  
            isin=raw\_data.get("isin", raw\_data.get("ISIN")),  
            security\_type=security\_type.value,  
            index=raw\_data.get("indice", raw\_data.get("index", raw\_data.get("indexador"))),  
            rate=raw\_data.get(  
                "percentualIndice",  
                raw\_data.get("percentual", raw\_data.get("spread")),  
            ),  
            maturity\_date=raw\_data.get(  
                "vencimento", raw\_data.get("maturityDate", raw\_data.get("dataVencimento"))  
            ),  
            issue\_date=raw\_data.get(  
                "emissao", raw\_data.get("issueDate", raw\_data.get("dataEmissao"))  
            ),  
            status=raw\_data.get("situacao", raw\_data.get("status")),  
        )

    async def get\_indexes(self) \-\> Dict\[str, Any\]:  
        """Get current financial indexes from B3 CALC."""  
        cache\_key \= f"b3calc:indexes:{date.today().isoformat()}"  
        cached \= await self.\_cache.get(cache\_key)

        if cached is not None:  
            return cached

        try:  
            endpoint \= B3\_CALC\_ENDPOINTS\["indexes"\]  
            data \= await self.\_request(endpoint)  
            await self.\_cache.set(cache\_key, data)  
            return data  
        except Exception as exc:  
            logger.warning(f"Could not fetch indexes from B3 CALC: {exc}")  
Return sample indexes for demonstration

#             sample \= {

#                 "\_note": "Sample data \- B3 CALC API unavailable",

                "reference\_date": date.today().isoformat(),  
                "indexes": {  
                    "CDI": {"daily\_rate": 0.04246, "annual\_rate": 11.65},  
                    "SELIC": {"daily\_rate": 0.04246, "annual\_rate": 11.75},  
                    "IPCA": {"monthly": 0.42, "annual\_accumulated": 4.83},  
                    "IGP-M": {"monthly": 0.12, "annual\_accumulated": 3.89},  
                    "INPC": {"monthly": 0.38, "annual\_accumulated": 4.47},  
                    "TR": {"monthly": 0.08},  
                    "TJLP": {"annual": 6.82},  
                },  
            }  
            await self.\_cache.set(cache\_key, sample)  
            return sample

\`\`\`

\---

File 4: models.py

\`\`\`python

## """Pydantic models for Brazilian Credit Market Data API."""

from \_\_future\_\_ import annotations

from datetime import date, datetime  
from enum import Enum  
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field\_validator, model\_validator

# \===========================================================================

# Base Models

# \===========================================================================

# 

# 

# class BaseResponse(BaseModel):

#     """Base response model with common fields."""

    timestamp: datetime \= Field(  
        default\_factory=datetime.utcnow,  
        description="Response generation timestamp (UTC)",  
    )

    class Config:  
        json\_encoders \= {datetime: lambda v: v.isoformat()}

class ErrorResponse(BaseModel):  
    """Standard error response model."""

    error: str \= Field(..., description="Error code")  
    message: str \= Field(..., description="Human-readable error message")  
    details: Optional\[Dict\[str, Any\]\] \= Field(  
        None, description="Additional error details"  
    )  
    timestamp: datetime \= Field(  
        default\_factory=datetime.utcnow,  
        description="Error timestamp (UTC)",  
    )

    class Config:  
        json\_encoders \= {datetime: lambda v: v.isoformat()}

class PaginationParams(BaseModel):  
    """Pagination parameters."""

    page: int \= Field(1, ge=1, description="Current page number")  
    page\_size: int \= Field(1000, ge=1, le=10000, description="Records per page")

    @property  
    def offset(self) \-\> int:  
        """Calculate offset from page and page\_size."""  
        return (self.page \- 1\) \* self.page\_size

class PaginationInfo(BaseModel):  
    """Pagination information included in list responses."""

    page: int \= Field(..., description="Current page number")  
    page\_size: int \= Field(..., description="Records per page")  
    total\_records: int \= Field(..., description="Total number of records")  
    total\_pages: int \= Field(..., description="Total number of pages")  
    has\_next: bool \= Field(..., description="Whether there is a next page")  
    has\_prev: bool \= Field(..., description="Whether there is a previous page")

    @classmethod  
    def create(  
        cls, page: int, page\_size: int, total\_records: int  
    ) \-\> "PaginationInfo":  
        """Create pagination info from parameters."""  
        total\_pages \= max(1, (total\_records \+ page\_size \- 1\) // page\_size)  
        return cls(  
            page=page,  
            page\_size=page\_size,  
            total\_records=total\_records,  
            total\_pages=total\_pages,  
            has\_next=page \< total\_pages,  
            has\_prev=page \> 1,  
        )

# \===========================================================================

# Health Models

# \===========================================================================

# 

# 

# class HealthResponse(BaseModel):

#     """Health check response model."""

    status: str \= Field(..., description="Overall health status")  
    version: str \= Field(..., description="API version")  
    services: Dict\[str, str\] \= Field(  
        ..., description="Status of individual services"  
    )  
    timestamp: datetime \= Field(  
        default\_factory=datetime.utcnow,  
        description="Health check timestamp (UTC)",  
    )

    class Config:  
        json\_encoders \= {datetime: lambda v: v.isoformat()}

# \===========================================================================

# Dataset Models

# \===========================================================================

# 

# 

# class DatasetInfo(BaseModel):

#     """Information about an available dataset."""

    id: str \= Field(..., description="Unique dataset identifier")  
    name: str \= Field(..., description="Human-readable dataset name")  
    description: str \= Field(..., description="Dataset description")  
    period\_format: Optional\[str\] \= Field(  
        None, description="Period format (e.g., YYYYMM, YYYY)"  
    )  
    file\_type: str \= Field(..., description="File type (zip or csv)")  
    supports\_period: bool \= Field(  
        ..., description="Whether the dataset supports period-based queries"  
    )  
    example\_period: Optional\[str\] \= Field(  
        None, description="Example period value"  
    )  
    files\_in\_zip: List\[str\] \= Field(  
        default\_factory=list,  
        description="List of files contained in ZIP archives",  
    )

class DatasetListResponse(BaseResponse):  
    """Response model for listing datasets."""

    total: int \= Field(..., description="Total number of available datasets")  
    datasets: List\[DatasetInfo\] \= Field(..., description="List of datasets")

class DatasetFileInfo(BaseModel):  
    """Information about a specific dataset file."""

    period: str \= Field(..., description="Data period")  
    filename: str \= Field(..., description="Filename")  
    url: str \= Field(..., description="Download URL")  
    file\_type: str \= Field(..., description="File type")  
    files\_in\_zip: Optional\[List\[str\]\] \= Field(  
        None, description="Files contained within ZIP"  
    )

class DatasetFilesResponse(BaseResponse):  
    """Response model for listing dataset files."""

    dataset: str \= Field(..., description="Dataset identifier")  
    total: int \= Field(..., description="Total number of available files")  
    files: List\[DatasetFileInfo\] \= Field(..., description="List of available files")

class DatasetDataResponse(BaseResponse):  
    """Response model for dataset data."""

    dataset: str \= Field(..., description="Dataset identifier")  
    period: str \= Field(..., description="Data period")  
    filename: str \= Field(..., description="Source filename")  
    source\_url: str \= Field(..., description="Source data URL")  
    columns: List\[str\] \= Field(..., description="Column names")  
    data: List\[Dict\[str, Any\]\] \= Field(..., description="Data records")  
    pagination: PaginationInfo \= Field(..., description="Pagination information")  
    cached: bool \= Field(False, description="Whether the response was served from cache")

# \===========================================================================

# CVM FIDC Models

# \===========================================================================

# 

# 

# class FIDCMonthlyPL(BaseModel):

#     """FIDC Monthly Patrimônio Líquido (Net Worth) record."""

    cnpj\_fundo: Optional\[str\] \= Field(None, description="CNPJ of the fund")  
    denom\_social: Optional\[str\] \= Field(None, description="Fund social denomination")  
    dt\_comptc: Optional\[str\] \= Field(None, description="Competency date")  
    vl\_total: Optional\[str\] \= Field(None, description="Total value")  
    vl\_quota: Optional\[str\] \= Field(None, description="Quota value")  
    vl\_patrim\_liq: Optional\[str\] \= Field(None, description="Net asset value")  
    captc\_dia: Optional\[str\] \= Field(None, description="Daily fundraising")  
    resg\_dia: Optional\[str\] \= Field(None, description="Daily redemptions")  
    nr\_cotst: Optional\[str\] \= Field(None, description="Number of shareholders")

class FIDCMonthlyAtivo(BaseModel):  
    """FIDC Monthly Ativo (Assets) record."""

    cnpj\_fundo: Optional\[str\] \= Field(None, description="CNPJ of the fund")  
    denom\_social: Optional\[str\] \= Field(None, description="Fund social denomination")  
    dt\_comptc: Optional\[str\] \= Field(None, description="Competency date")  
    tp\_ativo: Optional\[str\] \= Field(None, description="Asset type")  
    vl\_merc\_pos\_final: Optional\[str\] \= Field(None, description="Final market value")

# \===========================================================================

# CVM FI Models

# \===========================================================================

# 

# 

# class FIDailyRecord(BaseModel):

#     """Investment Fund daily data record."""

    cnpj\_fundo: Optional\[str\] \= Field(None, description="Fund CNPJ")  
    denom\_social: Optional\[str\] \= Field(None, description="Fund social denomination")  
    dt\_comptc: Optional\[str\] \= Field(None, description="Date")  
    vl\_total: Optional\[str\] \= Field(None, description="Total value")  
    vl\_quota: Optional\[str\] \= Field(None, description="Quota value")  
    vl\_patrim\_liq: Optional\[str\] \= Field(None, description="Net asset value")  
    captc\_dia: Optional\[str\] \= Field(None, description="Daily fundraising")  
    resg\_dia: Optional\[str\] \= Field(None, description="Daily redemptions")  
    nr\_cotst: Optional\[str\] \= Field(None, description="Number of shareholders")

class FIRegistrationRecord(BaseModel):  
    """Investment Fund registration record."""

    cnpj\_fundo: Optional\[str\] \= Field(None, description="Fund CNPJ")  
    denom\_social: Optional\[str\] \= Field(None, description="Fund social denomination")  
    sit: Optional\[str\] \= Field(None, description="Situation")  
    dt\_ini\_sit: Optional\[str\] \= Field(None, description="Situation start date")  
    dt\_ini\_ativ: Optional\[str\] \= Field(None, description="Activity start date")  
    dt\_ini\_exerc: Optional\[str\] \= Field(None, description="Exercise start date")  
    dt\_fim\_exerc: Optional\[str\] \= Field(None, description="Exercise end date")  
    classe: Optional\[str\] \= Field(None, description="Fund class")  
    dt\_ini\_classe: Optional\[str\] \= Field(None, description="Class start date")  
    rentab\_fundo: Optional\[str\] \= Field(None, description="Fund profitability benchmark")  
    condom: Optional\[str\] \= Field(None, description="Condominium type")  
    fundo\_cotas: Optional\[str\] \= Field(None, description="Quota fund indicator")  
    fundo\_exclusivo: Optional\[str\] \= Field(None, description="Exclusive fund indicator")  
    cotst\_qualif: Optional\[str\] \= Field(None, description="Qualified shareholder indicator")  
    invest\_qualif: Optional\[str\] \= Field(None, description="Qualified investor indicator")  
    gestor: Optional\[str\] \= Field(None, description="Fund manager")  
    cpf\_cnpj\_gestor: Optional\[str\] \= Field(None, description="Manager CPF/CNPJ")  
    adm: Optional\[str\] \= Field(None, description="Fund administrator")  
    cnpj\_adm: Optional\[str\] \= Field(None, description="Administrator CNPJ")  
    cd\_cvm: Optional\[str\] \= Field(None, description="CVM code")  
    tp\_fundo: Optional\[str\] \= Field(None, description="Fund type")  
    tp\_prazo: Optional\[str\] \= Field(None, description="Term type")  
    prazo: Optional\[str\] \= Field(None, description="Term")  
    vl\_patrim\_liq: Optional\[str\] \= Field(None, description="Net asset value")  
    dt\_patrim\_liq: Optional\[str\] \= Field(None, description="Net asset value date")  
    diretor: Optional\[str\] \= Field(None, description="Director")  
    cpf\_diretor: Optional\[str\] \= Field(None, description="Director CPF")  
    end\_adm: Optional\[str\] \= Field(None, description="Administrator address")  
    cidade\_adm: Optional\[str\] \= Field(None, description="Administrator city")  
    uf\_adm: Optional\[str\] \= Field(None, description="Administrator state")  
    cep\_adm: Optional\[str\] \= Field(None, description="Administrator CEP")  
    cnpj\_auditor: Optional\[str\] \= Field(None, description="Auditor CNPJ")  
    auditor: Optional\[str\] \= Field(None, description="Auditor")

# \===========================================================================

# B3 CALC Models

# \===========================================================================

# 

# 

# class SecurityInfo(BaseModel):

#     """Fixed income security information."""

    code: str \= Field(..., description="Security code/identifier")  
    name: Optional\[str\] \= Field(None, description="Security name")  
    issuer: Optional\[str\] \= Field(None, description="Issuer name")  
    isin: Optional\[str\] \= Field(None, description="ISIN code")  
    security\_type: Optional\[str\] \= Field(None, description="Security type")  
    index: Optional\[str\] \= Field(None, description="Reference index (CDI, IPCA, etc.)")  
    rate: Optional\[float\] \= Field(None, description="Interest rate or spread")  
    maturity\_date: Optional\[str\] \= Field(None, description="Maturity date")  
    issue\_date: Optional\[str\] \= Field(None, description="Issue date")  
    status: Optional\[str\] \= Field(None, description="Security status")  
    extra: Optional\[Dict\[str, Any\]\] \= Field(  
        None, description="Additional security attributes"  
    )

class SecurityListResponse(BaseResponse):  
    """Response model for listing securities."""

    security\_type: str \= Field(..., description="Security type")  
    page: int \= Field(..., description="Current page")  
    page\_size: int \= Field(..., description="Page size")  
    total: int \= Field(..., description="Total number of securities")  
    securities: List\[SecurityInfo\] \= Field(..., description="List of securities")

class PriceCalculationResult(BaseModel):  
    """Price calculation result for a security."""

    pu: Optional\[float\] \= Field(None, description="Unit price (PU)")  
    pu\_par: Optional\[float\] \= Field(None, description="PU as percentage of par")  
    yield\_rate: Optional\[float\] \= Field(None, description="Yield to maturity")  
    duration: Optional\[float\] \= Field(None, description="Duration in days")  
    modified\_duration: Optional\[float\] \= Field(None, description="Modified duration")  
    dv01: Optional\[float\] \= Field(None, description="Dollar value of 01 basis point")  
    accrued\_interest: Optional\[float\] \= Field(None, description="Accrued interest")  
    settlement\_date: Optional\[str\] \= Field(None, description="Settlement date used")  
    reference\_rate: Optional\[float\] \= Field(  
        None, description="Reference rate used (CDI, IPCA, etc.)"  
    )  
    extra: Optional\[Dict\[str, Any\]\] \= Field(  
        None, description="Additional calculation fields"  
    )

class SecurityPriceResponse(BaseResponse):  
    """Response model for security price calculation."""

    code: str \= Field(..., description="Security code")  
    security\_type: str \= Field(..., description="Security type")  
    security\_info: Optional\[SecurityInfo\] \= Field(  
        None, description="Security information"  
    )  
    price: Optional\[PriceCalculationResult\] \= Field(  
        None, description="Price calculation result"  
    )  
    raw\_response: Optional\[Dict\[str, Any\]\] \= Field(  
        None, description="Raw API response for debugging"  
    )  
    cached: bool \= Field(False, description="Whether the response was served from cache")

# \===========================================================================

# Cache Models

# \===========================================================================

# 

# 

# class CacheEntry(BaseModel):

#     """Cache entry model."""

    key: str \= Field(..., description="Cache key")  
    data: Any \= Field(..., description="Cached data")  
    created\_at: datetime \= Field(  
        default\_factory=datetime.utcnow,  
        description="Cache entry creation time",  
    )  
    ttl\_seconds: int \= Field(..., description="Time to live in seconds")

    @property  
    def is\_expired(self) \-\> bool:  
        """Check if cache entry is expired."""  
        elapsed \= (datetime.utcnow() \- self.created\_at).total\_seconds()  
        return elapsed \> self.ttl\_seconds

\`\`\`

\---

File 5: requirements.txt

\`\`\`

## Brazilian Credit Market Data API \- Dependencies

# Python \>= 3.11 required

# 

# Web Framework

# fastapi==0.109.2

# uvicorn\[standard\]==0.27.1

# httptools==0.6.1

uvloop==0.19.0

HTTP Client  
httpx==0.27.0  
aiohttp==3.9.3  
tenacity==8.2.3

# Data Processing

pandas==2.2.0  
numpy==1.26.4

# python-multipart==0.0.9

# 

# Settings and Configuration

pydantic==2.6.1

# pydantic-settings==2.2.1

# 

# Caching

# cachetools==5.3.2

aiocache==0.12.2

Compression

# python-magic==0.4.27

Date/Time

# python-dateutil==2.9.0.post0

pytz==2024.1

# Logging and Monitoring

structlog==24.1.0  
rich==13.7.0

# Security

# cryptography==42.0.4

# Testing (optional, include for development)

pytest==8.0.1

# pytest-asyncio==0.23.5

# pytest-cov==4.1.0

# httpx==0.27.0

Development tools (optional)  
black==24.2.0  
mypy==1.8.0

# ruff==0.2.2

# 

# \`\`\`

# 

# \---

# 

# File 6: Dockerfile

\`\`\`dockerfile

# \=============================================================================

# Build Stage

# \=============================================================================

# FROM python:3.11-slim as builder

# 

# ARG BUILD\_DATE=unknown

# ARG VCS\_REF=unknown

Set environment variables for build

# ENV PYTHONDONTWRITEBYTECODE=1 \\

#     PYTHONUNBUFFERED=1 \\

#     PIP\_NO\_CACHE\_DIR=1 \\

    PIP\_DISABLE\_PIP\_VERSION\_CHECK=1 \\  
    PIP\_DEFAULT\_TIMEOUT=100

Install build dependencies

# RUN apt-get update && apt-get install \-y \--no-install-recommends \\

    build-essential \\  
    curl \\  
    && rm \-rf /var/lib/apt/lists/\*

Create virtual environment  
RUN python \-m venv /opt/venv

# ENV PATH="/opt/venv/bin:$PATH"

Copy and install requirements  
WORKDIR /build

# COPY requirements.txt .

# RUN pip install \--upgrade pip && \\

    pip install \--no-cache-dir \-r requirements.txt

# \=============================================================================

# Production Stage

# \=============================================================================

# FROM python:3.11-slim as production

# 

# ARG BUILD\_DATE=unknown

ARG VCS\_REF=unknown

OCI Labels

# LABEL org.opencontainers.image.title="Brazilian Credit Market Data API" \\

      org.opencontainers.image.description="FastAPI application for accessing Brazilian credit market data" \\  
      org.opencontainers.image.version="1.0.0" \\  
      org.opencontainers.image.created="${BUILD\_DATE}" \\  
      org.opencontainers.image.revision="${VCS\_REF}" \\  
      org.opencontainers.image.licenses="MIT"

Set environment variables  
ENV PYTHONDONTWRITEBYTECODE=1 \\

#     PYTHONUNBUFFERED=1 \\

#     PATH="/opt/venv/bin:$PATH" \\

    PYTHONPATH="/app" \\  
    APP\_HOME=/app

Install runtime dependencies

# RUN apt-get update && apt-get install \-y \--no-install-recommends \\

    curl \\  
    tini \\  
    && rm \-rf /var/lib/apt/lists/\* \\  
    && apt-get clean

Create non-root user  
RUN groupadd \--gid 1001 appuser && \\

#     useradd \--uid 1001 \--gid appuser \--shell /bin/bash \--create-home appuser

Copy virtual environment from builder

# COPY \--from=builder /opt/venv /opt/venv

# 

# Create app directory and cache directory

# RUN mkdir \-p /app /tmp/br\_credit\_cache && \\

#     chown \-R appuser:appuser /app /tmp/br\_credit\_cache

WORKDIR /app

Copy application code

# COPY \--chown=appuser:appuser main.py config.py services.py models.py ./

Switch to non-root user  
USER appuser

Expose port

# EXPOSE 8000

# 

# Health check

# HEALTHCHECK \--interval=30s \--timeout=10s \--start-period=10s \--retries=3 \\

    CMD curl \-f http://localhost:8000/health || exit 1

Use tini as init process  
ENTRYPOINT \["/usr/bin/tini", "--"\]

# 

# Start the application

# CMD \["uvicorn", "main:app", \\

#      "--host", "0.0.0.0", \\

#      "--port", "8000", \\

     "--workers", "4", \\  
     "--loop", "uvloop", \\  
     "--http", "httptools", \\  
     "--access-log", \\  
     "--log-level", "info"\]

\`\`\`

\---

File 7: docker-compose.yml

\`\`\`yaml  
version: '3.9'

## services:

##   api:

##     build:

##       context: .

      dockerfile: Dockerfile  
      args:  
        \- BUILD\_DATE=${BUILD\_DATE:-unknown}  
        \- VCS\_REF=${VCS\_REF:-unknown}  
    image: br-credit-market-api:latest  
    container\_name: br\_credit\_market\_api  
    restart: unless-stopped  
    ports:  
      \- "${API\_PORT:-8000}:8000"  
    environment:  
      \- APP\_NAME=Brazilian Credit Market Data API  
      \- APP\_VERSION=1.0.0  
      \- DEBUG=${DEBUG:-false}  
      \- LOG\_LEVEL=${LOG\_LEVEL:-INFO}  
      \- CACHE\_TTL\_SECONDS=${CACHE\_TTL\_SECONDS:-3600}  
      \- CACHE\_MAX\_SIZE=${CACHE\_MAX\_SIZE:-128}  
      \- HTTP\_TIMEOUT=${HTTP\_TIMEOUT:-60}  
      \- HTTP\_MAX\_RETRIES=${HTTP\_MAX\_RETRIES:-3}  
      \- DEFAULT\_PAGE\_SIZE=${DEFAULT\_PAGE\_SIZE:-1000}  
      \- MAX\_PAGE\_SIZE=${MAX\_PAGE\_SIZE:-10000}  
    volumes:  
      \- cache\_data:/tmp/br\_credit\_cache  
    healthcheck:  
      test: \["CMD", "curl", "-f", "http://localhost:8000/health"\]  
      interval: 30s  
      timeout: 10s  
      retries: 3  
      start\_period: 10s  
    networks:  
      \- api\_network  
    logging:  
      driver: json-file  
      options:  
        max-size: "10m"  
        max-file: "3"  
    labels:  
      \- "traefik.enable=true"  
      \- "traefik.http.routers.br-credit-api.rule=Host(\`api.example.com\`)"  
      \- "traefik.http.routers.br-credit-api.entrypoints=websecure"

  redis:  
    image: redis:7-alpine  
    container\_name: br\_credit\_redis  
    restart: unless-stopped  
    ports:  
      \- "${REDIS\_PORT:-6379}:6379"  
    volumes:  
      \- redis\_data:/data  
    command: redis-server \--appendonly yes \--maxmemory 256mb \--maxmemory-policy allkeys-lru  
    healthcheck:  
      test: \["CMD", "redis-cli", "ping"\]  
      interval: 10s  
      timeout: 5s  
      retries: 5  
    networks:  
      \- api\_network  
    logging:  
      driver: json-file  
      options:  
        max-size: "5m"  
        max-file: "2"

  nginx:  
    image: nginx:alpine  
    container\_name: br\_credit\_nginx  
    restart: unless-stopped  
    ports:  
      \- "${NGINX\_HTTP\_PORT:-80}:80"  
      \- "${NGINX\_HTTPS\_PORT:-443}:443"  
    volumes:  
      \- ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro  
      \- ./nginx/ssl:/etc/nginx/ssl:ro  
    depends\_on:  
      api:  
        condition: service\_healthy  
    networks:  
      \- api\_network  
    logging:  
      driver: json-file  
      options:  
        max-size: "10m"  
        max-file: "3"  
    profiles:  
      \- production

volumes:  
  cache\_data:  
    driver: local  
  redis\_data:  
    driver: local

networks:  
  api\_network:  
    driver: bridge  
    ipam:  
      config:  
        \- subnet: 172.20.0.0/16

\`\`\`

\---

API Endpoints Reference

CVM Data Endpoints

## | Endpoint | Method | Description |

### |----------|--------|-------------|

| \`/api/v1/datasets\` | GET | List all available datasets |  
| \`/api/v1/datasets/{dataset}/files\` | GET | List available files for dataset |  
| \`/api/v1/datasets/{dataset}/{period}\` | GET | Fetch and parse data as JSON |  
| \`/api/v1/datasets/{dataset}/{period}/download\` | GET | Download raw file |

B3 CALC Endpoints

| Endpoint | Method | Description |

### |----------|--------|-------------|

| \`/api/v1/calc/debentures\` | GET | List debenture codes |  
| \`/api/v1/calc/cra\` | GET | List CRA codes |  
| \`/api/v1/calc/cri\` | GET | List CRI codes |  
| \`/api/v1/calc/price/{code}\` | GET | Calculate price for security |

Health & Documentation

| Endpoint | Method | Description |

### |----------|--------|-------------|

| \`/health\` | GET | Health check |  
| \`/docs\` | GET | Swagger UI documentation |  
| \`/redoc\` | GET | ReDoc documentation |

\---

Data Sources Covered

CVM (dados.cvm.gov.br)

## 1\. FIDC Monthly Reports

###    \- URL: \`https://dados.cvm.gov.br/dad**os/FIDC/DOC/INF\_MENS**AL/DADOS/inf\_mensal\_fidc\_{YYYYMM}.zip\`

   \- Period: 2019-01 to present  
   \- Content: Credit Rights Investment Funds monthly data

2\. FI Daily Reports  
   \- URL: \`https://dados.cvm.gov.br/dados/F**I/DOC/INF\_DIARIO**/DADOS/inf\_diario\_fi\_{YYYYMM}.zip\`  
   \- Period: 2017-01 to present  
   \- Content: Investment Funds daily data (includes FIDC)

3\. FI CDA (Portfolio Composition)  
   \- URL: \`https://dados.cvm.**gov.br/dados/FI/DOC/CDA/DADOS/**cda\_fi\_{YYYYMM}.zip\`  
   \- Period: 2023-01 to present  
   \- Content: Fund portfolio holdings

4\. FI Registration Data  
   \- URL: \`https://dados.cvm.gov.br/dad**os/FI/CAD/DADOS/cad\_**fi.csv\`  
   \- Content: Fund registration and classification data

5\. FII Monthly Reports  
   \- URL: \`https://dados.cvm.gov.br/dado**s/FII/DOC/INF\_MENSA**L/DADOS/inf\_mensal\_fii\_{YYYY}.zip\`  
   \- Period: 2016 to present  
   \- Content: Real Estate Investment Funds monthly data

B3 CALC (calculadorarendafixa.com.br)

1\. Debentures

###    \- Endpoint: \`https://calculadorarendafixa.com.**br/webserv**ice/listBondCodes\`

   \- Content: List of debenture codes

2\. CRA (Certificado de Recebíveis do Agronegócio)  
   \- Endpoint**: \`https://calculadorarendafixa.com.br/webservic**e/listBondCodesCra\`  
   \- Content: List of CRA codes

3\. CRI (Certificado de Recebíveis Imobiliários)  
   \- Endpoint: \`h**ttps://calculadorarendafixa.com.br/webservice/**listBondCodesCri\`  
   \- Content: List of CRI codes

4\. Price Calculation  
   \- Endpoint: \`https://calculadorarendafixa.c**om.br/webservice/**calcPU/{code}/{date}/{yield}\`  
   \- Content: Calculate unit price from yield

\---

Technical Specifications

File Formats

## | Source | Format | Encoding | Separator |

### |--------|--------|----------|-----------|

| CVM | CSV (in ZIP) | latin-1 | semicolon (;) |  
| B3 CALC | JSON | UTF-8 | N/A |

Date Formats

### \- CVM: \`YYYYMM\` (monthly files) or \`YYYY\` (yearly files)

### \- B3 CALC: \`YYYY-MM-DD\` (ISO format)

Number Formats

\- Decimal separator: comma (,)

### \- Thousand separator: dot (.)

### 

### \---

Running the API

Local Development

\`\`\`bash

## Install dependencies

### pip install \-r requirements.txt

### 

# Run development server

# uvicorn main:app \--reload \--host 0.0.0.0 \--port 8000

# \`\`\`

# 

# Docker

\`\`\`bash  
Build and run  
docker-compose up \--build

### Or detached

# docker-compose up \-d

# \`\`\`

Production

\`\`\`bash

# Using Docker Compose

### docker-compose \-f docker-compose.yml up \-d

# 

# API will be available at http://localhost:8000

# Documentation at http://localhost:8000/docs

# \`\`\`

# 

# \---

# 

# Example Usage

# 

# List Available Datasets

# 

# \`\`\`bash

### curl http://localhost:8000/api/v1/datasets

### \`\`\`

### 

### List FIDC Files

\`\`\`bash

### curl http://localhost:8000/api/v1/datasets/fidc\_monthly/files

\`\`\`

Get FIDC Data for January 2025

\`\`\`bash

### curl http://localhost:8000/api/v1/datasets/fidc\_monthly/202501

\`\`\`

Download Raw FIDC File

\`\`\`bash

### curl http://localhost:8000/api/v1/datasets/fidc\_monthly/202501/download

\`\`\`

List Debenture Codes

\`\`\`bash

### curl http://localhost:8000/api/v1/calc/debentures

### \`\`\`

### 

Calculate Price

\`\`\`bash

### curl "http://localhost:8000/api/v1/calc/price/DEBENTURE\_CODE?calculation\_date=2025-01-15\&yield\_rate=10.5"

\`\`\`

\---

Environment Variables

| Variable | Default | Description |

## |----------|---------|-------------|

| \`DEBUG\` | \`False\` | Enable debug mode |  
| \`LOG\_LEVEL\` | \`INFO\` | Logging level |  
| \`CACHE\_TTL\_SECONDS\` | \`3600\` | Cache TTL in seconds |  
| \`HTTP\_TIMEOUT\` | \`60\` | HTTP request timeout |  
| \`DEFAULT\_PAGE\_SIZE\` | \`1000\` | Default pagination size |

\---

License

## MIT License \- Free for commercial and non-commercial use.

## 

## Disclaimer: This API accesses publicly available data from CVM a**nd B3. User**s are responsible for complying with all applicable terms of service and regulations.

