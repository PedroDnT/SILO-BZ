"""B3 index closing levels (Ibovespa and siblings) — public, no auth.

WHY THIS EXISTS
---------------
The research seam needs the benchmark as its ADMINISTRATOR publishes it
(RESEARCH_SEAM.md §5, #412). BACEN SGS 7 stopped on 2019-09-30, and the tape's
IBOV11 is the options settlement index, printed only on expiry days and never
equal to the close; BOVA11 is an ETF. Neither may stand in for the index
(docs/reference/research/ibovespa-source.md).

THE CONTRACT (verified live 2026-09-28 and 2026-09-30)
------------------------------------------------------
    GET https://sistemaswebb3-listados.b3.com.br/indexStatisticsProxy/IndexCall/
        GetPortfolioDay/<base64 of {"index":"IBOV","language":"pt-br","year":"YYYY"}>
    -> {"results": [{"day": 1..31, "rateValue1".."rateValue12": "183.476,86" | null}],
        "min": {...same keys, monthly min...}, "max": {...monthly max...}}

One call per index and year: a day x month grid of pt-BR decimal strings, null
on non-session days. The 2025-12-30 value, 161.125,37, is B3's own published
year-end close. It is NOT the `indexProxy/indexCall/GetPortfolioDay` endpoint
b3_bdi_fetcher uses for index MEMBERSHIP; same name, different service.

There is no published contract, so everything the grid claims is checked and
any surprise raises (integrity rule 1): an unknown code answers HTTP 200 with
`"results": null` (IFNM did on 2026-09-29), which is an error here, never an
empty year.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

import httpx

from src.parsers.validation import DataValidator

logger = logging.getLogger(__name__)

DEFAULT_URL = "https://sistemaswebb3-listados.b3.com.br/indexStatisticsProxy/IndexCall/GetPortfolioDay"
SOURCE = "b3_index_statistics"

# Same stance as the other B3 proxies: a bare client is refused, and 403/429
# and 5xx from this edge are transient, never "no data".
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Referer": "https://sistemaswebb3-listados.b3.com.br/indexStatisticsPage/",
}
_RETRY_STATUSES = frozenset({403, 429, 500, 502, 503, 504})

# "183.476,86": thousands with dots, exactly two decimals, as published.
_LEVEL = re.compile(r"^\d{1,3}(?:\.\d{3})*,\d{2}$")


class B3IndexLevelError(RuntimeError):
    """The endpoint failed, or its answer broke a check. Never 'no data'."""


def _token(index_code: str, year: int) -> str:
    return base64.b64encode(
        json.dumps({"index": index_code, "language": "pt-br", "year": str(year)}).encode()
    ).decode()


def parse_level(text: str) -> Decimal:
    """'161.125,37' -> Decimal('161125.37'). Anything else raises."""
    if not isinstance(text, str) or not _LEVEL.match(text):
        raise B3IndexLevelError(f"unreadable index level {text!r}")
    return Decimal(text.replace(".", "").replace(",", "."))


def parse_year(
    body: Any, index_code: str, year: int, *, today: Optional[date] = None, source_url: str = ""
) -> List[Dict[str, Any]]:
    """One year's grid -> rows keyed (index_code, trade_date), oldest first.

    Checks, each a raise: a null or missing grid; a day outside 1..31 or
    repeated; a value on an impossible date, a weekend or a future date; an
    unreadable or non-positive level; and each month's min and max disagreeing
    with the levels the grid carries. A past year with no level at all raises
    too; the current year may be empty only in its first days.
    """
    today = today or date.today()
    validator = DataValidator()
    if not isinstance(body, dict) or not isinstance(body.get("results"), list) or not body["results"]:
        raise B3IndexLevelError(
            f"{index_code} {year}: the endpoint returned no grid (results={type(body.get('results')).__name__ if isinstance(body, dict) else body!r}); "
            "a null result for a configured index is an error, never an empty year"
        )
    rows: List[Dict[str, Any]] = []
    seen_days: set = set()
    by_month: Dict[int, List[Decimal]] = {}
    for entry in body["results"]:
        day = entry.get("day") if isinstance(entry, dict) else None
        if not isinstance(day, int) or not 1 <= day <= 31 or day in seen_days:
            raise B3IndexLevelError(f"{index_code} {year}: bad or repeated grid day {day!r}")
        seen_days.add(day)
        for month in range(1, 13):
            raw = entry.get(f"rateValue{month}")
            if raw is None:
                continue
            try:
                d = date(year, month, day)
            except ValueError as exc:
                raise B3IndexLevelError(f"{index_code} {year}: a level on an impossible date {year}-{month:02d}-{day:02d}") from exc
            if d.isoweekday() > 5:
                raise B3IndexLevelError(f"{index_code}: a level on a weekend, {d}")
            if d > today:
                raise B3IndexLevelError(f"{index_code}: a level dated in the future, {d}")
            level = parse_level(raw)
            ok_date, why_date = validator.validate_field("trade_date", d.isoformat(), "date")
            ok_num, why_num = validator.validate_field("level", str(level), "numeric")
            if not (ok_date and ok_num) or level <= 0:
                raise B3IndexLevelError(f"{index_code} {d}: invalid row ({why_date or why_num or 'level must be positive'})")
            by_month.setdefault(month, []).append(level)
            rows.append({
                "index_code": index_code,
                "trade_date": d.isoformat(),
                "level": level,
                "source": SOURCE,
                "source_url": source_url or None,
            })
    # The grid also publishes each month's min and max: they must be the
    # extremes of the levels it carries, or the format moved under us.
    for bound, pick in (("min", min), ("max", max)):
        published = body.get(bound) if isinstance(body.get(bound), dict) else {}
        for month, levels in by_month.items():
            raw = published.get(f"rateValue{month}")
            if raw is not None and parse_level(raw) != pick(levels):
                raise B3IndexLevelError(
                    f"{index_code} {year}-{month:02d}: published {bound} {raw} is not the {bound} of the grid ({pick(levels)})"
                )
    if not rows and (year < today.year or (today - date(year, 1, 1)).days > 10):
        raise B3IndexLevelError(f"{index_code} {year}: the grid holds no level for a year that has sessions")
    rows.sort(key=lambda r: r["trade_date"])
    return rows


class B3IndexLevelFetcher:
    def __init__(self, url: str = DEFAULT_URL, timeout: float = 30.0,
                 max_retries: int = 4, retry_delay: float = 3.0) -> None:
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    def fetch_year(self, index_code: str, year: int, *, today: Optional[date] = None) -> List[Dict[str, Any]]:
        """One index, one year, as validated rows. Raises on any failure."""
        url = f"{self.url}/{_token(index_code, year)}"
        last: Optional[BaseException] = None
        with httpx.Client(timeout=self.timeout, headers=_HEADERS, follow_redirects=True) as client:
            for attempt in range(1, self.max_retries + 1):
                try:
                    resp = client.get(url)
                except httpx.HTTPError as exc:
                    last = exc
                else:
                    if resp.status_code == 200:
                        try:
                            body = resp.json()
                        except ValueError as exc:
                            raise B3IndexLevelError(f"{index_code} {year}: non-JSON body: {exc}") from exc
                        rows = parse_year(body, index_code, year, today=today, source_url=url)
                        logger.info("B3 index %s %d: %d closing levels", index_code, year, len(rows))
                        return rows
                    if resp.status_code not in _RETRY_STATUSES:
                        raise B3IndexLevelError(f"{index_code} {year}: HTTP {resp.status_code}")
                    last = B3IndexLevelError(f"{index_code} {year}: HTTP {resp.status_code}")
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay * attempt)
        raise B3IndexLevelError(f"{index_code} {year}: failed after {self.max_retries} attempts: {last}")
