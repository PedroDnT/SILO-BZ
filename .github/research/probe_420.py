"""THROWAWAY probe for #420 (research/verify-420, never merged). Public SDK only, read-only.

Finds out why section 4 of scripts/verify_research_seam.py stopped with an IndexError,
runs the sections that crash hid (5, 6, 7), times financial_statement_history, and
probes the 'other classes' requirement. Aggregates only."""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "sdk"))
import verify_research_seam as v  # noqa: E402
from silo_client import SiloClient, SiloError  # noqa: E402

silo = SiloClient()
check = v.check
START6, END6 = v.START6, v.END6


def section(name, fn):
    print(f"--- {name}")
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        check(False, f"{name}: stopped by {type(exc).__name__}: {str(exc)[:300]}")


def s4():
    allu = silo._rpc("research_universe", {})
    universe = [u for u in allu if u["first_observed"] <= START6 and u["last_observed"] >= END6]
    names = sorted({u["ticker"] for u in universe})[:100]
    print(f"universe pairs {len(allu)}, candidates {len(universe)}, names {len(names)}")
    tape = [r["trade_date"] for r in silo.quote_history_all("PETR4", "2019-01-02", None, fields=["close"])]
    big = silo.prices(names, START6, END6, fields=["close", "prior_no_trade_sessions"])
    empties = [t for t in names if big.filter(big["ticker"] == t).height == 0]
    print(f"names with zero rows in {START6}..{END6}: {len(empties)}")
    for t in empties:
        for u in allu:
            if u["ticker"] == t:
                print("  EMPTY", t, u["isin"], u["first_observed"], u["last_observed"], u["n_sessions"], u.get("cnpj_basis"))
    unexplained = []
    for t in names:
        sub = big.filter(big["ticker"] == t)
        if sub.height == 0:
            continue
        first, last = str(sub["trade_date"][0]), str(sub["trade_date"][-1])
        span = len([d for d in tape if first <= d <= last])
        if sub.height + int(sub["prior_no_trade_sessions"][1:].sum()) != span:
            unexplained.append(t)
    check(not unexplained, f"s4 (empties skipped): every absence inside the coverage is a no-trade session ({len(unexplained)} unexplained: {unexplained[:5]})")


def s5():
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


def s6():
    check(v.refused(lambda: silo.quote_history("XXXX3", "2025-01-02", "2025-01-10"), "reason=unknown_ticker"), "unknown ticker refused")
    check(v.refused(lambda: silo.quote_history("PETR4", "2018-06-01", "2019-06-01"), "reason=outside_coverage"), "window before the tape refused")


def s7():
    tape = [r["trade_date"] for r in silo.quote_history_all("PETR4", "2019-01-02", None, fields=["close"])]
    ibov, after = [], ""
    while True:
        page = silo._rpc("index_history", {"p_index": "IBOV", "p_from": "2020-01-02", "p_to": tape[-1], "p_after": after}, page=True)
        ibov.extend(page)
        if len(page) < 1000:
            break
        after = str(page[-1]["trade_date"])
    by_date = {r["trade_date"]: r["level"] for r in ibov}
    check(float(by_date.get("2025-12-30", 0)) == 161125.37, f"IBOV 2025-12-30 = {by_date.get('2025-12-30')}")
    tape20 = {d for d in tape if d >= "2020-01-02"}
    check(set(by_date) == tape20, f"IBOV sessions equal the tape's from 2020 ({len(by_date)} vs {len(tape20)}); only in IBOV {len(set(by_date)-tape20)}, only in tape {len(tape20-set(by_date))}")


def fsh():
    for i in range(3):
        t0 = time.time()
        try:
            rows = silo.financial_statement_history("PETR4", "DRE", start="2023-01-01", end="2024-06-30")
            print(f"financial_statement_history try {i}: {len(rows)} rows in {time.time()-t0:.1f}s")
        except Exception as exc:  # noqa: BLE001
            print(f"financial_statement_history try {i}: {type(exc).__name__} after {time.time()-t0:.1f}s: {str(exc)[:160]}")
    t0 = time.time()
    rows = silo.financials("PETR4", "DRE", as_of="2024-02-29", start="2023-01-01", end="2024-06-30")
    print(f"financials(as_of) {len(rows)} rows in {time.time()-t0:.1f}s")


def classes():
    for t in ("BOVA11", "IBOV11", "AAPL34", "XPLG11", "PETR4"):
        for fields in (None, ["close", "asset_class"]):
            try:
                r = silo.quote_history(t, "2025-12-01", "2025-12-05", fields=fields)
                print(f"  {t} fields={fields}: {len(r)} rows, first {r[0] if r else None}")
            except SiloError as exc:
                print(f"  {t} fields={fields}: REFUSED {str(exc.body)[:200]}")


for name, fn in (("s4", s4), ("s5", s5), ("s6", s6), ("s7", s7), ("fsh", fsh), ("classes", classes)):
    section(name, fn)
print(f"\n{len(v.problems)} problem(s)")
