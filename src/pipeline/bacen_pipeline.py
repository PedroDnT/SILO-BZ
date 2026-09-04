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

import uuid

from src.fetchers.bacen_fetcher import BacenClient
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

# Audit log. Every ingest writes exactly one cvm_ingest_log row (integrity
# rule 3); until 2026-09-03 the BACEN ingestor wrote none, so the day both
# daily runs landed bacen_sgs=0 there was nothing for DB Health check 1 or
# diagnostic 15 to see. One row per source per run: entity 'bacen',
# doc_type sgs | ptax | expectativas, no period (the window is a trailing
# range, not a filing month). Undated rows are inside check 1's daily
# window, so an error row fails the gate until a later ok row heals it.
LOG_ENTITY = "bacen"
LOG_DOC_TYPES = ("sgs", "ptax", "expectativas")

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
            raise RuntimeError(
                f"PTAX: {len(errors)} of {len(PTAX_CURRENCIES)} currencies failed; "
                f"first error: {errors[0]}"
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
            raise RuntimeError(
                f"Expectativas: {len(errors)} of {len(tasks)} fetches failed; "
                f"first error: {errors[0]}"
            )

        logger.info("Expectativas done: total=%d", total)
        return total

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------

    def _log_start(self, run_id: str, doc_type: str) -> None:
        """Write the 'running' row. Lets a failure propagate — a run that cannot
        record itself must not proceed unrecorded (same stance as ANBIMA)."""
        upsert_rows(
            self._supabase,
            "cvm_ingest_log",
            [{
                "run_id":        run_id,
                "entity":        LOG_ENTITY,
                "doc_type":      doc_type,
                "period_year":   None,
                "period_month":  None,
                "rows_upserted": 0,          # NOT NULL — finish overwrites it
                "status":        "running",
                "started_at":    datetime.now(timezone.utc),
            }],
            conflict_columns="run_id",
        )

    def _log_finish(
        self, run_id: str, doc_type: str, status: str, rows: int,
        error: Optional[str] = None,
    ) -> None:
        # started_at is deliberately NOT sent: ON CONFLICT DO UPDATE sets every
        # column present, and resending it would make every run look
        # instantaneous. The row exists because _log_start succeeded.
        upsert_rows(
            self._supabase,
            "cvm_ingest_log",
            [{
                "run_id":        run_id,
                "entity":        LOG_ENTITY,
                "doc_type":      doc_type,
                "status":        status,
                "rows_upserted": rows,
                "finished_at":   datetime.now(timezone.utc),
                "error_msg":     error,
            }],
            conflict_columns="run_id",
        )

    async def _audited(self, doc_type: str, coro) -> int:
        """Run one source under an audit row: running → ok | error.

        The error row is written BEFORE the exception is re-raised, so the
        failure is in the warehouse even if the process dies right after.
        A failure to write the error row is logged and the original error
        still propagates — the audit must never mask the ingest failure.
        """
        run_id = str(uuid.uuid4())
        try:
            self._log_start(run_id, doc_type)
        except Exception:
            coro.close()  # never awaited; do not leave it dangling
            raise
        try:
            rows = await coro
        except Exception as exc:
            try:
                self._log_finish(run_id, doc_type, "error", 0, error=str(exc)[:2000])
            except Exception as log_exc:  # noqa: BLE001 — must not mask exc
                logger.warning("bacen/%s: could not write error row: %s", doc_type, log_exc)
            raise
        self._log_finish(run_id, doc_type, "ok", int(rows or 0))
        return int(rows or 0)

    async def _run_all(self, start: str, end: str, label: str) -> Dict[str, int]:
        """Run the three sources under audit rows, then raise if any failed.

        return_exceptions=True so every source finishes and writes its own
        row before the run fails; plain gather would propagate the first
        error while the other two were still mid-flight, and their rows
        might never be written.
        """
        results = await asyncio.gather(
            self._audited("sgs", self.ingest_sgs(start, end)),
            self._audited("ptax", self.ingest_ptax(start, end)),
            self._audited("expectativas", self.ingest_expectativas(start)),
            return_exceptions=True,
        )
        totals: Dict[str, int] = {}
        failures: List[str] = []
        for doc_type, table, res in zip(
            LOG_DOC_TYPES, ("bacen_sgs", "bacen_ptax", "bacen_expectativas"), results,
        ):
            if isinstance(res, BaseException):
                failures.append(f"{doc_type}: {res}")
                totals[table] = 0
            else:
                totals[table] = int(res)
        logger.info("BACEN %s done: %s", label, totals)
        if failures:
            raise RuntimeError(
                f"BACEN {label} failed for {len(failures)} source(s) — " + "; ".join(failures)
            )
        return totals

    # ------------------------------------------------------------------
    # Orchestrated runs
    # ------------------------------------------------------------------

    async def backfill(self, start: str = "2019-01-01") -> Dict[str, int]:
        """Full historical backfill for all BACEN data from start to today."""
        end = date.today().isoformat()
        logger.info("BACEN backfill: start=%s end=%s", start, end)
        return await self._run_all(start, end, "backfill")

    async def daily_update(self) -> Dict[str, int]:
        """Incremental update: last 7 days of all BACEN data."""
        end   = date.today()
        start = (end - timedelta(days=7)).isoformat()
        end   = end.isoformat()
        return await self._run_all(start, end, "daily update")
