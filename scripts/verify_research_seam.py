"""Verify the research price contract on the LIVE API, as an external caller would.

    python scripts/verify_research_seam.py        # exit 1 on any failure

No database access: only the public REST API through the SDK (the public key
is its default). Run it after the analytics apply, the corporate-event sweep
and the index backfill have landed; scripts/check_live_contract.py covers the
MCP and the contract shape. Checks, from the #410 acceptance list:

  1. ETER3's raw series crosses boards 08 and 02 with no lost session;
  2. PETR4 + VALE3 through prices(): one row per ticker and session, sorted,
     every page from one data revision;
  3. the page edge: 999 and 1000 rows serve whole, 1001 refuses, and the pages
     of the 1001 window equal the rows of the two smaller ones;
  4. 100 research-universe tickers over six years (raw close): no duplicate,
     no loss against each ticker's own walk, and every absence inside a
     coverage explained as a no-trade session;
  5. close_adj regressions: BBAS3's 2024 split, MGLU3's grouping and bonus,
     the same level in two windows, the raw close only when selected;
  6. refusals: an unknown ticker, a window before the coverage, a stretch
     close_adj cannot adjust;
  7. IBOV: 2025-12-30 = 161,125.37 and, from 2020, exactly the tape's sessions.

And the rest of the spec's test list (RESEARCH_SEAM.md section 9, #420), each
section isolated so one crash does not hide the others:

  8. the universe: only shares and units (no receipt, BDR, fund or index),
     NATU3 one row with a gap, every issuer-stem link one CNPJ, a rename is
     two rows filtered by as_of;
  9. total return (#418): PETR4's level below close_adj by the cash paid since,
     never above it, the ratio only rising to 1, equal on the latest session;
 10. the benchmark (#412, #415): IBOV from 1968 with exactly the eleven divisor
     steps flagged, no ticker standing in for the index, a long window refused,
     IBOV11 never equal to the official close;
 11. fundamentals as known (#414): as of 2024-02-29 PETR's DFP 2023 is absent
     and no line comes from a filing received on or after the date;
 12. macro: CDI from 2019 in three date-split calls, the whole window refused;
 13. coverage(): the index row names its depth, the quotes row the tape start;
 14. other classes: a fund quota, an index and a BDR have no close_adj (the default
     series refuses, naming the cause) and serve the raw close when it is selected.

Every section is isolated, the first seven too: a crash or a timeout in one is a
FAIL line and the sections after it still run. The no-look-ahead line has its own
section, because its only public source (financial_statement_history) can fail
on its own.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdk"))

from silo_client import SiloClient, SiloError, SiloOverCap  # noqa: E402

START6, END6 = "2020-01-02", "2025-12-30"
TAPE_START = "2019-01-02"
TR_FIELDS = ["close_adj", "close_total_return", "close_total_return_null_reason"]
#: The eleven sessions on which B3 re-scaled IBOV (found in the series, #412).
IBOV_DIVISOR_STEPS = [
    "1983-10-04", "1985-12-03", "1988-08-30", "1989-04-18", "1990-01-15",
    "1991-05-29", "1992-01-22", "1993-01-27", "1993-08-30", "1994-02-10",
    "1997-03-03",
]
problems: List[str] = []


def check(ok: bool, what: str) -> None:
    print(("ok    " if ok else "FAIL  ") + what)
    if not ok:
        problems.append(what)


def refused(fn, reason: str) -> bool:
    try:
        fn()
    except SiloError as exc:
        return reason in exc.body
    return False


def main() -> int:
    silo = SiloClient()
    run_sections(silo)
    run_extras(silo)
    print(f"\n{len(problems)} problem(s)")
    return 1 if problems else 0


def run_sections(silo: Any) -> None:
    """The #410 acceptance list, each section on its own like `run_extras`: a crash
    (or a timeout) in one is a FAIL line and the sections after it still run."""
    ctx: Dict[str, Any] = {}
    for section in (_eter3, _prices_two, _page_edge, _hundred_tickers, _close_adj, _refusals, _ibov, _other_classes):
        try:
            section(silo, ctx)
        except Exception as exc:  # noqa: BLE001 — a crash is a FAIL line, not a traceback
            check(False, f"{section.__name__.lstrip('_')}: stopped by {type(exc).__name__}: {str(exc)[:300]}")


def _tape(silo: Any, ctx: Dict[str, Any]) -> List[str]:
    """PETR4 prints on every session, so its dates are the market calendar (read once)."""
    if "tape" not in ctx:
        ctx["tape"] = [r["trade_date"] for r in silo.quote_history_all("PETR4", TAPE_START, None, fields=["close"])]
    return ctx["tape"]


def _eter3(silo: Any, ctx: Dict[str, Any]) -> None:
    # 1. ETER3 across boards.
    rows = silo.quote_history_all("ETER3", "2019-01-02", "2026-12-31", fields=["close", "board", "prior_no_trade_sessions"])
    boards = {r["board"] for r in rows}
    check({"08", "02"} <= boards and rows[0]["trade_date"] == "2019-01-02",
          f"ETER3 crosses boards {sorted(boards)} from {rows[0]['trade_date'] if rows else None}, {len(rows)} sessions")
    tape = [d for d in _tape(silo, ctx) if d <= rows[-1]["trade_date"]]
    missing = len(tape) - len(rows)
    explained = sum(r["prior_no_trade_sessions"] for r in rows)
    check(missing == explained, f"ETER3: {missing} sessions without a print, {explained} explained as no-trade")


def _prices_two(silo: Any, ctx: Dict[str, Any]) -> None:
    # 2. PETR4 + VALE3 through prices().
    df = silo.prices(["PETR4", "VALE3"], START6, END6)
    dup = df.height - df.unique(["ticker", "trade_date"]).height
    check(dup == 0 and df.columns == ["ticker", "trade_date", "close_adj"],
          f"prices(PETR4, VALE3): {df.height} rows, {dup} duplicates, columns {df.columns}")
    check(df.equals(df.sort(["ticker", "trade_date"])), "prices() is sorted by ticker, trade_date")


def _page_edge(silo: Any, ctx: Dict[str, Any]) -> None:
    # 3. The page edge.
    tape = _tape(silo, ctx)
    d999, d1001 = tape[0], tape[1000]
    # Through the raw page call: the SDK's truncation guard cannot tell a
    # 1000-row answer from a cut one unless the server sends a total.
    def whole(to):
        return silo._rpc("quote_history", {"p_ticker": "PETR4", "p_from": d999, "p_to": to,
                                           "p_fields": ["close"]}, page=True)
    n999, n1000 = len(whole(tape[998])), len(whole(tape[999]))
    check(n999 == 999 and n1000 == 1000, f"999 and 1000 rows serve whole ({n999}, {n1000})")
    check(refused(lambda: silo.quote_history("PETR4", d999, d1001, fields=["close"]), "more than 1000 rows"),
          "1001 rows refuse in whole-result mode")
    paged = silo.quote_history_all("PETR4", d999, d1001, fields=["close"])
    check([r["trade_date"] for r in paged] == tape[:1001], "the 1001 window pages to exactly its sessions")


def absences(names: List[str], big: Any, tape: List[str], walk_dates: Any) -> Tuple[List[str], List[str]]:
    """Split the names into (unexplained, silent) for a pull over START6..END6.

    A name with prints: every session between its first and last print is a print
    or a counted no-trade session (the first row's run starts before START6).
    A name with no print in the window is `silent`, and only when its own full
    walk (`walk_dates(name)`) has no session inside the window either: a ticker
    that traded in 2019 and again in 2026 is a known ticker with an empty window
    (an empty series, not a refusal), while a walk that has sessions the pull lost
    is unexplained."""
    unexplained, silent = [], []
    for t in names:
        sub = big.filter(big["ticker"] == t)
        if sub.height == 0:
            inside = [d for d in walk_dates(t) if START6 <= d <= END6]
            (unexplained if inside else silent).append(t)
            continue
        first, last = str(sub["trade_date"][0]), str(sub["trade_date"][-1])
        span = len([d for d in tape if first <= d <= last])
        if sub.height + int(sub["prior_no_trade_sessions"][1:].sum()) != span:
            unexplained.append(t)
    return unexplained, silent


def _hundred_tickers(silo: Any, ctx: Dict[str, Any]) -> None:
    # 4. 100 tickers over six years.
    tape = _tape(silo, ctx)
    universe = [u for u in silo._rpc("research_universe", {})
                if u["first_observed"] <= START6 and u["last_observed"] >= END6]
    names = sorted({u["ticker"] for u in universe})[:100]
    first_seen = {u["ticker"]: u["first_observed"] for u in universe}
    big = silo.prices(names, START6, END6, fields=["close", "prior_no_trade_sessions"])
    check(big.height == big.unique(["ticker", "trade_date"]).height, f"100 tickers: {big.height} rows, no duplicate")
    unexplained, silent = absences(
        names, big, tape,
        lambda t: [str(r["trade_date"]) for r in silo.quote_history_all(t, first_seen[t], None, fields=["close"])])
    check(not unexplained,
          f"every absence inside the coverage is a no-trade session ({len(unexplained)} unexplained: {unexplained[:5]}; "
          f"{len(silent)} name(s) with no session at all in the window, each confirmed by its own walk: {silent[:5]})")


def _close_adj(silo: Any, ctx: Dict[str, Any]) -> None:
    # 5. close_adj regressions.
    b = {r["trade_date"]: r for r in silo.quote_history("BBAS3", "2024-04-12", "2024-04-17", fields=["close", "close_adj"])}
    check(abs(float(b["2024-04-15"]["close_adj"]) - float(b["2024-04-15"]["close"]) / 2) < 1e-6
          and abs(float(b["2024-04-16"]["close_adj"]) - float(b["2024-04-16"]["close"])) < 1e-6,
          f"BBAS3 split 2024-04-15: {b['2024-04-15']} / {b['2024-04-16']}")
    wide = {r["trade_date"]: r["close_adj"] for r in silo.quote_history("BBAS3", "2024-01-02", "2024-06-28")}
    check(wide["2024-04-15"] == b["2024-04-15"]["close_adj"], "close_adj is the same in two windows")
    m = {r["trade_date"]: r for r in silo.quote_history("MGLU3", "2024-05-20", "2024-05-29", fields=["close", "close_adj"])}
    pre = m["2024-05-24"]
    post = min((r for r in m.values() if r["trade_date"] > "2024-05-24"), key=lambda r: r["trade_date"])
    check(float(pre["close_adj"]) > 5 * float(pre["close"]),
          f"MGLU3 grouping 2024-05-24 lifts the earlier level ({pre['close']} -> {pre['close_adj']}; next {post['close']} -> {post['close_adj']})")
    raw = silo.quote_history("PETR4", "2025-12-01", "2025-12-05", fields=["close"])
    check(bool(raw) and all(set(r) == {"ticker", "trade_date", "close"} for r in raw), "fields=[close] returns the raw close only")


def _refusals(silo: Any, ctx: Dict[str, Any]) -> None:
    # 6. Refusals.
    check(refused(lambda: silo.quote_history("XXXX3", "2025-01-02", "2025-01-10"), "reason=unknown_ticker"), "unknown ticker refused")
    check(refused(lambda: silo.quote_history("PETR4", "2018-06-01", "2019-06-01"), "reason=outside_coverage"), "window before the tape refused")


def _ibov(silo: Any, ctx: Dict[str, Any]) -> None:
    # 7. IBOV.
    tape = _tape(silo, ctx)
    # Paged with the server's cursor directly, so the check needs no SDK
    # wrapper for index_history.
    ibov, after = [], ""
    while True:
        page = silo._rpc("index_history", {"p_index": "IBOV", "p_from": "2020-01-02",
                                           "p_to": tape[-1], "p_after": after}, page=True)
        ibov.extend(page)
        if len(page) < 1000:
            break
        after = str(page[-1]["trade_date"])
    by_date = {r["trade_date"]: r["level"] for r in ibov}
    check(float(by_date.get("2025-12-30", 0)) == 161125.37, f"IBOV 2025-12-30 = {by_date.get('2025-12-30')}")
    tape20 = {d for d in tape if d >= "2020-01-02"}
    check(set(by_date) == tape20, f"IBOV sessions equal the tape's from 2020 ({len(by_date)} vs {len(tape20)})")


#: One ticker per class the research universe leaves out (spec section 3, items 4 and 5, as
#: built 2026-09-30): the adjusted close is refused with its cause, never NULL and never the raw close.
OTHER_CLASSES = (("BOVA11", "fund_quota"), ("IBOV11", "index"), ("AAPL34", "bdr"))


def _other_classes(silo: Any, ctx: Dict[str, Any]) -> None:
    # 8. Other classes.
    for ticker, asset_class in OTHER_CLASSES:
        check(refused(lambda t=ticker: silo.quote_history(t, "2025-12-01", "2025-12-05"),
                      "cause=outside research universe"),
              f"other classes: {ticker} ({asset_class}) has no close_adj, the default series refuses naming the cause")
        raw = silo.quote_history(ticker, "2025-12-01", "2025-12-05", fields=["close", "asset_class"])
        check(len(raw) > 0 and {r.get("asset_class") for r in raw} == {asset_class},
              f"other classes: {ticker} raw close is served when selected (asset_class "
              f"{sorted({str(r.get('asset_class')) for r in raw})}, {len(raw)} rows)")


# --- the rest of the spec's test list (#420) ---------------------------------

def _today() -> dt.date:
    return dt.date.today()


def _num(x: Any) -> Optional[float]:
    return None if x is None else float(x)


def _business_days(a: str, b: str) -> float:
    d0, d1 = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    return max((d1 - d0).days, 0) * 5 / 7


def run_extras(silo: Any) -> None:
    """Each section on its own: a crash in one is a FAIL line, and the rest run."""
    for section in (_universe, _total_return, _benchmark, _as_of, _as_of_leak, _macro, _coverage):
        try:
            section(silo)
        except Exception as exc:  # noqa: BLE001 — reported as a FAIL line, never swallowed
            check(False, f"{section.__name__.lstrip('_')}: stopped by {type(exc).__name__}: {str(exc)[:300]}")


def _universe(silo: Any) -> None:
    rows = silo.research_universe()
    check(300 <= len(rows) <= 1000, f"universe: {len(rows)} ticker+ISIN pairs, inside one 1,000-row page")
    outside = [r["ticker"] for r in rows if str(r["isin"])[6:9] not in ("ACN", "CDA", "UNT")]
    check(not outside, "universe: only shares and units, no receipt, BDR, fund or index"
          + (f" (outside the rule: {outside[:8]})" if outside else ""))
    check(not ({"BOVA11", "IBOV11"} & {r["ticker"] for r in rows}), "universe: BOVA11 and IBOV11 are not in it")
    natu = [r for r in rows if r["ticker"] == "NATU3"]
    span = _business_days(str(natu[0]["first_observed"]), str(natu[0]["last_observed"])) if len(natu) == 1 else 0
    check(len(natu) == 1 and natu[0]["n_sessions"] < 0.6 * span,
          f"universe: NATU3 is {len(natu)} row(s), n_sessions {natu[0]['n_sessions'] if natu else None} "
          f"against about {span:.0f} business days of span")
    stem_rows = {str(r["ticker"])[:4] for r in rows if r.get("cnpj_basis") == "fca_issuer_stem"}
    cnpjs: Dict[str, set] = {}
    for r in rows:
        if r.get("cnpj"):
            cnpjs.setdefault(str(r["ticker"])[:4], set()).add(r["cnpj"])
    many = {k: sorted(v) for k, v in cnpjs.items() if k in stem_rows and len(v) > 1}
    check(not many, f"universe: {len(stem_rows)} fca_issuer_stem stems, each with one CNPJ"
          + (f" (more than one: {many})" if many else ""))
    on_old = {r["ticker"] for r in silo.research_universe(as_of="2025-11-07")}
    on_new = {r["ticker"] for r in silo.research_universe(as_of="2025-11-10")}
    isins = {r["ticker"]: r["isin"] for r in rows if r["ticker"] in ("ELET3", "AXIA3")}
    check("ELET3" in on_old and "AXIA3" not in on_old and "AXIA3" in on_new and "ELET3" not in on_new
          and len(set(isins.values())) == 2,
          f"universe: a rename is two rows, ELET3 until 2025-11-07 and AXIA3 from 2025-11-10 ({isins})")


def _total_return(silo: Any) -> None:
    pin = silo.quote_history("PETR4", "2023-12-28", "2023-12-28", fields=TR_FIELDS)
    tr = _num(pin[0].get("close_total_return")) if len(pin) == 1 else None
    adj = _num(pin[0].get("close_adj")) if len(pin) == 1 else None
    if tr is None or not adj:
        why = pin[0].get("close_total_return_null_reason") if len(pin) == 1 else f"{len(pin)} rows"
        check(False, f"total return: PETR4 2023-12-28 has no level ({why})")
    else:
        ratio = tr / adj
        check(0.55 <= ratio <= 0.80, f"total return: PETR4 2023-12-28 is {ratio:.4f} of close_adj "
              "(0.6875 on 2026-09-30; it moves as distributions land)")
    rows = silo.quote_history_all("PETR4", TAPE_START, None, fields=TR_FIELDS)
    both = [(str(r["trade_date"]), _num(r["close_total_return"]), _num(r["close_adj"])) for r in rows
            if r.get("close_total_return") is not None and r.get("close_adj") is not None]
    if len(both) < 1000:
        check(False, f"total return: only {len(both)} of {len(rows)} PETR4 sessions carry both levels")
        return
    # Levels carry 6 decimals each, so a ratio is only known to about 1e-7: the
    # tolerances sit far above that and far below the 0.5% a real distribution moves it.
    above = [d for d, t, a in both if t > a * (1 + 1e-6)]
    ratios = [t / a for _, t, a in both]
    falls = [both[i + 1][0] for i in range(len(ratios) - 1) if ratios[i + 1] < ratios[i] * (1 - 1e-4)]
    gap = abs(both[-1][1] - both[-1][2])
    check(not above and not falls and gap < 1e-4,
          f"total return: {len(both)} PETR4 sessions, never above close_adj ({len(above)} above), the ratio "
          f"never falls ({len(falls)} falls), equal on the latest session (gap {gap:.1e})")


def _benchmark(silo: Any) -> None:
    today = _today().isoformat()
    ibov = silo.index_history_all("IBOV", "1968-01-02", today)
    dates = [str(r["trade_date"]) for r in ibov]
    steps = [str(r["trade_date"]) for r in ibov if r["divisor_step"]]
    check(len(ibov) >= 14000 and dates == sorted(set(dates)) and dates[:1] == ["1968-01-02"]
          and steps == IBOV_DIVISOR_STEPS,
          f"benchmark: IBOV {len(ibov)} sessions from {dates[0] if dates else None}, unique and ordered, "
          f"{len(steps)} divisor steps flagged (expected {len(IBOV_DIVISOR_STEPS)})")
    flagged = [str(r["trade_date"]) for r in silo.index_history("IBOV", "1997-02-28", "1997-03-03") if r["divisor_step"]]
    check(flagged == ["1997-03-03"], f"benchmark: the 1997-03-03 step is flagged and the session before is not ({flagged})")
    for code in ("BOVA11", "IBOV11", "PETR4"):
        check(refused(lambda c=code: silo.index_history(c), "22023"),
              f"benchmark: index_history refuses {code}, a ticker never stands in for the index")
    try:
        silo.index_history("IBOV", "1968-01-02", today)
        capped = False
    except SiloOverCap:
        capped = True
    check(capped, "benchmark: a 14,000-row window refuses instead of trimming")
    # The test is the price, not how often it prints: IBOV11 was monthly through
    # 2024 and is on nearly every session since December 2025.
    start = max(TAPE_START, (_today() - dt.timedelta(days=400)).isoformat())
    prints = silo.quote_history_all("IBOV11", start, today, fields=["close", "asset_class"])
    levels = {str(r["trade_date"]): _num(r["level"]) for r in silo.index_history_all("IBOV", start, today)}
    shared = [(_num(r["close"]), levels[str(r["trade_date"])]) for r in prints if str(r["trade_date"]) in levels]
    classes = {r.get("asset_class") for r in prints}
    equal = [1 for a, b in shared if abs(a - b) < 0.5]
    check(classes == {"index"} and len(shared) >= 20 and not equal,
          f"benchmark: IBOV11 (asset_class {sorted(map(str, classes))}) printed on {len(prints)} sessions since {start}, "
          f"{len(shared)} shared with the official close, {len(equal)} equal it: a settlement index, never the benchmark")


def _as_of(silo: Any) -> None:
    window = dict(start="2023-01-01", end="2024-06-30")
    t = "2024-02-29"
    rows = silo.financials("PETR4", "DRE", as_of=t, **window)
    refs = sorted({str(r["ref_date"]) for r in rows})
    check(bool(refs) and refs[-1] == "2023-09-30" and "2023-12-31" not in refs,
          f"as-of: as of {t} PETR's newest period is {refs[-1] if refs else None} and the DFP 2023 is absent")
    latest = {str(r["ref_date"]) for r in silo.financials("PETR4", "DRE", **window)}
    check("2023-12-31" in latest, "as-of: without as_of the DFP 2023 is read at its latest version (not point-in-time)")
    for name, call in (("company_financials", silo.company_financials), ("income_statements", silo.income_statements)):
        got = {str(r["ref_date"]) for r in call("PETR4", as_of=t, **window)}
        check(bool(got) and "2023-12-31" not in got, f"as-of: {name} honours as_of ({sorted(got)})")


def _as_of_leak(silo: Any) -> None:
    """No line comes from a filing received on or after the date. Its own section:
    the only public source of `filing_received_date` is financial_statement_history,
    and a failure to read it (a 504 on 2026-10-03) must not hide the other as-of lines."""
    window = dict(start="2023-01-01", end="2024-06-30")
    t = "2024-02-29"
    rows = silo.financials("PETR4", "DRE", as_of=t, **window)
    received = {(str(h["ref_date"]), h["doc_type"], h["version"]): h.get("filing_received_date")
                for h in silo.financial_statement_history("PETR4", "DRE", **window)}
    leaks = [k for k in ((str(r["ref_date"]), r["doc_type"], r["version"]) for r in rows)
             if received.get(k) is None or str(received[k]) >= t]
    check(bool(rows) and not leaks, f"as-of: {len(rows)} lines, none from a filing received on or after {t}"
          + (f" ({len(leaks)} leaks, first {leaks[0]})" if leaks else ""))


def _macro(silo: Any) -> None:
    today = _today().isoformat()
    spans = [("2019-01-01", "2021-12-31"), ("2022-01-01", "2024-12-31"), ("2025-01-01", today)]
    dates: List[str] = []
    for a, b in spans:
        dates += [str(r["reference_date"]) for r in silo.macro_series("CDI", a, b)]
    check(len(dates) > 1500 and dates == sorted(set(dates)),
          f"macro: CDI from 2019 in {len(spans)} date-split calls, {len(dates):,} rows, unique and ordered")
    try:
        silo.macro_series("CDI", "2019-01-01", today)
        capped = False
    except SiloOverCap:
        capped = True
    check(capped, "macro: the whole seven-year window refuses, so the caller splits by date")


def _coverage(silo: Any) -> None:
    rows = {r["dataset"]: r for r in silo.coverage()}
    index = (rows.get("index_history") or {}).get("notes") or ""
    quotes = (rows.get("quotes") or {}).get("notes") or ""
    check("IBOV from 1968-01-02" in index, f"coverage: the index_history row names its depth ({index[:60]!r})")
    check(TAPE_START in quotes, f"coverage: the quotes row names the tape start ({quotes[:60]!r})")


if __name__ == "__main__":
    raise SystemExit(main())
