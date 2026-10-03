"""Read-only probe of B3's index statistics endpoint for issue #416.

THROWAWAY (branch research/indices-416, never merged). It reads B3's public
GetPortfolioDay endpoint for each candidate index and prints aggregates to the
job log: depth, gaps, year-end closes, the real parse_year / mark_divisor_steps
verdict, and a listing probe. No secrets, no database, no writes.
"""

from __future__ import annotations

import base64
import json
import sys
import time
from collections import defaultdict
from datetime import date
from decimal import Decimal

sys.path.insert(0, ".")

import requests  # noqa: E402

from src.fetchers import b3_index_fetcher as f  # noqa: E402
from src.pipeline import ingest_b3_index as idx  # noqa: E402

CANDIDATES = ["IBOV", "IBXX", "IBXL", "SMLL", "IFIX", "IDIV", "IEEX", "ICON", "IMOB", "UTIL"]
LAST_YEAR = date.today().year
FIRST_TRY = 1960

fetcher = f.B3IndexFetcher(sleep_between=0.3)


def p(*a):
    print(*a, flush=True)


def listing_probe() -> None:
    """Try the sibling endpoint the index page may use to list its codes."""
    for path, payload in [
        ("https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall/GetStockIndex", {"language": "pt-br"}),
        ("https://sistemaswebb3-listados.b3.com.br/indexStatisticsProxy/IndexCall/GetStockIndex", {"language": "pt-br"}),
    ]:
        tok = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
        url = f"{path}/{tok}"
        try:
            r = requests.get(url, headers=f._HEADERS, timeout=40)
            p(f"LISTING {path} -> HTTP {r.status_code}, {len(r.text)} bytes")
            p("  head:", r.text[:2500].replace("\n", " "))
        except Exception as exc:  # noqa: BLE001
            p(f"LISTING {path} failed: {exc!r}")


def probe(code: str) -> dict:
    sessions: dict[date, Decimal] = {}
    null_years: list[int] = []
    first_year = None
    errors: list[str] = []
    for year in range(FIRST_TRY, LAST_YEAR + 1):
        try:
            payload = fetcher.fetch_year(code, year)
        except f.B3IndexNoResults:
            if first_year is not None:
                null_years.append(year)
            time.sleep(0.15)
            continue
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{year}: {exc!r}")
            continue
        if first_year is None:
            first_year = year
        try:
            for r in idx.parse_year(code, year, payload):
                sessions[r["trade_date"]] = r["level"]
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{year} parse_year: {exc!r}")
        time.sleep(0.3)
    return {"sessions": sessions, "null_years": null_years, "first_year": first_year, "errors": errors}


def report(code: str, res: dict, ibov_dates: set[date] | None) -> None:
    s = res["sessions"]
    p(f"\n===== {code} =====")
    if not s:
        p("NO SESSIONS", res["errors"][:5])
        return
    dates = sorted(s)
    p(f"first_year_with_results={res['first_year']} first_date={dates[0]} first_level={s[dates[0]]}")
    p(f"last_date={dates[-1]} last_level={s[dates[-1]]} n_sessions={len(dates)}")
    p(f"null_years_after_first={res['null_years']} errors={res['errors'][:5]}")
    p("first 5:", [(str(d), str(s[d])) for d in dates[:5]])
    p("last 5:", [(str(d), str(s[d])) for d in dates[-5:]])
    big = [(str(a), str(b), (b - a).days) for a, b in zip(dates, dates[1:]) if (b - a).days > 10]
    p(f"gaps_gt_10_calendar_days={len(big)}", big[:30])
    per = defaultdict(int)
    for d in dates:
        per[d.year] += 1
    p("sessions_per_year:", dict(sorted(per.items())))
    last_of_year: dict[int, date] = {}
    for d in dates:
        last_of_year[d.year] = d
    p("year_end_closes:", {y: (str(d), str(s[d])) for y, d in sorted(last_of_year.items())})
    if ibov_dates is not None:
        lo, hi = dates[0], dates[-1]
        ib = {d for d in ibov_dates if lo <= d <= hi}
        mine = set(dates)
        only_ibov = sorted(ib - mine)
        only_mine = sorted(mine - ib)
        p(f"vs_IBOV within span: ibov_sessions={len(ib)} missing_here={len(only_ibov)} extra_here={len(only_mine)}")
        p("  missing_here sample:", [str(d) for d in only_ibov[:15]], "... last", [str(d) for d in only_ibov[-5:]])
        p("  extra_here sample:", [str(d) for d in only_mine[:15]], "... last", [str(d) for d in only_mine[-5:]])
    moves = []
    for a, b in zip(dates, dates[1:]):
        ratio = float(s[b] / s[a])
        if ratio < 0.8 or ratio > 1.25:
            moves.append((str(b), round(ratio, 4)))
    p(f"one_session_moves_outside_0.8_1.25: n={len(moves)}", moves[:40])
    recs = [{"index_code": code, "trade_date": d, "level": s[d], "divisor_step": False} for d in dates]
    try:
        idx.mark_divisor_steps(code, recs)
        p("mark_divisor_steps: OK")
    except Exception as exc:  # noqa: BLE001
        p("mark_divisor_steps RAISED:", repr(exc))


def main() -> None:
    p("today", date.today(), "probing", CANDIDATES)
    listing_probe()
    results = {}
    ibov_dates = None
    for code in CANDIDATES:
        results[code] = probe(code)
        if code == "IBOV":
            ibov_dates = set(results[code]["sessions"])
        report(code, results[code], None if code == "IBOV" else ibov_dates)
    p("\n===== check dates =====")
    for d in [date(2025, 12, 30), date(2025, 12, 29), date(2024, 12, 30), date(2023, 12, 29), date(2022, 12, 30)]:
        p(str(d), {c: str(results[c]["sessions"].get(d)) for c in CANDIDATES})


if __name__ == "__main__":
    main()
