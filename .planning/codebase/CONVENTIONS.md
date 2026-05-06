# Coding Conventions

**Analysis Date:** 2026-05-05

## Naming Patterns

**Files:**
- Module files: lowercase with underscores: `cvm_fetcher.py`, `cvm_config.py`, `supabase_client.py`
- Test files: `test_<module_name>.py` pattern: `test_data_validation.py`, `test_cvm_fetch_parse.py`, `test_ingestor.py`
- Configuration files: `*_config.py` suffix: `cvm_config.py`

**Functions:**
- Lowercase with underscores: `_normalize_cnpj()`, `_validate_cnpj()`, `_parse_csv()`
- Private/internal functions: prefix with single underscore: `_rotate_nameservers()`, `_save_cache()`, `_extract_csv_from_zip()`
- Public API methods: no underscore prefix: `fetch()`, `validate_field()`, `validate_record()`
- Helper functions in modules: prefix with underscore if module-level: `_find_field()`, `_find_cnpj_field()`, `_find_inadimpl()` in `src/pipeline/cvm_pipeline.py`

**Variables:**
- Lowercase with underscores: `base_url`, `cache_dir`, `csv_name_pattern`, `max_retries`
- Constants: UPPERCASE: `_CHUNK_SIZE = 500` in `src/store/supabase_client.py`, `REQUEST_TIMEOUT`, `MAX_RETRIES`
- Private attributes in classes: single underscore prefix: `self._service`, `self._supabase`, `self._validators`

**Types:**
- Classes: PascalCase: `CVMFetcher`, `DataValidator`, `CVMIngestor`, `RotatingDNSResolver`, `ValidationError`, `ValidationWarning`, `EntityType`
- Enums: PascalCase with str Enum base: `class EntityType(str, Enum):` in `src/fetchers/cvm_config.py`
- Type hints: full typing imports from `typing` module: `Dict[str, Any]`, `List[str]`, `Optional[int]`, `Tuple[bool, str]`

## Code Style

**Formatting:**
- No explicit formatter configured (no `.prettierrc` or black/autopep8 config)
- Standard Python indentation: 4 spaces
- Line length: appears to target ~100-120 characters based on code samples
- No trailing whitespace

**Linting:**
- No `.eslintrc` or equivalent Python linter config found
- Code follows PEP 8 conventions implicitly (lowercase modules, uppercase constants, PascalCase classes)

## Import Organization

**Order:**
1. Standard library imports: `import os`, `import asyncio`, `import csv`, `import logging`
2. Third-party imports: `import aiohttp`, `import pandas`, `import dns.resolver`, `from supabase import create_client`
3. Local/relative imports: `from .cvm_config import config, dataset_config`, `from src.fetchers.cvm_fetcher import CVMFetcher`

**Path Aliases:**
- No path aliases configured (no `jsconfig.json` or `tsconfig.json`)
- Relative imports used within package: `from .cvm_config import config`
- Absolute imports from repo root: `from src.fetchers.cvm_fetcher import CVMFetcher` (requires `pythonpath = .` in `pytest.ini`)

**Module Exports:**
- `src/fetchers/__init__.py` re-exports: `from .cvm_fetcher import CVMFetcher` and `from .bacen_fetcher import BacenClient`
- `src/pipeline/__init__.py` re-exports: `from .cvm_pipeline import CVMIngestor`
- Allows importing like: `from src.fetchers import CVMFetcher`

## Error Handling

**Custom Exceptions:**
- `ValidationError` in `src/parsers/validation.py`: custom exception with fields (field, value, message, error_type)
- `ValidationWarning` in `src/parsers/validation.py`: custom warning class (not raising, but collecting and returning)

**Patterns:**
- Explicit ValueError/RuntimeError for validation/parameter failures: `raise ValueError(f"year is required for {entity}/{doc_type}")`
- Catch-all exceptions with re-raise for context: `except aiohttp.ClientError as exc: ... raise RuntimeError(f"Download failed...") from exc`
- Silent fallback with logging: `except Exception as exc: logger.warning(f"Cache write failed: {exc}")` in `src/fetchers/cvm_fetcher.py`
- Validation returns tuple: `(bool, str)` pattern — valid flag + error message string in `src/parsers/validation.py`
- Multiple errors collected in lists: validation methods return `(List[ValidationError], List[ValidationWarning])` not raising immediately

## Logging

**Framework:** Python's built-in `logging` module

**Patterns:**
- Module-level logger: `logger = logging.getLogger(__name__)` at top of each module
- Info-level for major operations: `logger.info(f"CVM fetch: {entity}/{doc_type} year={year} month={month} -> {url}")`
- Warning for non-critical failures: `logger.warning(f"Cache write failed: {exc}")`, `logger.warning(f"Custom DNS resolver unavailable...")`
- Error for actual errors: `logger.error("Upsert failed for table=%s chunk_start=%d: %s", table, i, exc)` in `src/store/supabase_client.py`
- F-strings used for inline formatting in logger calls
- Percentage completion logged: `logger.info(f"CVM parse: {entity}/{doc_type} -> {len(rows)} rows in {time.time() - started:.1f}s")`

## Comments

**When to Comment:**
- Module-level docstrings: required on every module, describing public surface and usage
- Class-level docstrings: on public classes, describing purpose
- Method docstrings: on public API methods with parameters and return type descriptions
- Inline comments: sparingly — code is self-documenting; use for WHY not WHAT
- Section separators: `# ---------------------------------------------------------------- <section>` used to organize logical code blocks within classes

**Docstring Style:**
- Triple-quoted docstrings at module, class, and method level
- Concise purpose statement on first line
- Extended description in subsequent paragraphs if complex
- Example: `"""CVM fetcher — downloads ZIP/CSV files from dados.cvm.gov.br with retry, DNS rotation, and on-disk caching, then extracts and parses the CSV payload into a list of dict rows. Public surface: CVMFetcher().fetch(...) -> List[dict]"""`
- Method docstrings document parameters and return values: `"""Download, decompress (if needed), and parse one CVM CSV. Returns the full list of row dicts. Caller is responsible for storage."""`

## Function Design

**Size:** 
- Small focused functions: most helpers 10-20 lines
- Larger methods for complex orchestration (e.g., `validate_dataset()` ~60 lines in `src/parsers/validation.py`)
- Private helper methods extracted to keep public methods readable

**Parameters:**
- Type hints always included: `def fetch(self, entity: str, doc_type: str, year: Optional[int] = None, month: Optional[int] = None) -> List[Dict[str, Any]]:`
- Optional parameters have default values: `year: Optional[int] = None`
- **kwargs used rarely; explicit parameters preferred for clarity
- Variadic `*candidates` used for fallback matching: `def _find_field(row: Dict[str, Any], *candidates: str) -> Optional[str]:`

**Return Values:**
- Single return type always specified: `-> List[Dict[str, Any]]`, `-> str`, `-> None`
- Tuple returns for multiple values: `-> Tuple[str, Dict]` in `_build_url()`
- Tuple returns for error patterns: `-> Tuple[bool, str]` for validation results
- None explicit for optional returns: `-> Optional[str]`, `-> Optional[Dict]`

## Module Design

**Exports:**
- Public interface via `__all__` not used; rely on naming conventions (no underscore = public)
- Classes exported via module docstring: `Public surface: CVMFetcher().fetch(...)`
- Helper functions prefixed with underscore are internal

**Structure within Modules:**
- Comments separate sections with `# ---------------------------------------------------------------- <name>`
- Related methods grouped in sections: helpers, DNS, cache, validate params, HTTP, parse, public API
- Classes group related functionality: `CVMFetcher` contains fetch/download/parse in one unit
- Config/lookup data in separate config modules: `cvm_config.py` holds `FetcherConfig` class and `DatasetConfig` with dataset definitions

**Configuration Management:**
- `FetcherConfig` class in `src/fetchers/cvm_config.py` holds config as class attributes
- Config values read from environment at class definition: `CVM_BASE_URL = os.getenv("CVM_BASE_URL", "https://...")`
- Singletons created at module level: `config = FetcherConfig()`, `dataset_config = DatasetConfig()`
- Accessed via module import: `from .cvm_config import config, dataset_config`

---

*Convention analysis: 2026-05-05*
