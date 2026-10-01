"""Fill cvm_fi_balancete_resumo (migration 59) from cvm_fi_balancete, month by month.

The daily ingest writes both tables from now on. This script builds the
summary for the months already stored, in SQL, without downloading anything
from CVM. It is idempotent (ON CONFLICT DO UPDATE), so a re-run rewrites the
same rows.

For each month it prints the rows it upserted and how many of them break the
balance identity  vl_ativo = vl_passivo + vl_patrim_liq + vl_receitas +
vl_despesas  (a group the fund did not file counts as 0 in the check only;
the stored value stays NULL). A database error raises and the process exits 1.

    python scripts/backfill_balancete_summary.py                 # every month
    python scripts/backfill_balancete_summary.py --start 2026-01 --end 2026-08

Runs in GitHub Actions as `daily_ingest` mode=balancete-summary, which has the
POSTGRES_URL secret.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.parsers.field_maps import fi_balancete as _balancete  # noqa: E402

logger = logging.getLogger("backfill_balancete_summary")

FIRST_MONTH = date(2019, 1, 1)


def _months(start: date, end: date) -> Iterator[Tuple[date, date]]:
    """[first day, first day of the next month) for each month from start to end."""
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        yield date(y, m, 1), date(ny, nm, 1)
        y, m = ny, nm


def build_upsert_sql() -> str:
    """INSERT ... SELECT for one month, taking %(lo)s and %(hi)s.

    Built from RESUMO_ACCOUNTS so the backfill and the ingest can never disagree
    on which code fills which column.
    """
    groups = _balancete.RESUMO_ACCOUNTS
    cols = list(groups.values())
    picks = ",\n           ".join(
        f"max(vl_saldo_balcte) FILTER (WHERE cd_conta_balcte = '{code}') AS {col}"
        for code, col in groups.items()
    )
    updates = ",\n        ".join(
        f"{c} = EXCLUDED.{c}"
        for c in ["tp_fundo_classe", "plano_conta_balcte", *cols, "n_contas"]
    ) + ",\n        fetched_at = NOW()"
    return f"""
INSERT INTO {_balancete.RESUMO_TABLE}
    (cnpj, dt_comptc, tp_fundo_classe, plano_conta_balcte, {", ".join(cols)}, n_contas)
SELECT cnpj, dt_comptc,
       max(tp_fundo_classe), max(plano_conta_balcte),
           {picks},
       count(DISTINCT cd_conta_balcte)
FROM {_balancete.TABLE}
WHERE dt_comptc >= %(lo)s AND dt_comptc < %(hi)s
GROUP BY cnpj, dt_comptc
ON CONFLICT ON CONSTRAINT uq_fi_balancete_resumo DO UPDATE SET
        {updates}
"""


IDENTITY_SQL = f"""
SELECT count(*) AS n,
       count(*) FILTER (
           WHERE abs(coalesce(vl_ativo, 0)
                     - coalesce(vl_passivo, 0) - coalesce(vl_patrim_liq, 0)
                     - coalesce(vl_receitas, 0) - coalesce(vl_despesas, 0)) > 1
       ) AS broken
FROM {_balancete.RESUMO_TABLE}
WHERE dt_comptc >= %(lo)s AND dt_comptc < %(hi)s
"""


def _parse_month(s: Optional[str], default: date) -> date:
    if not s:
        return default
    y, m = s.split("-")
    return date(int(y), int(m), 1)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--start", help="first month, YYYY-MM (default 2019-01)")
    ap.add_argument("--end", help="last month, YYYY-MM (default this month)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    today = date.today()
    start = _parse_month(args.start, FIRST_MONTH)
    end = _parse_month(args.end, date(today.year, today.month, 1))

    from src.store.pg_client import get_pg_client

    client = get_pg_client()
    upsert_sql = build_upsert_sql()
    total = 0
    try:
        for lo, hi in _months(start, end):
            with client.cursor() as cur:
                # One month aggregates about 2.2M account rows; the role's
                # default timeout is shorter than that on a busy instance.
                cur.execute("SET statement_timeout = '30min'")
                cur.execute(upsert_sql, {"lo": lo, "hi": hi})
                upserted = cur.rowcount
                cur.execute(IDENTITY_SQL, {"lo": lo, "hi": hi})
                n, broken = cur.fetchone()
            total += upserted
            logger.info("%s: upserted %d, stored %d, identity broken in %d",
                        lo.strftime("%Y-%m"), upserted, n, broken)
    finally:
        client.closeall()
    logger.info("done: %d rows upserted", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
