# Product Context

Brazilian Financial Data Infrastructure — a multi-service platform for accessing Brazilian financial market data from public sources.

## Overview

Provides unified API access to CVM (Securities Commission), BACEN (Central Bank), and B3 (Stock Exchange) data for credit market analysis, fixed income pricing, and economic indicators.

## Core Features

- **CVM Credit API**: FIDC, FIP, FIAGRO, SECURIT monthly/quarterly/annual data
- **BACEN API**: SGS time series, PTAX exchange rates, Focus market expectations
- **B3 CALC API**: Fixed income pricing for debentures, CRA, CRI
- **Historical Backfill**: CLI tool for bulk historical CVM data download with resume capability

## Technical Stack

- FastAPI (async web framework)
- Pydantic v2 (data validation)
- python-bcb (BACEN client)
- Docker & Docker Compose
- pytest (58 tests, 100% passing)

---

_Last updated: 2026-02-26_
