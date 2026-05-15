"""
Daily incremental update — run by GitHub Actions cron at 06:00 UTC.

Fetches:
  - CVM: current month + previous month for all entities

Required env vars: SUPABASE_URL, SUPABASE_SERVICE_KEY
"""

import asyncio
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.pipeline.cvm_pipeline import CVMIngestor

# BACEN benchmark data (SGS/PTAX) is no longer replicated locally.
# Clients fetch CDI/SELIC/IPCA directly from the BCB API at query time.
# See: https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados/ultimos/1?formato=json

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

    elapsed = time.monotonic() - start_ts
    total_rows = sum(totals.values())
    logger.info(
        "Daily update done in %.1fs — %d rows upserted: %s",
        elapsed, total_rows, totals,
    )


if __name__ == "__main__":
    asyncio.run(main())
