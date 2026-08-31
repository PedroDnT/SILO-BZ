"""Find monthly slices that are missing from a landing table.

Why this reads the table and not `cvm_ingest_log`
-------------------------------------------------
The audit log records *attempts*, so its latest row for a slice is the latest
attempt — not the state of the data. On 2026-08-27 `fi/balancete` 2026-06 had a
fresh `error` / `TimeoutError` row while the table held 2,178,163 rows from an
earlier `ok` attempt. Gap detection keyed on the newest audit row would have
re-fetched a complete month, and a "fail while any slice is not ok" gate keyed
on the same would never go green.

So: the table is the ground truth for *what we have*, and the audit log is used
for exactly one thing the table cannot express — telling a month CVM has not
published yet (`skipped`, from a 404) apart from a month we failed to load.
A month that does not exist upstream is not a gap.

The probe is one `EXISTS` per month, which rides the table's `dt_comptc` index.
Do not replace it with a `GROUP BY date_trunc('month', ...)` over the whole
table: `cvm_fi_balancete` is 111M rows / 24 GB and unpartitioned.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# doc_type -> (table, date column). Only FI monthly documents; these are the
# ones run_backfill can repair a month at a time via --doc-type.
FI_MONTHLY_TABLES: Dict[str, Tuple[str, str]] = {
    "balancete":     ("cvm_fi_balancete", "dt_comptc"),
    "inf_diario":    ("cvm_fi_diario",    "dt_comptc"),
    "perfil_mensal": ("cvm_fi_perfil",    "period"),
    "cda":           ("cvm_fi_cda",       "period"),
    # CDA blocks 4 and 2 — holdings, not the aggregate. Same competency grain as
    # `cda` (first-of-month `period`), but separate tables, so a gap in one says
    # nothing about the others and each is repaired on its own.
    "cda_acoes":     ("cvm_fi_cda_acoes",  "period"),
    "cda_cotas":     ("cvm_fi_cda_cotas",  "period"),
}

# CVM publishes a competency month one to two months late. Probing months that
# cannot exist yet would report permanent phantom gaps, so the scan stops here.
PUBLICATION_LAG_MONTHS = 2


@dataclass(frozen=True)
class MonthGap:
    year: int
    month: int

    def __str__(self) -> str:
        return f"{self.year}-{self.month:02d}"


def _month_range(
    start_year: int, end_year: int, today: date, lag_months: int,
) -> List[Tuple[int, int]]:
    """Every (year, month) from start_year to the newest plausibly published."""
    cutoff_y, cutoff_m = today.year, today.month
    for _ in range(lag_months):
        cutoff_m -= 1
        if cutoff_m == 0:
            cutoff_y, cutoff_m = cutoff_y - 1, 12

    months: List[Tuple[int, int]] = []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            if (year, month) > (cutoff_y, cutoff_m):
                break
            months.append((year, month))
    return months


def _skipped_months(client: Any, doc_type: str) -> set:
    """Months whose only recorded outcome is 'skipped' (CVM 404 — unpublished).

    A month with any 'ok' or 'error' row is a month CVM served at least once, so
    it is fair game for repair. One with nothing but 'skipped' does not exist
    upstream and must not be reported as a gap.
    """
    with client.cursor() as cur:
        cur.execute(
            """
            SELECT period_year, period_month
            FROM cvm_ingest_log
            WHERE entity = 'fi' AND doc_type = %s
              AND period_year IS NOT NULL AND period_month IS NOT NULL
            GROUP BY period_year, period_month
            HAVING bool_and(status = 'skipped')
            """,
            (doc_type,),
        )
        return {(int(y), int(m)) for y, m in cur.fetchall()}


def missing_fi_months(
    client: Any,
    doc_type: str,
    start_year: int = 2019,
    end_year: Optional[int] = None,
    today: Optional[date] = None,
) -> List[MonthGap]:
    """Published months with no rows in the doc_type's landing table.

    Args:
        client:     _PgClient from src.store.pg_client.
        doc_type:   one of FI_MONTHLY_TABLES.
        start_year: first year to probe.
        end_year:   last year to probe (default: current year).
        today:      injectable for tests.

    Returns:
        MonthGap per missing month, oldest first.
    """
    if doc_type not in FI_MONTHLY_TABLES:
        raise ValueError(
            f"unsupported doc_type {doc_type!r}; "
            f"expected one of {sorted(FI_MONTHLY_TABLES)}"
        )

    table, date_col = FI_MONTHLY_TABLES[doc_type]
    today = today or date.today()
    end_year = end_year or today.year

    unpublished = _skipped_months(client, doc_type)
    gaps: List[MonthGap] = []

    for year, month in _month_range(start_year, end_year, today, PUBLICATION_LAG_MONTHS):
        if (year, month) in unpublished:
            continue
        first = date(year, month, 1)
        nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        # EXISTS, not COUNT: we only need "is this month present", and the
        # index lookup stops at the first row instead of walking ~2M of them.
        # Table and column come from FI_MONTHLY_TABLES, never from user input.
        with client.cursor() as cur:
            cur.execute(
                f"SELECT EXISTS (SELECT 1 FROM {table} "
                f"WHERE {date_col} >= %s AND {date_col} < %s)",
                (first, nxt),
            )
            if not cur.fetchone()[0]:
                gaps.append(MonthGap(year, month))

    logger.info(
        "gap scan fi/%s %d-%d: %d missing month(s)%s",
        doc_type, start_year, end_year, len(gaps),
        f" — {', '.join(str(g) for g in gaps)}" if gaps else "",
    )
    return gaps
