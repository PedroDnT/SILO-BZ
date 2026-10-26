"""Implied rate of a debenture from a traded PU (#1007, ADR 0004 amendment).

A deterministic calculation, not a model and not a source: given the published
agenda of a bond, the B3 reference curves of the trade date and a traded PU, it
finds the yield that discounts the projected cash flows to that PU. Same inputs,
same output. Anything it cannot price raises ``Unsupported`` with a short
``reason``; the caller writes no row and counts the reason. It never guesses.

Conventions of ``METHOD_VERSION`` v1 (a change to any of them is a new version):

* 252 business days a year. Business days come from ANBIMA's holiday list.
  ``du(a, b)`` counts the business days in (a, b].
* A flow is dated at its ``data_liquidacao``; a flow on the settlement date or
  before is not part of the price. Interest accrues from the previous interest
  event date (or the start of rentability) to the event date, over the business
  days in [start, end).
* ``Amortizacao`` is a share of the VNA just before the event. A maturity event
  redeems what is left and must say 100%.
* PRE: coupon factor (1 + r) ** (du / 252); the yield is the discount rate.
* DI + spread: realised CDI (SGS 12) up to the settlement date, the forward DI
  of the PRE curve after it, times (1 + spread) ** (du / 252). The result is
  the spread over the DI curve.
* % of DI: each day accrues 1 + p * (DI factor - 1). The result is the percent
  of DI that discounts the flows.
* IPCA + spread: VNA follows IPCA by the 15th-of-the-month anniversary: the
  period that starts on the 15th of month m accrues the IPCA of month m, pro
  rata in business days (measured on the stored coupons of CHSF13 and CLAG13).
  Up to the settlement date it uses the published IPCA, or the latest Focus
  median for a month not yet published. Flows are the agenda applied to the VNA
  of the settlement date and discounted at the real yield, as for an NTN-B:
  expected inflation after the settlement date is in the yield, not in the flows.

Where this differs from ANBIMA's indicative rate (projection of IPCA, the
payment-date rule of each deed) the gap is the validation, not a fix.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable, Optional, Sequence

import numpy as np

METHOD_VERSION = "v1"
DAYS_YEAR = 252


class Unsupported(Exception):
    """The bond or an input cannot be priced. ``reason`` is a short counted code."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


def _d64(d: date) -> np.datetime64:
    return np.datetime64(d, "D")


class Calendar:
    """Business days from a holiday list; refuses to answer outside its coverage."""

    def __init__(self, holidays: Iterable[date]) -> None:
        days = sorted(set(holidays))
        if not days:
            raise Unsupported("calendar_empty")
        self.first, self.last = days[0], days[-1]
        self._h = np.array([_d64(d) for d in days], dtype="datetime64[D]")

    def _check(self, *ds: date) -> None:
        for d in ds:
            if not (self.first <= d <= self.last):
                raise Unsupported("calendar_coverage", f"{d} is outside {self.first}..{self.last}")

    def du(self, a: date, b: date) -> int:
        """Business days in (a, b]; negative when b < a."""
        self._check(a, b)
        return int(np.busday_count(_d64(a) + np.timedelta64(1, "D"), _d64(b) + np.timedelta64(1, "D"), holidays=self._h))

    def count_in(self, a: date, b: date) -> int:
        """Business days in [a, b)."""
        self._check(a, b)
        return int(np.busday_count(_d64(a), _d64(b), holidays=self._h))

    def days_in(self, a: date, b: date) -> np.ndarray:
        """Business days in [a, b), as datetime64[D]."""
        self._check(a, b)
        days = np.arange(_d64(a), _d64(b), dtype="datetime64[D]")
        return days[np.is_busday(days, holidays=self._h)]

    def next_bday(self, days: np.ndarray) -> np.ndarray:
        return np.busday_offset(days, 1, roll="forward", holidays=self._h)


class Curve:
    """A zero curve from (business days, annual percent rate) vertices on a 252 basis.

    Flat forward between vertices (log discount factor linear in business days),
    flat rate before the first vertex and the last forward after the last one.
    """

    def __init__(self, vertices: Sequence[tuple[int, float]]) -> None:
        pts = sorted({int(n): float(r) for n, r in vertices if int(n) > 0}.items())
        if len(pts) < 2:
            raise Unsupported("curve_missing", "fewer than 2 vertices")
        self._n = np.array([0.0] + [n for n, _ in pts])
        self._ldf = np.array([0.0] + [-n / DAYS_YEAR * math.log1p(r / 100.0) for n, r in pts])

    def log_df(self, n: float) -> float:
        xs, ys = self._n, self._ldf
        if n <= 0:
            return 0.0
        if n >= xs[-1]:
            slope = (ys[-1] - ys[-2]) / (xs[-1] - xs[-2])
            return float(ys[-1] + slope * (n - xs[-1]))
        return float(np.interp(n, xs, ys))

    def log_df_arr(self, n: np.ndarray) -> np.ndarray:
        xs, ys = self._n, self._ldf
        slope = (ys[-1] - ys[-2]) / (xs[-1] - xs[-2])
        return np.where(n >= xs[-1], ys[-1] + slope * (n - xs[-1]), np.interp(n, xs, ys))

    def df(self, n: float) -> float:
        return math.exp(self.log_df(n))

    def vertices(self) -> list[tuple[int, float]]:
        return [(int(n), float(100 * (math.exp(-l * DAYS_YEAR / n) - 1)))
                for n, l in zip(self._n[1:], self._ldf[1:])]


@dataclass(frozen=True)
class Event:
    data_evento: date
    evento: str
    data_liquidacao: date
    percentual_taxa_pct: Optional[float]


@dataclass(frozen=True)
class Bond:
    codigo: str
    indexador: Optional[str]
    forma_remuneracao: Optional[str]
    taxa_remuneracao_pct: Optional[float]
    vne_brl: float
    data_inicio_rentabilidade: Optional[date]
    data_vencimento: date
    events: tuple[Event, ...]


@dataclass
class Market:
    """What the trade date offers: curves, the CDI realised so far and IPCA."""

    trade_date: date
    pre: Curve
    cdi_pct_daily: dict = field(default_factory=dict)     # date -> SGS 12 value (percent a day)
    ipca_pct_monthly: dict = field(default_factory=dict)  # (year, month) -> percent of that month
    ipca_focus_pct: dict = field(default_factory=dict)    # (year, month) -> Focus median, latest survey <= trade date
    projected_used: set = field(default_factory=set, repr=False)
    _levels: dict = field(default_factory=dict, repr=False)

    def ipca_level(self, y: int, m: int) -> float:
        """Cumulative IPCA factor through month (y, m), from the first month held."""
        if not self._levels:
            f, ym = 1.0, min(self.ipca_pct_monthly)
            while ym in self.ipca_pct_monthly:
                f *= 1 + self.ipca_pct_monthly[ym] / 100.0
                self._levels[ym] = f
                ym = (ym[0] + 1, 1) if ym[1] == 12 else (ym[0], ym[1] + 1)
        if (y, m) not in self._levels:
            raise Unsupported("ipca_missing", f"{y}-{m:02d}")
        return self._levels[(y, m)]


# ----------------------------------------------------------------------------------
# IPCA index of the debenture VNA


def _anniversary(d: date) -> tuple[date, date]:
    """The 15th at or before ``d`` and the next 15th."""
    y, m = d.year, d.month
    if d.day < 15:
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    start = date(y, m, 15)
    y2, m2 = (y + 1, 1) if m == 12 else (y, m + 1)
    return start, date(y2, m2, 15)


def ipca_index(d: date, cal: Calendar, market: "Market") -> float:
    """Index level at ``d``: the period that starts on the 15th of month m accrues IPCA of m."""
    start, nxt = _anniversary(d)
    pm = (start.year, start.month)
    prev = (pm[0] - 1, 12) if pm[1] == 1 else (pm[0], pm[1] - 1)
    if pm in market.ipca_pct_monthly:
        rate = market.ipca_pct_monthly[pm]
    elif pm in market.ipca_focus_pct:
        rate = market.ipca_focus_pct[pm]
        market.projected_used.add(pm)
    else:
        raise Unsupported("ipca_missing", f"{pm[0]}-{pm[1]:02d}")
    theta = cal.du(start, d) / cal.du(start, nxt)
    return market.ipca_level(*prev) * (1 + rate / 100.0) ** theta


# ----------------------------------------------------------------------------------
# The calculation


@dataclass
class Result:
    implied_rate_pct: float
    rate_basis: str
    flows_used: int
    inputs: dict
    solver: dict


def _unit_basis(bond: Bond) -> str:
    idx, forma = (bond.indexador or "").upper(), bond.forma_remuneracao
    if idx == "PRE" and forma == "prefixado":
        return "pre_aa"
    if idx == "IPCA" and forma == "spread":
        return "ipca_real_aa"
    if idx == "DI" and forma == "spread":
        return "di_spread_aa"
    if idx == "DI" and forma == "percentual":
        return "pct_di"
    raise Unsupported("indexer", f"{bond.indexador}/{bond.forma_remuneracao}")


def _schedule(bond: Bond):
    """(interest dates, amortisation shares by event date, maturity date, mode) from the agenda.

    The agenda's percentages are shares of the VNA just before each event ("vna"), as on
    CLAG13 (33.3333, 50, 100), or shares of the original principal ("original"), as on KLBNA2
    (33.33, 33.33, then 33.34 at maturity). The maturity row says which: 100 is the whole
    remainder; otherwise the shares must add up to 100. Anything else is refused.
    """
    juros, amort, venc, venc_pct = [], {}, None, None
    for e in bond.events:
        if e.evento == "Pagamento de juros":
            juros.append(e.data_evento)
        elif e.evento == "Amortizacao":
            if e.percentual_taxa_pct is None or not 0 < e.percentual_taxa_pct <= 100:
                raise Unsupported("amortisation_pct", f"{e.data_evento}")
            amort[e.data_evento] = amort.get(e.data_evento, 0.0) + e.percentual_taxa_pct / 100.0
        elif e.evento.startswith("Vencimento"):
            venc, venc_pct = e.data_evento, e.percentual_taxa_pct
        else:
            raise Unsupported("event_type", e.evento)
    if venc is None or not juros:
        raise Unsupported("agenda_incomplete")
    if venc_pct == 100:
        mode = "vna"
    elif venc_pct is not None and abs(sum(amort.values()) * 100 + venc_pct - 100) < 0.02:
        mode = "original"
    else:
        raise Unsupported("maturity_pct", f"{venc_pct}")
    return sorted(set(juros)), amort, venc, mode


def implied_rate(bond: Bond, pu_brl: float, settlement: date, market: Market, cal: Calendar) -> Result:
    if not pu_brl or pu_brl <= 0:
        raise Unsupported("pu_invalid")
    basis = _unit_basis(bond)
    rate = bond.taxa_remuneracao_pct
    if rate is None:
        raise Unsupported("contract_rate_missing")
    market.projected_used.clear()
    juros_dates, amort, venc, mode = _schedule(bond)
    if bond.data_inicio_rentabilidade is None:
        raise Unsupported("start_missing")
    liq = {e.data_evento: e.data_liquidacao for e in bond.events}
    if venc <= settlement:
        raise Unsupported("matured")

    t = market.trade_date
    nt = lambda d: cal.du(t, d)  # business days from the curve date
    n_s = nt(settlement)
    has_di = basis in ("di_spread_aa", "pct_di")

    # Business-day log accrual of the DI leg, from the last interest date on or before the
    # settlement date to maturity: realised CDI before the settlement date, the forward
    # DI of the PRE curve from it.
    if has_di:
        grid_start = max([d for d in juros_dates if d <= settlement] + [bond.data_inicio_rentabilidade])
        grid = cal.days_in(grid_start, venc)
        logf = np.zeros(len(grid))
        k = int(np.searchsorted(grid, _d64(settlement)))
        for i in range(k):
            v = market.cdi_pct_daily.get(grid[i].astype(object))
            if v is None:
                raise Unsupported("cdi_missing", str(grid[i]))
            logf[i] = math.log1p(v / 100.0)
        if k < len(grid):
            n0 = nt(grid[k].astype(object))
            n = n0 + np.arange(len(grid) - k, dtype=float)
            logf[k:] = market.pre.log_df_arr(n) - market.pre.log_df_arr(n + 1)
        if basis == "pct_di":
            logf = np.log1p(rate / 100.0 * np.expm1(logf))
        cum = np.concatenate([[0.0], np.cumsum(logf)])

        def accrual(a: date, b: date) -> float:
            ia = int(np.searchsorted(grid, _d64(a)))
            ib = int(np.searchsorted(grid, _d64(b)))
            f = math.exp(cum[ib] - cum[ia])
            if basis == "di_spread_aa":
                f *= (1 + rate / 100.0) ** ((ib - ia) / DAYS_YEAR)
            return f
    else:
        def accrual(a: date, b: date) -> float:
            return (1 + rate / 100.0) ** (cal.count_in(a, b) / DAYS_YEAR)

    # VNA of the settlement date, as a multiple of the original principal.
    if basis == "ipca_real_aa":
        idx_s = ipca_index(settlement, cal, market) / ipca_index(bond.data_inicio_rentabilidade, cal, market)
    else:
        idx_s = 1.0

    def growth(d: date) -> float:
        return idx_s

    # Cash flows after the settlement date.
    all_dates = sorted(set(juros_dates) | set(amort) | {venc})
    flows: list[tuple[date, float]] = []
    remaining = 1.0  # share of the original principal still outstanding
    prev_coupon = bond.data_inicio_rentabilidade
    for d in all_dates:
        vna_before = bond.vne_brl * remaining * growth(d)
        cash = 0.0
        pay = liq.get(d, d)
        if d in juros_dates:
            if pay > settlement:
                cash += vna_before * (accrual(prev_coupon, d) - 1.0)
            prev_coupon = d
        if d == venc:
            share = remaining
        elif mode == "vna":
            share = remaining * amort.get(d, 0.0)
        else:
            share = amort.get(d, 0.0)
        if share and pay > settlement:
            cash += bond.vne_brl * share * growth(d)
        remaining -= share
        if cash and pay > settlement:
            flows.append((pay, cash))
    if not flows or remaining > 1e-9:
        raise Unsupported("agenda_incomplete", f"remaining={remaining:.6f}")

    # Discount factors as a function of the solved parameter y.
    ns = np.array([cal.du(settlement, d) for d, _ in flows], dtype=float)
    cf = np.array([c for _, c in flows])
    if has_di:
        di_df = np.array([market.pre.df(nt(d)) / market.pre.df(n_s) for d, _ in flows])
    if basis == "pct_di":
        lo, hi = 1e-6, 10.0

        def price(m: float) -> float:
            return float(np.sum(cf * di_df ** m))
    else:
        lo, hi = -0.95, 20.0
        base = di_df if has_di else 1.0

        def price(y: float) -> float:
            return float(np.sum(cf * base * (1 + y) ** (-ns / DAYS_YEAR)))

    f_lo, f_hi = price(lo) - pu_brl, price(hi) - pu_brl
    if f_lo * f_hi > 0:
        raise Unsupported("no_root", f"PU {pu_brl} outside [{price(hi):.2f}, {price(lo):.2f}]")
    iters = 0
    while hi - lo > 1e-13 and iters < 300:
        mid = (lo + hi) / 2
        if (price(mid) - pu_brl) * f_lo > 0:
            lo = mid
        else:
            hi = mid
        iters += 1
    y = (lo + hi) / 2
    out = y * 100.0
    last_cdi = max((d for d in market.cdi_pct_daily if d < settlement), default=None)
    return Result(
        implied_rate_pct=out,
        rate_basis=basis,
        flows_used=len(flows),
        inputs={
            "method_version": METHOD_VERSION,
            "curve_date": t.isoformat(),
            "pu_brl": pu_brl,
            "vna_settlement_brl": round(bond.vne_brl * _remaining_at(amort, mode, settlement) *
                                        idx_s, 6),
            "last_flow": flows[-1][0].isoformat(),
            "cdi_last_used": last_cdi.isoformat() if last_cdi and has_di else None,
            "ipca_through": ("%d-%02d" % max(market.ipca_pct_monthly) if basis == "ipca_real_aa" else None),
            "ipca_projected": sorted("%d-%02d" % ym for ym in market.projected_used),
        },
        solver={"iterations": iters, "residual_brl": round(price(y) - pu_brl, 8)},
    )


def _remaining_at(amort: dict, mode: str, d: date) -> float:
    r = 1.0
    for ad, a in sorted(amort.items()):
        if ad <= d:
            r = r * (1 - a) if mode == "vna" else r - a
    return r
