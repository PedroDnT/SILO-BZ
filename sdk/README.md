# silo-client

Thin Python client for the Silo read API — Brazilian public-markets data
(CVM funds, B3 COTAHIST quotes/options/termo) served from schema `api` over
the Supabase Data API.

```bash
pip install -e sdk/          # from the repo root, or copy sdk/silo_client/
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
