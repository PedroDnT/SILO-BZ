"""
Pipeline verification script — queries the live Supabase Postgres DB (via
psycopg2/SQL) and prints a structured report on data presence, field-population
rates, and sample business metrics for each entity type.

Usage:
    python scripts/verify_pipeline.py

Requires: POSTGRES_URL env var (or a .env file).
"""

import os
import sys
from typing import Any, List, Optional

from psycopg2 import sql

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.store.pg_client import get_pg_client

SEP = "=" * 68
SEP2 = "-" * 68


# ---------------------------------------------------------------------------
# Query helpers (psycopg2 + SQL against the Supabase Postgres connection)
#
# Identifiers (table/column names) are composed with psycopg2.sql.Identifier so
# they are safely quoted/escaped; filter *values* go through query parameters.
# ---------------------------------------------------------------------------

def _scalar(client: Any, query: Any, params: tuple = ()) -> int:
    with client.cursor() as cur:
        cur.execute(query, params)
        row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def count_table(client: Any, table: str, extra_filter=None) -> int:
    query = sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
    params: tuple = ()
    if extra_filter:
        query += sql.SQL(" WHERE {} = %s").format(sql.Identifier(extra_filter[0]))
        params = (extra_filter[1],)
    return _scalar(client, query, params)


def table_has_rows(client: Any, table: str) -> bool:
    """Presence without a COUNT(*).

    The holdings tables are the largest in the warehouse (cvm_fi_cda_acoes alone
    is 11 GB). COUNT(*) on them is a full scan that adds minutes to a script
    whose whole job is a fast smoke test, and the answer it buys — "is anything
    here" — is one row's worth of information. LIMIT 1 stops at the first tuple.
    """
    query = sql.SQL("SELECT EXISTS (SELECT 1 FROM {} LIMIT 1)").format(
        sql.Identifier(table)
    )
    with client.cursor() as cur:
        cur.execute(query)
        row = cur.fetchone()
    return bool(row and row[0])


def estimate_rows(client: Any, table: str) -> int:
    """Planner row estimate — an ESTIMATE, and labelled as one at the callsite.

    reltuples is maintained by ANALYZE (CI runs one after every ingest), so it
    trails the table by at most a day and can read -1 on a relation never
    analyzed. Never print it as a count: a verification script that rounds an
    estimate into a fact is the same defect class as fabricating data.
    """
    return _scalar(
        client,
        "SELECT GREATEST(reltuples, 0)::bigint FROM pg_class WHERE relname = %s",
        (table,),
    )


def sample_nonnull_pct(client: Any, table: str, col: str, sample: int = 50_000
                       ) -> Optional[int]:
    """Population rate over a bounded sample, or None if the sample is empty.

    Reads the first `sample` rows rather than the table, so the cost is fixed.
    It is a sample, not the rate — the callsite prints it with a ~ so nobody
    reads it as the whole table's number.
    """
    query = sql.SQL(
        "SELECT count(*) FILTER (WHERE {col} IS NOT NULL), count(*) "
        "FROM (SELECT {col} FROM {tbl} LIMIT %s) s"
    ).format(col=sql.Identifier(col), tbl=sql.Identifier(table))
    with client.cursor() as cur:
        cur.execute(query, (sample,))
        row = cur.fetchone()
    if not row or not row[1]:
        return None
    return 100 * row[0] // row[1]


def count_nonnull(client: Any, table: str, col: str, extra_filter=None) -> int:
    query = sql.SQL("SELECT count(*) FROM {} WHERE {} IS NOT NULL").format(
        sql.Identifier(table), sql.Identifier(col)
    )
    params: tuple = ()
    if extra_filter:
        query += sql.SQL(" AND {} = %s").format(sql.Identifier(extra_filter[0]))
        params = (extra_filter[1],)
    return _scalar(client, query, params)


def sample_rows(client: Any, table: str, order_col: str,
                select: str = "*", limit: int = 5, filters: Optional[list] = None) -> List[dict]:
    if select == "*":
        select_clause = sql.SQL("*")
    else:
        select_clause = sql.SQL(", ").join(
            sql.Identifier(c.strip()) for c in select.split(",")
        )
    query = sql.SQL("SELECT {} FROM {}").format(select_clause, sql.Identifier(table))
    params: list = []
    if filters:
        clauses = [sql.SQL("{} = %s").format(sql.Identifier(col)) for col, _ in filters]
        query += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(clauses)
        params = [val for _, val in filters]
    query += sql.SQL(" ORDER BY {} DESC NULLS LAST LIMIT %s").format(
        sql.Identifier(order_col)
    )
    params.append(limit)
    with client.cursor() as cur:
        cur.execute(query, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Report sections
# ---------------------------------------------------------------------------

def report_presence(client):
    print(f"\n{SEP}")
    print("  TABLE PRESENCE")
    print(SEP)
    checks = [
        ("cvm_fi_diario",           None,                              "vl_patrim_liq"),
        ("cvm_fi_cda",              None,                              "vl_merc_pos_final"),
        ("cvm_fidc_mensal",         None,                              "vl_patrim_liq"),
        ("cvm_fidc_tranche",        None,                              "vl_cota"),
        ("cvm_fidc_tranche_flows",  None,                              "vl_total"),
        ("cvm_fidc_aging",          None,                              "vl_inad_30"),
        ("cvm_fiagro_mensal",       None,                              "vl_patrim_liq"),
        ("cvm_fip_periodic",        None,                              "vl_patrim_liq"),
        ("cvm_fii_mensal",          ("doc_subtype", "geral"),          "vl_patrim_liq"),
        ("cvm_fii_mensal",          ("doc_subtype", "complemento"),    "vl_patrim_liq"),
        ("cvm_fii_mensal",          ("doc_subtype", "ativo_passivo"),  "rendimentos_distribuir"),
        ("cvm_securit_mensal",      None,                              "vl_emissao"),
        ("cvm_securit_serie",       None,                              "situacao"),
        ("cvm_securit_fluxo",       None,                              "recebimentos_direitos_creditorios"),
        ("cvm_securit_dfin",        None,                              None),
        ("bacen_sgs",               None,                              "value"),
        ("bacen_ptax",              None,                              "sell_rate"),
        ("bacen_expectativas",      None,                              "median"),
        ("cvm_ingest_log",          None,                              None),
    ]
    print(f"  {'Table / subtype':<42} {'rows':>8}  {'key field %':>10}")
    print(f"  {SEP2}")
    for table, filt, kf in checks:
        label = table
        if filt:
            label += f" [{filt[1]}]"
        total = count_table(client, table, extra_filter=filt)
        if kf and total > 0:
            nonnull = count_nonnull(client, table, kf, extra_filter=filt)
            pct = f"{100 * nonnull // total}%"
        else:
            pct = "—" if total == 0 else "n/a"
        flag = "  ✓" if total > 0 else "  ✗ EMPTY"
        print(f"  {label:<42} {total:>8}  {pct:>10}{flag}")

    report_holdings_presence(client)


# The fund holdings blocks. Kept out of the COUNT(*) list above on purpose:
# these are the three largest ingest tables in the warehouse, and counting them
# exactly would dominate the runtime of a script meant to finish in seconds.
# Presence is EXISTS, size is the planner's estimate, and the key-field rate is
# a bounded sample — each printed as what it is.
HOLDINGS_CHECKS = [
    ("cvm_fi_cda_acoes",      "cd_ativo"),          # block 4 — the B3 ticker edge
    ("cvm_fi_cda_cotas",      "cnpj_cota"),         # block 2 — fund-of-fund
    ("cvm_fi_cda_debentures", "cpf_cnpj_emissor"),  # block 6 — corporate credit
]


def report_holdings_presence(client):
    print(f"\n  {'Holdings block (est. rows, sampled %)':<42} {'~rows':>8}  {'~key %':>10}")
    print(f"  {SEP2}")
    for table, key_field in HOLDINGS_CHECKS:
        present = table_has_rows(client, table)
        if not present:
            print(f"  {table:<42} {0:>8}  {'—':>10}  ✗ EMPTY")
            continue
        est = estimate_rows(client, table)
        pct = sample_nonnull_pct(client, table, key_field)
        est_s = f"~{est}" if est else "?"
        pct_s = f"~{pct}%" if pct is not None else "n/a"
        print(f"  {table:<42} {est_s:>8}  {pct_s:>10}  ✓")


def report_quality(client):
    print(f"\n{SEP}")
    print("  KEY-FIELD NULL RATES  (target: < 5%  after pipeline fixes)")
    print(SEP)
    checks = [
        ("cvm_fi_diario",       None,                            "vl_patrim_liq",                     "FI      vl_patrim_liq"),
        ("cvm_fidc_mensal",     None,                            "vl_patrim_liq",                     "FIDC    vl_patrim_liq"),
        ("cvm_fidc_tranche",    None,                            "vl_rentab_mes",                     "FIDC    tranche vl_rentab_mes"),
        ("cvm_fidc_aging",      None,                            "vl_inad_30",                        "FIDC    aging vl_inad_30"),
        ("cvm_fii_mensal",      ("doc_subtype", "complemento"),  "vl_patrim_liq",                     "FII     complemento vl_patrim_liq"),
        ("cvm_fii_mensal",      ("doc_subtype", "complemento"),  "pct_dividend_yield_mes",            "FII     complemento pct_dividend_yield_mes"),
        ("cvm_fii_mensal",      ("doc_subtype", "ativo_passivo"),"rendimentos_distribuir",            "FII     ativo_passivo rendimentos_distribuir"),
        ("cvm_securit_mensal",  None,                            "vl_emissao",                        "SECURIT vl_emissao"),
        ("cvm_securit_mensal",  None,                            "dt_emissao",                        "SECURIT dt_emissao"),
        ("cvm_securit_serie",   None,                            "situacao",                          "SECURIT serie situacao"),
        ("cvm_securit_serie",   None,                            "valor_total_integralizado",         "SECURIT serie valor_total_integralizado"),
        ("cvm_securit_fluxo",   None,                            "recebimentos_direitos_creditorios", "SECURIT fluxo recebimentos"),
    ]
    for table, filt, col, label in checks:
        total = count_table(client, table, extra_filter=filt)
        nonnull = count_nonnull(client, table, col, extra_filter=filt)
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
    print("  (sampled — for full totals see scripts/queries/01_market_overview.sql)")


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


def report_fidc_tranche(client):
    print(f"\n{SEP}")
    print("  FIDC TRANCHE — LATEST PERIOD SAMPLE")
    print(SEP)
    rows = sample_rows(
        client, "cvm_fidc_tranche",
        order_col="period",
        select="period,cnpj,classe_serie,vl_cota,vl_rentab_mes,pr_desemp_real",
        limit=10,
    )
    if not rows:
        print("  (no data — run backfill --entity fidc)")
        return
    print(f"  {'Period':<10} {'CNPJ':<16} {'Classe':<35} {'Cota':>10} {'Rentab%':>8} {'Desemp%':>8}")
    print(f"  {SEP2}")
    for r in rows:
        cota = float(r["vl_cota"] or 0)
        rentab = float(r["vl_rentab_mes"] or 0)
        desemp = float(r["pr_desemp_real"] or 0)
        print(f"  {str(r['period']):<10} {r['cnpj']:<16} {str(r['classe_serie']):<35} "
              f"{cota:>10.4f} {rentab:>8.4f} {desemp:>8.4f}")


def report_securit_serie(client):
    print(f"\n{SEP}")
    print("  SECURIT SERIES — SITUACAO DISTRIBUTION (latest data_referencia)")
    print(SEP)
    rows = sample_rows(
        client, "cvm_securit_serie",
        order_col="data_referencia",
        select="instrument_type,situacao,classificacao_risco_atual",
        limit=500,
    )
    if not rows:
        print("  (no data — run backfill --entity securit)")
        return
    from collections import Counter
    by_type: dict = {}
    for r in rows:
        t = r["instrument_type"]
        s = r["situacao"] or "(null)"
        by_type.setdefault(t, Counter())[s] += 1
    for itype, counter in sorted(by_type.items()):
        total = sum(counter.values())
        adimpl = counter.get("Adimplente", 0)
        pct = 100 * adimpl // total if total else 0
        flag = "✓" if pct >= 90 else "!"
        print(f"  {itype:<15} total={total:>5}  Adimplente={adimpl:>5} ({pct}%)  {flag}")
        for sit, n in counter.most_common():
            if sit != "Adimplente":
                print(f"    └ {sit}: {n}")


def report_fii_yields(client):
    print(f"\n{SEP}")
    print("  FII COMPLEMENTO — TOP 10 BY DIVIDEND YIELD (latest period)")
    print(SEP)
    rows = sample_rows(
        client, "cvm_fii_mensal",
        order_col="pct_dividend_yield_mes",
        select="cnpj,period,vl_patrim_liq,pct_dividend_yield_mes,pct_rentab_efetiva_mes",
        limit=10,
        filters=[("doc_subtype", "complemento")],
    )
    if not rows:
        print("  (no data or pct_dividend_yield_mes column not yet populated)")
        return
    print(f"  {'CNPJ':<16} {'Period':<10} {'PL (M)':>10} {'DY%':>8} {'Rentab%':>9}")
    print(f"  {SEP2}")
    for r in rows:
        pl = float(r["vl_patrim_liq"] or 0) / 1e6
        dy = float(r["pct_dividend_yield_mes"] or 0)
        re = float(r["pct_rentab_efetiva_mes"] or 0)
        print(f"  {r['cnpj']:<16} {str(r['period']):<10} {pl:>10.2f} {dy:>8.4f} {re:>9.4f}")


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
        client = get_pg_client()
        print("  Postgres connection: OK")
    except EnvironmentError as e:
        print(f"  ERROR: {e}")
        print("  Set POSTGRES_URL and retry.")
        sys.exit(1)

    report_presence(client)
    report_quality(client)
    report_fi(client)
    report_fidc(client)
    report_fidc_tranche(client)
    report_fii(client)
    report_fii_yields(client)
    report_securit(client)
    report_securit_serie(client)
    report_ingest_log(client)

    print(f"\n{SEP}")
    print("  Done. For deeper analysis see: scripts/queries/ (13 numbered SQL files)")
    print(SEP)


if __name__ == "__main__":
    main()
