"""
Pipeline verification script — queries live Supabase DB and prints a
structured report on data presence, field-population rates, and sample
business metrics for each entity type.

Usage:
    python scripts/verify_pipeline.py

Requires: SUPABASE_URL and SUPABASE_SERVICE_KEY env vars (or a .env file).
"""

import os
import sys
from typing import Any, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.store.supabase_client import get_supabase_client

SEP = "=" * 68
SEP2 = "-" * 68


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def _q(client: Any, table: str):
    return client.table(table)


def count_table(client: Any, table: str) -> int:
    r = _q(client, table).select("*", count="exact", head=True).execute()
    return r.count or 0


def count_nonnull(client: Any, table: str, col: str, extra_filter=None) -> int:
    q = _q(client, table).select("*", count="exact", head=True).not_.is_(col, "null")
    if extra_filter:
        q = q.eq(*extra_filter)
    r = q.execute()
    return r.count or 0


def sample_rows(client: Any, table: str, order_col: str,
                select: str = "*", limit: int = 5, filters: Optional[list] = None) -> List[dict]:
    q = _q(client, table).select(select).order(order_col, desc=True).limit(limit)
    if filters:
        for col, val in filters:
            q = q.eq(col, val)
    return q.execute().data or []


# ---------------------------------------------------------------------------
# Report sections
# ---------------------------------------------------------------------------

def report_presence(client):
    print(f"\n{SEP}")
    print("  TABLE PRESENCE")
    print(SEP)
    checks = [
        ("cvm_fi_diario",    None,                       "vl_patrim_liq"),
        ("cvm_fi_cda",       None,                       "vl_merc_pos_final"),
        ("cvm_fidc_mensal",  None,                       "vl_patrim_liq"),
        ("cvm_fiagro_mensal",None,                       "vl_patrim_liq"),
        ("cvm_fip_periodic", None,                       "vl_patrim_liq"),
        ("cvm_fii_mensal",   ("doc_subtype", "geral"),   "vl_patrim_liq"),
        ("cvm_fii_mensal",   ("doc_subtype","complemento"),"vl_patrim_liq"),
        ("cvm_securit_mensal",None,                      "vl_emissao"),
        ("cvm_securit_dfin", None,                       None),
        ("cvm_ingest_log",   None,                       None),
    ]
    print(f"  {'Table / subtype':<42} {'rows':>8}  {'key field %':>10}")
    print(f"  {SEP2}")
    for table, filt, kf in checks:
        label = table
        if filt:
            label += f" [{filt[1]}]"
        total = count_table(client, table) if not filt else (
            _q(client, table)
            .select("*", count="exact", head=True)
            .eq(*filt)
            .execute().count or 0
        )
        if kf and total > 0:
            nonnull = count_nonnull(client, table, kf, extra_filter=filt)
            pct = f"{100 * nonnull // total}%"
        else:
            pct = "—" if total == 0 else "n/a"
        flag = "  ✓" if total > 0 else "  ✗ EMPTY"
        print(f"  {label:<42} {total:>8}  {pct:>10}{flag}")


def report_quality(client):
    print(f"\n{SEP}")
    print("  KEY-FIELD NULL RATES  (target: < 5%  after pipeline fixes)")
    print(SEP)
    checks = [
        ("cvm_fi_diario",    None,                       "vl_patrim_liq", "FI      vl_patrim_liq"),
        ("cvm_fidc_mensal",  None,                       "vl_patrim_liq", "FIDC    vl_patrim_liq  [tab_IV fix]"),
        ("cvm_fii_mensal",   ("doc_subtype","complemento"),"vl_patrim_liq","FII complemento vl_patrim_liq"),
        ("cvm_securit_mensal",None,                      "vl_emissao",   "SECURIT vl_emissao     [Valor_Atualizado_Emissao fix]"),
        ("cvm_securit_mensal",None,                      "vl_total",     "SECURIT vl_total       [Ativo fix]"),
        ("cvm_securit_mensal",None,                      "dt_emissao",   "SECURIT dt_emissao     [Data_Referencia fix]"),
    ]
    for table, filt, col, label in checks:
        if filt:
            total = _q(client, table).select("*", count="exact", head=True).eq(*filt).execute().count or 0
            nonnull = (
                _q(client, table)
                .select("*", count="exact", head=True)
                .eq(*filt)
                .not_.is_(col, "null")
                .execute().count or 0
            )
        else:
            total = count_table(client, table)
            nonnull = count_nonnull(client, table, col)
        if total == 0:
            print(f"  {label:<50}  no data")
            continue
        null_n = total - nonnull
        null_pct = 100 * null_n // total
        bar = "✓" if null_pct < 5 else ("!" if null_pct < 30 else "✗")
        print(f"  {label:<50}  {null_pct:>3}% null  {bar}")


def report_fi(client):
    print(f"\n{SEP}")
    print("  FI — RECENT MONTHLY INDUSTRY METRICS (latest 3 months, sampled)")
    print(SEP)
    rows = sample_rows(
        client, "cvm_fi_diario",
        order_col="dt_comptc",
        select="dt_comptc,vl_patrim_liq,captc_dia,resg_dia",
        limit=10,
    )
    if not rows:
        print("  (no data)")
        return
    from collections import defaultdict
    by_month: dict = defaultdict(lambda: {"pl": 0.0, "in": 0.0, "out": 0.0, "n": 0})
    for r in rows:
        m = str(r["dt_comptc"])[:7]
        pl = float(r["vl_patrim_liq"] or 0)
        ci = float(r["captc_dia"] or 0)
        co = float(r["resg_dia"] or 0)
        by_month[m]["pl"] += pl
        by_month[m]["in"] += ci
        by_month[m]["out"] += co
        by_month[m]["n"] += 1
    print(f"  {'Month':<10} {'Sample funds':>12} {'Total PL (M)':>14} {'Inflow (M)':>11} {'Redemption (M)':>15}")
    print(f"  {SEP2}")
    for m in sorted(by_month, reverse=True):
        d = by_month[m]
        print(f"  {m:<10} {d['n']:>12} {d['pl']/1e6:>14.1f} {d['in']/1e6:>11.1f} {d['out']/1e6:>15.1f}")
    print("  (sampled — for full totals run analysis_queries.sql query 4)")


def report_fidc(client):
    print(f"\n{SEP}")
    print("  FIDC — MONTHLY SNAPSHOT (latest 5 periods)")
    print(SEP)
    rows = sample_rows(
        client, "cvm_fidc_mensal",
        order_col="period",
        select="period,cnpj,vl_patrim_liq,vl_inadimpl",
        limit=50,
    )
    if not rows:
        print("  (no data)")
        return
    from collections import defaultdict
    by_period: dict = defaultdict(lambda: {"pl": 0.0, "delinq": 0.0, "n": 0})
    for r in rows:
        p = str(r["period"])[:7]
        by_period[p]["pl"] += float(r["vl_patrim_liq"] or 0)
        by_period[p]["delinq"] += float(r["vl_inadimpl"] or 0)
        by_period[p]["n"] += 1
    print(f"  {'Period':<10} {'Funds':>6} {'Total PL (M)':>14} {'Delinq. (M)':>12} {'Delinq%':>9}")
    print(f"  {SEP2}")
    for p in sorted(by_period, reverse=True)[:5]:
        d = by_period[p]
        dpct = 100 * d["delinq"] / d["pl"] if d["pl"] else 0.0
        print(f"  {p:<10} {d['n']:>6} {d['pl']/1e6:>14.1f} {d['delinq']/1e6:>12.1f} {dpct:>8.2f}%")


def report_fii(client):
    print(f"\n{SEP}")
    print("  FII — TOP 10 FUNDS BY NAV (complemento, latest period)")
    print(SEP)
    rows = sample_rows(
        client, "cvm_fii_mensal",
        order_col="vl_patrim_liq",
        select="cnpj,period,vl_patrim_liq",
        limit=10,
        filters=[("doc_subtype", "complemento")],
    )
    if not rows:
        print("  (no data — complemento doc_subtype may not be ingested yet)")
        return
    print(f"  {'CNPJ':<16} {'Period':<12} {'PL (M)':>10}")
    print(f"  {SEP2}")
    for r in rows:
        pl = float(r["vl_patrim_liq"] or 0) / 1e6
        print(f"  {r['cnpj']:<16} {str(r['period']):<12} {pl:>10.2f}")


def report_securit(client):
    print(f"\n{SEP}")
    print("  SECURIT — EMISSION VOLUME BY YEAR AND TYPE")
    print(SEP)
    rows = sample_rows(
        client, "cvm_securit_mensal",
        order_col="period_year",
        select="period_year,instrument_type,cnpj_securit,vl_emissao,vl_total",
        limit=200,
    )
    if not rows:
        print("  (no data)")
        return
    from collections import defaultdict
    by_key: dict = defaultdict(lambda: {"emissao": 0.0, "total": 0.0, "issuers": set(), "n": 0})
    for r in rows:
        k = (r["period_year"], r["instrument_type"])
        by_key[k]["emissao"] += float(r["vl_emissao"] or 0)
        by_key[k]["total"] += float(r["vl_total"] or 0)
        if r["cnpj_securit"]:
            by_key[k]["issuers"].add(r["cnpj_securit"])
        by_key[k]["n"] += 1
    print(f"  {'Year':<6} {'Type':<15} {'Issuers':>8} {'Emissao (M)':>13} {'Assets (M)':>11}")
    print(f"  {SEP2}")
    for (yr, tp) in sorted(by_key, reverse=True)[:12]:
        d = by_key[(yr, tp)]
        print(f"  {str(yr):<6} {tp:<15} {len(d['issuers']):>8} {d['emissao']/1e6:>13.1f} {d['total']/1e6:>11.1f}")


def report_ingest_log(client):
    print(f"\n{SEP}")
    print("  INGEST LOG — LAST 10 RUNS")
    print(SEP)
    rows = sample_rows(
        client, "cvm_ingest_log",
        order_col="started_at",
        select="entity,doc_type,period_year,period_month,status,rows_upserted,started_at",
        limit=10,
    )
    if not rows:
        print("  (no ingest runs recorded)")
        return
    print(f"  {'Entity':<10} {'Doc type':<22} {'Period':<10} {'Status':<8} {'Rows':>6}  Started at")
    print(f"  {SEP2}")
    for r in rows:
        period = f"{r['period_year']}" + (f"-{r['period_month']:02d}" if r['period_month'] else "")
        status_icon = "✓" if r["status"] == "ok" else "✗"
        print(f"  {r['entity']:<10} {r['doc_type']:<22} {period:<10} "
              f"{status_icon} {r['status']:<6} {r['rows_upserted']:>6}  {str(r['started_at'])[:19]}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print(f"\n{SEP}")
    print("  CVM PIPELINE VERIFICATION REPORT")
    print(f"  {SEP2}")
    try:
        client = get_supabase_client()
        print("  Supabase connection: OK")
    except EnvironmentError as e:
        print(f"  ERROR: {e}")
        print("  Set SUPABASE_URL and SUPABASE_SERVICE_KEY and retry.")
        sys.exit(1)

    report_presence(client)
    report_quality(client)
    report_fi(client)
    report_fidc(client)
    report_fii(client)
    report_securit(client)
    report_ingest_log(client)

    print(f"\n{SEP}")
    print("  Done. For deeper analysis run: scripts/analysis_queries.sql")
    print(SEP)


if __name__ == "__main__":
    main()
