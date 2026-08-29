"""Circuit breaker for CVM host-level blocking.

Motivation: on 2026-06-10 CVM refused every connection from the runner's IP. The
fetcher retried each of ~36 files three times with backoff — 4h22m that could
never succeed, ending in a green CI run with two empty year partitions. A
connect-level refusal is not transient, so retrying is futile; the run should
abort fast and loudly.

The breaker counts CONSECUTIVE connect failures across instances (a concurrent
backfill shares the host) and resets on any HTTP response — including a 404,
which proves the host answered and is routine on the daily trailing window.
"""

import asyncio
from unittest.mock import patch

import aiohttp
import pytest

from src.fetchers.cvm_fetcher import CVMFetcher, CVMHostUnreachable


def _connect_error():
    """Stand-in for the real failure's message.

    The breaker only formats the exception into its message, so it needs no
    aiohttp internals. Which exception type is *caught* is a property of
    _download's except clause (asserted separately below), not of the breaker.
    """
    return OSError(
        "Cannot connect to host dados.cvm.gov.br:443 ssl:default "
        "[Connect call failed ('45.7.170.66', 443)]"
    )


@pytest.fixture(autouse=True)
def _reset_breaker():
    CVMFetcher.reset_circuit()
    yield
    CVMFetcher.reset_circuit()


class TestBreaker:
    def test_trips_at_the_limit(self):
        limit = CVMFetcher._CONNECT_FAILURE_LIMIT
        # One below the limit: still counting, no abort.
        for _ in range(limit - 1):
            CVMFetcher._note_connect_failure("http://x", _connect_error())
        assert CVMFetcher._connect_failures == limit - 1

        with pytest.raises(CVMHostUnreachable) as exc:
            CVMFetcher._note_connect_failure("http://x", _connect_error())
        msg = str(exc.value)
        assert "consecutive connection failures" in msg
        assert "blocked" in msg
        assert "Re-dispatch" in msg  # tells the operator what to do

    def test_success_resets_the_count(self):
        for _ in range(CVMFetcher._CONNECT_FAILURE_LIMIT - 1):
            CVMFetcher._note_connect_failure("http://x", _connect_error())
        CVMFetcher._note_success()
        assert CVMFetcher._connect_failures == 0

    def test_interleaved_success_never_trips(self):
        # A flaky-but-reachable host must not abort the run.
        for _ in range(CVMFetcher._CONNECT_FAILURE_LIMIT * 3):
            CVMFetcher._note_connect_failure("http://x", _connect_error())
            CVMFetcher._note_success()
        assert CVMFetcher._connect_failures == 0

    def test_breaker_is_shared_across_instances(self):
        # A concurrent backfill creates several fetchers against one host.
        limit = CVMFetcher._CONNECT_FAILURE_LIMIT
        a, b = CVMFetcher.__new__(CVMFetcher), CVMFetcher.__new__(CVMFetcher)
        for i in range(limit - 1):
            (a if i % 2 else b)._note_connect_failure("http://x", _connect_error())
        with pytest.raises(CVMHostUnreachable):
            a._note_connect_failure("http://x", _connect_error())

    def test_unreachable_is_a_runtime_error(self):
        # Callers already catch Exception per slice; keep it in that hierarchy.
        assert issubclass(CVMHostUnreachable, RuntimeError)


class TestWiring:
    """The breaker is useless if _download doesn't route the real exception to it."""

    def test_download_handles_connector_error_before_generic_client_error(self):
        import inspect
        # _download is the cache/single-flight front door; the retry loop that
        # owns the exception handlers lives in _download_uncached.
        src = inspect.getsource(CVMFetcher._download_uncached)
        i_specific = src.index("except aiohttp.ClientConnectorError")
        i_generic = src.index("except (aiohttp.ClientError")
        assert i_specific < i_generic, (
            "ClientConnectorError must be caught BEFORE the generic ClientError, "
            "or it is swallowed by the generic branch and never counted"
        )
        assert "_note_connect_failure" in src
        assert "_note_success" in src

    def test_generic_branch_also_catches_asyncio_timeout(self):
        # aiohttp enforces ClientTimeout(total=) itself and raises a bare
        # asyncio.TimeoutError, which is NOT an aiohttp.ClientError — so it has
        # to be named explicitly or it escapes the retry loop on attempt 0.
        # That is exactly what happened to 32 fi/balancete months on
        # 2026-08-27. See test_timeout_retry.py for the behavioural proof.
        import inspect
        src = inspect.getsource(CVMFetcher._download_uncached)
        assert "asyncio.TimeoutError" in src, (
            "the retry loop must name asyncio.TimeoutError explicitly"
        )
        assert not issubclass(asyncio.TimeoutError, aiohttp.ClientError)

    def test_connector_error_is_a_client_error(self):
        # Documents why ordering matters: the specific type is a subclass, so a
        # generic-first ordering would shadow it.
        assert issubclass(aiohttp.ClientConnectorError, aiohttp.ClientError)


class TestLatch:
    """Tripping the breaker must actually STOP the run, not just one slice.

    Before the latch, CVMHostUnreachable ended exactly one slice: it is a
    RuntimeError, and every ingest method catches bare `except Exception`,
    writes its audit row and moves on. Measured on the 06:00 run of 2026-08-29
    — limit 8, and cvm_ingest_log recorded 39, 43, 51, 55, 56, 57 across twenty
    slices, each paying its own max_retries of connect attempts with backoff
    first. About forty minutes re-proving one refusal.
    """

    def _trip(self):
        for _ in range(CVMFetcher._CONNECT_FAILURE_LIMIT):
            try:
                CVMFetcher._note_connect_failure("https://x/y.zip", _connect_error())
            except CVMHostUnreachable:
                pass

    def test_latches_after_tripping(self):
        assert CVMFetcher._host_unreachable is None
        self._trip()
        assert CVMFetcher._host_unreachable is not None

    async def test_a_later_download_fails_without_touching_the_network(self):
        """The point of the latch: no socket, no backoff sleep, for slice N+1.

        Written as a native async test rather than driving the loop by hand —
        asyncio.get_event_loop() picks up whatever loop an earlier test left
        behind, which made this pass alone and fail in the full suite.
        """
        self._trip()
        fetcher = CVMFetcher()

        slept: list = []

        async def _no_sleep(delay):
            slept.append(delay)

        with patch("src.fetchers.cvm_fetcher.asyncio.sleep", _no_sleep), \
             patch("aiohttp.ClientSession") as session:
            with pytest.raises(CVMHostUnreachable):
                await fetcher._download_uncached("https://x/z.zip", "/tmp/c", "/tmp/m")

        assert session.call_count == 0, "latched breaker must not open a connection"
        assert slept == [], "latched breaker must not pay a backoff sleep"

    def test_success_clears_the_latch(self):
        """A working host must not stay poisoned for the rest of the process."""
        self._trip()
        CVMFetcher._note_success()
        assert CVMFetcher._host_unreachable is None
        CVMFetcher._raise_if_host_unreachable()  # must not raise
