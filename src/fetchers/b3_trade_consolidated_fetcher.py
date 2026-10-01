"""B3 TradeInformationConsolidatedFile fetcher — one CSV per session, no auth.

THE CONTRACT (verified live 2026-09-30)
---------------------------------------
Two plain GETs. The first names the file and returns a one-time token:

    GET {BASE}/api/download/requestname
        ?fileName=TradeInformationConsolidatedFile&date=YYYY-MM-DD&recaptchaToken=
    -> {"redirectUrl": "~/download?token=<token>"}

    GET {BASE}/api/download/?token=<token>
    -> text/csv: "Status do Arquivo: Final", then a ';' header row
       (RptDt;TckrSymb;ISIN;SgmtNm;...), ISO dates, pt-BR decimals.

Three quirks, all load-bearing:

1. `recaptchaToken` is accepted EMPTY. If B3 starts enforcing it the source
   is gone; this fetcher raises and never tries to solve a captcha.
2. A session outside retention, a weekend or a holiday is HTTP 200 with an
   EMPTY body. That is `B3TradeConsolidatedEmpty` (the ingestor logs it
   `skipped`), not a failure. On 2026-09-30 the oldest session served was
   2025-06-10.
3. The download route is `/api/download/?token=`. The `redirectUrl`'s own
   `~/download?token=` path serves the site's HTML shell with HTTP 200, so a
   body that is HTML is an error, never a file.

Why this source exists, and what it is checked against: migration 57.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://arquivos.b3.com.br"
FILE_NAME = "TradeInformationConsolidatedFile"
# 403 is Cloudflare rate-limiting on this host (src/fetchers/b3_bdi_fetcher.py),
# transient, never "no data".
_RETRY_STATUSES = frozenset({403, 429, 500, 502, 503, 504})
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    ),
}


class B3TradeConsolidatedEmpty(LookupError):
    """B3 served an empty file: no session that day, or outside retention."""


class B3TradeConsolidatedFetchError(RuntimeError):
    """Download failed after retries, or the response was unusable."""


class B3TradeConsolidatedFetcher:
    """HTTP only. Parsing lives in src.pipeline.ingest_b3_trade_consolidated."""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        retry_delay: Optional[float] = None,
    ) -> None:
        self.base_url = (
            base_url or os.getenv("B3_ARQUIVOS_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.timeout = float(timeout if timeout is not None else os.getenv("B3_REQUEST_TIMEOUT", "300"))
        self.max_retries = int(max_retries if max_retries is not None else os.getenv("B3_MAX_RETRIES", "3"))
        self.retry_delay = float(retry_delay if retry_delay is not None else os.getenv("B3_RETRY_DELAY", "2"))

    async def fetch(self, session: date) -> bytes:
        """The session's file as bytes. Raises B3TradeConsolidatedEmpty on an empty body."""
        label = f"{FILE_NAME} {session.isoformat()}"
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout), headers=_HEADERS, follow_redirects=True
        ) as client:
            resp = await self._get(
                client,
                f"{self.base_url}/api/download/requestname",
                params={"fileName": FILE_NAME, "date": session.isoformat(), "recaptchaToken": ""},
                label=label,
            )
            try:
                redirect = resp.json()["redirectUrl"]
                token = redirect.split("token=", 1)[1]
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise B3TradeConsolidatedFetchError(
                    f"{label}: no download token in {resp.text[:200]!r}"
                ) from exc
            if not token:
                raise B3TradeConsolidatedFetchError(f"{label}: empty download token")

            resp = await self._get(
                client, f"{self.base_url}/api/download/", params={"token": token}, label=label
            )

        content = resp.content
        if not content.strip():
            raise B3TradeConsolidatedEmpty(f"{label}: B3 served an empty file")
        if content.lstrip()[:15].lower().startswith((b"<!doctype", b"<html")):
            raise B3TradeConsolidatedFetchError(f"{label}: B3 served an HTML page, not the file")
        logger.info("B3 fetched %s (%d bytes)", label, len(content))
        return content

    async def _get(
        self, client: httpx.AsyncClient, url: str, *, params: dict, label: str
    ) -> httpx.Response:
        attempts = max(1, self.max_retries)
        last_exc: Optional[BaseException] = None
        for attempt in range(1, attempts + 1):
            try:
                resp = await client.get(url, params=params)
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.warning("B3 %s network error attempt=%d/%d: %s", label, attempt, attempts, exc)
            else:
                if resp.status_code == 200:
                    return resp
                if resp.status_code not in _RETRY_STATUSES:
                    raise B3TradeConsolidatedFetchError(f"{url} returned HTTP {resp.status_code}")
                last_exc = B3TradeConsolidatedFetchError(f"{url} returned HTTP {resp.status_code}")
                logger.warning("B3 %s HTTP %s attempt=%d/%d", label, resp.status_code, attempt, attempts)
            if attempt < attempts:
                await asyncio.sleep(self.retry_delay * attempt)
        raise B3TradeConsolidatedFetchError(
            f"{label}: failed after {attempts} attempts: {last_exc}"
        )
