"""
Full historical backfill CLI.

Usage:
    # All entities and BACEN, from 2019 to today
    python -m src.pipeline.run_backfill

    # CVM only, starting 2022
    python -m src.pipeline.run_backfill --start-year 2022 --cvm-only

    # Single entity
    python -m src.pipeline.run_backfill --entity fidc --start-year 2023

    # One FI document type only (safe gap repair)
    python -m src.pipeline.run_backfill --entity fi --doc-type balancete --start-year 2021

    # Repair named months of one FI document type (nothing else refetched)
    python -m src.pipeline.run_backfill --cvm-only --entity fi --doc-type balancete \
        --months 2019-04,2019-07,2023-01

    # Or let it find the gaps itself
    python -m src.pipeline.run_backfill --cvm-only --entity fi --doc-type balancete --repair-gaps

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
import re
import sys
import time
from typing import List, Optional, Sequence, Tuple

# Allow running as python -m src.pipeline.run_backfill from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.pipeline.cvm_pipeline import CVMIngestor
from src.pipeline.gaps import missing_fi_months
from src.pipeline.bacen_pipeline import BacenIngestor
from src.pipeline.b3_pipeline import B3Ingestor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("run_backfill")


async def main(args: argparse.Namespace) -> None:
    totals: dict = {}
    cvm_failures: list = []
    start_ts = time.monotonic()
    doc_type = getattr(args, "doc_type", None)
    if doc_type and args.entity != "fi":
        raise SystemExit("--doc-type requires --entity fi")
    if (getattr(args, "months", None) or getattr(args, "repair_gaps", False)) and not doc_type:
        raise SystemExit("--months / --repair-gaps require --entity fi --doc-type <t>")

    if not args.bacen_only and not args.b3_only:
        logger.info(
            "Starting CVM backfill: start_year=%d entity=%s doc_type=%s",
            args.start_year,
            args.entity or "all",
            doc_type or "all",
        )
        ingestor = CVMIngestor()

        months = parse_months(getattr(args, "months", None))
        if getattr(args, "repair_gaps", False):
            if months:
                raise SystemExit("--repair-gaps and --months are mutually exclusive")
            months = [
                (g.year, g.month)
                for g in missing_fi_months(
                    ingestor._supabase, doc_type,
                    start_year=args.start_year, end_year=args.end_year,
                )
            ]
            if not months:
                logger.info(
                    "No fi/%s gaps between %d and %s — nothing to repair.",
                    doc_type, args.start_year, args.end_year or "today",
                )
                return
        if months is not None and not months:
            raise SystemExit("--months matched no slices")

        cvm_totals = await ingestor.backfill(
            start_year=args.start_year,
            end_year=args.end_year,
            entity_filter=args.entity,
            doc_type_filter=doc_type,
            months=months,
        )
        totals.update(cvm_totals)
        cvm_failures = list(ingestor.failures)

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
    ensure_no_failed_slices(cvm_failures)


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


def parse_months(raw: Optional[str]) -> Optional[List[Tuple[int, int]]]:
    """Parse "2019-04,2019-07,2023-01" into [(2019, 4), (2019, 7), (2023, 1)].

    Returns None when nothing was requested (the normal full-range backfill).
    Raises SystemExit on anything malformed: a repair run is aimed at named
    slices, and silently dropping one the operator listed would leave a gap
    they believe is closed.
    """
    if raw is None:
        return None
    months: List[Tuple[int, int]] = []
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        match = re.fullmatch(r"(\d{4})-(\d{1,2})", token)
        if not match:
            raise SystemExit(
                f"--months: {token!r} is not YYYY-MM (e.g. 2019-04,2023-01)"
            )
        year, month = int(match.group(1)), int(match.group(2))
        if not 1 <= month <= 12:
            raise SystemExit(f"--months: {token!r} has no month {month}")
        months.append((year, month))
    return sorted(set(months))


def ensure_no_failed_slices(failures: Sequence) -> None:
    """Fail the process when any requested slice ended in 'error'.

    ensure_rows_landed() only catches the all-zero case. The 2026-08-27
    balancete backfill upserted ~81.7M rows and exited 0 while 32 monthly
    slices had failed — every ingest_* method catches its own exception, writes
    the audit row and returns 0, so the totals looked healthy and CI was green.
    A backfill that did not load what it was asked to load is a failed backfill.

    'skipped' slices (CVM 404 for a month that is not published yet) are not in
    the ledger and never fail a run — see CVMIngestor._record_failure.
    """
    if not failures:
        return
    logger.error(
        "Backfill finished with %d failed slice(s) — the rows it did upsert "
        "are real, but the requested range is incomplete:", len(failures),
    )
    for failure in failures:
        logger.error("  %s", failure)
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
        "--doc-type",
        choices=["inf_diario", "cda", "cda_acoes", "cda_cotas", "cda_debentures",
                 "perfil_mensal", "balancete"],
        default=None,
        help="Limit an --entity fi backfill to one document type",
    )
    parser.add_argument(
        "--months", type=str, default=None,
        help=(
            "Repair only these competency months, comma-separated YYYY-MM "
            "(e.g. 2019-04,2023-01). Requires --entity fi --doc-type; replaces "
            "the year range for the FI monthly loop so nothing else is refetched."
        ),
    )
    parser.add_argument(
        "--repair-gaps", action="store_true",
        help=(
            "Resolve --months automatically: every published month with no rows "
            "in the --doc-type table. Requires --entity fi --doc-type."
        ),
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
