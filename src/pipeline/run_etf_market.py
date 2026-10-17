"""ETF market snapshot (etfsbrasil.com.br via Apify) as its own daily job.

It ran at the end of run_daily until 2026-10-17 (#868). The scrape took 1,145 s
for 178 tickers on the measured run (``apify_etf_fetcher.py``) and its budget is
up to 2,400 s, all of it before ANALYZE, the analytical apply and the deploy
hook. Like B3 events, the market data and the FNET register, it now runs after
the hook: daily_ingest.yml, job ``etf-market``, and the watchdog's matching
recovery step.

Same contract as it had in run_daily. Not a CVM source: it reads its tickers
from the stored ``cvm_etf_registry``, so it never waits for the CVM probe.
``APIFY_TOKEN`` unset skips the scrape and is not a failure.
``ingest_etf_market`` writes a ``skipped`` audit row and returns 0 when Apify
never delivered a dataset (403 / 408 / ABORTED / usage limit); a scrape that ran
and returned bad or empty data raises, and this process exits non-zero.

    python -m src.pipeline.run_etf_market

Required env vars: POSTGRES_URL. Optional: APIFY_TOKEN.
"""

import asyncio
import logging
import os

from src.pipeline.ingest_etf_market import ingest_etf_market
from src.store.pg_client import get_pg_client

logger = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    if not os.getenv("APIFY_TOKEN"):
        logger.info("APIFY_TOKEN unset — skipping ETF market scrape")
        return
    try:
        rows = await ingest_etf_market(get_pg_client())
    except Exception as exc:
        logger.error("ETF market scrape failed: %s", exc, exc_info=True)
        raise SystemExit(1)
    logger.info("ETF market snapshot done — %d rows upserted", rows)


if __name__ == "__main__":
    asyncio.run(main())
