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
silo.coverage()                   # as_of (landed) vs complete_through (served)
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
short answer. Range paging does not work on RPC calls, so it cannot stitch the
rest for you; narrow the window, ask for fewer ids, or take one metric at a
time.

```python
from silo_client import SiloClient, SiloTruncated

try:
    rows = silo.quote_history("PETR4", start="2019-01-01")
except SiloTruncated as e:
    print(e.returned, "of", e.total)     # 1000 of 4382
```

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
are under.

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
