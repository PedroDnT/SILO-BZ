# Coding Conventions

**Analysis Date:** 2026-04-10

## Naming Patterns

**Files:**
- One module per layer: `config.py`, `models.py`, `services.py`, `main.py` — same names in every service package
- Snake_case for all Python filenames: `bacen_client.py`, `backfill_config.py`, `progress_tracker.py`
- Test files prefixed with `test_`: `test_csv_parsing.py`, `test_data_validation.py`, etc.

**Classes:**
- PascalCase: `CVMCreditDataService`, `DataValidator`, `CacheManager`, `RotatingDNSResolver`
- Exception subclasses follow the `Error`/`Warning` suffix: `ValidationError`, `ValidationWarning`
- Enum classes use PascalCase with `Type`/`DocType` suffix: `EntityType`, `FIDCDocType`, `SECURITDocType`

**Functions and methods:**
- Snake_case throughout: `get_data`, `validate_cnpj`, `_parse_csv_content`, `_build_url`
- Private helper methods prefixed with single underscore: `_validate_cnpj`, `_get_cache_key`, `_normalize_entity`
- Async methods have no special prefix — sync/async is signaled by `async def` only

**Variables and constants:**
- Module-level constants: SCREAMING_SNAKE_CASE: `DEFAULT_PAGE_SIZE`, `CVM_BASE_URL`, `WELL_KNOWN_SGS`
- Local variables: snake_case: `cache_key`, `csv_content`, `parsed_date`
- Boolean variables prefixed with `is_`: `is_valid`, `is_zip`

**CVM data field names:**
- Raw CSV column names preserved verbatim in uppercase: `CNPJ_FUNDO`, `DENOM_SOCIAL`, `DT_REG`, `VL_PATRIM_LIQ`, `DT_COMPTC`
- Pydantic model attributes mirror source names in lowercase: `cnpj_fundo`, `denom_social`, `dt_reg`

## Code Style

**Formatting:**
- No enforced formatter config file detected (no `.flake8`, no `pyproject.toml`, no `setup.cfg`)
- `black` is listed in CLAUDE.md dev commands — run `black .` before committing
- `isort` is also called out: run `isort .` before committing

**Linting:**
- `flake8` and `mypy` referenced in CLAUDE.md but no rule overrides detected
- Type hints required on all public methods (per CLAUDE.md)

**Import order:**
1. Standard library (`os`, `io`, `csv`, `asyncio`, `re`, `logging`, `datetime`)
2. Third-party (`fastapi`, `pydantic`, `aiohttp`, `httpx`)
3. Local package (behind `if __package__:` guard — see Import Guards section)

## Import Guards (Critical Pattern)

Every `main.py` and `services.py` uses dual-run import guards to support both package imports (`python -m uvicorn src.cvm_api.main:app`) and direct script execution:

```python
if __package__:
    from .config import config, dataset_config
    from .models import DataResponse, PaginationInfo
    from ..validation_utils import validator, ValidationError, ValidationWarning
else:
    from config import config, dataset_config
    from models import DataResponse, PaginationInfo
    from validation_utils import validator, ValidationError, ValidationWarning
```

**Always preserve this pattern** in `src/cvm_api/main.py`, `src/cvm_api/services.py`, `src/bacen_api/main.py`, `src/b3_calc_api/main.py`, and `src/b3_calc_api/services.py`.

## Pydantic v2 Patterns

All models use Pydantic v2. Required patterns:

```python
from pydantic import BaseModel, ConfigDict, Field

class MyModel(BaseModel):
    model_config = ConfigDict(extra="allow")        # not class Config
    field: Optional[str] = Field(None, description="...")

    # Schema examples use json_schema_extra, not schema_extra:
    model_config = ConfigDict(
        json_schema_extra={"example": {...}}
    )
```

**Never use** (Pydantic v1 patterns):
- `.dict()` — use `.model_dump()` instead
- `.schema()` — use `.model_json_schema()` instead
- `class Config:` inner class — use `model_config = ConfigDict(...)` instead
- `schema_extra` — use `json_schema_extra` instead

## Brazilian Financial Data Parsing

**CSV encoding and delimiter (CVM sources):**
- Encoding: `latin-1` (never UTF-8 for CVM files — the source format uses latin-1)
- Delimiter: `;` (semicolon, not comma)
- Parser: stdlib `csv.DictReader` — not pandas for CVM CSV parsing
- Empty string normalization: empty values become `None` after `.strip()`

```python
csv_reader = csv.DictReader(io.StringIO(csv_content), delimiter=";")
clean_value = value.strip() if value else None
```

**ZIP extraction (monthly FIDC, FIAGRO, SECURIT):**
- Predictable CSV filename pattern: `inf_mensal_fidc_{year}{month:02d}.csv`
- Fallback: if exact filename not found, use first `.csv` in archive
- Decode extracted bytes with `latin-1`: `zip_file.read(csv_file).decode("latin-1")`

**Field name normalization:**
- CVM field names come through as uppercase strings from `csv.DictReader`
- Strip whitespace from both keys and values but do not rename fields
- Preserve raw column names in API responses; do not snake_case them

## CNPJ / CPF Validation

Located in `src/validation_utils.py`. Always use the shared `DataValidator` class or convenience functions — do not re-implement checksum logic inline.

**CNPJ format rules:**
- Accept both formatted (`12.345.678/0001-90`) and unformatted (`12345678000190`)
- Strip non-digit characters before validation: `re.sub(r'[^\d]', '', cnpj)`
- Must be exactly 14 digits
- Reject repeated-digit sequences (e.g., `00000000000000`)
- Validate two-digit checksum using weights `[5,4,3,2,9,8,7,6,5,4,3,2]` / `[6,5,4,3,2,9,8,7,6,5,4,3,2]`

**Convenience functions (preferred for simple checks):**
```python
from src.validation_utils import validate_cnpj, validate_cpf, validate_date, validate_security_code

validate_cnpj("12.345.678/0001-90")   # returns bool
validate_date("2020-01-15")            # returns bool
validate_security_code("ABCD22")       # returns bool (debenture)
validate_security_code("12A1234567-89") # returns bool (CRA/CRI)
```

**Auto-detection by field name (used in `DataValidator.validate_field`):**
- Field name contains `cnpj` → CNPJ validator
- Field name contains `cpf` → CPF validator
- Field name contains `data`, `date`, or starts with `dt_` → date validator
- Field name contains `valor`, `value`, `vl_`, or `pu` → numeric validator
- Field name contains `taxa`, `rate`, `percent` → percentage validator

## Currency Format (BRL)

Brazilian Real format uses period as thousands separator and comma as decimal separator:
- Valid: `R$ 1.234,56`, `123,45`, `1.234,56`
- Invalid: `123.45` (dot as decimal), `USD 123.45` (foreign currency)

Regex pattern for validation: `r'^\d{1,3}(\.\d{3})*,\d{2}$|^\d+,\d{2}$'`

## Security Code Formats

- Debenture: `[A-Z]{4}\d{2}` — e.g., `ABCD22`
- CRA / CRI: `\d{2}[A-Z]\d{7}-\d{2}` — e.g., `12A1234567-89`

## Datetime Convention

**Always use timezone-aware datetimes:**
```python
from datetime import datetime, timezone

datetime.now(timezone.utc)     # correct
datetime.utcnow()              # deprecated in Python 3.12 — do not use
```

Apply to: timestamp fields in Pydantic models, cache metadata, validation date logic.

## Config Patterns

**CVM and B3 APIs** use a `BaseConfig` class with class-level attributes, instantiated as a module-level singleton:
```python
# src/cvm_api/config.py
class BaseConfig:
    CVM_BASE_URL = "https://dados.cvm.gov.br/dados"
    ENCODING = "latin-1"
    CSV_SEPARATOR = ";"
    ...

config = BaseConfig()
```

**BACEN API** uses module-level constants directly (no class):
```python
# src/bacen_api/config.py
DEFAULT_PAGE_SIZE: int = 100
WELL_KNOWN_SGS: dict[str, int] = {"SELIC_META": 432, ...}
```

Do not introduce new config patterns — extend the existing one for the relevant service.

## Error Handling

**Service layer:** raise `ValueError` for expected domain errors (bad parameters, missing data, invalid format). Raise `Exception` for unexpected infrastructure failures (network, disk).

**Route layer (main.py):** uniform try/except per route, mapping service exceptions to HTTP codes:
```python
try:
    result = await data_service.get_data(...)
except ValueError as e:
    logger.error(f"Validation error: {str(e)}")
    raise HTTPException(status_code=400, detail=str(e))
except Exception as e:
    logger.error(f"Error processing request: {str(e)}", exc_info=True)
    raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
```

**Validation layer:** return `Tuple[bool, str]` from individual validators — never raise from `_validate_*` methods. Raise from `validate_field` and above only when state is unrecoverable.

## Logging

**Framework:** stdlib `logging` — one `logger = logging.getLogger(__name__)` per module.

**Patterns:**
- `logger.info(f"...")` for normal flow milestones (download started, N records parsed, cache hit/miss)
- `logger.warning(f"...")` for recoverable issues (cache error, fallback used, empty records found)
- `logger.error(f"...", exc_info=True)` for unexpected failures in route handlers

Format configured in `main.py`:
```python
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

## Comments and Docstrings

- Module-level docstrings present in all test files and `src/validation_utils.py`
- Class-level docstrings on service and config classes: `"""Service for downloading and processing CVM credit market data"""`
- Method docstrings for all public and important private methods
- Inline comments for non-obvious logic (CNPJ checksum weights, DNS rotation, alias resolution)

## Function Design

**Pagination:** computed in-memory after full CSV load; centralized in `_paginate_data(data, page, page_size)` → returns `(page_data, PaginationInfo)`. Defaults and limits live in `BaseConfig.DEFAULT_PAGE_SIZE` and `BaseConfig.MAX_PAGE_SIZE`.

**Parameter normalization:** dedicated `_normalize_entity` / `_normalize_doc_type` methods normalize to lowercase before any lookup, preventing case-sensitivity bugs.

**URL construction:** all CVM URLs built from `DatasetConfig` patterns via `_build_url(entity, doc_type, year, month)` — never constructed inline in routes.

## Module Design

**Exports:**
- No `__all__` declarations — all public names are importable
- `src/validation_utils.py` exports a module-level `validator = DataValidator()` singleton alongside standalone convenience functions

**Barrel files:** not used — each service is imported by full dotted path.

---

*Convention analysis: 2026-04-10*
