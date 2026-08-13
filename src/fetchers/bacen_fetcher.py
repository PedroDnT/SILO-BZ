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
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import quote, urlencode

import httpx
import numpy as np
import pandas as pd

try:
    import bcb
    from bcb import sgs, PTAX, Expectativas, TaxaJuros
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
_OLINDA_PAGE = 10_000
_OLINDA_MAX_PAGES = 50


class BacenFetchError(RuntimeError):
    """A BACEN request failed or returned an unusable payload.

    Raised rather than returning an empty list: an empty result is a legitimate
    answer from these endpoints, so swallowing errors into `[]` makes a broken
    fetch look exactly like a quiet week. That confusion is what kept the Focus
    tables empty while every run reported success.
    """


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
            try:
                resp = await client.get(full)
            except httpx.HTTPError as exc:
                raise BacenFetchError(f"{url}: request failed: {exc}") from exc
            payload = _olinda_parse(resp.text, url)
            if resp.status_code != 200:
                raise BacenFetchError(f"{url}: HTTP {resp.status_code}")
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
    """Accept ISO date (YYYY-MM-DD) and return it unchanged for python-bcb sgs.get."""
    return d  # python-bcb sgs accepts ISO strings directly

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
        Fetch one or more SGS time series.

        Args:
            codes: mapping of label → series code. E.g. {"IPCA": 433, "CDI": 12}
            start: ISO date string "YYYY-MM-DD"
            end:   ISO date string "YYYY-MM-DD"
            last:  fetch only the last N observations (mutually exclusive with start/end)

        Returns:
            List of dicts with keys matching ``codes`` plus a 'date' key.
        """
        def _fetch() -> pd.DataFrame:
            kwargs: Dict[str, Any] = {}
            if last is not None:
                kwargs["last"] = last
            else:
                if start:
                    kwargs["start"] = start
                if end:
                    kwargs["end"] = end
            return sgs.get(codes, **kwargs)

        df = await asyncio.to_thread(_fetch)
        return _df_to_records(df)

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
