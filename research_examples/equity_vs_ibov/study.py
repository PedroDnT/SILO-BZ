"""Equity funds against the Ibovespa: what funds delivered and what holders got.

Same method as docs/reference/research/cdi-fund-vs-holder-return.md wherever it
applies: fund return from the quota on the window's two end dates (same
subclass, net of fees, before tax), median over funds, mean weighted by the
holders filed on the end date. The benchmark is B3's IBOV level
(``b3_index_level``), and the metric is the difference in percentage points,
never "% of the Ibovespa".

Run from the repository root, read only::

    python -m research_examples.equity_vs_ibov.study
"""
from __future__ import annotations

import statistics
from datetime import date
from typing import Dict, Iterable, List, Optional, Sequence

END = date(2026, 9, 30)
# Window start = last business day of the same month 1, 3 and 5 years earlier
# (the CDI study's month-end convention); 2023-09-30 was a Saturday.
WINDOWS = {12: date(2025, 9, 30), 36: date(2023, 9, 29), 60: date(2021, 9, 30)}

MAIN_CLASSES = {
    "AÇÕES - ATIVO - LIVRE",
    "AÇÕES - ATIVO - ÍNDICE ATIVO",
    "AÇÕES - ATIVO - VALOR / CRESCIMENTO",
    "AÇÕES - ATIVO - SUSTENTABILIDADE / GOVERNANÇA",
    "AÇÕES - INDEXADO - ÍNDICE PASSIVO",
}
PASSIVE_CLASS = "AÇÕES - INDEXADO - ÍNDICE PASSIVO"
EXCLUDED_CLASSES = {
    "MULTIMERCADO - ESTRATÉGIA - LONG & SHORT DIRECIONAL": "long_short",
    "MULTIMERCADO - ESTRATÉGIA - LONG & SHORT NEUTRO": "long_short",
    "AÇÕES - ATIVO - SMALL CAPS": "small_caps",
    "AÇÕES - ATIVO - SETORIAIS": "sectoral",
    "AÇÕES - INVESTIMENTO NO EXTERIOR": "foreign",
    "AÇÕES - ATIVO - DIVIDENDOS": "dividends",
    "AÇÕES - MONO AÇÃO": "single_stock",
    "AÇÕES - FUNDOS FECHADOS": "closed_end",
    "AÇÕES - FMP-FGTS": "fmp_fgts",
}
IBRX = {"IBRX", "IBRX-50"}


def period_return(q0: float, q1: float) -> float:
    """Return between two quotas (or two index levels)."""
    if q0 <= 0 or q1 <= 0:
        raise ValueError("quotas and levels must be positive")
    return q1 / q0 - 1


def annualize(r: float, years: float) -> float:
    return (1 + r) ** (1 / years) - 1


def excess_pp(fund_r: float, index_r: float) -> float:
    """Difference in percentage points: fund minus index."""
    return 100 * (fund_r - index_r)


def weighted_mean(values: Sequence[float], weights: Sequence[Optional[float]]) -> Optional[float]:
    """Mean of ``values`` weighted by ``weights``. A missing weight is never
    filled: the pair is left out, and the caller reports how many were."""
    pairs = [(v, w) for v, w in zip(values, weights) if w is not None]
    total = sum(w for _, w in pairs)
    if not pairs or total <= 0:
        return None
    return sum(v * w for v, w in pairs) / total


def group_of(classe_anbima: str, benchmark: Optional[str]) -> str:
    if classe_anbima in EXCLUDED_CLASSES:
        return EXCLUDED_CLASSES[classe_anbima]
    if classe_anbima not in MAIN_CLASSES:
        return "other_class"
    if benchmark is None:
        return "no_benchmark_on_file"
    if benchmark == "IBOVESPA":
        return "main"
    if benchmark in IBRX:
        return "ibrx"
    return "other_benchmark"


def summarize(rows: Iterable[dict], index_start: float, index_end: float, years: float) -> Dict[str, object]:
    """Statistics for funds with a quota on both end dates.

    Each row needs ``q0``, ``q1``, ``holders`` and ``pl``. With ``years`` > 1
    both the fund and the index return are annualized before the difference."""
    rows = list(rows)
    idx_r = period_return(index_start, index_end)
    if years > 1:
        idx_r = annualize(idx_r, years)
    fund_r = []
    for r in rows:
        f = period_return(r["q0"], r["q1"])
        fund_r.append(annualize(f, years) if years > 1 else f)
    diffs = [excess_pp(f, idx_r) for f in fund_r]
    out: Dict[str, object] = {
        "funds": len(rows),
        "index_return_pct": 100 * idx_r,
        "median_fund_return_pct": 100 * statistics.median(fund_r) if rows else None,
        "median_excess_pp": statistics.median(diffs) if rows else None,
        "holder_weighted_excess_pp": weighted_mean(diffs, [r["holders"] for r in rows]),
        "pl_weighted_excess_pp": weighted_mean(diffs, [r["pl"] for r in rows]),
        "holders": sum(r["holders"] for r in rows if r["holders"] is not None),
        "missing_holders": sum(1 for r in rows if r["holders"] is None),
        "funds_beating_index": sum(1 for d in diffs if d > 0),
    }
    return out


# ---------------------------------------------------------------------------
# Warehouse read (read only)
# ---------------------------------------------------------------------------

ROWS_SQL = """
WITH e AS (           -- class from the latest CVM extrato, as in the CDI study
  SELECT cnpj, classe_anbima, (fundo_cotas = 'S') AS fic
  FROM vw_fi_extrato_latest
  WHERE classe_anbima LIKE 'AÇÕES%%' OR classe_anbima LIKE 'MULTIMERCADO - ESTRATÉGIA - LONG%%'
),
rc AS (               -- declared benchmark, CVM 175 class register, as filed
  SELECT DISTINCT ON (cnpj_classe) cnpj_classe AS cnpj,
         upper(raw->>'Indicador_Desempenho') AS benchmark
  FROM cvm_registro_classe
  ORDER BY cnpj_classe, (situacao = 'Em Funcionamento Normal') DESC, data_registro DESC NULLS LAST
),
u AS (SELECT e.cnpj, e.classe_anbima, e.fic, rc.benchmark FROM e LEFT JOIN rc USING (cnpj)),
s AS (                -- quota on the start date
  SELECT d.cnpj, d.id_subclasse, d.vl_quota AS q0
  FROM cvm_fi_diario d JOIN u USING (cnpj)
  WHERE d.dt_comptc = %(start)s AND d.vl_quota > 0
),
t AS (                -- quota, holders and PL on the end date
  SELECT d.cnpj, d.id_subclasse, d.vl_quota AS q1, d.nr_cotst AS holders, d.vl_patrim_liq AS pl
  FROM cvm_fi_diario d JOIN u USING (cnpj)
  WHERE d.dt_comptc = %(end)s AND d.vl_quota > 0
)
SELECT u.cnpj, u.classe_anbima, u.fic, u.benchmark, s.id_subclasse, s.q0, t.q1, t.holders, t.pl,
       l.dt_comptc AS last_date, l.vl_quota AS q_last
FROM u
JOIN s USING (cnpj)
LEFT JOIN t ON t.cnpj = s.cnpj AND t.id_subclasse IS NOT DISTINCT FROM s.id_subclasse
LEFT JOIN LATERAL (   -- a fund with no end quota: its last quota inside the window
  SELECT d.dt_comptc, d.vl_quota FROM cvm_fi_diario d
  WHERE t.cnpj IS NULL AND d.cnpj = s.cnpj AND d.id_subclasse IS NOT DISTINCT FROM s.id_subclasse
    AND d.dt_comptc > %(start)s AND d.dt_comptc < %(end)s AND d.vl_quota > 0
  ORDER BY d.dt_comptc DESC LIMIT 1
) l ON TRUE
"""

ACTIVE_SQL = """
WITH e AS (
  SELECT cnpj, classe_anbima FROM vw_fi_extrato_latest
  WHERE classe_anbima LIKE 'AÇÕES%%' OR classe_anbima LIKE 'MULTIMERCADO - ESTRATÉGIA - LONG%%'
),
rc AS (
  SELECT DISTINCT ON (cnpj_classe) cnpj_classe AS cnpj, upper(raw->>'Indicador_Desempenho') AS benchmark
  FROM cvm_registro_classe
  ORDER BY cnpj_classe, (situacao = 'Em Funcionamento Normal') DESC, data_registro DESC NULLS LAST
)
SELECT e.classe_anbima, rc.benchmark, count(DISTINCT e.cnpj)
FROM e LEFT JOIN rc USING (cnpj)
WHERE e.cnpj IN (SELECT cnpj FROM cvm_fi_diario WHERE dt_comptc = %(end)s AND vl_quota > 0)
GROUP BY 1, 2
"""

INDEX_SQL = """
SELECT trade_date, level FROM b3_index_level
WHERE index_code = 'IBOV' AND trade_date BETWEEN %(start)s AND %(end)s
"""


def _fetch(client, sql: str, params: dict) -> List[tuple]:
    with client.cursor() as cur:
        cur.execute("SET default_transaction_read_only = on")
        cur.execute(sql, params)
        return cur.fetchall()


def pick_one_subclass(rows: List[dict]) -> List[dict]:
    """One row per fund. A fund filed under several subclasses keeps the one
    with the largest end-date PL (no such case in the CDI study's universe)."""
    best: Dict[str, dict] = {}
    for r in rows:
        cur = best.get(r["cnpj"])
        if cur is None or (r["pl"] or 0) > (cur["pl"] or 0):
            best[r["cnpj"]] = r
    return list(best.values())


def run(client) -> Dict[int, Dict[str, object]]:
    cols = ["cnpj", "classe_anbima", "fic", "benchmark", "id_subclasse", "q0", "q1", "holders", "pl",
            "last_date", "q_last"]
    results: Dict[int, Dict[str, object]] = {}
    for months, start in WINDOWS.items():
        params = {"start": start, "end": END}
        idx = {d: float(v) for d, v in _fetch(client, INDEX_SQL, params)}
        if start not in idx or END not in idx:
            raise LookupError(f"IBOV level missing on {start} or {END}")
        raw = [dict(zip(cols, r)) for r in _fetch(client, ROWS_SQL, params)]
        for r in raw:
            for k in ("q0", "q1", "q_last", "pl"):
                r[k] = float(r[k]) if r[k] is not None else None
            r["group"] = group_of(r["classe_anbima"], r["benchmark"])
        survivors = pick_one_subclass([r for r in raw if r["q1"] is not None])
        alive = {r["cnpj"] for r in survivors}
        closed = [r for r in raw if r["q1"] is None and r["cnpj"] not in alive]
        years = months / 12
        win: Dict[str, object] = {"start": start, "index_start": idx[start], "index_end": idx[END]}
        for g in sorted({r["group"] for r in raw}):
            rows = [r for r in survivors if r["group"] == g]
            win[g] = summarize(rows, idx[start], idx[END], years)
            win[g]["fic"] = sum(1 for r in rows if r["fic"])
        main = [r for r in survivors if r["group"] == "main"]
        win["main_active"] = summarize([r for r in main if r["classe_anbima"] != PASSIVE_CLASS], idx[start], idx[END], years)
        win["main_passive"] = summarize([r for r in main if r["classe_anbima"] == PASSIVE_CLASS], idx[start], idx[END], years)
        closed_main = [r for r in closed if r["group"] == "main" and r["last_date"] in idx]
        win["closed_by_group"] = {g: sum(1 for r in closed if r["group"] == g) for g in sorted({r["group"] for r in closed})}
        win["closed_main_with_last_quota"] = len(closed_main)
        win["closed_main_median_excess_pp_own_span"] = (
            statistics.median(excess_pp(period_return(r["q0"], r["q_last"]), period_return(idx[start], idx[r["last_date"]]))
                              for r in closed_main) if closed_main else None)
        win["top_main_by_pl"] = sorted(main, key=lambda r: -(r["pl"] or 0))[:3]
        results[months] = win
    with client.cursor() as cur:
        cur.execute("SET default_transaction_read_only = on")
        cur.execute(ACTIVE_SQL, {"end": END})
        results[0] = {"active_by_class_benchmark": cur.fetchall()}
    return results


if __name__ == "__main__":  # pragma: no cover
    import json
    from src.store.pg_client import get_pg_client

    print(json.dumps(run(get_pg_client()), default=str, indent=1, ensure_ascii=False))
