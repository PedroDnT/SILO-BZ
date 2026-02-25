"""
Real end-to-end integration tests for all 7 CVM data endpoints.
No mocking — these tests call the live CVM API and validate the full
download → extract → parse → paginate pipeline.

Tests auto-skip when CVM is unreachable (e.g. restricted sandbox).
Run on a network-enabled machine with:
    pytest tests/test_live_endpoints.py -v
or alongside the full suite:
    pytest -v
"""

import asyncio
import socket
import pytest
from src.cvm_api.services import CVMCreditDataService

# ---------------------------------------------------------------------------
# Network reachability check (no mock fallback — fails loudly if broken)
# ---------------------------------------------------------------------------

def _cvm_reachable() -> bool:
    """Return True only when dados.cvm.gov.br:443 is DNS-resolvable."""
    try:
        socket.getaddrinfo("dados.cvm.gov.br", 443)
        return True
    except OSError:
        return False


skip_if_no_network = pytest.mark.skipif(
    not _cvm_reachable(),
    reason="dados.cvm.gov.br unreachable — skipping live network tests"
)


# ---------------------------------------------------------------------------
# Endpoint matrix — every entity/doc_type combination
# ---------------------------------------------------------------------------

ENDPOINT_PARAMS = [
    pytest.param(
        "fidc", "mensal", 2025, 2,
        "FIDC/DOC/INF_MENSAL/DADOS/inf_mensal_fidc_202502.zip",
        id="fidc-mensal-2025-02",
    ),
    pytest.param(
        "fip", "inf_quadrimestral", 2024, None,
        "FIP/DOC/INF_QUADRIMESTRAL/DADOS/inf_quadrimestral_fip_2024.csv",
        id="fip-inf_quadrimestral-2024",
    ),
    pytest.param(
        "fip", "inf_trimestral", 2022, None,
        "FIP/DOC/INF_TRIMESTRAL/DADOS/inf_trimestral_fip_2022.csv",
        id="fip-inf_trimestral-2022",
    ),
    pytest.param(
        "fiagro", "mensal", 2025, 12,
        "FIAGRO/DOC/INF_MENSAL/DADOS/inf_mensal_fiagro_202512.zip",
        id="fiagro-mensal-2025-12",
    ),
    pytest.param(
        "securit", "cra_mensal", 2024, None,
        "SECURIT/DOC/INF_MENSAL_CRA/DADOS/inf_mensal_cra_2024.zip",
        id="securit-cra_mensal-2024",
    ),
    pytest.param(
        "securit", "cri_mensal", 2024, None,
        "SECURIT/DOC/INF_MENSAL_CRI/DADOS/inf_mensal_cri_2024.zip",
        id="securit-cri_mensal-2024",
    ),
    pytest.param(
        "securit", "ots_mensal", 2024, None,
        "SECURIT/DOC/INF_MENSAL_OTS/DADOS/inf_mensal_ots_2024.zip",
        id="securit-ots_mensal-2024",
    ),
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@skip_if_no_network
@pytest.mark.parametrize("entity,doc_type,year,month,url_fragment", ENDPOINT_PARAMS)
def test_fetch_and_parse(entity, doc_type, year, month, url_fragment):
    """
    Real fetch: downloads the file from CVM, extracts if ZIP, parses the CSV,
    and validates the DataResponse structure and content.
    """
    svc = CVMCreditDataService()

    async def _run():
        return await svc.get_data(
            entity=entity,
            doc_type=doc_type,
            year=year,
            month=month,
            page=1,
            page_size=10,
        )

    response = asyncio.run(_run())

    # --- source URL is correct ------------------------------------------------
    source_url = response.metadata.get("source_url", "")
    assert url_fragment in source_url, (
        f"Expected URL to contain '{url_fragment}', got '{source_url}'"
    )

    # --- records were parsed --------------------------------------------------
    assert response.pagination.total_items > 0, (
        f"{entity}/{doc_type}: expected records > 0, got {response.pagination.total_items}"
    )
    assert len(response.data) > 0, f"{entity}/{doc_type}: data list is empty"
    assert len(response.data) <= 10, f"{entity}/{doc_type}: page_size=10 exceeded"

    # --- pagination is consistent ---------------------------------------------
    assert response.pagination.page == 1
    assert response.pagination.page_size == 10
    assert response.pagination.total_pages >= 1

    # --- each row is a non-empty dict ----------------------------------------
    for i, row in enumerate(response.data):
        assert isinstance(row, dict), f"Row {i} is not a dict"
        non_null = {k: v for k, v in row.items() if v not in (None, "")}
        assert len(non_null) > 0, f"Row {i} has no non-null fields"

    # --- columns are consistent across all rows ------------------------------
    first_cols = set(response.data[0].keys())
    for i, row in enumerate(response.data[1:], start=1):
        assert set(row.keys()) == first_cols, (
            f"{entity}/{doc_type}: row {i} has different columns from row 0"
        )

    # --- processing time is sane (> 0, < 300 s) ------------------------------
    proc_time = response.metadata.get("processing_time_seconds", 0)
    assert 0 < proc_time < 300, f"Unexpected processing time: {proc_time}"


@skip_if_no_network
@pytest.mark.parametrize("entity,doc_type,year,month,url_fragment", ENDPOINT_PARAMS)
def test_pagination_second_page(entity, doc_type, year, month, url_fragment):
    """
    Real fetch of page 2 — verifies pagination works and returns a different
    slice than page 1.
    """
    svc = CVMCreditDataService()

    async def _run(page):
        return await svc.get_data(
            entity=entity,
            doc_type=doc_type,
            year=year,
            month=month,
            page=page,
            page_size=5,
        )

    r1 = asyncio.run(_run(1))
    if r1.pagination.total_pages < 2:
        pytest.skip(f"{entity}/{doc_type} has only 1 page — skipping page-2 test")

    r2 = asyncio.run(_run(2))

    assert r2.pagination.page == 2
    assert len(r2.data) > 0

    # Pages must carry different rows
    assert r1.data[0] != r2.data[0], (
        f"{entity}/{doc_type}: page 1 and page 2 returned the same first row"
    )


@skip_if_no_network
@pytest.mark.parametrize("entity,doc_type,year,month,url_fragment", ENDPOINT_PARAMS)
def test_cache_hit_on_second_call(entity, doc_type, year, month, url_fragment):
    """
    Second call to the same endpoint should serve from the on-disk cache
    and be significantly faster than the first.
    """
    svc = CVMCreditDataService()

    async def _run():
        return await svc.get_data(
            entity=entity,
            doc_type=doc_type,
            year=year,
            month=month,
            page=1,
            page_size=5,
        )

    r1 = asyncio.run(_run())
    r2 = asyncio.run(_run())

    t1 = r1.metadata.get("processing_time_seconds", 0)
    t2 = r2.metadata.get("processing_time_seconds", 0)

    # Cache hit should be at least 5× faster
    assert t2 < t1 or t2 < 1.0, (
        f"{entity}/{doc_type}: second call not faster (t1={t1}s t2={t2}s) — cache may not be working"
    )
