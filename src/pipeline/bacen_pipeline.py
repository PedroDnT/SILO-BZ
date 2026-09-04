"""
BACEN data ingestor — fetches SGS time series, PTAX exchange rates, and
Expectativas (Focus bulletin) and persists to Supabase.

Fetching is src/fetchers/bacen_fetcher.BacenClient (SGS and Olinda over
httpx); audit rows go through src/pipeline/ingest_log.
"""

import asyncio
import logging
import os
import sys
from datetime import date, datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.fetchers.bacen_fetcher import BacenClient
from src.pipeline.ingest_log import PartialIngestError, audited, describe
from src.store.pg_client import get_pg_client, upsert_rows

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

# Audit rows: one per source per run, written by src/pipeline/ingest_log
# (entity 'bacen'; period = the fetch window's start month — see that module
# for why a trailing window is keyed that way). The registry below is the
# single place the three sources are enumerated: doc_type, landing table,
# and how to run it. Nothing else may zip parallel lists.
LOG_ENTITY = "bacen"

EXPECTATIVAS_ENDPOINTS: List[str] = [
    "ExpectativasMercadoAnuais",
    # NOTE the singular "Expectativa": that is BACEN's actual resource name.
    # "ExpectativasMercadoMensais" does not exist and every fetch against it
    # failed with "Invalid name" — verified against the live OData service
    # document, which lists ExpectativaMercadoMensais.
    "ExpectativaMercadoMensais",
    "ExpectativasMercadoSelic",
    "ExpectativasMercadoInflacao12Meses",
]

# Indicators to filter per endpoint (None = all)
EXPECTATIVAS_INDICATORS: Dict[str, Optional[List[str]]] = {
    "ExpectativasMercadoAnuais":        ["IPCA", "IGP-M", "PIB Total", "Selic"],
    "ExpectativaMercadoMensais":        ["IPCA", "IGP-M"],
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
            # Fatal, like PTAX and Expectativas. This used to log and return
            # 0, and the daily run stayed green with bacen_sgs=0 (2026-09-03,
            # runs 33721538761 and 33798733736). A per-series "no observation
            # in the window" is handled inside the fetcher and is not an
            # exception; anything that reaches here is a broken fetch.
            raise RuntimeError(f"SGS fetch failed: {exc}") from exc

        if not records:
            # Every series empty for the window is possible only for a window
            # with no business day; visible, not silent.
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
                # One path for every currency, USD included: CotacaoMoedaPeriodo
                # serves USD too (verified against the live API), and the
                # dollar-specific helper still goes through python-bcb's
                # M/D/YYYY formatting, which Olinda answers with an empty set.
                records = await self._client.get_ptax_moeda_periodo(currency, start, end)
            except Exception as exc:
                # Fatal for the same reason as Expectativas: a swallowed error
                # here is why bacen_ptax reported 0 rows indefinitely.
                raise RuntimeError(f"PTAX fetch failed currency={currency}: {exc}") from exc

            if not records:
                logger.warning(
                    "PTAX %s returned no rows for %s..%s", currency, start, end
                )
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
        errors = [r for r in results if not isinstance(r, int)]
        for r in results:
            if isinstance(r, int):
                total += r
        if errors:
            # Surface rather than log-and-continue: a partial PTAX ingest that
            # reports success is how the FX series silently stayed empty.
            for err in errors:
                logger.error("PTAX task error: %s", err)
            raise PartialIngestError(
                f"PTAX: {len(errors)} of {len(PTAX_CURRENCIES)} currencies failed; "
                f"first error: {describe(errors[0])}",
                rows=total,
            )

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
                # Deliberately fatal. This used to warn and return 0, so six of
                # seven Focus fetches failed for months while the job reported
                # success and the dashboard rendered a blank chart. A fetch that
                # cannot run is an error, not an empty week.
                raise RuntimeError(
                    f"Expectativas fetch failed {endpoint}/{indicador}: {exc}"
                ) from exc

            if not records:
                # Genuinely empty is allowed (a filter can legitimately match
                # nothing) but must be visible, not silent.
                logger.warning(
                    "Expectativas %s/%s returned no rows for start=%s",
                    endpoint, indicador, start,
                )
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
                    # The forecast horizon. Part of the natural key: one survey
                    # date publishes one forecast per horizon, so keying without
                    # it collapsed ~97% of the payload to an arbitrary survivor.
                    "horizon":        rec.get("DataReferencia"),
                    "median":         rec.get("Mediana"),
                    "mean_val":       rec.get("Media"),
                    "std_dev":        rec.get("DesvioPadrao"),
                    "raw":            rec,
                })

            return upsert_rows(self._supabase, "bacen_expectativas", rows,
                               conflict_columns="endpoint_name,indicador,reference_date,horizon")

        tasks = []
        for endpoint in EXPECTATIVAS_ENDPOINTS:
            indicators = EXPECTATIVAS_INDICATORS.get(endpoint)
            if indicators:
                for ind in indicators:
                    tasks.append(_fetch_endpoint(endpoint, ind))
            else:
                tasks.append(_fetch_endpoint(endpoint, None))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        errors = [r for r in results if not isinstance(r, int)]
        for r in results:
            if isinstance(r, int):
                total += r
        if errors:
            # This is the exact spot the Focus outage hid in: six of seven
            # fetches raised, each was logged and dropped, and the run returned
            # a healthy-looking total from the one endpoint that worked.
            for err in errors:
                logger.error("Expectativas task error: %s", err)
            raise PartialIngestError(
                f"Expectativas: {len(errors)} of {len(tasks)} fetches failed; "
                f"first error: {describe(errors[0])}",
                rows=total,
            )

        logger.info("Expectativas done: total=%d", total)
        return total

    # ------------------------------------------------------------------
    # Orchestrated run
    # ------------------------------------------------------------------

    def _sources(self, start: str, end: str):
        """(doc_type, landing table, factory) — the only enumeration of the three."""
        return (
            ("sgs",          "bacen_sgs",          lambda: self.ingest_sgs(start, end)),
            ("ptax",         "bacen_ptax",         lambda: self.ingest_ptax(start, end)),
            ("expectativas", "bacen_expectativas", lambda: self.ingest_expectativas(start)),
        )

    async def _run_all(self, start: str, end: str, label: str) -> Dict[str, int]:
        """Run the three sources under audit rows; raise if any failed.

        ``return_exceptions=True`` so every source finishes and records
        itself before the run fails. Failures are re-raised as an
        ``ExceptionGroup`` carrying the original exceptions, so run_daily's
        ``exc_info`` prints the real tracebacks; a child cancelled on its
        own is re-raised as the cancellation it is, never folded into a
        failure message.
        """
        window_start = date.fromisoformat(start[:10])
        sources = self._sources(start, end)
        results = await asyncio.gather(
            *(
                audited(
                    self._supabase, LOG_ENTITY, doc_type, factory,
                    period_year=window_start.year, period_month=window_start.month,
                )
                for doc_type, _, factory in sources
            ),
            return_exceptions=True,
        )
        totals: Dict[str, int] = {}
        failures: List[tuple[str, Exception]] = []
        for (doc_type, table, _), res in zip(sources, results):
            if isinstance(res, asyncio.CancelledError):
                raise res
            if isinstance(res, BaseException):
                if not isinstance(res, Exception):
                    raise res
                logger.error("BACEN %s: %s failed", label, doc_type, exc_info=res)
                failures.append((doc_type, res))
                totals[table] = int(getattr(res, "rows", 0) or 0)
            else:
                totals[table] = int(res)
        logger.info("BACEN %s done: %s", label, totals)
        if failures:
            raise ExceptionGroup(
                f"BACEN {label} failed for {len(failures)} source(s) — "
                + "; ".join(f"{d}: {describe(e)}" for d, e in failures),
                [e for _, e in failures],
            )
        return totals

    async def backfill(self, start: str = "2019-01-01") -> Dict[str, int]:
        """Fetch every BACEN source from ``start`` to today and upsert.

        This is the one orchestrated entry point: run_daily calls it with a
        30-day window, run_backfill with the historical start. The audit
        rows tell the two apart by the window's start month.
        """
        end = date.today().isoformat()
        logger.info("BACEN backfill: start=%s end=%s", start, end)
        return await self._run_all(start, end, "backfill")
