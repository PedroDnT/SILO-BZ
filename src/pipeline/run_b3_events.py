"""
B3 corporate events, cash distributions and index levels, as their own daily step.

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

Contract, the same as run_daily: each source runs even if the other failed, and
the process exits non-zero if either did. Each ingest writes its own
cvm_ingest_log rows.

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

    # Published splits, groupings, bonuses, dividends and subscriptions per
    # ISIN. One request per traded issuer, derived from our own tape, not B3's
    # 3,500-company list.
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
