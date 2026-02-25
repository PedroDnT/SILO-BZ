# API Documentation Site

FastAPI-based documentation server with OpenAPI specs and interactive examples.

## Files

\- \`docs\_server.py\` \- FastAPI documentation server  
\- \`static/index.html\` \- Custom landing page  
\- \`static/openapi.yaml\` \- Complete OpenAPI specification  
\- \`Dockerfile.docs\` \- Docker image for docs server

## Features

\- Interactive API explorer  
\- Code examples in multiple languages  
\- Authentication guides  
\- Custom styling

\---

## docs\_server.py

\`\`\`python  
"""FastAPI Documentation Server for Brazilian Financial Data APIs.

This server provides comprehensive documentation for CVM Credit, ANBIMA, and BACEN APIs  
with interactive examples, code snippets, and extended OpenAPI specifications.  
"""

from fastapi import FastAPI, Request, HTTPException  
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse  
from fastapi.staticfiles import StaticFiles  
from fastapi.templating import Jinja2Templates  
from fastapi.openapi.utils import get\_openapi  
from fastapi.middleware.cors import CORSMiddleware  
from pydantic import BaseModel, Field  
from typing import List, Optional, Dict, Any  
from datetime import datetime, date  
from enum import Enum  
import yaml  
import logging

logging.basicConfig(level=logging.INFO)  
logger \= logging.getLogger(\_\_name\_\_)

app \= FastAPI(  
    title="Brazilian Financial Data APIs",  
    description="""Comprehensive API documentation for accessing Brazilian financial market data.  
    

## Overview

      
    This documentation covers three major Brazilian financial data sources:  
      
    \- **CVM Credit API**: Securities and Exchange Commission credit operations data  
    \- **ANBIMA API**: Brazilian Financial and Capital Markets Association data  
    \- **BACEN API**: Central Bank of Brazil economic indicators  
    

## Features

      
    \- Real-time and historical financial data  
    \- RESTful API design  
    \- Comprehensive filtering and pagination  
    \- Multiple data formats (JSON, CSV)  
    \- Rate limiting and caching  
    \- API key authentication  
    

## Getting Started

      
    1\. Obtain an API key from the developer portal  
    2\. Include the key in the \`X-API-Key\` header  
    3\. Make requests to the endpoints below  
    4\. Check the \[Quick Start Guide\](/docs) for examples  
    """,  
    version="1.0.0",  
    contact={  
        "name": "API Support",  
        "email": "api-support@financialdata.com.br",  
        "url": "https://docs.financialdata.com.br"  
    },  
    license\_info={  
        "name": "Apache 2.0",  
        "url": "https://www.apache.org/licenses/LICENSE-2.0.html"  
    },  
    docs\_url="/swagger",  
    redoc\_url="/redoc",  
    openapi\_url="/openapi.json"  
)

app.add\_middleware(  
    CORSMiddleware,  
    allow\_origins=\["\*"\],  
    allow\_credentials=True,  
    allow\_methods=\["\*"\],  
    allow\_headers=\["\*"\],  
)

app.mount("/static", StaticFiles(directory="static"), name="static")  
templates \= Jinja2Templates(directory="templates")

class OperationType(str, Enum):  
    """Types of credit operations."""  
    DEBENTURES \= "DEBENTURES"  
    COMMERCIAL\_NOTES \= "COMMERCIAL\_NOTES"  
    PROMISSORY\_NOTES \= "PROMISSORY\_NOTES"  
    CRI \= "CRI"  
    CRA \= "CRA"  
    FIDC \= "FIDC"

class MarketType(str, Enum):  
    """Market types for securities."""  
    PRIMARY \= "PRIMARY"  
    SECONDARY \= "SECONDARY"  
    BOTH \= "BOTH"

class DataFormat(str, Enum):  
    """Response data formats."""  
    JSON \= "json"  
    CSV \= "csv"

class CVMCreditOperation(BaseModel):  
    """CVM Credit Operation record."""  
    operation\_id: str \= Field(..., description="Unique operation identifier", example="CVM-2024-00123")  
    issuer\_name: str \= Field(..., description="Name of the issuing company", example="Petrobras S.A.")  
    issuer\_cnpj: str \= Field(..., description="CNPJ of the issuer", example="33.000.167/0001-01")  
    operation\_type: OperationType \= Field(..., description="Type of credit operation")  
    issue\_date: date \= Field(..., description="Date of issuance", example="2024-01-15")  
    maturity\_date: date \= Field(..., description="Maturity date", example="2029-01-15")  
    total\_amount: float \= Field(..., description="Total amount in BRL", example=1000000000.00, ge=0)  
    interest\_rate: Optional\[float\] \= Field(None, description="Annual interest rate (%)", example=12.5, ge=0)  
    market\_type: MarketType \= Field(..., description="Market where operation occurs")  
    rating: Optional\[str\] \= Field(None, description="Credit rating", example="AAA")  
    guarantees: Optional\[List\[str\]\] \= Field(None, description="List of guarantees")  
    created\_at: datetime \= Field(default\_factory=datetime.utcnow, description="Record creation timestamp")  
    updated\_at: datetime \= Field(default\_factory=datetime.utcnow, description="Last update timestamp")

    class Config:  
        json\_schema\_extra \= {  
            "example": {  
                "operation\_id": "CVM-2024-00123",  
                "issuer\_name": "Petrobras S.A.",  
                "issuer\_cnpj": "33.000.167/0001-01",  
                "operation\_type": "DEBENTURES",  
                "issue\_date": "2024-01-15",  
                "maturity\_date": "2029-01-15",  
                "total\_amount": 1000000000.00,  
                "interest\_rate": 12.5,  
                "market\_type": "PRIMARY",  
                "rating": "AAA",  
                "guarantees": \["Real estate assets", "Corporate guarantee"\],  
                "created\_at": "2024-01-15T10:00:00Z",  
                "updated\_at": "2024-01-15T10:00:00Z"  
            }  
        }

class ANBIMAIndicator(BaseModel):  
    """ANBIMA market indicator."""  
    indicator\_id: str \= Field(..., description="Indicator identifier", example="IMA-B")  
    indicator\_name: str \= Field(..., description="Indicator name", example="Market Index Series B")  
    reference\_date: date \= Field(..., description="Reference date", example="2024-01-15")  
    value: float \= Field(..., description="Indicator value", example=15234.56)  
    variation\_daily: Optional\[float\] \= Field(None, description="Daily variation (%)", example=0.25)  
    variation\_monthly: Optional\[float\] \= Field(None, description="Monthly variation (%)", example=1.5)  
    variation\_yearly: Optional\[float\] \= Field(None, description="Yearly variation (%)", example=8.5)

    class Config:  
        json\_schema\_extra \= {  
            "example": {  
                "indicator\_id": "IMA-B",  
                "indicator\_name": "Market Index Series B",  
                "reference\_date": "2024-01-15",  
                "value": 15234.56,  
                "variation\_daily": 0.25,  
                "variation\_monthly": 1.5,  
                "variation\_yearly": 8.5  
            }  
        }

class BACENIndicator(BaseModel):  
    """BACEN economic indicator."""  
    series\_code: int \= Field(..., description="BACEN series code", example=433)  
    series\_name: str \= Field(..., description="Series name", example="SELIC Interest Rate")  
    reference\_date: date \= Field(..., description="Reference date", example="2024-01-15")  
    value: float \= Field(..., description="Indicator value", example=11.75)  
    unit: str \= Field(..., description="Unit of measurement", example="% p.a.")

    class Config:  
        json\_schema\_extra \= {  
            "example": {  
                "series\_code": 433,  
                "series\_name": "SELIC Interest Rate",  
                "reference\_date": "2024-01-15",  
                "value": 11.75,  
                "unit": "% p.a."  
            }  
        }

class PaginationMeta(BaseModel):  
    """Pagination metadata."""  
    page: int \= Field(..., description="Current page number", example=1)  
    page\_size: int \= Field(..., description="Items per page", example=100)  
    total\_items: int \= Field(..., description="Total number of items", example=1500)  
    total\_pages: int \= Field(..., description="Total number of pages", example=15)

class CVMCreditResponse(BaseModel):  
    """Paginated response for CVM credit operations."""  
    data: List\[CVMCreditOperation\] \= Field(..., description="List of credit operations")  
    meta: PaginationMeta \= Field(..., description="Pagination metadata")

class APIHealthResponse(BaseModel):  
    """API health check response."""  
    status: str \= Field(..., description="Service status", example="healthy")  
    timestamp: datetime \= Field(default\_factory=datetime.utcnow, description="Check timestamp")  
    version: str \= Field(..., description="API version", example="1.0.0")  
    services: Dict\[str, str\] \= Field(..., description="Status of dependent services")

class APIError(BaseModel):  
    """Standard API error response."""  
    error: str \= Field(..., description="Error type", example="ValidationError")  
    message: str \= Field(..., description="Error message", example="Invalid date format")  
    details: Optional\[Dict\[str, Any\]\] \= Field(None, description="Additional error details")  
    timestamp: datetime \= Field(default\_factory=datetime.utcnow, description="Error timestamp")

@app.get("/", response\_class=HTMLResponse, include\_in\_schema=False)  
async def root(request: Request):  
    """Serve custom documentation landing page."""  
    try:  
        return FileResponse("static/index.html")  
    except Exception as e:  
        logger.error(f"Error serving index.html: {e}")  
        return HTMLResponse(content="\<h1\>Documentation Server\</h1\>\<p\>Visit /swagger for API docs\</p\>")

@app.get("/health", response\_model=APIHealthResponse, tags=\["System"\])  
async def health\_check():  
    """Check API health and service status.  
      
    Returns the current health status of the API and its dependencies.  
    Use this endpoint for monitoring and load balancer health checks.  
    """  
    return {  
        "status": "healthy",  
        "timestamp": datetime.utcnow(),  
        "version": "1.0.0",  
        "services": {  
            "database": "healthy",  
            "cache": "healthy",  
            "cvm\_api": "healthy",  
            "anbima\_api": "healthy",  
            "bacen\_api": "healthy"  
        }  
    }

@app.get(  
    "/api/v1/cvm/credit/operations",  
    response\_model=CVMCreditResponse,  
    tags=\["CVM Credit"\],  
    summary="List credit operations",  
    description="""Retrieve a paginated list of CVM credit operations.  
      
    This endpoint allows filtering by various parameters including operation type,  
    issuer, date ranges, and market type. Results are paginated and can be sorted.  
      
    **Rate Limit**: 100 requests per minute  
      
    **Cache**: Results cached for 5 minutes  
    """,  
    responses={  
        200: {"description": "Successful response with operations list"},  
        400: {"model": APIError, "description": "Invalid request parameters"},  
        401: {"model": APIError, "description": "Authentication required"},  
        429: {"model": APIError, "description": "Rate limit exceeded"},  
        500: {"model": APIError, "description": "Internal server error"}  
    }  
)  
async def list\_credit\_operations(  
    page: int \= Field(1, ge=1, description="Page number"),  
    page\_size: int \= Field(100, ge=1, le=1000, description="Items per page"),  
    operation\_type: Optional\[OperationType\] \= Field(None, description="Filter by operation type"),  
    issuer\_cnpj: Optional\[str\] \= Field(None, description="Filter by issuer CNPJ"),  
    start\_date: Optional\[date\] \= Field(None, description="Filter by issue date (from)"),  
    end\_date: Optional\[date\] \= Field(None, description="Filter by issue date (to)"),  
    market\_type: Optional\[MarketType\] \= Field(None, description="Filter by market type"),  
    min\_amount: Optional\[float\] \= Field(None, ge=0, description="Minimum operation amount"),  
    format: DataFormat \= Field(DataFormat.JSON, description="Response format")  
):  
    """List CVM credit operations with filtering and pagination."""  
    sample\_operations \= \[  
        CVMCreditOperation(  
            operation\_id="CVM-2024-00123",  
            issuer\_name="Petrobras S.A.",  
            issuer\_cnpj="33.000.167/0001-01",  
            operation\_type=OperationType.DEBENTURES,  
            issue\_date=date(2024, 1, 15),  
            maturity\_date=date(2029, 1, 15),  
            total\_amount=1000000000.00,  
            interest\_rate=12.5,  
            market\_type=MarketType.PRIMARY,  
            rating="AAA",  
            guarantees=\["Real estate assets", "Corporate guarantee"\]  
        ),  
        CVMCreditOperation(  
            operation\_id="CVM-2024-00124",  
            issuer\_name="Vale S.A.",  
            issuer\_cnpj="33.592.510/0001-54",  
            operation\_type=OperationType.CRI,  
            issue\_date=date(2024, 1, 20),  
            maturity\_date=date(2027, 1, 20),  
            total\_amount=500000000.00,  
            interest\_rate=10.8,  
            market\_type=MarketType.PRIMARY,  
            rating="AA+",  
            guarantees=\["Real estate collateral"\]  
        )  
    \]  
      
    return {  
        "data": sample\_operations,  
        "meta": {  
            "page": page,  
            "page\_size": page\_size,  
            "total\_items": 1500,  
            "total\_pages": 15  
        }  
    }

@app.get(  
    "/api/v1/cvm/credit/operations/{operation\_id}",  
    response\_model=CVMCreditOperation,  
    tags=\["CVM Credit"\],  
    summary="Get operation details",  
    description="Retrieve detailed information about a specific credit operation.",  
    responses={  
        200: {"description": "Operation details"},  
        404: {"model": APIError, "description": "Operation not found"}  
    }  
)  
async def get\_credit\_operation(operation\_id: str \= Field(..., description="Operation identifier")):  
    """Get details of a specific credit operation."""  
    return CVMCreditOperation(  
        operation\_id=operation\_id,  
        issuer\_name="Petrobras S.A.",  
        issuer\_cnpj="33.000.167/0001-01",  
        operation\_type=OperationType.DEBENTURES,  
        issue\_date=date(2024, 1, 15),  
        maturity\_date=date(2029, 1, 15),  
        total\_amount=1000000000.00,  
        interest\_rate=12.5,  
        market\_type=MarketType.PRIMARY,  
        rating="AAA",  
        guarantees=\["Real estate assets", "Corporate guarantee"\]  
    )

@app.get(  
    "/api/v1/anbima/indicators",  
    response\_model=List\[ANBIMAIndicator\],  
    tags=\["ANBIMA"\],  
    summary="Get ANBIMA indicators",  
    description="""Retrieve ANBIMA market indicators.  
      
    Access daily market indices including IMA-B, IMA-S, IRF-M and other benchmark indicators  
    from the Brazilian Financial and Capital Markets Association.  
    """  
)  
async def get\_anbima\_indicators(  
    reference\_date: Optional\[date\] \= Field(None, description="Reference date for indicators"),  
    indicator\_ids: Optional\[List\[str\]\] \= Field(None, description="Specific indicator IDs to retrieve")  
):  
    """Get ANBIMA market indicators."""  
    return \[  
        ANBIMAIndicator(  
            indicator\_id="IMA-B",  
            indicator\_name="Market Index Series B",  
            reference\_date=date(2024, 1, 15),  
            value=15234.56,  
            variation\_daily=0.25,  
            variation\_monthly=1.5,  
            variation\_yearly=8.5  
        ),  
        ANBIMAIndicator(  
            indicator\_id="IMA-S",  
            indicator\_name="Market Index SELIC",  
            reference\_date=date(2024, 1, 15),  
            value=2845.12,  
            variation\_daily=0.05,  
            variation\_monthly=0.98,  
            variation\_yearly=11.75  
        )  
    \]

@app.get(  
    "/api/v1/bacen/series/{series\_code}",  
    response\_model=List\[BACENIndicator\],  
    tags=\["BACEN"\],  
    summary="Get BACEN time series",  
    description="""Retrieve Central Bank of Brazil economic indicator time series.  
      
    Access over 18,000 economic time series including interest rates, exchange rates,  
    inflation indices, monetary aggregates, and other macroeconomic indicators.  
      
    **Popular Series Codes**:  
    \- 433: SELIC interest rate  
    \- 1: USD/BRL exchange rate  
    \- 433: CDI rate  
    \- 4389: IPCA inflation index  
    """  
)  
async def get\_bacen\_series(  
    series\_code: int \= Field(..., description="BACEN series code", example=433),  
    start\_date: Optional\[date\] \= Field(None, description="Start date for data"),  
    end\_date: Optional\[date\] \= Field(None, description="End date for data")  
):  
    """Get BACEN economic indicator time series."""  
    return \[  
        BACENIndicator(  
            series\_code=series\_code,  
            series\_name="SELIC Interest Rate",  
            reference\_date=date(2024, 1, 15),  
            value=11.75,  
            unit="% p.a."  
        )  
    \]

@app.get(  
    "/api/v1/statistics/summary",  
    tags=\["Statistics"\],  
    summary="Get market statistics",  
    description="Retrieve aggregated statistics across all data sources."  
)  
async def get\_statistics\_summary():  
    """Get aggregated market statistics."""  
    return {  
        "cvm\_operations\_total": 1500,  
        "cvm\_operations\_month": 45,  
        "total\_amount\_issued\_year": 125000000000.00,  
        "average\_interest\_rate": 11.2,  
        "anbima\_indicators\_count": 52,  
        "bacen\_series\_count": 18456,  
        "last\_updated": datetime.utcnow()  
    }

@app.get("/openapi.yaml", include\_in\_schema=False)  
async def get\_openapi\_yaml():  
    """Serve OpenAPI specification in YAML format."""  
    try:  
        return FileResponse("static/openapi.yaml", media\_type="application/x-yaml")  
    except Exception:  
        openapi\_schema \= app.openapi()  
        yaml\_content \= yaml.dump(openapi\_schema, default\_flow\_style=False, sort\_keys=False)  
        return JSONResponse(content={"yaml": yaml\_content})

def custom\_openapi():  
    """Generate custom OpenAPI schema with extended documentation."""  
    if app.openapi\_schema:  
        return app.openapi\_schema  
      
    openapi\_schema \= get\_openapi(  
        title=app.title,  
        version=app.version,  
        description=app.description,  
        routes=app.routes,  
    )  
      
    openapi\_schema\["info"\]\["x-logo"\] \= {  
        "url": "https://fastapi.tiangolo.com/img/logo-margin/logo-teal.png"  
    }  
      
    openapi\_schema\["servers"\] \= \[  
        {"url": "https://api.financialdata.com.br", "description": "Production"},  
        {"url": "https://staging-api.financialdata.com.br", "description": "Staging"},  
        {"url": "http://localhost:8080", "description": "Development"}  
    \]  
      
    openapi\_schema\["components"\]\["securitySchemes"\] \= {  
        "ApiKeyAuth": {  
            "type": "apiKey",  
            "in": "header",  
            "name": "X-API-Key",  
            "description": "API key for authentication. Obtain from developer portal."  
        },  
        "BearerAuth": {  
            "type": "http",  
            "scheme": "bearer",  
            "bearerFormat": "JWT",  
            "description": "JWT token authentication"  
        }  
    }  
      
    openapi\_schema\["security"\] \= \[{"ApiKeyAuth": \[\]}\]  
      
    openapi\_schema\["tags"\] \= \[  
        {  
            "name": "System",  
            "description": "System health and monitoring endpoints"  
        },  
        {  
            "name": "CVM Credit",  
            "description": "CVM credit operations data \- debentures, notes, and other credit instruments",  
            "externalDocs": {  
                "description": "CVM Official Documentation",  
                "url": "https://www.gov.br/cvm"  
            }  
        },  
        {  
            "name": "ANBIMA",  
            "description": "ANBIMA market indicators and benchmark indices",  
            "externalDocs": {  
                "description": "ANBIMA Official Website",  
                "url": "https://www.anbima.com.br"  
            }  
        },  
        {  
            "name": "BACEN",  
            "description": "Central Bank of Brazil economic time series",  
            "externalDocs": {  
                "description": "BACEN SGS System",  
                "url": "https://www3.bcb.gov.br/sgspub"  
            }  
        },  
        {  
            "name": "Statistics",  
            "description": "Aggregated statistics and analytics"  
        }  
    \]  
      
    app.openapi\_schema \= openapi\_schema  
    return app.openapi\_schema

app.openapi \= custom\_openapi

if \_\_name\_\_ \== "\_\_main\_\_":  
    import uvicorn  
    uvicorn.run(app, host="0.0.0.0", port=8080)  
\`\`\`

\---

## static/index.html

\`\`\`html  
\<\!DOCTYPE html\>  
\<html lang="en"\>  
\<head\>  
    \<meta charset="UTF-8"\>  
    \<meta name="viewport" content="width=device-width, initial-scale=1.0"\>  
    \<title\>Brazilian Financial Data APIs \- Documentation\</title\>  
    \<meta name="description" content="Comprehensive API documentation for accessing Brazilian financial market data from CVM, ANBIMA, and BACEN."\>  
    \<style\>  
        :root {  
            \--primary-color: \#009879;  
            \--secondary-color: \#005f4f;  
            \--accent-color: \#ffd700;  
            \--background: \#f8f9fa;  
            \--card-background: \#ffffff;  
            \--text-primary: \#2c3e50;  
            \--text-secondary: \#6c757d;  
            \--border-color: \#dee2e6;  
            \--code-background: \#f4f4f4;  
            \--success: \#28a745;  
            \--info: \#17a2b8;  
            \--warning: \#ffc107;  
        }  
          
        \* {  
            margin: 0;  
            padding: 0;  
            box-sizing: border-box;  
        }  
          
        body {  
            font-family: \-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;  
            line-height: 1.6;  
            color: var(--text-primary);  
            background: var(--background);  
        }  
          
        .header {  
            background: linear-gradient(135deg, var(--primary-color), var(--secondary-color));  
            color: white;  
            padding: 3rem 2rem;  
            text-align: center;  
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);  
        }  
          
        .header h1 {  
            font-size: 2.5rem;  
            margin-bottom: 0.5rem;  
            font-weight: 700;  
        }  
          
        .header p {  
            font-size: 1.2rem;  
            opacity: 0.9;  
        }  
          
        .nav-bar {  
            background: var(--card-background);  
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);  
            position: sticky;  
            top: 0;  
            z-index: 100;  
        }  
          
        .nav-content {  
            max-width: 1200px;  
            margin: 0 auto;  
            padding: 1rem 2rem;  
            display: flex;  
            gap: 2rem;  
            flex-wrap: wrap;  
        }  
          
        .nav-content a {  
            color: var(--text-primary);  
            text-decoration: none;  
            font-weight: 500;  
            padding: 0.5rem 1rem;  
            border-radius: 4px;  
            transition: all 0.3s ease;  
        }  
          
        .nav-content a:hover {  
            background: var(--primary-color);  
            color: white;  
        }  
          
        .container {  
            max-width: 1200px;  
            margin: 2rem auto;  
            padding: 0 2rem;  
        }  
          
        .section {  
            background: var(--card-background);  
            border-radius: 8px;  
            padding: 2rem;  
            margin-bottom: 2rem;  
            box-shadow: 0 2px 8px rgba(0,0,0,0.05);  
        }  
          
        .section h2 {  
            color: var(--primary-color);  
            margin-bottom: 1.5rem;  
            font-size: 1.8rem;  
            border-bottom: 3px solid var(--primary-color);  
            padding-bottom: 0.5rem;  
        }  
          
        .section h3 {  
            color: var(--secondary-color);  
            margin-top: 1.5rem;  
            margin-bottom: 1rem;  
            font-size: 1.3rem;  
        }  
          
        .api-grid {  
            display: grid;  
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));  
            gap: 1.5rem;  
            margin-top: 1.5rem;  
        }  
          
        .api-card {  
            border: 2px solid var(--border-color);  
            border-radius: 8px;  
            padding: 1.5rem;  
            transition: all 0.3s ease;  
            background: var(--card-background);  
        }  
          
        .api-card:hover {  
            border-color: var(--primary-color);  
            transform: translateY(-4px);  
            box-shadow: 0 4px 12px rgba(0,152,121,0.2);  
        }  
          
        .api-card h3 {  
            color: var(--primary-color);  
            margin-top: 0;  
            display: flex;  
            align-items: center;  
            gap: 0.5rem;  
        }  
          
        .api-card .badge {  
            background: var(--primary-color);  
            color: white;  
            padding: 0.25rem 0.75rem;  
            border-radius: 12px;  
            font-size: 0.75rem;  
            font-weight: 600;  
        }  
          
        .api-card p {  
            color: var(--text-secondary);  
            margin: 1rem 0;  
        }  
          
        .api-card ul {  
            list-style: none;  
            padding: 0;  
        }  
          
        .api-card li {  
            padding: 0.5rem 0;  
            color: var(--text-secondary);  
        }  
          
        .api-card li:before {  
            content: "✓ ";  
            color: var(--success);  
            font-weight: bold;  
            margin-right: 0.5rem;  
        }  
          
        .code-block {  
            background: var(--code-background);  
            border-left: 4px solid var(--primary-color);  
            padding: 1.5rem;  
            border-radius: 4px;  
            overflow-x: auto;  
            margin: 1rem 0;  
            font-family: 'Courier New', monospace;  
            position: relative;  
        }  
          
        .code-block pre {  
            margin: 0;  
            font-size: 0.9rem;  
            line-height: 1.5;  
        }  
          
        .code-header {  
            display: flex;  
            justify-content: space-between;  
            align-items: center;  
            margin-bottom: 1rem;  
            padding-bottom: 0.5rem;  
            border-bottom: 1px solid var(--border-color);  
        }  
          
        .code-lang {  
            font-weight: 600;  
            color: var(--primary-color);  
            text-transform: uppercase;  
            font-size: 0.85rem;  
        }  
          
        .copy-btn {  
            background: var(--primary-color);  
            color: white;  
            border: none;  
            padding: 0.5rem 1rem;  
            border-radius: 4px;  
            cursor: pointer;  
            font-size: 0.85rem;  
            transition: background 0.3s ease;  
        }  
          
        .copy-btn:hover {  
            background: var(--secondary-color);  
        }  
          
        .tab-container {  
            margin: 1.5rem 0;  
        }  
          
        .tabs {  
            display: flex;  
            gap: 0.5rem;  
            border-bottom: 2px solid var(--border-color);  
            margin-bottom: 1rem;  
        }  
          
        .tab {  
            padding: 0.75rem 1.5rem;  
            background: none;  
            border: none;  
            color: var(--text-secondary);  
            cursor: pointer;  
            font-size: 1rem;  
            font-weight: 500;  
            border-bottom: 3px solid transparent;  
            transition: all 0.3s ease;  
        }  
          
        .tab:hover {  
            color: var(--primary-color);  
        }  
          
        .tab.active {  
            color: var(--primary-color);  
            border-bottom-color: var(--primary-color);  
        }  
          
        .tab-content {  
            display: none;  
        }  
          
        .tab-content.active {  
            display: block;  
            animation: fadeIn 0.3s ease;  
        }  
          
        @keyframes fadeIn {  
            from { opacity: 0; transform: translateY(10px); }  
            to { opacity: 1; transform: translateY(0); }  
        }  
          
        .alert {  
            padding: 1rem 1.5rem;  
            border-radius: 4px;  
            margin: 1rem 0;  
            border-left: 4px solid;  
        }  
          
        .alert-info {  
            background: \#d1ecf1;  
            border-color: var(--info);  
            color: \#0c5460;  
        }  
          
        .alert-warning {  
            background: \#fff3cd;  
            border-color: var(--warning);  
            color: \#856404;  
        }  
          
        .alert-success {  
            background: \#d4edda;  
            border-color: var(--success);  
            color: \#155724;  
        }  
          
        .feature-grid {  
            display: grid;  
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));  
            gap: 1.5rem;  
            margin: 1.5rem 0;  
        }  
          
        .feature-box {  
            text-align: center;  
            padding: 1.5rem;  
            border: 1px solid var(--border-color);  
            border-radius: 8px;  
            transition: all 0.3s ease;  
        }  
          
        .feature-box:hover {  
            border-color: var(--primary-color);  
            box-shadow: 0 4px 12px rgba(0,152,121,0.15);  
        }  
          
        .feature-icon {  
            font-size: 3rem;  
            margin-bottom: 1rem;  
        }  
          
        .feature-box h4 {  
            color: var(--primary-color);  
            margin-bottom: 0.5rem;  
        }  
          
        .cta-buttons {  
            display: flex;  
            gap: 1rem;  
            margin: 2rem 0;  
            flex-wrap: wrap;  
        }  
          
        .btn {  
            padding: 0.75rem 2rem;  
            border-radius: 4px;  
            text-decoration: none;  
            font-weight: 600;  
            transition: all 0.3s ease;  
            border: none;  
            cursor: pointer;  
            font-size: 1rem;  
            display: inline-block;  
        }  
          
        .btn-primary {  
            background: var(--primary-color);  
            color: white;  
        }  
          
        .btn-primary:hover {  
            background: var(--secondary-color);  
            transform: translateY(-2px);  
            box-shadow: 0 4px 12px rgba(0,152,121,0.3);  
        }  
          
        .btn-secondary {  
            background: white;  
            color: var(--primary-color);  
            border: 2px solid var(--primary-color);  
        }  
          
        .btn-secondary:hover {  
            background: var(--primary-color);  
            color: white;  
        }  
          
        .endpoint-list {  
            list-style: none;  
            padding: 0;  
        }  
          
        .endpoint-item {  
            background: var(--code-background);  
            padding: 1rem;  
            margin: 0.5rem 0;  
            border-radius: 4px;  
            border-left: 4px solid var(--primary-color);  
        }  
          
        .endpoint-method {  
            font-weight: 700;  
            color: var(--success);  
            font-family: monospace;  
            margin-right: 1rem;  
        }  
          
        .endpoint-path {  
            font-family: monospace;  
            color: var(--text-primary);  
        }  
          
        .endpoint-desc {  
            color: var(--text-secondary);  
            margin-top: 0.5rem;  
            font-size: 0.9rem;  
        }  
          
        footer {  
            background: var(--text-primary);  
            color: white;  
            text-align: center;  
            padding: 2rem;  
            margin-top: 3rem;  
        }  
          
        footer a {  
            color: var(--accent-color);  
            text-decoration: none;  
        }  
          
        @media (max-width: 768px) {  
            .header h1 {  
                font-size: 1.8rem;  
            }  
              
            .nav-content {  
                flex-direction: column;  
                gap: 0.5rem;  
            }  
              
            .api-grid,  
            .feature-grid {  
                grid-template-columns: 1fr;  
            }  
              
            .cta-buttons {  
                flex-direction: column;  
            }  
              
            .btn {  
                text-align: center;  
            }  
        }  
    \</style\>  
\</head\>  
\<body\>  
    \<header class="header"\>  
        \<h1\>🇧🇷 Brazilian Financial Data APIs\</h1\>  
        \<p\>Comprehensive access to CVM, ANBIMA, and BACEN market data\</p\>  
    \</header\>  
      
    \<nav class="nav-bar"\>  
        \<div class="nav-content"\>  
            \<a href="\#overview"\>Overview\</a\>  
            \<a href="\#apis"\>APIs\</a\>  
            \<a href="\#quickstart"\>Quick Start\</a\>  
            \<a href="\#authentication"\>Authentication\</a\>  
            \<a href="\#examples"\>Examples\</a\>  
            \<a href="/swagger" target="\_blank"\>Swagger UI\</a\>  
            \<a href="/redoc" target="\_blank"\>ReDoc\</a\>  
        \</div\>  
    \</nav\>  
      
    \<div class="container"\>  
        \<section id="overview" class="section"\>  
            \<h2\>📊 Overview\</h2\>  
            \<p\>Access comprehensive Brazilian financial market data through a unified, modern REST API. Our platform aggregates data from three authoritative sources:\</p\>  
              
            \<div class="feature-grid"\>  
                \<div class="feature-box"\>  
                    \<div class="feature-icon"\>🏛️\</div\>  
                    \<h4\>CVM Data\</h4\>  
                    \<p\>Securities and Exchange Commission credit operations, debentures, and corporate bonds\</p\>  
                \</div\>  
                \<div class="feature-box"\>  
                    \<div class="feature-icon"\>📈\</div\>  
                    \<h4\>ANBIMA Indices\</h4\>  
                    \<p\>Market benchmark indices, fixed income indicators, and investment fund data\</p\>  
                \</div\>  
                \<div class="feature-box"\>  
                    \<div class="feature-icon"\>🏦\</div\>  
                    \<h4\>BACEN Series\</h4\>  
                    \<p\>Central Bank economic indicators, interest rates, exchange rates, and inflation data\</p\>  
                \</div\>  
                \<div class="feature-box"\>  
                    \<div class="feature-icon"\>⚡\</div\>  
                    \<h4\>Real-time Updates\</h4\>  
                    \<p\>Live data feeds with automatic updates and change notifications\</p\>  
                \</div\>  
            \</div\>  
              
            \<div class="cta-buttons"\>  
                \<a href="\#quickstart" class="btn btn-primary"\>Get Started\</a\>  
                \<a href="/swagger" class="btn btn-secondary" target="\_blank"\>API Documentation\</a\>  
            \</div\>  
        \</section\>  
          
        \<section id="apis" class="section"\>  
            \<h2\>🔌 Available APIs\</h2\>  
              
            \<div class="api-grid"\>  
                \<div class="api-card"\>  
                    \<h3\>  
                        CVM Credit API  
                        \<span class="badge"\>v1.0\</span\>  
                    \</h3\>  
                    \<p\>Access comprehensive data on credit operations registered with the Brazilian Securities and Exchange Commission.\</p\>  
                    \<ul\>  
                        \<li\>Debentures and corporate bonds\</li\>  
                        \<li\>Commercial and promissory notes\</li\>  
                        \<li\>Real estate credit certificates (CRI)\</li\>  
                        \<li\>Agribusiness credit certificates (CRA)\</li\>  
                        \<li\>FIDC receivables investment funds\</li\>  
                    \</ul\>  
                    \<div class="alert alert-info"\>  
                        \<strong\>Base URL:\</strong\> \<code\>/api/v1/cvm/credit\</code\>  
                    \</div\>  
                \</div\>  
                  
                \<div class="api-card"\>  
                    \<h3\>  
                        ANBIMA API  
                        \<span class="badge"\>v1.0\</span\>  
                    \</h3\>  
                    \<p\>Market indicators and benchmark indices from the Brazilian Financial and Capital Markets Association.\</p\>  
                    \<ul\>  
                        \<li\>IMA-B and IMA-S market indices\</li\>  
                        \<li\>IRF-M fixed income indicators\</li\>  
                        \<li\>Investment fund rankings\</li\>  
                        \<li\>Daily price curves\</li\>  
                        \<li\>Trading volumes and statistics\</li\>  
                    \</ul\>  
                    \<div class="alert alert-info"\>  
                        \<strong\>Base URL:\</strong\> \<code\>/api/v1/anbima\</code\>  
                    \</div\>  
                \</div\>  
                  
                \<div class="api-card"\>  
                    \<h3\>  
                        BACEN API  
                        \<span class="badge"\>v1.0\</span\>  
                    \</h3\>  
                    \<p\>Economic time series from the Central Bank of Brazil's Time Series Management System (SGS).\</p\>  
                    \<ul\>  
                        \<li\>SELIC and CDI interest rates\</li\>  
                        \<li\>USD/BRL and other exchange rates\</li\>  
                        \<li\>IPCA, IGP-M inflation indices\</li\>  
                        \<li\>Monetary aggregates (M1, M2, M3)\</li\>  
                        \<li\>18,000+ economic indicators\</li\>  
                    \</ul\>  
                    \<div class="alert alert-info"\>  
                        \<strong\>Base URL:\</strong\> \<code\>/api/v1/bacen\</code\>  
                    \</div\>  
                \</div\>  
            \</div\>  
        \</section\>  
          
        \<section id="quickstart" class="section"\>  
            \<h2\>🚀 Quick Start Guide\</h2\>  
              
            \<h3\>1. Obtain API Key\</h3\>  
            \<div class="alert alert-warning"\>  
                \<strong\>⚠️ Authentication Required:\</strong\> All API requests require a valid API key. Register at the developer portal to obtain your key.  
            \</div\>  
              
            \<h3\>2. Make Your First Request\</h3\>  
            \<p\>Use your API key in the \<code\>X-API-Key\</code\> header to authenticate requests:\</p\>  
              
            \<div class="tab-container"\>  
                \<div class="tabs"\>  
                    \<button class="tab active" onclick="showTab('curl')"\>cURL\</button\>  
                    \<button class="tab" onclick="showTab('python')"\>Python\</button\>  
                    \<button class="tab" onclick="showTab('javascript')"\>JavaScript\</button\>  
                    \<button class="tab" onclick="showTab('java')"\>Java\</button\>  
                \</div\>  
                  
                \<div id="curl" class="tab-content active"\>  
                    \<div class="code-block"\>  
                        \<div class="code-header"\>  
                            \<span class="code-lang"\>bash\</span\>  
                            \<button class="copy-btn" onclick="copyCode('curl-code')"\>Copy\</button\>  
                        \</div\>  
                        \<pre id="curl-code"\>curl \-X GET "https://api.financialdata.com.br/api/v1/cvm/credit/operations" \\  
  \-H "X-API-Key: your\_api\_key\_here" \\  
  \-H "Accept: application/json"\</pre\>  
                    \</div\>  
                \</div\>  
                  
                \<div id="python" class="tab-content"\>  
                    \<div class="code-block"\>  
                        \<div class="code-header"\>  
                            \<span class="code-lang"\>python\</span\>  
                            \<button class="copy-btn" onclick="copyCode('python-code')"\>Copy\</button\>  
                        \</div\>  
                        \<pre id="python-code"\>import requests

API\_KEY \= "your\_api\_key\_here"  
BASE\_URL \= "https://api.financialdata.com.br"

headers \= {  
    "X-API-Key": API\_KEY,  
    "Accept": "application/json"  
}

response \= requests.get(  
    f"{BASE\_URL}/api/v1/cvm/credit/operations",  
    headers=headers,  
    params={"page": 1, "page\_size": 100}  
)

if response.status\_code \== 200:  
    data \= response.json()  
    print(f"Retrieved {len(data\['data'\])} operations")  
    for operation in data\['data'\]:  
        print(f"{operation\['issuer\_name'\]}: R$ {operation\['total\_amount'\]:,.2f}")  
else:  
    print(f"Error: {response.status\_code}")\</pre\>  
                    \</div\>  
                \</div\>  
                  
                \<div id="javascript" class="tab-content"\>  
                    \<div class="code-block"\>  
                        \<div class="code-header"\>  
                            \<span class="code-lang"\>javascript\</span\>  
                            \<button class="copy-btn" onclick="copyCode('js-code')"\>Copy\</button\>  
                        \</div\>  
                        \<pre id="js-code"\>const API\_KEY \= 'your\_api\_key\_here';  
const BASE\_URL \= 'https://api.financialdata.com.br';

async function getCVMOperations() {  
    const response \= await fetch(  
        \`${BASE\_URL}/api/v1/cvm/credit/operations?page=1\&page\_size=100\`,  
        {  
            headers: {  
                'X-API-Key': API\_KEY,  
                'Accept': 'application/json'  
            }  
        }  
    );  
      
    if (response.ok) {  
        const data \= await response.json();  
        console.log(\`Retrieved ${data.data.length} operations\`);  
        data.data.forEach(operation \=\> {  
            console.log(\`${operation.issuer\_name}: R$ ${operation.total\_amount.toLocaleString()}\`);  
        });  
    } else {  
        console.error(\`Error: ${response.status}\`);  
    }  
}

getCVMOperations();\</pre\>  
                    \</div\>  
                \</div\>  
                  
                \<div id="java" class="tab-content"\>  
                    \<div class="code-block"\>  
                        \<div class="code-header"\>  
                            \<span class="code-lang"\>java\</span\>  
                            \<button class="copy-btn" onclick="copyCode('java-code')"\>Copy\</button\>  
                        \</div\>  
                        \<pre id="java-code"\>import java.net.http.HttpClient;  
import java.net.http.HttpRequest;  
import java.net.http.HttpResponse;  
import java.net.URI;  
import com.google.gson.Gson;

public class CVMApiClient {  
    private static final String API\_KEY \= "your\_api\_key\_here";  
    private static final String BASE\_URL \= "https://api.financialdata.com.br";  
      
    public static void main(String\[\] args) throws Exception {  
        HttpClient client \= HttpClient.newHttpClient();  
          
        HttpRequest request \= HttpRequest.newBuilder()  
            .uri(URI.create(BASE\_URL \+ "/api/v1/cvm/credit/operations?page=1\&page\_size=100"))  
            .header("X-API-Key", API\_KEY)  
            .header("Accept", "application/json")  
            .GET()  
            .build();  
          
        HttpResponse\<String\> response \= client.send(request,   
            HttpResponse.BodyHandlers.ofString());  
          
        if (response.statusCode() \== 200\) {  
            Gson gson \= new Gson();  
            CVMResponse data \= gson.fromJson(response.body(), CVMResponse.class);  
            System.out.println("Retrieved " \+ data.data.size() \+ " operations");  
        } else {  
            System.err.println("Error: " \+ response.statusCode());  
        }  
    }  
}\</pre\>  
                    \</div\>  
                \</div\>  
            \</div\>  
              
            \<h3\>3. Explore the Response\</h3\>  
            \<div class="code-block"\>  
                \<div class="code-header"\>  
                    \<span class="code-lang"\>json\</span\>  
                    \<button class="copy-btn" onclick="copyCode('response-code')"\>Copy\</button\>  
                \</div\>  
                \<pre id="response-code"\>{  
  "data": \[  
    {  
      "operation\_id": "CVM-2024-00123",  
      "issuer\_name": "Petrobras S.A.",  
      "issuer\_cnpj": "33.000.167/0001-01",  
      "operation\_type": "DEBENTURES",  
      "issue\_date": "2024-01-15",  
      "maturity\_date": "2029-01-15",  
      "total\_amount": 1000000000.00,  
      "interest\_rate": 12.5,  
      "market\_type": "PRIMARY",  
      "rating": "AAA",  
      "guarantees": \["Real estate assets", "Corporate guarantee"\]  
    }  
  \],  
  "meta": {  
    "page": 1,  
    "page\_size": 100,  
    "total\_items": 1500,  
    "total\_pages": 15  
  }  
}\</pre\>  
            \</div\>  
        \</section\>  
          
        \<section id="authentication" class="section"\>  
            \<h2\>🔐 Authentication\</h2\>  
              
            \<h3\>API Key Authentication\</h3\>  
            \<p\>Include your API key in the \<code\>X-API-Key\</code\> header with every request:\</p\>  
              
            \<div class="code-block"\>  
                \<pre\>X-API-Key: your\_api\_key\_here\</pre\>  
            \</div\>  
              
            \<div class="alert alert-warning"\>  
                \<strong\>🔒 Security Best Practices:\</strong\>  
                \<ul style="margin-top: 0.5rem; padding-left: 1.5rem;"\>  
                    \<li\>Never commit API keys to version control\</li\>  
                    \<li\>Use environment variables to store keys\</li\>  
                    \<li\>Rotate keys periodically\</li\>  
                    \<li\>Use different keys for development and production\</li\>  
                    \<li\>Implement rate limiting in your application\</li\>  
                \</ul\>  
            \</div\>  
              
            \<h3\>Rate Limits\</h3\>  
            \<p\>API requests are rate limited to ensure fair usage:\</p\>  
            \<ul\>  
                \<li\>\<strong\>Standard Tier:\</strong\> 100 requests per minute\</li\>  
                \<li\>\<strong\>Professional Tier:\</strong\> 1,000 requests per minute\</li\>  
                \<li\>\<strong\>Enterprise Tier:\</strong\> Custom limits\</li\>  
            \</ul\>  
              
            \<p\>Rate limit information is included in response headers:\</p\>  
            \<div class="code-block"\>  
                \<pre\>X-RateLimit-Limit: 100  
X-RateLimit-Remaining: 95  
X-RateLimit-Reset: 1640000000\</pre\>  
            \</div\>  
        \</section\>  
          
        \<section id="examples" class="section"\>  
            \<h2\>💡 Usage Examples\</h2\>  
              
            \<h3\>Example 1: Get CVM Operations by Type\</h3\>  
            \<div class="code-block"\>  
                \<div class="code-header"\>  
                    \<span class="code-lang"\>python\</span\>  
                    \<button class="copy-btn" onclick="copyCode('example1-code')"\>Copy\</button\>  
                \</div\>  
                \<pre id="example1-code"\>\# Get all debentures issued in 2024  
import requests  
from datetime import date

response \= requests.get(  
    "https://api.financialdata.com.br/api/v1/cvm/credit/operations",  
    headers={"X-API-Key": "your\_api\_key"},  
    params={  
        "operation\_type": "DEBENTURES",  
        "start\_date": "2024-01-01",  
        "end\_date": "2024-12-31",  
        "page\_size": 100  
    }  
)

operations \= response.json()\['data'\]  
total\_issued \= sum(op\['total\_amount'\] for op in operations)  
print(f"Total debentures issued in 2024: R$ {total\_issued:,.2f}")\</pre\>  
            \</div\>  
              
            \<h3\>Example 2: Get ANBIMA Market Indices\</h3\>  
            \<div class="code-block"\>  
                \<div class="code-header"\>  
                    \<span class="code-lang"\>python\</span\>  
                    \<button class="copy-btn" onclick="copyCode('example2-code')"\>Copy\</button\>  
                \</div\>  
                \<pre id="example2-code"\>\# Get current ANBIMA indices  
import requests

response \= requests.get(  
    "https://api.financialdata.com.br/api/v1/anbima/indicators",  
    headers={"X-API-Key": "your\_api\_key"},  
    params={"indicator\_ids": \["IMA-B", "IMA-S", "IRF-M"\]}  
)

for indicator in response.json():  
    print(f"{indicator\['indicator\_name'\]}: {indicator\['value'\]:.2f}")  
    print(f"  Daily: {indicator\['variation\_daily'\]:+.2f}%")  
    print(f"  Monthly: {indicator\['variation\_monthly'\]:+.2f}%")  
    print(f"  Yearly: {indicator\['variation\_yearly'\]:+.2f}%")\</pre\>  
            \</div\>  
              
            \<h3\>Example 3: Get BACEN Time Series\</h3\>  
            \<div class="code-block"\>  
                \<div class="code-header"\>  
                    \<span class="code-lang"\>python\</span\>  
                    \<button class="copy-btn" onclick="copyCode('example3-code')"\>Copy\</button\>  
                \</div\>  
                \<pre id="example3-code"\>\# Get SELIC interest rate history  
import requests  
import pandas as pd

response \= requests.get(  
    "https://api.financialdata.com.br/api/v1/bacen/series/433",  
    headers={"X-API-Key": "your\_api\_key"},  
    params={  
        "start\_date": "2023-01-01",  
        "end\_date": "2024-01-01"  
    }  
)

data \= response.json()  
df \= pd.DataFrame(data)  
df\['reference\_date'\] \= pd.to\_datetime(df\['reference\_date'\])

print(f"SELIC Rate Statistics (2023):")  
print(f"  Average: {df\['value'\].mean():.2f}%")  
print(f"  Minimum: {df\['value'\].min():.2f}%")  
print(f"  Maximum: {df\['value'\].max():.2f}%")\</pre\>  
            \</div\>  
              
            \<h3\>Example 4: Advanced Filtering and Aggregation\</h3\>  
            \<div class="code-block"\>  
                \<div class="code-header"\>  
                    \<span class="code-lang"\>python\</span\>  
                    \<button class="copy-btn" onclick="copyCode('example4-code')"\>Copy\</button\>  
                \</div\>  
                \<pre id="example4-code"\>\# Analyze credit operations by issuer  
import requests  
from collections import defaultdict

def get\_all\_operations(api\_key):  
    """Fetch all operations with pagination."""  
    all\_operations \= \[\]  
    page \= 1  
      
    while True:  
        response \= requests.get(  
            "https://api.financialdata.com.br/api/v1/cvm/credit/operations",  
            headers={"X-API-Key": api\_key},  
            params={"page": page, "page\_size": 100}  
        )  
          
        data \= response.json()  
        all\_operations.extend(data\['data'\])  
          
        if page \>= data\['meta'\]\['total\_pages'\]:  
            break  
        page \+= 1  
      
    return all\_operations

Aggregate by issuer

# operations \= get\_all\_operations("your\_api\_key")

issuer\_totals \= defaultdict(lambda: {"count": 0, "total\_amount": 0})

for op in operations:  
    issuer \= op\['issuer\_name'\]  
    issuer\_totals\[issuer\]\['count'\] \+= 1  
    issuer\_totals\[issuer\]\['total\_amount'\] \+= op\['total\_amount'\]

Print top 10 issuers

# top\_issuers \= sorted(

#     issuer\_totals.items(),

    key=lambda x: x\[1\]\['total\_amount'\],  
    reverse=True  
)\[:10\]

print("Top 10 Issuers by Total Amount:")  
for issuer, stats in top\_issuers:  
    print(f"{issuer}: {stats\['count'\]} operations, R$ {stats\['total\_amount'\]:,.2f}")\</pre\>  
            \</div\>  
        \</section\>  
          
        \<section class="section"\>  
            \<h2\>📝 API Endpoints Reference\</h2\>  
              
            \<h3\>CVM Credit API\</h3\>  
            \<ul class="endpoint-list"\>  
                \<li class="endpoint-item"\>  
                    \<span class="endpoint-method"\>GET\</span\>  
                    \<span class="endpoint-path"\>/api/v1/cvm/credit/operations\</span\>  
                    \<div class="endpoint-desc"\>List all credit operations with filtering and pagination\</div\>  
                \</li\>  
                \<li class="endpoint-item"\>  
                    \<span class="endpoint-method"\>GET\</span\>  
                    \<span class="endpoint-path"\>/api/v1/cvm/credit/operations/{operation\_id}\</span\>  
                    \<div class="endpoint-desc"\>Get detailed information about a specific operation\</div\>  
                \</li\>  
            \</ul\>  
              
            \<h3\>ANBIMA API\</h3\>  
            \<ul class="endpoint-list"\>  
                \<li class="endpoint-item"\>  
                    \<span class="endpoint-method"\>GET\</span\>  
                    \<span class="endpoint-path"\>/api/v1/anbima/indicators\</span\>  
                    \<div class="endpoint-desc"\>Get current market indicators and benchmark indices\</div\>  
                \</li\>  
            \</ul\>  
              
            \<h3\>BACEN API\</h3\>  
            \<ul class="endpoint-list"\>  
                \<li class="endpoint-item"\>  
                    \<span class="endpoint-method"\>GET\</span\>  
                    \<span class="endpoint-path"\>/api/v1/bacen/series/{series\_code}\</span\>  
                    \<div class="endpoint-desc"\>Get time series data for a specific BACEN indicator\</div\>  
                \</li\>  
            \</ul\>  
              
            \<h3\>Statistics API\</h3\>  
            \<ul class="endpoint-list"\>  
                \<li class="endpoint-item"\>  
                    \<span class="endpoint-method"\>GET\</span\>  
                    \<span class="endpoint-path"\>/api/v1/statistics/summary\</span\>  
                    \<div class="endpoint-desc"\>Get aggregated market statistics\</div\>  
                \</li\>  
            \</ul\>  
              
            \<div class="alert alert-info"\>  
                \<strong\>📚 Complete Documentation:\</strong\> For detailed endpoint documentation including all parameters, response schemas, and examples, visit the \<a href="/swagger" target="\_blank" style="color: \#0c5460; font-weight: 600;"\>Swagger UI\</a\> or \<a href="/redoc" target="\_blank" style="color: \#0c5460; font-weight: 600;"\>ReDoc\</a\> pages.  
            \</div\>  
        \</section\>  
          
        \<section class="section"\>  
            \<h2\>🆘 Support & Resources\</h2\>  
              
            \<div class="api-grid"\>  
                \<div class="api-card"\>  
                    \<h3\>📖 Documentation\</h3\>  
                    \<ul\>  
                        \<li\>\<a href="/swagger" target="\_blank"\>Swagger UI\</a\>\</li\>  
                        \<li\>\<a href="/redoc" target="\_blank"\>ReDoc\</a\>\</li\>  
                        \<li\>\<a href="/openapi.yaml" target="\_blank"\>OpenAPI Spec\</a\>\</li\>  
                    \</ul\>  
                \</div\>  
                  
                \<div class="api-card"\>  
                    \<h3\>💬 Community\</h3\>  
                    \<ul\>  
                        \<li\>GitHub Discussions\</li\>  
                        \<li\>Stack Overflow\</li\>  
                        \<li\>Discord Server\</li\>  
                    \</ul\>  
                \</div\>  
                  
                \<div class="api-card"\>  
                    \<h3\>🔧 Developer Tools\</h3\>  
                    \<ul\>  
                        \<li\>Python SDK\</li\>  
                        \<li\>JavaScript SDK\</li\>  
                        \<li\>Postman Collection\</li\>  
                    \</ul\>  
                \</div\>  
            \</div\>  
        \</section\>  
    \</div\>  
      
    \<footer\>  
        \<p\>\&copy; 2024 Brazilian Financial Data APIs. All rights reserved.\</p\>  
        \<p\>  
            \<a href="\#"\>Terms of Service\</a\> |  
            \<a href="\#"\>Privacy Policy\</a\> |  
            \<a href="\#"\>API Status\</a\> |  
            \<a href="mailto:api-support@financialdata.com.br"\>Contact Support\</a\>  
        \</p\>  
    \</footer\>  
      
    \<script\>  
        function showTab(tabName) {  
            // Hide all tab contents  
            const contents \= document.querySelectorAll('.tab-content');  
            contents.forEach(content \=\> content.classList.remove('active'));  
              
            // Remove active class from all tabs  
            const tabs \= document.querySelectorAll('.tab');  
            tabs.forEach(tab \=\> tab.classList.remove('active'));  
              
            // Show selected tab content  
            document.getElementById(tabName).classList.add('active');  
              
            // Add active class to clicked tab  
            event.target.classList.add('active');  
        }  
          
        function copyCode(elementId) {  
            const codeElement \= document.getElementById(elementId);  
            const text \= codeElement.textContent;  
              
            navigator.clipboard.writeText(text).then(() \=\> {  
                const button \= event.target;  
                const originalText \= button.textContent;  
                button.textContent \= 'Copied\!';  
                button.style.background \= '\#28a745';  
                  
                setTimeout(() \=\> {  
                    button.textContent \= originalText;  
                    button.style.background \= '';  
                }, 2000);  
            }).catch(err \=\> {  
                console.error('Failed to copy:', err);  
                alert('Failed to copy code');  
            });  
        }  
          
        // Smooth scrolling for anchor links  
        document.querySelectorAll('a\[href^="\#"\]').forEach(anchor \=\> {  
            anchor.addEventListener('click', function (e) {  
                const href \= this.getAttribute('href');  
                if (href \!== '\#' && document.querySelector(href)) {  
                    e.preventDefault();  
                    document.querySelector(href).scrollIntoView({  
                        behavior: 'smooth',  
                        block: 'start'  
                    });  
                }  
            });  
        });  
    \</script\>  
\</body\>  
\</html\>  
\`\`\`

\---

static/openapi.yaml

\`\`\`yaml  
openapi: 3.1.0

## info:

##   title: Brazilian Financial Data APIs

  description: |  
    Comprehensive API documentation for accessing Brazilian financial market data.  
      
Overview  
    

##     This documentation covers three major Brazilian financial data sources:

      
    \- CVM Credit API: Securities and Exchange Comm**ission credit** operations data  
    \- ANBIMA API: Brazilian Financial and Capital **Markets As**sociation data  
    \- BACEN API: Central Bank of Brazil economic i**ndicators**  
      
Features  
    

##     \- Real-time and historical financial data

    \- RESTful API design  
    \- Comprehensive filtering and pagination  
    \- Multiple data formats (JSON, CSV)  
    \- Rate limiting and caching  
    \- API key authentication  
      
Getting Started  
    

##     1\. Obtain an API key from the developer portal

    2\. Include the key in the \`X-API-Key\` header  
    3\. Make requests to the endpoints below  
    4\. Check the \[Quick Start Guide\](/docs) for examples  
  version: 1.0.0  
  contact:  
    name: API Support  
    email: api-support@financialdata.com.br  
    url: https://docs.financialdata.com.br  
  license:  
    name: Apache 2.0  
    url: https://www.apache.org/licenses/LICENSE-2.0.html  
  x-logo:  
    url: https://fastapi.tiangolo.com/img/logo-margin/logo-teal.png

servers:  
  \- url: https://api.financialdata.com.br  
    description: Production  
  \- url: https://staging-api.financialdata.com.br  
    description: Staging  
  \- url: http://localhost:8080  
    description: Development

security:  
  \- ApiKeyAuth: \[\]

tags:  
  \- name: System  
    description: System health and monitoring endpoints  
  \- name: CVM Credit  
    description: CVM credit operations data \- debentures, notes, and other credit instruments  
    externalDocs:  
      description: CVM Official Documentation  
      url: https://www.gov.br/cvm  
  \- name: ANBIMA  
    description: ANBIMA market indicators and benchmark indices  
    externalDocs:  
      description: ANBIMA Official Website  
      url: https://www.anbima.com.br  
  \- name: BACEN  
    description: Central Bank of Brazil economic time series  
    externalDocs:  
      description: BACEN SGS System  
      url: https://www3.bcb.gov.br/sgspub  
  \- name: Statistics  
    description: Aggregated statistics and analytics

paths:  
  /health:  
    get:  
      tags:  
        \- System  
      summary: Check API health  
      description: |  
        Check API health and service status.  
          
        Returns the current health status of the API and its dependencies.  
        Use this endpoint for monitoring and load balancer health checks.  
      operationId: health\_check  
      responses:  
        '200':  
          description: Successful response  
          content:  
            application/json:  
              schema:  
                $ref: '\#/components/schemas/APIHealthResponse'  
              example:  
                status: healthy  
                timestamp: '2024-01-15T10:00:00Z'  
                version: 1.0.0  
                services:  
                  database: healthy  
                  cache: healthy  
                  cvm\_api: healthy  
                  anbima\_api: healthy  
                  bacen\_api: healthy

  /api/v1/cvm/credit/operations:  
    get:  
      tags:  
        \- CVM Credit  
      summary: List credit operations  
      description: |  
        Retrieve a paginated list of CVM credit operations.  
          
        This endpoint allows filtering by various parameters including operation type,  
        issuer, date ranges, and market type. Results are paginated and can be sorted.  
          
        Rate Limit: 100 requests per minute  
          
        **C**ache: Results cached for 5 minutes  
      op**erati**onId: list\_credit\_operations  
      parameters:  
        \- name: page  
          in: query  
          description: Page number  
          required: false  
          schema:  
            type: integer  
            minimum: 1  
            default: 1  
        \- name: page\_size  
          in: query  
          description: Items per page  
          required: false  
          schema:  
            type: integer  
            minimum: 1  
            maximum: 1000  
            default: 100  
        \- name: operation\_type  
          in: query  
          description: Filter by operation type  
          required: false  
          schema:  
            $ref: '\#/components/schemas/OperationType'  
        \- name: issuer\_cnpj  
          in: query  
          description: Filter by issuer CNPJ  
          required: false  
          schema:  
            type: string  
            example: '33.000.167/0001-01'  
        \- name: start\_date  
          in: query  
          description: Filter by issue date (from)  
          required: false  
          schema:  
            type: string  
            format: date  
            example: '2024-01-01'  
        \- name: end\_date  
          in: query  
          description: Filter by issue date (to)  
          required: false  
          schema:  
            type: string  
            format: date  
            example: '2024-12-31'  
        \- name: market\_type  
          in: query  
          description: Filter by market type  
          required: false  
          schema:  
            $ref: '\#/components/schemas/MarketType'  
        \- name: min\_amount  
          in: query  
          description: Minimum operation amount  
          required: false  
          schema:  
            type: number  
            minimum: 0  
            example: 1000000  
        \- name: format  
          in: query  
          description: Response format  
          required: false  
          schema:  
            $ref: '\#/components/schemas/DataFormat'  
      responses:  
        '200':  
          description: Successful response with operations list  
          content:  
            application/json:  
              schema:  
                $ref: '\#/components/schemas/CVMCreditResponse'  
        '400':  
          description: Invalid request parameters  
          content:  
            application/json:  
              schema:  
                $ref: '\#/components/schemas/APIError'  
        '401':  
          description: Authentication required  
          content:  
            application/json:  
              schema:  
                $ref: '\#/components/schemas/APIError'  
        '429':  
          description: Rate limit exceeded  
          content:  
            application/json:  
              schema:  
                $ref: '\#/components/schemas/APIError'  
        '500':  
          description: Internal server error  
          content:  
            application/json:  
              schema:  
                $ref: '\#/components/schemas/APIError'

  /api/v1/cvm/credit/operations/{operation\_id}:  
    get:  
      tags:  
        \- CVM Credit  
      summary: Get operation details  
      description: Retrieve detailed information about a specific credit operation.  
      operationId: get\_credit\_operation  
      parameters:  
        \- name: operation\_id  
          in: path  
          description: Operation identifier  
          required: true  
          schema:  
            type: string  
            example: CVM-2024-00123  
      responses:  
        '200':  
          description: Operation details  
          content:  
            application/json:  
              schema:  
                $ref: '\#/components/schemas/CVMCreditOperation'  
        '404':  
          description: Operation not found  
          content:  
            application/json:  
              schema:  
                $ref: '\#/components/schemas/APIError'

  /api/v1/anbima/indicators:  
    get:  
      tags:  
        \- ANBIMA  
      summary: Get ANBIMA indicators  
      description: |  
        Retrieve ANBIMA market indicators.  
          
        Access daily market indices including IMA-B, IMA-S, IRF-M and other benchmark indicators  
        from the Brazilian Financial and Capital Markets Association.  
      operationId: get\_anbima\_indicators  
      parameters:  
        \- name: reference\_date  
          in: query  
          description: Reference date for indicators  
          required: false  
          schema:  
            type: string  
            format: date  
            example: '2024-01-15'  
        \- name: indicator\_ids  
          in: query  
          description: Specific indicator IDs to retrieve  
          required: false  
          schema:  
            type: array  
            items:  
              type: string  
            example: \['IMA-B', 'IMA-S'\]  
      responses:  
        '200':  
          description: Successful response  
          content:  
            application/json:  
              schema:  
                type: array  
                items:  
                  $ref: '\#/components/schemas/ANBIMAIndicator'

  /api/v1/bacen/series/{series\_code}:  
    get:  
      tags:  
        \- BACEN  
      summary: Get BACEN time series  
      description: |  
        Retrieve Central Bank of Brazil economic indicator time series.  
          
        Access over 18,000 economic time series including interest rates, exchange rates,  
        inflation indices, monetary aggregates, and other macroeconomic indicators.  
          
        Popular Series Codes:  
        \- 433: SELIC i**nterest rate**  
        \- 1: USD/BRL exchange rate  
        \- 433: CDI rate  
        \- 4389: IPCA inflation index  
      operationId: get\_bacen\_series  
      parameters:  
        \- name: series\_code  
          in: path  
          description: BACEN series code  
          required: true  
          schema:  
            type: integer  
            example: 433  
        \- name: start\_date  
          in: query  
          description: Start date for data  
          required: false  
          schema:  
            type: string  
            format: date  
            example: '2023-01-01'  
        \- name: end\_date  
          in: query  
          description: End date for data  
          required: false  
          schema:  
            type: string  
            format: date  
            example: '2024-01-01'  
      responses:  
        '200':  
          description: Successful response  
          content:  
            application/json:  
              schema:  
                type: array  
                items:  
                  $ref: '\#/components/schemas/BACENIndicator'

  /api/v1/statistics/summary:  
    get:  
      tags:  
        \- Statistics  
      summary: Get market statistics  
      description: Retrieve aggregated statistics across all data sources.  
      operationId: get\_statistics\_summary  
      responses:  
        '200':  
          description: Successful response  
          content:  
            application/json:  
              schema:  
                type: object  
                properties:  
                  cvm\_operations\_total:  
                    type: integer  
                    example: 1500  
                  cvm\_operations\_month:  
                    type: integer  
                    example: 45  
                  total\_amount\_issued\_year:  
                    type: number  
                    example: 125000000000.00  
                  average\_interest\_rate:  
                    type: number  
                    example: 11.2  
                  anbima\_indicators\_count:  
                    type: integer  
                    example: 52  
                  bacen\_series\_count:  
                    type: integer  
                    example: 18456  
                  last\_updated:  
                    type: string  
                    format: date-time  
                    example: '2024-01-15T10:00:00Z'

components:  
  securitySchemes:  
    ApiKeyAuth:  
      type: apiKey  
      in: header  
      name: X-API-Key  
      description: API key for authentication. Obtain from developer portal.  
    BearerAuth:  
      type: http  
      scheme: bearer  
      bearerFormat: JWT  
      description: JWT token authentication

  schemas:  
    OperationType:  
      type: string  
      description: Types of credit operations  
      enum:  
        \- DEBENTURES  
        \- COMMERCIAL\_NOTES  
        \- PROMISSORY\_NOTES  
        \- CRI  
        \- CRA  
        \- FIDC

    MarketType:  
      type: string  
      description: Market types for securities  
      enum:  
        \- PRIMARY  
        \- SECONDARY  
        \- BOTH

    DataFormat:  
      type: string  
      description: Response data formats  
      enum:  
        \- json  
        \- csv

    CVMCreditOperation:  
      type: object  
      required:  
        \- operation\_id  
        \- issuer\_name  
        \- issuer\_cnpj  
        \- operation\_type  
        \- issue\_date  
        \- maturity\_date  
        \- total\_amount  
        \- market\_type  
      properties:  
        operation\_id:  
          type: string  
          description: Unique operation identifier  
          example: CVM-2024-00123  
        issuer\_name:  
          type: string  
          description: Name of the issuing company  
          example: Petrobras S.A.  
        issuer\_cnpj:  
          type: string  
          description: CNPJ of the issuer  
          example: '33.000.167/0001-01'  
        operation\_type:  
          $ref: '\#/components/schemas/OperationType'  
        issue\_date:  
          type: string  
          format: date  
          description: Date of issuance  
          example: '2024-01-15'  
        maturity\_date:  
          type: string  
          format: date  
          description: Maturity date  
          example: '2029-01-15'  
        total\_amount:  
          type: number  
          description: Total amount in BRL  
          minimum: 0  
          example: 1000000000.00  
        interest\_rate:  
          type: number  
          description: Annual interest rate (%)  
          minimum: 0  
          example: 12.5  
          nullable: true  
        market\_type:  
          $ref: '\#/components/schemas/MarketType'  
        rating:  
          type: string  
          description: Credit rating  
          example: AAA  
          nullable: true  
        guarantees:  
          type: array  
          items:  
            type: string  
          description: List of guarantees  
          example: \['Real estate assets', 'Corporate guarantee'\]  
          nullable: true  
        created\_at:  
          type: string  
          format: date-time  
          description: Record creation timestamp  
          example: '2024-01-15T10:00:00Z'  
        updated\_at:  
          type: string  
          format: date-time  
          description: Last update timestamp  
          example: '2024-01-15T10:00:00Z'

    ANBIMAIndicator:  
      type: object  
      required:  
        \- indicator\_id  
        \- indicator\_name  
        \- reference\_date  
        \- value  
      properties:  
        indicator\_id:  
          type: string  
          description: Indicator identifier  
          example: IMA-B  
        indicator\_name:  
          type: string  
          description: Indicator name  
          example: Market Index Series B  
        reference\_date:  
          type: string  
          format: date  
          description: Reference date  
          example: '2024-01-15'  
        value:  
          type: number  
          description: Indicator value  
          example: 15234.56  
        variation\_daily:  
          type: number  
          description: Daily variation (%)  
          example: 0.25  
          nullable: true  
        variation\_monthly:  
          type: number  
          description: Monthly variation (%)  
          example: 1.5  
          nullable: true  
        variation\_yearly:  
          type: number  
          description: Yearly variation (%)  
          example: 8.5  
          nullable: true

    BACENIndicator:  
      type: object  
      required:  
        \- series\_code  
        \- series\_name  
        \- reference\_date  
        \- value  
        \- unit  
      properties:  
        series\_code:  
          type: integer  
          description: BACEN series code  
          example: 433  
        series\_name:  
          type: string  
          description: Series name  
          example: SELIC Interest Rate  
        reference\_date:  
          type: string  
          format: date  
          description: Reference date  
          example: '2024-01-15'  
        value:  
          type: number  
          description: Indicator value  
          example: 11.75  
        unit:  
          type: string  
          description: Unit of measurement  
          example: '% p.a.'

    PaginationMeta:  
      type: object  
      required:  
        \- page  
        \- page\_size  
        \- total\_items  
        \- total\_pages  
      properties:  
        page:  
          type: integer  
          description: Current page number  
          example: 1  
        page\_size:  
          type: integer  
          description: Items per page  
          example: 100  
        total\_items:  
          type: integer  
          description: Total number of items  
          example: 1500  
        total\_pages:  
          type: integer  
          description: Total number of pages  
          example: 15

    CVMCreditResponse:  
      type: object  
      required:  
        \- data  
        \- meta  
      properties:  
        data:  
          type: array  
          items:  
            $ref: '\#/components/schemas/CVMCreditOperation'  
          description: List of credit operations  
        meta:  
          $ref: '\#/components/schemas/PaginationMeta'

    APIHealthResponse:  
      type: object  
      required:  
        \- status  
        \- timestamp  
        \- version  
        \- services  
      properties:  
        status:  
          type: string  
          description: Service status  
          example: healthy  
        timestamp:  
          type: string  
          format: date-time  
          description: Check timestamp  
          example: '2024-01-15T10:00:00Z'  
        version:  
          type: string  
          description: API version  
          example: 1.0.0  
        services:  
          type: object  
          additionalProperties:  
            type: string  
          description: Status of dependent services  
          example:  
            database: healthy  
            cache: healthy  
            cvm\_api: healthy  
            anbima\_api: healthy  
            bacen\_api: healthy

    APIError:  
      type: object  
      required:  
        \- error  
        \- message  
        \- timestamp  
      properties:  
        error:  
          type: string  
          description: Error type  
          example: ValidationError  
        message:  
          type: string  
          description: Error message  
          example: Invalid date format  
        details:  
          type: object  
          additionalProperties: true  
          description: Additional error details  
          nullable: true  
        timestamp:  
          type: string  
          format: date-time  
          description: Error timestamp  
          example: '2024-01-15T10:00:00Z'  
\`\`\`

\---

Dockerfile.docs

\`\`\`dockerfile

## FROM python:3.11-slim

## 

## WORKDIR /app

RUN apt-get update && apt-get install \-y \\  
    curl \\  
    && rm \-rf /var/lib/apt/lists/\*

COPY requirements-docs.txt .  
RUN pip install \--no-cache-dir \-r requirements-docs.txt

COPY docs\_server.py .  
COPY static/ ./static/  
COPY templates/ ./templates/

EXPOSE 8080

HEALTHCHECK \--interval=30s \--timeout=10s \--start-period=5s \--retries=3 \\  
    CMD curl \-f http://localhost:8080/health || exit 1

CMD \["uvicorn", "docs\_server:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"\]  
\`\`\`

\---

\*Generated: February 2026\*  
