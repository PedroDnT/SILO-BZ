"""Offline checks of the equity-funds-vs-Ibovespa study arithmetic, on a synthetic
fund and a synthetic index with known quotas and levels."""
import math

import pytest

from research_examples.equity_vs_ibov import study as S


def test_twelve_months_difference_in_points():
    # Fund 100 -> 120 (+20%), index 1,000 -> 1,100 (+10%): +10 points, not "200% of the index".
    out = S.summarize([{"q0": 100.0, "q1": 120.0, "holders": 10, "pl": 1e6}], 1000.0, 1100.0, 1)
    assert out["index_return_pct"] == pytest.approx(10.0)
    assert out["median_fund_return_pct"] == pytest.approx(20.0)
    assert out["median_excess_pp"] == pytest.approx(10.0)
    assert out["holder_weighted_excess_pp"] == pytest.approx(10.0)
    assert out["funds_beating_index"] == 1


def test_long_window_annualizes_both_sides_before_the_difference():
    # 36 months: fund +33.1% -> 10% a year; index +21.0% -> about 6.56% a year.
    out = S.summarize([{"q0": 100.0, "q1": 133.1, "holders": 1, "pl": 1.0}], 1000.0, 1210.0, 3)
    idx_a = 1.21 ** (1 / 3) - 1
    assert out["index_return_pct"] == pytest.approx(100 * idx_a)
    assert out["median_excess_pp"] == pytest.approx(100 * (0.10 - idx_a))


def test_median_and_weights():
    rows = [
        {"q0": 100.0, "q1": 105.0, "holders": 1000, "pl": 1.0},   # -5 pp
        {"q0": 100.0, "q1": 110.0, "holders": 10, "pl": 10.0},    #  0 pp
        {"q0": 100.0, "q1": 125.0, "holders": 10, "pl": 89.0},    # +15 pp
    ]
    out = S.summarize(rows, 50.0, 55.0, 1)                         # index +10%
    assert out["median_excess_pp"] == pytest.approx(0.0)
    assert out["holder_weighted_excess_pp"] == pytest.approx((-5 * 1000 + 15 * 10) / 1020)
    assert out["pl_weighted_excess_pp"] == pytest.approx((-5 * 1 + 15 * 89) / 100)
    assert out["holders"] == 1020


def test_missing_weight_is_left_out_never_filled():
    rows = [{"q0": 1.0, "q1": 1.2, "holders": None, "pl": 1.0},
            {"q0": 1.0, "q1": 1.0, "holders": 5, "pl": 1.0}]
    out = S.summarize(rows, 1.0, 1.1, 1)
    assert out["missing_holders"] == 1
    assert out["holder_weighted_excess_pp"] == pytest.approx(-10.0)


def test_non_positive_quota_raises():
    with pytest.raises(ValueError):
        S.period_return(0.0, 1.0)


def test_groups():
    assert S.group_of("AÇÕES - ATIVO - LIVRE", "IBOVESPA") == "main"
    assert S.group_of("AÇÕES - ATIVO - LIVRE", "IBRX-50") == "ibrx"
    assert S.group_of("AÇÕES - ATIVO - LIVRE", None) == "no_benchmark_on_file"
    assert S.group_of("AÇÕES - ATIVO - SMALL CAPS", "IBOVESPA") == "small_caps"
    assert S.group_of("MULTIMERCADO - ESTRATÉGIA - LONG & SHORT NEUTRO", "IBOVESPA") == "long_short"


def test_one_subclass_per_fund():
    rows = [{"cnpj": "1", "pl": 5.0, "id": "a"}, {"cnpj": "1", "pl": 9.0, "id": "b"}, {"cnpj": "2", "pl": None, "id": "c"}]
    kept = {r["id"] for r in S.pick_one_subclass(rows)}
    assert kept == {"b", "c"}
    assert not math.isnan(S.excess_pp(0.1, 0.05))
