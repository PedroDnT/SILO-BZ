"""Tesouro Direto fetcher — the Treasury's daily posted rates and prices per title.

One public CSV on the Tesouro Transparente open-data portal (CKAN dataset
``taxas-dos-titulos-ofertados-pelo-tesouro-direto``, ODbL licence) holds the
whole history: every title the retail platform offered, every base date from
2004-12-31. The publisher refreshes it on the business day after each session
and states that past values "may be revised", so a stored copy is upserted,
never only appended.

Contract, verified on the live file 2026-11-16 (14.7 MB, 178,594 rows):

    Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;PU Compra Manha;PU Venda Manha;PU Base Manha
    Tesouro Selic;01/03/2031;13/11/2026;0,11;0,12;20211,26;20192,26;20192,26

  * ``;`` separator, ``,`` decimal, dates ``dd/mm/yyyy``. The metadata sheet
    says thousands are separated by ``.``; the live file has none. Both parse.
  * The key (Tipo Titulo, Data Vencimento, Data Base) is unique: 0 duplicates.
  * Rates are percent a year and can be negative (a Tesouro Selic spread, an
    IPCA+ real rate in 2020). They are stored as published.
  * ``PU Compra`` / ``PU Venda`` are ``0,00`` when the title is not on sale on
    that side (49 rows, mostly the day before maturity). That is the
    publisher's "not offered" marker, not a price: it becomes NULL.
  * What the numbers are: the Treasury's posted morning quote on its retail
    platform, not a trade. ``PU Base`` is the same-day mark the platform uses
    for holdings (metadata sheet).

Storage is src/pipeline/tesouro_pipeline.py. Nothing here fills or guesses: a
changed header raises, and a row whose date or number does not parse is dropped
and counted.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .http import Retry, env_retry_config, linear, retry_async

logger = logging.getLogger(__name__)

CSV_URL = (
    "https://www.tesourotransparente.gov.br/ckan/dataset/"
    "df56aa42-484a-4a59-8184-7676580c81e3/resource/"
    "796d2059-14e9-44e3-80c9-2d9e30b405c1/download/precotaxatesourodireto.csv"
)

# CSV header → column in tesouro_direto_daily, in the file's order.
FIELD_MAP: Dict[str, str] = {
    "Tipo Titulo": "tipo_titulo",
    "Data Vencimento": "data_vencimento",
    "Data Base": "data_base",
    "Taxa Compra Manha": "taxa_compra",
    "Taxa Venda Manha": "taxa_venda",
    "PU Compra Manha": "pu_compra",
    "PU Venda Manha": "pu_venda",
    "PU Base Manha": "pu_base",
}
_DATES = ("data_vencimento", "data_base")
_RATES = ("taxa_compra", "taxa_venda")
_PRICES = ("pu_compra", "pu_venda", "pu_base")

_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class TesouroFetchError(RuntimeError):
    """The download failed or the file is not the documented CSV."""


def _retry_config() -> Tuple[int, float]:
    return env_retry_config("TESOURO", attempts="4", delay="5")


async def fetch_csv() -> bytes:
    """GET the whole file. Persistent HTTP errors raise ``TesouroFetchError``."""
    attempts, delay = _retry_config()
    async with httpx.AsyncClient(timeout=180.0, follow_redirects=True) as client:

        async def attempt(n: int) -> bytes:
            try:
                resp = await client.get(CSV_URL)
            except httpx.HTTPError as exc:
                logger.warning("Tesouro Direto request error attempt=%d/%d: %s", n, attempts, exc)
                raise Retry(exc) from exc
            if resp.status_code in _RETRY_STATUSES:
                logger.warning("Tesouro Direto HTTP %s attempt=%d/%d", resp.status_code, n, attempts)
                raise Retry(TesouroFetchError(f"Tesouro Direto: HTTP {resp.status_code}"))
            if resp.status_code != 200:
                raise TesouroFetchError(
                    f"Tesouro Direto: HTTP {resp.status_code}: {resp.text[:200]}"
                )
            return resp.content

        return await retry_async(
            attempt,
            attempts=attempts,
            backoff=linear(delay),
            exhausted=lambda last, n: TesouroFetchError(
                f"Tesouro Direto: failed after {n} attempts: {last}"
            ),
        )


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _number(value: str) -> Decimal:
    """'1.234,56' or '1234,56' → Decimal('1234.56'). Raises on anything else."""
    text = value.strip().replace(".", "").replace(",", ".")
    if not text:
        raise ValueError("empty number")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {value!r}") from exc


def _parse_row(raw: Dict[str, str]) -> Dict[str, Any]:
    title = (raw["Tipo Titulo"] or "").strip()
    if not title:
        raise ValueError("empty Tipo Titulo")
    row: Dict[str, Any] = {"tipo_titulo": title}
    for header, column in FIELD_MAP.items():
        if column == "tipo_titulo":
            continue
        value = raw[header]
        if column in _DATES:
            row[column] = datetime.strptime(value.strip(), "%d/%m/%Y").date()
        elif column in _RATES:
            row[column] = _number(value)
        else:
            price = _number(value)
            if price < 0:
                raise ValueError(f"negative {header}: {value!r}")
            # 0,00 is the publisher's "not on sale" marker, never a price.
            row[column] = None if price == 0 else price
    return row


def parse_csv(raw: bytes, since: Optional[date] = None) -> Tuple[List[Dict[str, Any]], int]:
    """Parse the file into rows keyed on (tipo_titulo, data_vencimento, data_base).

    ``since`` keeps only rows whose ``data_base`` is on or after it. Returns
    ``(rows, dropped)``: a row whose date or number does not parse is dropped
    and counted, never coerced. A header that differs from the documented one
    raises, and so does a file with no data rows.
    """
    reader = csv.DictReader(io.StringIO(_decode(raw)), delimiter=";")
    header = [h.strip() for h in (reader.fieldnames or [])]
    if header != list(FIELD_MAP):
        raise TesouroFetchError(f"Tesouro Direto: unexpected header {header!r}")
    reader.fieldnames = header

    rows: List[Dict[str, Any]] = []
    dropped = 0
    seen = 0
    for raw_row in reader:
        seen += 1
        try:
            row = _parse_row(raw_row)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            dropped += 1
            logger.warning("Tesouro Direto: row %d dropped: %s", seen, exc)
            continue
        if since is not None and row["data_base"] < since:
            continue
        rows.append(row)
    if seen == 0:
        raise TesouroFetchError("Tesouro Direto: the file has a header and no rows")
    return rows, dropped
