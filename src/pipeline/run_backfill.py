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

    # B3 COTAHIST yearly zips (opt-in — large)
    python -m src.pipeline.run_backfill --b3-only --b3-start-year 2019

Required env vars: POSTGRES_URL
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
from src.pipeline.b3_pipeline import B3Ingestor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("run_backfill")


async def main(args: argparse.Namespace) -> None:
    totals: dict = {}
    start_ts = time.monotonic()

    if not args.bacen_only and not args.b3_only:
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

    if not args.cvm_only and not args.b3_only:
        logger.info("Starting BACEN backfill: start=%s", args.bacen_start)
        bacen_ingestor = BacenIngestor()
        bacen_totals = await bacen_ingestor.backfill(start=args.bacen_start)
        totals.update(bacen_totals)

    # Yearly COTAHIST zips are large (options + cash). Opt-in only so a default
    # CVM+BACEN backfill does not stall on millions of B3 rows.
    if args.b3_only or args.include_b3:
        logger.info(
            "Starting B3 COTAHIST backfill: start_year=%d end_year=%s",
            args.b3_start_year,
            args.end_year,
        )
        b3_ingestor = B3Ingestor()
        b3_totals = await b3_ingestor.backfill(
            start_year=args.b3_start_year,
            end_year=args.end_year,
        )
        totals.update(b3_totals)

    elapsed = time.monotonic() - start_ts
    total_rows = sum(totals.values())
    logger.info(
        "Backfill complete in %.1fs — %d total rows: %s",
        elapsed, total_rows, totals,
    )
    ensure_rows_landed(total_rows)


def ensure_rows_landed(total_rows: int) -> None:
    """Fail the process when a backfill upserts nothing.

    A backfill exists to land rows; zero across every slice means every fetch
    failed (e.g. CVM refusing the runner's IP — the 2026-06-10 run spent 4h
    failing each download, printed "0 total rows", and exited 0, so CI showed
    green while the 2024/2025 partitions stayed empty). Exiting non-zero makes
    that visible in CI instead of masquerading as success. Re-running over
    already-complete years still lands rows (idempotent ON CONFLICT upserts
    count them), so this only trips when nothing was ingested at all.
    """
    if total_rows == 0:
        logger.error(
            "Backfill upserted 0 rows across all slices — treating as failure "
            "(every fetch likely failed; check network/CVM availability)"
        )
        sys.exit(1)


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
        choices=["fi", "fidc", "fip", "fiagro", "fii", "securit", "cia_aberta", "etf"],
        help="Limit CVM download to one entity (fi | fidc | fip | fiagro | fii | securit | cia_aberta | etf)"
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
    parser.add_argument(
        "--include-b3", action="store_true",
        help="Also backfill B3 COTAHIST yearly quotation zips (large)"
    )
    parser.add_argument(
        "--b3-only", action="store_true",
        help="Skip CVM and BACEN; backfill only B3 COTAHIST yearly zips"
    )
    parser.add_argument(
        "--b3-start-year", type=int, default=2019,
        help="First year of B3 COTAHIST yearly zips (default: 2019)"
    )
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
