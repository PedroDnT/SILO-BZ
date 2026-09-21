"""
IBGE ingestor — the IPCA item tree (variation, weight, YTD and 12-month
accumulation for the general index, 9 groups, 19 subgroups, 51 items and
~377 subitems) from SIDRA tables 1419 and 7060 into ``ibge_ipca_item_monthly``.

Fetching and parsing are src/fetchers/ibge_sidra_fetcher.py; audit rows go
through src/pipeline/ingest_log under entity ``ibge`` / doc_type ``ipca_item``
(one row per orchestrated run, keyed on the window's start month like BACEN).

Why a second inflation source next to BACEN's SGS: SGS carries the group
VARIATIONS but not the WEIGHTS, and "what is moving the index" is weight ×
variation. IBGE publishes both, at item level, with the 12-month figure as
published rather than chained — so the served contribution is arithmetic on
two published numbers, never an estimate.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import date
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.fetchers.ibge_sidra_fetcher import (  # noqa: E402
    fetch_ipca_items, parse_ipca_items, table_windows,
)
from src.pipeline.ingest_log import audited  # noqa: E402
from src.store.pg_client import get_pg_client, upsert_rows  # noqa: E402

logger = logging.getLogger(__name__)

TABLE = "ibge_ipca_item_monthly"
CONFLICT_COLUMNS = "reference_month,item_code"
LOG_ENTITY = "ibge"
LOG_DOC_TYPE = "ipca_item"

# Where SIDRA's item-level history begins (table 1419). There is no earlier
# item tree with weights on SIDRA; BACEN's SGS groups (no weights) go back to
# 1991 and are the series to read before this date.
DEFAULT_START = "2012-01-01"


def _first_of_month(d: date) -> date:
    return d.replace(day=1)


def _previous_month(d: date) -> date:
    first = _first_of_month(d)
    return date(first.year - 1, 12, 1) if first.month == 1 else date(first.year, first.month - 1, 1)


class IbgeIngestor:
    """Downloads the IPCA item tree from SIDRA and upserts it.

    Example::

        ingestor = IbgeIngestor()
        await ingestor.backfill(start="2012-01-01")
    """

    def __init__(self) -> None:
        self._pg = get_pg_client()

    async def ingest_items(self, start: date, end: date) -> int:
        """Fetch every table window covering ``start..end`` and upsert.

        A window IBGE has not published yet returns the header row only and
        contributes 0 rows — visible in the log, never an error. A fetch that
        fails raises (after the fetcher's retries) and takes the audit row
        to ``error``.
        """
        total = 0
        plan = table_windows(start, end)
        if not plan:
            logger.warning("IBGE IPCA: no SIDRA table covers %s..%s", start, end)
            return 0
        for table, period_from, period_to in plan:
            observations = await fetch_ipca_items(table, period_from, period_to)
            if not observations:
                logger.warning(
                    "IBGE IPCA t/%s %s..%s: not published yet (header only)",
                    table, period_from, period_to,
                )
                continue
            rows, skipped = parse_ipca_items(observations, table)
            if skipped:
                logger.info(
                    "IBGE IPCA t/%s %s..%s: %d observation(s) outside the table's structure skipped",
                    table, period_from, period_to, skipped,
                )
            if not rows:
                continue
            n = upsert_rows(self._pg, TABLE, rows, conflict_columns=CONFLICT_COLUMNS)
            logger.info("IBGE IPCA t/%s %s..%s: %d rows", table, period_from, period_to, n)
            total += n
        return total

    async def _run(self, start: date, end: date, label: str) -> Dict[str, int]:
        rows = await audited(
            self._pg, LOG_ENTITY, LOG_DOC_TYPE,
            lambda: self.ingest_items(start, end),
            period_year=start.year, period_month=start.month,
        )
        logger.info("IBGE IPCA %s done: %s=%d", label, TABLE, rows)
        return {TABLE: rows}

    async def daily_update(self) -> Dict[str, int]:
        """Previous month + current month.

        IBGE releases month M around the 10th of M+1, so the previous month
        is the one that usually lands; the current month is asked for so a
        release is never missed by a day, and answers header-only until it
        is out.
        """
        today = date.today()
        return await self._run(_previous_month(today), _first_of_month(today), "daily")

    async def backfill(self, start: str = DEFAULT_START) -> Dict[str, int]:
        """Everything from ``start`` (ISO date) to the current month."""
        return await self._run(
            _first_of_month(date.fromisoformat(start[:10])),
            _first_of_month(date.today()),
            "backfill",
        )
