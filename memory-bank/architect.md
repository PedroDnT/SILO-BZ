# MemoriPilot: System Architect

## Overview

This file contains the architectural decisions and design patterns for the Brazilian Financial Data Infrastructure project.

## Architectural Decisions

1. **Multi-Service Architecture**: Separate FastAPI services for CVM, BACEN, and B3 CALC APIs, each running on its own port (8000, 8002, 8001)
2. **Fallback Pattern**: B3 CALC API falls back to sample data when upstream is unavailable - preserve this behavior
3. **Config-Driven Network Settings**: CVM retry/backoff and DNS settings are config-driven, not hardcoded
4. **Pydantic v2**: All new code uses v2 patterns (model_dump(), ConfigDict, json_schema_extra)
5. **Import Guards**: Service main.py files use `if __package__:` guards for dual-run compatibility
6. **Async Wrapper**: BACEN uses async wrapper around sync python-bcb library

---

_Last updated: 2026-02-26_
