#!/usr/bin/env python3
"""DUSTIN-BR research dataset: one point-in-time row per B3 session.

Builds the daily feature matrix for a Brazilian rates-regime model from the
landing tables of migration 48 and the existing BACEN tables. It builds NO
model and NO target: labels look forward by definition and belong in the
modelling notebook.

The one rule everything here serves: **a value appears on row t only if it
was public by the end of B3 session t.** Every source has an availability
rule (docs/research/dustin_br_data_sources.md §8, mirrored in ``RULES``):

    DI curves, DOC, USDBRL, UST, VIX, SELIC   same day as the observation
    Brent (EIA, weekly release)               the day after the first Wednesday after it
    IPCA, IC-Br (monthly, dated the 1st)      the 15th of the next month
    Focus (survey day D)                      the Tuesday after D's week

Mechanics, in order:

1. Each source is kept on its OWN observation calendar, as
   ``(obs_date, value, available_date)``.
2. Momentum and realised volatility are computed on that native calendar
   (Brent's 21-day vol is 21 Brent days, not 21 B3 sessions of a series that
   only moves once a week). Pair correlations use the dates both sources
   observed, and become available when the later of the two does.
3. Every column is then as-of joined to the B3 session grid on
   ``available_date``, with a staleness limit in sessions per source. Past it
   the value is NULL and counted, never carried forward blindly.
4. Rolling windows need their full length (no partial windows): a 63-day
   feature is NULL for its first 62 observations.

DI constant-maturity rates come from B3's PRE curve (the DI x pré reference
curve, whose vertices include every DI1 maturity at its settlement rate),
interpolated flat-forward in business days on a 252-day basis — the DI
convention. No extrapolation: a tenor beyond the longest vertex is NULL.

Run (reads with the operator's POSTGRES_URL through src.store.pg_client):

    python -m research_examples.dustin_br.build_dataset \\
        --start 2008-01-02 --end 2026-09-25 --out dustin_br.csv
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# ---------------------------------------------------------------------------
# Availability rules
# ---------------------------------------------------------------------------


def same_day(d: date) -> date:
    return d


def eia_weekly_release(d: date) -> date:
    """EIA releases spot prices weekly on Wednesday, through the previous day
    (measured: release 2026-09-23 carried data to 09-22). So an observation
    is public on the first Wednesday strictly after it — a Wednesday's own
    price waits a full week — plus one day for holiday-shifted releases."""
    wednesday = d + timedelta(days=(2 - d.weekday()) % 7 or 7)
    return wednesday + timedelta(days=1)


def fifteenth_of_next_month(d: date) -> date:
    """IPCA (IBGE, ~10th of M+1) and IC-Br (BCB, early M+1) for month M dated
    on its 1st. The 15th is a conservative ASSUMPTION, not a release calendar."""
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(y, m, 15)


def tuesday_after_week(d: date) -> date:
    """Focus: statistics dated D are published the Monday after D's week
    (measured: on Sunday 2026-09-27 the newest value was dated 09-18).
    Tuesday adds one day for holiday Mondays."""
    return d - timedelta(days=d.weekday()) + timedelta(days=8)


@dataclass(frozen=True)
class Rule:
    available: Callable[[date], date]
    max_stale_sessions: int


RULES: Dict[str, Rule] = {
    "di": Rule(same_day, 0),
    "usdbrl": Rule(same_day, 5),
    "ust": Rule(same_day, 5),
    "vix": Rule(same_day, 5),
    "selic": Rule(same_day, 5),
    "brent": Rule(eia_weekly_release, 10),
    "monthly": Rule(fifteenth_of_next_month, 45),
    "focus": Rule(tuesday_after_week, 10),
}

MOMENTUM_WINDOWS = (5, 21, 63)
VOL_WINDOWS = (21, 63)
CORR_WINDOWS = (21, 63)
DI_TENORS_DU = {"di_1y": 252, "di_2y": 504, "di_3y": 756, "di_5y": 1260, "di_10y": 2520}

# ---------------------------------------------------------------------------
# DI curve
# ---------------------------------------------------------------------------


def flat_forward(vertices_du: Sequence[int], rates_pct: Sequence[float], target_du: int) -> float:
    """Rate (% a.a., 252 basis) at ``target_du`` by flat-forward interpolation.

    Log discount factors are linear in business days between the two
    neighbouring vertices, which is exactly a constant forward rate between
    them. Returns NaN outside [shortest, longest] vertex: no extrapolation.
    """
    du = np.asarray(vertices_du, dtype=float)
    r = np.asarray(rates_pct, dtype=float)
    order = np.argsort(du)
    du, r = du[order], r[order]
    if len(du) == 0 or target_du < du[0] or target_du > du[-1]:
        return float("nan")
    log_df = -du / 252.0 * np.log1p(r / 100.0)
    lt = float(np.interp(target_du, du, log_df))
    return (math.exp(-lt * 252.0 / target_du) - 1.0) * 100.0


def di_constant_maturity(curves: pd.DataFrame) -> pd.DataFrame:
    """One row per session: DI rates at the DI_TENORS_DU business-day tenors."""
    pre = curves[curves["curve"] == "PRE"]
    out = []
    for trade_date, g in pre.groupby("trade_date", sort=True):
        g = g[g["business_days"] > 0]
        row = {"obs_date": trade_date}
        for name, du in DI_TENORS_DU.items():
            row[name] = flat_forward(g["business_days"].to_numpy(), g["rate"].astype(float).to_numpy(), du)
        out.append(row)
    return pd.DataFrame(out, columns=["obs_date", *DI_TENORS_DU])


def doc_one_year_effective(curves: pd.DataFrame) -> pd.DataFrame:
    """B3 DOC (clean onshore dollar coupon) at 365 calendar days, as an
    annual effective rate in %. ASSUMPTION to verify against B3's methodology
    before modelling: DOC is a linear rate on a 360-day basis, so over one
    year of 365 days the accumulation is 1 + r·365/360. Linear interpolation
    in calendar days between the neighbouring vertices; no extrapolation."""
    doc = curves[(curves["curve"] == "DOC") & (curves["calendar_days"] >= 30)]
    out = []
    for trade_date, g in doc.groupby("trade_date", sort=True):
        g = g.sort_values("calendar_days")
        cd = g["calendar_days"].to_numpy(dtype=float)
        if len(cd) == 0 or not (cd[0] <= 365 <= cd[-1]):
            continue
        r = float(np.interp(365.0, cd, g["rate"].astype(float).to_numpy()))
        out.append({"obs_date": trade_date, "doc_1y_eff": r * 365.0 / 360.0})
    return pd.DataFrame(out, columns=["obs_date", "doc_1y_eff"])


def ust_effective(par_yield_pct: pd.Series) -> pd.Series:
    """Treasury par yields are semi-annual bond-equivalent: (1 + y/2)^2 - 1."""
    return ((1.0 + par_yield_pct / 200.0) ** 2 - 1.0) * 100.0


# ---------------------------------------------------------------------------
# Native-calendar features
# ---------------------------------------------------------------------------


def native_features(frame: pd.DataFrame, col: str, kind: str) -> pd.DataFrame:
    """Momentum and realised vol of ``col`` on its own observation calendar.

    kind 'rate': changes in the level (pp); realised vol = std of daily
    changes × √252 (pp per year). kind 'price': log changes; vol = std of
    log returns × √252. Full windows only.
    """
    f = frame.sort_values("obs_date").reset_index(drop=True)
    x = f[col].astype(float)
    step = x.diff() if kind == "rate" else np.log(x).diff()
    for k in MOMENTUM_WINDOWS:
        f[f"{col}_mom_{k}d"] = (x - x.shift(k)) if kind == "rate" else np.log(x / x.shift(k))
    for w in VOL_WINDOWS:
        f[f"{col}_rv_{w}d"] = step.rolling(w, min_periods=w).std() * math.sqrt(252.0)
    return f


def pair_correlation(a: pd.DataFrame, a_col: str, a_kind: str,
                     b: pd.DataFrame, b_col: str, b_kind: str, name: str) -> pd.DataFrame:
    """Rolling correlation of daily changes on the dates BOTH observed.
    The value on a common date becomes available when the later source does."""
    m = a[["obs_date", a_col, "available_date"]].merge(
        b[["obs_date", b_col, "available_date"]], on="obs_date", suffixes=("_a", "_b"))
    m = m.sort_values("obs_date").reset_index(drop=True)

    def step(s: pd.Series, kind: str) -> pd.Series:
        s = s.astype(float)
        return s.diff() if kind == "rate" else np.log(s).diff()

    da, db = step(m[a_col], a_kind), step(m[b_col], b_kind)
    out = pd.DataFrame({"obs_date": m["obs_date"],
                        "available_date": np.maximum(m["available_date_a"], m["available_date_b"])})
    for w in CORR_WINDOWS:
        out[f"{name}_{w}d"] = da.rolling(w, min_periods=w).corr(db)
    return out


# ---------------------------------------------------------------------------
# Point-in-time join
# ---------------------------------------------------------------------------


def with_availability(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    f = frame.copy()
    f["available_date"] = [RULES[rule].available(d) for d in f["obs_date"]]
    return f


def asof_join(sessions: Sequence[date], frame: pd.DataFrame, columns: Iterable[str],
              rule: str, prefix_obs: Optional[str] = None) -> Tuple[pd.DataFrame, int]:
    """Values public by each session, within the source's staleness limit.

    Returns (frame indexed like ``sessions``, number of session-cells nulled
    for staleness). ``available_date`` must be on ``frame``.
    """
    columns = list(columns)
    grid = pd.DataFrame({"date": pd.to_datetime(list(sessions))})
    right = frame[["obs_date", "available_date", *columns]].copy()
    right["available_date"] = pd.to_datetime(right["available_date"])
    right["obs_date"] = pd.to_datetime(right["obs_date"])
    # Several observations can become public together (EIA's weekly batch):
    # the newest observation wins.
    right = (right.sort_values(["available_date", "obs_date"])
                  .drop_duplicates("available_date", keep="last"))
    j = pd.merge_asof(grid, right, left_on="date", right_on="available_date", direction="backward")
    # Staleness in B3 sessions since the value became public.
    sess = grid["date"].to_numpy()
    avail_idx = np.searchsorted(sess, j["available_date"].to_numpy(), side="left")
    age = np.arange(len(sess)) - avail_idx
    stale = j["available_date"].notna() & (age > RULES[rule].max_stale_sessions)
    nulled = int(stale.sum())
    j.loc[stale, columns] = np.nan
    j.loc[stale, "obs_date"] = pd.NaT
    out = j[columns].copy()
    if prefix_obs:
        out[f"{prefix_obs}__obs_date"] = j["obs_date"].dt.date
    out.index = grid["date"].dt.date
    return out, nulled


# ---------------------------------------------------------------------------
# The builder
# ---------------------------------------------------------------------------

SCALAR_SERIES = {
    # name: (rule, kind for momentum/vol or None for level-only)
    "usdbrl": ("usdbrl", "price"),
    "ust_2y": ("ust", "rate"),
    "ust_5y": ("ust", "rate"),
    "ust_10y": ("ust", "rate"),
    "ust_30y": ("ust", "rate"),
    "ust_1y": ("ust", None),
    "vix": ("vix", "price"),
    "brent": ("brent", "price"),
    "selic": ("selic", None),
    "ipca": ("monthly", None),
    "ipca_12m": ("monthly", None),
    "commodity_index": ("monthly", None),
    "focus_ipca_12m": ("focus", None),
}


def build(sessions: Sequence[date], curves: pd.DataFrame, series: Dict[str, pd.DataFrame],
          futures: Optional[pd.DataFrame] = None) -> Tuple[pd.DataFrame, Dict[str, int]]:
    """The feature matrix, and a count of staleness-nulled cells per block.

    ``curves``: [trade_date, curve, calendar_days, business_days, rate].
    ``series``: name → [obs_date, value] for every SCALAR_SERIES name present.
    ``futures`` (optional, 2018+): [trade_date, open_interest, contracts].
    """
    sessions = sorted(sessions)
    blocks: List[pd.DataFrame] = []
    nulled: Dict[str, int] = {}

    def add(name: str, frame: pd.DataFrame, cols: Iterable[str], rule: str, obs: Optional[str] = None):
        j, n = asof_join(sessions, frame, cols, rule, obs)
        blocks.append(j)
        nulled[name] = n

    # DI curve: levels, shape, momentum, realised vol.
    di = di_constant_maturity(curves)
    di["di_2s5s"] = di["di_5y"] - di["di_2y"]
    di["di_curvature"] = 2 * di["di_2y"] - di["di_1y"] - di["di_5y"]
    for col in ("di_1y", "di_2y", "di_5y", "di_2s5s", "di_curvature"):
        di = native_features(di, col, "rate")
    di = with_availability(di, "di")
    add("di", di, [c for c in di.columns if c.startswith("di_")], "di", "di")

    # Scalar series on their own calendars.
    native: Dict[str, pd.DataFrame] = {}
    for name, (rule, kind) in SCALAR_SERIES.items():
        if name not in series or series[name].empty:
            continue
        f = series[name].rename(columns={"value": name})[["obs_date", name]].dropna()
        if kind:
            f = native_features(f, name, kind)
        f = with_availability(f, rule)
        native[name] = f
        add(name, f, [c for c in f.columns if c.startswith(name)], rule, name)
    if "ust_10y" in native and "ust_2y" in native:
        u = native["ust_10y"][["obs_date", "ust_10y", "available_date"]].merge(
            native["ust_2y"][["obs_date", "ust_2y"]], on="obs_date")
        u["ust_2s10s"] = u["ust_10y"] - u["ust_2y"]
        add("ust_2s10s", u, ["ust_2s10s"], "ust")

    # Sovereign-risk PROXY: onshore dollar premium, DOC 1Y minus UST 1Y, bp.
    # Not CDS. See the research doc §3.D for what it mixes in.
    if "ust_1y" in native:
        doc = doc_one_year_effective(curves).merge(
            native["ust_1y"][["obs_date", "ust_1y"]], on="obs_date")
        doc["brazil_sovereign_risk_proxy"] = (doc["doc_1y_eff"] - ust_effective(doc["ust_1y"].astype(float))) * 100.0
        doc = native_features(doc, "brazil_sovereign_risk_proxy", "rate")
        # Observed only on dates both markets were open, so it inherits the UST
        # staleness limit: a US holiday must not blank the feature.
        doc = with_availability(doc, "ust")
        add("sovereign", doc, [c for c in doc.columns if c.startswith("brazil_")], "ust", "brazil_sovereign_risk_proxy")

    # Rates-volatility proxy for MOVE: realised UST 10Y vol, in bp. Not MOVE.
    if "ust_10y" in native:
        r = native["ust_10y"][["obs_date", "available_date"]].copy()
        r["rates_vol_proxy"] = native["ust_10y"]["ust_10y_rv_21d"] * 100.0
        add("rates_vol_proxy", r, ["rates_vol_proxy"], "ust")

    # Cross-asset correlations of daily changes.
    di_native = di[["obs_date", "di_2y", "available_date"]]
    # A pair is observed only on dates both sides were; it takes the staleness
    # limit of its less frequent side (US holidays for UST and VIX).
    pairs = [
        ("corr_di2y_usdbrl", di_native, "di_2y", "rate", "usdbrl", "price", "usdbrl"),
        ("corr_di2y_ust10y", di_native, "di_2y", "rate", "ust_10y", "rate", "ust"),
        ("corr_di2y_vix", di_native, "di_2y", "rate", "vix", "price", "vix"),
    ]
    for name, a, a_col, a_kind, b_name, b_kind, rule in pairs:
        if b_name in native:
            c = pair_correlation(a, a_col, a_kind, native[b_name], b_name, b_kind, name)
            add(name, c, [col for col in c.columns if col.startswith(name)], rule)
    if "usdbrl" in native and "brent" in native:
        c = pair_correlation(native["usdbrl"], "usdbrl", "price", native["brent"], "brent", "price",
                             "corr_usdbrl_brent")
        add("corr_usdbrl_brent", c, [col for col in c.columns if col.startswith("corr_")], "brent")

    # DI1 liquidity, contract level summed per session (LATE-STARTING: 2018).
    if futures is not None and not futures.empty:
        liq = (futures.groupby("trade_date", as_index=False)
                      .agg(di1_open_interest=("open_interest", "sum"), di1_contracts=("contracts", "sum"))
                      .rename(columns={"trade_date": "obs_date"}))
        liq = with_availability(liq, "di")
        add("di1_liquidity", liq, ["di1_open_interest", "di1_contracts"], "di")

    out = pd.concat(blocks, axis=1)
    out.index.name = "date"
    return out.reset_index(), nulled


# ---------------------------------------------------------------------------
# Loading from the warehouse (operator connection, read only)
# ---------------------------------------------------------------------------

_SGS = {"usdbrl": 1, "selic": 432, "ipca": 433, "ipca_12m": 13522, "commodity_index": 27574}
_UST = {"ust_1y": "UST_PAR_1Y", "ust_2y": "UST_PAR_2Y", "ust_5y": "UST_PAR_5Y",
        "ust_10y": "UST_PAR_10Y", "ust_30y": "UST_PAR_30Y"}


def _query(client, sql: str, params: tuple, columns: List[str]) -> pd.DataFrame:
    with client.cursor() as cur:
        cur.execute(sql, params)
        return pd.DataFrame(cur.fetchall(), columns=columns)


def load(client, start: date, end: date) -> Tuple[List[date], pd.DataFrame, Dict[str, pd.DataFrame], pd.DataFrame]:
    """Everything ``build`` needs, with a warm-up margin before ``start`` so
    63-session windows and monthly series are populated on day one."""
    lo = start - timedelta(days=200)
    curves = _query(client,
                    "SELECT trade_date, curve, calendar_days, business_days, rate FROM b3_reference_rate "
                    "WHERE curve IN ('PRE', 'DOC') AND trade_date BETWEEN %s AND %s",
                    (lo, end), ["trade_date", "curve", "calendar_days", "business_days", "rate"])
    series: Dict[str, pd.DataFrame] = {}
    for name, code in _SGS.items():
        series[name] = _query(client, "SELECT reference_date, value FROM bacen_sgs "
                              "WHERE series_code = %s AND reference_date BETWEEN %s AND %s",
                              (code, lo, end), ["obs_date", "value"])
    for name, sid in {**_UST, "vix": "VIX_CLOSE", "brent": "BRENT_SPOT_FOB"}.items():
        series[name] = _query(client, "SELECT observation_date, value FROM mkt_series "
                              "WHERE series_id = %s AND observation_date BETWEEN %s AND %s",
                              (sid, lo, end), ["obs_date", "value"])
    series["focus_ipca_12m"] = _query(
        client, "SELECT reference_date, median FROM bacen_expectativas "
        "WHERE endpoint_name = 'ExpectativasMercadoInflacao12Meses' AND indicador = 'IPCA' "
        "AND horizon IS NULL AND reference_date BETWEEN %s AND %s", (lo, end), ["obs_date", "value"])
    futures = _query(client, "SELECT trade_date, open_interest, contracts FROM b3_futures_settlement "
                     "WHERE ticker LIKE 'DI1%%' AND trade_date BETWEEN %s AND %s",
                     (lo, end), ["trade_date", "open_interest", "contracts"])
    # The B3 session grid is the target's own calendar: the days PRE was published.
    sessions = sorted(set(curves.loc[curves["curve"] == "PRE", "trade_date"]))
    for f in series.values():
        f["value"] = pd.to_numeric(f["value"])
    return sessions, curves, series, futures


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--out", required=True, help="CSV path")
    args = p.parse_args(argv)
    from src.store.pg_client import get_pg_client

    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    sessions, curves, series, futures = load(get_pg_client(), start, end)
    if not sessions:
        print("no PRE sessions in the window — has the b3_reference_rate backfill run?", file=sys.stderr)
        return 1
    frame, nulled = build(sessions, curves, series, futures)
    frame = frame[(frame["date"] >= start) & (frame["date"] <= end)]
    frame.to_csv(args.out, index=False)
    print(f"{len(frame)} sessions {frame['date'].min()}..{frame['date'].max()}, {frame.shape[1]} columns → {args.out}")
    print("staleness-nulled cells per block:", {k: v for k, v in nulled.items() if v})
    empty = [c for c in frame.columns if frame[c].isna().all()]
    if empty:
        print("columns with no value in the window:", ", ".join(empty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
