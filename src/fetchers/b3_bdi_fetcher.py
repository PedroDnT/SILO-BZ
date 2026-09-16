"""B3 BDI (Boletim Diário de Informações) table exports — public, no auth.

WHY THIS EXISTS
---------------
`b3_cotahist` is the trade tape; it says nothing about who is short. The
securities-lending book (BTC/BTB) and the investor-type participation split
are published separately, through the export API behind
https://arquivos.b3.com.br/bdi — the page B3 moved every public listed/OTC
dataset onto in December 2025 (Comunicado Externo 01/2026-VTEC retired the
old `/tabelas` portal).

THE CONTRACT (verified live 2026-09-16)
---------------------------------------
Catalog (plain GET, no auth, no headers needed):

    GET {BASE}/bdi/download/chapters?lang=pt-br      -> 13 chapters
    GET {BASE}/bdi/table/classifications?lang=pt-br  -> ~70 tables + metadata

Export — the ONLY route that returns rows:

    POST {BASE}/bdi/table/export/csv?lang=pt-br
    {"Name": <table>, "Date": "YYYY-MM-DD", "FinalDate": "YYYY-MM-DD",
     "ClientId": "", "Filters": {}}
    -> text/csv, ';' delimited, UTF-8 BOM, pt-BR decimals, dd/mm/yyyy dates

Five quirks, all load-bearing:

1. `Filters` must be an OBJECT. A list returns HTTP 400 with
   "could not be converted to System.Collections.Generic.IDictionary".
2. The endpoint is behind Cloudflare, which 403s a request without
   browser-ish headers (Origin/Referer/User-Agent) and rate-limits bursts
   with the same 403 + a ~5.5 KB HTML challenge page. A 403 here is
   TRANSIENT — it is never "no data". Serialize and back off.
3. `Date` != `FinalDate` returns the whole range in one response, which is
   how the first run claims the retention window in a single call.
4. **The window is silently clamped.** Requesting BTBLendingOpenPosition for
   2024-01-02..2026-09-10 returns HTTP 200 and 5.2 MB containing exactly 18
   sessions (17/08/2026..10/09/2026). A 200 is NOT evidence the requested
   span was delivered, so callers must reconcile the dates they got against
   the dates they asked for (`src.parsers.b3_bdi.reconcile_span`).
5. A slice outside retention, or a non-session day, returns HTTP 200 whose
   body is the header block plus the literal `Nenhum resultado`. That is
   `B3BdiEmpty` (the ingestor logs it `skipped`), not a failure.

RETENTION — READ THIS BEFORE PLANNING A BACKFILL
------------------------------------------------
Retention is per table, published in the catalog's `limitDate`, and verified:

    BTBLendingOpenPosition   D-21    ~21 business days. 2026-08-17 has data,
    BTBLoanBalance           D-21    2026-08-14 returns "Nenhum resultado".
    BTBTrade                 D-21
    SharesInvesVolum         D-21
    InstrumentsEquities      D-21
    AverageChart             (none)  trailing 12 months as of ANY past date
    ConsolidatedRecords      M-18
    HistoricalExchange       5 years

There is no archive and no deep-history route: the legacy
`/api/download/requestname` API still serves >1 year but knows none of the
lending tables, and the `pesquisapregao` bulletin archive returns empty zips.
So the lending tables are a **ratchet** — every day the cron does not run is
a day lost permanently. That is why `run_backfill` deliberately offers no
lending option: it would imply a history that cannot exist.

The legacy `requestname` API is NOT a fallback for these tables. It returns
HTTP 400 for every BDI table name.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from datetime import date
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://arquivos.b3.com.br"
DEFAULT_INDEX_URL = "https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall"

# Cloudflare rejects a bare client. Same stance as b3_corporate_events_fetcher.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Content-Type": "application/json",
    "Origin": DEFAULT_BASE_URL,
    "Referer": f"{DEFAULT_BASE_URL}/bdi/tabelas/",
}

# 403 is in here on purpose: for this host it is Cloudflare rate-limiting a
# burst, not an authorization verdict. Retrying it is correct; treating it as
# "no data" would silently drop a session we can never fetch again.
_RETRY_STATUSES = frozenset({403, 429, 500, 502, 503, 504})

_EMPTY_MARKER = "Nenhum resultado"


class B3BdiEmpty(LookupError):
    """B3 returned 200 with `Nenhum resultado` — outside retention, or no session."""


class B3BdiFetchError(RuntimeError):
    """Download failed after retries, or the response was unusable."""


def _looks_like_html(text: str) -> bool:
    head = text.lstrip()[:200].lower()
    return head.startswith("<!doctype") or head.startswith("<html")


class B3BdiFetcher:
    """HTTP only. Parsing lives in src.parsers.b3_bdi."""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        index_url: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        retry_delay: Optional[float] = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("B3_BDI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.index_url = (index_url or os.getenv("B3_INDEX_BASE_URL") or DEFAULT_INDEX_URL).rstrip("/")
        self.timeout = float(timeout if timeout is not None else os.getenv("B3_REQUEST_TIMEOUT", "300"))
        self.max_retries = int(max_retries if max_retries is not None else os.getenv("B3_MAX_RETRIES", "4"))
        self.retry_delay = float(retry_delay if retry_delay is not None else os.getenv("B3_RETRY_DELAY", "5"))

    # ── BDI CSV export ────────────────────────────────────────────────────

    async def fetch_table(self, name: str, start: date, end: Optional[date] = None) -> str:
        """Export one BDI table for [start, end] as decoded CSV text.

        Returns text rather than bytes because the empty-slice verdict is a
        property of the decoded body, and the caller must not have to decode
        twice to learn whether it got data.
        """
        end = end or start
        if end < start:
            raise ValueError(f"end {end} < start {start}")
        url = f"{self.base_url}/bdi/table/export/csv?lang=pt-br"
        payload = {
            "Name": name,
            "Date": start.isoformat(),
            "FinalDate": end.isoformat(),
            "ClientId": "",
            "Filters": {},
        }
        label = f"{name} {start.isoformat()}..{end.isoformat()}"
        text = await self._post(url, payload, label=label)

        if _EMPTY_MARKER in text:
            raise B3BdiEmpty(f"{label}: B3 returned '{_EMPTY_MARKER}'")
        return text

    async def _post(self, url: str, payload: Dict[str, Any], *, label: str) -> str:
        last_exc: Optional[BaseException] = None
        attempts = max(1, self.max_retries)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout), follow_redirects=True, headers=_HEADERS
        ) as client:
            for attempt in range(1, attempts + 1):
                try:
                    resp = await client.post(url, content=json.dumps(payload))
                except httpx.HTTPError as exc:
                    last_exc = exc
                    logger.warning("B3 BDI %s transport error attempt=%d/%d: %s",
                                   label, attempt, attempts, exc)
                    await self._backoff(attempt, attempts)
                    continue

                if resp.status_code in _RETRY_STATUSES:
                    last_exc = B3BdiFetchError(f"{label} returned HTTP {resp.status_code}")
                    logger.warning("B3 BDI %s HTTP %s attempt=%d/%d (Cloudflare throttle?)",
                                   label, resp.status_code, attempt, attempts)
                    await self._backoff(attempt, attempts)
                    continue

                if resp.status_code != 200:
                    raise B3BdiFetchError(
                        f"{label} returned HTTP {resp.status_code}: {resp.text[:300]}"
                    )

                text = resp.text
                if not text.strip():
                    raise B3BdiFetchError(f"{label} returned an empty body")
                if _looks_like_html(text):
                    # A challenge page served with 200. Same remedy as a 403.
                    last_exc = B3BdiFetchError(f"{label} returned an HTML challenge page")
                    logger.warning("B3 BDI %s got an HTML body attempt=%d/%d", label, attempt, attempts)
                    await self._backoff(attempt, attempts)
                    continue

                logger.info("B3 BDI fetched %s (%d bytes)", label, len(text))
                return text

        raise B3BdiFetchError(f"Failed to export {label} after {attempts} attempts: {last_exc}")

    async def _backoff(self, attempt: int, attempts: int) -> None:
        if attempt < attempts:
            await asyncio.sleep(self.retry_delay * attempt)

    # ── index portfolio (free float + B3 sector) ──────────────────────────

    async def fetch_index_portfolio(self, index_code: str, *, page_size: int = 120) -> List[Dict[str, Any]]:
        """Every constituent of one B3 index, with free float and sector.

        `theoricalQty` is the index's free-float-adjusted share count — the
        only free, B3-published free float we have. `segment` carries B3's own
        sector label, and only when the request asks for segment "2"; segment
        "1" returns the same rows with `segment: null`.

        Parameters ride as a base64 JSON object in the PATH, the same dialect
        b3_corporate_events_fetcher documents.
        """
        rows: List[Dict[str, Any]] = []
        page = 1
        total_pages = 1
        header_date: Optional[str] = None
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout), follow_redirects=True,
            headers={**_HEADERS, "Accept": "application/json",
                     "Referer": "https://sistemaswebb3-listados.b3.com.br/indexPage/"},
        ) as client:
            while page <= total_pages:
                token = base64.b64encode(json.dumps({
                    "language": "pt-br",
                    "pageNumber": page,
                    "pageSize": page_size,
                    "index": index_code,
                    "segment": "2",
                }).encode()).decode()
                url = f"{self.index_url}/GetPortfolioDay/{token}"
                body = await self._get_json(url, label=f"{index_code} page {page}")
                if not body:
                    raise B3BdiFetchError(f"index {index_code} page {page} returned an empty body")

                total_pages = int((body.get("page") or {}).get("totalPages") or 1)
                header_date = header_date or ((body.get("header") or {}).get("date"))
                for r in body.get("results") or []:
                    rows.append({**r, "index_code": index_code, "header_date": header_date})
                page += 1

        if not rows:
            raise B3BdiFetchError(f"index {index_code} returned no constituents")
        logger.info("B3 index %s: %d constituents (as of %s)", index_code, len(rows), header_date)
        return rows

    async def _get_json(self, url: str, *, label: str) -> Dict[str, Any]:
        last_exc: Optional[BaseException] = None
        attempts = max(1, self.max_retries)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout), follow_redirects=True,
            headers={**_HEADERS, "Accept": "application/json"},
        ) as client:
            for attempt in range(1, attempts + 1):
                try:
                    resp = await client.get(url)
                except httpx.HTTPError as exc:
                    last_exc = exc
                    await self._backoff(attempt, attempts)
                    continue
                if resp.status_code in _RETRY_STATUSES:
                    last_exc = B3BdiFetchError(f"{label} returned HTTP {resp.status_code}")
                    await self._backoff(attempt, attempts)
                    continue
                if resp.status_code != 200:
                    raise B3BdiFetchError(f"{label} returned HTTP {resp.status_code}")
                try:
                    return resp.json()
                except ValueError as exc:
                    raise B3BdiFetchError(f"{label} returned a non-JSON body: {exc}") from exc
        raise B3BdiFetchError(f"Failed to read {label} after {attempts} attempts: {last_exc}")
