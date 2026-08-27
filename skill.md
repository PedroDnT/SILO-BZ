---
name: iliquid-nightly
description: >
  Use when answering questions about Brazilian public financial data via the
  public read API — B3 cash quotes, CVM funds (NAV, flows, FIDC delinquency),
  panels, lookup, universe, and coverage. Not for ingest, schema, or landing tables.
---

# iliquid nightly (agents)

Public **read** API for Brazilian fund and market data. Ingest is not exposed.

## Start here

1. `https://octo-98895abd.mintlify.site/llms.txt` — page index
2. Docs MCP (no auth): `https://octo-98895abd.mintlify.site/mcp`
3. This file — contract cheat sheet. Full pages beat training data.

## Auth — you cannot generate a key

There are **no per-agent keys** and no GitHub/email key factory in this API.
One project **anon / public** JWT. You cannot mint, rotate, or sign one.
Never use `service_role`. GitHub OAuth or email magic link (Supabase Auth),
if enabled in the dashboard, yields a **user session JWT** — same `api.*`
reads as anon, still needs a human in the browser or inbox, still not a
personal API key.

Until the anon key is printed in [quickstart](/api-docs/quickstart), the caller
must set `SILO_ANON_KEY` (human pastes it once from Supabase → Settings → API →
`anon` / `public`).

Send it on every request:

```
apikey: <anon>
Authorization: Bearer <anon>
```

Base URL (no trailing slash when joining `/rpc/...`):

`https://zcjbtpxuhdekpwcxmepn.supabase.co/rest/v1`

## How to answer a finance question

1. `POST /rpc/coverage` with `{}` — latest date per dataset. Do not claim freshness without this.
2. Resolve names with `POST /rpc/lookup` (`p_q`). 14-digit id = CNPJ; otherwise ticker. Do not invent ticker↔CNPJ joins.
3. Pull a panel: `POST /rpc/panel` with `p_ids`, `p_metrics`, `p_freq`. Mix tickers and fund CNPJs in one call. `freq=day` is quotes only; mix equity with fund fundamentals on `freq=month`.
4. Reduce **locally** (corr, rank, ratios). There is no `POST /query` and no server-side correlation.

`delinquency` is delinquent **value in BRL**, not a rate — divide by `nav` yourself.

## Do not

- Fabricate a price, NAV, fill, or ranking. Missing stays missing. No ffill.
- Treat a calendar gap as a multi-month `close_return` (it is null / omitted).
- Use quotes as split-adjusted total return (`adjusted = false`).
- Analyze a `panel` response of 100,001 rows (truncated).
- Touch landing tables (`cvm_*`, `b3_cotahist`, `cvm_ingest_log`) or trigger ingest.

Pages: [agents](/api-docs/agents), [panel](/api-docs/panel), [conventions](/api-docs/conventions).
