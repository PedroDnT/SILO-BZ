"""The HTTP policy every fetcher shares: one retry loop, one env reader, one session holder.

Each fetcher decides what counts as transient (a status set, a 200 that is an
HTML challenge page) and what its own error type and message are; this module
owns the loop around that decision, so the wait schedule exists once.

An attempt is a function of its 1-based number. It returns the result, or
raises ``Retry(cause)`` to ask for another try, or raises anything else to stop
at once (a 404, a contract break). When the budget is spent, ``exhausted(last,
attempts)`` builds the error to raise, so each fetcher keeps its own type and
message. A failed fetch always raises; nothing here returns a fallback value
(AGENTS.md rule 1).

    async def attempt(n):
        try:
            resp = await client.get(url)
        except httpx.HTTPError as exc:
            raise Retry(exc) from exc
        if resp.status_code in RETRY_STATUSES:
            raise Retry(MyError(f"HTTP {resp.status_code}"))
        return resp

    return await retry_async(
        attempt, attempts=3, backoff=linear(2.0),
        exhausted=lambda last, n: MyError(f"failed after {n} attempts: {last}"),
    )
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Awaitable, Callable, Dict, Generic, Hashable, Optional, Tuple, TypeVar

T = TypeVar("T")
S = TypeVar("S")

Backoff = Callable[[int], float]
Exhausted = Callable[[Optional[BaseException], int], BaseException]


class Retry(Exception):
    """An attempt raises this to ask for another one; ``cause`` is what went wrong."""

    def __init__(self, cause: BaseException) -> None:
        super().__init__(str(cause))
        self.cause = cause


def linear(delay: float) -> Backoff:
    """Wait ``delay * attempt`` seconds after attempt number ``attempt``."""

    def wait(attempt: int) -> float:
        return delay * attempt

    return wait


def exponential(base: float) -> Backoff:
    """Wait ``base * 2 ** attempt`` seconds after attempt number ``attempt`` (2x, 4x, 8x ...)."""

    def wait(attempt: int) -> float:
        return base * (2 ** attempt)

    return wait


def env_retry_config(prefix: str, *, attempts: str = "4", delay: str = "2") -> Tuple[int, float]:
    """``(attempts, delay seconds)`` from ``<prefix>_MAX_RETRIES`` / ``<prefix>_RETRY_DELAY``.

    Read on every call so tests can pin the budget without reimporting a module.
    The budget is at least one attempt. The defaults are strings because the
    environment gives strings; ``int("4")`` and ``float("2")`` are the same
    numbers the callers always used.
    """
    return (
        max(1, int(os.getenv(f"{prefix}_MAX_RETRIES", attempts))),
        float(os.getenv(f"{prefix}_RETRY_DELAY", delay)),
    )


async def retry_async(
    attempt_fn: Callable[[int], Awaitable[T]],
    *,
    attempts: int,
    backoff: Backoff,
    exhausted: Exhausted,
) -> T:
    """Run ``attempt_fn(1..attempts)`` until one returns; wait between tries, never after the last.

    ``attempts`` is used as given: a caller that wants "at least one" clamps it
    itself. With nothing left to try, raises ``exhausted(last_cause, attempts)``
    chained to the last cause.
    """
    last: Optional[BaseException] = None
    for attempt in range(1, attempts + 1):
        try:
            return await attempt_fn(attempt)
        except Retry as retry:
            last = retry.cause
        if attempt < attempts:
            await asyncio.sleep(backoff(attempt))
    raise exhausted(last, attempts) from last


def retry_sync(
    attempt_fn: Callable[[int], T],
    *,
    attempts: int,
    backoff: Backoff,
    exhausted: Exhausted,
) -> T:
    """``retry_async`` for blocking fetchers (``requests``); sleeps with ``time.sleep``."""
    last: Optional[BaseException] = None
    for attempt in range(1, attempts + 1):
        try:
            return attempt_fn(attempt)
        except Retry as retry:
            last = retry.cause
        if attempt < attempts:
            time.sleep(backoff(attempt))
    raise exhausted(last, attempts) from last


class SessionHolder(Generic[S]):
    """Sessions that the attempts of one download share, opened on first use and closed together.

    ``build(key)`` makes the session for ``key``; ``key`` is whatever must make
    two attempts use different sessions (CVM's rotated DNS order) and is the
    same for attempts that may share one. Use as ``async with SessionHolder(...)``.
    A session is never opened per attempt: a retry reuses the connection pool
    and the TLS session of the attempt before it.
    """

    def __init__(self, build: Callable[[Hashable], Awaitable[S]]) -> None:
        self._build = build
        self._sessions: Dict[Hashable, S] = {}

    async def get(self, key: Hashable = 0) -> S:
        if key not in self._sessions:
            self._sessions[key] = await self._build(key)
        return self._sessions[key]

    async def aclose(self) -> None:
        sessions, self._sessions = list(self._sessions.values()), {}
        for session in sessions:
            await session.close()  # type: ignore[attr-defined]

    async def __aenter__(self) -> "SessionHolder[S]":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()
