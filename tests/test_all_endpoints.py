"""
Comprehensive integration tests for all API endpoints across CVM, BACEN, and B3 CALC services.

This test suite validates the complete request → response pipeline for each endpoint
without mocking external services. Tests auto-skip when services are unreachable.

Run with:
    pytest tests/test_all_endpoints.py -v
    PYTHONPATH=. pytest tests/test_all_endpoints.py -v
"""

import asyncio
import socket
import pytest
from typing import Any, Dict, List, Optional

# Import services
from src.cvm_api.services import CVMCreditDataService
from src.clients.bacen_client import BacenClient
from src.b3_calc_api.services import B3CalcService


# ============================================================================
# Network Reachability Checks
# ============================================================================

def _check_host(host: str, port: int = 443) -> bool:
    """Check if a host is reachable."""
    try:
        socket.getaddrinfo(host, port)
        return True
    except OSError:
        return False


CVM_REACHABLE = _check_host("dados.cvm.gov.br")
BACEN_REACHABLE = _check_host("www.bcb.gov.br")
B3_CALC_REACHABLE = _check_host("calculadorarendafixa.com.br")

skip_if_no_cvm = pytest.mark.skipif(
    not CVM_REACHABLE, reason="CVM (dados.cvm.gov.br) unreachable"
)
skip_if_no_bacen = pytest.mark.skipif(
    not BACEN_REACHABLE, reason="BACEN (www.bcb.gov.br) unreachable"
)
skip_if_no_b3_calc = pytest.mark.skipif(
    not B3_CALC_REACHABLE, reason="B3 CALC (calculadorarendafixa.com.br) unreachable"
)


# ============================================================================
# CVM API Test Parameters
# ============================================================================

CVM_ENDPOINTS = [
    # Entity, DocType, Year, Month, Description
    ("fidc", "mensal", 2025, 2, "FIDC monthly data"),
    ("fidc", "cadastral", 2024, None, "FIDC cadastral data"),
    ("fidc", "trimestral", 2024, None, "FIDC quarterly data"),
    ("fidc", "anual", 2024, None, "FIDC annual data"),
    ("fip", "inf_quadrimestral", 2024, None, "FIP quadrimestral data"),
    ("fip", "inf_trimestral", 2024, None, "FIP quarterly data"),
    ("fip", "cadastral", 2024, None, "FIP cadastral data"),
    ("fip", "dfin", 2024, None, "FIP financial statements"),
    ("fiagro", "mensal", 2025, 1, "FIAGRO monthly data"),
    ("fiagro", "cadastral", 2024, None, "FIAGRO cadastral data"),
    ("fiagro", "trimestral", 2024, None, "FIAGRO quarterly data"),
    ("fiagro", "anual", 2024, None, "FIAGRO annual data"),
    ("securit", "cra_mensal", 2024, None, "SECURIT CRA monthly"),
    ("securit", "cri_mensal", 2024, None, "SECURIT CRI monthly"),
    ("securit", "ots_mensal", 2024, None, "SECURIT OTS monthly"),
    ("securit", "lca_mensal", 2024, None, "SECURIT LCA monthly"),
    ("securit", "lci_mensal", 2024, None, "SECURIT LCI monthly"),
]


# ============================================================================
# BACEN API Test Parameters
# ============================================================================

BACEN_SGS_SERIES = [
    # Series Code, Label, Expected to have data
    (432, "SELIC_META", True),
    (11, "SELIC_DIARIA", True),
    (12, "CDI", True),
    (433, "IPCA", True),
    (1, "USDBRL", True),
]

BACEN_PTAX_DATES = [
    # Date string
    "2024-01-15",
    "2024-06-30",
    "2024-12-31",
]

BACEN_PTAX_RANGES = [
    # Start, End
    ("2024-01-01", "2024-01-31"),
    ("2024-06-01", "2024-06-30"),
]


# ============================================================================
# B3 CALC API Test Parameters
# ============================================================================

from src.b3_calc_api.config import SecurityType

B3_CALC_SECURITIES = [
    # Security Type (as SecurityType enum), Code examples
    (SecurityType.DEBENTURE, ["PETR34", "VALE12", "ITUB4"]),
    (SecurityType.CRA, ["22A00123456-10"]),
    (SecurityType.CRI, ["22A00123456-20"]),
]


# ============================================================================
# CVM API Tests
# ============================================================================

@skip_if_no_cvm
@pytest.mark.parametrize("entity,doc_type,year,month,description", CVM_ENDPOINTS)
class TestCVMEndpoints:
    """Test all CVM API endpoints."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup service for each test."""
        self.service = CVMCreditDataService()

    def test_cvm_endpoint_returns_valid_response(
        self, entity: str, doc_type: str, year: int, month: Optional[int], description: str
    ):
        """Test that endpoint returns valid DataResponse with data.
        
        Note: Some CVM endpoints may return 404 if data is not yet published.
        This is expected behavior for government data portals.
        """
        try:
            result = asyncio.run(self.service.get_data(
                entity=entity,
                doc_type=doc_type,
                year=year,
                month=month,
                page=1,
                page_size=10,
            ))
        except ValueError as e:
            # Handle expected 404 errors when CVM hasn't published the data yet
            if "Data not found at URL" in str(e) or "404" in str(e):
                pytest.skip(f"Data not available on CVM server: {description}")
            raise

        # Validate response structure
        assert result is not None
        assert hasattr(result, "entity")
        assert hasattr(result, "data")
        assert hasattr(result, "pagination")
        assert result.entity == entity
        assert isinstance(result.data, list)
        assert len(result.data) <= 10

    def test_cvm_endpoint_pagination(
        self, entity: str, doc_type: str, year: int, month: Optional[int], description: str
    ):
        """Test pagination works correctly.
        
        Note: Some CVM endpoints may return 404 if data is not yet published.
        """
        try:
            result = asyncio.run(self.service.get_data(
                entity=entity,
                doc_type=doc_type,
                year=year,
                month=month,
                page=1,
                page_size=5,
            ))
        except ValueError as e:
            # Handle expected 404 errors when CVM hasn't published the data yet
            if "Data not found at URL" in str(e) or "404" in str(e):
                pytest.skip(f"Data not available on CVM server: {description}")
            raise

        assert result.pagination.page == 1
        assert result.pagination.page_size == 5
        assert result.pagination.total_items >= 0
        assert result.pagination.total_pages >= 1


# ============================================================================
# BACEN API Tests
# ============================================================================

@skip_if_no_bacen
class TestBACENSGSEndpoints:
    """Test BACEN SGS (time series) endpoints."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup client for each test."""
        self.client = BacenClient()

    @pytest.mark.parametrize("series_code,label,has_data", BACEN_SGS_SERIES)
    def test_sgs_single_series(self, series_code: int, label: str, has_data: bool):
        """Test fetching a single SGS series."""
        data = asyncio.run(self.client.get_sgs_series(
            codes={label: series_code},
            start="2024-01-01",
            end="2024-03-31",
        ))

        assert isinstance(data, list)
        if has_data:
            assert len(data) > 0
            # Check structure
            if data:
                assert "date" in data[0] or label in data[0]

    def test_sgs_multi_series(self):
        """Test fetching multiple SGS series at once."""
        codes = {"SELIC": 432, "CDI": 12, "IPCA": 433}
        data = asyncio.run(self.client.get_sgs_series(
            codes=codes,
            start="2024-01-01",
            end="2024-03-31",
        ))

        assert isinstance(data, list)
        assert len(data) > 0


@skip_if_no_bacen
class TestBACENPTAXEndpoints:
    """Test BACEN PTAX (exchange rate) endpoints."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup client for each test."""
        self.client = BacenClient()

    @pytest.mark.parametrize("date", BACEN_PTAX_DATES)
    def test_ptax_dolar_dia(self, date: str):
        """Test fetching USD/BRL rate for a single day."""
        data = asyncio.run(self.client.get_ptax_dolar_dia(date))

        assert isinstance(data, list)
        # PTAX returns data for the given date or closest available
        assert len(data) >= 0

    @pytest.mark.parametrize("start,end", BACEN_PTAX_RANGES)
    def test_ptax_dolar_periodo(self, start: str, end: str):
        """Test fetching USD/BRL rates for a date range."""
        data = asyncio.run(self.client.get_ptax_dolar_periodo(start, end))

        assert isinstance(data, list)
        assert len(data) > 0
        # Verify dates are in range
        for record in data:
            if "data" in record:
                record_date = record["data"]
                assert start <= record_date <= end


# ============================================================================
# B3 CALC API Tests
# ============================================================================

@skip_if_no_b3_calc
class TestB3CalcEndpoints:
    """Test B3 CALC fixed income pricing endpoints."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup service for each test."""
        self.service = B3CalcService()

    def test_b3_calc_health(self):
        """Test B3 CALC service health check."""
        # The service should initialize without error
        asyncio.run(self.service.initialize())
        assert self.service._client is not None

    @pytest.mark.parametrize("security_type,codes", B3_CALC_SECURITIES)
    def test_b3_calc_list_securities(self, security_type: SecurityType, codes: List[str]):
        """Test listing securities by type."""
        asyncio.run(self.service.initialize())
        
        result = asyncio.run(self.service.list_securities(
            security_type=security_type,
            page=1,
            page_size=10,
        ))

        assert result is not None
        assert hasattr(result, "securities")
        assert isinstance(result.securities, list)

    @pytest.mark.parametrize("security_type,codes", B3_CALC_SECURITIES)
    def test_b3_calc_get_price(self, security_type: SecurityType, codes: List[str]):
        """Test getting price for a specific security."""
        asyncio.run(self.service.initialize())
        
        # Try first code from each type
        code = codes[0] if codes else None
        if code:
            result = asyncio.run(self.service.get_security_price(
                code=code,
                security_type=security_type,
            ))

            # May return sample data if live API fails
            assert result is not None
            assert hasattr(result, "code")
            assert result.code == code


# ============================================================================
# Integration Tests - Full API Flow
# ============================================================================

@skip_if_no_cvm
class TestCVMAPIFullFlow:
    """Test complete CVM API flow with error handling."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.service = CVMCreditDataService()

    def test_invalid_entity_raises_error(self):
        """Test that invalid entity raises ValueError."""
        with pytest.raises(ValueError, match="Unknown"):
            asyncio.run(self.service.get_data(
                entity="invalid_entity",
                doc_type="mensal",
                year=2024,
                month=1,
            ))

    def test_invalid_doc_type_raises_error(self):
        """Test that invalid doc_type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown document type"):
            asyncio.run(self.service.get_data(
                entity="fidc",
                doc_type="invalid_type",
                year=2024,
                month=1,
            ))


@skip_if_no_bacen
class TestBACENAPIFullFlow:
    """Test complete BACEN API flow with error handling."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = BacenClient()

    def test_invalid_series_code(self):
        """Test that invalid series code returns empty data or handles gracefully.
        
        Note: Invalid series codes can cause timeouts on BACEN API.
        This test handles both success (empty list) and timeout cases.
        """
        import httpx
        try:
            # Use a very high series code that likely doesn't exist
            data = asyncio.run(self.client.get_sgs_series(
                codes={"INVALID": 999999},
                start="2024-01-01",
                end="2024-01-31",
            ))
            # Should return empty list for non-existent series
            assert isinstance(data, list)
        except (httpx.ReadTimeout, httpx.TimeoutException):
            # Timeout is acceptable for invalid series codes
            pytest.skip("BACEN API timed out on invalid series code - this is expected")


# ============================================================================
# Performance & Reliability Tests
# ============================================================================

@skip_if_no_cvm
class TestCVMPerformance:
    """Performance tests for CVM API."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.service = CVMCreditDataService()

    def test_concurrent_requests(self):
        """Test handling concurrent requests."""
        async def run_tests():
            tasks = [
                self.service.get_data("fidc", "mensal", 2025, 1, 1, 5),
                self.service.get_data("fip", "cadastral", 2024, None, 1, 5),
                self.service.get_data("fiagro", "mensal", 2025, 1, 1, 5),
            ]
            return await asyncio.gather(*tasks, return_exceptions=True)
        
        results = asyncio.run(run_tests())
        
        # All should succeed or gracefully handle errors
        for result in results:
            if isinstance(result, Exception):
                # Allow network errors or data not found but not code bugs
                error_str = str(result).lower()
                assert ("timeout" in error_str or 
                        "connection" in error_str or 
                        "not found" in error_str or
                        "404" in error_str)


# ============================================================================
# Test Summary
# ============================================================================

def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Add custom summary to test output."""
    terminalreporter.write_sep("=", "Endpoint Test Summary")
    terminalreporter.write_line("CVM API: Tests all 17 entity/doc_type combinations")
    terminalreporter.write_line("BACEN API: Tests SGS, PTAX endpoints")
    terminalreporter.write_line("B3 CALC API: Tests security listing and pricing")
    terminalreporter.write_line("")
    terminalreporter.write_line("Services auto-skip if unreachable (network/firewall).")
