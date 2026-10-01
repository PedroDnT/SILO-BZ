"""Verify the research seam on SILO's live public interface (#420, spec §9).

Read-only. Uses only the public SDK (`sdk/silo_client`) and the publishable key
built into it, i.e. exactly what an external research caller has. It runs the
public-interface test list of RESEARCH_SEAM.md §9 against the live API and
gives a READY or NOT READY verdict per requirement, with the evidence:

    pip install -e sdk/
    python docs/reference/research/verify_research_seam.py \
        [--n 100] [--workers 8] [--db-url "$POSTGRES_URL"] \
        [--markdown out.md] [--json out.json]

Run it AFTER the analytics apply that installs the research functions (a merge
deploys nothing). The exit code is 0 only when every requirement is READY.

A check that raises is a FAIL with the exception as its evidence: nothing here
is retried or swallowed. A check that cannot run is NOT RUN, which is not a
pass. The board-continuity requirement reads `b3_cotahist`, which the public API
does not expose, so it needs `--db-url`; without one it is NOT RUN and prints
the query. Never put a connection string with a password on a shared terminal.

The pins below are numbers this repository measured on 2026-09-30 (UTC-3); the
adjusted LEVELS move when a later corporate event lands, so the hard pins are
returns and raw closes, and a level is reported as evidence.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

try:  # an installed SDK, else the one in this repository
    from silo_client import (
        KNOWN_CATALOG_VERSION,
        SiloClient,
        SiloError,
        SiloFanOutError,
        SiloOverCap,
    )
except ImportError:  # pragma: no cover - the in-repo fallback
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "sdk"))
    from silo_client import (  # type: ignore  # noqa: E402
        KNOWN_CATALOG_VERSION,
        SiloClient,
        SiloError,
        SiloFanOutError,
        SiloOverCap,
    )

TAPE_START = "2019-01-02"
UTC_MINUS_3 = dt.timezone(dt.timedelta(hours=-3))

REQUIREMENTS: Dict[str, str] = {
    "R1": "Research universe (§4)",
    "R2": "Price-adjusted close (§3, #417)",
    "R3": "Total-return close (§3, #418)",
    "R4": "Benchmark index (§5, #412, #415)",
    "R5": "Fundamentals as known, no look-ahead (§6, #414)",
    "R6": "Tape window and refusals (§3)",
    "R7": "Board continuity (§3 item 6, §9; #377 section 8)",
    "R8": "Research-sized retrieval (§7, §8)",
    "R9": "Macro by date split (§7)",
    "R10": "Contract: catalog and coverage",
}

#: The eleven sessions on which B3 re-scaled IBOV (found in the series, #412).
IBOV_DIVISOR_STEPS = [
    "1983-10-04", "1985-12-03", "1988-08-30", "1989-04-18", "1990-01-15",
    "1991-05-29", "1992-01-22", "1993-01-27", "1993-08-30", "1994-02-10",
    "1997-03-03",
]

#: The `codbdi`-change query (#377 section 8): universe tickers that printed on
#: more than one board of the cash market since the start of the tape.
BOARD_SQL = """\
WITH u AS (SELECT ticker FROM public.mv_research_universe)
SELECT b.codneg AS ticker,
       array_to_string(array_agg(DISTINCT b.codbdi ORDER BY b.codbdi), '/') AS boards,
       count(DISTINCT b.trade_date) AS sessions
FROM public.b3_cotahist b
JOIN u ON u.ticker = b.codneg
WHERE b.tpmerc = '010' AND b.trade_date >= DATE '2019-01-02'
GROUP BY b.codneg
HAVING count(DISTINCT b.codbdi) > 1
ORDER BY sessions DESC"""


@dataclass
class Result:
    requirement: str
    check: str
    status: str  # PASS | FAIL | NOT RUN
    evidence: str


class Ctx:
    """What the checks share: the client, the clock, and anything fetched once."""

    def __init__(self, s: Any, n: int, workers: int, today: dt.date,
                 board_query: Optional[Callable[[], List[Dict[str, Any]]]] = None):
        self.s = s
        self.n = n
        self.workers = workers
        self.today = today
        self.board_query = board_query
        self._universe: Optional[List[Dict[str, Any]]] = None
        self.pull: Optional[Dict[str, List[Dict[str, Any]]]] = None
        self.results: List[Result] = []

    @property
    def universe(self) -> List[Dict[str, Any]]:
        if self._universe is None:
            self._universe = self.s.research_universe()
        return self._universe


def _num(x: Any) -> Optional[float]:
    return None if x is None else float(x)


def _by_date(rows: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(r["trade_date"]): r for r in rows}


def _refused(exc: BaseException, *needles: str) -> bool:
    body = getattr(exc, "body", None) or str(exc)
    return isinstance(exc, SiloError) and all(n in body for n in needles)


def _business_days(a: str, b: str) -> float:
    d0, d1 = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    return max((d1 - d0).days, 0) * 5 / 7


def check(ctx: Ctx, req: str, name: str, fn: Callable[[], "tuple[bool, str]"]) -> None:
    """Run one check. An exception is a FAIL carrying the exception, never a skip."""
    try:
        ok, evidence = fn()
        status = "PASS" if ok else "FAIL"
    except Exception as exc:  # noqa: BLE001 - reported, then the run continues
        status, evidence = "FAIL", f"{type(exc).__name__}: {str(exc)[:300]}"
    ctx.results.append(Result(req, name, status, evidence))


def not_run(ctx: Ctx, req: str, name: str, why: str) -> None:
    ctx.results.append(Result(req, name, "NOT RUN", why))


# ---------------------------------------------------------------------------
# R1 research universe
# ---------------------------------------------------------------------------

def r1(ctx: Ctx) -> None:
    def count():
        n = len(ctx.universe)
        return 300 <= n <= 1000, f"{n} ticker+ISIN pairs"

    def receipts():
        bad = [r["ticker"] for r in ctx.universe
               if str(r["isin"])[6:9] not in ("ACN", "CDA", "UNT")]
        return not bad, ("no subscription receipt, BDR, fund or index in the universe"
                         if not bad else f"outside the rule: {bad[:8]}")

    def natu3():
        rows = [r for r in ctx.universe if r["ticker"] == "NATU3"]
        if len(rows) != 1:
            return False, f"NATU3 has {len(rows)} rows, expected one"
        r = rows[0]
        span = _business_days(str(r["first_observed"]), str(r["last_observed"]))
        return r["n_sessions"] < 0.6 * span, (
            f"one row, n_sessions {r['n_sessions']} against about {span:.0f} business days of span")

    def stems():
        by_stem: Dict[str, set] = {}
        for r in ctx.universe:
            if r.get("cnpj"):
                by_stem.setdefault(str(r["ticker"])[:4], set()).add(r["cnpj"])
        stem_rows = {str(r["ticker"])[:4] for r in ctx.universe
                     if r.get("cnpj_basis") == "fca_issuer_stem"}
        bad = {k: sorted(v) for k, v in by_stem.items() if k in stem_rows and len(v) > 1}
        return not bad, (f"{len(stem_rows)} fca_issuer_stem stems, each with one CNPJ"
                         if not bad else f"stems with more than one CNPJ: {bad}")

    def rename():
        s = ctx.s
        on_old = {r["ticker"] for r in s.research_universe(as_of="2025-11-07")}
        on_new = {r["ticker"] for r in s.research_universe(as_of="2025-11-10")}
        isins = {r["ticker"]: r["isin"] for r in ctx.universe if r["ticker"] in ("ELET3", "AXIA3")}
        ok = ("ELET3" in on_old and "AXIA3" not in on_old and "AXIA3" in on_new
              and "ELET3" not in on_new and len(set(isins.values())) == 2)
        return ok, f"ELET3 until 2025-11-07, AXIA3 from 2025-11-10, two ISINs, never linked: {isins}"

    def not_substitutes():
        tickers = {r["ticker"] for r in ctx.universe}
        bad = sorted({"BOVA11", "IBOV11"} & tickers)
        return not bad, "BOVA11 and IBOV11 are not in the universe" if not bad else f"present: {bad}"

    check(ctx, "R1", "universe size and the 1,000-row cap", count)
    check(ctx, "R1", "no R## receipt, BDR, fund or index", receipts)
    check(ctx, "R1", "NATU3 is one row with n_sessions below its span", natu3)
    check(ctx, "R1", "every fca_issuer_stem stem has one CNPJ", stems)
    check(ctx, "R1", "a rename is two rows, filtered by as_of", rename)
    check(ctx, "R1", "BOVA11 and IBOV11 are outside the universe", not_substitutes)


# ---------------------------------------------------------------------------
# R2 price-adjusted close
# ---------------------------------------------------------------------------

def r2(ctx: Ctx) -> None:
    s = ctx.s

    def bbas3():
        d = _by_date(s.quote_history("BBAS3", start="2024-04-10", end="2024-04-20"))
        a, b = d["2024-04-15"], d["2024-04-16"]
        raw_ret = _num(b["close"]) / _num(a["close"]) - 1
        adj_a, adj_b = _num(a["close_price_adjusted"]), _num(b["close_price_adjusted"])
        reasons = [r["close_price_adjusted_null_reason"] for r in d.values()]
        if adj_a is None or adj_b is None:
            return False, f"adjusted close is NULL: {set(reasons)}"
        adj_ret = adj_b / adj_a - 1
        ok = (abs(_num(a["close"]) - 56.46) < 0.01 and -0.03 <= adj_ret <= 0.0
              and raw_ret < -0.4 and not any(reasons) and a["adjusted"] is False)
        return ok, (f"raw {a['close']} -> {b['close']} ({raw_ret:+.1%}); adjusted {adj_a:.2f} -> "
                    f"{adj_b:.2f} ({adj_ret:+.1%}); level 28.23 was measured on 2026-09-30 and "
                    "moves when a later event lands")

    def mglu3():
        d = _by_date(s.quote_history("MGLU3", start="2024-05-20", end="2024-05-31"))
        a, b = d["2024-05-24"], d["2024-05-27"]
        raw_ret = _num(b["close"]) / _num(a["close"]) - 1
        adj_a, adj_b = _num(a["close_price_adjusted"]), _num(b["close_price_adjusted"])
        if adj_a is None or adj_b is None:
            return False, (f"adjusted close is NULL: {a['close_price_adjusted_null_reason']}")
        adj_ret = adj_b / adj_a - 1
        return abs(adj_ret) < 0.15 and raw_ret > 5, (
            f"raw {raw_ret:+.0%} across the grouping, adjusted {adj_ret:+.1%}")

    def other_classes():
        out = []
        for ticker in ("BOVA11", "IBOV11"):
            rows = s.quote_history(ticker, start="2025-01-02", end=ctx.today.isoformat())
            if not rows:
                return False, f"{ticker} returned no rows to test"
            bad = [r for r in rows if r["close_price_adjusted"] is not None
                   or r["close_price_adjusted_null_reason"] != "outside research universe"]
            out.append(f"{ticker} {len(rows)} rows" + (f", {len(bad)} wrong" if bad else ""))
            if bad:
                return False, "; ".join(out)
        return True, "; ".join(out) + ": NULL with 'outside research universe'"

    check(ctx, "R2", "BBAS3 split 2024-04-15: no jump in the adjusted return", bbas3)
    check(ctx, "R2", "MGLU3 grouping 2024-05-24: no jump in the adjusted return", mglu3)
    check(ctx, "R2", "other classes are NULL with a reason", other_classes)


# ---------------------------------------------------------------------------
# R3 total-return close
# ---------------------------------------------------------------------------

def r3(ctx: Ctx) -> None:
    s = ctx.s

    def petr4_pin():
        rows = s.quote_history("PETR4", start="2023-12-28", end="2023-12-28")
        if len(rows) != 1:
            return False, f"{len(rows)} rows on 2023-12-28"
        r = rows[0]
        tr, adj = _num(r["close_total_return"]), _num(r["close_price_adjusted"])
        if tr is None or adj is None:
            return False, (f"NULL: adjusted {r['close_price_adjusted_null_reason']!r}, "
                           f"total return {r['close_total_return_null_reason']!r}")
        ratio = tr / adj
        return 0.55 <= ratio <= 0.80, (
            f"total return / adjusted = {ratio:.4f} (0.6875 on 2026-09-30; it moves as "
            "distributions land)")

    def invariants():
        rows = ctx.s.quote_history_all("PETR4", start=TAPE_START, end=ctx.today.isoformat())
        pairs = [(r["trade_date"], _num(r["close_total_return"]), _num(r["close_price_adjusted"]))
                 for r in rows]
        both = [(d, tr, adj) for d, tr, adj in pairs if tr is not None and adj is not None]
        if len(both) < 1000:
            return False, f"only {len(both)} of {len(rows)} sessions carry both levels"
        above = [d for d, tr, adj in both if tr > adj * (1 + 1e-9)]
        ratios = [tr / adj for _, tr, adj in both]
        # The ratio is 1 / prod(1 + D/P) over LATER events: it can only rise toward 1.
        falls = [both[i + 1][0] for i in range(len(ratios) - 1)
                 if ratios[i + 1] < ratios[i] * (1 - 1e-9)]
        last_gap = abs(both[-1][1] - both[-1][2])
        ok = not above and not falls and last_gap < 1e-4
        return ok, (f"{len(both)} sessions: never above the adjusted close ({len(above)} above), "
                    f"the ratio never falls ({len(falls)} falls), equal on the latest session "
                    f"(gap {last_gap:.2e})")

    check(ctx, "R3", "PETR4 total return differs from adjusted by the cash paid since", petr4_pin)
    check(ctx, "R3", "total return <= adjusted, ratio rises to 1, equal on the latest session", invariants)


# ---------------------------------------------------------------------------
# R4 benchmark index
# ---------------------------------------------------------------------------

def r4(ctx: Ctx) -> None:
    s = ctx.s

    def year_end():
        rows = s.index_history("IBOV", start="2025-12-30", end="2025-12-30")
        if len(rows) != 1:
            return False, f"{len(rows)} rows on 2025-12-30"
        level = _num(rows[0]["level"])
        return abs(level - 161125.37) < 0.005, f"IBOV 2025-12-30 = {level} (B3's year-end figure is 161,125.37)"

    def full_history():
        rows = s.index_history_all("IBOV", start="1968-01-02", end=ctx.today.isoformat())
        dates = [str(r["trade_date"]) for r in rows]
        steps = [str(r["trade_date"]) for r in rows if r["divisor_step"]]
        ok = (len(rows) >= 14000 and dates == sorted(set(dates)) and dates[0] == "1968-01-02"
              and steps == IBOV_DIVISOR_STEPS)
        return ok, (f"{len(rows)} sessions from {dates[0]}, unique and ordered, "
                    f"{len(steps)} divisor steps (expected {len(IBOV_DIVISOR_STEPS)})")

    def tickers_refused():
        out = []
        for code in ("BOVA11", "IBOV11", "PETR4"):
            try:
                rows = s.index_history(code)
            except SiloError as exc:
                if not _refused(exc, "22023"):
                    return False, f"{code} failed with something other than the refusal: {exc}"
                out.append(f"{code} refused")
            else:
                return False, f"{code} was served ({len(rows)} rows): a ticker substituted for the index"
        return True, ", ".join(out) + " (22023, naming the codes held)"

    def over_cap():
        try:
            s.index_history("IBOV", start="1968-01-02", end=ctx.today.isoformat())
        except SiloOverCap:
            return True, "IBOV from 1968 without a cursor is refused, not trimmed"
        return False, "a 14,000-row window was not refused"

    def ibov11_is_not_the_index():
        start = max(TAPE_START, (ctx.today - dt.timedelta(days=400)).isoformat())
        end = ctx.today.isoformat()
        prints = s.quote_history("IBOV11", start=start, end=end)
        levels = {str(r["trade_date"]): _num(r["level"])
                  for r in s.index_history_all("IBOV", start=start, end=end)}
        classes = {r.get("asset_class") for r in prints}
        shared = [(_num(r["close"]), levels[str(r["trade_date"])])
                  for r in prints if str(r["trade_date"]) in levels]
        if classes != {"index"} or len(shared) < 20:
            return False, (f"asset_class {sorted(map(str, classes))}, {len(shared)} sessions shared with "
                           "the official series (need at least 20)")
        diffs = [abs(a / b - 1) for a, b in shared]
        equal = [1 for a, b in shared if abs(a - b) < 0.5]
        ok = not equal
        return ok, (f"IBOV11 printed on {len(prints)} sessions since {start}; on the {len(shared)} shared "
                    f"with the official close, {len(equal)} equal it (mean difference "
                    f"{sum(diffs) / len(diffs):.2%}, largest {max(diffs):.2%}): a settlement index, never the "
                    "benchmark. Print frequency is not the test: it was monthly through 2024 and is nearly "
                    "daily since December 2025")

    def step_boundary():
        rows = s.index_history("IBOV", start="1997-02-28", end="1997-03-03")
        flagged = [str(r["trade_date"]) for r in rows if r["divisor_step"]]
        return flagged == ["1997-03-03"], f"1997-02-28..1997-03-03 flagged: {flagged}"

    check(ctx, "R4", "IBOV 2025-12-30 equals B3's published year-end close", year_end)
    check(ctx, "R4", "IBOV from 1968: ordered, eleven divisor steps, flagged", full_history)
    check(ctx, "R4", "a ticker never substitutes for the index", tickers_refused)
    check(ctx, "R4", "the 1997-03-03 step is flagged and the session before is not", step_boundary)
    check(ctx, "R4", "a long window refuses instead of trimming", over_cap)
    check(ctx, "R4", "IBOV11 is a settlement index and never equals the official close", ibov11_is_not_the_index)


# ---------------------------------------------------------------------------
# R5 fundamentals as known
# ---------------------------------------------------------------------------

def r5(ctx: Ctx) -> None:
    s = ctx.s
    window = dict(start="2023-01-01", end="2024-06-30")
    t = "2024-02-29"

    def acceptance():
        rows = s.financials("PETR4", "DRE", as_of=t, **window)
        refs = sorted({str(r["ref_date"]) for r in rows})
        return (bool(refs) and refs[-1] == "2023-09-30" and "2023-12-31" not in refs), (
            f"as of {t} the newest period is {refs[-1] if refs else None}; the DFP 2023 is absent")

    def no_look_ahead():
        rows = s.financials("PETR4", "DRE", as_of=t, **window)
        hist = s.financial_statement_history("PETR4", "DRE", **window)
        received = {(str(h["ref_date"]), h["doc_type"], h["version"]): h.get("filing_received_date")
                    for h in hist}
        leaks = []
        for r in rows:
            key = (str(r["ref_date"]), r["doc_type"], r["version"])
            got = received.get(key)
            if got is None or str(got) >= t:
                leaks.append((key, got))
        return (bool(rows) and not leaks), (
            f"{len(rows)} lines, each from a document received before {t}"
            if not leaks else f"{len(leaks)} lines from a document received on or after {t} "
            f"(or with no header): {leaks[:3]}")

    def latest_default():
        rows = s.financials("PETR4", "DRE", **window)
        refs = {str(r["ref_date"]) for r in rows}
        return "2023-12-31" in refs, (
            "without as_of the DFP 2023 is read at its latest version (not point-in-time)"
            if "2023-12-31" in refs else "the DFP 2023 is missing without as_of")

    def siblings():
        out = []
        for name, call in (
            ("company_financials", lambda: s.company_financials("PETR4", as_of=t, **window)),
            ("income_statements", lambda: s.income_statements("PETR4", as_of=t, **window)),
        ):
            rows = call()
            refs = {str(r["ref_date"]) for r in rows}
            if not rows or "2023-12-31" in refs:
                return False, f"{name}: {len(rows)} rows, refs {sorted(refs)}"
            out.append(f"{name} {len(rows)} rows")
        return True, ", ".join(out) + ", none for 2023-12-31"

    check(ctx, "R5", "PETR4 DFP 2023 at 2024-02-29 returns the ITR 2023-09-30", acceptance)
    check(ctx, "R5", "no line from a filing received on or after T", no_look_ahead)
    check(ctx, "R5", "without as_of it reads the latest version (labelled not point-in-time)", latest_default)
    check(ctx, "R5", "company_financials and income_statements honour as_of", siblings)


# ---------------------------------------------------------------------------
# R6 tape window and refusals
# ---------------------------------------------------------------------------

def r6(ctx: Ctx) -> None:
    s = ctx.s

    def before_tape():
        try:
            s.quote_history("PETR4", start="2018-12-31", end="2019-01-31")
        except SiloError as exc:
            return _refused(exc, "22023", TAPE_START) and not isinstance(exc, SiloOverCap), (
                f"refused naming {TAPE_START}" if _refused(exc, "22023", TAPE_START)
                else f"refused, but not naming the date: {exc}")
        return False, "a window starting 2018-12-31 was served"

    def empty_window():
        try:
            s.quote_history("PETR4", start="2015-01-01", end="2016-01-01")
        except SiloError as exc:
            return _refused(exc, "22023", TAPE_START), "an empty pre-tape window is refused too"
        return False, "an empty pre-tape window returned quietly"

    def boundary():
        rows = s.quote_history("PETR4", start=TAPE_START, end="2019-01-31")
        first = str(rows[0]["trade_date"]) if rows else None
        return (len(rows) >= 15 and first == TAPE_START), f"{len(rows)} rows, first {first}"

    def over_cap():
        try:
            s.quote_history("PETR4", start=TAPE_START, end=ctx.today.isoformat())
        except SiloOverCap:
            pass
        else:
            return False, "a seven-year window was served in one response"
        rows = s.quote_history_all("PETR4", start=TAPE_START, end=ctx.today.isoformat())
        dates = [str(r["trade_date"]) for r in rows]
        return (len(rows) > 1000 and dates == sorted(set(dates))), (
            f"refused in one call, {len(rows)} rows by cursor, unique and ordered")

    def unknown_ticker():
        rows = s.quote_history("ZZZZ9", start="2024-01-02", end="2024-01-31")
        return rows == [], "an unknown ticker returns an empty series, never a guessed row"

    def coverage_note():
        row = next((r for r in s.coverage() if r["dataset"] == "quotes"), None)
        note = (row or {}).get("notes") or ""
        return TAPE_START in note, f"coverage quotes notes: {note[:120]!r}"

    check(ctx, "R6", "a p_from before 2019-01-02 is refused, naming the date", before_tape)
    check(ctx, "R6", "an empty window wholly before the tape is refused", empty_window)
    check(ctx, "R6", "2019-01-02 itself is served", boundary)
    check(ctx, "R6", "over the row cap refuses; the cursor returns all of it", over_cap)
    check(ctx, "R6", "an unknown ticker is an empty series", unknown_ticker)
    check(ctx, "R6", "coverage() publishes the tape start on the quotes row", coverage_note)


# ---------------------------------------------------------------------------
# R7 board continuity (needs the database)
# ---------------------------------------------------------------------------

def r7(ctx: Ctx) -> None:
    name = "no universe ticker changed board since 2019"
    if ctx.board_query is None:
        not_run(ctx, "R7", name,
                "needs database access (b3_cotahist is not in the public API). Run with --db-url, or "
                "run this query read-only and compare:\n" + BOARD_SQL)
        return

    def run():
        rows = ctx.board_query()
        if not rows:
            return True, "every research-universe ticker printed on a single board"
        top = ", ".join(f"{r['ticker']} {r['boards']}" for r in rows[:8])
        return False, (f"{len(rows)} tickers printed on more than one board since 2019 ({top}...). "
                       "quote_history serves only the latest board by default, so their earlier sessions "
                       "are missing. OWNER DECISION PENDING (comment on #420): serve the union, refuse, "
                       "or document. Until chosen this requirement is NOT READY.")

    check(ctx, "R7", name, run)


# ---------------------------------------------------------------------------
# R8 research-sized retrieval
# ---------------------------------------------------------------------------

def r8(ctx: Ctx) -> None:
    s = ctx.s

    def pull():
        recent = (ctx.today - dt.timedelta(days=7)).isoformat()
        live = [r for r in ctx.universe if str(r["last_observed"]) >= recent]
        live.sort(key=lambda r: (-int(r["n_sessions"]), r["ticker"]))
        tickers = []
        for r in live:
            if r["ticker"] not in tickers:
                tickers.append(r["ticker"])
            if len(tickers) == ctx.n:
                break
        t0 = time.perf_counter()
        ctx.pull = s.quote_history_many(tickers, start=TAPE_START, end=ctx.today.isoformat(),
                                        workers=ctx.workers, require_rows=True)
        wall = time.perf_counter() - t0
        rows = sum(len(v) for v in ctx.pull.values())
        return len(ctx.pull) == len(tickers), (
            f"{len(ctx.pull)} tickers, {rows:,} rows, {wall:.1f} s on {ctx.workers} workers, "
            "no refusal, no empty series")

    def invariants():
        if ctx.pull is None:
            return False, "the pull did not complete"
        bad: List[str] = []
        reasons: Dict[str, int] = {}
        total = 0
        for ticker, rows in ctx.pull.items():
            for r in rows:
                total += 1
                adj, tr = r["close_price_adjusted"], r["close_total_return"]
                if adj is None and not r["close_price_adjusted_null_reason"]:
                    bad.append(f"{ticker} {r['trade_date']}: adjusted NULL without a reason")
                if tr is None and not r["close_total_return_null_reason"]:
                    bad.append(f"{ticker} {r['trade_date']}: total return NULL without a reason")
                if tr is not None and adj is None:
                    bad.append(f"{ticker} {r['trade_date']}: total return without an adjusted close")
                if r["adjusted"] is not False:
                    bad.append(f"{ticker} {r['trade_date']}: adjusted flag is not false")
                for key in ("close_price_adjusted_null_reason", "close_total_return_null_reason"):
                    if r[key]:
                        reasons[r[key]] = reasons.get(r[key], 0) + 1
        top = sorted(reasons.items(), key=lambda kv: -kv[1])[:4]
        return not bad, (f"{total:,} rows: every NULL carries a reason, no total return without an "
                         f"adjusted close; reasons {top}" if not bad else "; ".join(bad[:4]))

    def proven():
        if ctx.pull is None:
            return False, "the pull did not complete"
        latest = {t: rows[-1] for t, rows in ctx.pull.items()}
        with_value = [t for t, r in latest.items() if r["close_price_adjusted"] is not None]
        share = len(with_value) / len(latest)
        missing = {t: r["close_price_adjusted_null_reason"] for t, r in latest.items()
                   if r["close_price_adjusted"] is None}
        return share >= 0.95, (f"{len(with_value)} of {len(latest)} tickers have an adjusted close on "
                               f"their latest session ({share:.0%}); without: {dict(list(missing.items())[:5])}")

    def two_names():
        out = s.quote_history_many(["PETR4", "VALE3"], start=TAPE_START, end=ctx.today.isoformat(),
                                   workers=2, require_rows=True)
        counts = {k: len(v) for k, v in out.items()}
        return all(c >= 1800 for c in counts.values()), f"rows by ticker: {counts}"

    check(ctx, "R8", f"{ctx.n} liquid names since 2019: the whole request, no refusal", pull)
    check(ctx, "R8", "every NULL carries a reason; total return needs the adjusted close", invariants)
    check(ctx, "R8", "at least 95% of the names have an adjusted close on their latest session", proven)
    check(ctx, "R8", "PETR4 and VALE3 together", two_names)


# ---------------------------------------------------------------------------
# R9 macro by date split
# ---------------------------------------------------------------------------

def r9(ctx: Ctx) -> None:
    s = ctx.s
    today = ctx.today

    def chunks():
        spans = [("2019-01-01", "2021-12-31"), ("2022-01-01", "2024-12-31"), ("2025-01-01", today.isoformat())]
        dates: List[str] = []
        for a, b in spans:
            dates += [str(r["reference_date"]) for r in s.macro_series("CDI", start=a, end=b)]
        ok = len(dates) > 1500 and dates == sorted(set(dates))
        return ok, f"CDI 2019 onward in {len(spans)} three-year calls: {len(dates):,} rows, unique and ordered"

    def whole_refused():
        try:
            s.macro_series("CDI", start="2019-01-01", end=today.isoformat())
        except SiloOverCap:
            return True, "the whole window is refused (no cursor), so the caller splits by date"
        return False, "a seven-year daily window was served in one call"

    check(ctx, "R9", "CDI from 2019 fits in three date-split calls", chunks)
    check(ctx, "R9", "the whole window refuses instead of trimming", whole_refused)


# ---------------------------------------------------------------------------
# R10 contract
# ---------------------------------------------------------------------------

def r10(ctx: Ctx) -> None:
    s = ctx.s

    def catalog_version():
        served = s.catalog(refresh=True).get("version")
        return isinstance(served, int) and served >= 48, (
            f"catalog v{served} (this script needs v48: the tape window)")

    def coverage_rows():
        rows = {r["dataset"]: r for r in s.coverage()}
        note = (rows.get("index_history") or {}).get("notes") or ""
        return "IBOV from 1968-01-02" in note, f"index_history notes: {note[:100]!r}"

    check(ctx, "R10", "catalog version is current", catalog_version)
    check(ctx, "R10", "coverage() lists the index with its depth", coverage_rows)


# ---------------------------------------------------------------------------

def run_all(s: Any, n: int = 100, workers: int = 8, today: Optional[dt.date] = None,
            board_query: Optional[Callable[[], List[Dict[str, Any]]]] = None) -> List[Result]:
    ctx = Ctx(s, n, workers, today or dt.date.today(), board_query)
    for fn in (r1, r2, r3, r4, r5, r6, r7, r8, r9, r10):
        fn(ctx)
    return ctx.results


def verdicts(results: Sequence[Result]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for req in REQUIREMENTS:
        mine = [r for r in results if r.requirement == req]
        out[req] = "READY" if mine and all(r.status == "PASS" for r in mine) else "NOT READY"
    return out


def overall(results: Sequence[Result]) -> str:
    return "READY" if all(v == "READY" for v in verdicts(results).values()) else "NOT READY"


def render_markdown(results: Sequence[Result], now: Optional[dt.datetime] = None) -> str:
    now = now or dt.datetime.now(dt.timezone.utc)
    local = now.astimezone(UTC_MINUS_3)
    v = verdicts(results)
    lines = [
        f"## Research seam verification: **{overall(results)}**",
        "",
        f"Run {local:%Y-%m-%d %H:%M} UTC-3 ({now:%H:%M} UTC) against the live public API, "
        f"read-only. Spec: `docs/planning/RESEARCH_SEAM.md` §9.",
        "",
        "| Requirement | Verdict | PASS | FAIL | NOT RUN |",
        "| --- | --- | --- | --- | --- |",
    ]
    for req, title in REQUIREMENTS.items():
        mine = [r for r in results if r.requirement == req]
        count = lambda st: sum(1 for r in mine if r.status == st)  # noqa: E731
        lines.append(f"| {req} {title} | **{v[req]}** | {count('PASS')} | {count('FAIL')} | {count('NOT RUN')} |")
    lines += ["", "### Checks", ""]
    for req, title in REQUIREMENTS.items():
        lines.append(f"**{req} {title}**")
        lines.append("")
        for r in (x for x in results if x.requirement == req):
            first, *rest = r.evidence.splitlines() or [""]
            lines.append(f"- `{r.status}` {r.check}: {first}")
            for extra in rest:
                lines.append(f"  {extra}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _db_board_query(url: str) -> Callable[[], List[Dict[str, Any]]]:
    def run() -> List[Dict[str, Any]]:
        import psycopg2  # imported late: only --db-url needs it
        import psycopg2.extras

        conn = psycopg2.connect(url)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SET statement_timeout = '120s'")
                cur.execute(BOARD_SQL)
                return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    return run


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--n", type=int, default=100, help="size of the research-sized pull")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--db-url", default=None, help="read-only connection for the board-continuity query")
    ap.add_argument("--markdown", default=None, help="write the report here")
    ap.add_argument("--json", default=None, help="write the results here")
    a = ap.parse_args(argv)

    s = SiloClient(retries=0)
    results = run_all(s, n=a.n, workers=a.workers,
                      board_query=_db_board_query(a.db_url) if a.db_url else None)
    report = render_markdown(results)
    sys.stdout.write(report)
    if a.markdown:
        Path(a.markdown).write_text(report, encoding="utf-8")
    if a.json:
        Path(a.json).write_text(json.dumps({
            "overall": overall(results), "verdicts": verdicts(results),
            "results": [asdict(r) for r in results],
        }, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0 if overall(results) == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
