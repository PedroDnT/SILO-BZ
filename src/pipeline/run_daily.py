"""
Daily incremental update — run by GitHub Actions cron at 06:00 UTC.

Fetches:
  - CVM: current month + previous month for all entities
  - BACEN: last 7 days of SGS, PTAX, and Expectativas

Required env vars: SUPABASE_URL, SUPABASE_SERVICE_KEY
"""

import asyncio
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.ingestor.cvm_ingestor import CVMIngestor
from src.ingestor.bacen_ingestor import BacenIngestor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("run_daily")


async def main() -> None:
    start_ts = time.monotonic()
    logger.info("Daily update starting")

    cvm_ingestor   = CVMIngestor()
    bacen_ingestor = BacenIngestor()

    cvm_totals, bacen_totals = await asyncio.gather(
        cvm_ingestor.daily_update(),
        bacen_ingestor.daily_update(),
    )

    totals = {**cvm_totals, **bacen_totals}
    elapsed = time.monotonic() - start_ts
    total_rows = sum(totals.values())
    logger.info(
        "Daily update done in %.1fs — %d rows upserted: %s",
        elapsed, total_rows, totals,
    )


if __name__ == "__main__":
    asyncio.run(main())
