"""
Daily incremental update — run by GitHub Actions cron at 06:00 UTC.

Fetches:
  - CVM: current month + previous month for all entities
  - BACEN: last ~30 days
  - ANBIMA ETF: latest monthly boletim (idempotent — upserts full history)

Required env vars: POSTGRES_URL
"""

import asyncio
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.pipeline.cvm_pipeline import CVMIngestor
from src.pipeline.bacen_pipeline import BacenIngestor
from src.pipeline.anbima_etf_pipeline import AnbimaEtfIngestor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("run_daily")


async def main() -> None:
    start_ts = time.monotonic()
    logger.info("Daily update starting")

    cvm_ingestor = CVMIngestor()
    totals = await cvm_ingestor.daily_update()

    # BACEN: incremental refresh — re-fetches the last ~30 days; cheap.
    try:
        bacen_ingestor = BacenIngestor()
        from datetime import date, timedelta
        bacen_start = (date.today() - timedelta(days=30)).isoformat()
        bacen_totals = await bacen_ingestor.backfill(start=bacen_start)
        totals.update(bacen_totals)
    except Exception as exc:
        logger.warning("BACEN daily refresh failed: %s", exc)

    # ANBIMA ETF: fetch latest monthly boletim; idempotent upsert.
    try:
        anbima_ingestor = AnbimaEtfIngestor()
        anbima_totals = await anbima_ingestor.daily_update()
        totals.update(anbima_totals)
    except Exception as exc:
        logger.warning("ANBIMA ETF daily refresh failed: %s", exc)

    elapsed = time.monotonic() - start_ts
    total_rows = sum(totals.values())
    logger.info(
        "Daily update done in %.1fs — %d rows upserted: %s",
        elapsed, total_rows, totals,
    )


if __name__ == "__main__":
    asyncio.run(main())
