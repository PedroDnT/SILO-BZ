"""The DUSTIN-BR regime model (research_examples/dustin_br/model.py).

What these pin: the label looks forward exactly 21 sessions and the Markov
baseline's regime only backward; no model learns from a label that reaches
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


def _frame(years: int = 6, seed: int = 0, planted: float = 0.0) -> pd.DataFrame:
    """Random-walk curve plus noise features, B3-like sessions from 2008.
    ``planted`` > 0 leaks the sign of the next 21 sessions' level change into
    one feature: a positive control, deliberately forward-looking."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2008-01-01", periods=250 * years)
    n = len(dates)
    di_2y = 10 + np.cumsum(rng.normal(0, 0.05, n))
    f = pd.DataFrame({"date": dates, "di_2y": di_2y, "di_2s5s": np.cumsum(rng.normal(0, 0.02, n)),
                      "di_1y": di_2y - 0.2, "selic": 10.0, "ipca_12m": 4.0})
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
    y = m.regimes(f)
    assert (y.iloc[: n - m.HORIZON] == m.REGIMES.index("bear_flattener")).all()
    assert y.iloc[n - m.HORIZON:].isna().all()                  # the future is not known yet
    f["di_2y"] = np.linspace(11, 10, n)
    f["di_2s5s"] = np.linspace(0, 1, n)
    assert (m.regimes(f).dropna() == m.REGIMES.index("bull_steepener")).all()
    f["di_2y"] = 10.0                                           # no move, no label
    assert m.regimes(f).isna().all()


def test_the_markov_baseline_only_looks_back():
    f = _frame(years=1)
    past, label = m.past_regime(f), m.regimes(f)
    pd.testing.assert_series_equal(past, label.shift(m.HORIZON), check_names=False)


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


def test_noise_features_earn_no_skill():
    preds = m.walk_forward(_frame(seed=2))
    mean, lo, hi = m.summary(preds)["gains"][("log_loss", "model, C chosen in training", "climatology")]
    assert lo < 0 < hi and abs(mean) < 0.05


def test_a_planted_signal_is_found():
    preds = m.walk_forward(_frame(seed=3, planted=2.0))
    mean, lo, hi = m.summary(preds)["gains"][("log_loss", "model, C chosen in training", "climatology")]
    assert lo > 0.1


def test_the_block_bootstrap_brackets_the_mean():
    assert m.block_bootstrap(np.full(100, 0.25)) == pytest.approx((0.25, 0.25))
    diff = np.random.default_rng(4).normal(0.1, 1.0, 2000)
    lo, hi = m.block_bootstrap(diff)
    assert lo < diff.mean() < hi


def test_the_report_states_the_verdict_and_the_latest_forecast():
    f = _frame(seed=5)
    report = m.render(f, m.walk_forward(f), m.latest_forecast(f))
    assert "## Scores" in report and "moving-block bootstrap" in report
    assert "## Latest forecast: 2013-" in report
    assert report.count("| bull_steepener |") == 1
