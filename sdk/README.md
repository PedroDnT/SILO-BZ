# silo-client

Thin Python client for the Silo read API — Brazilian public-markets data
(CVM funds, B3 COTAHIST quotes/options/termo) served from schema `api` over
the Supabase Data API.

```bash
pip install -e sdk/              # from the repo root, or copy sdk/silo_client/
pip install -e "sdk/[pandas]"    # adds the wide-DataFrame panel output
```

```python
from silo_client import SiloClient

silo = SiloClient(url="https://<ref>.supabase.co", key="<publishable key>")
# or set SILO_URL / SILO_ANON_KEY and call SiloClient()

silo.catalog()                    # metric map + constraints — read it once
silo.coverage()                   # as_of (elapsed) vs complete_through (served)
                                  # vs newest_period (may be future) vs landed_at
silo.metric_coverage()            # which (family, metric) pairs are filed, since when
silo.lookup("petrobras")          # company rows carry tickers=["PETR3","PETR4"]

df = silo.panel(
    ["PETR4", "05754060000113"],
    metrics=["close_return", "delinquency"],
)                                 # wide DataFrame, (date) x (id, metric)
df.corr()                         # reductions happen HERE, not over HTTP
```

## Two things that will bite you if nobody says them

**A capped response raises.** PostgREST stops at **1,000 rows** and answers
HTTP 200 with the first page, oldest first. Six years of daily quotes come back
as three and a half, and the series simply looks like it ended — which is
indistinguishable from a company that stopped trading. The client asks the
server for a true count and raises `SiloTruncated` rather than handing you the
short answer. Range paging does not work on RPC calls, so for the series
functions it cannot stitch the rest for you; narrow the window, ask for fewer
ids, or take one metric at a time. `panel` is different since catalog v24: the
server **refuses** a call over one 1,000-row page (`SiloOverCap`) and pages
with its own `p_after` cursor — `iter_panel()` / `panel_all()` walk it, and
`panel_all(None, [...], entity_type="fidc", min_nav=1e7, min_months=12)` walks
a whole family for a signed-in caller.

```python
from silo_client import SiloClient, SiloOverCap, SiloTruncated

try:
    rows = silo.quote_history("PETR4", start="2019-01-01")
except SiloOverCap:
    # Since catalog v26 the server REFUSES rather than trims, and the three
    # long series page. A cursor walk, not a stitched guess:
    rows = silo.quote_history_all("PETR4", start="2019-01-01")

# fund_nav pages within ONE family: its cursor is a bare period, and 385 CNPJs
# file under two families in the same month, so the family is not optional.
nav = silo.fund_nav_all("05754060000113", "fi", start="2019-01-01")

# SiloTruncated still fires on the GET views, which do cut at 1000 rows.
try:
    page = silo.view("funds", entity_type="eq.fidc")
except SiloTruncated as e:
    print(e.returned, "of", e.total)     # 1000 of 4382
    print(e.rows[-1]["cnpj"])            # where the cut fell — inspect, never use
```

`option_history`, `termo_history`, `financials`, `company_financials` and
`anbima_classes` have no cursor: `SiloOverCap` there means narrow the window
and call again.

**Views are the one surface that pages**, and the client knows it. `view()`
with an explicit `limit`/`offset` returns that page whatever the total;
`view_all()` walks every page for you (an `order` is required — offset paging
without one can duplicate or drop a row at a boundary without saying so):

```python
fidcs = silo.view_all("funds", entity_type="eq.fidc", order="cnpj.asc",
                      select="cnpj,fund_name,first_period,last_period")
page2 = silo.view("funds", order="cnpj.asc", limit=1000, offset=1000)
```

A `view()` call with no `limit` that lands on the 1,000-row cap still raises:
that is the silent cut, not a page.

**Signing in raises four ceilings, and not the fifth.** Pass a user JWT as
`token=` (or set `SILO_TOKEN`) and the request moves from the anonymous role to
`authenticated`:

| | anonymous | signed in |
| --- | ---: | ---: |
| `panel` ids per call | 3 | 50 |
| `search_funds` rows | 25 | 200 |
| `option_chain` rows | 200 | 2,000 |
| query budget | 3s | 8s |
| **rows per response** | **1,000** | **1,000** |

That last row is not a typo. `db-max-rows` is a server-wide setting applied
identically to every caller; no tier changes it. Get a token from the sign-in
page in the docs, and check `silo.tier` if you need to know which ceiling you
are under. The same table, as numbers, is `silo.limits()` — read from the
catalog's `limits` block, which a test pins to the SQL that enforces it.

**The client tells you when it is out of date.** `catalog()` compares the
server's catalog version with the one this client was written against and
warns (`SiloCatalogDrift`) on a mismatch — a newer server has endpoints or
limits the wrappers do not know; an older one lacks some they call. It never
refuses: everything read off the catalog itself keeps working.

## The contract, in client form

- **Catalog-driven.** Metric names are validated against the live catalog; a
  typo raises `ValueError` client-side instead of returning an empty panel
  that looks like missing data.
- **Nothing fabricated.** Missing observations stay `NaN` — no forward-fill,
  no interpolation, no invented month-ends. Server errors surface with the
  server's own message (`SiloError`).
- **Honest windows by default.** `end=None` on `panel`/`fund_nav` keeps the
  server's clamp: fund metrics stop at each family's latest _complete_
  period. Pass an explicit `end` to see partial months verbatim.
- **Unadjusted prices.** `close` is as published; a 2:1 split looks like
  −50%. `close_return` is already null across session gaps > 7 days and
  quotation-factor changes, but corporate actions are yours to handle.
- **The panel is the primitive.** Correlation, ranking, spreads, factor
  models are reductions of the DataFrame this client hands you. The API will
  not compute them, and neither will this client.

The shared publishable key printed in the docs is **testing only**.

## Testing

Offline, via `httpx.MockTransport` — see `tests/test_sdk_client.py` in the
repo root. No network, no fabricated fixtures beyond the documented response
shapes.
