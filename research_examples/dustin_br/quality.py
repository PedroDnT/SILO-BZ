#!/usr/bin/env python3
"""Build the DUSTIN-BR matrix from the warehouse and report on its quality.

What the Research Build workflow runs (.github/workflows/research_build.yml):

    python -m research_examples.dustin_br.quality \\
        --start 2008-01-02 --end 2026-09-25 --out-dir out

It writes three files to ``--out-dir``:

* ``dustin_br.csv``: the matrix, exactly as ``build_dataset`` writes it;
* ``coverage_by_year.csv``: for every column, the share of sessions with a value;
* ``quality.md``: sessions and columns, B3 sessions a source lacks,
  staleness-nulled cells per block, how often B3's extrapolated tail leaves
  ``di_5y`` / ``di_10y`` NULL, coverage by year for one column per source, and
  the no-look-ahead check re-run on the real inputs.

The check is the one ``tests/test_dustin_br_builder.py`` makes on synthetic
data: rebuild with every input that was not yet public at a cutoff removed,
and no row up to the cutoff may change. A changed cell fails the run (exit 1)
after the files are written, so they can be inspected.

Read only, like the builder: its queries run with
``default_transaction_read_only = on``.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_examples.dustin_br import build_dataset as bd  # noqa: E402

# One column per source: enough to see where each starts and where it thins out.
KEY_COLUMNS = ("di_1y", "di_5y", "di_10y", "breakeven_2y", "brazil_sovereign_risk_proxy",
               "usdbrl", "selic", "ipca", "commodity_index", "focus_ipca_12m", "ust_10y",
               "ofr_fsi", "brent", "corr_di2y_usdbrl_63d", "di1_open_interest")


def published_by(cutoff: date, curves: pd.DataFrame, series: Dict[str, pd.DataFrame],
                 futures: Optional[pd.DataFrame]):
    """The inputs as they stood at the end of session ``cutoff``: every
    observation not yet public then is removed, by its availability rule."""
    kept = {}
    for name, frame in series.items():
        rule = bd.RULES[bd.SCALAR_SERIES[name][0]]
        kept[name] = frame.loc[np.array([rule.available(d) <= cutoff for d in frame["obs_date"]], dtype=bool)]
    # B3 curves and DI1 settlements are public the evening of their session.
    past_futures = None if futures is None else futures[futures["trade_date"] <= cutoff]
    return curves[curves["trade_date"] <= cutoff], kept, past_futures


def changed_cells(expected: pd.DataFrame, got: pd.DataFrame) -> int:
    """Cells that differ, a NULL matching a NULL. A column the rebuild lacks
    reads as NULL: a block whose input is not public yet is not built at all."""
    expected = expected.reset_index(drop=True)
    got = got.reset_index(drop=True).reindex(columns=expected.columns)
    if len(expected) != len(got):
        return max(len(expected), len(got)) * expected.shape[1]
    changed = 0
    for col in expected.columns:
        a, b = expected[col], got[col]
        both_null = a.isna() & b.isna()
        if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b):
            same = np.isclose(a.astype(float), b.astype(float), rtol=1e-12, atol=0.0) | both_null
        else:
            same = (a == b) | both_null
        changed += int((~same).sum())
    return changed


def look_ahead(sessions: Sequence[date], curves: pd.DataFrame, series: Dict[str, pd.DataFrame],
               futures: Optional[pd.DataFrame], full: pd.DataFrame,
               cutoffs: Sequence[date]) -> Dict[date, int]:
    """Changed cells in the rows up to each cutoff once everything published
    after it is removed. Zero at every cutoff is the builder's promise."""
    result = {}
    for cutoff in cutoffs:
        c, s, f = published_by(cutoff, curves, series, futures)
        part, _ = bd.build([d for d in sessions if d <= cutoff], c, s, f)
        result[cutoff] = changed_cells(full[full["date"] <= cutoff], part)
    return result


def missing_sessions(sessions: Sequence[date], futures: Optional[pd.DataFrame],
                     equity_sessions: Sequence[date]) -> Dict[str, List[date]]:
    """B3 sessions a source lacks. The session grid is the days ``PRE`` was
    published; it is checked both ways against the equity calendar where one
    is stored, and DI1 is checked from its own first session. A gap here is
    the source's (B3 served an empty archive for PR210610.zip, a session),
    and the builder leaves that day's cells NULL."""
    pre, equity = set(sessions), set(equity_sessions)
    out: Dict[str, List[date]] = {}
    if pre and equity:
        lo, hi = max(min(pre), min(equity)), min(max(pre), max(equity))
        out["PRE curve missing on an equity session"] = sorted(d for d in equity - pre if lo <= d <= hi)
        out["PRE curve on a day with no equity session"] = sorted(d for d in pre - equity if lo <= d <= hi)
    if pre and futures is not None and not futures.empty:
        di1 = set(futures["trade_date"])
        out[f"DI1 settlements missing on a PRE session (from {min(di1)})"] = sorted(
            d for d in pre - di1 if d >= min(di1))
    return out


def _year(frame: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(frame["date"]).dt.year.rename("year")


def coverage_by_year(frame: pd.DataFrame) -> pd.DataFrame:
    """Share of sessions with a value, per column and calendar year."""
    return frame.drop(columns="date").notna().groupby(_year(frame)).mean()


def tail_masking(frame: pd.DataFrame) -> pd.DataFrame:
    """Per year: the median ``di_anchor_du`` and the share of sessions where a
    long DI tenor falls in B3's extrapolated tail, so the builder leaves it NULL."""
    year = _year(frame)
    anchor = frame["di_anchor_du"].astype(float)
    out = pd.DataFrame({"sessions": year.value_counts().sort_index(),
                        "median_anchor_du": anchor.groupby(year).median()})
    for name in ("di_5y", "di_10y"):
        out[f"{name}_in_tail"] = (anchor < bd.DI_TENORS_DU[name]).groupby(year).mean()
    return out


def _pct(x: float) -> str:
    return "" if pd.isna(x) else f"{100 * x:.0f}"


def _table(header: Sequence[str], rows) -> list:
    return ["| " + " | ".join(header) + " |", "|" + "---|" * len(header),
            *("| " + " | ".join(str(c) for c in r) + " |" for r in rows)]


def render(frame: pd.DataFrame, nulled: Dict[str, int], look: Dict[date, int],
           start: date, end: date, missing: Optional[Dict[str, List[date]]] = None) -> str:
    """quality.md: what the matrix holds, and whether the look-ahead check passed."""
    failed = {d: n for d, n in look.items() if n}
    empty = [c for c in frame.columns if frame[c].isna().all()]
    lines = [
        f"# DUSTIN-BR matrix, {start} to {end}",
        "",
        f"- **{len(frame):,} sessions** (rows), {frame['date'].min()} to {frame['date'].max()}; "
        f"{frame.shape[1]} columns.",
        f"- Builder commit: {os.getenv('GITHUB_SHA') or 'not recorded (local run)'}.",
        f"- **No look-ahead: {'FAILED' if failed else 'passed'}.** Rebuilt at "
        f"{', '.join(str(d) for d in look) or 'no cutoff'} with every input published later removed: "
        + (f"changed cells {failed}." if failed else "no row up to a cutoff changed."),
        "- Staleness-nulled cells per block (a value past its limit is NULL, never carried): "
        + (", ".join(f"{k} {v:,}" for k, v in nulled.items() if v) or "none") + ".",
        f"- Columns with no value in the window: {', '.join(empty) or 'none'}.",
        "",
        "## Sessions",
        "",
        "B3 sessions a source lacks. The equity calendar is `b3_cotahist` (PETR4 cash rows),",
        "over the dates both hold.",
        "",
        *(f"- {what}: {', '.join(str(d) for d in days) or 'none'}." for what, days in (missing or {}).items()),
        "",
        "## Coverage by year",
        "",
        "Share of sessions with a value, %. Every column is in `coverage_by_year.csv`.",
        "",
    ]
    cov = coverage_by_year(frame)
    cols = [c for c in KEY_COLUMNS if c in cov.columns]
    counts = _year(frame).value_counts()
    lines += _table(["year", "sessions", *cols],
                    [(y, counts[y], *(_pct(cov.at[y, c]) for c in cols)) for y in cov.index])
    lines += [
        "",
        "## B3's extrapolated tail",
        "",
        "`di_anchor_du` is where B3's straight-line extension of `PRE` begins (past the",
        "DI1 contracts). A tenor beyond it is B3's extrapolation, so the builder leaves it NULL.",
        "",
    ]
    tail = tail_masking(frame)
    lines += _table(["year", "sessions", "median anchor (du)", "di_5y in tail %", "di_10y in tail %"],
                    [(y, int(r.sessions), f"{r.median_anchor_du:.0f}", _pct(r.di_5y_in_tail),
                      _pct(r.di_10y_in_tail)) for y, r in tail.iterrows()])
    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--out-dir", required=True)
    args = p.parse_args(argv)
    from src.store.pg_client import get_pg_client

    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    client = get_pg_client()
    sessions, curves, series, futures = bd.load(client, start, end)
    in_window = [d for d in sessions if start <= d <= end]
    if not in_window:
        print("no PRE sessions in the window — has the b3_reference_rate backfill run?", file=sys.stderr)
        return 1
    full, nulled = bd.build(sessions, curves, series, futures)
    frame = full[(full["date"] >= start) & (full["date"] <= end)]
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out / "dustin_br.csv", index=False)
    coverage_by_year(frame).to_csv(out / "coverage_by_year.csv")
    # Three cutoffs at the quartiles of the window: each is a rebuild.
    cutoffs = [in_window[len(in_window) * k // 4] for k in (1, 2, 3)]
    look = look_ahead(sessions, curves, series, futures, full, cutoffs)
    # PETR4 trades every session, and its cash rows are an index range scan.
    equity = bd._query(client, "SELECT trade_date FROM b3_cotahist WHERE codneg = 'PETR4' "
                       "AND tpmerc = '010' AND trade_date BETWEEN %s AND %s", (start, end), ["trade_date"])
    in_futures = None if futures is None else futures[futures["trade_date"] >= start]
    missing = missing_sessions(in_window, in_futures, equity["trade_date"].tolist())
    report = render(frame, nulled, look, start, end, missing)
    (out / "quality.md").write_text(report, encoding="utf-8")
    print(report)
    return 1 if any(look.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
