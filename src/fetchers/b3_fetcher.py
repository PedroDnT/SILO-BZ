"""B3 COTAHIST fetcher — public historical quotation zips.

URLs (verified 2026-08-14, no auth):

    https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{year}.ZIP
    https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_D{dd}{mm}{yyyy}.ZIP

Daily files 404 on weekends/holidays and on sessions B3 has not published yet.
That is `B3CotahistNotFound`, not a generic failure — the ingestor logs those
slices `skipped`. Any other HTTP/network error raises.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Optional

import httpx

from .http import Retry, linear, retry_async

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist"
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class B3CotahistNotFound(FileNotFoundError):
    """The requested COTAHIST zip is not published (HTTP 404)."""


class B3CotahistFetchError(RuntimeError):
    """Download failed after retries, or the response was unusable."""


def daily_filename(session: date) -> str:
    return f"COTAHIST_D{session.strftime('%d%m%Y')}.ZIP"


def yearly_filename(year: int) -> str:
    return f"COTAHIST_A{year}.ZIP"


class B3CotahistFetcher:
    """HTTP-only. Parsing lives in src.parsers.cotahist."""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        retry_delay: Optional[float] = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("B3_COTAHIST_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = float(timeout if timeout is not None else os.getenv("B3_REQUEST_TIMEOUT", "300"))
        self.max_retries = int(max_retries if max_retries is not None else os.getenv("B3_MAX_RETRIES", "3"))
        self.retry_delay = float(retry_delay if retry_delay is not None else os.getenv("B3_RETRY_DELAY", "2"))

    def _url(self, filename: str) -> str:
        return f"{self.base_url}/{filename}"

    async def fetch_daily(self, session: date) -> bytes:
        return await self._download(self._url(daily_filename(session)), label=daily_filename(session))

    async def fetch_year(self, year: int) -> bytes:
        if year < 1986:
            raise ValueError(f"COTAHIST yearly files start at 1986, got {year}")
        return await self._download(self._url(yearly_filename(year)), label=yearly_filename(year))

    async def _download(self, url: str, *, label: str) -> bytes:
        attempts = max(1, self.max_retries)
        timeout = httpx.Timeout(self.timeout)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:

            async def attempt(n: int) -> bytes:
                try:
                    resp = await client.get(url)
                except httpx.HTTPError as exc:
                    logger.warning(
                        "B3 COTAHIST download error %s attempt=%d/%d: %s",
                        label, n, attempts, exc,
                    )
                    raise Retry(exc) from exc

                if resp.status_code == 404:
                    raise B3CotahistNotFound(f"Data not found at {url}")

                if resp.status_code in _RETRY_STATUSES:
                    logger.warning(
                        "B3 COTAHIST %s HTTP %s attempt=%d/%d",
                        label, resp.status_code, n, attempts,
                    )
                    raise Retry(B3CotahistFetchError(f"{url} returned HTTP {resp.status_code}"))

                if resp.status_code != 200:
                    raise B3CotahistFetchError(
                        f"{url} returned HTTP {resp.status_code}"
                    )

                content = resp.content
                if not content:
                    raise B3CotahistFetchError(f"{url} returned an empty body")
                logger.info("B3 COTAHIST fetched %s (%d bytes)", label, len(content))
                return content

            return await retry_async(
                attempt,
                attempts=attempts,
                backoff=linear(self.retry_delay),
                exhausted=lambda last, n: B3CotahistFetchError(
                    f"Failed to download {url} after {n} attempts: {last}"
                ),
            )
