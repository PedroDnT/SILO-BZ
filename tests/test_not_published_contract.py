"""The fetcher's real "not published" messages must classify as 'skipped'.

CVM skip versus error is decided by substring: `_classify_finish` looks for
`_NOT_PUBLISHED_MARKERS` in the rendered error, and `cvm_fetcher.py` composes
those messages with f-strings. Each side is tested alone elsewhere
(`test_timeout_retry.py`, `test_missing_block_is_skipped.py`), each against a
hand-written string. This file joins them: it raises the fetcher's actual
exception, renders it the way `_log_finish` receives it (`describe`), and
classifies it. Reword either side and this fails (OPEN_ITEMS.md item 17.8).
"""

from __future__ import annotations

import io
import zipfile

import pytest
from aiohttp import web

from src.fetchers.cvm_fetcher import CVMFetcher
from src.pipeline.cvm_pipeline import _classify_finish
from src.pipeline.ingest_log import describe


@pytest.fixture
def fetcher(tmp_path, monkeypatch):
    monkeypatch.setenv("CVM_CACHE_DIR", str(tmp_path / "cache"))
    f = CVMFetcher()
    f.timeout = 2
    f.max_retries = 1
    f.retry_delay = 0
    f.dns_nameservers = []
    CVMFetcher._connect_failures = 0
    return f


async def _status_of_http(fetcher, tmp_path, status: int) -> str:
    async def respond(request):
        return web.Response(status=status)

    app = web.Application()
    app.router.add_get("/f.zip", respond)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    try:
        with pytest.raises(Exception) as exc:
            await fetcher._download_uncached(
                f"http://127.0.0.1:{port}/f.zip", str(tmp_path / "c.bin"), str(tmp_path / "c.json")
            )
    finally:
        await runner.cleanup()
    return _classify_finish(describe(exc.value), None, 0)[0]


def _zip_with(members) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name in members:
            zf.writestr(name, f"A;B\n{name};1\n".encode("latin-1"))
    return buf.getvalue()


def _status_of_extract(members, pattern: str, year: int, month) -> str:
    with pytest.raises(ValueError) as exc:
        CVMFetcher()._extract_csv_from_zip(_zip_with(members), pattern, year, month)
    return _classify_finish(describe(exc.value), None, 0)[0]


@pytest.mark.asyncio
async def test_a_real_404_is_skipped(fetcher, tmp_path):
    assert await _status_of_http(fetcher, tmp_path, 404) == "skipped"


@pytest.mark.asyncio
async def test_a_real_500_is_an_error(fetcher, tmp_path):
    assert await _status_of_http(fetcher, tmp_path, 500) == "error"


def test_a_real_unreleased_cda_block_is_skipped():
    partial = ["cda_fi_BLC_1_202608.csv", "cda_fi_BLC_2_202608.csv", "cda_fi_BLC_4_202608.csv"]
    assert _status_of_extract(partial, "cda_fi_BLC_6_{year}{month:02d}.csv", 2026, 8) == "skipped"


def test_a_real_renamed_member_is_an_error():
    renamed = ["cda_fi_BLOCO_6_202608.csv", "cda_fi_PL_202608.csv"]
    assert _status_of_extract(renamed, "cda_fi_BLC_6_{year}{month:02d}.csv", 2026, 8) == "error"
