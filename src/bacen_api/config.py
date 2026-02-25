"""
Configuration for the BACEN (Banco Central do Brasil) API service.

Environment variables:
  BACEN_API_HOST  — bind host (default: 0.0.0.0)
  BACEN_API_PORT  — bind port (default: 8002)
  LOG_LEVEL       — uvicorn log level (default: info)
"""

import os

# ─── Service ──────────────────────────────────────────────────────────────────
API_TITLE = "BACEN Data API"
API_VERSION = "1.0.0"
API_DESCRIPTION = (
    "REST API for Brazilian Central Bank (BACEN) public data: "
    "SGS time series, PTAX exchange rates, Focus market expectations, "
    "and interest-rate statistics — powered by python-bcb."
)

HOST: str = os.getenv("BACEN_API_HOST", "0.0.0.0")
PORT: int = int(os.getenv("BACEN_API_PORT", "8002"))
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "info")

# ─── Pagination ───────────────────────────────────────────────────────────────
DEFAULT_PAGE: int = 1
DEFAULT_PAGE_SIZE: int = 100
MAX_PAGE_SIZE: int = 1000

# ─── SGS – well-known series ──────────────────────────────────────────────────
WELL_KNOWN_SGS: dict[str, int] = {
    "SELIC_META": 432,
    "SELIC_DIARIA": 11,
    "CDI": 12,
    "IPCA": 433,
    "IGPM": 189,
    "INPC": 188,
    "USDBRL": 1,
    "EURBRL": 21619,
    "POUPANCA": 25,
    "PIB": 4380,
}

# ─── Expectativas – available endpoint names ──────────────────────────────────
EXPECTATIVAS_ENDPOINTS: list[str] = [
    "ExpectativasMercadoAnuais",
    "ExpectativasMercadoMensais",
    "ExpectativasMercadoTrimestrais",
    "ExpectativasMercadoSelic",
    "ExpectativasMercadoTop5Anuais",
    "ExpectativasMercadoTop5Mensais",
    "ExpectativasMercadoInflacao12Meses",
    "InstituicoesCreditoras",
]

# ─── PTAX – supported currency codes (subset) ────────────────────────────────
COMMON_CURRENCIES: list[str] = [
    "USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "CNY", "ARS", "CLP",
]
