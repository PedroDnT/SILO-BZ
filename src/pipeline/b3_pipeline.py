"""B3 COTAHIST ingest — fetch public quotation zips, parse register 01, upsert.

Landing table: b3_cotahist. No ticker↔CNPJ match here (deferred).

    ingestor = B3Ingestor()
    await ingestor.daily_update()          # last N calendar days of daily zips
    await ingestor.backfill(start_year=2019)  # yearly zips
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from src.fetchers.b3_bdi_fetcher import B3BdiEmpty, B3BdiFetcher
from src.fetchers.b3_fetcher import B3CotahistFetcher, B3CotahistNotFound
from src.parsers import b3_bdi as bdi
from src.parsers.cotahist import CONFLICT, TABLE, batched, parse_cotahist_bytes
from src.pipeline import ingest_b3_lending as lending
from src.store.pg_client import get_pg_client, upsert_rows
from src.pipeline import ingest_log

logger = logging.getLogger(__name__)

_UPSERT_BATCH = 5000


class B3Ingestor:
    def __init__(
        self,
        fetcher: Optional[B3CotahistFetcher] = None,
        bdi_fetcher: Optional[B3BdiFetcher] = None,
    ) -> None:
        self._fetcher = fetcher or B3CotahistFetcher()
        self._bdi = bdi_fetcher or B3BdiFetcher()
        self._supabase = get_pg_client()
        self._doc_type_of: Dict[str, str] = {}

    def _lookback_days(self) -> int:
        raw = os.getenv("B3_DAILY_LOOKBACK_DAYS", "7").strip()
        try:
            n = int(raw)
        except ValueError:
            return 7
        return n if n >= 1 else 7

    # Audit rows go through src/pipeline/ingest_log (the one writer). Both
    # calls are best-effort: the audit table must not be able to stop ingest,
    # and a failed write is logged, never swallowed. The doc_type is remembered
    # per run so the finish upsert can INSERT a keyed row if the start never
    # landed.
    def _log_start(self, run_id: str, doc_type: str, year: Optional[int], month: Optional[int]) -> None:
        self._doc_type_of[run_id] = doc_type
        try:
            ingest_log.start(self._supabase, run_id, "b3", doc_type,
                             period_year=year, period_month=month, upsert=upsert_rows)
        except Exception as exc:  # noqa: BLE001 — audit must not stop ingest
            logger.warning("ingest_log start failed: %s", ingest_log.describe(exc))

    def _log_finish(
        self,
        run_id: str,
        rows: int,
        error: Optional[str] = None,
        *,
        skipped: bool = False,
    ) -> None:
        status = "skipped" if skipped else ("error" if error else "ok")
        try:
            ingest_log.finish(self._supabase, run_id, "b3", self._doc_type_of.get(run_id, "unknown"),
                              status=status, rows=rows, error=error, upsert=upsert_rows)
        except Exception as exc:  # noqa: BLE001 — audit must not mask the outcome
            logger.warning("ingest_log finish failed: %s", ingest_log.describe(exc))

    def _upsert(self, rows: List[Dict[str, Any]]) -> int:
        total = 0
        for batch in batched(rows, _UPSERT_BATCH):
            total += upsert_rows(
                self._supabase,
                TABLE,
                batch,
                conflict_columns=",".join(CONFLICT),
            )
        return total

    async def ingest_daily(self, session: date) -> int:
        """Fetch one session's daily zip and upsert. 404 → skipped (returns 0)."""
        run_id = str(uuid4())
        self._log_start(run_id, "cotahist_daily", session.year, session.month)
        label = session.isoformat()
        try:
            payload = await self._fetcher.fetch_daily(session)
        except B3CotahistNotFound as exc:
            logger.info("B3 COTAHIST daily %s not published — skipped", label)
            self._log_finish(run_id, 0, ingest_log.describe(exc), skipped=True)
            return 0
        except Exception as exc:
            logger.error("B3 COTAHIST daily %s fetch failed: %s", label, exc)
            self._log_finish(run_id, 0, ingest_log.describe(exc))
            raise

        try:
            rows = parse_cotahist_bytes(payload, origin=label)
            n = self._upsert(rows)
        except Exception as exc:
            self._log_finish(run_id, 0, ingest_log.describe(exc))
            raise

        self._log_finish(run_id, n)
        logger.info("B3 COTAHIST daily %s upserted %d rows", label, n)
        return n

    async def ingest_year(self, year: int) -> int:
        """Fetch one yearly zip and upsert. 404 → skipped (returns 0)."""
        run_id = str(uuid4())
        self._log_start(run_id, "cotahist_yearly", year, None)
        try:
            payload = await self._fetcher.fetch_year(year)
        except B3CotahistNotFound as exc:
            logger.info("B3 COTAHIST year %s not published — skipped", year)
            self._log_finish(run_id, 0, ingest_log.describe(exc), skipped=True)
            return 0
        except Exception as exc:
            logger.error("B3 COTAHIST year %s fetch failed: %s", year, exc)
            self._log_finish(run_id, 0, ingest_log.describe(exc))
            raise

        try:
            rows = parse_cotahist_bytes(payload, origin=str(year))
            n = self._upsert(rows)
        except Exception as exc:
            self._log_finish(run_id, 0, ingest_log.describe(exc))
            raise

        self._log_finish(run_id, n)
        logger.info("B3 COTAHIST year %s upserted %d rows", year, n)
        return n

    def _traded_issuers(self, lookback_days: int = 400) -> List[str]:
        """B3 issuing-company codes for tickers that actually printed recently.

        The corporate-events endpoint is one request per issuer and B3 lists
        ~3,500 companies, most of which never trade. Deriving the list from our
        own tape keeps the daily sweep to the universe we actually serve
        (a few hundred issuers) instead of hammering B3 for shells.

        The issuing code is *usually* the ticker's first four characters
        (PETR4 -> PETR). Tickers shorter than four characters cannot yield
        one and are skipped rather than padded. That prefix is not always
        B3's listed-company catalog key (ADMF3 trades as B100 S.A.); those
        codes come back as ``B3SupplementEmpty`` and are not slice errors.
        """
        sql = """
            SELECT DISTINCT left(codneg, 4) AS issuer
              FROM b3_cotahist
             WHERE tpmerc = '010'
               AND length(codneg) >= 4
               AND trade_date > (SELECT max(trade_date) FROM b3_cotahist) - %s
             ORDER BY issuer
        """
        with self._supabase.cursor() as cur:
            cur.execute(sql, (lookback_days,))
            return [r[0] for r in cur.fetchall() if r and r[0]]

    async def ingest_corporate_events(
        self,
        issuers: Optional[List[str]] = None,
        lookback_days: int = 400,
    ) -> int:
        """Fetch published corporate events for the traded universe.

        One request per issuer, so a failure on ONE issuer must not abandon
        the sweep — but it must not vanish either. Transport/parse failures
        are counted and the run is logged as an error when any occurred,
        with the count and a sample in the message. An empty supplement
        body is different: B3 is saying that issuing code is not in the
        listed-companies catalog (DB Health #6: 35/2153 empty, first ADMF,
        after 11,632 rows had already been upserted). Those are skipped,
        not fabricated, and do not fail the slice when any sibling returned
        a body. An all-empty sweep is still an error — that is the
        malformed-token case.
        """
        from src.fetchers.b3_corporate_events_fetcher import (
            B3CorporateEventsFetcher,
            B3SupplementEmpty,
        )
        from src.pipeline.ingest_b3_events import ingest_b3_corporate_events

        run_id = str(uuid4())
        self._log_start(run_id, "corporate_events", None, None)
        try:
            codes = issuers if issuers is not None else self._traded_issuers(lookback_days)
            if not codes:
                self._log_finish(run_id, 0, skipped=True)
                logger.info("B3 corporate events: no traded issuers found, skipped")
                return 0

            fetcher = B3CorporateEventsFetcher()
            rows: List[Dict[str, Any]] = []
            failures: List[str] = []
            missing: List[str] = []
            fetched = 0
            for code in codes:
                try:
                    rows.extend(fetcher.fetch_events(code))
                    fetched += 1
                except B3SupplementEmpty:
                    missing.append(code)
                except Exception as exc:  # noqa: BLE001 - counted, then reported
                    failures.append(f"{code}: {exc}")

            total = ingest_b3_corporate_events(self._supabase, rows) if rows else 0

            if missing:
                logger.warning(
                    "B3 corporate events: %d/%d issuers have no listed-company "
                    "supplement (first: %s)",
                    len(missing),
                    len(codes),
                    ", ".join(missing[:8]),
                )

            if failures:
                # Partial success is still a failure to report: silence here
                # would let an issuer rot out of the event table unnoticed.
                msg = (
                    f"{len(failures)}/{len(codes)} issuers failed; "
                    f"first: {failures[0][:200]}"
                )
                self._log_finish(run_id, total, error=msg)
                logger.warning("B3 corporate events partial: %s", msg)
            elif fetched == 0:
                # Every issuer returned empty — the path token is wrong or
                # B3 is serving empty bodies wholesale. Same failure mode as
                # a malformed GET, which used to look like a dead endpoint.
                msg = (
                    f"all {len(codes)} issuers returned an empty supplement "
                    f"body; first: {missing[0] if missing else '?'}"
                )
                self._log_finish(run_id, total, error=msg)
                logger.error("B3 corporate events: %s", msg)
            else:
                self._log_finish(run_id, total)
            logger.info(
                "B3 corporate events: %d rows from %d issuers "
                "(%d failed, %d no supplement)",
                total, len(codes), len(failures), len(missing),
            )
            return total
        except Exception as exc:
            self._log_finish(run_id, 0, error=ingest_log.describe(exc))
            raise


    # ── B3 BDI: securities lending, investor flow, free float, instruments ──
    #
    # These four are on a clock the rest of this class is not: B3 keeps ~21
    # business days and then the session is unrecoverable. Every one of them
    # therefore reports what it MEANT to fetch against what B3 actually
    # delivered, because the export answers an over-wide window with HTTP 200
    # and a silently truncated result set.

    async def _ingest_bdi_span(
        self,
        *,
        doc_type: str,
        b3_table: str,
        parse,
        upsert,
        targets: List[date],
        date_field: str,
    ) -> int:
        """Fetch one BDI table over [min(targets), max(targets)] and upsert.

        One ranged request instead of one per session: B3 supports it, and it
        is the difference between 1 and 21 trips through Cloudflare on the
        first run of a fresh database.
        """
        if not targets:
            return 0
        run_id = str(uuid4())
        start, end = targets[0], targets[-1]
        self._log_start(run_id, doc_type, start.year, start.month)
        label = f"{b3_table} {start.isoformat()}..{end.isoformat()}"
        try:
            text = await self._bdi.fetch_table(b3_table, start, end)
        except B3BdiEmpty as exc:
            # Outside retention, or none of these were sessions. Not an error —
            # but if it keeps happening the staleness check must escalate it,
            # because for these tables an unfetched session never comes back.
            logger.info("B3 BDI %s returned no rows — skipped", label)
            self._log_finish(run_id, 0, ingest_log.describe(exc), skipped=True)
            return 0
        except Exception as exc:
            logger.error("B3 BDI %s fetch failed: %s", label, exc)
            self._log_finish(run_id, 0, ingest_log.describe(exc))
            raise

        try:
            rows = parse(text)
            n = upsert(self._supabase, rows)
            delivered, missing = bdi.reconcile_span(rows, date_field, targets)
        except Exception as exc:
            self._log_finish(run_id, 0, ingest_log.describe(exc))
            raise

        if missing:
            # A 200 is not evidence the span arrived. Record the shortfall on
            # the audit row rather than letting the run look clean while the
            # series quietly has holes in it.
            msg = (
                f"B3 delivered {len(delivered)}/{len(targets)} requested sessions; "
                f"missing {', '.join(d.isoformat() for d in missing[:8])}"
                f"{' …' if len(missing) > 8 else ''}"
            )
            # ...but a shortfall confined to the NEWEST session is B3 not having
            # published yet, not a hole. These tables publish on their own lags:
            # verified 2026-09-17 03:36 BRT, BTBTrade had 2026-09-16 (40,021
            # rows) while BTBLendingOpenPosition for the same session did not
            # exist yet. The daily cron runs at 03:03 BRT and always re-requests
            # the newest two sessions, so filing that as an error made DB Health
            # red EVERY morning over a gap the next run heals by itself — and a
            # gate that cries missing-data at a healthy warehouse is the false
            # alarm the health script exists to avoid.
            #
            # Only the newest session gets this benefit. A session missing from
            # anywhere older is the silent clamp, or a real hole, and stays an
            # error: it has had a full publication cycle and did not arrive.
            not_published_yet = missing == [targets[-1]]
            if not_published_yet:
                logger.info("B3 BDI %s: %s — newest session, not published yet", label, msg)
                self._log_finish(run_id, n, msg, skipped=True)
            else:
                logger.warning("B3 BDI %s: %s", label, msg)
                self._log_finish(run_id, n, error=msg)
        else:
            self._log_finish(run_id, n)
        logger.info("B3 BDI %s upserted %d rows over %d sessions", label, n, len(delivered))
        return n

    async def ingest_lending(self) -> Dict[str, int]:
        """Short balances and lending rates for every retrievable missing session."""
        totals: Dict[str, int] = {}
        targets = lending.sessions_to_fetch(
            self._supabase, bdi.TABLE_OPEN_POSITION, "trade_date"
        )
        totals[bdi.TABLE_OPEN_POSITION] = await self._ingest_bdi_span(
            doc_type="lending_open_position",
            b3_table="BTBLendingOpenPosition",
            parse=lambda t: bdi.parse_lending_open_position(t, origin="daily"),
            upsert=lending.upsert_open_positions,
            targets=targets,
            date_field="trade_date",
        )

        rate_targets = lending.sessions_to_fetch(
            self._supabase, bdi.TABLE_LENDING_RATE, "trade_date"
        )
        totals[bdi.TABLE_LENDING_RATE] = await self._ingest_bdi_span(
            doc_type="lending_rate",
            b3_table="BTBLoanBalance",
            parse=lambda t: bdi.parse_lending_rate(t, origin="daily"),
            upsert=lending.upsert_lending_rates,
            targets=rate_targets,
            date_field="trade_date",
        )
        return totals

    async def ingest_lending_trades(self) -> int:
        """Individual lending trades, ONE REQUEST PER SESSION.

        Not a ranged fetch, and this is not an optimisation choice. BTBTrade
        IGNORES `FinalDate`: verified 2026-09-16, asking for 2026-09-08..09-11
        returns only 08/09, and 09-10..09-11 returns only 10/09 — byte-for-byte
        the same body as the single day. `_ingest_bdi_span` would therefore
        request the whole window, receive one session, and (correctly) log the
        other twenty as a shortfall on every run, forever.

        Each session is its own audit row, so a single bad day is visible as
        one skipped/errored slice instead of poisoning the whole window. A
        failure on one session does not abandon the rest, but it is counted
        and reported — the sessions behind it are the ones about to age out.
        """
        targets = lending.sessions_to_fetch(
            self._supabase, bdi.TABLE_LENDING_TRADE, "trade_date"
        )
        # Newest first: an older session is closer to ageing out, but a run
        # that never reaches today leaves the freshest data missing, and the
        # window is wide enough to come back for the rest tomorrow.
        targets = sorted(targets, reverse=True)[:lending.MAX_TRADE_SESSIONS_PER_RUN]

        total = 0
        failures: List[str] = []
        for session in targets:
            run_id = str(uuid4())
            self._log_start(run_id, "lending_trade", session.year, session.month)
            try:
                text = await self._bdi.fetch_table("BTBTrade", session)
            except B3BdiEmpty as exc:
                self._log_finish(run_id, 0, ingest_log.describe(exc), skipped=True)
                continue
            except Exception as exc:  # noqa: BLE001 — counted, reported below
                self._log_finish(run_id, 0, ingest_log.describe(exc))
                failures.append(f"{session.isoformat()}: {exc}")
                continue
            try:
                rows = bdi.parse_lending_trade(text, origin=session.isoformat())
                # The export is single-session, so anything else in the body
                # means B3 answered a different day than the one asked for.
                wrong = {r["trade_date"] for r in rows} - {session}
                if wrong:
                    raise RuntimeError(
                        f"BTBTrade for {session} returned sessions "
                        f"{sorted(d.isoformat() for d in wrong)}"
                    )
                n = lending.upsert_lending_trades(self._supabase, rows)
            except Exception as exc:  # noqa: BLE001 — counted, reported below
                self._log_finish(run_id, 0, ingest_log.describe(exc))
                failures.append(f"{session.isoformat()}: {exc}")
                continue
            self._log_finish(run_id, n)
            total += n
            logger.info("B3 lending trades %s: %d rows", session, n)

        if failures and total == 0 and targets:
            raise RuntimeError(
                f"B3 lending trades: all {len(targets)} sessions failed; "
                f"first: {failures[0][:200]}"
            )
        if failures:
            logger.warning("B3 lending trades: %d/%d sessions failed; first: %s",
                           len(failures), len(targets), failures[0][:200])
        return total

    async def ingest_investor_flow(self) -> Dict[str, int]:
        """Month-to-date investor participation, one request per missing session.

        This table has no ranged form worth using: each export is a single
        cumulative snapshot, so a range would return one file, not a series.
        The request date is NOT the reference date — B3 publishes T+2 — so
        the dates asked for are derived from the sessions that are missing.
        """
        sessions = lending.known_sessions(self._supabase) or lending._fallback_sessions(
            lending.RETENTION_SESSIONS
        )
        missing = lending.sessions_to_fetch(
            self._supabase, bdi.TABLE_INVESTOR, "reference_date"
        )
        requests = lending.investor_request_dates(sessions, missing)

        total = 0
        failures: List[str] = []
        for request_date in requests:
            run_id = str(uuid4())
            self._log_start(run_id, "investor_participation", request_date.year, request_date.month)
            try:
                text = await self._bdi.fetch_table("SharesInvesVolum", request_date)
            except B3BdiEmpty as exc:
                self._log_finish(run_id, 0, ingest_log.describe(exc), skipped=True)
                continue
            except Exception as exc:  # noqa: BLE001 — counted, reported below
                self._log_finish(run_id, 0, ingest_log.describe(exc))
                failures.append(f"{request_date.isoformat()}: {exc}")
                continue
            try:
                rows = bdi.parse_investor_participation(text, origin=request_date.isoformat())
                n = lending.upsert_investor_participation(self._supabase, rows)
            except Exception as exc:  # noqa: BLE001 — counted, reported below
                self._log_finish(run_id, 0, ingest_log.describe(exc))
                failures.append(f"{request_date.isoformat()}: {exc}")
                continue
            self._log_finish(run_id, n)
            total += n

        if failures and total == 0:
            # Every request failed: that is a broken source, not a bad day.
            raise RuntimeError(
                f"B3 investor participation: all {len(requests)} requests failed; "
                f"first: {failures[0][:200]}"
            )
        if failures:
            logger.warning(
                "B3 investor participation: %d/%d requests failed; first: %s",
                len(failures), len(requests), failures[0][:200],
            )

        monthly = await self._ingest_investor_flow_monthly()
        return {bdi.TABLE_INVESTOR: total, bdi.TABLE_INVESTOR_MONTHLY: monthly}

    async def _ingest_investor_flow_monthly(self) -> int:
        """Last month's participation by market. Only the latest month exists.

        Dated by the newest session we know about, not by today: B3 publishes
        the BDI from ~15:00 (their 2026-07-31 notice), so asking for the
        current date during a morning cron reliably returns "Nenhum
        resultado". Verified 2026-09-16 — 09-15 had data, 09-16 did not yet.
        """
        run_id = str(uuid4())
        sessions = lending.known_sessions(self._supabase, limit=1)
        request_date = sessions[-1] if sessions else date.today()
        self._log_start(
            run_id, "investor_participation_monthly", request_date.year, request_date.month
        )
        try:
            text = await self._bdi.fetch_table("SharesInvesVolumMonthly", request_date)
        except B3BdiEmpty as exc:
            self._log_finish(run_id, 0, ingest_log.describe(exc), skipped=True)
            return 0
        except Exception as exc:
            self._log_finish(run_id, 0, ingest_log.describe(exc))
            raise
        try:
            rows = bdi.parse_investor_participation_monthly(
                text, request_date=request_date, origin=request_date.isoformat()
            )
            n = lending.upsert_investor_participation_monthly(self._supabase, rows)
        except Exception as exc:
            self._log_finish(run_id, 0, ingest_log.describe(exc))
            raise
        self._log_finish(run_id, n)
        return n

    async def ingest_index_portfolios(self, indices: Optional[List[str]] = None) -> int:
        """Free float and B3 sector for the index universe.

        IBRA is the broad one (~148 names) and IBOV the headline; SMLL adds
        the small caps that dominate a crowded-short list. A failure on one
        index must not abandon the others, but it must not vanish either.
        """
        codes = indices or [c.strip() for c in
                            os.getenv("B3_INDEX_CODES", "IBOV,IBRA,SMLL").split(",") if c.strip()]
        run_id = str(uuid4())
        self._log_start(run_id, "index_portfolio", None, None)
        total = 0
        failures: List[str] = []
        try:
            for code in codes:
                try:
                    records = await self._bdi.fetch_index_portfolio(code)
                    rows = bdi.parse_index_portfolio(records, origin=code)
                    total += lending.upsert_index_portfolio(self._supabase, rows)
                except Exception as exc:  # noqa: BLE001 — counted, then reported
                    failures.append(f"{code}: {exc}")
        except Exception as exc:
            self._log_finish(run_id, total, ingest_log.describe(exc))
            raise

        if failures and total == 0:
            msg = f"all {len(codes)} indices failed; first: {failures[0][:200]}"
            self._log_finish(run_id, 0, error=msg)
            raise RuntimeError(f"B3 index portfolios: {msg}")
        if failures:
            msg = f"{len(failures)}/{len(codes)} indices failed; first: {failures[0][:200]}"
            self._log_finish(run_id, total, error=msg)
            logger.warning("B3 index portfolios partial: %s", msg)
        else:
            self._log_finish(run_id, total)
        logger.info("B3 index portfolios: %d rows from %s", total, ",".join(codes))
        return total

    async def ingest_instruments(self) -> int:
        """Cash-market instrument registry (shares outstanding, ISIN, governance).

        Dated by the newest session we know about rather than by today, so a
        Saturday run does not file Friday's registry under Saturday.
        """
        sessions = lending.known_sessions(self._supabase, limit=1)
        reference_date = sessions[-1] if sessions else date.today()
        run_id = str(uuid4())
        self._log_start(run_id, "instrument_registry", reference_date.year, reference_date.month)
        try:
            text = await self._bdi.fetch_table("InstrumentsEquities", reference_date)
        except B3BdiEmpty as exc:
            self._log_finish(run_id, 0, ingest_log.describe(exc), skipped=True)
            return 0
        except Exception as exc:
            self._log_finish(run_id, 0, ingest_log.describe(exc))
            raise
        try:
            rows = bdi.parse_instrument_registry(
                text, reference_date=reference_date, origin=reference_date.isoformat()
            )
            n = lending.upsert_instrument_registry(self._supabase, rows)
        except Exception as exc:
            self._log_finish(run_id, 0, ingest_log.describe(exc))
            raise
        self._log_finish(run_id, n)
        logger.info("B3 instrument registry %s: %d rows", reference_date, n)
        return n

    async def daily_update_bdi(self) -> Dict[str, int]:
        """Every BDI-sourced table, in one call. Ratchet — see the fetcher."""
        totals: Dict[str, int] = {}
        totals.update(await self.ingest_lending())
        totals[bdi.TABLE_LENDING_TRADE] = await self.ingest_lending_trades()
        totals.update(await self.ingest_investor_flow())
        totals[bdi.TABLE_INDEX_PORTFOLIO] = await self.ingest_index_portfolios()
        totals[bdi.TABLE_INSTRUMENT] = await self.ingest_instruments()
        return totals

    async def daily_update(self) -> Dict[str, int]:
        """Re-fetch the trailing calendar window of daily zips.

        Weekends/holidays 404 and are skipped. A real fetch/parse failure
        raises so run_daily can fail the process.
        """
        today = date.today()
        lookback = self._lookback_days()
        total = 0
        for offset in range(lookback):
            session = today - timedelta(days=offset)
            total += await self.ingest_daily(session)
        logger.info("B3 COTAHIST daily_update done: rows=%d lookback=%d", total, lookback)
        return {TABLE: total}

    async def backfill(self, start_year: int = 2019, end_year: Optional[int] = None) -> Dict[str, int]:
        """Yearly COTAHIST zips. COTAHIST ONLY — there is no lending backfill.

        The BDI lending and investor-flow tables are capped at ~21 business
        days by B3 (src/fetchers/b3_bdi_fetcher.py). Offering a start_year
        for them would imply a history that cannot be retrieved at any
        price, so they are reachable only through daily_update_bdi.
        """
        if end_year is None:
            end_year = date.today().year
        if end_year < start_year:
            raise ValueError(f"end_year {end_year} < start_year {start_year}")
        total = 0
        for year in range(start_year, end_year + 1):
            total += await self.ingest_year(year)
        logger.info("B3 COTAHIST backfill done: rows=%d years=%s-%s", total, start_year, end_year)
        return {TABLE: total}
