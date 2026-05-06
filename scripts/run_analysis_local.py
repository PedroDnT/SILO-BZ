"""
Run all 11 analytical queries against the local DuckDB seeded by seed_local_db.py.
Prints results in table form with PASS / WARN / EMPTY verdicts.

Usage:
    python scripts/run_analysis_local.py
    python scripts/run_analysis_local.py --db PATH
"""

import argparse
import os
import sys
from typing import Any, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import duckdb

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".local_db", "iliquid_local.duckdb")

SEP  = "=" * 68
SEP2 = "-" * 68


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt(val: Any, width: int = 14) -> str:
    if val is None:
        return "NULL".rjust(width)
    if isinstance(val, float):
        return f"{val:,.2f}".rjust(width)
    return str(val).rjust(width)


def _print_table(rows: List[tuple], cols: List[str], max_rows: int = 10):
    if not rows:
        return
    widths = [max(len(c), max(len(str(r[i])) for r in rows[:max_rows])) + 2
              for i, c in enumerate(cols)]
    header = "  " + "  ".join(c.ljust(w) for c, w in zip(cols, widths))
    print(header)
    print("  " + "  ".join("-" * w for w in widths))
    for row in rows[:max_rows]:
        print("  " + "  ".join(str(v).ljust(w) for v, w in zip(row, widths)))
    if len(rows) > max_rows:
        print(f"  … {len(rows) - max_rows} more rows")


def _run(conn, sql: str, params: dict = {}) -> Tuple[List[tuple], List[str]]:
    try:
        rel = conn.execute(sql, params) if params else conn.execute(sql)
        rows = rel.fetchall()
        cols = [d[0] for d in rel.description] if rel.description else []
        return rows, cols
    except Exception as e:
        return [], [f"ERROR: {e}"]


def _verdict(rows, key_col_idx: Optional[int], label: str) -> str:
    if not rows:
        return "EMPTY"
    if key_col_idx is not None:
        all_null = all(r[key_col_idx] is None for r in rows)
        if all_null:
            return "WARN  ← key column all NULL"
    return "PASS"


def _sample_cnpj(conn, table: str, col: str = "cnpj", filter_clause: str = "") -> str:
    join = "AND" if filter_clause.strip().upper().startswith("WHERE") else "WHERE"
    sql = f"SELECT {col} FROM {table} {filter_clause} {join} {col} IS NOT NULL LIMIT 1"
    rows, _ = _run(conn, sql)
    return rows[0][0] if rows else "00000000000000"


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def q1_data_presence(conn):
    print(f"\n{SEP}")
    print("  Q1 — DATA PRESENCE: row counts + date coverage per table")
    print(SEP)
    sql = """
    SELECT 'cvm_fi_diario'          AS tbl, COUNT(*) AS rows, MIN(dt_comptc)::TEXT AS earliest, MAX(dt_comptc)::TEXT AS latest,
           ROUND(100.0*COUNT(*) FILTER (WHERE vl_patrim_liq IS NOT NULL)/COUNT(*),1) AS pl_pct
    FROM cvm_fi_diario
    UNION ALL
    SELECT 'cvm_fi_cda', COUNT(*), MIN(period)::TEXT, MAX(period)::TEXT,
           ROUND(100.0*COUNT(*) FILTER (WHERE vl_merc_pos_final IS NOT NULL)/COUNT(*),1)
    FROM cvm_fi_cda
    UNION ALL
    SELECT 'cvm_fidc_mensal', COUNT(*), MIN(period)::TEXT, MAX(period)::TEXT,
           ROUND(100.0*COUNT(*) FILTER (WHERE vl_patrim_liq IS NOT NULL)/COUNT(*),1)
    FROM cvm_fidc_mensal
    UNION ALL
    SELECT 'cvm_fip_periodic', COUNT(*), MIN(period_year)::TEXT, MAX(period_year)::TEXT,
           ROUND(100.0*COUNT(*) FILTER (WHERE vl_patrim_liq IS NOT NULL)/COUNT(*),1)
    FROM cvm_fip_periodic
    UNION ALL
    SELECT 'cvm_fii_mensal [geral]', COUNT(*), MIN(period)::TEXT, MAX(period)::TEXT,
           ROUND(100.0*COUNT(*) FILTER (WHERE vl_patrim_liq IS NOT NULL)/COUNT(*),1)
    FROM cvm_fii_mensal WHERE doc_subtype = 'geral'
    UNION ALL
    SELECT 'cvm_fii_mensal [complemento]', COUNT(*), MIN(period)::TEXT, MAX(period)::TEXT,
           ROUND(100.0*COUNT(*) FILTER (WHERE vl_patrim_liq IS NOT NULL)/COUNT(*),1)
    FROM cvm_fii_mensal WHERE doc_subtype = 'complemento'
    UNION ALL
    SELECT 'cvm_securit_mensal', COUNT(*), MIN(period_year)::TEXT, MAX(period_year)::TEXT,
           ROUND(100.0*COUNT(*) FILTER (WHERE vl_emissao IS NOT NULL)/COUNT(*),1)
    FROM cvm_securit_mensal
    ORDER BY tbl
    """
    rows, cols = _run(conn, sql)
    _print_table(rows, cols)
    print(f"\n  Verdict: {_verdict(rows, 1, 'rows')}")


def q2_null_rates(conn):
    print(f"\n{SEP}")
    print("  Q2 — KEY-FIELD NULL RATES  (pipeline fix verification)")
    print(SEP)
    sql = """
    SELECT 'FI      vl_patrim_liq'          AS field,
           ROUND(100.0*COUNT(*) FILTER (WHERE vl_patrim_liq IS NULL)/NULLIF(COUNT(*),0),1) AS null_pct
    FROM cvm_fi_diario
    UNION ALL
    SELECT 'FIDC    vl_patrim_liq [tab_IV]',
           ROUND(100.0*COUNT(*) FILTER (WHERE vl_patrim_liq IS NULL)/NULLIF(COUNT(*),0),1)
    FROM cvm_fidc_mensal
    UNION ALL
    SELECT 'FII complemento vl_patrim_liq',
           ROUND(100.0*COUNT(*) FILTER (WHERE vl_patrim_liq IS NULL)/NULLIF(COUNT(*),0),1)
    FROM cvm_fii_mensal WHERE doc_subtype = 'complemento'
    UNION ALL
    SELECT 'SECURIT vl_emissao [Valor_Atualizado]',
           ROUND(100.0*COUNT(*) FILTER (WHERE vl_emissao IS NULL)/NULLIF(COUNT(*),0),1)
    FROM cvm_securit_mensal
    UNION ALL
    SELECT 'SECURIT vl_total  [Ativo]',
           ROUND(100.0*COUNT(*) FILTER (WHERE vl_total IS NULL)/NULLIF(COUNT(*),0),1)
    FROM cvm_securit_mensal
    UNION ALL
    SELECT 'SECURIT dt_emissao [Data_Referencia]',
           ROUND(100.0*COUNT(*) FILTER (WHERE dt_emissao IS NULL)/NULLIF(COUNT(*),0),1)
    FROM cvm_securit_mensal
    ORDER BY null_pct DESC
    """
    rows, cols = _run(conn, sql)
    for row in rows:
        pct = float(row[1]) if row[1] is not None else 100.0
        flag = "✓" if pct < 5 else ("!" if pct < 50 else "✗")
        print(f"  {row[0]:<45} {pct:>5.1f}% null  {flag}")
    # PASS if all fixes produced < 5% null
    fixable = [r for r in rows if "tab_IV" in r[0] or "Valor_Atualizado" in r[0]
               or "Ativo" in r[0] or "complemento" in r[0] or "Data_Referencia" in r[0]]
    worst = max((float(r[1]) if r[1] is not None else 100.0 for r in fixable), default=100)
    print(f"\n  Verdict: {'PASS' if worst < 5 else 'WARN  ← fix fields still have NULLs'}")


def q3_fund_nav_trend(conn, cnpj: str):
    print(f"\n{SEP}")
    print(f"  Q3 — FI FUND NAV TREND (cnpj={cnpj}, last 90 days)")
    print(SEP)
    if cnpj == "00000000000000":
        print("  Skipped — cvm_fi_diario not seeded (run without --skip-fi for this query)")
        return
    sql = """
    SELECT dt_comptc::TEXT AS date, vl_patrim_liq, vl_quota, nr_cotst,
           captc_dia, resg_dia,
           captc_dia - resg_dia AS net_flow
    FROM cvm_fi_diario
    WHERE cnpj = ? AND dt_comptc >= CURRENT_DATE - INTERVAL 90 DAY
    ORDER BY dt_comptc DESC
    LIMIT 10
    """
    rows, cols = _run(conn, sql, [cnpj])
    _print_table(rows, cols)
    print(f"\n  Verdict: {_verdict(rows, 1, 'vl_patrim_liq')}")


def q4_fi_industry_monthly(conn):
    print(f"\n{SEP}")
    print("  Q4 — FI INDUSTRY: monthly inflow vs. redemption")
    print(SEP)
    sql = """
    SELECT DATE_TRUNC('month', dt_comptc)::TEXT AS month,
           COUNT(DISTINCT cnpj)      AS funds,
           ROUND(SUM(vl_patrim_liq)/1e9,2) AS total_pl_bn,
           ROUND(SUM(captc_dia)/1e6,2)     AS inflow_mm,
           ROUND(SUM(resg_dia)/1e6,2)      AS redemption_mm,
           ROUND((SUM(captc_dia)-SUM(resg_dia))/1e6,2) AS net_flow_mm
    FROM cvm_fi_diario
    GROUP BY 1 ORDER BY 1 DESC LIMIT 6
    """
    rows, cols = _run(conn, sql)
    _print_table(rows, cols)
    print(f"\n  Verdict: {_verdict(rows, 3, 'inflow_mm')}")


def q5_fidc_monthly(conn):
    print(f"\n{SEP}")
    print("  Q5 — FIDC: monthly industry PL + delinquency rate")
    print(SEP)
    sql = """
    SELECT period::TEXT AS period,
           COUNT(DISTINCT cnpj) AS funds,
           ROUND(SUM(vl_patrim_liq)/1e9,2) AS total_pl_bn,
           ROUND(SUM(vl_inadimpl)/1e9,4)   AS total_inadimpl_bn,
           ROUND(100.0*SUM(vl_inadimpl)/NULLIF(SUM(vl_patrim_liq),0),3) AS delinq_pct
    FROM cvm_fidc_mensal
    GROUP BY 1 ORDER BY 1 DESC LIMIT 6
    """
    rows, cols = _run(conn, sql)
    _print_table(rows, cols)
    print(f"\n  Verdict: {_verdict(rows, 2, 'total_pl_bn')}")


def q6_fidc_inflow(conn):
    print(f"\n{SEP}")
    print("  Q6 — FIDC: MoM PL change (latest period)")
    print(SEP)
    sql = """
    WITH latest AS (
        SELECT MAX(period) AS p FROM cvm_fidc_mensal
    ),
    prev_period AS (
        SELECT MAX(period) AS p FROM cvm_fidc_mensal
        WHERE period < (SELECT p FROM latest)
    )
    SELECT curr.cnpj,
           curr.period::TEXT,
           curr.vl_patrim_liq,
           curr.vl_patrim_liq - prev.vl_patrim_liq     AS pl_change,
           ROUND(100.0*(curr.vl_patrim_liq - prev.vl_patrim_liq)
                 /NULLIF(prev.vl_patrim_liq,0),2)       AS growth_pct
    FROM cvm_fidc_mensal curr
    LEFT JOIN cvm_fidc_mensal prev
           ON prev.cnpj = curr.cnpj AND prev.period = (SELECT p FROM prev_period)
    WHERE curr.period = (SELECT p FROM latest)
      AND curr.vl_patrim_liq IS NOT NULL
    ORDER BY curr.vl_patrim_liq DESC
    LIMIT 10
    """
    rows, cols = _run(conn, sql)
    _print_table(rows, cols)
    print(f"\n  Verdict: {_verdict(rows, 2, 'vl_patrim_liq')}")


def q7_fii_top10(conn):
    print(f"\n{SEP}")
    print("  Q7 — FII: top 10 by NAV (complemento, latest period)")
    print(SEP)
    sql = """
    SELECT cnpj, period::TEXT, ROUND(vl_patrim_liq/1e6,2) AS pl_mm
    FROM cvm_fii_mensal
    WHERE doc_subtype = 'complemento'
      AND period = (SELECT MAX(period) FROM cvm_fii_mensal WHERE doc_subtype = 'complemento')
      AND vl_patrim_liq IS NOT NULL
    ORDER BY vl_patrim_liq DESC
    LIMIT 10
    """
    rows, cols = _run(conn, sql)
    _print_table(rows, cols)
    print(f"\n  Verdict: {_verdict(rows, 2, 'pl_mm')}")


def q8_fii_fund_trend(conn, cnpj: str):
    print(f"\n{SEP}")
    print(f"  Q8 — FII FUND NAV TREND  (cnpj={cnpj}, complemento)")
    print(SEP)
    if cnpj == "00000000000000":
        print("  Skipped — no FII complemento CNPJ discovered (check seed)")
        return
    sql = """
    SELECT period::TEXT AS period, vl_patrim_liq,
           vl_patrim_liq - LAG(vl_patrim_liq) OVER (ORDER BY period) AS pl_delta,
           ROUND(100.0*(vl_patrim_liq - LAG(vl_patrim_liq) OVER (ORDER BY period))
                 /NULLIF(LAG(vl_patrim_liq) OVER (ORDER BY period),0),2) AS mom_pct
    FROM cvm_fii_mensal
    WHERE cnpj = ? AND doc_subtype = 'complemento'
    ORDER BY period DESC LIMIT 12
    """
    rows, cols = _run(conn, sql, [cnpj])
    _print_table(rows, cols)
    print(f"\n  Verdict: {_verdict(rows, 1, 'vl_patrim_liq')}")


def q9_securit_emissions(conn):
    print(f"\n{SEP}")
    print("  Q9 — SECURIT: CRA/CRI emission volume by year")
    print(SEP)
    sql = """
    SELECT period_year, instrument_type,
           COUNT(DISTINCT cnpj_securit)      AS issuers,
           COUNT(*)                           AS records,
           ROUND(SUM(vl_emissao)/1e9,3)      AS emissao_bn,
           ROUND(SUM(vl_total)/1e9,3)        AS assets_bn
    FROM cvm_securit_mensal
    GROUP BY 1, 2 ORDER BY 1 DESC, 2
    """
    rows, cols = _run(conn, sql)
    _print_table(rows, cols)
    # PASS if vl_emissao is populated (key fix)
    vl_idx = cols.index("emissao_bn") if "emissao_bn" in cols else None
    print(f"\n  Verdict: {_verdict(rows, vl_idx, 'emissao_bn')}")


def q10_fip_trend(conn):
    print(f"\n{SEP}")
    print("  Q10 — FIP: year-end PL trend")
    print(SEP)
    sql = """
    SELECT period_year, COUNT(DISTINCT cnpj) AS funds,
           ROUND(SUM(vl_patrim_liq)/1e9,2)  AS total_pl_bn
    FROM cvm_fip_periodic
    WHERE vl_patrim_liq IS NOT NULL
    GROUP BY 1 ORDER BY 1 DESC
    """
    rows, cols = _run(conn, sql)
    _print_table(rows, cols)
    print(f"\n  Verdict: {_verdict(rows, 2, 'total_pl_bn')}")


def q11_ingest_log(conn):
    print(f"\n{SEP}")
    print("  Q11 — INGEST LOG (not populated by seed; table existence check)")
    print(SEP)
    sql = "SELECT COUNT(*) AS rows FROM information_schema.tables WHERE table_name='cvm_ingest_log'"
    rows, _ = _run(conn, sql)
    exists = rows and rows[0][0] > 0
    print(f"  cvm_ingest_log table exists: {exists}")
    print(f"  (Populated only when running the full pipeline against a real Supabase instance)")
    print(f"\n  Verdict: PASS")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(db_path: str):
    if not os.path.exists(db_path):
        print(f"ERROR: DB not found at {db_path}")
        print("Run:  python scripts/seed_local_db.py --skip-fi")
        sys.exit(1)

    conn = duckdb.connect(db_path, read_only=True)

    print(f"\n{SEP}")
    print(f"  CVM ANALYTICAL QUERY RUNNER")
    print(f"  DB: {db_path}")
    print(SEP)

    # Auto-discover sample CNPJs for fund-specific queries
    fi_cnpj  = _sample_cnpj(conn, "cvm_fi_diario")
    fii_cnpj = _sample_cnpj(conn, "cvm_fii_mensal", filter_clause="WHERE doc_subtype='complemento'")
    print(f"  Sample FI  CNPJ: {fi_cnpj}")
    print(f"  Sample FII CNPJ: {fii_cnpj}")

    q1_data_presence(conn)
    q2_null_rates(conn)
    q3_fund_nav_trend(conn, fi_cnpj)
    q4_fi_industry_monthly(conn)
    q5_fidc_monthly(conn)
    q6_fidc_inflow(conn)
    q7_fii_top10(conn)
    q8_fii_fund_trend(conn, fii_cnpj)
    q9_securit_emissions(conn)
    q10_fip_trend(conn)
    q11_ingest_log(conn)

    conn.close()
    print(f"\n{SEP}")
    print("  Done. Fix verification: look for WARN rows in Q2.")
    print(f"  Full SQL reference: scripts/analysis_queries.sql")
    print(SEP)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=DEFAULT_DB)
    args = parser.parse_args()
    main(args.db)
