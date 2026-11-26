"""Divide the stored per-share lines of cia_account by the scale the ingest applied (#1115).

Until #1115 the listed-company ingest multiplied every VL_CONTA by its
ESCALA_MOEDA factor (MIL = 1,000). The per-share accounts, `3.99` and every
account under `3.99.` (earnings per share), are published in reais per share,
so they were stored 1,000 times too large: 3240.00 for a basic EPS of 3.24.
The ingest no longer multiplies them. This script corrects the rows already
stored, once.

What it changes: `vl_conta` of the rows with `cd_conta = '3.99'` or under
`3.99.`, a scale the ingest multiplied by (the factors come from
`_MONEY_SCALE` in src/pipeline/ingest_cia.py: MIL 1,000, MILHAO 1,000,000) and
a value that is not NULL and not zero. Nothing else: UNIDADE rows, rows with an
unknown or missing scale (the ingest multiplied those by 1) and every other
account are left alone. `escala_moeda` is not rewritten.

It runs ONCE. A second run would divide rows that are already right, and
cia_account has no timestamp to tell them apart, so:

- each `dt_refer` year is one transaction that first writes that year's row in
  the marker table `cia_account_eps_scale_fix` and then updates the year; the
  two commit together or not at all;
- `--apply` with any marker row present exits 2 and changes nothing. After a
  run that stopped half way, `--apply --resume` does the years with no marker
  row and never touches a marked one;
- it refuses while `cvm_ingest_log` shows an ITR or DFP slice written by the
  fixed ingest (`parser_version` 3 or later): those rows are already unscaled.
  `raw` cannot tell, because it holds no copy of the published value. So the
  order is: merge the ingest fix, then run this before the next ingest;
- it refuses when a row it should change lies outside the year range.

`vl_conta` is NUMERIC(28,2), so the corrected value keeps 2 decimals: 551.23
(a published 0.55123) becomes 0.55. The report counts the rows that lose
digits this way and the ones that become 0.00, and `--apply` refuses them
unless `--accept-rounding` is given. The fixed ingest rounds the same way.

It reports only, unless --apply is given. The report prints, per year, the
per-share rows by scale, the rows to change and 5 sample rows (cd_cvm,
dt_refer, cd_conta, old value, new value). Every query is bounded to one year
of `dt_refer`, except the two that look outside the range.

    python scripts/fix_cia_eps_scale.py --dry-run
    python scripts/fix_cia_eps_scale.py --apply
    python scripts/fix_cia_eps_scale.py --apply --accept-rounding
    python scripts/fix_cia_eps_scale.py --apply --resume      # after a failed run only

Needs POSTGRES_URL; the connection comes from src.store.pg_client. `--apply`
creates the marker table (CREATE TABLE IF NOT EXISTS, row level security on,
no grant to anon or authenticated).
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.pipeline.ingest_cia import _MONEY_SCALE  # noqa: E402

logger = logging.getLogger("fix_cia_eps_scale")

TABLE = "cia_account"
MARKER = "cia_account_eps_scale_fix"
LOG_TABLE = "cvm_ingest_log"
FIRST_YEAR = 2010            # the first partition of cia_account
SAMPLE_LIMIT = 5
#: PARSER_VERSION of the ingest that stopped scaling the per-share accounts.
FIXED_PARSER_VERSION = 3
EXIT_REFUSED = 2
BRASILIA = timezone(timedelta(hours=-3))    # no daylight saving since 2019

#: Scale token -> the integer the ingest multiplied by. A factor of 1 changed
#: nothing, so those scales are not corrected.
FACTORS: Dict[str, int] = {k: int(v) for k, v in _MONEY_SCALE.items() if v != 1}

_SCALE_KEY = "upper(trim(escala_moeda))"
_SCALES_IN = ", ".join(f"'{k}'" for k in FACTORS)
FACTOR_SQL = "CASE {key} {whens} END".format(
    key=_SCALE_KEY, whens=" ".join(f"WHEN '{k}' THEN {f}" for k, f in FACTORS.items()),
)
# '3.99' and everything under '3.99.'; never '3.990' or '3.9'. No LIKE, so the
# statements carry no % for the driver to trip over.
PER_SHARE_SQL = "(cd_conta = '3.99' OR left(cd_conta, 5) = '3.99.')"
NEW_VALUE_SQL = f"CAST(round(vl_conta / ({FACTOR_SQL}), 2) AS NUMERIC(28,2))"
_YEAR = "dt_refer >= %(lo)s AND dt_refer < %(hi)s"
# The rows the correction changes.
CANDIDATE_SQL = (
    f"{PER_SHARE_SQL} AND {_SCALE_KEY} IN ({_SCALES_IN})"
    " AND vl_conta IS NOT NULL AND vl_conta <> 0"
)

# Every per-share row of the year by the scale as stored: what is there, and
# which of it has a value to change.
SCALES_SQL = f"""
SELECT escala_moeda, count(*),
       count(*) FILTER (WHERE vl_conta IS NOT NULL AND vl_conta <> 0)
FROM {TABLE}
WHERE {_YEAR} AND {PER_SHARE_SQL}
GROUP BY escala_moeda
ORDER BY escala_moeda
"""

CANDIDATES_SQL = f"""
SELECT count(*),
       count(*) FILTER (WHERE {NEW_VALUE_SQL} * ({FACTOR_SQL}) <> vl_conta),
       count(*) FILTER (WHERE {NEW_VALUE_SQL} = 0),
       sum(vl_conta), sum({NEW_VALUE_SQL})
FROM {TABLE}
WHERE {_YEAR} AND {CANDIDATE_SQL}
"""

# After the update: the same rows, zero or not (a row rounded to 0.00 is still one of them).
SCALED_SUM_SQL = f"""
SELECT count(*), sum(vl_conta)
FROM {TABLE}
WHERE {_YEAR} AND {PER_SHARE_SQL} AND {_SCALE_KEY} IN ({_SCALES_IN}) AND vl_conta IS NOT NULL
"""

PER_SHARE_ROWS_SQL = f"SELECT count(*) FROM {TABLE} WHERE {_YEAR} AND {PER_SHARE_SQL}"

SAMPLE_SQL = f"""
SELECT cd_cvm, dt_refer, cd_conta, vl_conta, {NEW_VALUE_SQL}
FROM {TABLE}
WHERE {_YEAR} AND {CANDIDATE_SQL}
ORDER BY dt_refer DESC, cd_cvm, cd_conta, vl_conta
LIMIT %(limit)s
"""

UPDATE_SQL = f"""
UPDATE {TABLE}
SET vl_conta = {NEW_VALUE_SQL}
WHERE {_YEAR} AND {CANDIDATE_SQL}
"""

# Rows the year batches would never reach.
OUTSIDE_SQL = f"""
SELECT count(*) FROM {TABLE}
WHERE (dt_refer < %(lo)s OR dt_refer >= %(hi)s) AND {CANDIDATE_SQL}
"""

MARKER_EXISTS_SQL = (
    "SELECT count(*) FROM information_schema.tables"
    " WHERE table_schema = current_schema() AND table_name = %(table)s"
)
MARKER_DDL = f"""
CREATE TABLE IF NOT EXISTS {MARKER} (
    dt_refer_year INT PRIMARY KEY,
    rows_updated  INT NOT NULL,
    rows_rounded  INT NOT NULL,
    applied_at    TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""
# Postgres only. A new table in schema public is reachable through the REST
# gateway unless it is closed, like the landing tables are.
MARKER_LOCKDOWN_SQL: Tuple[str, ...] = (
    f"ALTER TABLE {MARKER} ENABLE ROW LEVEL SECURITY",
    f"""
DO $$
DECLARE r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE {MARKER} FROM %I', r);
        END IF;
    END LOOP;
END $$
""",
)
MARKED_SQL = f"SELECT dt_refer_year, rows_updated FROM {MARKER} ORDER BY dt_refer_year"
MARK_SQL = f"""
INSERT INTO {MARKER} (dt_refer_year, rows_updated, rows_rounded)
VALUES (%(year)s, %(updated)s, %(rounded)s)
ON CONFLICT (dt_refer_year) DO NOTHING
"""

# An ITR or DFP slice the fixed ingest started: its rows are already unscaled.
# 'skipped' and an 'ok' with no rows wrote nothing; 'running' and 'error' may have.
FIXED_INGEST_SQL = f"""
SELECT count(*), min(started_at) FROM {LOG_TABLE}
WHERE entity = 'cia_aberta' AND doc_type IN ('itr', 'dfp')
  AND status <> 'skipped' AND NOT (status = 'ok' AND rows_upserted = 0)
  AND CASE WHEN parser_version ~ '^[0-9]+$' THEN CAST(parser_version AS INT) END >= %(version)s
"""


class Refused(RuntimeError):
    """The correction must not run; nothing was changed by the step that raised."""


@dataclass
class YearReport:
    year: int
    per_share_rows: int = 0
    scales: List[Tuple[Optional[str], int, int]] = field(default_factory=list)
    to_change: int = 0
    rounded: int = 0            # rows that lose digits beyond 2 decimals
    to_zero: int = 0            # of those, rows that become 0.00
    sum_before: Decimal = Decimal(0)
    sum_after: Decimal = Decimal(0)
    samples: List[tuple] = field(default_factory=list)
    marked: bool = False        # corrected by an earlier run; not read, not touched
    updated: int = 0


def factor_of(escala_moeda: Optional[str]) -> int:
    """The factor this script divides by for a stored scale; 1 means untouched."""
    if not escala_moeda:
        return 1
    return FACTORS.get(escala_moeda.strip().upper(), 1)


def _bounds(year: int) -> dict:
    return {"lo": date(year, 1, 1), "hi": date(year + 1, 1, 1)}


def _dec(value: Any) -> Decimal:
    return Decimal(0) if value is None else Decimal(str(value))


def _utc3(moment: Any) -> str:
    """A stored instant as Brasília time, for a message; the stored value is not touched."""
    if getattr(moment, "tzinfo", None) is None:
        return str(moment)
    return moment.astimezone(BRASILIA).strftime("%Y-%m-%d %H:%M UTC-3")


def marker_exists(cur: Any) -> bool:
    cur.execute(MARKER_EXISTS_SQL, {"table": MARKER})
    return bool(cur.fetchone()[0])


def marked_years(client: Any) -> Dict[int, int]:
    """{year: rows updated} of the years an earlier --apply committed."""
    with client.cursor() as cur:
        if not marker_exists(cur):
            return {}
        cur.execute(MARKED_SQL)
        return {int(y): int(n) for y, n in cur.fetchall()}


def ensure_marker(client: Any) -> None:
    with client.cursor() as cur:
        cur.execute(MARKER_DDL)
        for sql in MARKER_LOCKDOWN_SQL:
            cur.execute(sql)


def fixed_ingest_runs(client: Any) -> Tuple[int, Any]:
    """(slices, first start) of ITR/DFP slices written by the fixed ingest."""
    with client.cursor() as cur:
        cur.execute(FIXED_INGEST_SQL, {"version": FIXED_PARSER_VERSION})
        n, first = cur.fetchone()
    return int(n), first


def rows_outside(client: Any, start_year: int, end_year: int) -> int:
    with client.cursor() as cur:
        cur.execute(OUTSIDE_SQL, {"lo": date(start_year, 1, 1), "hi": date(end_year + 1, 1, 1)})
        return int(cur.fetchone()[0])


def report_year(client: Any, year: int, *, sample_limit: int = SAMPLE_LIMIT) -> YearReport:
    """Count one year. Reads only."""
    params = _bounds(year)
    rep = YearReport(year=year)
    with client.cursor() as cur:
        cur.execute(SCALES_SQL, params)
        rep.scales = [(s, int(n), int(nz)) for s, n, nz in cur.fetchall()]
        rep.per_share_rows = sum(n for _, n, _ in rep.scales)
        cur.execute(CANDIDATES_SQL, params)
        n, rounded, to_zero, before, after = cur.fetchone()
        rep.to_change, rep.rounded, rep.to_zero = int(n), int(rounded or 0), int(to_zero or 0)
        rep.sum_before, rep.sum_after = _dec(before), _dec(after)
        # The SQL and the ingest's own rule must agree on which scales were
        # multiplied; a database that upper-cases differently would not.
        by_rule = sum(nz for s, _, nz in rep.scales if factor_of(s) != 1)
        if by_rule != rep.to_change:
            raise Refused(
                f"{TABLE} {year}: the ingest's scale table selects {by_rule} rows but the "
                f"SQL selects {rep.to_change}; the scales are {rep.scales!r}"
            )
        if rep.to_change and sample_limit:
            cur.execute(SAMPLE_SQL, {**params, "limit": sample_limit})
            rep.samples = cur.fetchall()
    return rep


def apply_year(client: Any, rep: YearReport) -> YearReport:
    """Correct one year in one transaction, on one connection.

    The year's marker row goes in first: if the year is already marked the
    insert writes nothing and the transaction is rolled back before any row is
    divided. The update must touch exactly the rows counted inside the
    transaction, keep the number of per-share rows, and leave the sum the
    report predicted, or the year is rolled back, marker row included.
    """
    params = _bounds(rep.year)
    with client.cursor() as cur:
        cur.execute("BEGIN")
        try:
            cur.execute(PER_SHARE_ROWS_SQL, params)
            rows_before = int(cur.fetchone()[0])
            cur.execute(CANDIDATES_SQL, params)
            n, rounded, _to_zero, _before, after = cur.fetchone()
            expected, expected_sum = int(n), _dec(after)
            cur.execute(MARK_SQL, {"year": rep.year, "updated": expected, "rounded": int(rounded or 0)})
            if cur.rowcount != 1:
                raise Refused(f"{TABLE} {rep.year}: already marked as corrected; rolled back")
            cur.execute(UPDATE_SQL, params)
            updated = cur.rowcount
            if updated != expected:
                raise RuntimeError(
                    f"{TABLE} {rep.year}: updated {updated} rows but {expected} were to change; rolled back"
                )
            cur.execute(PER_SHARE_ROWS_SQL, params)
            rows_after = int(cur.fetchone()[0])
            cur.execute(SCALED_SUM_SQL, params)
            _n, total = cur.fetchone()
            if rows_after != rows_before:
                raise RuntimeError(
                    f"{TABLE} {rep.year}: {rows_before} per-share rows before, {rows_after} after; rolled back"
                )
            # Rows that were zero before add nothing to either side.
            if _dec(total) != expected_sum:
                raise RuntimeError(
                    f"{TABLE} {rep.year}: the corrected rows sum to {total}, expected {expected_sum}; rolled back"
                )
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise
    rep.updated = updated
    return rep


def log_year(rep: YearReport, *, apply: bool) -> None:
    if rep.marked:
        logger.info("%d: corrected by an earlier run (%d rows), not touched", rep.year, rep.updated)
        return
    if not rep.per_share_rows:
        return
    scales = ", ".join(
        f"{s!r} {n} rows ({nz} with a value, "
        + (f"divide by {factor_of(s):,}" if factor_of(s) != 1 else "left alone") + ")"
        for s, n, nz in rep.scales
    )
    action = f"changed {rep.updated}" if apply else f"would change {rep.to_change}"
    logger.info(
        "%d: %d per-share rows; %s; %s; %d lose digits past 2 decimals (%d become 0.00); "
        "sum %s -> %s",
        rep.year, rep.per_share_rows, scales, action, rep.rounded, rep.to_zero,
        rep.sum_before, rep.sum_after,
    )


def log_samples(samples: Sequence[tuple]) -> None:
    if not samples:
        return
    logger.info("sample rows (cd_cvm, dt_refer, cd_conta, old value, new value):")
    for cd_cvm, dt_refer, cd_conta, old, new in samples:
        logger.info("  %s  %s  %s  %s -> %s", cd_cvm, dt_refer, cd_conta, old, new)


def run(client: Any, start_year: int, end_year: int, *, apply: bool, resume: bool = False,
        accept_rounding: bool = False, sample_limit: int = SAMPLE_LIMIT) -> List[YearReport]:
    """Report every year and, with apply, correct the ones not yet marked.

    Every refusal is decided before the first row is changed. Raises Refused
    when --apply must not run; a dry run logs the same reason and goes on.
    """
    mode = "apply" if apply else "dry run"
    refusals: List[str] = []

    marked = marked_years(client)
    if marked:
        years = sorted(marked)
        logger.info(
            "marker %s: %d years already corrected (%d..%d, %d rows)",
            MARKER, len(years), years[0], years[-1], sum(marked.values()),
        )
        if not resume:
            refusals.append(
                f"{MARKER} already holds {len(years)} years: the correction has run. A second run "
                "would divide rows that are already right. Only after a run that stopped half way: "
                "--apply --resume does the years with no marker row"
            )

    slices, first = fixed_ingest_runs(client)
    if slices:
        refusals.append(
            f"{LOG_TABLE} has {slices} ITR/DFP slices written with parser_version >= "
            f"{FIXED_PARSER_VERSION} (the first started {_utc3(first)}): the fixed ingest has already "
            "stored per-share rows unscaled, and nothing in the table tells them from the rows "
            "still to divide. Do not run this; re-ingest the listed-company statements instead"
        )

    outside = rows_outside(client, start_year, end_year)
    if outside:
        refusals.append(
            f"{outside} rows to change have a dt_refer outside {start_year}..{end_year}; "
            "widen --start-year / --end-year so one run covers them all"
        )

    reports: List[YearReport] = []
    for year in range(start_year, end_year + 1):
        if year in marked:
            rep = YearReport(year=year, marked=True, updated=marked[year])
        else:
            rep = report_year(client, year, sample_limit=sample_limit)
        reports.append(rep)
    todo = [r for r in reports if not r.marked]

    rounded = sum(r.rounded for r in todo)
    if rounded and not accept_rounding:
        refusals.append(
            f"{rounded} rows lose digits past 2 decimals ({sum(r.to_zero for r in todo)} become 0.00) "
            "because vl_conta is NUMERIC(28,2); pass --accept-rounding to correct them anyway"
        )
    if apply and marked and resume and not todo:
        refusals.append("every year in the range is already marked; nothing is left to resume")

    if apply and refusals:
        for rep in reports:
            log_year(rep, apply=False)
        raise Refused("nothing was changed: " + "; ".join(refusals))

    if apply:
        ensure_marker(client)
        for rep in todo:
            apply_year(client, rep)
    for rep in reports:
        log_year(rep, apply=apply)
    with_samples = [r for r in todo if r.samples]
    if with_samples:
        log_samples(with_samples[-1].samples)

    logger.info(
        "%s %d..%d (%s): %d per-share rows before, %d after; %d to change, %d changed; "
        "%d lose digits past 2 decimals (%d become 0.00); %d years already marked",
        TABLE, start_year, end_year, mode,
        sum(r.per_share_rows for r in todo), sum(r.per_share_rows for r in todo),
        sum(r.to_change for r in todo), sum(r.updated for r in todo),
        rounded, sum(r.to_zero for r in todo), len(reports) - len(todo),
    )
    for reason in refusals:
        logger.warning("--apply would be refused: %s", reason)
    return reports


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--start-year", type=int, default=FIRST_YEAR,
                    help=f"first dt_refer year (default: {FIRST_YEAR}, the first partition)")
    ap.add_argument("--end-year", type=int, default=None,
                    help="last dt_refer year (default: next year)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="report only; this is the default")
    mode.add_argument("--apply", action="store_true",
                      help="divide the stored per-share values, once")
    ap.add_argument("--resume", action="store_true",
                    help="with --apply, after a run that stopped half way: do the unmarked years")
    ap.add_argument("--accept-rounding", action="store_true",
                    help="with --apply: correct rows that lose digits past 2 decimals")
    ap.add_argument("--sample-limit", type=int, default=SAMPLE_LIMIT,
                    help=f"sample rows to print (default: {SAMPLE_LIMIT})")
    args = ap.parse_args(argv)
    if args.end_year is None:
        args.end_year = date.today().year + 1
    if args.end_year < args.start_year:
        ap.error("--end-year is before --start-year")
    if args.resume and not args.apply:
        ap.error("--resume needs --apply")
    if args.sample_limit < 0:
        ap.error("--sample-limit cannot be negative")
    return args


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from src.store.pg_client import get_pg_client

    client = get_pg_client()
    try:
        run(client, args.start_year, args.end_year, apply=args.apply, resume=args.resume,
            accept_rounding=args.accept_rounding, sample_limit=args.sample_limit)
    except Refused as e:
        logger.error("refused: %s", e)
        return EXIT_REFUSED
    finally:
        client.closeall()
    return 0


if __name__ == "__main__":
    sys.exit(main())
