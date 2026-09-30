"""U.S. Treasury par curve, Cboe VIX, EIA Brent and the OFR FSI — HTTP only.

Primary publishers only; FRED and Yahoo are copies (docs/reference/research/
dustin_br_data_sources.md §3). Verified 2026-09-26/27, no auth except EIA:

    Treasury  https://home.treasury.gov/resource-center/data-chart-center/
              interest-rates/daily-treasury-rates.csv/{year}/all
              ?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv
    Cboe      https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv
    EIA       https://api.eia.gov/v2/petroleum/pri/spt/data/  (series RBRTE)
    OFR       https://www.financialresearch.gov/financial-stress-index/data/fsi.csv
              …/financial-stress-index/files/FSI_Revision_History_2023-06-27.xlsx

The OFR workbook's name carries the date of OFR's latest revision; a new
revision is a new file, linked from the FSI page, and this URL moves with it.

EIA wants an API key. ``EIA_API_KEY`` is read from the environment; without
it the public ``DEMO_KEY`` is used, which EIA rate-limits — logged every
time, so a throttled run is explainable. EIA pages at 5,000 rows.

Every failure raises ``MarketFetchError``; an empty answer is never turned
into "no data".
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

TREASURY_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{year}/all"
)
CBOE_VIX_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
EIA_SPOT_URL = "https://api.eia.gov/v2/petroleum/pri/spt/data/"
EIA_PAGE = 5000
OFR_FSI_URL = "https://www.financialresearch.gov/financial-stress-index/data/fsi.csv"
OFR_FSI_REVISIONS_URL = ("https://www.financialresearch.gov/financial-stress-index/files/"
                         "FSI_Revision_History_2023-06-27.xlsx")
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class MarketFetchError(RuntimeError):
    """A market-data request failed after retries or returned an unusable body."""


class GlobalMarketFetcher:
    def __init__(self, *, timeout: float = 120.0, max_retries: Optional[int] = None,
                 retry_delay: Optional[float] = None) -> None:
        self.timeout = timeout
        self.max_retries = int(max_retries if max_retries is not None else os.getenv("MKT_MAX_RETRIES", "4"))
        self.retry_delay = float(retry_delay if retry_delay is not None else os.getenv("MKT_RETRY_DELAY", "3"))

    async def _get(self, url: str, params: Optional[Any] = None, *, label: str, binary: bool = False) -> Any:
        last_exc: Optional[BaseException] = None
        attempts = max(1, self.max_retries)
        async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout), follow_redirects=True,
                                     headers={"User-Agent": "SILO-BZ ingest (github.com/PedroDnT/SILO-BZ)"}) as client:
            for attempt in range(1, attempts + 1):
                try:
                    resp = await client.get(url, params=params)
                except httpx.HTTPError as exc:
                    last_exc = exc
                    logger.warning("%s transport error attempt=%d/%d: %s", label, attempt, attempts, exc)
                    if attempt < attempts:
                        await asyncio.sleep(self.retry_delay * attempt)
                    continue
                if resp.status_code in _RETRY_STATUSES:
                    last_exc = MarketFetchError(f"{label}: HTTP {resp.status_code}")
                    logger.warning("%s HTTP %s attempt=%d/%d", label, resp.status_code, attempt, attempts)
                    if attempt < attempts:
                        await asyncio.sleep(self.retry_delay * attempt)
                    continue
                if resp.status_code != 200:
                    raise MarketFetchError(f"{label}: HTTP {resp.status_code}: {resp.text[:200]}")
                if not resp.content.strip():
                    raise MarketFetchError(f"{label}: empty body")
                return resp.content if binary else resp.text
        raise MarketFetchError(f"{label}: failed after {attempts} attempts: {last_exc}")

    async def fetch_treasury_year(self, year: int) -> str:
        params = {"type": "daily_treasury_yield_curve", "field_tdr_date_value": str(year),
                  "page": "", "_format": "csv"}
        return await self._get(TREASURY_URL.format(year=year), params, label=f"Treasury par {year}")

    async def fetch_cboe_vix(self) -> str:
        return await self._get(CBOE_VIX_URL, label="Cboe VIX_History.csv")

    async def fetch_ofr_fsi(self) -> str:
        return await self._get(OFR_FSI_URL, label="OFR fsi.csv")

    async def fetch_ofr_fsi_revisions(self) -> bytes:
        return await self._get(OFR_FSI_REVISIONS_URL, label="OFR FSI revision history", binary=True)

    async def fetch_eia_brent(self, start: date, end: date) -> List[Dict[str, Any]]:
        key = os.getenv("EIA_API_KEY", "").strip()
        if not key:
            logger.warning("EIA_API_KEY unset — using EIA's rate-limited DEMO_KEY")
            key = "DEMO_KEY"
        out: List[Dict[str, Any]] = []
        offset = 0
        while True:
            params = [
                ("frequency", "daily"), ("data[0]", "value"), ("facets[series][]", "RBRTE"),
                ("start", start.isoformat()), ("end", end.isoformat()),
                ("sort[0][column]", "period"), ("sort[0][direction]", "asc"),
                ("offset", str(offset)), ("length", str(EIA_PAGE)), ("api_key", key),
            ]
            # The key rides in the query string; never let it reach a log line.
            text = await self._get(EIA_SPOT_URL, params, label=f"EIA RBRTE {start}..{end} offset {offset}")
            try:
                body = json.loads(text)
                page = body["response"]["data"]
                total = int(body["response"]["total"])
            except (ValueError, KeyError, TypeError) as exc:
                raise MarketFetchError(f"EIA RBRTE: unexpected body {text[:200]!r}") from exc
            out.extend(page)
            offset += len(page)
            if not page or offset >= total:
                break
        return out
