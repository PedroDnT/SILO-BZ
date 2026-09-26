"""FNET ingestor — the B3 Fundos.NET document register (backlog B1).

Fetching and parsing are src/fetchers/fnet_fetcher.py. Audit rows go through
src/pipeline/ingest_log under entity ``fnet``:

    doc_type ``register``  one row per delivery-day window run (daily / backfill
                            month); period = the window's start month.
    doc_type ``fund_link`` one row per fund-sweep run.

Two tables:

  * ``fnet_document``          one row per FNET id, from the UNFILTERED
                               delivery-day crawl (the complete list).
  * ``fnet_document_filter``   "FNET returned this id for this filter":
                               tipoFundo 1/2/3 from the per-type crawls, and
                               cnpjFundo from the per-fund sweep. FNET rows
                               carry neither a CNPJ nor a type, so this is the
                               only way either is known — never by name.

The daily run crawls the trailing ``FNET_DAILY_LOOKBACK_DAYS`` delivery days
(default 3) and sweeps a rotating slice of the FII/FIDC registry
(``FNET_SWEEP_SLICES``, default 14: every fund is swept once a fortnight, which
also refreshes the ``status`` of its older documents when they get superseded).
"""

from __future__ import annotations

import asyncio
import logging
import os
import zlib
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence

from src.fetchers.fnet_fetcher import FUND_TYPES, FnetFetcher, parse_documents
from src.pipeline.ingest_log import audited
from src.store.pg_client import get_pg_client, upsert_rows

logger = logging.getLogger(__name__)

TABLE = "fnet_document"
CONFLICT_COLUMNS = "fnet_id"
FILTER_TABLE = "fnet_document_filter"
FILTER_CONFLICT_COLUMNS = "fnet_id,filter_name,filter_value"
LOG_ENTITY = "fnet"
DOC_REGISTER = "register"
DOC_FUND_LINK = "fund_link"

# FNET's own tipoFundo codes, keyed by the registry's entity_type.
_TIPO_BY_ENTITY = {"fii": 1, "fidc": 2}


class FnetBackfillIncomplete(RuntimeError):
    """One or more backfill months failed; each has an ``error`` audit row."""


class FnetSweepIncomplete(RuntimeError):
    """One or more funds in a sweep failed; the sweep's audit row is ``error``.

    ``rows`` is the links stored from the other funds: ``audited`` records it
    as ``rows_upserted`` so the error row does not claim nothing landed.
    """

    def __init__(self, message: str, rows: int = 0):
        super().__init__(message)
        self.rows = rows


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        n = int(raw)
    except ValueError:
        return default
    return n if n >= minimum else default


def _days(start: date, end: date) -> List[date]:
    if end < start:
        raise ValueError(f"end {end} < start {start}")
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _filter_rows(ids: Iterable[int], name: str, value: str) -> List[Dict[str, Any]]:
    return [{"fnet_id": i, "filter_name": name, "filter_value": value} for i in ids]


def sweep_slice(cnpjs: Sequence[str], day: date, slices: int) -> List[str]:
    """The funds swept on ``day``: a stable hash of the CNPJ, modulo ``slices``.

    Stable across runs and machines (crc32, not Python's salted hash), so the
    same fund always falls on the same day of the cycle.
    """
    k = day.toordinal() % slices
    return [c for c in cnpjs if zlib.crc32(c.encode()) % slices == k]


class FnetIngestor:
    """Crawl FNET's register and record which filters each document answers to.

    Example::

        ing = FnetIngestor()
        await ing.daily_update()
        await ing.backfill(date(2026, 8, 1), date(2026, 8, 31))
    """

    def __init__(self, fetcher: Optional[FnetFetcher] = None) -> None:
        self._fetcher = fetcher or FnetFetcher()
        self._pg = get_pg_client()

    # ── storage ──────────────────────────────────────────────────────────

    def _store(self, raw_rows: List[Dict[str, Any]], label: str) -> int:
        rows, dropped = parse_documents(raw_rows)
        if dropped:
            logger.warning("FNET %s: %d row(s) dropped by validation (no id/versao/delivery date)", label, dropped)
        return upsert_rows(self._pg, TABLE, rows, conflict_columns=CONFLICT_COLUMNS)

    def _store_filters(self, rows: List[Dict[str, Any]]) -> int:
        return upsert_rows(self._pg, FILTER_TABLE, rows, conflict_columns=FILTER_CONFLICT_COLUMNS)

    # ── the register: one delivery day at a time ─────────────────────────

    async def ingest_day(self, day: date) -> int:
        """The day's complete register plus its tipoFundo labels. Returns documents stored."""
        label = day.isoformat()
        raw = await self._fetcher.search(day=day)
        n = self._store(raw, label)
        for tipo, name in FUND_TYPES.items():
            typed = await self._fetcher.search(day=day, tipo_fundo=tipo)
            # A typed row the unfiltered crawl did not list means the two
            # queries disagree about the same day; store it rather than lose
            # it, and say so.
            known = {r.get("id") for r in raw}
            extra = [r for r in typed if r.get("id") not in known]
            if extra:
                logger.warning("FNET %s %s: %d id(s) not in the unfiltered crawl; stored", label, name, len(extra))
                n += self._store(extra, f"{label} {name}")
            self._store_filters(_filter_rows(
                (int(r["id"]) for r in typed if r.get("id") is not None), "tipoFundo", str(tipo)))
        logger.info("FNET register %s: %d documents", label, n)
        return n

    async def ingest_days(self, days: Sequence[date]) -> int:
        total = 0
        for d in days:
            total += await self.ingest_day(d)
        return total

    # ── the fund link: cnpjFundo sweeps ──────────────────────────────────

    def registry_funds(self) -> List[str]:
        """FII and FIDC CNPJs from cvm_fund_registry, sorted. The universe the sweep walks."""
        sql = ("SELECT DISTINCT cnpj FROM cvm_fund_registry "
               "WHERE entity_type IN ('fii', 'fidc') ORDER BY cnpj")
        with self._pg.cursor() as cur:
            cur.execute(sql)
            return [r[0] for r in cur.fetchall()]

    async def sweep_funds(self, cnpjs: Sequence[str]) -> int:
        """Every document FNET lists for each fund; records the cnpjFundo link. Returns links stored.

        A fund whose query fails does not abandon the rest of the slice (run
        36101156388 lost ~500 funds to one ReadTimeout): the sweep moves on,
        then raises ``FnetSweepIncomplete`` naming every failed fund, so the
        enclosing ``audited`` still writes an ``error`` row and the run is red.
        """
        links = 0
        failed: List[str] = []
        for cnpj in cnpjs:
            try:
                raw = await self._fetcher.search(cnpj=cnpj)
            except Exception as exc:  # re-raised below, after the other funds
                logger.error("FNET sweep cnpjFundo=%s failed: %r; continuing with the next fund", cnpj, exc)
                failed.append(f"{cnpj}: {exc!r}")
                continue
            if not raw:
                continue
            self._store(raw, f"cnpj {cnpj}")
            links += self._store_filters(_filter_rows(
                (int(r["id"]) for r in raw if r.get("id") is not None), "cnpjFundo", cnpj))
        if failed:
            raise FnetSweepIncomplete(
                f"FNET sweep: {len(failed)} of {len(cnpjs)} fund(s) failed "
                f"({links} links stored from the rest). " + "; ".join(failed),
                rows=links,
            )
        return links

    # ── orchestration ────────────────────────────────────────────────────

    async def daily_update(self) -> Dict[str, int]:
        today = date.today()
        lookback = _env_int("FNET_DAILY_LOOKBACK_DAYS", 3)
        days = _days(today - timedelta(days=lookback - 1), today)
        docs = await audited(
            self._pg, LOG_ENTITY, DOC_REGISTER, lambda: self.ingest_days(days),
            period_year=days[0].year, period_month=days[0].month, upsert=upsert_rows,
        )
        slices = _env_int("FNET_SWEEP_SLICES", 14)
        todays = sweep_slice(self.registry_funds(), today, slices)
        links = await audited(
            self._pg, LOG_ENTITY, DOC_FUND_LINK, lambda: self.sweep_funds(todays),
            period_year=today.year, period_month=today.month, upsert=upsert_rows,
        )
        logger.info("FNET daily: %d documents over %d day(s); %d fund link(s) from %d fund(s)",
                    docs, len(days), links, len(todays))
        return {TABLE: docs, FILTER_TABLE: links}

    async def backfill(self, start: date, end: Optional[date] = None) -> Dict[str, int]:
        """Delivery days ``start..end``, audited one calendar month at a time.

        A month that fails is already recorded as an ``error`` audit row by
        ``audited``; the backfill moves on to the next month instead of
        abandoning the rest of the range, then raises at the end naming every
        failed month, so the run is still red and nothing is swallowed.
        """
        end = end or date.today()
        total = 0
        failed: List[str] = []
        month_start = start
        while month_start <= end:
            nxt = (month_start.replace(day=1) + timedelta(days=32)).replace(day=1)
            month_days = _days(month_start, min(end, nxt - timedelta(days=1)))
            label = f"{month_start.year:04d}-{month_start.month:02d}"
            try:
                total += await audited(
                    self._pg, LOG_ENTITY, DOC_REGISTER,
                    lambda md=month_days: self.ingest_days(md),
                    period_year=month_start.year, period_month=month_start.month, upsert=upsert_rows,
                )
            except Exception as exc:  # recorded by audited(); re-raised below
                logger.error("FNET backfill %s failed: %r; continuing with the next month", label, exc)
                failed.append(f"{label}: {exc!r}")
            month_start = nxt
        if failed:
            raise FnetBackfillIncomplete(
                f"FNET backfill {start}..{end}: {len(failed)} month(s) failed "
                f"({total} documents stored from the rest); re-run the same range. " + "; ".join(failed)
            )
        return {TABLE: total}

    async def sweep_all(self) -> Dict[str, int]:
        """Every FII/FIDC fund in the registry, once. For backfill; about 1.5 s a fund."""
        cnpjs = self.registry_funds()
        today = date.today()
        links = await audited(
            self._pg, LOG_ENTITY, DOC_FUND_LINK, lambda: self.sweep_funds(cnpjs),
            period_year=today.year, period_month=today.month, upsert=upsert_rows,
        )
        return {FILTER_TABLE: links}


async def _main() -> None:
    """The daily FNET refresh, run by daily_ingest.yml as its own step."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    totals: Dict[str, int] = {}
    first_error: Optional[BaseException] = None
    try:
        totals.update(await FnetIngestor().daily_update())
    except Exception as exc:  # the diff queue still runs; re-raised below
        logger.error("FNET register refresh failed: %r", exc)
        first_error = exc
    # B4 slice 1: the restatement-diff queue (its own audit row, fnet / diff).
    from src.pipeline.fnet_diff_pipeline import FnetDiffIngestor
    try:
        totals.update(await FnetDiffIngestor().run())
    except Exception as exc:
        logger.error("FNET diff queue failed: %r", exc)
        first_error = first_error or exc
    logger.info("FNET daily update done: %s", totals)
    if first_error is not None:
        raise first_error


if __name__ == "__main__":
    asyncio.run(_main())
