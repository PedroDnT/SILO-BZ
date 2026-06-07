"""Apify-backed ETF market fetcher — scrapes etfsbrasil.com.br/comparador/<ticker>.

Why this exists
---------------
CVM open data does not expose ETF NAV / quotaholders for post-CVM-175 share
classes (etf_daily is empty — the registry's fund-level CNPJ no longer matches
the class-level CNPJ in cvm_fi_diario). etfsbrasil.com.br carries the per-ETF NAV,
number of cotistas, returns, fees and index, but renders NAV/cotistas via JS and
rate-limits direct scraping — so we drive the apify/web-scraper actor (headless
browser) with rotating RESIDENTIAL proxies.

Public surface
--------------
    ApifyETFFetcher().fetch(tickers) -> list[dict]   # one scraped record per ticker

The actor's pageFunction lives in apify/etfsbrasil_scraper.js (read at call time
and passed in the run input), so there is nothing to pre-deploy on Apify — only an
API token is required.

Configuration (env)
-------------------
    APIFY_TOKEN         required — Apify API token.
    APIFY_ETF_ACTOR     optional — actor id (default 'apify~web-scraper').
    APIFY_PROXY_GROUPS  optional — comma list (default 'RESIDENTIAL').

Data-integrity: a failed run (non-2xx, timeout, or empty dataset) RAISES — it
never returns a plausible-looking empty/fallback result. Parsing/validation and
the DB upsert live in src/pipeline/ingest_etf_market.py.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_COMPARADOR_URL = "https://www.etfsbrasil.com.br/comparador/{ticker}"
_PAGE_FUNCTION_PATH = Path(__file__).resolve().parents[2] / "apify" / "etfsbrasil_scraper.js"
_APIFY_BASE = "https://api.apify.com/v2"


class ApifyETFFetcher:
    """Runs the etfsbrasil web-scraper on Apify and returns the dataset items."""

    def __init__(
        self,
        token: Optional[str] = None,
        actor: Optional[str] = None,
        timeout_secs: int = 600,
    ) -> None:
        self._token = token or os.getenv("APIFY_TOKEN")
        if not self._token:
            raise RuntimeError(
                "APIFY_TOKEN is not set — required to run the etfsbrasil ETF scraper"
            )
        # Apify actor ids use '~' between owner and name in the REST path.
        self._actor = actor or os.getenv("APIFY_ETF_ACTOR", "apify~web-scraper")
        self._timeout = timeout_secs
        self._proxy_groups = [
            g.strip()
            for g in os.getenv("APIFY_PROXY_GROUPS", "RESIDENTIAL").split(",")
            if g.strip()
        ]
        self._page_function = _PAGE_FUNCTION_PATH.read_text(encoding="utf-8")

    def _build_input(self, tickers: List[str]) -> Dict[str, Any]:
        start_urls = [
            {"url": _COMPARADOR_URL.format(ticker=t.strip().lower())}
            for t in tickers
            if t and t.strip()
        ]
        if not start_urls:
            raise ValueError("ApifyETFFetcher.fetch called with no tickers")
        return {
            "startUrls": start_urls,
            "pageFunction": self._page_function,
            "proxyConfiguration": {
                "useApifyProxy": True,
                "apifyProxyGroups": self._proxy_groups,
            },
            "maxConcurrency": int(os.getenv("APIFY_ETF_CONCURRENCY", "5")),
            "maxRequestRetries": 3,
            "pageLoadTimeoutSecs": 60,
            "waitUntil": ["networkidle2"],
            "injectJQuery": False,
        }

    def fetch(self, tickers: List[str]) -> List[Dict[str, Any]]:
        """Run the scraper synchronously and return one record per scraped ticker.

        Raises on any transport error, non-2xx status, or an empty dataset — a
        failed scrape must surface, never masquerade as "no ETFs".
        """
        run_input = self._build_input(tickers)
        url = (
            f"{_APIFY_BASE}/acts/{self._actor}/run-sync-get-dataset-items"
            f"?token={self._token}&format=json"
        )
        body = json.dumps(run_input).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                payload = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise RuntimeError(
                f"Apify run failed for etfsbrasil scrape: HTTP {exc.code} — {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Apify run failed (network): {exc}") from exc

        items = json.loads(payload)
        if not isinstance(items, list) or not items:
            raise RuntimeError(
                "Apify etfsbrasil scrape returned an empty dataset — refusing to "
                "treat as success (check token, actor, proxy blocks, or selectors)"
            )
        logger.info("etfsbrasil scrape: %d ETF records for %d tickers",
                    len(items), len(tickers))
        return items
