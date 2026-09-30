"""The DUSTIN-BR research dataset builder: interpolation and point-in-time rules.

research_examples/dustin_br/build_dataset.py builds features, never a model.
What these pin: DI constant-maturity interpolation is exact at vertices and
never extrapolates; every availability rule in docs/reference/research/
dustin_br_data_sources.md §8; the as-of join never shows a value before it
was public and nulls it past its staleness limit; and — the property that
matters for out-of-sample work — rows up to T are IDENTICAL whether or not
anything published after T exists.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research_examples.dustin_br import build_dataset as bd
from research_examples.dustin_br import quality


# ---------------------------------------------------------------------------
# DI interpolation
# ---------------------------------------------------------------------------

DU = [1, 21, 63, 126, 252, 504, 756, 1260, 2520]
RATES = [13.65, 13.66, 13.60, 13.55, 13.60, 13.78, 13.85, 13.98, 13.95]


def test_flat_forward_reproduces_every_vertex():
    for du, r in zip(DU, RATES):
        assert bd.flat_forward(DU, RATES, du) == pytest.approx(r, abs=1e-10)


def test_flat_forward_is_a_constant_forward_between_vertices():
    # Between 252 and 504 business days the forward is constant, so the
    # 378-day discount factor is the geometric mean of the two.
    df252 = (1 + 13.60 / 100) ** (-252 / 252)
    df504 = (1 + 13.78 / 100) ** (-504 / 252)
    expected = (math.sqrt(df252 * df504) ** (-252 / 378) - 1) * 100
    assert bd.flat_forward(DU, RATES, 378) == pytest.approx(expected, abs=1e-10)


def test_no_extrapolation_beyond_the_curve():
    assert math.isnan(bd.flat_forward(DU, RATES, 3000))
    assert math.isnan(bd.flat_forward([252, 504], [13.0, 13.2], 126))


# ---------------------------------------------------------------------------
# Availability rules
# ---------------------------------------------------------------------------

def test_eia_brent_waits_for_the_weekly_wednesday_release():
    tue, wed, mon = date(2026, 9, 22), date(2026, 9, 23), date(2026, 9, 21)
    assert bd.eia_weekly_release(tue) == date(2026, 9, 24)   # released Wed 23, used Thu
    assert bd.eia_weekly_release(mon) == date(2026, 9, 24)
    assert bd.eia_weekly_release(wed) == date(2026, 10, 1)   # waits for next Wednesday


def test_focus_is_public_the_week_after_its_survey_date():
    # Measured: on Sunday 2026-09-27 the newest daily Focus value was 09-18.
    assert bd.tuesday_after_week(date(2026, 9, 18)) == date(2026, 9, 22)
    assert bd.tuesday_after_week(date(2026, 9, 14)) == date(2026, 9, 22)
    assert bd.tuesday_after_week(date(2026, 9, 21)) == date(2026, 9, 29)


def test_monthly_series_are_public_on_the_15th_of_the_next_month():
    assert bd.fifteenth_of_next_month(date(2026, 8, 1)) == date(2026, 9, 15)
    assert bd.fifteenth_of_next_month(date(2025, 12, 1)) == date(2026, 1, 15)


def test_ofr_fsi_is_used_three_weekdays_after_its_date():
    # Measured: on Sunday 2026-09-27 the newest OFR value was Wednesday 09-23.
    assert bd.three_weekdays_after(date(2026, 9, 23)) == date(2026, 9, 28)   # Wed -> Mon
    assert bd.three_weekdays_after(date(2026, 9, 25)) == date(2026, 9, 30)   # Fri -> Wed
    assert bd.three_weekdays_after(date(2026, 9, 21)) == date(2026, 9, 24)   # Mon -> Thu


def test_a_revised_ofr_date_uses_its_first_release():
    current = pd.DataFrame({"obs_date": [date(2017, 10, 2), date(2017, 10, 3), date(2026, 9, 23)],
                            "value": [-3.455, -3.545, -2.663]})
    first = pd.DataFrame({"obs_date": [date(2017, 10, 2), date(2017, 10, 3)], "value": [-3.605, -3.700]})
    out = bd.prefer_first_release(current, first)
    assert list(out["value"]) == [-3.605, -3.700, -2.663]
    empty = pd.DataFrame(columns=["obs_date", "value"])
    assert list(bd.prefer_first_release(current, empty)["value"]) == [-3.455, -3.545, -2.663]


# ---------------------------------------------------------------------------
# As-of join
# ---------------------------------------------------------------------------

SESS = [date(2026, 9, d) for d in (14, 15, 16, 17, 18, 21, 22, 23, 24, 25)]


def test_a_value_never_appears_before_it_is_public():
    f = bd.with_availability(pd.DataFrame({"obs_date": [date(2026, 9, 15)], "x": [1.0]}), "brent")
    out, _ = bd.asof_join(SESS, f, ["x"], "brent", "x")
    assert out.loc[date(2026, 9, 16), "x"] != out.loc[date(2026, 9, 16), "x"]  # NaN on Wed 16
    assert out.loc[date(2026, 9, 17), "x"] == 1.0                              # public Thu 17
    assert out.loc[date(2026, 9, 17), "x__obs_date"] == date(2026, 9, 15)


def test_a_value_past_its_staleness_limit_is_nulled_not_carried():
    f = bd.with_availability(pd.DataFrame({"obs_date": [date(2026, 9, 14)], "x": [4.5]}), "ust")
    out, nulled = bd.asof_join(SESS, f, ["x"], "ust")
    assert out["x"].notna().sum() == 6          # the day itself + 5 sessions
    assert nulled == len(SESS) - 6
    assert out.loc[date(2026, 9, 22), "x"] != out.loc[date(2026, 9, 22), "x"]


def test_native_windows_need_their_full_length():
    f = pd.DataFrame({"obs_date": [date(2026, 1, 1) + timedelta(days=i) for i in range(30)],
                      "v": np.linspace(10, 11, 30)})
    g = bd.native_features(f, "v", "rate")
    assert g["v_rv_21d"].iloc[:21].isna().all() and g["v_rv_21d"].iloc[21:].notna().all()
    assert g["v_mom_5d"].iloc[:5].isna().all()
    assert g["v_rv_63d"].isna().all()


# ---------------------------------------------------------------------------
# End to end on synthetic data
# ---------------------------------------------------------------------------

def _synthetic(seed: int = 7):
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2020-01-01", "2020-12-31").date
    sessions = [d for i, d in enumerate(days) if i % 37 != 5]   # a few B3 holidays
    curve_rows = []
    base = 5.0
    # Every curve reaches one vertex past the tenors read from it, as B3's do:
    # the last segment is never treated as anchored.
    for d in sessions:
        base += rng.normal(0, 0.03)
        for du in [*DU, 3000]:
            curve_rows.append((d, "PRE", int(du * 365 / 252), du, base + du / 1000 + rng.normal(0, 0.005)))
            curve_rows.append((d, "DPL", int(du * 365 / 252), du, 3.0 + du / 2000 + rng.normal(0, 0.005)))
        for cd in (30, 90, 180, 360, 720, 1080):
            curve_rows.append((d, "DOC", cd, int(cd * 252 / 365), 3.0 + rng.normal(0, 0.05)))
    curves = pd.DataFrame(curve_rows, columns=["trade_date", "curve", "calendar_days", "business_days", "rate"])

    def walk(dates, start, sd):
        return pd.DataFrame({"obs_date": list(dates), "value": start + np.cumsum(rng.normal(0, sd, len(dates)))})

    us_days = [d for i, d in enumerate(days) if i % 41 != 3]    # US holidays differ
    months = [date(2020, m, 1) for m in range(1, 13)]
    series = {
        "usdbrl": walk(sessions, 5.2, 0.02),
        "ust_1y": walk(us_days, 1.5, 0.02), "ust_2y": walk(us_days, 1.6, 0.02),
        "ust_5y": walk(us_days, 1.7, 0.02), "ust_10y": walk(us_days, 1.9, 0.02),
        "ust_30y": walk(us_days, 2.3, 0.02),
        "ofr_fsi": walk(us_days, -2.0, 0.1), "ofr_fsi_volatility": walk(us_days, -0.5, 0.05),
        "brent": walk(days, 60.0, 0.8),
        "selic": walk(sessions, 4.5, 0.0),
        "ipca": walk(months, 0.3, 0.1), "ipca_12m": walk(months, 4.0, 0.1),
        "commodity_index": walk(months, 300.0, 5.0),
        "focus_ipca_12m": walk(sessions, 3.5, 0.01),
    }
    futures = pd.DataFrame({"trade_date": [d for d in sessions for _ in range(3)],
                            "ticker": [t for _ in sessions for t in ("DI1F21", "DI1F22", "DI1F23")],
                            "open_interest": 1000, "contracts": 10})
    return sessions, curves, series, futures


RULE_OF = {name: rule for name, (rule, _kind) in bd.SCALAR_SERIES.items()}


def _published_by(cutoff, curves, series, futures):
    c = curves[curves["trade_date"] <= cutoff]
    s = {k: v[[bd.RULES[RULE_OF[k]].available(d) <= cutoff for d in v["obs_date"]]] for k, v in series.items()}
    f = futures[futures["trade_date"] <= cutoff]
    return c, s, f


def test_the_matrix_has_the_documented_columns():
    sessions, curves, series, futures = _synthetic()
    out, _ = bd.build(sessions, curves, series, futures)
    for col in ("di_1y", "di_2y", "di_3y", "di_5y", "di_10y", "di_anchor_du", "di_2s5s", "di_curvature",
                "usdbrl", "ust_2y", "ust_10y", "ust_2s10s", "ofr_fsi", "ofr_fsi_volatility",
                "ofr_fsi_mom_21d", "corr_di2y_ofr_vol_21d", "rates_vol_proxy",
                "brazil_sovereign_risk_proxy", "brent", "commodity_index", "ipca", "selic",
                "breakeven_1y", "breakeven_2y", "breakeven_5y", "breakeven_2y_mom_21d",
                "di_2y_mom_21d", "di_2y_rv_63d", "corr_di2y_usdbrl_21d", "corr_usdbrl_brent_63d",
                "di1_open_interest", "brent__obs_date"):
        assert col in out.columns, col
    assert list(out["date"]) == sorted(sessions)
    assert out["di_10y"].notna().all() and out["breakeven_5y"].notna().all()


def test_no_look_ahead_rows_up_to_t_ignore_everything_published_later():
    sessions, curves, series, futures = _synthetic()
    full, _ = bd.build(sessions, curves, series, futures)
    for cutoff in (date(2020, 3, 18), date(2020, 7, 1), date(2020, 11, 20)):
        c, s, f = _published_by(cutoff, curves, series, futures)
        past = [d for d in sessions if d <= cutoff]
        part, _ = bd.build(past, c, s, f)
        pd.testing.assert_frame_equal(
            full[full["date"] <= cutoff].reset_index(drop=True), part.reset_index(drop=True),
            check_dtype=False,
        )


def test_open_interest_is_null_when_b3_drops_a_contract_that_held_a_position():
    """Measured: B3's Price Report omits OpnIntrst for 36 of 37 DI1 contracts
    on 2018-05-10, in every version. Summing the rest would say 4,380
    contracts were open instead of about 23 million. A contract with no
    position the session before (new or empty) is not a drop."""
    d1, d2, d3 = date(2018, 5, 9), date(2018, 5, 10), date(2018, 5, 11)
    futures = pd.DataFrame([
        (d1, "DI1N18", 100, 5), (d1, "DI1F19", 200, 7), (d1, "DI1F29", None, None),
        (d2, "DI1N18", None, 4), (d2, "DI1F19", 210, 6), (d2, "DI1F29", None, None),
        (d3, "DI1N18", 120, 3), (d3, "DI1F19", 220, 2), (d3, "DI1F29", None, None),
        (d3, "DI1F30", None, 1),                                  # listed that day
    ], columns=["trade_date", "ticker", "open_interest", "contracts"])
    liq = bd.di1_liquidity(futures).set_index("obs_date")
    assert liq.loc[d1, "di1_open_interest"] == 300
    assert pd.isna(liq.loc[d2, "di1_open_interest"])              # DI1N18 held 100 the day before
    assert liq.loc[d2, "di1_contracts"] == 10                     # volume is still whole
    assert liq.loc[d3, "di1_open_interest"] == 340                # F29 and F30 never held one
    out, _ = bd.build([d1, d2, d3], _real_like_pre([d1, d2, d3]), {}, futures)
    assert out["di1_open_interest"].isna().tolist() == [False, True, False]


def _real_like_pre(days):
    return pd.DataFrame([(d, "PRE", cd, du, 6.5) for d in days for cd, du in ((365, 252), (730, 504), (1826, 1260))],
                        columns=["trade_date", "curve", "calendar_days", "business_days", "rate"])


def test_the_sovereign_proxy_is_doc_minus_ust_in_effective_terms():
    """DOC is linear on 360 days (Manual de Curvas v21 §4.5): over 365 days
    the effective annual rate is r·365/360. UST par is semi-annual."""
    d = date(2020, 6, 1)
    doc = [(30, 20, 2.1), (90, 62, 2.4), (180, 124, 2.7), (360, 250, 3.0), (370, 257, 3.0),
           (720, 497, 3.6), (1080, 745, 3.9)]
    curves = pd.DataFrame(
        [(d, "DOC", cd, du, r) for cd, du, r in doc]
        + [(d, "PRE", 365, 252, 5.0), (d, "PRE", 730, 504, 5.5), (d, "PRE", 1095, 756, 5.9)],
        columns=["trade_date", "curve", "calendar_days", "business_days", "rate"])
    series = {"ust_1y": pd.DataFrame({"obs_date": [d], "value": [2.0]})}
    out, _ = bd.build([d], curves, series)
    doc_eff = 3.0 * 365 / 360
    ust_eff = ((1 + 2.0 / 200) ** 2 - 1) * 100
    assert out.loc[0, "brazil_sovereign_risk_proxy"] == pytest.approx((doc_eff - ust_eff) * 100)


# ---------------------------------------------------------------------------
# B3's extrapolated tail (Manual de Curvas v21 §2.1)
# ---------------------------------------------------------------------------

TS_CURVES = (Path(__file__).parent / "fixtures" / "b3_taxaswap_20260925_curves.txt").read_text(encoding="latin-1")


def _real_curves() -> pd.DataFrame:
    from src.parsers.b3_taxa_swap import parse_taxa_swap
    rows, _ = parse_taxa_swap(TS_CURVES, session=date(2026, 9, 25))
    df = pd.DataFrame(rows)
    df["rate"] = df["rate"].astype(float)
    return df


def test_the_anchor_on_the_real_2026_09_25_curve_stops_before_the_last_di1_maturity():
    """Measured on the full Price Report of 2026-09-25: 45 DI1 contracts, the
    second-to-last maturing in 3322 business days and the last in 3572. The
    detector must never place the anchor past the second-to-last."""
    pre = _real_curves().query("curve == 'PRE'").sort_values("business_days")
    anchor = bd.pre_anchor(pre)
    assert anchor == 3289
    assert anchor <= 3322 < pre["business_days"].max()


def _contracts_then_extension():
    """DI1-like vertices with an irregular curve, then B3's extension of the
    last segment's forward, rounded to 3 decimals as PRE is published."""
    contract_du = [21, 63, 126, 252, 504, 756, 1008, 1260, 1512, 1764, 2016]
    contract_r = [13.60, 13.52, 13.41, 13.35, 13.62, 13.88, 13.95, 14.10, 14.02, 14.21, 14.40]
    log_df = [du / 252 * math.log1p(r / 100) for du, r in zip(contract_du, contract_r)]
    fwd = (log_df[-1] - log_df[-2]) / (contract_du[-1] - contract_du[-2])
    rows = list(zip(contract_du, contract_r))
    for du in range(2268, 6048, 252):
        lf = log_df[-1] + fwd * (du - contract_du[-1])
        rows.append((du, round((math.exp(lf * 252 / du) - 1) * 100, 3)))
    return pd.DataFrame([(date(2026, 1, 5), "PRE", int(du * 365 / 252), du, r) for du, r in rows],
                        columns=["trade_date", "curve", "calendar_days", "business_days", "rate"])


def test_the_detector_finds_where_b3s_extension_begins():
    curves = _contracts_then_extension()
    # The flat-forward segment starts at the second-to-last contract.
    assert bd.pre_anchor(curves) == 1764


def test_di_tenors_past_the_anchor_are_null_not_b3s_extrapolation():
    out = bd.di_constant_maturity(_contracts_then_extension())
    assert out.loc[0, "di_anchor_du"] == 1764
    assert out.loc[0, "di_5y"] == pytest.approx(14.10, abs=1e-9)   # a contract vertex
    assert math.isnan(out.loc[0, "di_10y"])                         # 2520 is extrapolated


def test_breakeven_is_b3s_implied_inflation_from_pre_and_dpl():
    d = date(2026, 1, 5)
    rows = []
    for du in (21, 252, 504, 756, 1260, 1512, 2520):
        rows.append((d, "PRE", int(du * 365 / 252), du, 12.0 + du / 10000))
        rows.append((d, "DPL", int(du * 365 / 252), du, 6.0))
    out = bd.breakeven_inflation(pd.DataFrame(rows, columns=["trade_date", "curve", "calendar_days",
                                                             "business_days", "rate"]))
    assert out.loc[0, "breakeven_1y"] == pytest.approx(((1.12 + 0.000252) / 1.06 - 1) * 100)
    assert out.loc[0, "breakeven_5y"] == pytest.approx(((1.12 + 0.00126) / 1.06 - 1) * 100)


def test_real_breakevens_on_2026_09_25_are_b3s_numbers():
    """PRE 13.61 / DPL 6.76 at 253 business days, as published that day."""
    out = bd.breakeven_inflation(_real_curves())
    assert 6.3 < out.loc[0, "breakeven_1y"] < 6.5
    assert 5.9 < out.loc[0, "breakeven_2y"] < 6.0


def test_a_us_holiday_does_not_blank_the_cross_market_features():
    sessions, curves, series, futures = _synthetic()
    out, _ = bd.build(sessions, curves, series, futures)
    us = set(series["ust_1y"]["obs_date"])
    br_only = [d for d in sessions if d not in us and d > date(2020, 5, 1)]
    assert br_only, "the synthetic calendars must differ"
    rows = out[out["date"].isin(br_only)]
    assert rows["brazil_sovereign_risk_proxy"].notna().all()
    assert rows["corr_di2y_ust10y_21d"].notna().all()


def test_every_warehouse_query_runs_read_only():
    executed = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            executed.append(sql)

        def fetchall(self):
            return []

    class Client:
        def cursor(self):
            return Cursor()

    bd.load(Client(), date(2020, 1, 2), date(2020, 1, 3))
    assert len(executed) >= 2
    assert executed[0::2] == ["SET default_transaction_read_only = on"] * (len(executed) // 2)
    assert all(sql.startswith("SELECT ") for sql in executed[1::2])


# ---------------------------------------------------------------------------
# The quality report (research_examples/dustin_br/quality.py)
# ---------------------------------------------------------------------------

def test_the_real_data_check_passes_on_the_builder_and_says_so():
    sessions, curves, series, futures = _synthetic()
    full, nulled = bd.build(sessions, curves, series, futures)
    cutoffs = (date(2020, 3, 18), date(2020, 7, 1), date(2020, 11, 20))
    look = quality.look_ahead(sessions, curves, series, futures, full, cutoffs)
    assert look == dict.fromkeys(cutoffs, 0)
    report = quality.render(full, nulled, look, sessions[0], sessions[-1])
    assert "**No look-ahead: passed.**" in report
    assert "| year | sessions | di_1y | di_5y | di_10y |" in report


def test_the_real_data_check_catches_a_planted_leak(monkeypatch):
    """Tomorrow's PTAX on today's row: the rows up to the cutoff change."""
    honest = bd.build

    def leaky(sessions, curves, series, futures=None):
        usdbrl = series["usdbrl"]
        leaked = usdbrl.assign(value=usdbrl["value"].shift(-1)).dropna()
        return honest(sessions, curves, {**series, "usdbrl": leaked}, futures)

    monkeypatch.setattr(bd, "build", leaky)
    sessions, curves, series, futures = _synthetic()
    full, nulled = bd.build(sessions, curves, series, futures)
    look = quality.look_ahead(sessions, curves, series, futures, full, [date(2020, 7, 1)])
    assert look[date(2020, 7, 1)] > 0
    assert "**No look-ahead: FAILED.**" in quality.render(full, nulled, look, sessions[0], sessions[-1])


def test_a_block_the_rebuild_lacks_reads_as_null():
    """Before 2018 there are no DI1 settlements, so a rebuild at an early
    cutoff has no di1_* columns at all: that matches NULL, not a value."""
    full = pd.DataFrame({"date": [date(2012, 9, 3)], "di_1y": [8.1], "di1_open_interest": [np.nan]})
    rebuilt = pd.DataFrame({"date": [date(2012, 9, 3)], "di_1y": [8.1]})
    assert quality.changed_cells(full, rebuilt) == 0
    assert quality.changed_cells(full.assign(di1_open_interest=5.0), rebuilt) == 1
    assert quality.changed_cells(full, rebuilt.assign(di_1y=8.2)) == 1


def test_coverage_and_tail_masking_are_per_year():
    frame = pd.DataFrame({
        "date": [date(2008, 1, 2), date(2008, 1, 3), date(2009, 1, 2), date(2009, 1, 5)],
        "di_anchor_du": [2000, 3000, 3000, 3000],
        "di_10y": [np.nan, 11.0, 12.0, np.nan],
    })
    cov = quality.coverage_by_year(frame)
    assert cov.loc[2008, "di_10y"] == 0.5 and cov.loc[2009, "di_anchor_du"] == 1.0
    tail = quality.tail_masking(frame)
    assert tail.loc[2008, "sessions"] == 2 and tail.loc[2008, "median_anchor_du"] == 2500
    assert tail.loc[2008, "di_10y_in_tail"] == 0.5 and tail.loc[2009, "di_10y_in_tail"] == 0.0
    assert tail.loc[2008, "di_5y_in_tail"] == 0.0


def test_sessions_a_source_lacks_are_listed_both_ways():
    """Measured 2026-09-28: B3 serves an empty archive for PR210610.zip, a
    session with a PRE curve and equity trading, so DI1 is missing that day."""
    pre = [date(2021, 6, 8), date(2021, 6, 9), date(2021, 6, 10), date(2021, 6, 11)]
    equity = [date(2021, 6, 7), date(2021, 6, 8), date(2021, 6, 9), date(2021, 6, 10), date(2021, 6, 14)]
    futures = pd.DataFrame({"trade_date": [date(2021, 6, 9), date(2021, 6, 11)]})
    missing = quality.missing_sessions(pre, futures, equity)
    assert missing == {
        "PRE curve missing on an equity session": [],   # 06-07 and 06-14 are outside the common span
        "PRE curve on a day with no equity session": [date(2021, 6, 11)],
        "DI1 settlements missing on a PRE session (from 2021-06-09)": [date(2021, 6, 10)],
    }
    frame = pd.DataFrame({"date": pre, "di_anchor_du": [3000] * 4})
    report = quality.render(frame, {}, {}, pre[0], pre[-1], missing)
    assert "- DI1 settlements missing on a PRE session (from 2021-06-09): 2021-06-10." in report
    assert "- PRE curve missing on an equity session: none." in report
