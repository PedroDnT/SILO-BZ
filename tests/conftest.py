"""
Pytest configuration and shared fixtures for Brazilian Financial Data Infrastructure tests
"""

import pytest
import asyncio
import os
import tempfile
import shutil
from typing import Dict, List, Any
from unittest.mock import Mock, AsyncMock

# Test data fixtures
@pytest.fixture
def sample_cvm_csv_data():
    """Sample CSV data in CVM format (latin-1, semicolon separated)"""
    return """CNPJ_FUNDO;DENOM_SOCIAL;DT_REG;DT_CANCEL;SIT
12.345.678/0001-90;FUNDO EXEMPLO FIDC;2020-01-15;;ATIVO
98.765.432/0001-10;FUNDO TESTE FIDC;2019-06-20;2023-12-31;CANCELADO
11.222.333/0001-44;FUNDO DEMO FIDC;2021-03-10;;ATIVO
"""

@pytest.fixture
def sample_cvm_csv_with_errors():
    """Sample CSV data with various errors"""
    return """CNPJ_FUNDO;DENOM_SOCIAL;DT_REG;DT_CANCEL;SIT
INVALID_CNPJ;FUNDO EXEMPLO FIDC;2020-01-15;;ATIVO
12.345.678/0001-90;FUNDO TESTE FIDC;invalid-date;;ATIVO
98.765.432/0001-10;FUNDO DEMO FIDC;2019-06-20;future-date;CANCELADO
11.222.333/0001-44;;2021-03-10;;ATIVO
"""

@pytest.fixture
def sample_empty_csv():
    """Empty CSV file"""
    return """CNPJ_FUNDO;DENOM_SOCIAL;DT_REG"""

@pytest.fixture
def sample_malformed_csv():
    """Malformed CSV data"""
    return """CNPJ_FUNDO,DENOM_SOCIAL,DT_REG
12.345.678/0001-90,"FUNDO EXEMPLO FIDC",2020-01-15
98.765.432/0001-10,FUNDO TESTE FIDC,2019-06-20,2023-12-31,CANCELADO
11.222.333/0001-44,FUNDO DEMO FIDC
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
        {
            "CNPJ_FUNDO": "98.765.432/0001-10",
            "DENOM_SOCIAL": "FUNDO TESTE FIDC",
            "DT_REG": "2019-06-20",
            "DT_CANCEL": "2023-12-31",
            "SIT": "CANCELADO",
            "TP_FUNDO": "FIDC"
        }
    ]

@pytest.fixture
def sample_fip_records():
    """Sample FIP records for testing"""
    return [
        {
            "CNPJ_FUNDO": "33.444.555/0001-66",
            "DENOM_SOCIAL": "FUNDO EXEMPLO FIP",
            "DT_REG": "2018-11-05",
            "VL_PATRIMONIO": "1000000.50",
            "QT_COTAS": "10000"
        }
    ]

@pytest.fixture
def sample_validation_config():
    """Sample validation configuration"""
    return {
        "required_fields": ["CNPJ_FUNDO", "DENOM_SOCIAL", "DT_REG"],
        "field_types": {
            "CNPJ_FUNDO": "cnpj",
            "DT_REG": "date",
            "VL_PATRIMONIO": "numeric"
        },
        "business_rules": []
    }

@pytest.fixture
def temp_dirs():
    """Create temporary directories for testing"""
    temp_dir = tempfile.mkdtemp()
    cache_dir = os.path.join(temp_dir, "cache")
    temp_data_dir = os.path.join(temp_dir, "temp")

    os.makedirs(cache_dir, exist_ok=True)
    os.makedirs(temp_data_dir, exist_ok=True)

    yield {
        "base": temp_dir,
        "cache": cache_dir,
        "temp": temp_data_dir
    }

    # Cleanup
    shutil.rmtree(temp_dir)

@pytest.fixture
def mock_aiohttp_response():
    """Mock aiohttp response for testing"""
    mock_response = Mock()
    mock_response.status = 200
    mock_response.read = AsyncMock(return_value=b"mock file content")
    return mock_response

@pytest.fixture
def mock_aiohttp_session(mock_aiohttp_response):
    """Mock aiohttp session for testing"""
    mock_session = Mock()
    mock_session.get = AsyncMock(return_value=mock_aiohttp_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    return mock_session

@pytest.fixture
def mock_zip_content():
    """Mock ZIP file content for testing"""
    import io
    import zipfile

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
        csv_content = """CNPJ_FUNDO;DENOM_SOCIAL;DT_REG
12.345.678/0001-90;FUNDO EXEMPLO;2020-01-15
98.765.432/0001-10;FUNDO TESTE;2019-06-20
"""
        zip_file.writestr("test_data.csv", csv_content)

    zip_buffer.seek(0)
    return zip_buffer.getvalue()

@pytest.fixture
def sample_sgs_dataframe():
    """Single-series SGS DataFrame with DatetimeIndex (for BACEN unit tests)."""
    import pandas as pd
    import numpy as np
    idx = pd.DatetimeIndex(["2024-01-01", "2024-02-01", "2024-03-01"], name="Date")
    return pd.DataFrame({"IPCA": [0.42, 0.83, np.nan]}, index=idx)


@pytest.fixture
def sample_ptax_dataframe():
    """PTAX USD/BRL DataFrame (for BACEN unit tests)."""
    import pandas as pd
    idx = pd.DatetimeIndex(["2024-01-31"], name="DateTime")
    return pd.DataFrame({"cotacaoCompra": [5.01], "cotacaoVenda": [5.02]}, index=idx)


@pytest.fixture
def sample_expectativas_dataframe():
    """Expectativas focus bulletin DataFrame (for BACEN unit tests)."""
    import pandas as pd
    import numpy as np
    return pd.DataFrame({
        "Indicador": ["IPCA", "IPCA"],
        "Data": ["2024-01-26", "2024-02-02"],
        "Mediana": [3.9, 4.0],
        "Media": [3.88, 3.99],
        "DesvioPadrao": [0.12, np.nan],
    })


# Pytest configuration
def pytest_configure(config):
    """Configure pytest with custom markers"""
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "slow: Slow running tests")
    config.addinivalue_line("markers", "cvm: CVM API tests")
    config.addinivalue_line("markers", "validation: Data validation tests")
    config.addinivalue_line("markers", "parsing: CSV parsing tests")

# Async test support
@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

# Exactly the columns of public.cvm_ingest_log (verified against Silo). Every
# audit writer's rows must be a subset: the 2026-07-25 ANBIMA incident sent
# `notes`/`error_message`, which do not exist, and ingest was silently disabled.
INGEST_LOG_COLUMNS = frozenset({
    "id", "run_id", "entity", "doc_type", "period_year", "period_month",
    "rows_upserted", "status", "error_msg", "started_at", "finished_at",
})


@pytest.fixture
def ingest_log_columns():
    return INGEST_LOG_COLUMNS
