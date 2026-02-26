# Decision Log

| Date       | Decision                           | Rationale                                                                             |
| ---------- | ---------------------------------- | ------------------------------------------------------------------------------------- |
| 2026-02-26 | Multi-service FastAPI architecture | Separate services for CVM, BACEN, B3 CALC allow independent scaling and deployment    |
| 2026-02-26 | B3 CALC fallback to sample data    | Ensures service availability when upstream calculadorarendafixa.com.br is unavailable |
| 2026-02-26 | Config-driven network settings     | Centralizes retry, timeout, DNS settings in config.py for resilience tuning           |
| 2026-02-26 | Pydantic v2 adoption               | Modern validation with better performance and cleaner API                             |
| 2026-02-26 | Latin-1 encoding for CVM CSVs      | Required for proper parsing of Brazilian regulatory data files                        |
| 2026-02-26 | In-memory pagination               | Full CSV download followed by in-memory pagination for simplicity                     |
| 2026-02-26 | Unified API Gateway with YAML      | Single entry point (port 8000) with OpenAPI spec in YAML for Redocly documentation    |

---

_Last updated: 2026-02-26_
