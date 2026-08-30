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

from src.fetchers.b3_fetcher import B3CotahistFetcher, B3CotahistNotFound
from src.parsers.cotahist import CONFLICT, TABLE, batched, parse_cotahist_bytes
from src.store.pg_client import get_pg_client, upsert_rows

logger = logging.getLogger(__name__)

_UPSERT_BATCH = 5000


class B3Ingestor:
    def __init__(self, fetcher: Optional[B3CotahistFetcher] = None) -> None:
        self._fetcher = fetcher or B3CotahistFetcher()
        self._supabase = get_pg_client()

    def _lookback_days(self) -> int:
        raw = os.getenv("B3_DAILY_LOOKBACK_DAYS", "7").strip()
        try:
            n = int(raw)
        except ValueError:
            return 7
        return n if n >= 1 else 7

    def _log_start(self, run_id: str, doc_type: str, year: Optional[int], month: Optional[int]) -> None:
        try:
            upsert_rows(self._supabase, "cvm_ingest_log", [{
                "run_id": run_id,
                "entity": "b3",
                "doc_type": doc_type,
                "period_year": year,
                "period_month": month,
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
            }])
        except Exception as exc:
            logger.warning("ingest_log start failed: %s", exc)

    def _log_finish(
        self,
        run_id: str,
        rows: int,
        error: Optional[str] = None,
        *,
        skipped: bool = False,
    ) -> None:
        if skipped:
            status = "skipped"
        elif error:
            status = "error"
        else:
            status = "ok"
        try:
            with self._supabase.cursor() as cur:
                cur.execute(
                    "UPDATE cvm_ingest_log SET rows_upserted=%s, status=%s,"
                    " error_msg=%s, finished_at=%s WHERE run_id=%s",
                    (
                        rows,
                        status,
                        error,
                        datetime.now(timezone.utc).isoformat(),
                        run_id,
                    ),
                )
        except Exception as exc:
            logger.warning("ingest_log finish failed: %s", exc)

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
            self._log_finish(run_id, 0, str(exc), skipped=True)
            return 0
        except Exception as exc:
            logger.error("B3 COTAHIST daily %s fetch failed: %s", label, exc)
            self._log_finish(run_id, 0, str(exc))
            raise

        try:
            rows = parse_cotahist_bytes(payload, origin=label)
            n = self._upsert(rows)
        except Exception as exc:
            self._log_finish(run_id, 0, str(exc))
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
            self._log_finish(run_id, 0, str(exc), skipped=True)
            return 0
        except Exception as exc:
            logger.error("B3 COTAHIST year %s fetch failed: %s", year, exc)
            self._log_finish(run_id, 0, str(exc))
            raise

        try:
            rows = parse_cotahist_bytes(payload, origin=str(year))
            n = self._upsert(rows)
        except Exception as exc:
            self._log_finish(run_id, 0, str(exc))
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
            self._log_finish(run_id, 0, error=str(exc))
            raise

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
        if end_year is None:
            end_year = date.today().year
        if end_year < start_year:
            raise ValueError(f"end_year {end_year} < start_year {start_year}")
        total = 0
        for year in range(start_year, end_year + 1):
            total += await self.ingest_year(year)
        logger.info("B3 COTAHIST backfill done: rows=%d years=%s-%s", total, start_year, end_year)
        return {TABLE: total}
