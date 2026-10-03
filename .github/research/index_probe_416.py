"""Second read-only probe of B3's index statistics endpoint for issue #416.

THROWAWAY (branch research/indices-416, never merged). Targeted dates and the
two anomalies the first run found (UTIL 2012 null, IEEX March 1999). No
secrets, no database, no writes.
"""

from __future__ import annotations

import base64
import json
import sys
import time
from datetime import date

sys.path.insert(0, ".")

import requests  # noqa: E402

from src.fetchers import b3_index_fetcher as f  # noqa: E402
from src.pipeline import ingest_b3_index as idx  # noqa: E402

fetcher = f.B3IndexFetcher(sleep_between=0.3)


def p(*a):
    print(*a, flush=True)


def levels(code: str, years: list[int]) -> dict:
    out = {}
    for y in years:
        try:
            payload = fetcher.fetch_year(code, y)
        except f.B3IndexNoResults:
            p(f"  {code} {y}: results=null")
            continue
        for r in idx.parse_year(code, y, payload):
            out[r["trade_date"]] = r["level"]
        time.sleep(0.3)
    return out


def window(s: dict, lo: date, hi: date) -> list:
    return [(str(d), str(v)) for d, v in sorted(s.items()) if lo <= d <= hi]


def main() -> None:
    p("today", date.today())
    codes = ["IBOV", "IBXX", "IBXL", "SMLL", "IFIX", "IDIV", "IEEX", "ICON", "IMOB", "UTIL"]
    s = {c: levels(c, [2025]) for c in codes}
    p("\n== dates matched against B3's own daily bulletin (BDI) ==")
    for d in [date(2025, 9, 10), date(2025, 10, 10), date(2025, 10, 13), date(2025, 11, 11)]:
        p(str(d), {c: str(s[c].get(d)) for c in codes})
    p("\n== SMLL around its methodology base date 2008-04-30 ==")
    smll = levels("SMLL", [2008])
    p(window(smll, date(2008, 4, 24), date(2008, 5, 6)))
    p("SMLL 2008-09-01", smll.get(date(2008, 9, 1)))
    p("\n== IEEX, IBOV and IBXX around 1999-03 ==")
    iee = levels("IEEX", [1999])
    ib = levels("IBOV", [1999])
    ibx = levels("IBXX", [1999])
    p("IEEX", window(iee, date(1999, 3, 8), date(1999, 4, 6)))
    p("IBOV", window(ib, date(1999, 3, 8), date(1999, 4, 6)))
    p("IBXX", window(ibx, date(1999, 3, 8), date(1999, 4, 6)))
    p("\n== UTIL 2011..2013, raw ==")
    for y in (2011, 2012, 2013):
        tok = f.B3IndexFetcher._token("UTIL", y)
        url = f"{f.BASE_URL}/GetPortfolioDay/{tok}"
        for attempt in (1, 2):
            r = requests.get(url, headers=f._HEADERS, timeout=40)
            body = r.text
            try:
                res = json.loads(body).get("results")
                nonnull = sum(1 for row in (res or []) for m in range(1, 13) if row.get(f"rateValue{m}") not in (None, ""))
            except Exception as exc:  # noqa: BLE001
                res, nonnull = None, repr(exc)
            p(f"UTIL {y} attempt {attempt}: HTTP {r.status_code}, {len(body)} bytes, results_is_null={res is None}, non_null_cells={nonnull}, head={body[:160]!r}")
            time.sleep(2)
    p("\n== codes B3 lists in its own membership endpoint ==")
    tok = base64.b64encode(json.dumps({"language": "pt-br"}, separators=(",", ":")).encode()).decode()
    r = requests.get(
        f"https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall/GetStockIndex/{tok}",
        headers=f._HEADERS, timeout=40,
    )
    body = r.json()
    codes_seen = sorted({c for row in body["results"] for c in row["indexes"].split(",") if c})
    p("header", body.get("header"))
    p("distinct index codes in membership:", len(codes_seen), codes_seen)
    p("codes containing TR or PR or ending in a digit:", [c for c in codes_seen if "TR" in c or "PR" in c or c[-1].isdigit()])
    p("\n== null-year handling in the shipped ingest ==")
    p("INDEX_CODES", idx.INDEX_CODES, "FIRST_YEAR", idx.FIRST_YEAR)


if __name__ == "__main__":
    main()
