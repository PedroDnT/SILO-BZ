# Quickstart

Three calls to get oriented: discover what exists, check what is fresh, pull your first series.

## 1. Get your API key

SILO runs on Supabase. The anon key is a public, rate-limited key that reads the `api` schema. You can find it in the Supabase dashboard under **Settings → API → Project API keys → anon (public)**.

For most research use cases the anon key is all you need. It carries a 3-second statement timeout and the same row cap as the authenticated tier.

## 2. Discover what is available

`catalog()` returns every endpoint with its description, parameters, and constraints. It hits no database.

```bash
curl -X POST \
  'https://zcjbtpxuhdekpwcxmepn.supabase.co/rest/v1/rpc/catalog' \
  -H 'apikey: YOUR_ANON_KEY' \
  -H 'Content-Type: application/json' \
  -d '{}'
```

The response is a JSON object with an `endpoints` array. Each entry has:

- `name` — the RPC function name
- `description` — what it returns
- `agent` — a machine-readable summary for LLM use
- `params` — typed parameter list

## 3. Check data freshness

`coverage()` returns the freshness of every ingested dataset.

```bash
curl -X POST \
  'https://zcjbtpxuhdekpwcxmepn.supabase.co/rest/v1/rpc/coverage' \
  -H 'apikey: YOUR_ANON_KEY' \
  -H 'Content-Type: application/json' \
  -d '{}'
```

Look at `landed_at` (when SILO ingested it) and `complete_through` (how far the source publishes). The difference between the two is Brazil's filing lag, not a pipeline failure.

## 4. Pull prices

```bash
curl -X POST \
  'https://zcjbtpxuhdekpwcxmepn.supabase.co/rest/v1/rpc/quote_history' \
  -H 'apikey: YOUR_ANON_KEY' \
  -H 'Content-Type: application/json' \
  -d '{
    "p_ticker": "PETR4",
    "p_from": "2024-01-02",
    "p_to": "2024-12-31",
    "p_fields": ["date","close","close_adj","volume"]
  }'
```

The response is a `series` array of date-keyed objects. If the window would return more than 1000 rows you get an error with `DETAIL` and `HINT` — use `p_after` to page through it.

## Python SDK

```python
pip install silo-bz
```

```python
import silo

client = silo.Client(api_key="YOUR_ANON_KEY")

# Prices
df = client.prices("PETR4", start="2024-01-02", end="2024-12-31")

# Multi-asset panel
panel = client.panel(
    ids=["PETR4", "VALE3"],
    metrics=["close", "close_adj"],
    start="2024-01-02",
    end="2024-12-31"
)

# Research universe
universe = client.research_universe()
```

## What you get back

Every price series is:

- **Unadjusted by default.** `close` is the raw COTAHIST close. `X-Silo-Adjusted: false` is on every response.
- **Cash-only board selected automatically.** PETR4 trades on multiple boards; SILO serves the cash board (BDI 02) so you are never mixing auction prints with daily closes.
- **Not split-adjusted for past events.** `close_adj` applies only B3's corporate events (splits, bonus shares) as stored in the tape. Distributions are in `close_total_return`.

## Next steps

- [Authentication](/authentication) — when and why to use a JWT
- [Core concepts](/concepts) — row caps, cursors, coverage semantics
- [Research universe](/guides/research-universe) — build a survivorship-aware equity universe
