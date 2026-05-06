# Testing Patterns

**Analysis Date:** 2026-05-05

## Test Framework

**Runner:**
- pytest 9.0.3
- Config: `pytest.ini` at repo root
- Async support: pytest-asyncio 0.23.4

**Config File:** `pytest.ini`
```ini
[pytest]
pythonpath = .
asyncio_mode = auto
```

**Assertion Library:**
- Built-in pytest assertions: `assert condition`, `assert not is_valid`

**Run Commands:**
```bash
pytest                    # Run all tests
pytest -v                 # Verbose output
pytest tests/test_cvm_fetch_parse.py::TestFIFetch   # Run single test class
pytest -k "test_validate_cnpj"                      # Run tests matching name pattern
pytest --markers          # Show available markers
```

**Coverage:**
- No coverage configuration detected (no `.coveragerc` or coverage settings in `pytest.ini`)
- Hypothesis 6.98.3 available for property-based testing (installed but usage not yet detected in test files)

## Test File Organization

**Location:**
- Tests co-located in `tests/` directory separate from source
- Pattern: `tests/test_<module_name>.py` mirrors source structure

**Naming:**
- Test files: `test_*.py`
- Test classes: `Test<Feature>` (e.g., `TestCNPJValidation`, `TestFIFetch`, `TestUpsertRows`)
- Test methods: `test_<what_should_happen>` (e.g., `test_validate_cnpj_valid_formatted`, `test_fi_diario_fetch_returns_expected_columns`)

**Structure:**
```
tests/
├── conftest.py                 # Pytest fixtures and configuration
├── test_cvm_fetch_parse.py     # Fetch/parse/ingest tests for all CVM entities
├── test_data_validation.py     # DataValidator tests
└── test_ingestor.py            # Supabase and ingestor helper tests
```

## Test Structure

**Suite Organization:**
- Test classes group related tests by feature/component: `class TestCNPJValidation:` groups CNPJ validation tests
- Fixtures defined in `conftest.py` at module level
- Helper functions in test modules: `def _make_csv_bytes()`, `def _make_zip_bytes()`, `def _make_ingestor_with_capture()`

**Test Method Pattern:**

```python
class TestCNPJValidation:
    """Test CNPJ validation functionality"""

    def test_validate_cnpj_valid_formatted(self):
        """Test validation of valid formatted CNPJ"""
        validator = DataValidator()
        valid_cnpjs = ["12.345.678/0001-90", "98.765.432/0001-10"]
        for cnpj in valid_cnpjs:
            is_valid, message = validator._validate_cnpj(cnpj)
            assert is_valid, f"CNPJ {cnpj} should be valid: {message}"
```

**Async Test Pattern:**
```python
class TestFIFetch:
    @pytest.mark.asyncio
    async def test_fi_diario_fetch_returns_expected_columns(self):
        mock_bytes = _make_zip_bytes("inf_diario_fi_202503.csv", FI_DIARIO_ROWS)
        with patch.object(CVMFetcher, "_download", new_callable=AsyncMock, return_value=mock_bytes):
            fetcher = CVMFetcher()
            rows = await fetcher.fetch("fi", "inf_diario", year=2025, month=3)
        assert len(rows) == 2
```

**Setup/Teardown:**
- Fixtures handle setup/teardown via yield pattern
- Example: `temp_dirs` fixture in `conftest.py` creates temp dirs and cleans up via `shutil.rmtree(temp_dir)` after yield
- Context managers used for mock patches: `with patch.object(...):` and `with patch(...):` 

**Assertion Pattern:**
- Direct assertions: `assert is_valid`, `assert len(rows) == 2`
- Membership assertions: `assert expected_cols.issubset(set(rows[0].keys()))`
- Message assertions: `assert "14 digits" in message`
- Negation assertions: `assert not is_valid`

## Mocking

**Framework:** `unittest.mock` from standard library

**Patterns:**

```python
# Async mock for HTTP responses
from unittest.mock import AsyncMock, MagicMock, patch

mock_response = Mock()
mock_response.status = 200
mock_response.read = AsyncMock(return_value=b"mock file content")

# Patch async methods
@patch.object(CVMFetcher, "_download", new_callable=AsyncMock, return_value=mock_bytes)
async def test_fetch(self):
    fetcher = CVMFetcher()
    rows = await fetcher.fetch("fi", "inf_diario", year=2025, month=3)

# Mock Supabase client
with patch("src.pipeline.cvm_pipeline.get_supabase_client", return_value=MagicMock()):
    ingestor = CVMIngestor()

# Mock methods with return value
def _make_client(self, captured: list):
    mock_table = MagicMock(return_value=MagicMock(upsert=MagicMock()))
    client = MagicMock()
    client.table = mock_table
    return client
```

**What to Mock:**
- External HTTP calls: `CVMFetcher._download()` patched to return mock ZIP/CSV bytes
- Database operations: `get_supabase_client()`, `upsert_rows()` stubbed with `MagicMock()`
- File I/O: not explicitly mocked; tests use `tempfile.mkdtemp()` for real temp directories
- Time-dependent operations: `datetime.now()` not mocked; tests use real times

**What NOT to Mock:**
- CSV parsing: real parsing tested with synthetic CSV data (not mocked)
- Validation logic: real validators used, not mocked
- Field lookup helpers: real functions tested with fixture data
- Temporary file operations: real filesystem used for cache tests

## Fixtures and Factories

**Test Data Fixtures in `conftest.py`:**

```python
@pytest.fixture
def sample_cvm_csv_data():
    """Sample CSV data in CVM format (latin-1, semicolon separated)"""
    return """CNPJ_FUNDO;DENOM_SOCIAL;DT_REG;DT_CANCEL;SIT
12.345.678/0001-90;FUNDO EXEMPLO FIDC;2020-01-15;;ATIVO
"""

@pytest.fixture
def sample_fidc_cadastral_records():
    """Sample FIDC cadastral records for testing"""
    return [
        {
            "CNPJ_FUNDO": "12.345.678/0001-90",
            "DENOM_SOCIAL": "FUNDO EXEMPLO FIDC",
            "DT_REG": "2020-01-15",
            "DT_CANCEL": None,
            "SIT": "ATIVO",
            "TP_FUNDO": "FIDC"
        },
    ]
```

**Temporary Directory Factory in `conftest.py`:**

```python
@pytest.fixture
def temp_dirs():
    """Create temporary directories for testing"""
    temp_dir = tempfile.mkdtemp()
    cache_dir = os.path.join(temp_dir, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    yield {
        "base": temp_dir,
        "cache": cache_dir,
        "temp": temp_data_dir
    }
    shutil.rmtree(temp_dir)  # Cleanup
```

**Helper Factory Functions in Test Modules:**

```python
def _make_csv_bytes(rows: list[dict], encoding: str = "latin-1") -> bytes:
    """Create CSV bytes from list of dicts"""
    if not rows:
        return b""
    cols = list(rows[0].keys())
    lines = [";".join(cols)]
    for row in rows:
        lines.append(";".join("" if row[c] is None else str(row[c]) for c in cols))
    return "\n".join(lines).encode(encoding)

def _make_zip_bytes(csv_name: str, rows: list[dict]) -> bytes:
    """Create ZIP file bytes containing CSV"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(csv_name, _make_csv_bytes(rows))
    buf.seek(0)
    return buf.getvalue()
```

**Location:**
- Global fixtures: `tests/conftest.py`
- Local test data: defined as constants in test modules (e.g., `FI_DIARIO_ROWS`, `FIDC_MENSAL_ROWS` in `test_cvm_fetch_parse.py`)

## Coverage

**Requirements:** Not enforced (no coverage config)

**Markers Configured in `conftest.py`:**

```python
config.addinivalue_line("markers", "unit: Unit tests")
config.addinivalue_line("markers", "integration: Integration tests")
config.addinivalue_line("markers", "slow: Slow running tests")
config.addinivalue_line("markers", "cvm: CVM API tests")
config.addinivalue_line("markers", "validation: Data validation tests")
config.addinivalue_line("markers", "parsing: CSV parsing tests")
```

**View Coverage (not configured, but would use):**
```bash
pytest --cov=src --cov-report=html    # If coverage was installed
```

## Test Types

**Unit Tests:**
- Scope: Individual functions and methods in isolation
- Approach: Mock external dependencies (HTTP, database)
- Examples: `TestCNPJValidation.test_validate_cnpj_*` tests CNPJ validation logic; `TestHelperFunctions.*` tests field extraction helpers
- Location: `tests/test_data_validation.py`, `tests/test_ingestor.py` (helper function tests)

**Integration Tests:**
- Scope: Fetcher → Parser → Validator pipeline end-to-end
- Approach: Mock HTTP (patch `_download`) but use real CSV parsing and validation
- Examples: `TestFIFetch.test_fi_diario_fetch_returns_expected_columns` tests full fetch/parse flow with synthetic data
- Location: `tests/test_cvm_fetch_parse.py` (entire file is integration tests for different entity types)

**E2E Tests:**
- Framework: Not automated (no Selenium, Playwright, etc.)
- Approach: Would require real Supabase credentials and CVM API access — manual testing only

## Common Patterns

**Async Testing:**
```python
@pytest.mark.asyncio
async def test_fi_diario_fetch_returns_expected_columns(self):
    mock_bytes = _make_zip_bytes("inf_diario_fi_202503.csv", FI_DIARIO_ROWS)
    with patch.object(CVMFetcher, "_download", new_callable=AsyncMock, return_value=mock_bytes):
        fetcher = CVMFetcher()
        rows = await fetcher.fetch("fi", "inf_diario", year=2025, month=3)
    assert len(rows) == 2
```

**Error Testing — Exception Raised:**
```python
def test_validate_cnpj_invalid_checksum(self):
    """Test validation of CNPJ with invalid checksum"""
    validator = DataValidator()
    invalid_cnpj = "12.345.678/0001-91"  # Last digit should be 0
    is_valid, message = validator._validate_cnpj(invalid_cnpj)
    assert not is_valid
    assert "checksum" in message
```

**Error Testing — Collection Pattern:**
```python
def test_validate_record_with_errors(self):
    """Test that validation collects multiple errors"""
    validator = DataValidator()
    record = {"CNPJ_FUNDO": "invalid", "DT_REG": "invalid-date"}
    required = ["CNPJ_FUNDO"]
    field_types = {"CNPJ_FUNDO": "cnpj", "DT_REG": "date"}
    
    errors, warnings = validator.validate_record(record, required, field_types)
    assert len(errors) > 0  # Multiple validation failures collected
    assert any("CNPJ" in e.field for e in errors)
```

**Parametric Testing with Loops:**
```python
def test_validate_cnpj_valid_formatted(self):
    """Test validation of valid formatted CNPJ"""
    validator = DataValidator()
    valid_cnpjs = [
        "12.345.678/0001-90",
        "98.765.432/0001-10",
        "11.222.333/0001-44"
    ]
    for cnpj in valid_cnpjs:
        is_valid, message = validator._validate_cnpj(cnpj)
        assert is_valid, f"CNPJ {cnpj} should be valid: {message}"
```

**Setup Pattern with Helper Methods:**
```python
class TestUpsertRows:
    def _make_client(self, captured: list):
        """Build a mock Supabase client that records upserted rows."""
        mock_exec  = MagicMock(return_value=MagicMock())
        mock_table = MagicMock(return_value=MagicMock(upsert=mock_upsert))
        client = MagicMock()
        client.table = mock_table
        return client

    def test_upsert_small_batch_single_call(self):
        captured = []
        client = self._make_client(captured)
        rows = [{"id": i} for i in range(10)]
        result = upsert_rows(client, "test_table", rows)
        assert result == 10
```

---

*Testing analysis: 2026-05-05*
