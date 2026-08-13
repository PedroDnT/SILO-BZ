#!/usr/bin/env python3
"""Report what data actually exists, per table, so dashboard figures can be judged.

Motivation
----------
Several dashboard charts render empty or show only a few points. There are two
very different causes and they need opposite fixes:

  * the data genuinely stops (or never started) -- the FIGURE should change:
    widen/re-anchor the window, relabel it, or drop the section;
  * the query is wrong -- the QUERY should change.

You cannot tell which from the rendered page. This script prints the ground
truth: for every base table, how many rows exist, the first and last period,
how stale the newest row is, and how many rows fall inside the rolling windows
the dashboard actually uses (3 / 12 / 24 / 36 months back from today).

The last column is the one that matters. A dashboard query written as
`where period >= current_date - interval '12 months'` returns NOTHING when the
newest row is 13 months old, however many million rows the table holds. CVM
publishes with a 1-2 month lag, so a chart anchored on current_date is
structurally fragile; anchoring on the table's own max(period) is not.

Read-only. Safe to run against production.

    POSTGRES_URL=... python scripts/audit_coverage.py
"""
from __future__ import annotations

import os
import sys
from typing import List, Optional, Tuple

import psycopg2

# (table, period column). Period column None -> count only (no time grain).
TABLES: List[Tuple[str, Optional[str]]] = [
    ("cvm_fi_diario",            "dt_comptc"),
    ("cvm_fi_cda",               "period"),
    ("cvm_fi_perfil",            "period"),
    ("cvm_fi_balancete",         "dt_comptc"),
    ("cvm_fidc_mensal",          "period"),
    ("cvm_fidc_tranche",         "period"),
    ("cvm_fidc_tranche_flows",   "period"),
    ("cvm_fidc_aging",           "period"),
    ("cvm_fiagro_mensal",        "period"),
    ("cvm_fip_periodic",         None),
    ("cvm_fii_mensal",           "period"),
    ("cvm_fii_periodic",         "data_referencia"),
    ("cvm_securit_mensal",       None),
    ("cvm_securit_serie",        "data_referencia"),
    ("cvm_securit_fluxo",        "data_referencia"),
    ("cvm_securit_dfin",         None),
    ("cvm_fund_registry",        None),
    ("cvm_etf_registry",         None),
    ("etf_market_snapshot",      "snapshot_date"),
    ("bacen_sgs",                "reference_date"),
    ("bacen_ptax",               "reference_date"),
    ("bacen_expectativas",       "reference_date"),
    ("cia_company",              None),
    ("cia_filing",               "dt_refer"),
    ("cia_account",              "dt_refer"),
    ("cia_event",                "data_entrega"),
    ("cvm_ingest_log",           None),
]

# Analytical relations the dashboard reads directly.
VIEWS: List[Tuple[str, Optional[str]]] = [
    ("fact_fund_monthly",   "period"),
    ("fact_security_monthly", "period"),
    ("dim_fund",            None),
    ("dim_security",        None),
    ("dim_administrator",   None),
    ("dim_gestor",          None),
    ("etf_daily",           "dt_comptc"),
    ("etf_market_latest",   "snapshot_date"),
]


def exists(cur, relname: str) -> bool:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (relname,))
    return bool(cur.fetchone()[0])


def profile(cur, relname: str, period_col: Optional[str]) -> Optional[dict]:
    if not exists(cur, relname):
        return None
    if period_col is None:
        cur.execute(f"SELECT count(*) FROM {relname}")  # noqa: S608 - fixed identifiers
        return {"rows": cur.fetchone()[0]}
    cur.execute(  # noqa: S608 - identifiers come from the constant lists above
        f"""
        SELECT count(*),
               min({period_col})::date,
               max({period_col})::date,
               (CURRENT_DATE - max({period_col})::date),
               count(*) FILTER (WHERE {period_col} >= CURRENT_DATE - INTERVAL '3 months'),
               count(*) FILTER (WHERE {period_col} >= CURRENT_DATE - INTERVAL '12 months'),
               count(*) FILTER (WHERE {period_col} >= CURRENT_DATE - INTERVAL '24 months'),
               count(*) FILTER (WHERE {period_col} >= CURRENT_DATE - INTERVAL '36 months'),
               count(DISTINCT date_trunc('month', {period_col}))
        FROM {relname}
        """
    )
    (rows, first, last, stale_days, w3, w12, w24, w36, months) = cur.fetchone()
    return {
        "rows": rows, "first": first, "last": last, "stale_days": stale_days,
        "w3": w3, "w12": w12, "w24": w24, "w36": w36, "months": months,
    }


def render(cur, title: str, spec: List[Tuple[str, Optional[str]]]) -> List[str]:
    warnings: List[str] = []
    print(f"\n{'=' * 118}\n  {title}\n{'=' * 118}")
    print(f"  {'relation':<26}{'rows':>12} {'first':>12} {'last':>12} {'stale':>7} "
          f"{'mo':>4} {'≤3mo':>10} {'≤12mo':>10} {'≤24mo':>10}")
    print(f"  {'-' * 114}")
    for relname, period_col in spec:
        p = profile(cur, relname, period_col)
        if p is None:
            print(f"  {relname:<26}{'MISSING':>12}")
            warnings.append(f"{relname}: relation does not exist")
            continue
        if period_col is None:
            print(f"  {relname:<26}{p['rows']:>12}{'  (no period column)':>40}")
            if p["rows"] == 0:
                warnings.append(f"{relname}: EMPTY")
            continue
        flag = ""
        if p["rows"] == 0:
            flag = "  <-- EMPTY"
            warnings.append(f"{relname}: EMPTY")
        elif p["w12"] == 0:
            flag = "  <-- nothing in last 12 months"
            warnings.append(
                f"{relname}: newest row is {p['stale_days']}d old ({p['last']}); "
                f"any current_date-anchored 12-month chart renders EMPTY"
            )
        elif p["w3"] == 0:
            flag = "  <-- nothing in last 3 months"
            warnings.append(
                f"{relname}: newest row is {p['stale_days']}d old ({p['last']}); "
                f"short-window charts will look empty"
            )
        print(f"  {relname:<26}{p['rows']:>12} {str(p['first']):>12} {str(p['last']):>12} "
              f"{str(p['stale_days']) + 'd':>7} {p['months']:>4} "
              f"{p['w3']:>10} {p['w12']:>10} {p['w24']:>10}{flag}")
    return warnings


def main() -> int:
    url = os.environ.get("POSTGRES_URL")
    if not url:
        print("POSTGRES_URL is not set", file=sys.stderr)
        return 2
    conn = psycopg2.connect("".join(url.split()))
    conn.set_session(readonly=True, autocommit=True)
    warnings: List[str] = []
    with conn.cursor() as cur:
        warnings += render(cur, "BASE TABLES", TABLES)
        warnings += render(cur, "ANALYTICAL RELATIONS", VIEWS)

        print(f"\n{'=' * 118}\n  PER-ENTITY LATEST SUCCESSFUL INGEST (cvm_ingest_log)\n{'=' * 118}")
        cur.execute(
            """
            SELECT entity, doc_type, max(period_year) AS yr,
                   max(finished_at)::date AS last_ok,
                   sum(rows_upserted) AS rows_total
            FROM cvm_ingest_log
            WHERE status = 'ok'
            GROUP BY entity, doc_type
            ORDER BY entity, doc_type
            """
        )
        for entity, doc_type, yr, last_ok, rows_total in cur.fetchall():
            print(f"  {entity:<14}{doc_type:<22}{str(yr):>6}  last_ok={last_ok}  rows={rows_total}")
    conn.close()

    print(f"\n{'=' * 118}\n  FINDINGS ({len(warnings)})\n{'=' * 118}")
    for w in warnings:
        print(f"  - {w}")
    if not warnings:
        print("  none - every profiled relation has recent data")
    return 0


if __name__ == "__main__":
    sys.exit(main())
