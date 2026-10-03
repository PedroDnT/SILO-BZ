"""Third read-only probe for issue #416: how often does B3's endpoint answer
results=null for a year it does serve? (UTIL 2012 did once, then answered twice.)

THROWAWAY (branch research/indices-416, never merged). No secrets, no writes.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date

sys.path.insert(0, ".")

import requests  # noqa: E402

from src.fetchers import b3_index_fetcher as f  # noqa: E402

FIRST = {"IBOV": 1968, "IBXX": 1994, "IBXL": 1997, "SMLL": 2005, "IFIX": 2010,
         "IDIV": 2005, "IEEX": 1994, "ICON": 2006, "IMOB": 2007, "UTIL": 2005}
PASSES = 3
LAST = date.today().year


def p(*a):
    print(*a, flush=True)


def raw(code: str, year: int):
    url = f"{f.BASE_URL}/GetPortfolioDay/{f.B3IndexFetcher._token(code, year)}"
    r = requests.get(url, headers=f._HEADERS, timeout=40)
    r.raise_for_status()
    body = r.text.strip()
    if not body:
        return "empty"
    data = json.loads(body)
    return "null" if data.get("results") is None else "ok"


def main() -> None:
    p("today", date.today(), "passes", PASSES)
    total = {"ok": 0, "null": 0, "empty": 0, "error": 0}
    events = []
    for n in range(1, PASSES + 1):
        for code, first in FIRST.items():
            for year in range(first, LAST + 1):
                try:
                    res = raw(code, year)
                except Exception as exc:  # noqa: BLE001
                    res = "error"
                    events.append((n, code, year, f"error {exc!r}"))
                total[res] += 1
                if res in ("null", "empty"):
                    again = []
                    for _ in range(3):
                        time.sleep(1.5)
                        try:
                            again.append(raw(code, year))
                        except Exception as exc:  # noqa: BLE001
                            again.append(f"error {exc!r}")
                    events.append((n, code, year, f"{res}; retries={again}"))
                    p(f"pass {n} {code} {year}: {res}; retries={again}")
                time.sleep(0.25)
        p(f"-- pass {n} done: totals so far {total}")
    p("\nTOTALS", total, "requests", sum(total.values()))
    p("EVENTS", events)


if __name__ == "__main__":
    main()
