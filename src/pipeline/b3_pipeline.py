"""B3 COTAHIST ingest — fetch public quotation zips, parse register 01, upsert.

Landing table: b3_cotahist. No ticker↔CNPJ match here (deferred).

    ingestor = B3Ingestor()
    await ingestor.daily_update()          # last N calendar days of daily zips
    await ingestor.backfill(start_year=2019)  # yearly zips
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import zlib
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union
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
# arquivos.b3.com.br sits behind Cloudflare, which 403s bursts (the BDI host).
# One second between consolidated-trade sessions, as the manual probes paced.
_TC_PAUSE_SECONDS = 1.0

# The first session of the COTAHIST tape SILO holds. The corporate-event sweep
# covers every issuer that printed since then, so a price-adjusted close has
# its issuer's events for the whole window it can serve (#413).
TAPE_START = date(2019, 1, 2)

# The nightly corporate-event sweep is incremental. api.close_adj refuses an
# instrument whose issuer proof predates its last session, so every share or
# unit issuer that printed since its proof is re-swept every night. Everyone
# else (delisted issuers, BDRs, FIIs, ETFs, funds, none of which close_adj
# serves) is re-swept in a rotating slice, each issuer once every this many
# days. On 2026-10-01 the full sweep was 2,597 issuers and 44 minutes, the
# whole of its step's 45-minute timeout.
EVENT_SWEEP_ROTATION_DAYS = 14


class B3Ingestor:
    def __init__(
        self,
        fetcher: Optional[B3CotahistFetcher] = None,
        bdi_fetcher: Optional[B3BdiFetcher] = None,
        trade_consolidated_fetcher: Optional[Any] = None,
    ) -> None:
        self._fetcher = fetcher or B3CotahistFetcher()
        self._bdi = bdi_fetcher or B3BdiFetcher()
        self._tc_fetcher = trade_consolidated_fetcher
        self._supabase = get_pg_client()

    def _lookback_days(self) -> int:
        raw = os.getenv("B3_DAILY_LOOKBACK_DAYS", "7").strip()
        try:
            n = int(raw)
        except ValueError:
            return 7
        return n if n >= 1 else 7

    # Audit rows go through src/pipeline/ingest_log.audited (the one writer).
    # The work returns its row count, or an Outcome when the run ends skipped,
    # or ends in error without raising (a partial sweep). An exception in
    # ``skip_on`` is "B3 has nothing for this request": a skipped row and 0.
    # Anything else is an error row and is re-raised.
    async def _audited(
        self,
        doc_type: str,
        work: Callable[[], Awaitable[Union[int, ingest_log.Outcome]]],
        *,
        year: Optional[int] = None,
        month: Optional[int] = None,
        skip_on: Tuple[type, ...] = (),
        run_id: Optional[str] = None,
    ) -> int:
        async def guarded() -> Union[int, ingest_log.Outcome]:
            try:
                return await work()
            except skip_on as exc:
                logger.info("B3 %s skipped: %s", doc_type, ingest_log.describe(exc))
                return ingest_log.Outcome(0, "skipped", ingest_log.describe(exc))

        return await ingest_log.audited(
            self._supabase, "b3", doc_type, guarded,
            period_year=year, period_month=month, upsert=upsert_rows, run_id=run_id,
        )

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
        label = session.isoformat()

        async def work() -> int:
            payload = await self._fetcher.fetch_daily(session)
            n = self._upsert(parse_cotahist_bytes(payload, origin=label))
            logger.info("B3 COTAHIST daily %s upserted %d rows", label, n)
            return n

        return await self._audited(
            "cotahist_daily", work, year=session.year, month=session.month,
            skip_on=(B3CotahistNotFound,),
        )

    async def ingest_year(self, year: int) -> int:
        """Fetch one yearly zip and upsert. 404 → skipped (returns 0)."""

        async def work() -> int:
            payload = await self._fetcher.fetch_year(year)
            n = self._upsert(parse_cotahist_bytes(payload, origin=str(year)))
            logger.info("B3 COTAHIST year %s upserted %d rows", year, n)
            return n

        return await self._audited(
            "cotahist_yearly", work, year=year, skip_on=(B3CotahistNotFound,),
        )

    def _traded_issuers(
        self, lookback_days: int = 400, since: Optional[date] = None
    ) -> List[str]:
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

        ``since`` replaces the lookback with a fixed first session. The
        corporate-event sweep passes the tape start, so an issuer that stopped
        trading more than 400 days ago still has its events (#413).
        """
        if since is not None:
            sql = """
                SELECT DISTINCT left(codneg, 4) AS issuer
                  FROM b3_cotahist
                 WHERE tpmerc = '010'
                   AND length(codneg) >= 4
                   AND trade_date >= %s
                 ORDER BY issuer
            """
            params: Tuple[Any, ...] = (since,)
        else:
            sql = """
                SELECT DISTINCT left(codneg, 4) AS issuer
                  FROM b3_cotahist
                 WHERE tpmerc = '010'
                   AND length(codneg) >= 4
                   AND trade_date > (SELECT max(trade_date) FROM b3_cotahist) - %s
                 ORDER BY issuer
            """
            params = (lookback_days,)
        with self._supabase.cursor() as cur:
            cur.execute(sql, params)
            return [r[0] for r in cur.fetchall() if r and r[0]]

    def _issuers_due_for_proof(self, since: date) -> List[str]:
        """Share and unit issuers whose sweep proof is missing or stale.

        The same rule api.assert_close_adj applies: the issuer is
        substr(isin, 3, 4), the universe is ISIN code ACN, CDA or UNT, and a
        proof is stale when its date in UTC-3 is before the issuer's last
        session on the tape. (The API also requires a unit ticker to end in
        11; sweeping a few more issuers than it serves is harmless.)
        """
        sql = """
            WITH last AS (
                SELECT substr(isin, 3, 4) AS issuer, max(trade_date) AS last_session
                  FROM b3_cotahist
                 WHERE tpmerc = '010'
                   AND trade_date >= %s
                   AND substr(isin, 7, 3) IN ('ACN', 'CDA', 'UNT')
                 GROUP BY 1
            )
            SELECT l.issuer
              FROM last l
              LEFT JOIN b3_corporate_event_sweep s ON s.issuing_company = l.issuer
             WHERE s.proven_at IS NULL
                OR (s.proven_at AT TIME ZONE 'America/Sao_Paulo')::date < l.last_session
             ORDER BY 1
        """
        with self._supabase.cursor() as cur:
            cur.execute(sql, (since,))
            return [r[0] for r in cur.fetchall() if r and r[0]]

    def _sweep_plan(self, since: date, today: date) -> List[str]:
        """Tonight's issuers: every one due for proof, plus today's rotation slice.

        The slice is fixed by a checksum of the code, not by Python's salted
        hash(), so the same issuers come up on the same day in every run and
        each one is swept once every EVENT_SWEEP_ROTATION_DAYS days.
        """
        due = self._issuers_due_for_proof(since)
        due_set = set(due)
        slot = today.toordinal() % EVENT_SWEEP_ROTATION_DAYS
        rotation = [
            code for code in self._traded_issuers(since=since)
            if code not in due_set
            and zlib.crc32(code.encode()) % EVENT_SWEEP_ROTATION_DAYS == slot
        ]
        logger.info(
            "B3 corporate events plan: %d due for proof + %d in rotation slot %d/%d",
            len(due), len(rotation), slot, EVENT_SWEEP_ROTATION_DAYS,
        )
        return sorted(due_set | set(rotation))

    def _tape_names(
        self, codes: List[str], lookback_days: int = 400
    ) -> Dict[str, Tuple[str, List[str]]]:
        """code -> (name the tape last printed for it, CNPJs cia_ticker lists).

        For issuing codes B3's catalog no longer lists. The name is COTAHIST's
        own ``nome_resumido`` on the code's latest standard-lot session inside
        the same window as _traded_issuers; it equals the catalog tradingName
        wherever both exist (docs/reference/research/cash-dividends-mapping.md §2). The
        CNPJs are CVM's published ticker history, used to tell a renamed
        company from a delisted one. A code with no name printed is absent.
        """
        sql = """
            WITH latest AS (
                SELECT DISTINCT ON (left(codneg, 4))
                       left(codneg, 4)        AS issuer,
                       btrim(nome_resumido)   AS name
                  FROM b3_cotahist
                 WHERE tpmerc = '010'
                   AND codbdi = '02'
                   AND left(codneg, 4) = ANY(%s)
                   AND btrim(coalesce(nome_resumido, '')) <> ''
                   AND trade_date > (SELECT max(trade_date) FROM b3_cotahist) - %s
                 ORDER BY left(codneg, 4), trade_date DESC
            )
            SELECT l.issuer, l.name,
                   coalesce(array_agg(DISTINCT t.cnpj_cia)
                              FILTER (WHERE t.cnpj_cia IS NOT NULL), '{}')
              FROM latest l
              LEFT JOIN cia_ticker t
                ON length(t.codneg) >= 5 AND left(t.codneg, 4) = l.issuer
             GROUP BY l.issuer, l.name
        """
        with self._supabase.cursor() as cur:
            cur.execute(sql, (list(codes), lookback_days))
            return {r[0]: (r[1], sorted(r[2] or [])) for r in cur.fetchall() if r and r[1]}

    async def ingest_corporate_events(
        self,
        issuers: Optional[List[str]] = None,
        since: date = TAPE_START,
        full: bool = False,
    ) -> int:
        """Fetch published corporate events for the issuers due tonight.

        By default the sweep is incremental (``_sweep_plan``): the share and
        unit issuers whose proof is missing or older than their last session,
        plus a rotating slice of every other issuer traded since ``since``.
        ``full=True`` sweeps every issuer traded since ``since``; ``issuers``
        names the codes outright.

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

        Every code whose supplement came back is recorded in
        b3_corporate_event_sweep once its events are stored: the proof that
        api.quote_history needs before it serves a price-adjusted close for
        that issuer (#413).
        """
        from src.fetchers.b3_corporate_events_fetcher import (
            B3CorporateEventsFetcher,
            B3SupplementEmpty,
        )
        from src.pipeline.ingest_b3_events import (
            ingest_b3_corporate_events,
            record_sweep_proofs,
        )

        run_id = str(uuid4())

        async def work() -> Union[int, ingest_log.Outcome]:
            if issuers is not None:
                codes = issuers
            elif full:
                codes = self._traded_issuers(since=since)
            else:
                codes = self._sweep_plan(since=since, today=date.today())
            if not codes:
                logger.info("B3 corporate events: no traded issuers found, skipped")
                return ingest_log.Outcome(0, "skipped")

            fetcher = B3CorporateEventsFetcher()
            rows: List[Dict[str, Any]] = []
            failures: List[str] = []
            missing: List[str] = []
            n_events: Dict[str, int] = {}
            for code in codes:
                try:
                    code_rows = fetcher.fetch_events(code)
                except B3SupplementEmpty:
                    missing.append(code)
                    continue
                except Exception as exc:  # noqa: BLE001 - counted, then reported
                    failures.append(f"{code}: {exc}")
                    continue
                rows.extend(code_rows)
                n_events[code] = len(code_rows)
            fetched = len(n_events)

            total = ingest_b3_corporate_events(self._supabase, rows) if rows else 0
            # After the events, never before: a proof must not outlive a
            # failed upsert of the events it vouches for.
            record_sweep_proofs(self._supabase, n_events, run_id)

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
                outcome = ingest_log.Outcome(total, "error", msg)
                logger.warning("B3 corporate events partial: %s", msg)
            elif fetched == 0:
                # Every issuer returned empty — the path token is wrong or
                # B3 is serving empty bodies wholesale. Same failure mode as
                # a malformed GET, which used to look like a dead endpoint.
                msg = (
                    f"all {len(codes)} issuers returned an empty supplement "
                    f"body; first: {missing[0] if missing else '?'}"
                )
                outcome = ingest_log.Outcome(total, "error", msg)
                logger.error("B3 corporate events: %s", msg)
            else:
                outcome = ingest_log.Outcome(total, "ok")
            logger.info(
                "B3 corporate events: %d rows from %d issuers "
                "(%d failed, %d no supplement)",
                total, len(codes), len(failures), len(missing),
            )
            return outcome

        return await self._audited("corporate_events", work, run_id=run_id)

    async def ingest_index_levels(
        self,
        indices: Optional[Tuple[str, ...]] = None,
        today: Optional[date] = None,
    ) -> int:
        """Fetch every published year of each configured index and upsert the levels.

        One call per calendar year (59 for IBOV, about a minute), refetched in
        full every night: the upsert rewrites only a row that changed, so a
        B3 correction or an intraday level stored earlier heals with no
        backfill mode. The whole series is validated before anything is
        written, because the divisor-step check compares neighbouring sessions
        across year boundaries. A null result for a configured index is an
        error (B3IndexNoResults), except for the current year in the first days
        of January, before its first session. One cvm_ingest_log row.
        """
        from src.fetchers.b3_index_fetcher import B3IndexFetcher, B3IndexNoResults
        from src.pipeline import ingest_b3_index as idx


        async def work() -> int:
            nonlocal today
            today = today or date.today()
            fetcher = B3IndexFetcher()
            records: List[Dict[str, Any]] = []
            for code in indices or idx.INDEX_CODES:
                series: List[Dict[str, Any]] = []
                for year in range(idx.FIRST_YEAR[code], today.year + 1):
                    try:
                        payload = fetcher.fetch_year(code, year)
                    except B3IndexNoResults:
                        if not idx.year_may_be_empty(year, today):
                            raise
                        logger.info(
                            "B3 index %s %d: no grid yet, the year has no session", code, year
                        )
                        continue
                    series.extend(idx.parse_year(code, year, payload))
                    time.sleep(fetcher.sleep_between)
                idx.mark_divisor_steps(code, series)
                records.extend(series)
            total = idx.ingest_b3_index_levels(self._supabase, records)
            logger.info("B3 index levels: %d sessions across %d index(es)", total,
                        len(indices or idx.INDEX_CODES))
            return total

        return await self._audited("index_levels", work)

    async def ingest_cash_dividends(
        self,
        issuers: Optional[List[str]] = None,
        lookback_days: int = 400,
        since: Optional[date] = None,
        full_history: bool = False,
    ) -> int:
        """Fetch B3's full cash-distribution history for the traded universe.

        b3_corporate_event's cash rows come from a ~12-month window; this is
        the complete history (migration 51). Every page is fetched for every
        issuer each time, because B3 orders the endpoint by share class before
        date (see the fetcher). What gets upserted is narrowed instead: the
        daily run keeps distributions whose entitlement date is within
        `lookback_days`, unless `since` is given; `full_history` upserts all.

        Failure semantics mirror ingest_corporate_events: one issuer failing
        is counted and fails the slice, but does not abandon the sweep.

        Names come from B3's catalog first. The catalog lists ACTIVE companies
        only, so a code missing from it falls back to the name the tape
        printed for it (_tape_names): B3 answers a delisted company's own
        COTAHIST name with its history (ENBR, "ENERGIAS BR", 34 rows). A
        missing code that cia_ticker ties to a CNPJ the catalog carries is
        queried under the catalog's name instead: a rename (ELET->AXIA) or a
        tape prefix that is not the catalog key (ADMF3 -> B100). B3 also
        answers the old name (ELETROBRAS, 184 rows), so querying both would
        count every distribution twice; a name already fetched is skipped.
        A code with neither is reported, not guessed.
        """
        from src.fetchers.b3_corporate_events_fetcher import (
            B3CorporateEventsFetcher,
            cash_dividend_query_name,
        )
        from src.pipeline.ingest_b3_cash_dividends import (
            ingest_b3_cash_dividends,
            parse_cash_dividends,
        )


        async def work() -> Union[int, ingest_log.Outcome]:
            codes = issuers if issuers is not None else self._traded_issuers(lookback_days)
            if not codes:
                logger.info("B3 cash dividends: no traded issuers found, skipped")
                return ingest_log.Outcome(0, "skipped")

            if full_history:
                cutoff: Optional[date] = None
            elif since is not None:
                cutoff = since
            else:
                cutoff = date.today() - timedelta(days=lookback_days)

            fetcher = B3CorporateEventsFetcher()
            names = fetcher.trading_names()
            records: List[Dict[str, Any]] = []
            failures: List[str] = []
            fetched = 0
            # Normalized as sent: "KLABIN S/A" and "KLABIN SA" are one query.
            seen: set = set()

            def fetch_one(code: str, name: str, cnpj: Optional[str]) -> None:
                nonlocal fetched
                key = cash_dividend_query_name(name)
                if key in seen:
                    return
                seen.add(key)
                try:
                    raw = fetcher.fetch_cash_dividends(name)
                    records.extend(parse_cash_dividends(
                        code, name, raw, since=cutoff, cnpj=cnpj,
                    ))
                    fetched += 1
                except Exception as exc:  # noqa: BLE001 - counted, then reported
                    failures.append(f"{code}/{name}: {exc}")

            not_in_catalog: List[str] = []
            for code in codes:
                entries = names.get(code)
                if not entries:
                    not_in_catalog.append(code)
                    continue
                for entry in entries:
                    fetch_one(code, entry["trading_name"], entry.get("cnpj") or None)

            renamed: List[str] = []
            missing: List[str] = []
            from_tape = 0
            if not_in_catalog:
                catalog_by_cnpj: Dict[str, List[str]] = {}
                for entries in names.values():
                    for e in entries:
                        if e.get("cnpj"):
                            catalog_by_cnpj.setdefault(e["cnpj"], []).append(e["trading_name"])
                tape = self._tape_names(not_in_catalog, lookback_days)
                for code in not_in_catalog:
                    found = tape.get(code)
                    if found is None:
                        missing.append(code)
                        continue
                    name, cnpjs = found
                    listed = [c for c in cnpjs if c in catalog_by_cnpj]
                    if listed:
                        # A company the catalog lists under another code:
                        # renamed (ELET, now AXIA) or a tape prefix that is
                        # not its catalog key (ADMF3 trades as B100). Query
                        # the catalog name; seen skips it when that code was
                        # already fetched, so nothing is counted twice.
                        renamed.append(code)
                        for c in listed:
                            for current in catalog_by_cnpj[c]:
                                fetch_one(code, current, c)
                        continue
                    # One CNPJ is CVM's published mapping; several are left
                    # NULL rather than picked.
                    cnpj = cnpjs[0] if len(cnpjs) == 1 else None
                    fetch_one(code, name, cnpj)
                    from_tape += 1

            total = ingest_b3_cash_dividends(self._supabase, records) if records else 0

            if renamed:
                logger.info(
                    "B3 cash dividends: %d codes resolved to a catalog company "
                    "through cia_ticker's CNPJ (first: %s)",
                    len(renamed), ", ".join(renamed[:8]),
                )
            if missing:
                logger.warning(
                    "B3 cash dividends: %d/%d issuers have no tradingName in "
                    "B3's catalog or on the tape (first: %s)",
                    len(missing), len(codes), ", ".join(missing[:8]),
                )
            if failures:
                msg = (
                    f"{len(failures)} company fetches failed; "
                    f"first: {failures[0][:200]}"
                )
                outcome = ingest_log.Outcome(total, "error", msg)
                logger.warning("B3 cash dividends partial: %s", msg)
            elif fetched == 0:
                msg = (
                    f"no company in {len(codes)} issuers could be fetched "
                    f"(no tradingName for {len(missing)})"
                )
                outcome = ingest_log.Outcome(total, "error", msg)
                logger.error("B3 cash dividends: %s", msg)
            else:
                outcome = ingest_log.Outcome(total, "ok")
            logger.info(
                "B3 cash dividends: %d rows from %d companies "
                "(%d named from the tape, %d via catalog CNPJ, %d failed, "
                "%d without tradingName, cutoff %s)",
                total, fetched, from_tape, len(renamed), len(failures),
                len(missing), cutoff or "none",
            )
            return outcome

        return await self._audited("cash_dividends", work)


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
        start, end = targets[0], targets[-1]
        label = f"{b3_table} {start.isoformat()}..{end.isoformat()}"

        async def work() -> Union[int, ingest_log.Outcome]:
            text = await self._bdi.fetch_table(b3_table, start, end)
            rows = parse(text)
            n = upsert(self._supabase, rows)
            delivered, missing = bdi.reconcile_span(rows, date_field, targets)

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
                #
                # When the older sessions DID land, the slice is `ok`: our run
                # succeeded, and `coverage().landed_at` counts only `ok` rows, so
                # `skipped` here made the source's calendar read as our staleness
                # every morning. The shortfall stays on the row as a note. Only a
                # span where nothing landed is `skipped`.
                not_published_yet = missing == [targets[-1]]
                if not_published_yet:
                    logger.info("B3 BDI %s: %s — newest session, not published yet", label, msg)
                    if delivered:
                        outcome = ingest_log.Outcome(n, "ok", msg)
                    else:
                        outcome = ingest_log.Outcome(n, "skipped", msg)
                else:
                    logger.warning("B3 BDI %s: %s", label, msg)
                    outcome = ingest_log.Outcome(n, "error", msg)
            else:
                outcome = ingest_log.Outcome(n, "ok")
            logger.info("B3 BDI %s upserted %d rows over %d sessions", label, n, len(delivered))
            return outcome

        # Outside retention, or none of these were sessions. Not an error, but
        # if it keeps happening the staleness check must escalate it, because
        # for these tables an unfetched session never comes back.
        return await self._audited(
            doc_type, work, year=start.year, month=start.month, skip_on=(B3BdiEmpty,),
        )

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

            async def work() -> int:
                text = await self._bdi.fetch_table("BTBTrade", session)
                rows = bdi.parse_lending_trade(text, origin=session.isoformat())
                # The export is single-session, so anything else in the body
                # means B3 answered a different day than the one asked for.
                wrong = {r["trade_date"] for r in rows} - {session}
                if wrong:
                    raise RuntimeError(
                        f"BTBTrade for {session} returned sessions "
                        f"{sorted(d.isoformat() for d in wrong)}"
                    )
                return lending.upsert_lending_trades(self._supabase, rows)

            try:
                n = await self._audited(
                    "lending_trade", work, year=session.year, month=session.month,
                    skip_on=(B3BdiEmpty,),
                )
            except Exception as exc:  # noqa: BLE001 — counted, reported below
                failures.append(f"{session.isoformat()}: {exc}")
                continue
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

            async def work() -> int:
                text = await self._bdi.fetch_table("SharesInvesVolum", request_date)
                rows = bdi.parse_investor_participation(text, origin=request_date.isoformat())
                return lending.upsert_investor_participation(self._supabase, rows)

            try:
                n = await self._audited(
                    "investor_participation", work,
                    year=request_date.year, month=request_date.month, skip_on=(B3BdiEmpty,),
                )
            except Exception as exc:  # noqa: BLE001 — counted, reported below
                failures.append(f"{request_date.isoformat()}: {exc}")
                continue
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
        sessions = lending.known_sessions(self._supabase, limit=1)
        request_date = sessions[-1] if sessions else date.today()

        async def work() -> int:
            text = await self._bdi.fetch_table("SharesInvesVolumMonthly", request_date)
            rows = bdi.parse_investor_participation_monthly(
                text, request_date=request_date, origin=request_date.isoformat()
            )
            return lending.upsert_investor_participation_monthly(self._supabase, rows)

        return await self._audited(
            "investor_participation_monthly", work,
            year=request_date.year, month=request_date.month, skip_on=(B3BdiEmpty,),
        )

    async def ingest_index_portfolios(self, indices: Optional[List[str]] = None) -> int:
        """Free float and B3 sector for the index universe.

        IBRA is the broad one (~148 names) and IBOV the headline; SMLL adds
        the small caps that dominate a crowded-short list. A failure on one
        index must not abandon the others, but it must not vanish either.
        """
        codes = indices or [c.strip() for c in
                            os.getenv("B3_INDEX_CODES", "IBOV,IBRA,SMLL").split(",") if c.strip()]

        async def work() -> Union[int, ingest_log.Outcome]:
            total = 0
            failures: List[str] = []
            for code in codes:
                try:
                    records = await self._bdi.fetch_index_portfolio(code)
                    rows = bdi.parse_index_portfolio(records, origin=code)
                    total += lending.upsert_index_portfolio(self._supabase, rows)
                except Exception as exc:  # noqa: BLE001 — counted, then reported
                    failures.append(f"{code}: {exc}")

            if failures and total == 0:
                raise RuntimeError(
                    f"B3 index portfolios: all {len(codes)} indices failed; "
                    f"first: {failures[0][:200]}"
                )
            logger.info("B3 index portfolios: %d rows from %s", total, ",".join(codes))
            if failures:
                msg = f"{len(failures)}/{len(codes)} indices failed; first: {failures[0][:200]}"
                logger.warning("B3 index portfolios partial: %s", msg)
                return ingest_log.Outcome(total, "error", msg)
            return total

        return await self._audited("index_portfolio", work)

    async def ingest_instruments(self) -> int:
        """Cash-market instrument registry (shares outstanding, ISIN, governance).

        Dated by the newest session we know about rather than by today, so a
        Saturday run does not file Friday's registry under Saturday.
        """
        sessions = lending.known_sessions(self._supabase, limit=1)
        reference_date = sessions[-1] if sessions else date.today()

        async def work() -> int:
            text = await self._bdi.fetch_table("InstrumentsEquities", reference_date)
            rows = bdi.parse_instrument_registry(
                text, reference_date=reference_date, origin=reference_date.isoformat()
            )
            n = lending.upsert_instrument_registry(self._supabase, rows)
            logger.info("B3 instrument registry %s: %d rows", reference_date, n)
            return n

        return await self._audited(
            "instrument_registry", work,
            year=reference_date.year, month=reference_date.month, skip_on=(B3BdiEmpty,),
        )

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

    # B3's consolidated trade file, segment FORWARD (migration 57): the fixed
    # income ETFs COTAHIST does not carry. One file and one audit row per session.
    async def ingest_trade_consolidated(self, session: date) -> int:
        """Fetch one session's file and upsert its FORWARD rows.

        An empty file (no session, or outside retention) and a file B3 has not
        marked Final are logged `skipped` and return 0. Anything else raises.
        """
        from src.fetchers.b3_trade_consolidated_fetcher import (
            B3TradeConsolidatedEmpty,
            B3TradeConsolidatedFetcher,
        )
        from src.pipeline import ingest_b3_trade_consolidated as tc

        label = session.isoformat()

        async def work() -> Union[int, ingest_log.Outcome]:
            payload = await (self._tc_fetcher or B3TradeConsolidatedFetcher()).fetch(session)
            rows, dropped = tc.parse(tc.decode(payload), session)
            n = upsert_rows(self._supabase, tc.TABLE, rows, conflict_columns=tc.CONFLICT_COLS)
            logger.info("B3 consolidated trades %s: %d rows (%d dropped)", label, n, dropped)
            note = f"{dropped} row(s) dropped by validation" if dropped else None
            return ingest_log.Outcome(n, "ok", note)

        return await self._audited(
            "trade_consolidated", work, year=session.year, month=session.month,
            skip_on=(
                B3TradeConsolidatedEmpty,
                tc.B3TradeConsolidatedNotFinal,
                tc.B3TradeConsolidatedIncomplete,
            ),
        )

    async def daily_update_trade_consolidated(self) -> Dict[str, int]:
        """The trailing calendar window, like COTAHIST's (B3_DAILY_LOOKBACK_DAYS).

        Weekends are not requested; a holiday answers an empty file and is skipped.
        """
        from src.pipeline.ingest_b3_trade_consolidated import TABLE as TC_TABLE

        today = date.today()
        total = 0
        sessions = [today - timedelta(days=o) for o in range(self._lookback_days())]
        for session in (s for s in sessions if s.weekday() < 5):
            total += await self.ingest_trade_consolidated(session)
            await asyncio.sleep(_TC_PAUSE_SECONDS)
        # A day with no session is skipped (HTTP 400 or an empty file). If EVERY
        # weekday of the window was, the contract has more likely changed than
        # B3 closed for a week, so that is an error, never a quiet zero.
        if total == 0:
            raise RuntimeError(
                f"B3 consolidated trades: no row landed for any weekday of the last "
                f"{len(sessions)} days; check the contract in b3_trade_consolidated_fetcher"
            )
        return {TC_TABLE: total}

    async def backfill_trade_consolidated(
        self, start: date, end: Optional[date] = None
    ) -> Dict[str, int]:
        """Every weekday from ``start`` to ``end`` (default today), one file each.

        Sessions before B3's retention edge answer an empty file and are logged
        skipped: no row is stored for them, and none can be.
        """
        from src.pipeline.ingest_b3_trade_consolidated import TABLE as TC_TABLE

        end = end or date.today()
        if end < start:
            raise ValueError(f"end {end} < start {start}")
        total = 0
        failed: List[str] = []
        session = start
        while session <= end:
            if session.weekday() < 5:
                # One bad session must not cost the rest of the history: each
                # failure already has its own error row in cvm_ingest_log, and
                # the run still fails at the end, naming every one.
                try:
                    total += await self.ingest_trade_consolidated(session)
                except Exception as exc:  # noqa: BLE001 - logged per session, raised below
                    failed.append(f"{session}: {exc}")
                await asyncio.sleep(_TC_PAUSE_SECONDS)
            session += timedelta(days=1)
        logger.info("B3 consolidated trades backfill %s..%s: %d rows, %d failed",
                    start, end, total, len(failed))
        if failed:
            raise RuntimeError(
                f"B3 consolidated trades backfill: {len(failed)} session(s) failed; "
                f"first: {failed[0][:300]}"
            )
        return {TC_TABLE: total}

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
