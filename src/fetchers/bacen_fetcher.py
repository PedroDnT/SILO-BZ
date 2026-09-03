"""BACEN fetcher — async wrapper around python-bcb (SGS, PTAX, Expectativas,
TaxaJuros). The python-bcb library is synchronous, so each call is dispatched
via ``asyncio.to_thread``. This module fetches AND lightly normalizes BCB
DataFrames into row dicts; storage is done by src/pipeline/bacen_pipeline.py.

Usage:
    from src.fetchers.bacen_fetcher import BacenClient
    client = BacenClient()
    rows = await client.get_sgs_series({433: "IPCA"}, start="2020-01-01")
"""

import asyncio
import json
import logging
import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import quote, urlencode

import httpx
import numpy as np
import pandas as pd

try:
    import bcb
    from bcb import PTAX, Expectativas, TaxaJuros
except ImportError as exc:  # pragma: no cover
    raise ImportError("python-bcb is required. Run: pip install python-bcb") from exc

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Direct Olinda (OData) access
#
# Expectativas and PTAX are fetched over plain HTTP rather than through
# python-bcb, because both of the library's paths are broken against the live
# service and failed silently:
#
#   * Expectativas — python-bcb composes multiple filters with the `&`
#     operator, which its ODataPropertyFilter no longer supports:
#     "unsupported operand type(s) for &: 'ODataPropertyFilter' and
#     'ODataPropertyFilter'". Every multi-filter Focus fetch raised, was caught,
#     logged as a warning and counted as 0 rows, so the job stayed green while
#     ingesting nothing.
#   * PTAX — the library formats dates as M/D/YYYY. Olinda wants MM-DD-YYYY and
#     answers an M/D/YYYY request with HTTP 200 and an EMPTY result set, which
#     is indistinguishable from "no data" and produced bacen_ptax: 0 forever.
#
# Both were verified against the live API while writing this: the same filter
# that fails through the library returns rows over raw HTTP, and PTAX returns
# rows only with MM-DD-YYYY.
#
# Encoding matters. Spaces in an OData $filter must be %20; urlencode's default
# quote_plus emits '+', which Olinda rejects with
# "The types 'Edm.Boolean' and 'Edm.String' are not compatible."  Hence
# quote_via=quote below.
# ---------------------------------------------------------------------------

_OLINDA = "https://olinda.bcb.gov.br/olinda/servico"
# SGS (Sistema Gerenciador de Séries Temporais) REST API. One series per
# request; python-bcb's sgs.get() wrapped the same endpoint but raised on the
# first series that answered 404 and discarded every series fetched before it.
_SGS = "https://api.bcb.gov.br/dados/serie"

_OLINDA_PAGE = 10_000
_OLINDA_MAX_PAGES = 50
# Same transient set as B3 COTAHIST. Olinda returned HTML 503 on the
# 2026-08-19 daily run and, with no retry, took the whole job red after
# CVM/ANBIMA/B3 had already succeeded (Actions run 32221952063).
_OLINDA_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

# Expectativas endpoints that carry a Suavizada (smoothed Y/N) dimension —
# see the comment in BacenClient.get_expectativas().
_SUAVIZADA_ENDPOINTS = frozenset({
    "ExpectativasMercadoInflacao12Meses",
    "ExpectativasMercadoInflacao13a24Meses",
})


class BacenFetchError(RuntimeError):
    """A BACEN request failed or returned an unusable payload.

    Raised rather than returning an empty list: an empty result is a legitimate
    answer from these endpoints, so swallowing errors into `[]` makes a broken
    fetch look exactly like a quiet week. That confusion is what kept the Focus
    tables empty while every run reported success.
    """


def _olinda_retry_config() -> Tuple[int, float]:
    """Attempts and delay (seconds) for Olinda GETs.

    Read from the environment on every call so tests can pin retries to 1–2
    without reimporting the module. Defaults match B3: a few tries, linear
    backoff. Exhausted retries still raise — a persistent 503 is an error,
    not an empty week.
    """
    attempts = max(1, int(os.getenv("BACEN_OLINDA_MAX_RETRIES", "4")))
    delay = float(os.getenv("BACEN_OLINDA_RETRY_DELAY", "2"))
    return attempts, delay


def _olinda_parse(body: str, url: str) -> Dict[str, Any]:
    """Parse an Olinda response, turning its error envelope into an exception.

    Olinda reports errors as HTTP 400 with a JSONP-style ``/*{...}*/`` body,
    which json.loads cannot read. Unwrap it so the real message survives.
    """
    text = body.strip()
    if text.startswith("/*") and text.endswith("*/"):
        text = text[2:-2].strip()
        try:
            err = json.loads(text)
        except json.JSONDecodeError:
            raise BacenFetchError(f"{url}: unparseable error envelope: {body[:200]}")
        raise BacenFetchError(
            f"{url}: BACEN returned {err.get('codigo')}: {err.get('mensagem')}"
        )
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise BacenFetchError(f"{url}: response is not JSON: {body[:200]}") from exc


async def _olinda_request(
    client: httpx.AsyncClient,
    url: str,
    full: str,
    *,
    attempts: int,
    delay: float,
) -> Dict[str, Any]:
    """GET one Olinda URL, retrying transient HTTP/network failures.

    Status is inspected before JSON parsing: a 503 HTML body used to surface
    as "response is not JSON" and abort without a second try. Persistent
    failures still raise ``BacenFetchError`` — never an empty list.
    """
    last_exc: Optional[BaseException] = None
    for attempt in range(1, attempts + 1):
        try:
            resp = await client.get(full)
        except httpx.HTTPError as exc:
            last_exc = exc
            logger.warning(
                "Olinda request error %s attempt=%d/%d: %s",
                url, attempt, attempts, exc,
            )
            if attempt < attempts:
                await asyncio.sleep(delay * attempt)
            continue

        if resp.status_code in _OLINDA_RETRY_STATUSES:
            last_exc = BacenFetchError(f"{url}: HTTP {resp.status_code}")
            logger.warning(
                "Olinda HTTP %s attempt=%d/%d: %s",
                resp.status_code, attempt, attempts, url,
            )
            if attempt < attempts:
                await asyncio.sleep(delay * attempt)
            continue

        if resp.status_code != 200:
            # 4xx (and other non-retryable statuses) are not blips. Parse so
            # Olinda's /*{codigo,mensagem}*/ envelope survives; otherwise
            # raise with the status.
            try:
                _olinda_parse(resp.text, url)
            except BacenFetchError:
                raise
            raise BacenFetchError(f"{url}: HTTP {resp.status_code}")

        return _olinda_parse(resp.text, url)

    raise BacenFetchError(
        f"{url}: failed after {attempts} attempts: {last_exc}"
    )


async def _olinda_get(
    service: str,
    resource: str,
    params: Dict[str, str],
    *,
    paginate: bool = True,
) -> List[Dict[str, Any]]:
    """GET an Olinda OData resource, following $skip pages, raising on failure."""
    collected: List[Dict[str, Any]] = []
    skip = 0
    attempts, delay = _olinda_retry_config()
    async with httpx.AsyncClient(timeout=120.0) as client:
        for page in range(_OLINDA_MAX_PAGES):
            query = dict(params)
            query["$format"] = "json"
            if paginate:
                query["$top"] = str(_OLINDA_PAGE)
                if skip:
                    query["$skip"] = str(skip)
            url = f"{_OLINDA}/{service}/versao/v1/odata/{resource}"
            # quote_via=quote keeps spaces as %20; '+' is rejected by Olinda.
            full = f"{url}?{urlencode(query, quote_via=quote)}"
            payload = await _olinda_request(
                client, url, full, attempts=attempts, delay=delay,
            )
            batch = payload.get("value", [])
            collected.extend(batch)
            if not paginate or len(batch) < _OLINDA_PAGE:
                return collected
            skip += _OLINDA_PAGE
    logger.warning(
        "Olinda %s/%s hit the %d-page cap; returning %d rows",
        service, resource, _OLINDA_MAX_PAGES, len(collected),
    )
    return collected


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _df_to_records(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Convert a BCB DataFrame result to a JSON-serialisable list of dicts.
    - Resets datetime index to a regular column called 'date'.
    - Converts NaN → None and numpy types → native Python.
    - Converts date/datetime objects to ISO strings.
    """
    if df is None or df.empty:
        return []

    # Reset index so that the DatetimeIndex becomes a column.
    df = df.reset_index()

    records = []
    for row in df.to_dict(orient="records"):
        clean: Dict[str, Any] = {}
        for k, v in row.items():
            if isinstance(v, float) and np.isnan(v):
                clean[str(k)] = None
            elif isinstance(v, (pd.Timestamp, datetime, date)):
                clean[str(k)] = v.isoformat()
            elif isinstance(v, (np.integer,)):
                clean[str(k)] = int(v)
            elif isinstance(v, (np.floating,)):
                clean[str(k)] = None if np.isnan(v) else float(v)
            else:
                clean[str(k)] = v
        records.append(clean)
    return records


def _to_sgs_date(d: Optional[str]) -> Optional[str]:
    """ISO YYYY-MM-DD → the DD/MM/YYYY the SGS REST API expects."""
    if not d:
        return None
    return datetime.strptime(d[:10], "%Y-%m-%d").strftime("%d/%m/%Y")


def _sgs_iso(d: str) -> str:
    """SGS answers dates as DD/MM/YYYY; the warehouse keys on ISO."""
    return datetime.strptime(d.strip(), "%d/%m/%Y").date().isoformat()


def _sgs_value(raw: Any, *, label: str, code: int, when: str) -> Optional[float]:
    """SGS answers values as strings. Empty is NULL; anything else must parse.

    "Null stays null": an empty observation is stored as None, never as 0.
    A non-empty value that is not a number is a contract change on BACEN's
    side and raises rather than being coerced into a guess.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if text in ("", "-"):
        return None
    try:
        return float(text)
    except ValueError as exc:
        raise BacenFetchError(
            f"SGS {label} ({code}) {when}: non-numeric value {text!r}"
        ) from exc


_SGS_NOT_FOUND_MARKERS = ("Value(s) not found", "SGSNegocioException")


async def _sgs_request(
    client: httpx.AsyncClient,
    label: str,
    code: int,
    start: Optional[str],
    end: Optional[str],
    last: Optional[int],
    *,
    attempts: int,
    delay: float,
) -> List[Dict[str, Any]]:
    """GET one SGS series, retrying transient failures.

    Returns the raw ``[{"data": "DD/MM/YYYY", "valor": "..."}]`` list.

    A 404 whose body says ``Value(s) not found`` is BACEN's answer for "no
    observation in this window" — a monthly series asked for a window that
    starts after the 1st, or before this month's figure is published. That
    is a legitimate empty answer for THIS series and returns ``[]``. Every
    other failure raises ``BacenFetchError``: an outage must not read as a
    quiet month.
    """
    if last is not None:
        url = f"{_SGS}/bcdata.sgs.{code}/dados/ultimos/{int(last)}"
        params: Dict[str, str] = {"formato": "json"}
    else:
        url = f"{_SGS}/bcdata.sgs.{code}/dados"
        params = {"formato": "json"}
        if start:
            params["dataInicial"] = _to_sgs_date(start) or ""
        if end:
            params["dataFinal"] = _to_sgs_date(end) or ""
    full = f"{url}?{urlencode(params)}"
    where = f"SGS {label} ({code})"

    last_exc: Optional[BaseException] = None
    for attempt in range(1, attempts + 1):
        try:
            resp = await client.get(full)
        except httpx.HTTPError as exc:
            last_exc = exc
            logger.warning("%s request error attempt=%d/%d: %s", where, attempt, attempts, exc)
            if attempt < attempts:
                await asyncio.sleep(delay * attempt)
            continue

        if resp.status_code in _OLINDA_RETRY_STATUSES:
            last_exc = BacenFetchError(f"{where}: HTTP {resp.status_code}")
            logger.warning("%s HTTP %s attempt=%d/%d", where, resp.status_code, attempt, attempts)
            if attempt < attempts:
                await asyncio.sleep(delay * attempt)
            continue

        if resp.status_code == 404 and any(m in resp.text for m in _SGS_NOT_FOUND_MARKERS):
            return []

        if resp.status_code != 200:
            raise BacenFetchError(f"{where}: HTTP {resp.status_code}: {resp.text[:200]}")

        try:
            payload = json.loads(resp.text)
        except json.JSONDecodeError as exc:
            # Seen live 2026-09-03: HTTP 200 with an XHTML interstitial for
            # series 432, gone on the next request. A page is not data;
            # treat it as transient like a 503 and retry. Exhausted retries
            # still raise — never an empty window.
            last_exc = BacenFetchError(f"{where}: response is not JSON: {resp.text[:200]}")
            logger.warning("%s non-JSON 200 attempt=%d/%d: %s", where, attempt, attempts, resp.text[:80].replace("\n", " "))
            if attempt < attempts:
                await asyncio.sleep(delay * attempt)
            continue
        if not isinstance(payload, list):
            raise BacenFetchError(f"{where}: expected a JSON list, got {type(payload).__name__}")
        return payload

    raise BacenFetchError(f"{where}: failed after {attempts} attempts: {last_exc}")

# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class BacenClient:
    """
    Async client for Banco Central do Brasil public data via python-bcb.

    Instantiation is cheap (no IO). Each method call is wrapped in
    asyncio.to_thread to avoid blocking the event loop.
    """

    # ------------------------------------------------------------------
    # SGS – sistema gerenciador de séries temporais
    # ------------------------------------------------------------------

    async def get_sgs_series(
        self,
        codes: Dict[str, int],
        start: Optional[str] = None,
        end: Optional[str] = None,
        last: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch one or more SGS time series, one request per series.

        Args:
            codes: mapping of label → series code. E.g. {"IPCA": 433, "CDI": 12}
            start: ISO date string "YYYY-MM-DD"
            end:   ISO date string "YYYY-MM-DD"
            last:  fetch only the last N observations (mutually exclusive with start/end)

        Returns:
            List of dicts with keys matching ``codes`` plus a 'date' key
            (ISO), one dict per distinct observation date, sorted ascending.
            A series with no observation in the window is simply absent
            from every dict — it is not zero and it does not fail the
            others.

        Why not python-bcb's ``sgs.get``: it fetched the series in sequence
        and raised ``Download error: code = 433`` (433 is the IPCA series
        code, not an HTTP status) on the first 404, discarding CDI, Selic and
        every other series already fetched. The daily 30-day window asks
        for IPCA before the month's figure is published, so BACEN answers
        404 ``Value(s) not found`` for it most days — and until 2026-09-03
        that took all ten series down to zero rows (Daily CVM Ingest
        33721538761 and 33798733736 both logged ``bacen_sgs: 0``).

        Raises ``BacenFetchError`` on any failure that is not that documented
        404 — a broken fetch must not look like a quiet window.
        """
        attempts, delay = _olinda_retry_config()
        by_date: Dict[str, Dict[str, Any]] = {}
        async with httpx.AsyncClient(timeout=120.0) as client:
            for label, code in codes.items():
                points = await _sgs_request(
                    client, label, int(code), start, end, last,
                    attempts=attempts, delay=delay,
                )
                if not points:
                    logger.warning(
                        "SGS %s (%s): no observation for %s..%s (BACEN 404 or empty)",
                        label, code, start, end,
                    )
                    continue
                for point in points:
                    when = str(point.get("data", "")).strip()
                    if not when:
                        raise BacenFetchError(f"SGS {label} ({code}): observation without a date")
                    iso = _sgs_iso(when)
                    by_date.setdefault(iso, {"date": iso})[label] = _sgs_value(
                        point.get("valor"), label=label, code=int(code), when=iso,
                    )
        return [by_date[d] for d in sorted(by_date)]

    # ------------------------------------------------------------------
    # PTAX – exchange rates
    # ------------------------------------------------------------------

    async def get_ptax_dolar_dia(self, date_str: str) -> List[Dict[str, Any]]:
        """
        USD/BRL PTAX closing rate for a specific date.

        Args:
            date_str: ISO date "YYYY-MM-DD"

        Returns:
            List of dicts with compra/venda rates (typically 1 row).
        """
        def _fetch() -> pd.DataFrame:
            ptax = PTAX()
            ep = ptax.get_endpoint("CotacaoDolarDia")
            # PTAX date format: M/D/YYYY
            d = datetime.strptime(date_str, "%Y-%m-%d")
            ptax_date = f"{d.month}/{d.day}/{d.year}"
            return ep.query().parameters(dataCotacao=ptax_date).collect()

        df = await asyncio.to_thread(_fetch)
        return _df_to_records(df)

    async def get_ptax_dolar_periodo(
        self, start: str, end: str
    ) -> List[Dict[str, Any]]:
        """
        USD/BRL PTAX closing rates for a date range.

        Args:
            start: ISO date "YYYY-MM-DD"
            end:   ISO date "YYYY-MM-DD"

        Returns:
            List of dicts with daily compra/venda rates.
        """
        def _fetch() -> pd.DataFrame:
            ptax = PTAX()
            ep = ptax.get_endpoint("CotacaoDolarPeriodo")
            s = datetime.strptime(start, "%Y-%m-%d")
            e = datetime.strptime(end, "%Y-%m-%d")
            ptax_start = f"{s.month}/{s.day}/{s.year}"
            ptax_end = f"{e.month}/{e.day}/{e.year}"
            return ep.query().parameters(
                dataInicial=ptax_start, dataFinalCotacao=ptax_end
            ).collect()

        df = await asyncio.to_thread(_fetch)
        return _df_to_records(df)

    async def get_ptax_moeda_dia(
        self, moeda: str, date_str: str
    ) -> List[Dict[str, Any]]:
        """
        Exchange rate for any currency vs BRL for a specific date.

        Args:
            moeda:    3-letter currency code, e.g. "EUR", "GBP"
            date_str: ISO date "YYYY-MM-DD"

        Returns:
            List of dicts with compra/venda rates.
        """
        def _fetch() -> pd.DataFrame:
            ptax = PTAX()
            ep = ptax.get_endpoint("CotacaoMoedaDia")
            d = datetime.strptime(date_str, "%Y-%m-%d")
            ptax_date = f"{d.month}/{d.day}/{d.year}"
            return ep.query().parameters(moeda=moeda, dataCotacao=ptax_date).collect()

        df = await asyncio.to_thread(_fetch)
        return _df_to_records(df)

    async def get_ptax_moeda_periodo(
        self, moeda: str, start: str, end: str
    ) -> List[Dict[str, Any]]:
        """
        Exchange rate for any currency vs BRL for a date range.

        Args:
            moeda:  3-letter currency code, e.g. "EUR"
            start:  ISO date "YYYY-MM-DD"
            end:    ISO date "YYYY-MM-DD"

        Returns:
            List of dicts with daily compra/venda rates.
        """
        # MM-DD-YYYY, not M/D/YYYY. Olinda answers the latter with HTTP 200 and
        # an empty result set — silently, which is how bacen_ptax stayed at 0.
        s = datetime.strptime(start, "%Y-%m-%d")
        e = datetime.strptime(end, "%Y-%m-%d")
        resource = (
            "CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,"
            "dataFinalCotacao=@dataFinalCotacao)"
        )
        return await _olinda_get(
            "PTAX",
            resource,
            {
                "@moeda": f"'{moeda}'",
                "@dataInicial": f"'{s:%m-%d-%Y}'",
                "@dataFinalCotacao": f"'{e:%m-%d-%Y}'",
            },
        )

    async def get_ptax_moedas(self) -> List[Dict[str, Any]]:
        """
        List all currencies available in PTAX.

        Returns:
            List of dicts with currency metadata.
        """
        def _fetch() -> pd.DataFrame:
            ptax = PTAX()
            ep = ptax.get_endpoint("Moedas")
            return ep.query().collect()

        df = await asyncio.to_thread(_fetch)
        return _df_to_records(df)

    # ------------------------------------------------------------------
    # Expectativas – market expectations
    # ------------------------------------------------------------------

    EXPECTATIVAS_ENDPOINTS = [
        "ExpectativasMercadoAnuais",
        "ExpectativasMercadoMensais",
        "ExpectativasMercadoTrimestrais",
        "ExpectativasMercadoSelic",
        "ExpectativasMercadoTop5Anuais",
        "ExpectativasMercadoTop5Mensais",
        "ExpectativasMercadoInflacao12Meses",
        "InstituicoesCreditoras",
    ]

    async def get_expectativas(
        self,
        endpoint_name: str,
        indicador: Optional[str] = None,
        start: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Query the BACEN market expectations (Focus bulletin) API.

        Args:
            endpoint_name: one of EXPECTATIVAS_ENDPOINTS
            indicador:     filter by indicator, e.g. "IPCA", "Selic"
            start:         ISO date for field 'Data' lower bound
            limit:         max rows to return (default 100)

        Returns:
            List of dicts with expectation data.
        """
        filters: List[str] = []
        if indicador:
            filters.append(f"Indicador eq '{indicador}'")
        if start:
            filters.append(f"Data ge '{start}'")
        # BACEN publishes TWO statistics per (Indicador, Data, DataReferencia):
        # baseCalculo=0 uses submissions from the trailing 30 days, baseCalculo=1
        # from the trailing 4 business days — verified live, e.g. IPCA/2026-08-07/
        # 2026: baseCalculo=0 has Mediana=5.0176 (151 respondents), baseCalculo=1
        # has Mediana=4.9927 (34 respondents). Our natural key doesn't carry
        # baseCalculo, so without this filter the two silently collided on
        # upsert — whichever the API happened to return last won arbitrarily.
        # 0 is the market-standard "Focus" figure (the one BACEN's own bulletin
        # and financial press quote); 1 is a separate, narrower product.
        filters.append("baseCalculo eq 0")
        # The two Inflacao12Meses/13Meses endpoints carry a second dimension
        # BACEN's other Expectativas endpoints don't have: Suavizada (Y/N,
        # smoothed vs raw), also not part of our natural key and colliding the
        # same way baseCalculo did. Conditional because filtering on a field
        # that doesn't exist on the other endpoints 400s the request (verified
        # live). 'N' (unsmoothed) is the series conventionally quoted as "the"
        # 12-month expectation; 'S' is a supplementary smoothed treatment.
        if endpoint_name in _SUAVIZADA_ENDPOINTS:
            filters.append("Suavizada eq 'N'")

        params: Dict[str, str] = {"$orderby": "Data desc"}
        if filters:
            params["$filter"] = " and ".join(filters)

        return await _olinda_get("Expectativas", endpoint_name, params)

    # ------------------------------------------------------------------
    # TaxaJuros – interest rates by institution
    # ------------------------------------------------------------------

    TAXAS_JUROS_ENDPOINTS = [
        "TaxasJurosMercadoImobiliario",
    ]

    async def get_taxas_juros(
        self,
        endpoint_name: str = "TaxasJurosMercadoImobiliario",
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Query BACEN interest-rate data via TaxaJuros OData API.

        Args:
            endpoint_name: OData endpoint name
            limit:         max rows to return

        Returns:
            List of dicts with interest-rate data.
        """
        def _fetch() -> pd.DataFrame:
            tj = TaxaJuros()
            ep = tj.get_endpoint(endpoint_name)
            return ep.query().limit(limit).collect()

        df = await asyncio.to_thread(_fetch)
        return _df_to_records(df)
