"""Daily levels of B3-published indices, one calendar year per call.

The source is B3's index statistics proxy, the JSON the index page calls:

    GET {BASE_URL}/GetPortfolioDay/{base64 {"index": "IBOV", "language": "pt-br", "year": "2025"}}

The index is named in the token, not the path, like every B3 proxy here. The
answer is a calendar grid, not a list:

    {"min": {"day": 0, "rateValue1": ...}, "max": {...},
     "results": [{"day": 1, "rateValue1": null, "rateValue2": "131.147,29", ...},
                 ...                                   # day 1 .. 31
                 {"day": 31, ...}]}

``rateValueN`` is month N of the requested year and a null cell is a day with
no session (a weekend, a holiday, a 30th of February). ``min`` and ``max`` are
per-month extremes on a pseudo-day 0 and carry no session. Numbers use the
Brazilian format ("161.125,37"). Verified 2026-09-30 for IBOV 1968-2026: 14,489
sessions, no duplicate date, no weekend, no cell that is not a number.

The endpoint answers HTTP 200 with ``"results": null`` for a code B3 does not
publish here (IFNM did on 2026-09-29), and for any year it has nothing for.
That is B3 saying "no such series", and returning it as an empty year would
publish a fabricated gap, so it raises ``B3IndexNoResults``.

Parsing and validation are in src/pipeline/ingest_b3_index.py; this module is
transport only.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

BASE_URL = (
    "https://sistemaswebb3-listados.b3.com.br/indexStatisticsProxy/IndexCall"
)

# B3 rejects requests without a browser-ish UA.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://sistemaswebb3-listados.b3.com.br/",
}


class B3IndexNoResults(LookupError):
    """B3 answered 200 with ``results: null`` for an index and year.

    For a code SILO has configured this is an error, never an empty year: it
    means the code is not published by this endpoint, or B3 has no series for
    that year. Retrying does not fill it.
    """


class B3IndexFetcher:
    """Fetch one year of an index's daily levels from B3's statistics proxy."""

    def __init__(
        self,
        timeout: int = 40,
        max_retries: int = 3,
        sleep_between: float = 0.5,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.sleep_between = sleep_between
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    @staticmethod
    def _token(index_code: str, year: int) -> str:
        payload = {"index": index_code, "language": "pt-br", "year": str(year)}
        return base64.b64encode(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        ).decode("ascii")

    def fetch_year(self, index_code: str, year: int) -> Dict[str, Any]:
        """The decoded year grid for one index. Raises; never returns a stub.

        A failed fetch raises after ``max_retries`` so the caller logs an error
        row. A null ``results`` raises B3IndexNoResults at once.
        """
        url = f"{BASE_URL}/GetPortfolioDay/{self._token(index_code, year)}"
        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                body = response.text.strip()
                if not body:
                    raise ValueError(
                        f"GetPortfolioDay returned an empty body for "
                        f"{index_code} {year}: B3 answers 200 with no content "
                        "when the path token is malformed"
                    )
                payload = json.loads(body)
                if not isinstance(payload, dict):
                    raise ValueError(
                        f"unexpected GetPortfolioDay payload for {index_code} "
                        f"{year}: {type(payload).__name__}"
                    )
                if payload.get("results") is None:
                    raise B3IndexNoResults(
                        f"GetPortfolioDay returned results=null for "
                        f"{index_code} {year}"
                    )
                return payload
            except B3IndexNoResults:
                raise
            except Exception as exc:  # noqa: BLE001 - re-raised below
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(self.sleep_between * (2 ** attempt))
        raise RuntimeError(
            f"B3 GetPortfolioDay failed after {self.max_retries} attempts for "
            f"{index_code} {year}: {last_error}"
        ) from last_error
