"""Offline checks of the implied-rate calculation (#1007).

Every bond and curve here is synthetic and small enough to check by hand: the
expected PU is written from the closed form of the bond, not from the solver.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.credit.implied_rate import (
    Bond, Calendar, Curve, Event, Market, Unsupported, implied_rate, ipca_index,
)

# A few holidays are enough: the calendar only needs to cover 2025-2040.
HOLIDAYS = [date(y, 1, 1) for y in range(2025, 2041)] + [date(y, 12, 25) for y in range(2025, 2041)]
CAL = Calendar(HOLIDAYS)
T = date(2026, 1, 2)  # a Friday and a business day


def brute_du(a: date, b: date) -> int:
    """Business days in (a, b], counted one day at a time."""
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() < 5 and d not in HOLIDAYS:
            n += 1
    return n


def flat(rate_pct: float) -> Curve:
    return Curve([(n, rate_pct) for n in (21, 252, 504, 1260, 2520, 5040)])


def bond(indexador, forma, rate, events, start=T, vne=1000.0, venc=None):
    venc = venc or max(e.data_evento for e in events)
    return Bond("TEST11", indexador, forma, rate, vne, start, venc, tuple(events))


def ev(d, nome, pct=None, liq=None):
    return Event(d, nome, liq or d, pct)


V = date(2027, 1, 4)  # one year ahead; maturity in all the bullet bonds
N = brute_du(T, V)


def test_calendar_counts_like_a_brute_force_loop():
    assert N == 252 - 1 or N > 240  # sanity: about a year
    for a, b in [(T, V), (date(2026, 12, 24), date(2027, 1, 4)), (date(2030, 5, 6), date(2031, 3, 1))]:
        assert CAL.du(a, b) == brute_du(a, b)
        assert CAL.count_in(a, b) == brute_du(a, b) + (
            1 if a.weekday() < 5 and a not in HOLIDAYS else 0) - (
            1 if b.weekday() < 5 and b not in HOLIDAYS else 0)


def test_calendar_refuses_outside_its_coverage():
    with pytest.raises(Unsupported) as e:
        CAL.du(date(2040, 12, 31), date(2041, 6, 1))
    assert e.value.reason == "calendar_coverage"


def test_flat_curve_discounts_at_its_rate():
    c = flat(10.0)
    assert c.df(252) == pytest.approx(1 / 1.10)
    assert c.df(126) == pytest.approx(1.10 ** -0.5)
    assert c.df(7000) == pytest.approx(1.10 ** (-7000 / 252))  # flat forward past the last vertex


def test_prefixed_bullet_recovers_the_discount_rate():
    # 12% a year accrues for N business days; discounted at 14% it is worth the PU below.
    b = bond("PRE", "prefixado", 12.0, [ev(V, "Pagamento de juros"), ev(V, "Vencimento (resgate)", 100)])
    pu = 1000 * (1.12 / 1.14) ** (N / 252)
    r = implied_rate(b, pu, T, Market(T, flat(10.0)), CAL)
    assert r.rate_basis == "pre_aa"
    assert r.implied_rate_pct == pytest.approx(14.0, abs=1e-8)
    assert r.flows_used == 1
    assert abs(r.solver["residual_brl"]) < 1e-6
    assert r.inputs["method_version"] == "v1"


def test_prefixed_at_its_own_rate_is_par():
    b = bond("PRE", "prefixado", 12.0, [ev(V, "Pagamento de juros"), ev(V, "Vencimento (resgate)", 100)])
    assert implied_rate(b, 1000.0, T, Market(T, flat(10.0)), CAL).implied_rate_pct == pytest.approx(12.0, abs=1e-8)


def test_di_plus_spread_returns_the_spread_over_the_curve():
    # Flow = 1000 * 1.10**(N/252) * 1.01**(N/252). Discount = 1.10**(N/252) * (1+y)**(N/252).
    b = bond("DI", "spread", 1.0, [ev(V, "Pagamento de juros"), ev(V, "Vencimento (resgate)", 100)])
    m = Market(T, flat(10.0))
    assert implied_rate(b, 1000.0, T, m, CAL).implied_rate_pct == pytest.approx(1.0, abs=1e-8)
    pu = 1000 * (1.01 / 1.02) ** (N / 252)
    assert implied_rate(b, pu, T, m, CAL).implied_rate_pct == pytest.approx(2.0, abs=1e-8)


def test_di_plus_spread_uses_the_realised_cdi_before_settlement():
    # Settled one business day after the start: the first day accrues at the realised CDI.
    s = date(2026, 1, 5)
    cdi = 0.05  # percent a day, above the 10% curve's daily rate on purpose
    b = bond("DI", "spread", 1.0, [ev(V, "Pagamento de juros"), ev(V, "Vencimento (resgate)", 100)])
    m = Market(T, flat(10.0), cdi_pct_daily={T: cdi})
    n = brute_du(s, V)
    flow = 1000 * (1 + cdi / 100) * 1.10 ** (n / 252) * 1.01 ** ((n + 1) / 252)
    pu = flow / (1.10 ** (n / 252) * 1.02 ** (n / 252))
    assert implied_rate(b, pu, s, m, CAL).implied_rate_pct == pytest.approx(2.0, abs=1e-6)


def test_missing_cdi_is_refused_not_guessed():
    s = date(2026, 1, 5)
    b = bond("DI", "spread", 1.0, [ev(V, "Pagamento de juros"), ev(V, "Vencimento (resgate)", 100)])
    with pytest.raises(Unsupported) as e:
        implied_rate(b, 1000.0, s, Market(T, flat(10.0)), CAL)
    assert e.value.reason == "cdi_missing"


def test_percent_of_di_returns_the_multiplier():
    # 100% of DI on a flat 10% curve is worth 1000 * 1.10**(N/252); discounted at m times DI.
    b = bond("DI", "percentual", 100.0, [ev(V, "Pagamento de juros"), ev(V, "Vencimento (resgate)", 100)])
    m = Market(T, flat(10.0))
    assert implied_rate(b, 1000.0, T, m, CAL).implied_rate_pct == pytest.approx(100.0, abs=1e-6)
    pu = 1000 * 1.10 ** ((1 - 1.1) * N / 252)
    assert implied_rate(b, pu, T, m, CAL).implied_rate_pct == pytest.approx(110.0, abs=1e-6)


def test_ipca_plus_spread_discounts_at_the_real_yield_on_todays_vna():
    # Settled on the 15th with the index at 1.00 of the start: VNA 1000, flows on VNA, real yield.
    m = Market(T, flat(10.0), ipca_pct_monthly={(y, mo): 0.4 for y in range(2024, 2028) for mo in range(1, 13)})
    b = bond("IPCA", "spread", 6.0, [ev(V, "Pagamento de juros"), ev(V, "Vencimento (resgate)", 100)], start=T)
    pu = 1000 * (1.06 / 1.08) ** (N / 252)
    r = implied_rate(b, pu, T, m, CAL)
    assert r.rate_basis == "ipca_real_aa"
    assert r.implied_rate_pct == pytest.approx(8.0, abs=1e-6)
    assert r.inputs["vna_settlement_brl"] == pytest.approx(1000.0)


def test_ipca_vna_of_the_settlement_date_scales_the_pu():
    # One full 15th-to-15th period later at 0.5% a month: VNA 1005, the PU scales with it.
    start, s = date(2026, 1, 15), date(2026, 2, 16)
    m = Market(s, flat(10.0), ipca_pct_monthly={(y, mo): 0.5 for y in range(2024, 2028) for mo in range(1, 13)})
    venc = date(2027, 2, 15)
    b = bond("IPCA", "spread", 6.0, [ev(venc, "Pagamento de juros"), ev(venc, "Vencimento (resgate)", 100)], start=start)
    theta = CAL.du(date(2026, 2, 15), s) / CAL.du(date(2026, 2, 15), date(2026, 3, 15))
    vna = 1000 * 1.005 ** (1 + theta)
    n_acc, n_disc = CAL.count_in(start, venc), CAL.du(s, venc)
    pu = vna * (1.06 ** (n_acc / 252)) / 1.07 ** (n_disc / 252)
    r = implied_rate(b, pu, s, m, CAL)
    assert r.inputs["vna_settlement_brl"] == pytest.approx(vna, rel=1e-9)
    assert r.implied_rate_pct == pytest.approx(7.0, abs=1e-6)


def test_ipca_index_follows_the_15th_anniversary():
    ipca = {(2025, 12): 0.40, (2026, 1): 0.60, (2026, 2): 0.30}
    m = Market(T, flat(10.0), ipca_pct_monthly=ipca)
    # The period that starts on 15/01 accrues January's IPCA (0.60%); the one that starts
    # on 15/02 accrues February's (0.30%), pro rata in business days.
    a, b = date(2026, 1, 15), date(2026, 2, 16)
    theta = CAL.du(date(2026, 2, 15), b) / CAL.du(date(2026, 2, 15), date(2026, 3, 15))
    assert ipca_index(date(2026, 2, 15), CAL, m) / ipca_index(a, CAL, m) == pytest.approx(1.006, rel=1e-12)
    assert ipca_index(b, CAL, m) / ipca_index(a, CAL, m) == pytest.approx(1.006 * 1.003 ** theta, rel=1e-12)


def test_an_unpublished_month_uses_the_focus_median_and_says_so():
    m = Market(T, flat(10.0), ipca_pct_monthly={(2025, 12): 0.40}, ipca_focus_pct={(2026, 1): 0.50})
    start = date(2026, 1, 15)
    day = date(2026, 1, 20)
    theta = CAL.du(start, day) / CAL.du(start, date(2026, 2, 15))
    assert ipca_index(day, CAL, m) / ipca_index(start, CAL, m) == pytest.approx(1.005 ** theta)
    assert m.projected_used == {(2026, 1)}


def test_ipca_missing_month_is_refused():
    m = Market(T, flat(10.0), ipca_pct_monthly={(2025, 1): 0.4})
    b = bond("IPCA", "spread", 6.0, [ev(V, "Pagamento de juros"), ev(V, "Vencimento (resgate)", 100)])
    with pytest.raises(Unsupported) as e:
        implied_rate(b, 1000.0, T, m, CAL)
    assert e.value.reason == "ipca_missing"


def test_coupons_and_amortisation_match_a_hand_built_schedule():
    # PRE 12%. Interest on 2026-07-01 and 2027-01-04. 50% of the VNA amortises on the first date.
    j1, j2 = date(2026, 7, 1), V
    b = bond("PRE", "prefixado", 12.0, [
        ev(j1, "Pagamento de juros"), ev(j1, "Amortizacao", 50),
        ev(j2, "Pagamento de juros"), ev(j2, "Vencimento (resgate)", 100)])
    n1, n2 = brute_du(T, j1), brute_du(j1, j2)
    c1 = 1000 * (1.12 ** (n1 / 252) - 1)
    a1 = 500.0
    c2 = 500 * (1.12 ** (n2 / 252) - 1)
    y = 0.09
    pu = (c1 + a1) / (1 + y) ** (brute_du(T, j1) / 252) + (c2 + 500) / (1 + y) ** (brute_du(T, j2) / 252)
    r = implied_rate(b, pu, T, Market(T, flat(10.0)), CAL)
    assert r.flows_used == 2
    assert r.implied_rate_pct == pytest.approx(9.0, abs=1e-8)


def test_flows_on_or_before_settlement_are_not_priced():
    j1 = date(2026, 7, 1)
    b = bond("PRE", "prefixado", 12.0, [
        ev(j1, "Pagamento de juros"), ev(V, "Pagamento de juros"), ev(V, "Vencimento (resgate)", 100)])
    s = j1  # settles on the coupon date: that coupon already belongs to the seller
    n = brute_du(j1, V)
    c2 = 1000 * (1.12 ** (brute_du(j1, V) / 252) - 1)
    pu = (c2 + 1000) / 1.13 ** (n / 252)
    assert implied_rate(b, pu, s, Market(T, flat(10.0)), CAL).implied_rate_pct == pytest.approx(13.0, abs=1e-8)


@pytest.mark.parametrize("indexador,forma,reason", [("IGPM", "spread", "indexer"), (None, None, "indexer")])
def test_unsupported_indexers_are_refused(indexador, forma, reason):
    b = bond(indexador, forma, 5.0, [ev(V, "Pagamento de juros"), ev(V, "Vencimento (resgate)", 100)])
    with pytest.raises(Unsupported) as e:
        implied_rate(b, 1000.0, T, Market(T, flat(10.0)), CAL)
    assert e.value.reason == reason


def test_a_maturity_that_is_not_the_whole_remainder_is_refused():
    b = bond("PRE", "prefixado", 12.0, [ev(V, "Pagamento de juros"), ev(V, "Vencimento (resgate)", 33.34)])
    with pytest.raises(Unsupported) as e:
        implied_rate(b, 1000.0, T, Market(T, flat(10.0)), CAL)
    assert e.value.reason == "maturity_pct"


def test_unknown_event_type_and_missing_agenda_are_refused():
    b = bond("PRE", "prefixado", 12.0, [ev(V, "Pagamento de juros"), ev(V, "Vencimento (resgate)", 100),
                                       ev(V, "Repactuacao")])
    with pytest.raises(Unsupported) as e:
        implied_rate(b, 1000.0, T, Market(T, flat(10.0)), CAL)
    assert e.value.reason == "event_type"
    empty = Bond("X", "PRE", "prefixado", 12.0, 1000.0, T, V, ())
    with pytest.raises(Unsupported) as e:
        implied_rate(empty, 1000.0, T, Market(T, flat(10.0)), CAL)
    assert e.value.reason == "agenda_incomplete"


def test_matured_bond_and_a_pu_outside_the_solvable_range():
    b = bond("PRE", "prefixado", 12.0, [ev(V, "Pagamento de juros"), ev(V, "Vencimento (resgate)", 100)])
    with pytest.raises(Unsupported) as e:
        implied_rate(b, 1000.0, V, Market(V, flat(10.0)), CAL)
    assert e.value.reason == "matured"
    with pytest.raises(Unsupported) as e:
        implied_rate(b, 1e9, T, Market(T, flat(10.0)), CAL)
    assert e.value.reason == "no_root"
    with pytest.raises(Unsupported) as e:
        implied_rate(b, 0, T, Market(T, flat(10.0)), CAL)
    assert e.value.reason == "pu_invalid"


def test_same_inputs_give_the_same_result():
    b = bond("PRE", "prefixado", 12.0, [ev(V, "Pagamento de juros"), ev(V, "Vencimento (resgate)", 100)])
    a = implied_rate(b, 987.65, T, Market(T, flat(10.0)), CAL)
    c = implied_rate(b, 987.65, T, Market(T, flat(10.0)), CAL)
    assert (a.implied_rate_pct, a.inputs, a.solver) == (c.implied_rate_pct, c.inputs, c.solver)
