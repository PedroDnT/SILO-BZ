"""
B3 corporate events, cash distributions, index levels and the fixed income ETF
prints (b3_trade_consolidated), as their own daily step.

Both ran inside run_daily until 2026-09-30. There, a failure made the process
exit non-zero, and that skipped ANALYZE, the analytical apply and the dashboard
deploy hook for CVM, BACEN and B3 data that had all landed: on 2026-08-29 a
corporate-events SSL EOF turned the run red. They are slow foreign calls, a few
hundred per-issuer requests to B3's listed-companies proxy (about 7 and 3
minutes on 2026-09-30). Like the FNET register and the market data, they now
run after the dashboard is published: daily_ingest.yml, step "Refresh B3
corporate events and cash dividends", and the matching watchdog recovery step.

The analytical apply reads neither table. api.quote_history reads
b3_corporate_event (and its sweep) live, so a new event counts from the moment
it lands, wherever in the job that happens.

Contract, the same as run_daily: each source runs even if another failed, and
the process exits non-zero if any source raised. A source that finishes with
issuers failed (corporate events, cash dividends) does not raise: it
writes an `error` cvm_ingest_log row, which DB Health reads, and returns its
count, so the step stays green. Each ingest writes its own cvm_ingest_log rows.

    python -m src.pipeline.run_b3_events

Required env vars: POSTGRES_URL
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.pipeline.b3_pipeline import B3Ingestor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("run_b3_events")


async def main() -> None:
    failures: list[tuple[str, Exception]] = []
    totals: dict[str, int] = {}

    # B3's consolidated trade file, segment FORWARD (migration 57): the fixed
    # income ETFs (IMAB11, LFTS11, ...) that COTAHIST does not carry. The last
    # 7 calendar days, one file per weekday; a day with no session is skipped.
    # Here, not in run_daily: it shares arquivos.b3.com.br with the BDI
    # ratchet, and a failure must not skip the apply or the deploy. FIRST in
    # this step: it takes seconds, and on 2026-10-01 (run 36842444079) the
    # corporate-event sweep took 44 of the step's 45 minutes, so nothing
    # after it ran.
    try:
        totals.update(await B3Ingestor().daily_update_trade_consolidated())
    except Exception as exc:
        logger.error("B3 consolidated trades refresh failed: %s", exc, exc_info=True)
        failures.append(("b3_trade_consolidated", exc))

    # Published splits, groupings, bonuses, dividends and subscriptions per
    # ISIN. One request per issuer due tonight (B3Ingestor._sweep_plan): the
    # share and unit issuers that printed since their proof, plus a rotating
    # 1/14 of everyone else, instead of all ~2,600 every night.
    try:
        totals["b3_corporate_event"] = await B3Ingestor().ingest_corporate_events()
    except Exception as exc:
        logger.error("B3 corporate events refresh failed: %s", exc, exc_info=True)
        failures.append(("b3_corporate_events", exc))

    # Cash distributions, full history (migration 51). The supplement above
    # carries only ~12 months of cash rows; this endpoint carries all of them,
    # paged by share class.
    try:
        totals["b3_cash_dividend"] = await B3Ingestor().ingest_cash_dividends()
    except Exception as exc:
        logger.error("B3 cash dividends refresh failed: %s", exc, exc_info=True)
        failures.append(("b3_cash_dividends", exc))

    # Daily levels of B3's published indices (migration 55): IBOV from 1968.
    # Every year is refetched, about a minute, so it needs no backfill mode.
    # The benchmark a research caller reads through api.index_history.
    try:
        totals["b3_index_level"] = await B3Ingestor().ingest_index_levels()
    except Exception as exc:
        logger.error("B3 index levels refresh failed: %s", exc, exc_info=True)
        failures.append(("b3_index_levels", exc))

    logger.info("B3 events done — rows upserted: %s", totals)

    if failures:
        summary = "; ".join(f"{name}: {exc}" for name, exc in failures)
        logger.error("B3 events FAILED for %d source(s) — %s", len(failures), summary)
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
