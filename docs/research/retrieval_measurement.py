"""Measure a research-sized retrieval on SILO's public interface (wayfinder #376).

Read-only. Uses only the public SDK (`sdk/silo_client`) and the publishable key
published in `skill.md`, i.e. exactly what an external research caller has.

    pip install -e sdk/
    python docs/research/retrieval_measurement.py [--workers 1] [--n 100] [--years 10]

Every request is timed. Refusals (22023 over-cap), timeouts (57014) and
rate limiting (HTTP 429) are recorded, never retried silently. Results go to
stdout as JSON so the build phase can diff runs.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from silo_client import SiloClient, SiloError, SiloOverCap, SiloTimeout

URL = "https://zcjbtpxuhdekpwcxmepn.supabase.co"
KEY = "sb_publishable__yfFQsykAglrvc9GS6_PYw_B24ex437"  # public, from skill.md


class Meter:
    """Counts every HTTP request the SDK makes, with status and latency."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def hook(self, client: SiloClient) -> None:
        http = client._http

        def on_request(req: httpx.Request) -> None:
            req.extensions["t0"] = time.perf_counter()

        def on_response(resp: httpx.Response) -> None:
            t0 = resp.request.extensions.get("t0", time.perf_counter())
            resp.read()
            self.calls.append({
                "path": resp.request.url.path.rsplit("/", 1)[-1],
                "status": resp.status_code,
                "ms": round((time.perf_counter() - t0) * 1000),
                "code": _sqlstate(resp),
            })

        http.event_hooks["request"].append(on_request)
        http.event_hooks["response"].append(on_response)


def _sqlstate(resp: httpx.Response) -> str | None:
    if resp.status_code < 400:
        return None
    try:
        return resp.json().get("code")
    except ValueError:
        return f"http{resp.status_code}"


def pick_universe(s: SiloClient, n: int) -> tuple[str, list[dict]]:
    """Today's n most-traded equity + unit tickers, from the public views.

    Survivorship-biased on purpose: this measures cost, not a universe.
    """
    last = s.view("equities", select="trade_date", ticker="eq.PETR4",
                  lot="eq.standard", order="trade_date.desc", limit=1)[0]["trade_date"]
    rows: list[dict] = []
    for v in ("equities", "units"):
        rows += s.view(v, select="ticker,volume", trade_date=f"eq.{last}",
                       lot="eq.standard", board="eq.02", order="volume.desc", limit=n)
    rows.sort(key=lambda r: r["volume"] or 0, reverse=True)
    return last, rows[:n]


def one_ticker(s: SiloClient, ticker: str, start: str, end: str) -> dict:
    t0 = time.perf_counter()
    try:
        rows = s.quote_history_all(ticker, start=start, end=end)
        err = None
    except (SiloOverCap, SiloTimeout, SiloError) as e:
        rows, err = [], f"{type(e).__name__}: {str(e)[:160]}"
    dates = [r["trade_date"] for r in rows]
    return {
        "ticker": ticker, "rows": len(rows),
        "pages": len(rows) // 1000 + 1 if not err else None,
        "first": min(dates) if dates else None, "last": max(dates) if dates else None,
        "dup_dates": len(dates) - len(set(dates)),
        "s": round(time.perf_counter() - t0, 2), "error": err,
    }


def quotes(s: SiloClient, tickers: list[str], start: str, end: str, workers: int) -> dict:
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        per = list(ex.map(lambda t: one_ticker(s, t, start, end), tickers))
    return {"workers": workers, "wall_s": round(time.perf_counter() - t0, 1),
            "rows": sum(p["rows"] for p in per),
            "errors": [p for p in per if p["error"]], "per_ticker": per}


def macro_cdi(s: SiloClient, start: dt.date, end: dt.date) -> dict:
    """CDI over the whole window in one call, then split by hand until it fits."""
    out: dict = {"attempts": []}
    for years in (15, 8, 4, 3):
        t0 = time.perf_counter()
        chunks, rows, err = [], 0, None
        a = start
        while a <= end:
            b = min(dt.date(a.year + years, a.month, a.day) - dt.timedelta(days=1), end)
            chunks.append((a, b))
            a = b + dt.timedelta(days=1)
        try:
            got = [s.macro_series("CDI", start=a, end=b) for a, b in chunks]
            rows = sum(len(g) for g in got)
            dates = [r["reference_date"] for g in got for r in g]
            first, last = (min(dates), max(dates)) if dates else (None, None)
        except (SiloOverCap, SiloTimeout, SiloError) as e:
            err, first, last = f"{type(e).__name__}: {str(e)[:200]}", None, None
        out["attempts"].append({"chunk_years": years, "planned_calls": len(chunks), "rows": rows,
                                "first": first, "last": last,
                                "s": round(time.perf_counter() - t0, 2), "error": err})
        if not err:
            break
    return out


def fundamentals(s: SiloClient, ticker: str, start: str, end: str) -> dict:
    """Every statement for one company over the whole window.

    What a caller must do today: ask for the window, and on a refusal (22023)
    or a timeout (57014) halve it and ask again, down to a 31-day floor.
    """
    out = []
    for st in ("BPA", "BPP", "DRE", "DFC_MI", "DFC_MD", "DVA", "DMPL", "DRA"):
        t0 = time.perf_counter()
        tally = {"calls": 0, "rows": 0, "refused": 0, "timeouts": 0, "errors": []}

        def fetch(a: dt.date, b: dt.date) -> None:
            tally["calls"] += 1
            try:
                tally["rows"] += len(s.financial_statement_history(ticker, st, start=a, end=b))
                return
            except SiloOverCap:
                tally["refused"] += 1
            except SiloTimeout:
                tally["timeouts"] += 1
            except SiloError as e:
                tally["errors"].append(f"{a}..{b}: {str(e)[:120]}")
                return
            if (b - a).days <= 31:
                tally["errors"].append(f"{a}..{b}: still failing at the 31-day floor")
                return
            mid = a + (b - a) / 2
            fetch(a, mid)
            fetch(mid + dt.timedelta(days=1), b)

        fetch(dt.date.fromisoformat(start), dt.date.fromisoformat(end))
        out.append({"statement": st, **tally, "s": round(time.perf_counter() - t0, 2)})
    return {"ticker": ticker, "statements": out}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--years", type=int, default=10)
    ap.add_argument("--skip", default="", help="comma list: quotes,cdi,fund,ibov")
    a = ap.parse_args()
    skip = set(filter(None, a.skip.split(",")))

    meter = Meter()
    s = SiloClient(url=URL, key=KEY, retries=0)
    meter.hook(s)
    t0 = time.perf_counter()

    last, uni = pick_universe(s, a.n)
    end = dt.date.fromisoformat(last)
    start = dt.date(end.year - a.years, end.month, end.day) + dt.timedelta(days=1)
    res: dict = {"run_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                 "last_trade_date": last, "window": [start.isoformat(), last],
                 "universe": [u["ticker"] for u in uni]}

    if "quotes" not in skip:
        res["quotes"] = quotes(s, res["universe"], start.isoformat(), last, a.workers)
    if "ibov" not in skip:
        res["ibov11"] = one_ticker(s, "IBOV11", start.isoformat(), last)
    if "cdi" not in skip:
        res["cdi"] = macro_cdi(s, dt.date(end.year - 15, end.month, end.day), end)
    if "fund" not in skip:
        res["fundamentals"] = fundamentals(s, "PETR4", "2019-01-01", last)

    calls = meter.calls
    ms = sorted(c["ms"] for c in calls)
    res["http"] = {
        "requests": len(calls),
        "by_status": {str(k): sum(1 for c in calls if c["status"] == k)
                      for k in sorted({c["status"] for c in calls})},
        "by_code": {k: sum(1 for c in calls if c["code"] == k)
                    for k in sorted({c["code"] for c in calls if c["code"]})},
        "rate_limited_429": sum(1 for c in calls if c["status"] == 429),
        "latency_ms_p50": ms[len(ms) // 2] if ms else None,
        "latency_ms_p95": ms[int(len(ms) * .95)] if ms else None,
        "latency_ms_max": ms[-1] if ms else None,
        "by_path": {p: sum(1 for c in calls if c["path"] == p)
                    for p in sorted({c["path"] for c in calls})},
    }
    res["total_wall_s"] = round(time.perf_counter() - t0, 1)
    json.dump(res, sys.stdout, indent=1, default=str)


if __name__ == "__main__":
    main()
