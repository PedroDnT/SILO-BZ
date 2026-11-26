"""Delete the day-1 rows of cvm_fi_perfil that have a twin later in the month (#1121).

The source publishes the investor profile dated on the last day of the month,
and that date is the stored `period`. Until #1121 the ingest stamped a row with
no parseable date with the first of the month, so an early file version left
9,204 rows on day 1 (9,199 in 2026-09, 5 in 2026-08). Once the month is
re-ingested the same fund has its real row at month-end, and the day-1 row is a
duplicate of the fund-month.

Month by month, this script:

- deletes a day-1 row only when the same fund has a row on another day of that
  month, in one transaction per month, and prints the month's row count before
  and after;
- lists the day-1 rows with no twin and leaves them alone (that fund would lose
  its only row of the month);
- counts the fund-months with rows on 2 or more dates that are not day 1, and
  leaves them alone too.

It reports only, unless --apply is given. Running it twice is safe: the second
run finds no twinned day-1 row and deletes nothing. No row is rewritten and no
period is re-keyed. Every query is bounded to one month of `period`.

Run it after the re-ingest of the affected months, dry run first:

    python scripts/drop_perfil_day1_twins.py --start 2026-08 --end 2026-09 --dry-run
    python scripts/drop_perfil_day1_twins.py --start 2026-08 --end 2026-09 --apply
    python scripts/drop_perfil_day1_twins.py                 # report on every month from 2019-01

Needs POSTGRES_URL; the connection comes from src.store.pg_client.
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterator, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logger = logging.getLogger("drop_perfil_day1_twins")

TABLE = "cvm_fi_perfil"
FIRST_MONTH = (2019, 1)   # the table starts here
LIST_LIMIT = 50

# Every statement names one month: [first, next_first).
MONTH_ROWS_SQL = f"""
SELECT count(*) FROM {TABLE}
WHERE period >= %(first)s AND period < %(next_first)s
"""

DAY1_ROWS_SQL = f"""
SELECT count(*) FROM {TABLE}
WHERE period = %(first)s
"""

# A day-1 row is a twin when the same fund has a row on another day of the month.
_HAS_TWIN = f"""
EXISTS (
    SELECT 1 FROM {TABLE} o
    WHERE o.cnpj = d.cnpj
      AND o.period > %(first)s AND o.period < %(next_first)s
)
"""

TWINNED_SQL = f"""
SELECT count(*) FROM {TABLE} d
WHERE d.period = %(first)s
  AND {_HAS_TWIN}
"""

LONE_SQL = f"""
SELECT d.cnpj FROM {TABLE} d
WHERE d.period = %(first)s
  AND NOT {_HAS_TWIN}
ORDER BY d.cnpj
LIMIT %(limit)s
"""

# Reported, never changed: a fund with rows on 2+ dates that are not day 1.
MULTI_DATE_SQL = f"""
SELECT count(*) FROM (
    SELECT cnpj FROM {TABLE}
    WHERE period > %(first)s AND period < %(next_first)s
    GROUP BY cnpj
    HAVING count(*) > 1
) m
"""

DELETE_SQL = f"""
DELETE FROM {TABLE} d
WHERE d.period = %(first)s
  AND {_HAS_TWIN}
"""


@dataclass
class MonthReport:
    first: date
    rows_before: int = 0
    rows_after: int = 0
    day1: int = 0
    twinned: int = 0
    lone: int = 0
    lone_cnpjs: List[str] = field(default_factory=list)
    multi_date: int = 0
    deleted: int = 0


def next_month(first: date) -> date:
    return date(first.year + (first.month == 12), first.month % 12 + 1, 1)


def months(start: date, end: date) -> Iterator[date]:
    """First days of start..end, both included."""
    cur = start
    while cur <= end:
        yield cur
        cur = next_month(cur)


def parse_month(raw: str) -> date:
    try:
        year, month = raw.split("-")
        return date(int(year), int(month), 1)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{raw!r} is not YYYY-MM (e.g. 2026-09)")


def _count(cur: Any, sql: str, params: dict) -> int:
    cur.execute(sql, params)
    return int(cur.fetchone()[0])


def process_month(client: Any, first: date, *, apply: bool, list_limit: int = LIST_LIMIT) -> MonthReport:
    """Report one month and, with apply, delete its twinned day-1 rows.

    The delete and its checks are one transaction: the number of rows deleted
    must equal the number of twinned day-1 rows counted just before, and the
    month must shrink by exactly that much, or the month is rolled back.
    """
    params = {"first": first, "next_first": next_month(first)}
    rep = MonthReport(first=first)
    with client.cursor() as cur:
        rep.rows_before = rep.rows_after = _count(cur, MONTH_ROWS_SQL, params)
        rep.multi_date = _count(cur, MULTI_DATE_SQL, params)
        rep.day1 = _count(cur, DAY1_ROWS_SQL, params)
        if not rep.day1:
            return rep
        rep.twinned = _count(cur, TWINNED_SQL, params)
        rep.lone = rep.day1 - rep.twinned
        if rep.lone:
            cur.execute(LONE_SQL, {**params, "limit": list_limit})
            rep.lone_cnpjs = [r[0] for r in cur.fetchall()]
        if not (apply and rep.twinned):
            return rep

        cur.execute("BEGIN")
        try:
            twinned = _count(cur, TWINNED_SQL, params)
            cur.execute(DELETE_SQL, params)
            deleted = cur.rowcount
            if deleted != twinned:
                raise RuntimeError(
                    f"{TABLE} {first:%Y-%m}: deleted {deleted} rows but {twinned} "
                    "day-1 rows had a twin; rolled back"
                )
            after = _count(cur, MONTH_ROWS_SQL, params)
            left = _count(cur, TWINNED_SQL, params)
            if after != rep.rows_before - deleted or left:
                raise RuntimeError(
                    f"{TABLE} {first:%Y-%m}: {rep.rows_before} rows before, {after} after "
                    f"a delete of {deleted}, {left} twinned day-1 rows left; rolled back"
                )
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise
        rep.deleted, rep.rows_after = deleted, after
    return rep


def log_month(rep: MonthReport, *, apply: bool) -> None:
    month = f"{rep.first:%Y-%m}"
    if rep.day1:
        action = f"deleted {rep.deleted}" if apply else f"would delete {rep.twinned}"
        logger.info(
            "%s: %d rows before, %d after; %d on day 1 (%d with a twin, %d without); %s",
            month, rep.rows_before, rep.rows_after, rep.day1, rep.twinned, rep.lone, action,
        )
    if rep.lone:
        shown = ", ".join(rep.lone_cnpjs)
        more = rep.lone - len(rep.lone_cnpjs)
        logger.info(
            "%s: day-1 rows with no twin, left alone (%d): %s%s",
            month, rep.lone, shown, f" ... and {more} more" if more > 0 else "",
        )
    if rep.multi_date:
        logger.info(
            "%s: %d fund-months with rows on 2+ dates that are not day 1, left alone",
            month, rep.multi_date,
        )


def run(client: Any, start: date, end: date, *, apply: bool,
        list_limit: int = LIST_LIMIT) -> List[MonthReport]:
    reports = []
    for first in months(start, end):
        rep = process_month(client, first, apply=apply, list_limit=list_limit)
        log_month(rep, apply=apply)
        reports.append(rep)
    logger.info(
        "%s %s..%s (%s): %d rows before, %d after; day-1 rows: %d with a twin, "
        "%d without (left alone); %d deleted; %d fund-months on 2+ other dates (left alone)",
        TABLE, f"{start:%Y-%m}", f"{end:%Y-%m}", "applied" if apply else "dry run",
        sum(r.rows_before for r in reports), sum(r.rows_after for r in reports),
        sum(r.twinned for r in reports), sum(r.lone for r in reports),
        sum(r.deleted for r in reports), sum(r.multi_date for r in reports),
    )
    return reports


def parse_args(argv: Optional[List[str]] = None) -> Tuple[argparse.Namespace, date, date]:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--start", type=parse_month, default=date(*FIRST_MONTH, 1),
                    help="first month, YYYY-MM (default: 2019-01)")
    ap.add_argument("--end", type=parse_month, default=None,
                    help="last month, YYYY-MM (default: the current month)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="report only; this is the default")
    mode.add_argument("--apply", action="store_true",
                      help="delete the day-1 rows that have a twin")
    ap.add_argument("--list-limit", type=int, default=LIST_LIMIT,
                    help=f"how many untwinned funds to name per month (default: {LIST_LIMIT})")
    args = ap.parse_args(argv)
    end = args.end or date.today().replace(day=1)
    if end < args.start:
        ap.error("--end is before --start")
    if args.list_limit < 0:
        ap.error("--list-limit cannot be negative")
    return args, args.start, end


def main(argv: Optional[List[str]] = None) -> int:
    args, start, end = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from src.store.pg_client import get_pg_client

    client = get_pg_client()
    try:
        run(client, start, end, apply=args.apply, list_limit=args.list_limit)
    finally:
        client.closeall()
    return 0


if __name__ == "__main__":
    sys.exit(main())
