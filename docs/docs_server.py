"""
Documentation server for the Brazilian Financial Data Infrastructure.

Serves a unified API documentation portal for all three services:
  - CVM Credit Market API   (port 8000)
  - B3 CALC API             (port 8001)
  - BACEN Data API          (port 8002)

Run:
  uvicorn docs.docs_server:app --host 0.0.0.0 --port 8080 --reload
"""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).parent / "static"
PORT = int(os.getenv("PORT", "8080"))

app = FastAPI(
    title="BR Finance Docs",
    description="Unified documentation portal for the Brazilian Financial Data APIs.",
    version="1.0.0",
    docs_url=None,   # We serve our own UI
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse, tags=["Docs"])
async def root():
    """Main documentation portal landing page."""
    index = STATIC_DIR / "index.html"
    if index.exists():
        return HTMLResponse(content=index.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>BR Finance API Docs</h1><p>Missing static/index.html</p>")


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "healthy", "service": "docs"}


@app.get("/api/services", tags=["Docs"])
async def list_services():
    """List all available API services."""
    return JSONResponse({
        "services": [
            {
                "name": "CVM Credit Market API",
                "description": "CVM credit market data: FIDC, FIP, FIAGRO, SECURIT",
                "base_url": "http://localhost:8000",
                "docs": "http://localhost:8000/docs",
                "health": "http://localhost:8000/health",
            },
            {
                "name": "B3 CALC API",
                "description": "B3 CALC proxy for debentures, CRA, CRI pricing",
                "base_url": "http://localhost:8001",
                "docs": "http://localhost:8001/docs",
                "health": "http://localhost:8001/health",
            },
            {
                "name": "BACEN Data API",
                "description": "Banco Central do Brasil: SGS time series, PTAX FX rates, Focus expectations",
                "base_url": "http://localhost:8002",
                "docs": "http://localhost:8002/docs",
                "health": "http://localhost:8002/health",
            },
        ]
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("docs.docs_server:app", host="0.0.0.0", port=PORT, reload=True)
