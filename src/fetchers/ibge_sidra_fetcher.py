"""IBGE SIDRA fetcher — the IPCA item tree with its monthly weights.

BACEN's SGS publishes IPCA and the nine expenditure groups as monthly
variations only. What actually moves the headline is variation × weight, and
the weights live in IBGE's SIDRA, table 7060 (IPCA structure from 2020-01) and
its predecessor 1419 (2012-01..2019-12). Both carry the WHOLE tree — general
index, 9 groups, 19 subgroups, 51 items and ~377 subitems (457 rows a month in
7060, 464 in 1419) — and the same four variables:

    63    IPCA - Variação mensal               % in the month
    66    IPCA - Peso mensal                   % of the basket (Índice geral = 100)
    69    IPCA - Variação acumulada no ano     % year to date
    2265  IPCA - Variação acumulada em 12 meses

Endpoint contract, verified live 2026-09-21:

    GET https://apisidra.ibge.gov.br/values/t/{table}/n1/all/v/63,66,69,2265
        /p/{YYYYMM}-{YYYYMM}/c315/all?formato=json

  * The response is a JSON list whose FIRST element is a header row (its "V"
    is the literal "Valor"); every other element is one (variable, month,
    item) observation with the value in "V" as a string.
  * A month IBGE has not published answers HTTP 200 with the header row only;
    a range that straddles the release returns only the published months.
    That is "not published", not an outage — it must not raise.
  * "D4C" is the c315 classification code (7169 = Índice geral, 7170 =
    1.Alimentação e bebidas, …), "D4N" its name prefixed with IBGE's structure
    number ("1.", "11.", "1101.", "1101002."), which is where the level comes
    from. A code that is not part of the table's structure comes back with an
    empty "D4N" and "..." values; those rows are skipped and counted.
  * Twelve months × four variables × the whole tree is one 4.6 MB request
    (21,936 rows), so the fetch is chunked by calendar year.

Storage is src/pipeline/ibge_pipeline.py. Nothing here fills, guesses or
converts: "..." / "-" / "X" are IBGE's own not-available markers and become
NULL; any other non-numeric value is a contract change and raises.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

SIDRA_BASE = "https://apisidra.ibge.gov.br/values"

# (table, first month, last month or None for "still current"). Contiguous by
# construction: 1419 ends 2019-12, 7060 begins 2020-01 (both verified with
# /p/first 1 and /p/last 1).
IPCA_TABLES: Tuple[Tuple[int, str, Optional[str]], ...] = (
    (1419, "2012-01", "2019-12"),
    (7060, "2020-01", None),
)

# SIDRA variable code → column in ibge_ipca_item_monthly.
VARIABLES: Dict[str, str] = {
    "63":   "variacao_mensal",
    "66":   "peso_mensal",
    "69":   "variacao_acum_ano",
    "2265": "variacao_acum_12m",
}

# IBGE's own "no value" markers. Anything else non-numeric raises.
_NOT_AVAILABLE = frozenset({"...", "..", "-", "X", ""})

# Structure-number length → level. Verified on 7060/2026-08: 1 geral (no
# prefix), 9 one-digit groups, 19 two-digit subgroups, 51 four-digit items,
# 377 seven-digit subitems.
_LEVEL_BY_PREFIX_LEN = {1: 1, 2: 2, 4: 3, 7: 4}
_NAME_RE = re.compile(r"^(?P<num>\d+)\.(?P<name>.+)$")

_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class SidraFetchError(RuntimeError):
    """A SIDRA request failed or answered something that is not IPCA data."""


def _retry_config() -> Tuple[int, float]:
    attempts = max(1, int(os.getenv("IBGE_SIDRA_MAX_RETRIES", "4")))
    delay = float(os.getenv("IBGE_SIDRA_RETRY_DELAY", "2"))
    return attempts, delay


def _yyyymm(d: date) -> str:
    return f"{d.year:04d}{d.month:02d}"


def _month(s: str) -> date:
    """'2020-01' → date(2020, 1, 1)."""
    y, m = s.split("-")
    return date(int(y), int(m), 1)


def table_windows(start: date, end: date) -> List[Tuple[int, str, str]]:
    """Plan the requests for ``start..end`` (first-of-month dates, inclusive).

    Returns ``(table, from YYYYMM, to YYYYMM)`` triples: each SIDRA table is
    clipped to its own span and then cut into calendar-year chunks, so no
    request asks a table for months it never carried and none exceeds twelve
    months. Months before 2012-01 are silently outside every table — there is
    no earlier item-level source, and asking 1419 for 2011 would only ever
    return the header row.
    """
    plan: List[Tuple[int, str, str]] = []
    start = start.replace(day=1)
    end = end.replace(day=1)
    for table, first, last in IPCA_TABLES:
        lo = max(start, _month(first))
        hi = min(end, _month(last)) if last else end
        if hi < lo:
            continue
        cursor = lo
        while cursor <= hi:
            year_end = date(cursor.year, 12, 1)
            chunk_end = min(year_end, hi)
            plan.append((table, _yyyymm(cursor), _yyyymm(chunk_end)))
            cursor = date(cursor.year + 1, 1, 1)
    return plan


def _url(table: int, period_from: str, period_to: str) -> str:
    variables = ",".join(VARIABLES)
    period = period_from if period_from == period_to else f"{period_from}-{period_to}"
    return (
        f"{SIDRA_BASE}/t/{table}/n1/all/v/{variables}/p/{period}"
        f"/c315/all?formato=json"
    )


async def fetch_ipca_items(
    table: int, period_from: str, period_to: str
) -> List[Dict[str, Any]]:
    """GET one table window; return SIDRA's observation rows (header dropped).

    An empty list means IBGE has published none of those months. HTTP errors
    that persist through the retries, a non-JSON body and a body that is not
    the documented list-with-header shape all raise ``SidraFetchError``.
    """
    url = _url(table, period_from, period_to)
    attempts, delay = _retry_config()
    last_exc: Optional[BaseException] = None
    async with httpx.AsyncClient(timeout=180.0) as client:
        for attempt in range(1, attempts + 1):
            try:
                resp = await client.get(url)
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.warning("SIDRA t/%s %s..%s request error attempt=%d/%d: %s",
                               table, period_from, period_to, attempt, attempts, exc)
                if attempt < attempts:
                    await asyncio.sleep(delay * attempt)
                continue

            if resp.status_code in _RETRY_STATUSES:
                last_exc = SidraFetchError(f"SIDRA t/{table}: HTTP {resp.status_code}")
                logger.warning("SIDRA t/%s HTTP %s attempt=%d/%d",
                               table, resp.status_code, attempt, attempts)
                if attempt < attempts:
                    await asyncio.sleep(delay * attempt)
                continue

            if resp.status_code != 200:
                raise SidraFetchError(
                    f"SIDRA t/{table} {period_from}..{period_to}: HTTP {resp.status_code}: "
                    f"{resp.text[:200]}"
                )

            try:
                payload = json.loads(resp.text)
            except json.JSONDecodeError:
                # SIDRA answers overload with an HTML page on a 200; a page
                # is not data, treat it as transient.
                last_exc = SidraFetchError(
                    f"SIDRA t/{table}: response is not JSON: {resp.text[:200]}"
                )
                logger.warning("SIDRA t/%s non-JSON 200 attempt=%d/%d", table, attempt, attempts)
                if attempt < attempts:
                    await asyncio.sleep(delay * attempt)
                continue

            if not isinstance(payload, list) or not payload:
                raise SidraFetchError(
                    f"SIDRA t/{table}: expected a non-empty JSON list, got "
                    f"{type(payload).__name__} of length {len(payload) if isinstance(payload, list) else 'n/a'}"
                )
            header = payload[0]
            if not isinstance(header, dict) or header.get("V") != "Valor":
                raise SidraFetchError(
                    f"SIDRA t/{table}: first row is not the documented header: {str(header)[:200]}"
                )
            return [row for row in payload[1:] if isinstance(row, dict)]

    raise SidraFetchError(
        f"SIDRA t/{table} {period_from}..{period_to}: failed after {attempts} attempts: {last_exc}"
    )


def _value(raw: Any, *, where: str) -> Optional[float]:
    if raw is None:
        return None
    text = str(raw).strip()
    if text in _NOT_AVAILABLE:
        return None
    try:
        return float(text)
    except ValueError as exc:
        raise SidraFetchError(f"{where}: non-numeric value {text!r}") from exc


def parse_ipca_items(rows: List[Dict[str, Any]], table: int) -> Tuple[List[Dict[str, Any]], int]:
    """Pivot SIDRA's long observations into one row per (month, item).

    Returns ``(rows, skipped)`` where ``skipped`` counts observations whose
    item is not part of this table's structure (empty "D4N"). A month, code
    or name that does not parse raises: those are the natural key and are
    never guessed.
    """
    by_key: Dict[Tuple[date, int], Dict[str, Any]] = {}
    skipped = 0
    for obs in rows:
        name_raw = str(obs.get("D4N") or "").strip()
        if not name_raw:
            skipped += 1
            continue
        var = str(obs.get("D2C") or "").strip()
        column = VARIABLES.get(var)
        if column is None:
            raise SidraFetchError(f"SIDRA t/{table}: unexpected variable code {var!r}")
        period = str(obs.get("D3C") or "").strip()
        if not re.fullmatch(r"\d{6}", period):
            raise SidraFetchError(f"SIDRA t/{table}: unparseable month {period!r}")
        reference_month = date(int(period[:4]), int(period[4:]), 1)
        code_raw = str(obs.get("D4C") or "").strip()
        if not code_raw.isdigit():
            raise SidraFetchError(f"SIDRA t/{table}: unparseable item code {code_raw!r}")
        item_code = int(code_raw)

        m = _NAME_RE.match(name_raw)
        if m:
            number, name = m.group("num"), m.group("name").strip()
            level = _LEVEL_BY_PREFIX_LEN.get(len(number))
            if level is None:
                raise SidraFetchError(
                    f"SIDRA t/{table}: structure number {number!r} has an unknown length"
                )
        else:
            number, name, level = None, name_raw, 0

        where = f"SIDRA t/{table} {period} {code_raw} v{var}"
        row = by_key.setdefault((reference_month, item_code), {
            "reference_month":   reference_month.isoformat(),
            "item_code":         item_code,
            "item_number":       number,
            "item_name":         name,
            "level":             level,
            "variacao_mensal":   None,
            "peso_mensal":       None,
            "variacao_acum_ano": None,
            "variacao_acum_12m": None,
            "sidra_table":       table,
        })
        row[column] = _value(obs.get("V"), where=where)
    ordered = sorted(by_key.values(), key=lambda r: (r["reference_month"], r["item_code"]))
    return ordered, skipped
