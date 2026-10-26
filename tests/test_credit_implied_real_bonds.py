"""The implied-rate calculation against real, stored data (#1007).

``tests/fixtures/credit_implied_2026-10-21.json`` holds what SILO stored on 2026-10-21 for six
debentures: the agenda, the B3 PRE curve, CDI, IPCA and ANBIMA's own indicative rate and PU of
that day. Two checks need no judgement:

* the accrual reproduces the interest ANBIMA lists as paid (LIQUIDADO) to the cent;
* feeding ANBIMA's indicative PU back in returns ANBIMA's indicative rate, to a few basis points.

A gap above the tolerance means a convention changed: bump ``METHOD_VERSION``, do not widen it.
"""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from src.credit.implied_rate import Bond, Calendar, Curve, Event, Market, implied_rate

FX = json.loads((Path(__file__).parent / "fixtures" / "credit_implied_2026-10-21.json").read_text())
CAL = Calendar(date.fromisoformat(d) for d in FX["holidays"])
T = date.fromisoformat(FX["curve_date"])
NAMES = {"Pag": "Pagamento de juros", "Amo": "Amortizacao", "Ven": "Vencimento (resgate)"}


def d6(s: str) -> date:
    return date(2000 + int(s[:2]), int(s[2:4]), int(s[4:]))


def cdi_daily() -> dict:
    steps = [(d6(a), float(b)) for a, b in (x.split(",") for x in FX["cdi_steps"].split(";"))]
    out, d = {}, steps[0][0]
    while d <= T:
        if CAL.du(d - timedelta(days=1), d) == 1:
            out[d] = [v for sd, v in steps if sd <= d][-1]
        d += timedelta(days=1)
    return out


def market() -> Market:
    ipca = {(2000 + int(a[:2]), int(a[2:])): float(b) for a, b in (x.split(",") for x in FX["ipca"].split(";"))}
    focus = {tuple(map(int, k.split("-"))): v for k, v in FX["focus"].items()}
    return Market(T, Curve([(n, r) for n, r, _ in FX["pre"]]), cdi_daily(), ipca, focus)


def bond(code: str) -> Bond:
    idx, forma, tx, vne, start, venc, _vna = FX["bonds"][code]["head"].split("/")
    events = []
    for e in FX["bonds"][code]["events"].split(";"):
        de, nm, dl, pct, _paid = e.split(",")
        events.append(Event(d6(de), NAMES[nm], d6(dl), float(pct) if pct else None))
    return Bond(code, idx, forma, float(tx), float(vne), date.fromisoformat(start), date.fromisoformat(venc), tuple(events))


def test_the_holiday_list_agrees_with_every_b3_curve_vertex():
    for n, _rate, cal_days in FX["pre"]:
        assert CAL.du(T, T + timedelta(days=cal_days)) == n


@pytest.mark.parametrize("a,b,paid,vna,kind,rate", [
    # AESLA8, DI + 0.49%: coupons of 2026-06-10 and 2026-09-10, on a VNA of 1000.
    (date(2026, 3, 10), date(2026, 6, 10), 35.273073, 1000, "spread", 0.49),
    (date(2026, 6, 10), date(2026, 9, 10), 35.868463, 1000, "spread", 0.49),
    # KLBNA2, 114.65% of DI: coupon of 2026-09-21, on a VNA of 10000.
    (date(2026, 3, 19), date(2026, 9, 21), 800.6459, 10000, "percentual", 114.65),
])
def test_di_accrual_reproduces_the_interest_ANBIMA_lists_as_paid(a, b, paid, vna, kind, rate):
    cdi = cdi_daily()
    f = 1.0
    for dd in CAL.days_in(a, b):
        di = 1 + cdi[dd.astype(object)] / 100
        f *= di if kind == "spread" else 1 + rate / 100 * (di - 1)
    if kind == "spread":
        f *= (1 + rate / 100) ** (CAL.count_in(a, b) / 252)
    assert vna * (f - 1) == pytest.approx(paid, abs=5e-5)  # the listed amounts have 4 to 6 decimals


@pytest.mark.parametrize("code,tol_bp", [
    ("AEGPA0", 1), ("AESLA8", 1), ("RADL14", 1), ("KLBNA2", 1),  # PRE, DI+, % DI
    ("CHSF13", 4), ("CLAG13", 4),                                # IPCA+: VNA of the day is rebuilt
])
def test_ANBIMA_indicative_pu_gives_back_ANBIMA_indicative_rate(code, tol_bp):
    ind = FX["indicative_2026_10_21"][code]
    res = implied_rate(bond(code), ind["pu"], T, market(), CAL)
    assert abs(res.implied_rate_pct - ind["rate_pct"]) * 100 <= tol_bp
    assert abs(res.solver["residual_brl"]) < 1e-6


def test_ipca_vna_matches_the_vna_ANBIMA_stored():
    for code, stored in (("CHSF13", 1111.47539), ("CLAG13", 881.673194)):
        ind = FX["indicative_2026_10_21"][code]
        res = implied_rate(bond(code), ind["pu"], T, market(), CAL)
        assert res.inputs["vna_settlement_brl"] == pytest.approx(stored, rel=6e-4)  # 2-decimal IPCA, Focus for October
        assert res.inputs["ipca_projected"] == ["2026-10"]
