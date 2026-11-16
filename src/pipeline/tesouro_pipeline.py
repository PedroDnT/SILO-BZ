"""
Tesouro Direto ingestor — the Treasury's daily posted rates and prices per
title into ``tesouro_direto_daily``.

Fetching and parsing are src/fetchers/tesouro_direto_fetcher.py; audit rows go
through src/pipeline/ingest_log under entity ``tesouro`` / doc_type
``td_precos`` (one row per run).

The source is one CSV with the whole history (~180k rows), so both modes
download the same file. The daily mode upserts only the base dates of the last
``DAILY_LOOKBACK_DAYS`` days: that lands the new session, heals a missed day and
picks up a recent revision without rewriting 20 years of rows every morning.
The backfill upserts every row.

    python -m src.pipeline.tesouro_pipeline            # daily window
    python -m src.pipeline.tesouro_pipeline --backfill # whole history
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import date, timedelta
from typing import Dict, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.fetchers.tesouro_direto_fetcher import fetch_csv, parse_csv  # noqa: E402
from src.pipeline.ingest_log import audited  # noqa: E402
from src.store.pg_client import get_pg_client, upsert_rows  # noqa: E402

logger = logging.getLogger(__name__)

TABLE = "tesouro_direto_daily"
CONFLICT_COLUMNS = "tipo_titulo,data_vencimento,data_base"
LOG_ENTITY = "tesouro"
LOG_DOC_TYPE = "td_precos"

# 30 calendar days: about 20 sessions. The file is published the business day
# after each session, so a week of missed runs still heals.
DAILY_LOOKBACK_DAYS = 30


class TesouroIngestor:
    """Downloads the Tesouro Direto file and upserts it.

    Example::

        await TesouroIngestor().daily_update()
    """

    def __init__(self) -> None:
        self._pg = get_pg_client()

    async def ingest(self, since: Optional[date]) -> int:
        raw = await fetch_csv()
        rows, dropped = parse_csv(raw, since=since)
        if dropped:
            logger.warning("Tesouro Direto: %d row(s) failed validation and were dropped", dropped)
        n = upsert_rows(self._pg, TABLE, rows, conflict_columns=CONFLICT_COLUMNS)
        logger.info("Tesouro Direto since=%s: %d rows", since or "all", n)
        return n

    async def _run(self, since: Optional[date], label: str) -> Dict[str, int]:
        anchor = since or date.today()
        rows = await audited(
            self._pg, LOG_ENTITY, LOG_DOC_TYPE,
            lambda: self.ingest(since),
            period_year=anchor.year, period_month=anchor.month,
        )
        logger.info("Tesouro Direto %s done: %s=%d", label, TABLE, rows)
        return {TABLE: rows}

    async def daily_update(self) -> Dict[str, int]:
        """Base dates of the last ``DAILY_LOOKBACK_DAYS`` days."""
        return await self._run(date.today() - timedelta(days=DAILY_LOOKBACK_DAYS), "daily")

    async def backfill(self) -> Dict[str, int]:
        """Every row of the file, from 2004-12-31."""
        return await self._run(None, "backfill")


def main(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--backfill", action="store_true", help="Upsert the whole history")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    ingestor = TesouroIngestor()
    asyncio.run(ingestor.backfill() if args.backfill else ingestor.daily_update())


if __name__ == "__main__":
    main()
