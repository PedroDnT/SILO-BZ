#!/usr/bin/env python3
"""DUSTIN-BR Stage 4: the curve's regime 21 sessions ahead, as probabilities.

TARGET (built here and never stored in the matrix, since it looks forward).
Over the next 21 B3 sessions the 2y DI rate falls (bull) or rises (bear), and
the 2s5s slope widens (steepener) or narrows (flattener):

    bull_steepener   bull_flattener   bear_steepener   bear_flattener

A row whose 21st session ahead is not in the matrix yet, or whose level or
slope did not move at all, has no label.

MODEL. L2-regularised multinomial logistic regression on the CORE features,
standardised on each training window alone, fitted by Newton's method, in two
variants reported side by side:

* C = 0.1, set before any test year was scored. It overfits: 4,600 daily
  labels that overlap 20 of 21 sessions carry about 220 independent outcomes,
  and the likelihood counts all 4,600 (measured: in-sample log loss 1.24,
  out of sample 1.86, worse than both baselines);
* C chosen in each training window, added after that result: the grid value
  with the lowest log loss on the window's last two years, fitted on the rest
  (purged the same way). No test year is looked at.

EVALUATION, walk-forward. For each test year from 2012: fit on every labelled
row whose label closes before the year starts (the 21 sessions before it are
purged, since their labels reach into it), then predict every session of the
year. Two baselines get the same rows:

* climatology: each regime's share in the training window;
* Markov: each regime's share after the regime of the 21 sessions that just
  ended (known at t), in the training window.

Scores: log loss and Brier score (how good the probabilities are) and hit
rate, by era, and each model's gain over each baseline in log loss and hit
rate, with a 90% interval from a moving-block bootstrap. The blocks are 21
sessions long because consecutive labels share 20 of their 21 sessions: 4,600
rows hold only about 220 independent outcomes.

Run (reads the matrix that build_dataset / quality write):

    python -m research_examples.dustin_br.model --matrix out/dustin_br.csv --out-dir out
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

HORIZON = 21
FIRST_TEST_YEAR = 2012
C = 0.1  # inverse L2 strength, fixed before looking at any test year
C_GRID = (1e-4, 3e-4, 1e-3, 3e-3, 1e-2, 3e-2, 1e-1)
VALIDATION_YEARS = 2
REGIMES = ("bull_steepener", "bull_flattener", "bear_steepener", "bear_flattener")
ERAS = ((2012, 2016), (2017, 2020), (2021, 2026))

# CORE inputs only (research doc §7), as spreads, changes, volatilities and
# correlations: raw rate levels are left out because SELIC ran from 2% to 15%
# over 2008-2026, and a level the training window never saw is extrapolation.
FEATURES = (
    "di_2s5s", "di_curvature", "policy_gap", "real_policy_rate",
    "di_2y_mom_5d", "di_2y_mom_21d", "di_2y_mom_63d", "di_2s5s_mom_21d", "di_2s5s_mom_63d",
    "di_2y_rv_21d", "di_2y_rv_63d",
    "usdbrl_mom_21d", "usdbrl_mom_63d", "usdbrl_rv_21d",
    "ust_2s10s", "ust_2y_mom_21d", "ust_10y_mom_21d",
    "ofr_fsi", "ofr_fsi_mom_21d",
    "brent_mom_21d", "brent_mom_63d",
    "rates_vol_proxy",
    "corr_di2y_usdbrl_63d", "corr_di2y_ust10y_63d",
)


# ---------------------------------------------------------------------------
# Target and features
# ---------------------------------------------------------------------------


def _regime(level_change: pd.Series, slope_change: pd.Series) -> pd.Series:
    """Regime code (index into REGIMES), NaN where either change is 0 or missing."""
    bear = level_change > 0
    flattener = slope_change < 0
    code = pd.Series(2 * bear.astype(float) + flattener.astype(float), index=level_change.index)
    moved = (level_change != 0) & (slope_change != 0) & level_change.notna() & slope_change.notna()
    return code.where(moved)


def regimes(frame: pd.DataFrame, horizon: int = HORIZON) -> pd.Series:
    """The label of row t: the regime from session t to session t + horizon."""
    return _regime(frame["di_2y"].shift(-horizon) - frame["di_2y"],
                   frame["di_2s5s"].shift(-horizon) - frame["di_2s5s"])


def past_regime(frame: pd.DataFrame, horizon: int = HORIZON) -> pd.Series:
    """The regime of the 21 sessions that END at t: known at t (Markov baseline)."""
    return _regime(frame["di_2y"] - frame["di_2y"].shift(horizon),
                   frame["di_2s5s"] - frame["di_2s5s"].shift(horizon))


def design(frame: pd.DataFrame) -> pd.DataFrame:
    """FEATURES; the two policy spreads are derived from matrix columns."""
    f = frame.assign(policy_gap=frame["di_1y"] - frame["selic"],            # a year of policy, priced
                     real_policy_rate=frame["selic"] - frame["ipca_12m"])   # ex post
    return f[list(FEATURES)].astype(float)


# ---------------------------------------------------------------------------
# Multinomial logistic regression (Newton's method, numpy only)
# ---------------------------------------------------------------------------


def _softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


@dataclass
class Logit:
    """Minimises  sum_i -log p(y_i | x_i) + ||W||^2 / (2C)  over the feature
    weights W (intercepts unpenalised), the objective scikit-learn's
    multinomial LogisticRegression uses. Features are standardised with the
    training rows' own mean and deviation."""

    C: float = C
    classes: int = len(REGIMES)
    max_iter: int = 100
    tol: float = 1e-9

    def fit(self, x: np.ndarray, y: np.ndarray) -> "Logit":
        self.mean_ = x.mean(axis=0)
        sd = x.std(axis=0)
        self.sd_ = np.where(sd > 0, sd, 1.0)
        n, k = len(x), self.classes
        xs = np.hstack([np.ones((n, 1)), (x - self.mean_) / self.sd_])
        d = xs.shape[1]
        onehot = np.eye(k)[y.astype(int)]
        penalty = np.full(d, 1.0 / self.C)
        # Intercepts are unpenalised; a negligible ridge only makes the Hessian
        # invertible (softmax intercepts are defined up to a common constant).
        penalty[0] = 1e-9
        w = np.zeros((d, k))

        def objective(w: np.ndarray) -> float:
            z = xs @ w
            z = z - z.max(axis=1, keepdims=True)
            loglik = (z * onehot).sum() - np.log(np.exp(z).sum(axis=1)).sum()
            return -loglik + 0.5 * (penalty[:, None] * w * w).sum()

        f = objective(w)
        for _ in range(self.max_iter):
            p = _softmax(xs @ w)
            grad = xs.T @ (p - onehot) + penalty[:, None] * w
            if np.abs(grad).max() < self.tol * n:
                break
            s = p[:, :, None] * (np.eye(k)[None] - p[:, None, :])        # n x k x k
            hess = np.einsum("na,nkl,nb->akbl", xs, s, xs).reshape(d * k, d * k)
            hess[np.diag_indices(d * k)] += np.repeat(penalty, k)
            step = np.linalg.solve(hess, grad.reshape(-1)).reshape(d, k)
            t = 1.0
            while t > 1e-10:                                                # backtracking
                trial = objective(w - t * step)
                if trial <= f:
                    break
                t /= 2
            w, f = w - t * step, trial
        self.coef_ = w
        return self

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        xs = np.hstack([np.ones((len(x), 1)), (x - self.mean_) / self.sd_])
        return _softmax(xs @ self.coef_)


# ---------------------------------------------------------------------------
# Walk-forward evaluation
# ---------------------------------------------------------------------------


def _shares(codes: np.ndarray, k: int = len(REGIMES)) -> np.ndarray:
    """Regime shares, with one pseudo-count each so no regime gets probability 0."""
    return (np.bincount(codes.astype(int), minlength=k) + 1.0) / (len(codes) + k)


def train_rows(usable: np.ndarray, y: np.ndarray, pos: np.ndarray, before: int,
               horizon: int = HORIZON) -> np.ndarray:
    """Rows a model may learn from when it predicts session ``before``: usable,
    labelled, and with a label that closes first (row i's label covers
    sessions i+1 .. i+horizon)."""
    return usable & ~np.isnan(y) & (pos + horizon < before)


def choose_c(x: np.ndarray, y: np.ndarray, years: np.ndarray, pos: np.ndarray,
             horizon: int = HORIZON, grid: Sequence[float] = C_GRID) -> float:
    """The grid C with the lowest log loss on the last VALIDATION_YEARS of a
    training window, fitted on its rows whose labels close before the
    validation starts. ``pos`` is each row's session position."""
    val = years > years.max() - VALIDATION_YEARS
    fit = pos + horizon < pos[val][0]
    yv = y[val].astype(int)
    losses = []
    for c in grid:
        p = Logit(C=c).fit(x[fit], y[fit]).predict_proba(x[val])
        losses.append(-np.log(np.clip(p[np.arange(len(yv)), yv], 1e-15, 1.0)).mean())
    return float(grid[int(np.argmin(losses))])


def walk_forward(frame: pd.DataFrame, first_test_year: int = FIRST_TEST_YEAR,
                 horizon: int = HORIZON, c: float = C) -> pd.DataFrame:
    """Out-of-sample probabilities for every session from ``first_test_year``.

    One row per test session: date, test_year, label (NaN when not known
    yet), c_chosen, and p_<regime> for the model at ``c`` (p_), the model at
    the C chosen in the training window (n_), climatology (clim_) and Markov
    (markov_).
    """
    frame = frame.sort_values("date").reset_index(drop=True)
    x = design(frame).to_numpy()
    y = regimes(frame, horizon).to_numpy()
    past = past_regime(frame, horizon).to_numpy()
    years = pd.to_datetime(frame["date"]).dt.year.to_numpy()
    usable = ~np.isnan(x).any(axis=1)
    pos = np.arange(len(frame))
    out = []
    for year in range(first_test_year, int(years.max()) + 1):
        test = (years == year) & usable
        if not test.any():
            continue
        first = int(pos[test][0])
        train = train_rows(usable, y, pos, first, horizon)
        if train.sum() < 200:
            continue
        model = Logit(C=c).fit(x[train], y[train])
        c_chosen = choose_c(x[train], y[train], years[train], pos[train], horizon)
        nested = Logit(C=c_chosen).fit(x[train], y[train])
        clim = _shares(y[train])
        markov = {r: _shares(y[train & (past == r)]) for r in range(len(REGIMES))}
        p_model = model.predict_proba(x[test])
        p_nested = nested.predict_proba(x[test])
        p_markov = np.array([markov[int(r)] if not np.isnan(r) else clim for r in past[test]])
        block = pd.DataFrame({"date": frame.loc[test, "date"].to_numpy(), "test_year": year,
                              "label": y[test], "c_chosen": c_chosen})
        for j, name in enumerate(REGIMES):
            block[f"p_{name}"] = p_model[:, j]
            block[f"n_{name}"] = p_nested[:, j]
            block[f"clim_{name}"] = clim[j]
            block[f"markov_{name}"] = p_markov[:, j]
        out.append(block)
    return pd.concat(out, ignore_index=True)


def latest_forecast(frame: pd.DataFrame, horizon: int = HORIZON) -> Tuple[str, float, np.ndarray]:
    """(date, C, probabilities) for the last session: C chosen as in the walk
    forward, the model fitted on every label known on that date."""
    frame = frame.sort_values("date").reset_index(drop=True)
    x = design(frame).to_numpy()
    y = regimes(frame, horizon).to_numpy()
    years = pd.to_datetime(frame["date"]).dt.year.to_numpy()
    usable = ~np.isnan(x).any(axis=1)
    pos = np.arange(len(frame))
    last = int(np.flatnonzero(usable)[-1])
    train = train_rows(usable, y, pos, last + 1, horizon)
    c = choose_c(x[train], y[train], years[train], pos[train], horizon)
    p = Logit(C=c).fit(x[train], y[train]).predict_proba(x[[last]])[0]
    return pd.Timestamp(frame.loc[last, "date"]).date().isoformat(), c, p


# ---------------------------------------------------------------------------
# Scores
# ---------------------------------------------------------------------------


def _probs(preds: pd.DataFrame, prefix: str) -> np.ndarray:
    return preds[[f"{prefix}{name}" for name in REGIMES]].to_numpy()


def row_scores(preds: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """Per labelled row: log loss, Brier score and hit (1 if the top regime happened)."""
    known = preds.dropna(subset=["label"])
    p = _probs(known, prefix)
    y = known["label"].to_numpy().astype(int)
    onehot = np.eye(len(REGIMES))[y]
    return pd.DataFrame({"date": known["date"].to_numpy(), "test_year": known["test_year"].to_numpy(),
                         "log_loss": -np.log(np.clip(p[np.arange(len(y)), y], 1e-15, 1.0)),
                         "brier": ((p - onehot) ** 2).sum(axis=1),
                         "hit": (p.argmax(axis=1) == y).astype(float)})


def block_bootstrap(diff: np.ndarray, block: int = HORIZON, draws: int = 2000,
                    seed: int = 0) -> Tuple[float, float]:
    """90% interval of mean(diff), resampling contiguous blocks of rows."""
    rng = np.random.default_rng(seed)
    n = len(diff)
    starts = np.arange(n - block + 1)
    per = int(np.ceil(n / block))
    means = np.empty(draws)
    for b in range(draws):
        idx = (rng.choice(starts, per)[:, None] + np.arange(block)).ravel()[:n]
        means[b] = diff[idx].mean()
    return float(np.quantile(means, 0.05)), float(np.quantile(means, 0.95))


MODELS = {f"model, C = {C}": "p_", "model, C chosen in training": "n_"}
BASELINES = {"climatology": "clim_", "Markov": "markov_"}
PREFIXES = {**MODELS, **BASELINES}


def summary(preds: pd.DataFrame) -> Dict[str, object]:
    """Scores by era and overall, and each model's gain over each baseline in
    log loss (baseline minus model) and hit rate (model minus baseline):
    above 0 means the model is better."""
    scores = {name: row_scores(preds, prefix) for name, prefix in PREFIXES.items()}
    years = scores["climatology"]["test_year"]
    eras = [(f"{lo}-{hi}", (years >= lo) & (years <= hi)) for lo, hi in ERAS] + \
           [("all", pd.Series(True, index=years.index))]
    table = []
    for label, mask in eras:
        row = {"era": label, "rows": int(mask.sum())}
        for name, s in scores.items():
            for metric in ("log_loss", "brier", "hit"):
                row[f"{metric}:{name}"] = float(s.loc[mask, metric].mean())
        table.append(row)
    gains = {}
    for metric, sign in (("log_loss", -1.0), ("hit", 1.0)):
        for model in MODELS:
            for base in BASELINES:
                diff = sign * (scores[model][metric] - scores[base][metric]).to_numpy()
                gains[(metric, model, base)] = (float(diff.mean()), *block_bootstrap(diff))
    return {"table": pd.DataFrame(table), "gains": gains}


def calibration(preds: pd.DataFrame, prefix: str,
                edges: Sequence[float] = (0.0, 0.2, 0.3, 0.4, 0.5, 1.0)) -> pd.DataFrame:
    """Pooled over regimes: mean predicted probability against how often it happened."""
    known = preds.dropna(subset=["label"])
    p = _probs(known, prefix).ravel()
    hit = np.eye(len(REGIMES))[known["label"].to_numpy().astype(int)].ravel()
    bins = pd.cut(p, list(edges), include_lowest=True)
    t = pd.DataFrame({"bin": bins, "p": p, "hit": hit}).groupby("bin", observed=True)
    return pd.DataFrame({"pairs": t.size(), "predicted": t["p"].mean(), "happened": t["hit"].mean()})


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def render(frame: pd.DataFrame, preds: pd.DataFrame, latest: Tuple[str, float, np.ndarray]) -> str:
    s = summary(preds)
    labels = regimes(frame).dropna().astype(int)
    balance = ", ".join(f"{REGIMES[k]} {_pct(v)}" for k, v in labels.value_counts(normalize=True).sort_index().items())
    known = preds["label"].notna()
    chosen = preds.groupby("test_year")["c_chosen"].first()
    lines = [
        f"# DUSTIN-BR regime model, walk-forward {preds['test_year'].min()}-{preds['test_year'].max()}",
        "",
        f"- Target: the regime of the next {HORIZON} sessions (2y DI level x 2s5s slope). "
        f"Label balance over {len(labels):,} labelled sessions: {balance}.",
        f"- Model: L2 multinomial logistic on {len(FEATURES)} CORE features, refitted every January on "
        f"labels that close before the year ({HORIZON}-session purge). C = {C} was set before any test "
        f"year was scored; the other variant picks C per window from {list(C_GRID)} on its last "
        f"{VALIDATION_YEARS} years (chosen: " + ", ".join(f"{y} {c:g}" for y, c in chosen.items()) + ").",
        f"- Out of sample: {int(known.sum()):,} labelled sessions, {preds['test_year'].nunique()} fits.",
        "",
        "## Scores",
        "",
        "Lower log loss and Brier are better; a coin among four regimes has log loss 1.386 and Brier 0.75. "
        "Columns: " + " / ".join(PREFIXES) + ".",
        "",
        "| era | rows | log loss | Brier | hit rate |",
        "|---|---|---|---|---|",
    ]
    for _, r in s["table"].iterrows():
        cells = [" / ".join(f"{r[f'{m}:{n}']:.3f}" if m != "hit" else _pct(r[f'{m}:{n}']) for n in PREFIXES)
                 for m in ("log_loss", "brier", "hit")]
        lines.append(f"| {r['era']} | {r['rows']:,} | " + " | ".join(cells) + " |")
    lines += ["", "Gain over each baseline (above 0 means the model is better), with a 90% moving-block "
              f"bootstrap interval ({HORIZON}-session blocks). Log loss: baseline minus model. Hit rate: "
              "model minus baseline, in percentage points.", ""]
    for (metric, model, base), (mean, lo, hi) in s["gains"].items():
        verdict = "better" if lo > 0 else "worse" if hi < 0 else "not distinguishable"
        if metric == "hit":
            mean, lo, hi = 100 * mean, 100 * lo, 100 * hi
        name = "log loss" if metric == "log_loss" else "hit rate"
        lines.append(f"- {name}, {model} vs {base}: {mean:+.3f} [{lo:+.3f}, {hi:+.3f}], **{verdict}**.")
    for model, prefix in MODELS.items():
        cal = calibration(preds, prefix)
        lines += ["", f"## Calibration: {model}", "", "Pooled over regimes: when it says p, how often did it happen?",
                  "", "| predicted | pairs | mean predicted | happened |", "|---|---|---|---|"]
        lines += [f"| {b} | {int(r.pairs):,} | {_pct(r.predicted)} | {_pct(r.happened)} |" for b, r in cal.iterrows()]
    date, c, p = latest
    lines += ["", f"## Latest forecast: {date}, the next {HORIZON} sessions", "",
              f"The model with C chosen in training (C = {c:g}), fitted on every label known on that date. "
              "Research output, not advice; read it against the scores above.", "",
              "| regime | probability |", "|---|---|"]
    lines += [f"| {name} | {_pct(v)} |" for name, v in zip(REGIMES, p)]
    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--matrix", required=True, help="dustin_br.csv from build_dataset or quality")
    p.add_argument("--out-dir", required=True)
    args = p.parse_args(argv)
    frame = pd.read_csv(args.matrix, parse_dates=["date"])
    preds = walk_forward(frame)
    latest = latest_forecast(frame)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    preds.to_csv(out / "model_predictions.csv", index=False)
    report = render(frame, preds, latest)
    (out / "model_report.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
