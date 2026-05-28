"""
BACEN data ingestor — fetches SGS time series, PTAX exchange rates, and
Expectativas (Focus bulletin) from python-bcb and persists to Supabase.

Reuses BacenClient from src/clients/bacen_client.py.
"""

import asyncio
import logging
import os
import sys
from datetime import date, datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.fetchers.bacen_fetcher import BacenClient
from src.store.supabase_client import get_pg_client, upsert_rows

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Series / currency / endpoint configuration
# ---------------------------------------------------------------------------

SGS_SERIES: Dict[str, int] = {
    "SELIC_META":   432,
    "SELIC_DIARIA": 11,
    "CDI":          12,
    "IPCA":         433,
    "IGPM":         189,
    "INPC":         188,
    "USDBRL":       1,
    "EURBRL":       21619,
    "POUPANCA":     25,
    "PIB":          4380,
}

PTAX_CURRENCIES: List[str] = ["USD", "EUR", "GBP", "JPY", "ARS"]

EXPECTATIVAS_ENDPOINTS: List[str] = [
    "ExpectativasMercadoAnuais",
    "ExpectativasMercadoMensais",
    "ExpectativasMercadoSelic",
    "ExpectativasMercadoInflacao12Meses",
]

# Indicators to filter per endpoint (None = all)
EXPECTATIVAS_INDICATORS: Dict[str, Optional[List[str]]] = {
    "ExpectativasMercadoAnuais":        ["IPCA", "IGP-M", "PIB Total", "Selic"],
    "ExpectativasMercadoMensais":       ["IPCA", "IGP-M"],
    "ExpectativasMercadoSelic":         None,
    "ExpectativasMercadoInflacao12Meses": ["IPCA"],
}


# ---------------------------------------------------------------------------
# Ingestor
# ---------------------------------------------------------------------------

class BacenIngestor:
    """
    Downloads BACEN data and upserts to Supabase tables.

    Example::

        ingestor = BacenIngestor()
        await ingestor.backfill(start="2019-01-01")
    """

    def __init__(self) -> None:
        self._client  = BacenClient()
        self._supabase = get_pg_client()

    # ------------------------------------------------------------------
    # SGS time series
    # ------------------------------------------------------------------

    async def ingest_sgs(self, start: str, end: Optional[str] = None) -> int:
        """
        Fetch all configured SGS series for the given date range and upsert.

        Args:
            start: ISO date "YYYY-MM-DD"
            end:   ISO date "YYYY-MM-DD" (defaults to today)

        Returns:
            Total rows upserted across all series.
        """
        if end is None:
            end = date.today().isoformat()

        logger.info("SGS: start=%s end=%s series=%d", start, end, len(SGS_SERIES))
        total = 0

        # Fetch all series in one call (python-bcb returns a multi-column df)
        try:
            records = await self._client.get_sgs_series(
                codes=SGS_SERIES,
                start=start,
                end=end,
            )
        except Exception as exc:
            logger.error("SGS fetch failed: %s", exc)
            return 0

        if not records:
            logger.warning("SGS: no data returned for %s–%s", start, end)
            return 0

        # Flatten: one row per (series_name, date)
        rows: List[Dict[str, Any]] = []
        for rec in records:
            ref_date = rec.get("date") or rec.get("Date")
            if not ref_date:
                continue
            for series_name, series_code in SGS_SERIES.items():
                value = rec.get(series_name)
                if value is None:
                    continue
                rows.append({
                    "series_code":    series_code,
                    "series_name":    series_name,
                    "reference_date": str(ref_date)[:10],  # keep only date part
                    "value":          float(value) if value is not None else None,
                })

        total = upsert_rows(
            self._supabase, "bacen_sgs", rows,
            conflict_columns="series_code,reference_date"
        )
        logger.info("SGS done: rows=%d", total)
        return total

    # ------------------------------------------------------------------
    # PTAX exchange rates
    # ------------------------------------------------------------------

    async def ingest_ptax(self, start: str, end: Optional[str] = None) -> int:
        """Fetch PTAX rates for configured currencies and upsert."""
        if end is None:
            end = date.today().isoformat()

        logger.info("PTAX: start=%s end=%s currencies=%s", start, end, PTAX_CURRENCIES)
        total = 0

        async def _fetch_currency(currency: str) -> int:
            try:
                if currency == "USD":
                    records = await self._client.get_ptax_dolar_periodo(start, end)
                else:
                    records = await self._client.get_ptax_moeda_periodo(currency, start, end)
            except Exception as exc:
                logger.warning("PTAX fetch failed currency=%s: %s", currency, exc)
                return 0

            if not records:
                return 0

            rows: List[Dict[str, Any]] = []
            for rec in records:
                ref_date = rec.get("date") or rec.get("dataHoraCotacao", "")
                if hasattr(ref_date, "isoformat"):
                    ref_date = ref_date.isoformat()
                ref_date = str(ref_date)[:10]

                buy  = rec.get("cotacaoCompra") or rec.get("paridadeCompra")
                sell = rec.get("cotacaoVenda")  or rec.get("paridadeVenda")

                rows.append({
                    "currency":       currency,
                    "reference_date": ref_date,
                    "buy_rate":       float(buy)  if buy  is not None else None,
                    "sell_rate":      float(sell) if sell is not None else None,
                })

            return upsert_rows(
                self._supabase, "bacen_ptax", rows,
                conflict_columns="currency,reference_date"
            )

        results = await asyncio.gather(
            *[_fetch_currency(c) for c in PTAX_CURRENCIES],
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, int):
                total += r
            else:
                logger.error("PTAX task error: %s", r)

        logger.info("PTAX done: total=%d", total)
        return total

    # ------------------------------------------------------------------
    # Expectativas (Focus bulletin)
    # ------------------------------------------------------------------

    async def ingest_expectativas(
        self,
        start: str,
        limit_per_call: int = 10_000,
    ) -> int:
        """Fetch Focus / market expectation data and insert."""
        logger.info("Expectativas: start=%s endpoints=%d", start, len(EXPECTATIVAS_ENDPOINTS))
        total = 0

        async def _fetch_endpoint(endpoint: str, indicador: Optional[str]) -> int:
            try:
                records = await self._client.get_expectativas(
                    endpoint_name=endpoint,
                    indicador=indicador,
                    start=start,
                    limit=limit_per_call,
                )
            except Exception as exc:
                logger.warning("Expectativas fetch failed %s/%s: %s", endpoint, indicador, exc)
                return 0

            if not records:
                return 0

            rows: List[Dict[str, Any]] = []
            for rec in records:
                ref_date = rec.get("Data") or rec.get("data") or rec.get("date")
                if ref_date:
                    ref_date = str(ref_date)[:10]

                rows.append({
                    "endpoint_name":  endpoint,
                    "indicador":      rec.get("Indicador") or indicador,
                    "reference_date": ref_date,
                    "median":         rec.get("Mediana"),
                    "mean_val":       rec.get("Media"),
                    "std_dev":        rec.get("DesvioPadrao"),
                    "raw":            rec,
                })

            return upsert_rows(self._supabase, "bacen_expectativas", rows,
                               conflict_columns="endpoint_name,indicador,reference_date")

        tasks = []
        for endpoint in EXPECTATIVAS_ENDPOINTS:
            indicators = EXPECTATIVAS_INDICATORS.get(endpoint)
            if indicators:
                for ind in indicators:
                    tasks.append(_fetch_endpoint(endpoint, ind))
            else:
                tasks.append(_fetch_endpoint(endpoint, None))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, int):
                total += r
            else:
                logger.error("Expectativas task error: %s", r)

        logger.info("Expectativas done: total=%d", total)
        return total

    # ------------------------------------------------------------------
    # Orchestrated runs
    # ------------------------------------------------------------------

    async def backfill(self, start: str = "2019-01-01") -> Dict[str, int]:
        """Full historical backfill for all BACEN data from start to today."""
        end = date.today().isoformat()
        logger.info("BACEN backfill: start=%s end=%s", start, end)

        sgs_n, ptax_n, exp_n = await asyncio.gather(
            self.ingest_sgs(start, end),
            self.ingest_ptax(start, end),
            self.ingest_expectativas(start),
        )

        totals = {
            "bacen_sgs":          sgs_n,
            "bacen_ptax":         ptax_n,
            "bacen_expectativas": exp_n,
        }
        logger.info("BACEN backfill done: %s", totals)
        return totals

    async def daily_update(self) -> Dict[str, int]:
        """Incremental update: last 7 days of all BACEN data."""
        end   = date.today()
        start = (end - timedelta(days=7)).isoformat()
        end   = end.isoformat()

        sgs_n, ptax_n, exp_n = await asyncio.gather(
            self.ingest_sgs(start, end),
            self.ingest_ptax(start, end),
            self.ingest_expectativas(start),
        )

        totals = {
            "bacen_sgs":          sgs_n,
            "bacen_ptax":         ptax_n,
            "bacen_expectativas": exp_n,
        }
        logger.info("BACEN daily update done: %s", totals)
        return totals
