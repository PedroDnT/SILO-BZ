"""The DUSTIN-BR Stage 4 model (research_examples/dustin_br/model.py).

What these pin: every target's label looks forward exactly 21 sessions and
the Markov baseline's class only backward; no model learns from a label that reaches
into the session it predicts; the Newton fit is the penalised maximum
likelihood (checked here by its optimality condition, and once, offline,
against scikit-learn: probabilities agreed to 1e-7); and the walk forward
finds a signal that is there and none where there is none.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research_examples.dustin_br import model as m

DERIVED = {"policy_gap", "real_policy_rate"}
REGIME, LEVEL, SLOPE = (m.TARGETS[name] for name in ("regime", "level", "slope"))


def _frame(years: int = 6, seed: int = 0) -> pd.DataFrame:
    """Random-walk curve plus noise inputs, B3-like sessions from 2008."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2008-01-01", periods=250 * years)
    n = len(dates)
    di_2y = 10 + np.cumsum(rng.normal(0, 0.05, n))
    f = pd.DataFrame({"date": dates, "di_2y": di_2y, "di_2s5s": np.cumsum(rng.normal(0, 0.02, n)),
                      "di_1y": di_2y - 0.2, "selic": 10.0, "ipca_12m": 4.0})
    for col in m.FEATURES:
        if col not in f and col not in DERIVED:
            f[col] = rng.normal(size=n)
    return f


def _clean(seed: int, planted: float = 0.0, years: int = 6) -> pd.DataFrame:
    """Labels from random walks, every INPUT stationary noise (the di_2s5s and
    policy inputs included). A random-walk input is the known hazard: its
    in-sample fit to persistent, overlapping labels is spurious (on
    ``_frame``, seed 2, the level model loses 0.19 to climatology), which is
    why the real inputs are spreads, changes and volatilities."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2008-01-01", periods=250 * years)
    n = len(dates)
    di_2y = 10 + np.cumsum(rng.normal(0, 0.05, n))
    f = pd.DataFrame({"date": dates, "di_2y": di_2y, "di_2s5s": rng.normal(size=n),
                      "di_1y": 10.0 + rng.normal(0, 0.1, n), "selic": 10.0,
                      "ipca_12m": 4.0 + rng.normal(0, 0.1, n)})
    for col in m.FEATURES:
        if col not in f and col not in DERIVED:
            f[col] = rng.normal(size=n)
    if planted:
        up = np.sign(pd.Series(di_2y).shift(-m.HORIZON) - pd.Series(di_2y)).fillna(0).to_numpy()
        f["ofr_fsi"] = planted * up + rng.normal(size=n)
    return f


def test_the_label_is_the_next_21_sessions_regime():
    n = 60
    f = pd.DataFrame({"di_2y": np.linspace(10, 11, n), "di_2s5s": np.linspace(1, 0, n)})
    y = REGIME.label(f)
    assert (y.iloc[: n - m.HORIZON] == REGIME.classes.index("bear_flattener")).all()
    assert y.iloc[n - m.HORIZON:].isna().all()                  # the future is not known yet
    assert (LEVEL.label(f).dropna() == LEVEL.classes.index("bear")).all()
    assert (SLOPE.label(f).dropna() == SLOPE.classes.index("flattener")).all()
    f["di_2y"] = np.linspace(11, 10, n)
    f["di_2s5s"] = np.linspace(0, 1, n)
    assert (REGIME.label(f).dropna() == REGIME.classes.index("bull_steepener")).all()
    assert (LEVEL.label(f).dropna() == LEVEL.classes.index("bull")).all()
    assert (SLOPE.label(f).dropna() == SLOPE.classes.index("steepener")).all()
    f["di_2y"] = 10.0                                           # no move, no label
    assert REGIME.label(f).isna().all() and LEVEL.label(f).isna().all()
    assert SLOPE.label(f).notna().sum() == n - m.HORIZON        # the slope still moved


def test_the_markov_baseline_only_looks_back():
    f = _frame(years=1)
    for target in m.TARGETS.values():
        pd.testing.assert_series_equal(target.past(f), target.label(f).shift(m.HORIZON), check_names=False)


def test_no_model_learns_from_a_label_that_reaches_the_predicted_session():
    pos = np.arange(200)
    y = np.zeros(200)
    rows = m.train_rows(np.ones(200, bool), y, pos, before=100)
    assert rows[: 100 - m.HORIZON].all() and not rows[100 - m.HORIZON:].any()   # row 78 + 21 < 100


def test_the_fit_is_the_penalised_maximum_likelihood():
    rng = np.random.default_rng(1)
    x = rng.normal(size=(400, 5)) * [1, 10, 0.1, 3, 1]
    y = rng.integers(0, 4, 400)
    fit = m.Logit(C=0.5).fit(x, y)
    xs = np.hstack([np.ones((400, 1)), (x - fit.mean_) / fit.sd_])
    grad = xs.T @ (fit.predict_proba(x) - np.eye(4)[y])
    grad[1:] += fit.coef_[1:] / 0.5                             # intercepts are not penalised
    assert np.abs(grad).max() < 1e-5
    tiny = m.Logit(C=1e-8).fit(x, y).predict_proba(x)          # all shrinkage: the class shares
    assert np.allclose(tiny, np.bincount(y, minlength=4) / 400, atol=1e-4)


def _gain(preds, target):
    return m.summary(preds, target.classes)["gains"][("log_loss", m.HEADLINE, "climatology")]


def test_noise_inputs_earn_no_skill():
    for seed in (2, 3, 4):
        mean, lo, hi = _gain(m.walk_forward(_clean(seed), LEVEL), LEVEL)
        assert abs(mean) < 0.01, seed


def test_a_planted_signal_is_found():
    for seed in (2, 3):
        for target in (REGIME, LEVEL):                          # the leak is the level's direction
            mean, lo, hi = _gain(m.walk_forward(_clean(seed, planted=2.0), target), target)
            assert lo > 0.3, (seed, target.name)


def test_the_block_bootstrap_brackets_the_mean():
    assert m.block_bootstrap(np.full(100, 0.25)) == pytest.approx((0.25, 0.25))
    diff = np.random.default_rng(4).normal(0.1, 1.0, 2000)
    lo, hi = m.block_bootstrap(diff)
    assert lo < diff.mean() < hi


def test_the_report_states_the_verdict_and_the_latest_forecast():
    f = _frame(seed=5)
    report = m.render(f, {name: (m.walk_forward(f, t), m.latest_forecast(f, t)) for name, t in m.TARGETS.items()})
    assert "## Headline: model, C chosen in training" in report and "moving-block bootstrap" in report
    for name, target in m.TARGETS.items():
        assert f"| {name} | " in report and f"## {target.title}" in report
    assert report.count("Latest forecast, 2013-") == 3
