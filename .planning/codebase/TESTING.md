# Testing Patterns

**Analysis Date:** 2026-04-10

## Framework & Runner

- **Framework:** `pytest` (no pytest-asyncio plugin detected — async handled via custom `event_loop` fixture)
- **Run command:** `PYTHONPATH=. pytest tests/ -v` (PYTHONPATH required for src imports in git worktrees)
- **Current coverage:** 58 tests, 100% passing (as of 2026-02-24)
- **Test location:** `tests/` directory at repo root

## Test Files

| File | Lines | Focus |
|------|-------|-------|
| `tests/conftest.py` | ~165 | Shared fixtures: CSV samples, mock HTTP sessions, temp dirs |
| `tests/test_csv_parsing.py` | 280 | CVM CSV parsing: latin-1, semicolons, ZIP extraction, edge cases |
| `tests/test_cvm_url_patterns.py` | 64 | URL pattern construction for all entity/doc_type combos |
| `tests/test_data_validation.py` | 500 | CNPJ, CPF, date, currency, security code validators |
| `tests/test_live_endpoints.py` | 203 | End-to-end live CVM API calls (auto-skip when unreachable) |

## Pytest Markers

Registered in `conftest.pytest_configure`:

| Marker | Use |
|--------|-----|
| `unit` | Pure unit tests with no I/O |
| `integration` | Tests that call real services |
| `slow` | Long-running tests |
| `cvm` | CVM API-specific tests |
| `validation` | Data validation tests |
| `parsing` | CSV parsing tests |

Run subsets: `pytest -m "unit and not slow"`, `pytest -m cvm`

## Test Class Structure

Tests are organized into classes per feature area within each file:

```python
class TestCSVParseContent:
    """Test CSV content parsing functionality"""
    def test_parse_valid_csv_latin1_semicolon(self, sample_cvm_csv_data): ...
    def test_parse_csv_with_whitespace(self): ...

class TestZIPHandling:
    def test_extract_csv_from_zip(self, mock_zip_content): ...
```

No inheritance from base test classes — each class stands alone.

## Shared Fixtures (`tests/conftest.py`)

### CSV Data Fixtures

| Fixture | Type | Description |
|---------|------|-------------|
| `sample_cvm_csv_data` | `str` | Valid FIDC cadastral CSV (latin-1, semicolons, 3 records) |
| `sample_cvm_csv_with_errors` | `str` | CSV with invalid CNPJ, bad dates, empty fields |
| `sample_empty_csv` | `str` | Header-only CSV (0 data rows) |
| `sample_malformed_csv` | `str` | Comma-delimited CSV (wrong format) |
| `sample_fidc_cadastral_records` | `List[dict]` | Pre-parsed FIDC record dicts |
| `sample_fip_records` | `List[dict]` | Pre-parsed FIP record dicts |
| `sample_validation_config` | `dict` | Required fields + type config |

### Infrastructure Fixtures

| Fixture | Description |
|---------|-------------|
| `temp_dirs` | Temp `cache/` and `temp/` dirs, cleaned up after each test |
| `mock_aiohttp_response` | Mock HTTP 200 response returning `b"mock file content"` |
| `mock_aiohttp_session` | Mock aiohttp session with context manager support |
| `mock_zip_content` | In-memory ZIP with a valid CSV inside |
| `event_loop` | Session-scoped asyncio event loop for async tests |

## Mocking Strategy

**HTTP layer:** `unittest.mock.Mock` / `AsyncMock` — wraps `aiohttp.ClientSession.get`. Real network calls are NOT made in unit tests.

```python
@pytest.fixture
def mock_aiohttp_session(mock_aiohttp_response):
    mock_session = Mock()
    mock_session.get = AsyncMock(return_value=mock_aiohttp_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    return mock_session
```

**File system:** `tempfile.mkdtemp()` via `temp_dirs` fixture — real temp dirs, cleaned up via `shutil.rmtree` in teardown.

**No database mocking** — the services have no database layer; all state is in-memory or file-based.

## Live Integration Tests (`test_live_endpoints.py`)

These tests call the real CVM API (`dados.cvm.gov.br`):

- **Auto-skip mechanism:** Network reachability check via `socket.connect` before each test class; marks all tests in class as `pytest.skip` if unreachable
- **No fallback to mock data** — these tests fail loudly if the network is available but CVM returns unexpected data
- **Validates full pipeline:** HTTP download → ZIP/CSV extraction → latin-1 decode → pagination → JSON response shape
- **Run separately:** `pytest tests/test_live_endpoints.py -v` (slow, network-dependent)

## Data Validation Tests (`test_data_validation.py`)

Extensive coverage of `src/validation_utils.py`:

- **CNPJ:** valid formatted/unformatted, invalid checksum, repeated digits, wrong length
- **CPF:** similar coverage to CNPJ
- **Dates:** ISO format, Brazilian `dd/mm/yyyy`, invalid strings, edge cases
- **Currency (BRL):** Brazilian Real format (`1.234,56`), rejects dot-decimal format
- **Security codes:** debenture (`ABCD22`), CRA/CRI (`12A1234567-89`), invalid patterns

## URL Pattern Tests (`test_cvm_url_patterns.py`)

Tests `DatasetConfig.get_dataset_config()` for every valid entity/doc_type combination:

```python
def test_fidc_url():
    config = get_dataset_config("fidc", "cadastral")
    assert "dados.cvm.gov.br" in config.url_pattern
```

Ensures URL construction logic stays correct when config is modified.

## Async Test Support

Session-scoped `event_loop` fixture in `conftest.py` enables async tests:

```python
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
```

Async test methods decorated with `@pytest.mark.asyncio` (from `pytest-asyncio` or manual `asyncio.run()`).

## Running Tests

```bash
# Full suite (from repo root, PYTHONPATH required)
PYTHONPATH=. pytest tests/ -v

# Single file
PYTHONPATH=. pytest tests/test_csv_parsing.py -v

# Single test
PYTHONPATH=. pytest tests/test_cvm_url_patterns.py::test_fidc_url -v

# By marker
PYTHONPATH=. pytest tests/ -m validation -v
PYTHONPATH=. pytest tests/ -m "not integration" -v

# Live endpoints only
PYTHONPATH=. pytest tests/test_live_endpoints.py -v
```

## Coverage Gaps

- **BACEN API** (`src/bacen_api/`) — no dedicated test file; covered only indirectly via live endpoint tests
- **B3 CALC API** (`src/b3_calc_api/`) — no dedicated test file; sample data fallback untested
- **Backfill tool** (`src/tools/backfill.py`) — no tests
- **On-chain bridge layer** — does not exist yet; will require new test file when added
- **Rate limiting** — env vars defined but not wired; no tests

---

*Testing analysis: 2026-04-10*
