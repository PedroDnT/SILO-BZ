"""
Full historical backfill CLI.

Usage:
    # All entities and BACEN, from 2019 to today
    python -m src.pipeline.run_backfill

    # CVM only, starting 2022
    python -m src.pipeline.run_backfill --start-year 2022 --cvm-only

    # Single entity
    python -m src.pipeline.run_backfill --entity fidc --start-year 2023

    # BACEN only
    python -m src.pipeline.run_backfill --bacen-only --bacen-start 2020-01-01

Required env vars: SUPABASE_URL, SUPABASE_SERVICE_KEY
"""

import argparse
import asyncio
import logging
import os
import sys
import time

# Allow running as python -m src.pipeline.run_backfill from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.pipeline.cvm_pipeline import CVMIngestor
from src.pipeline.bacen_pipeline import BacenIngestor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("run_backfill")


async def main(args: argparse.Namespace) -> None:
    totals: dict = {}
    start_ts = time.monotonic()

    if not args.bacen_only:
        logger.info(
            "Starting CVM backfill: start_year=%d entity=%s",
            args.start_year,
            args.entity or "all",
        )
        ingestor = CVMIngestor()
        cvm_totals = await ingestor.backfill(
            start_year=args.start_year,
            end_year=args.end_year,
            entity_filter=args.entity,
        )
        totals.update(cvm_totals)

    if not args.cvm_only:
        logger.info("Starting BACEN backfill: start=%s", args.bacen_start)
        bacen_ingestor = BacenIngestor()
        bacen_totals = await bacen_ingestor.backfill(start=args.bacen_start)
        totals.update(bacen_totals)

    elapsed = time.monotonic() - start_ts
    total_rows = sum(totals.values())
    logger.info(
        "Backfill complete in %.1fs — %d total rows: %s",
        elapsed, total_rows, totals,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Full historical CVM + BACEN backfill")
    parser.add_argument(
        "--start-year", type=int, default=2019,
        help="First year to download (default: 2019)"
    )
    parser.add_argument(
        "--end-year", type=int, default=None,
        help="Last year (inclusive, default: current year)"
    )
    parser.add_argument(
        "--entity", type=str, default=None,
        choices=["fi", "fidc", "fip", "fiagro", "fii", "securit"],
        help="Limit CVM download to one entity (fi | fidc | fip | fiagro | fii | securit)"
    )
    parser.add_argument(
        "--bacen-start", type=str, default="2019-01-01",
        help="Start date for BACEN data (ISO format, default: 2019-01-01)"
    )
    parser.add_argument(
        "--cvm-only", action="store_true",
        help="Skip BACEN ingestion"
    )
    parser.add_argument(
        "--bacen-only", action="store_true",
        help="Skip CVM ingestion"
    )
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
