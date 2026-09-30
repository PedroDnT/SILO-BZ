"""Rates and global market data: DI1 futures, B3 reference curves, UST, Brent, OFR FSI.

Six sources, one audit entity (``market``), one row of ``cvm_ingest_log``
per slice. Sources, coverage and point-in-time rules:
docs/reference/research/dustin_br_data_sources.md.

    doc_type           table                   slice
    b3_price_report    b3_futures_settlement   one B3 session
    b3_reference_rate  b3_reference_rate       one B3 session
    us_treasury        mkt_series              one calendar year
    eia_brent          mkt_series              one date window
    ofr_fsi            mkt_series              one fetch (window-filtered)
    cboe_vix           mkt_series              one fetch (window-filtered), LICENSED ONLY

Cboe's terms of use require its advance approval and a signed licence for
any use of the data on its website (research doc §5), and this warehouse
ingests nothing that needs a licence. So VIX runs only where
``CBOE_VIX_LICENSED=1``: the daily run skips it otherwise, and a backfill
refuses it. Set that only once a licence is signed.

The audit entity is NOT ``b3``: api.coverage() reads the newest ``b3`` success
as COTAHIST's freshness, and a DI1 run must never answer for the quote tape.

A B3 date that is not a session answers with an empty archive and is logged
``skipped``. Every other failure writes an ``error`` row and fails the run at
the end — after the other sources have had their turn.

A value that changes on re-fetch is counted and written onto the ``ok`` audit
row ("revised N stored observations"), so a publisher's correction is visible
instead of silently overwriting what research may already have used.

    python -m src.pipeline.market_pipeline                      # daily window
    python -m src.pipeline.market_pipeline --backfill --sources b3_reference_rate \\
        --start 2008-01-01 --end 2008-12-31
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from uuid import uuid4

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.fetchers.b3_pesquisapregao_fetcher import B3FileNotPublished, B3PesquisaPregaoFetcher
from src.fetchers.global_market_fetcher import GlobalMarketFetcher
from src.parsers import b3_price_report as pr
from src.parsers import b3_taxa_swap as ts
from src.parsers import global_market as gm
from src.pipeline import ingest_log
from src.store.pg_client import get_pg_client, upsert_rows

logger = logging.getLogger(__name__)

LOG_ENTITY = "market"
SOURCES: Tuple[str, ...] = (
    "b3_price_report", "b3_reference_rate", "us_treasury", "eia_brent", "ofr_fsi", "cboe_vix",
)
# First date each source has anything to give (measured, research doc §3/§6).
EARLIEST = {
    "b3_price_report": date(2018, 1, 2),
    "b3_reference_rate": date(2008, 1, 2),
}


def vix_licensed() -> bool:
    """True only where the operator holds a signed Cboe licence (module docstring)."""
    return os.getenv("CBOE_VIX_LICENSED", "").strip() == "1"


def default_sources() -> Tuple[str, ...]:
    return tuple(s for s in SOURCES if s != "cboe_vix" or vix_licensed())


def _env_list(name: str, default: Sequence[str]) -> Tuple[str, ...]:
    raw = os.getenv(name, "")
    items = tuple(x.strip() for x in raw.split(",") if x.strip())
    return items or tuple(default)


def weekdays(start: date, end: date) -> List[date]:
    """Mon–Fri in [start, end]. B3 has no weekend session, so a weekend is not
    asked for; a weekday holiday is asked for and comes back ``skipped``."""
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


class MarketIngestor:
    def __init__(
        self,
        b3_fetcher: Optional[B3PesquisaPregaoFetcher] = None,
        market_fetcher: Optional[GlobalMarketFetcher] = None,
        client: Any = None,
    ) -> None:
        self._b3 = b3_fetcher or B3PesquisaPregaoFetcher()
        self._mkt = market_fetcher or GlobalMarketFetcher()
        self._supabase = client if client is not None else get_pg_client()
        self.futures_roots = _env_list("B3_FUTURES_ROOTS", pr.DEFAULT_ROOTS)
        self.curves = _env_list("B3_REFERENCE_CURVES", ts.DEFAULT_CURVES)
        self.failures: List[str] = []
        self.skips: List[str] = []

    # ── audit ────────────────────────────────────────────────────────────
    async def _slice(
        self, doc_type: str, label: str, period: Optional[date],
        work: Callable[[], Awaitable[Tuple[int, Optional[str]]]],
    ) -> int:
        """Run one slice under a running → ok | skipped | error audit row.

        ``work`` returns ``(rows, note)``; a note (revisions, a shortfall) is
        recorded on the ok row. Exceptions are recorded and collected, not
        re-raised, so one bad session does not abandon the rest; ``run``
        fails the process at the end if any slice failed.
        """
        run_id = str(uuid4())
        year = period.year if period else None
        month = period.month if period else None
        try:
            ingest_log.start(self._supabase, run_id, LOG_ENTITY, doc_type,
                             period_year=year, period_month=month, upsert=upsert_rows)
        except Exception as exc:  # noqa: BLE001 — audit must not stop ingest
            logger.warning("%s: could not write the running row (%s)", label, ingest_log.describe(exc))

        status, rows, error = "error", 0, None
        try:
            rows, note = await work()
            status, error = "ok", note
        except (B3FileNotPublished, ts.TaxaSwapStaleFile) as exc:
            # No file of its own for that date: an empty archive, or an earlier
            # session's file republished under it. Nothing is stored.
            status, error = "skipped", ingest_log.describe(exc)
            self.skips.append(label)
            logger.info("%s: not published for that date — skipped (%s)", label, error)
        except Exception as exc:  # noqa: BLE001 — recorded, collected, raised by run()
            error = ingest_log.describe(exc)
            self.failures.append(f"{label}: {error}")
            logger.error("%s failed: %s", label, error, exc_info=exc)
        except BaseException as exc:
            # Cancellation or a job timeout: record it, then let it propagate.
            error = ingest_log.describe(exc)
            raise
        finally:
            try:
                ingest_log.finish(self._supabase, run_id, LOG_ENTITY, doc_type, status=status,
                                  rows=rows, error=error, period_year=year, period_month=month,
                                  upsert=upsert_rows)
            except Exception as exc:  # noqa: BLE001 — must not mask the outcome
                logger.warning("%s: could not write the %s row (%s)", label, status, ingest_log.describe(exc))
        return rows

    # ── B3 files ─────────────────────────────────────────────────────────
    async def ingest_price_report(self, session: date) -> int:
        async def work():
            name, xml = await self._b3.fetch_price_report(session)
            rows, counts = pr.parse_price_report(xml, session=session, roots=self.futures_roots, origin=name)
            if not rows:
                # A published report with no contract of a configured root is a
                # source change (or a wrong root), not a quiet day.
                raise pr.PriceReportFormatError(f"{name}: no {self.futures_roots} contract in the report")
            n = upsert_rows(self._supabase, pr.TABLE, rows, conflict_columns=",".join(pr.CONFLICT))
            note = None
            if counts["dropped_invalid"] or counts["dropped_non_outright"]:
                note = (f"dropped {counts['dropped_invalid']} invalid, "
                        f"{counts['dropped_non_outright']} non-outright tickers")
            return n, note
        return await self._slice("b3_price_report", f"price report {session}", session, work)

    async def ingest_reference_rates(self, session: date) -> int:
        async def work():
            text = await self._b3.fetch_taxa_swap(session)
            rows, counts = ts.parse_taxa_swap(text, session=session, curves=self.curves,
                                              origin=f"TaxaSwap {session}")
            n = upsert_rows(self._supabase, ts.TABLE, rows, conflict_columns=",".join(ts.CONFLICT))
            note = f"dropped {counts['dropped_invalid']} invalid vertices" if counts["dropped_invalid"] else None
            return n, note
        return await self._slice("b3_reference_rate", f"reference rates {session}", session, work)

    # ── mkt_series ───────────────────────────────────────────────────────
    def _revisions(self, rows: List[Dict[str, Any]]) -> int:
        """How many incoming rows change a value already stored."""
        if not rows:
            return 0
        source = rows[0]["source"]
        series = sorted({r["series_id"] for r in rows})
        lo = min(r["observation_date"] for r in rows)
        hi = max(r["observation_date"] for r in rows)
        with self._supabase.cursor() as cur:
            cur.execute(
                "SELECT series_id, observation_date, value FROM mkt_series "
                "WHERE source = %s AND series_id = ANY(%s) AND observation_date BETWEEN %s AND %s",
                (source, series, lo, hi),
            )
            stored = {(s, d): v for s, d, v in cur.fetchall()}
        return sum(
            1 for r in rows
            if (r["series_id"], r["observation_date"]) in stored
            and stored[(r["series_id"], r["observation_date"])] != r["value"]
        )

    def _store_series(self, rows: List[Dict[str, Any]], counts: Dict[str, int]) -> Tuple[int, Optional[str]]:
        revised = self._revisions(rows)
        n = upsert_rows(self._supabase, gm.TABLE, rows, conflict_columns=",".join(gm.CONFLICT))
        notes = []
        if revised:
            notes.append(f"revised {revised} stored observations")
        if counts.get("dropped_invalid"):
            notes.append(f"dropped {counts['dropped_invalid']} implausible observations")
        return n, "; ".join(notes) or None

    async def ingest_treasury_year(self, year: int) -> int:
        async def work():
            rows, counts = gm.parse_treasury_par_csv(await self._mkt.fetch_treasury_year(year),
                                                     origin=f"Treasury {year}")
            if not rows:
                raise gm.MarketFormatError(f"Treasury {year}: no observation")
            return self._store_series(rows, counts)
        return await self._slice("us_treasury", f"Treasury par {year}", date(year, 1, 1), work)

    async def ingest_cboe_vix(self, start: date, end: date) -> int:
        async def work():
            rows, counts = gm.parse_cboe_vix_csv(await self._mkt.fetch_cboe_vix())
            rows = [r for r in rows if start <= r["observation_date"] <= end]
            return self._store_series(rows, counts)
        return await self._slice("cboe_vix", f"Cboe VIX {start}..{end}", start, work)

    async def ingest_eia_brent(self, start: date, end: date) -> int:
        async def work():
            rows, counts = gm.parse_eia_spot(await self._mkt.fetch_eia_brent(start, end))
            return self._store_series(rows, counts)
        return await self._slice("eia_brent", f"EIA Brent {start}..{end}", start, work)

    def _superseded_first_releases(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Stored OFR values that ``rows`` would overwrite, as first-release rows.

        OFR says the FSI is not revised once estimated, except as its revision
        workbook lists. When a fetch still brings a changed value, the stored
        one is what was public first, so it is kept under the first-release
        id; a date that already has one (OFR's record, or an earlier change)
        keeps it. Point-in-time research reads first releases first.
        """
        current = [r for r in rows if r["series_id"] in gm.OFR_FIRST_RELEASE]
        if not current:
            return []
        ids = sorted({*gm.OFR_FIRST_RELEASE, *gm.OFR_FIRST_RELEASE.values()})
        lo = min(r["observation_date"] for r in current)
        hi = max(r["observation_date"] for r in current)
        with self._supabase.cursor() as cur:
            cur.execute(
                "SELECT series_id, observation_date, value FROM mkt_series "
                "WHERE source = %s AND series_id = ANY(%s) AND observation_date BETWEEN %s AND %s",
                (gm.SOURCE_OFR, ids, lo, hi),
            )
            stored = {(s, d): v for s, d, v in cur.fetchall()}
        incoming = {(r["series_id"], r["observation_date"]) for r in rows}
        kept = []
        for r in current:
            old = stored.get((r["series_id"], r["observation_date"]))
            first = (gm.OFR_FIRST_RELEASE[r["series_id"]], r["observation_date"])
            if old is not None and old != r["value"] and first not in stored and first not in incoming:
                kept.append({**r, "series_id": first[0], "value": old})
        return kept

    async def ingest_ofr_fsi(self, start: date, end: date, *, revisions: bool = False) -> int:
        """fsi.csv within [start, end]; with ``revisions``, also the first
        releases from OFR's revision workbook (backfill only: its URL moves
        with every new revision, and the daily window never reaches back to
        the dates it covers)."""
        async def work():
            rows, counts = gm.parse_ofr_fsi_csv(await self._mkt.fetch_ofr_fsi())
            if revisions:
                first, _ = gm.parse_ofr_fsi_revisions(await self._mkt.fetch_ofr_fsi_revisions())
                rows = rows + first
            rows = [r for r in rows if start <= r["observation_date"] <= end]
            if not rows:
                raise gm.MarketFormatError(f"OFR FSI: no observation in {start}..{end}")
            kept = self._superseded_first_releases(rows)
            n, note = self._store_series(rows + kept, counts)
            if kept:
                note = "; ".join(filter(None, [note, f"kept {len(kept)} superseded values as first releases"]))
            return n, note
        return await self._slice("ofr_fsi", f"OFR FSI {start}..{end}", start, work)

    # ── orchestration ────────────────────────────────────────────────────
    async def backfill(self, sources: Iterable[str], start: date, end: date) -> Dict[str, int]:
        sources = list(sources)
        unknown = sorted(set(sources) - set(SOURCES))
        if unknown or not sources:
            raise ValueError(f"unknown market source(s) {unknown or '(none)'}; choose from {SOURCES}")
        if "cboe_vix" in sources and not vix_licensed():
            raise ValueError("cboe_vix needs a signed Cboe licence; set CBOE_VIX_LICENSED=1 only once "
                             "one exists (docs/reference/research/dustin_br_data_sources.md §5)")
        if end < start:
            raise ValueError(f"end {end} < start {start}")
        # A session that has not happened yet is not a request worth making.
        end = min(end, datetime.now(timezone.utc).date())
        totals: Dict[str, int] = {}
        for source in sources:
            lo = max(start, EARLIEST.get(source, start))
            n = 0
            if source == "b3_price_report":
                for d in weekdays(lo, end):
                    n += await self.ingest_price_report(d)
            elif source == "b3_reference_rate":
                for d in weekdays(lo, end):
                    n += await self.ingest_reference_rates(d)
            elif source == "us_treasury":
                for year in range(lo.year, end.year + 1):
                    n += await self.ingest_treasury_year(year)
            elif source == "cboe_vix":
                n += await self.ingest_cboe_vix(lo, end)
            elif source == "eia_brent":
                n += await self.ingest_eia_brent(lo, end)
            elif source == "ofr_fsi":
                n += await self.ingest_ofr_fsi(lo, end, revisions=True)
            totals[source] = n
        return totals

    async def daily_update(self, today: Optional[date] = None) -> Dict[str, int]:
        """The trailing window of every source.

        B3: the last ``MARKET_DAILY_LOOKBACK_DAYS`` (default 7) calendar days,
        so a missed night heals. Treasury: this year's file (and last year's
        in the first week of January). EIA: 45 days, because EIA publishes
        weekly and revises. OFR: 30 days, so an older date is never
        re-fetched and what was first published stays stored. Cboe: 30
        days, only where licensed.
        """
        today = today or datetime.now(timezone.utc).date()
        lookback = int(os.getenv("MARKET_DAILY_LOOKBACK_DAYS", "7"))
        b3_start = today - timedelta(days=lookback - 1)
        totals = await self.backfill(("b3_price_report", "b3_reference_rate"), b3_start, today)
        years = {today.year} | ({today.year - 1} if today.timetuple().tm_yday <= 7 else set())
        totals["us_treasury"] = 0
        for year in sorted(years):
            totals["us_treasury"] += await self.ingest_treasury_year(year)
        totals["eia_brent"] = await self.ingest_eia_brent(today - timedelta(days=45), today)
        totals["ofr_fsi"] = await self.ingest_ofr_fsi(today - timedelta(days=30), today)
        if vix_licensed():
            totals["cboe_vix"] = await self.ingest_cboe_vix(today - timedelta(days=30), today)
        else:
            logger.info("Cboe VIX not fetched: no licence (CBOE_VIX_LICENSED unset)")
        return totals


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="DI1 futures, B3 reference curves, UST, Brent, OFR FSI")
    p.add_argument("--backfill", action="store_true", help="load --start..--end instead of the daily window")
    p.add_argument("--sources", default=",".join(default_sources()),
                   help=f"comma-separated subset of {', '.join(SOURCES)} (cboe_vix only where licensed)")
    p.add_argument("--start", help="first date (ISO), backfill only")
    p.add_argument("--end", help="last date (ISO, default today), backfill only")
    return p.parse_args(argv)


async def run(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    ingestor = MarketIngestor()
    if args.backfill:
        if not args.start:
            raise SystemExit("--backfill needs --start")
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end) if args.end else datetime.now(timezone.utc).date()
        sources = [s.strip() for s in args.sources.split(",") if s.strip()]
        totals = await ingestor.backfill(sources, start, end)
    else:
        totals = await ingestor.daily_update()
    logger.info("market ingest done: %s; %d skipped slice(s)", totals, len(ingestor.skips))
    if ingestor.failures:
        logger.error("market ingest FAILED for %d slice(s):", len(ingestor.failures))
        for f in ingestor.failures:
            logger.error("  %s", f)
        return 1
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    raise SystemExit(asyncio.run(run()))
