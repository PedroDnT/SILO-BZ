"""Olinda pagination cap raises instead of truncating (issue #1107).

After ``_OLINDA_MAX_PAGES`` full pages, ``_olinda_get`` used to log a warning
and return the rows it had, so a wide Focus or PTAX backfill could land a
truncated dataset under an ok audit row. It must raise instead.
"""

from typing import Any, Dict, List

import pytest

from src.fetchers import bacen_fetcher


def _endpoint(page_sizes: List[int], calls: List[str]):
    """A mocked Olinda that serves one page per call, sized from page_sizes."""

    async def fake_request(client, url, full, *, attempts, delay) -> Dict[str, Any]:
        calls.append(full)
        n = page_sizes[min(len(calls) - 1, len(page_sizes) - 1)]
        return {"value": [{"i": i} for i in range(n)]}

    return fake_request


@pytest.fixture
def small_pages(monkeypatch):
    monkeypatch.setattr(bacen_fetcher, "_OLINDA_PAGE", 3)
    monkeypatch.setattr(bacen_fetcher, "_OLINDA_MAX_PAGES", 4)


async def test_an_endpoint_that_never_returns_a_short_page_raises(small_pages, monkeypatch):
    calls: List[str] = []
    monkeypatch.setattr(bacen_fetcher, "_olinda_request", _endpoint([3], calls))

    with pytest.raises(bacen_fetcher.BacenFetchError) as info:
        await bacen_fetcher._olinda_get("Expectativas", "ExpectativasMercadoAnuais", {})

    assert isinstance(info.value, RuntimeError)
    msg = str(info.value)
    assert "Expectativas/ExpectativasMercadoAnuais" in msg
    assert "4-page cap" in msg
    assert "12 rows" in msg
    assert len(calls) == 4


async def test_a_short_last_page_returns_every_row(small_pages, monkeypatch):
    calls: List[str] = []
    monkeypatch.setattr(bacen_fetcher, "_olinda_request", _endpoint([3, 3, 3, 1], calls))

    rows = await bacen_fetcher._olinda_get("PTAX", "CotacaoMoedaPeriodo", {})

    assert len(rows) == 10
    assert len(calls) == 4
    assert "%24skip=9" in calls[-1]


async def test_an_unpaginated_request_returns_its_one_page(small_pages, monkeypatch):
    calls: List[str] = []
    monkeypatch.setattr(bacen_fetcher, "_olinda_request", _endpoint([3], calls))

    rows = await bacen_fetcher._olinda_get("PTAX", "Moedas", {}, paginate=False)

    assert len(rows) == 3
    assert len(calls) == 1
