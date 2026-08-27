"""A CVM download that times out must be retried, not abandoned on attempt 0.

Regression test for the 2026-08-27 fi/balancete backfill, where 32 monthly
slices died with a message-less "TimeoutError" after a single try despite
CVM_MAX_RETRIES=3.

`aiohttp` enforces `ClientTimeout(total=)` with its own timer and raises a bare
`asyncio.TimeoutError` — which is `builtins.TimeoutError` on 3.11+ and is *not*
an `aiohttp.ClientError`. The retry loop only listed `ClientConnectorError` and
`ClientError`, so the total-timeout escaped both clauses.

These tests drive the real aiohttp client against a real local server that
stalls, rather than raising a mocked exception: the bug was entirely about which
exception the library actually raises, so a mock that raises the exception we
*think* it raises would have passed against the broken code.
"""

from __future__ import annotations

import asyncio

import aiohttp
import pytest
from aiohttp import web

from src.fetchers.cvm_fetcher import CVMFetcher


@pytest.fixture
def fetcher(tmp_path, monkeypatch):
    """A fetcher with a short timeout, no backoff, and its own cache dir."""
    monkeypatch.setenv("CVM_CACHE_DIR", str(tmp_path / "cache"))
    f = CVMFetcher()
    f.timeout = 0.25          # ClientTimeout(total=) — the timer under test
    f.max_retries = 3
    f.retry_delay = 0         # keep the test fast; backoff is not what we assert
    f.dns_nameservers = []    # no DNS rotation against 127.0.0.1
    CVMFetcher._connect_failures = 0
    return f


async def _serve(handler, path="/slow"):
    """Start a local aiohttp server and return (base_url, cleanup)."""
    app = web.Application()
    app.router.add_get(path, handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    return f"http://127.0.0.1:{port}", runner.cleanup


@pytest.mark.asyncio
async def test_total_timeout_is_retried_max_retries_times(fetcher, tmp_path):
    attempts = 0

    async def stall(request):
        nonlocal attempts
        attempts += 1
        await asyncio.sleep(5)          # far past the 0.25s total timeout
        return web.Response(body=b"never")

    base, cleanup = await _serve(stall)
    try:
        with pytest.raises(RuntimeError) as exc:
            await fetcher._download_uncached(
                f"{base}/slow", str(tmp_path / "c.bin"), str(tmp_path / "c.json")
            )
    finally:
        await cleanup()

    # The whole point: every attempt was spent, not just the first.
    assert attempts == fetcher.max_retries, (
        f"expected {fetcher.max_retries} download attempts, server saw {attempts}"
    )
    # And the failure says something. A bare TimeoutError stringifies to "",
    # which is how the audit table ended up with a diagnosis-free error column.
    message = str(exc.value)
    assert "TimeoutError" in message
    assert f"after {fetcher.max_retries} attempts" in message
    assert message.rstrip().endswith(("s", "TimeoutError")) and message.strip() != ""


@pytest.mark.asyncio
async def test_the_raised_exception_really_is_not_a_client_error(fetcher, tmp_path):
    """Pin the library behaviour the fix depends on.

    If a future aiohttp made total-timeout raise a ClientError subclass, the
    explicit clause would be redundant rather than wrong — but we would want to
    know, because this assertion is the reason the fix is written that way.
    """
    async def stall(request):
        await asyncio.sleep(5)
        return web.Response(body=b"never")

    base, cleanup = await _serve(stall)
    try:
        timeout = aiohttp.ClientTimeout(total=0.25)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            with pytest.raises(asyncio.TimeoutError) as exc:
                async with session.get(f"{base}/slow") as resp:
                    await resp.read()
    finally:
        await cleanup()

    assert not isinstance(exc.value, aiohttp.ClientError), (
        "aiohttp's total-timeout is not a ClientError — the retry loop must "
        "name asyncio.TimeoutError explicitly"
    )


@pytest.mark.asyncio
async def test_404_is_not_retried(fetcher, tmp_path):
    """A month CVM has not published is a 'skipped' non-event, not a failure.

    It must escape as ValueError on the first attempt — retrying a 404 three
    times per slice is what made the daily trailing window slow for no reason.
    """
    attempts = 0

    async def missing(request):
        nonlocal attempts
        attempts += 1
        return web.Response(status=404)

    base, cleanup = await _serve(missing, path="/missing")
    try:
        with pytest.raises(ValueError, match="Data not found"):
            await fetcher._download_uncached(
                f"{base}/missing", str(tmp_path / "c.bin"), str(tmp_path / "c.json")
            )
    finally:
        await cleanup()

    assert attempts == 1, "a 404 must not be retried"


@pytest.mark.asyncio
async def test_a_slow_but_finishing_download_still_succeeds(fetcher, tmp_path):
    """Guard against 'fix' by shortening the timeout: slow-but-OK must pass."""
    async def slow_ok(request):
        await asyncio.sleep(0.05)       # well inside the 0.25s budget
        return web.Response(body=b"payload")

    base, cleanup = await _serve(slow_ok, path="/ok")
    try:
        content = await fetcher._download_uncached(
            f"{base}/ok", str(tmp_path / "c.bin"), str(tmp_path / "c.json")
        )
    finally:
        await cleanup()

    assert content == b"payload"
