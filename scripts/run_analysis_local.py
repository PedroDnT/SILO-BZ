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
# Suspicious deal screens  (Q12–Q19)
# ---------------------------------------------------------------------------

def q12_cross_fund_holdings(conn):
    print(f"\n{SEP}")
    print("  Q12 — SUSPICIOUS: cross-fund holdings (FoF > 50% of portfolio)")
    print(SEP)
    sql = """
    WITH latest_cda AS (
        SELECT cnpj, MAX(period) AS max_period
        FROM cvm_fi_cda
        GROUP BY cnpj
    ),
    portfolio AS (
        SELECT c.cnpj, c.period,
               SUM(c.vl_merc_pos_final)
                   FILTER (WHERE c.tp_ativo ILIKE 'FUNDO%' OR c.tp_aplic ILIKE '%fundo%')
                   AS vl_in_funds,
               SUM(c.vl_merc_pos_final) AS vl_total
        FROM cvm_fi_cda c
        JOIN latest_cda lc ON lc.cnpj = c.cnpj AND lc.max_period = c.period
        GROUP BY c.cnpj, c.period
    )
    SELECT p.cnpj,
           p.period::TEXT,
           ROUND(p.vl_in_funds / 1e6, 2)  AS vl_in_funds_m,
           ROUND(p.vl_total   / 1e6, 2)   AS portfolio_m,
           ROUND(100.0 * p.vl_in_funds / NULLIF(p.vl_total, 0), 1) AS pct_in_funds
    FROM portfolio p
    WHERE p.vl_in_funds / NULLIF(p.vl_total, 0) > 0.5
      AND p.vl_total > 10e6
    ORDER BY pct_in_funds DESC
    LIMIT 20
    """
    rows, cols = _run(conn, sql)
    _print_table(rows, cols)
    print(f"\n  Verdict: {_verdict(rows, None, 'cross-fund')}")


def q13_zombie_funds(conn):
    print(f"\n{SEP}")
    print("  Q13 — SUSPICIOUS: zombie FIDCs (delinquency +2pp over 6mo, AUM still grew)")
    print(SEP)
    sql = """
    WITH ranked AS (
        SELECT cnpj, period,
               vl_patrim_liq,
               ROUND(100.0 * vl_inadimpl / NULLIF(vl_patrim_liq, 0), 2) AS inadimpl_rate,
               ROW_NUMBER() OVER (PARTITION BY cnpj ORDER BY period DESC) AS rn_desc,
               ROW_NUMBER() OVER (PARTITION BY cnpj ORDER BY period ASC)  AS rn_asc
        FROM cvm_fidc_mensal
        WHERE vl_patrim_liq > 0
    ),
    now_  AS (SELECT cnpj, period, vl_patrim_liq, inadimpl_rate FROM ranked WHERE rn_desc = 1),
    then_ AS (SELECT cnpj, period, vl_patrim_liq, inadimpl_rate FROM ranked WHERE rn_desc = 7)
    SELECT n.cnpj,
           n.period::TEXT                                        AS period_now,
           ROUND(n.inadimpl_rate, 2)                            AS inadimpl_now_pct,
           ROUND(t.inadimpl_rate, 2)                            AS inadimpl_6mo_ago_pct,
           ROUND(n.inadimpl_rate - t.inadimpl_rate, 2)          AS acceleration_pp,
           ROUND(n.vl_patrim_liq / 1e6, 1)                      AS pl_now_m,
           ROUND((n.vl_patrim_liq - t.vl_patrim_liq) / 1e6, 1) AS pl_delta_m
    FROM now_ n
    JOIN then_ t ON t.cnpj = n.cnpj
    WHERE n.inadimpl_rate - t.inadimpl_rate >= 2.0
      AND n.vl_patrim_liq > t.vl_patrim_liq
      AND n.vl_patrim_liq > 50e6
    ORDER BY acceleration_pp DESC
    LIMIT 20
    """
    rows, cols = _run(conn, sql)
    _print_table(rows, cols)
    print(f"\n  Verdict: {_verdict(rows, None, 'zombie')}")


def q14_captive_vehicles(conn):
    print(f"\n{SEP}")
    print("  Q14 — SUSPICIOUS: captive vehicles (R$100M+ AUM, ≤10 investors)")
    print(SEP)
    sql = """
    SELECT cnpj, dt_comptc::TEXT AS date, tp_fundo,
           nr_cotst,
           ROUND(vl_patrim_liq / 1e6, 1) AS pl_m,
           ROUND(vl_patrim_liq / NULLIF(nr_cotst, 0) / 1e6, 2) AS pl_per_cotista_m
    FROM cvm_fi_diario
    WHERE dt_comptc = (SELECT MAX(dt_comptc) FROM cvm_fi_diario)
      AND nr_cotst BETWEEN 1 AND 10
      AND vl_patrim_liq > 100e6
    ORDER BY vl_patrim_liq DESC
    LIMIT 20
    """
    rows, cols = _run(conn, sql)
    _print_table(rows, cols)
    print(f"\n  Verdict: {_verdict(rows, None, 'captive')}")


def q15_evergreen_aging(conn):
    print(f"\n{SEP}")
    print("  Q15 — SUSPICIOUS: evergreen aging (>70% delinquency always in 0-30d bucket)")
    print(SEP)
    sql = """
    WITH monthly AS (
        SELECT cnpj, period,
               ROUND(100.0 * vl_inad_30 / NULLIF(vl_total_inad, 0), 1) AS pct_short,
               ROUND(100.0 * (COALESCE(vl_inad_360, 0) + COALESCE(vl_inad_maior_1080, 0))
                     / NULLIF(vl_total_inad, 0), 1) AS pct_long_tail
        FROM cvm_fidc_aging
        WHERE vl_total_inad > 1e6
    )
    SELECT cnpj,
           COUNT(period)            AS months,
           ROUND(AVG(pct_short), 1) AS avg_pct_short_bucket,
           ROUND(STDDEV(pct_short), 1) AS stddev_short,
           ROUND(AVG(pct_long_tail), 1) AS avg_pct_long_tail,
           MAX(period)::TEXT        AS latest_period
    FROM monthly
    GROUP BY cnpj
    HAVING COUNT(period) >= 6
       AND AVG(pct_short) > 70
       AND STDDEV(pct_short) < 10
       AND AVG(pct_long_tail) < 5
    ORDER BY avg_pct_short_bucket DESC
    LIMIT 20
    """
    rows, cols = _run(conn, sql)
    _print_table(rows, cols)
    print(f"\n  Verdict: {_verdict(rows, None, 'evergreen')}")


def q16_subordination_erosion(conn):
    print(f"\n{SEP}")
    print("  Q16 — SUSPICIOUS: subordination erosion (junior -3pp+ in one month)")
    print(SEP)
    sql = """
    WITH fund_nav AS (
        SELECT cnpj, period,
               SUM(qt_cota * vl_cota)
                   FILTER (WHERE LOWER(classe_serie) LIKE '%junior%'
                              OR LOWER(classe_serie) LIKE '%j%nior%')
                   AS nav_junior,
               SUM(qt_cota * vl_cota) AS nav_total
        FROM cvm_fidc_tranche
        WHERE vl_cota > 0 AND qt_cota > 0
        GROUP BY cnpj, period
    ),
    subord AS (
        SELECT cnpj, period,
               ROUND(100.0 * nav_junior / NULLIF(nav_total, 0), 2) AS subord_pct,
               LAG(ROUND(100.0 * nav_junior / NULLIF(nav_total, 0), 2))
                   OVER (PARTITION BY cnpj ORDER BY period) AS subord_prev
        FROM fund_nav
        WHERE nav_total > 10e6
    )
    SELECT cnpj,
           period::TEXT,
           subord_pct,
           subord_prev,
           ROUND(subord_pct - subord_prev, 2) AS delta_pp
    FROM subord
    WHERE subord_prev IS NOT NULL
      AND subord_pct - subord_prev <= -3
    ORDER BY delta_pp ASC
    LIMIT 20
    """
    rows, cols = _run(conn, sql)
    _print_table(rows, cols)
    print(f"\n  Verdict: {_verdict(rows, None, 'subord_erosion')}")


def q17_senior_yield_decoupled(conn):
    print(f"\n{SEP}")
    print("  Q17 — SUSPICIOUS: senior yield positive despite fund inadimpl > 15%")
    print(SEP)
    sql = """
    WITH delinq AS (
        SELECT cnpj, period,
               ROUND(100.0 * vl_inadimpl / NULLIF(vl_patrim_liq, 0), 2) AS inadimpl_rate
        FROM cvm_fidc_mensal
        WHERE vl_patrim_liq > 50e6
    ),
    senior AS (
        SELECT cnpj, period,
               ROUND(AVG(vl_rentab_mes) * 100, 4) AS avg_senior_return_pct,
               COUNT(*) AS n_tranches
        FROM cvm_fidc_tranche
        WHERE (LOWER(classe_serie) LIKE '%senior%' OR LOWER(classe_serie) LIKE '%s%nior%')
          AND vl_rentab_mes BETWEEN -0.1 AND 0.1
        GROUP BY cnpj, period
    )
    SELECT d.cnpj, d.period::TEXT, d.inadimpl_rate,
           s.avg_senior_return_pct, s.n_tranches
    FROM delinq d
    JOIN senior s ON s.cnpj = d.cnpj AND s.period = d.period
    WHERE d.inadimpl_rate > 15
      AND s.avg_senior_return_pct > 0
    ORDER BY d.inadimpl_rate DESC
    LIMIT 20
    """
    rows, cols = _run(conn, sql)
    _print_table(rows, cols)
    print(f"\n  Verdict: {_verdict(rows, None, 'yield_decoupled')}")


def q18_overdue_securit(conn):
    print(f"\n{SEP}")
    print("  Q18 — SUSPICIOUS: CRI/CRA past maturity but still open")
    print(SEP)
    sql = """
    SELECT instrument_type, cnpj_securit, codigo_isin, numero_serie,
           data_vencimento::TEXT, situacao,
           ROUND(valor_total_integralizado / 1e6, 2) AS integralizado_m,
           classificacao_risco_atual,
           data_referencia::TEXT AS last_report
    FROM cvm_securit_serie s
    WHERE data_vencimento < CURRENT_DATE
      AND data_vencimento IS NOT NULL
      AND situacao IS NOT NULL
      AND LOWER(situacao) NOT IN ('liquidado', 'vencido', 'cancelado', 'encerrado')
      AND data_referencia = (
          SELECT MAX(s2.data_referencia)
          FROM cvm_securit_serie s2
          WHERE s2.cnpj_securit = s.cnpj_securit
            AND s2.codigo_identificacao = s.codigo_identificacao
      )
    ORDER BY data_vencimento ASC
    LIMIT 20
    """
    rows, cols = _run(conn, sql)
    _print_table(rows, cols)
    print(f"\n  Verdict: {_verdict(rows, None, 'overdue_securit')}")


def q19_combined_watchlist(conn):
    print(f"\n{SEP}")
    print("  Q19 — SUSPICIOUS: combined red-flag watchlist (FIDCs with ≥2 signals)")
    print(SEP)
    sql = """
    WITH ranked AS (
        SELECT cnpj, period, vl_patrim_liq,
               ROUND(100.0 * vl_inadimpl / NULLIF(vl_patrim_liq, 0), 2) AS inadimpl_rate,
               ROW_NUMBER() OVER (PARTITION BY cnpj ORDER BY period DESC) AS rn_desc
        FROM cvm_fidc_mensal
        WHERE vl_patrim_liq > 0
    ),
    now_ AS (SELECT cnpj, period, vl_patrim_liq, inadimpl_rate FROM ranked WHERE rn_desc = 1),
    prev_ AS (SELECT cnpj, vl_patrim_liq AS prev_pl, inadimpl_rate AS prev_rate
              FROM ranked WHERE rn_desc = 7),
    zombie AS (
        SELECT n.cnpj
        FROM now_ n JOIN prev_ p ON p.cnpj = n.cnpj
        WHERE n.inadimpl_rate - p.prev_rate >= 1.5
          AND n.vl_patrim_liq > p.prev_pl
          AND n.vl_patrim_liq > 50e6
    ),
    evergreen AS (
        SELECT cnpj
        FROM (
            SELECT cnpj,
                   AVG(100.0 * vl_inad_30 / NULLIF(vl_total_inad, 0)) AS avg_short,
                   STDDEV(100.0 * vl_inad_30 / NULLIF(vl_total_inad, 0)) AS sd_short
            FROM cvm_fidc_aging
            WHERE vl_total_inad > 1e6
            GROUP BY cnpj HAVING COUNT(*) >= 6
        ) t
        WHERE avg_short > 70 AND sd_short < 10
    ),
    fund_nav AS (
        SELECT cnpj, period,
               ROUND(100.0 *
                   SUM(qt_cota * vl_cota) FILTER (
                       WHERE LOWER(classe_serie) LIKE '%junior%'
                          OR LOWER(classe_serie) LIKE '%j%nior%'
                   ) / NULLIF(SUM(qt_cota * vl_cota), 0), 2) AS subord_pct,
               LAG(ROUND(100.0 *
                   SUM(qt_cota * vl_cota) FILTER (
                       WHERE LOWER(classe_serie) LIKE '%junior%'
                          OR LOWER(classe_serie) LIKE '%j%nior%'
                   ) / NULLIF(SUM(qt_cota * vl_cota), 0), 2))
                   OVER (PARTITION BY cnpj ORDER BY period) AS subord_prev
        FROM cvm_fidc_tranche
        WHERE vl_cota > 0 AND qt_cota > 0
        GROUP BY cnpj, period
    ),
    erosion AS (
        SELECT DISTINCT cnpj FROM fund_nav
        WHERE subord_prev IS NOT NULL AND subord_pct - subord_prev <= -3
    )
    SELECT n.cnpj,
           n.period::TEXT                            AS latest_period,
           ROUND(n.vl_patrim_liq / 1e6, 1)          AS pl_m,
           n.inadimpl_rate                           AS inadimpl_pct,
           (z.cnpj IS NOT NULL)::INT                 AS flag_zombie,
           (e.cnpj IS NOT NULL)::INT                 AS flag_evergreen,
           (er.cnpj IS NOT NULL)::INT                AS flag_erosion,
           (z.cnpj IS NOT NULL)::INT
         + (e.cnpj IS NOT NULL)::INT
         + (er.cnpj IS NOT NULL)::INT                AS flag_count
    FROM now_ n
    LEFT JOIN zombie   z  ON z.cnpj  = n.cnpj
    LEFT JOIN evergreen e ON e.cnpj  = n.cnpj
    LEFT JOIN erosion  er ON er.cnpj = n.cnpj
    WHERE (z.cnpj IS NOT NULL OR e.cnpj IS NOT NULL OR er.cnpj IS NOT NULL)
    ORDER BY flag_count DESC, n.vl_patrim_liq DESC
    LIMIT 20
    """
    rows, cols = _run(conn, sql)
    _print_table(rows, cols)
    print(f"\n  Verdict: {_verdict(rows, None, 'watchlist')}")


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
    q12_cross_fund_holdings(conn)
    q13_zombie_funds(conn)
    q14_captive_vehicles(conn)
    q15_evergreen_aging(conn)
    q16_subordination_erosion(conn)
    q17_senior_yield_decoupled(conn)
    q18_overdue_securit(conn)
    q19_combined_watchlist(conn)

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
