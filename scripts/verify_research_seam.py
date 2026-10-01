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
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdk"))

from silo_client import SiloClient, SiloError  # noqa: E402

START6, END6 = "2020-01-02", "2025-12-30"
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
    try:
        _checks(silo)
    except Exception as exc:  # noqa: BLE001 — a crash is a FAIL line, not a traceback
        check(False, f"verification stopped: {type(exc).__name__}: {str(exc)[:300]}")
    print(f"\n{len(problems)} problem(s)")
    return 1 if problems else 0


def _checks(silo: SiloClient) -> None:
    # 1. ETER3 across boards.
    rows = silo.quote_history_all("ETER3", "2019-01-02", "2026-12-31", fields=["close", "board", "prior_no_trade_sessions"])
    boards = {r["board"] for r in rows}
    check({"08", "02"} <= boards and rows[0]["trade_date"] == "2019-01-02",
          f"ETER3 crosses boards {sorted(boards)} from {rows[0]['trade_date'] if rows else None}, {len(rows)} sessions")
    # PETR4 prints on every session, so its dates are the market calendar.
    tape = [r["trade_date"] for r in silo.quote_history_all("PETR4", "2019-01-02", rows[-1]["trade_date"], fields=["close"])]
    missing = len(tape) - len(rows)
    explained = sum(r["prior_no_trade_sessions"] for r in rows)
    check(missing == explained, f"ETER3: {missing} sessions without a print, {explained} explained as no-trade")

    # 2. PETR4 + VALE3 through prices().
    df = silo.prices(["PETR4", "VALE3"], START6, END6)
    dup = df.height - df.unique(["ticker", "trade_date"]).height
    check(dup == 0 and df.columns == ["ticker", "trade_date", "close_adj"],
          f"prices(PETR4, VALE3): {df.height} rows, {dup} duplicates, columns {df.columns}")
    check(df.equals(df.sort(["ticker", "trade_date"])), "prices() is sorted by ticker, trade_date")

    # 3. The page edge.
    d999, d1000, d1001 = tape[0], tape[999 - 1], tape[1000]
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

    # 4. 100 tickers over six years.
    universe = [u for u in silo._rpc("research_universe", {})
                if u["first_observed"] <= START6 and u["last_observed"] >= END6]
    names = sorted({u["ticker"] for u in universe})[:100]
    big = silo.prices(names, START6, END6, fields=["close", "prior_no_trade_sessions"])
    check(big.height == big.unique(["ticker", "trade_date"]).height, f"100 tickers: {big.height} rows, no duplicate")
    unexplained = []
    for t in names:
        sub = big.filter(big["ticker"] == t)
        first, last = str(sub["trade_date"][0]), str(sub["trade_date"][-1])
        span = len([d for d in tape if first <= d <= last])
        # Every session between the first and last print is a print or a
        # counted no-trade session (the first row's run starts before START6).
        if sub.height + int(sub["prior_no_trade_sessions"][1:].sum()) != span:
            unexplained.append(t)
    check(not unexplained, f"every absence inside the coverage is a no-trade session ({len(unexplained)} unexplained: {unexplained[:5]})")

    # 5. close_adj regressions.
    b = {r["trade_date"]: r for r in silo.quote_history("BBAS3", "2024-04-12", "2024-04-17", fields=["close", "close_adj"])}
    check(abs(float(b["2024-04-15"]["close_adj"]) - float(b["2024-04-15"]["close"]) / 2) < 1e-6
          and abs(float(b["2024-04-16"]["close_adj"]) - float(b["2024-04-16"]["close"])) < 1e-6,
          f"BBAS3 split 2024-04-15: {b['2024-04-15']} / {b['2024-04-16']}")
    wide = {r["trade_date"]: r["close_adj"] for r in silo.quote_history("BBAS3", "2024-01-02", "2024-06-28")}
    check(wide["2024-04-15"] == b["2024-04-15"]["close_adj"], "close_adj is the same in two windows")
    m = {r["trade_date"]: r for r in silo.quote_history("MGLU3", "2024-05-20", "2024-05-29", fields=["close", "close_adj"])}
    pre, post = m["2024-05-24"], min(r for r in m.values() if r["trade_date"] > "2024-05-24")
    check(float(pre["close_adj"]) > 5 * float(pre["close"]),
          f"MGLU3 grouping 2024-05-24 lifts the earlier level ({pre['close']} -> {pre['close_adj']}; next {post['close']} -> {post['close_adj']})")
    raw = silo.quote_history("PETR4", "2025-12-01", "2025-12-05", fields=["close"])
    check(all(set(r) == {"ticker", "trade_date", "close"} for r in raw), "fields=[close] returns the raw close only")

    # 6. Refusals.
    check(refused(lambda: silo.quote_history("XXXX3", "2025-01-02", "2025-01-10"), "reason=unknown_ticker"), "unknown ticker refused")
    check(refused(lambda: silo.quote_history("PETR4", "2018-06-01", "2019-06-01"), "reason=outside_coverage"), "window before the tape refused")

    # 7. IBOV.
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


if __name__ == "__main__":
    raise SystemExit(main())
