---
name: iliquid-nightly
description: >
  Use when answering questions about Brazilian public financial data via the
  public read API — B3 cash quotes, CVM funds (NAV, flows, FIDC delinquency),
  panels, lookup, and coverage. Not for ingest, schema, or landing tables.
---

# iliquid nightly (agents)

Public **read** API for Brazilian fund and market data. Ingest is not exposed.

## Start here

1. `https://octo-98895abd.mintlify.site/llms.txt` — page index
2. Docs MCP (no auth): `https://octo-98895abd.mintlify.site/mcp`
3. This file — contract cheat sheet. Full pages beat training data.

## Auth — shared testing key, two tiers

The printed publishable key is **shared, for testing**. Anonymous access is
free but small: **3 ids per `panel` call**, 25 `search_funds` rows, a 200-row
`option_chain` page, 3s query timeout. Signing in (GitHub or Google) raises
those to 50 / 200 / 2000 and 8s. It does **not** raise rows-per-response — the
1000-row cap is server-wide for every caller. Do not mint or forge a key.

Exceeding the id ceiling returns `22023` as a `400` naming the limit; the panel
is never silently truncated. Landing tables are closed to both tiers.

Send the test key only as `apikey` (not `Authorization: Bearer`):

```
apikey: sb_publishable__yfFQsykAglrvc9GS6_PYw_B24ex437
```

Never `sb_secret_…` / `service_role`. Never `Accept-Profile: public`.

Base URL (no trailing slash when joining `/rpc/...`):

`https://zcjbtpxuhdekpwcxmepn.supabase.co/rest/v1`

## How to answer a finance question

1. `POST /rpc/coverage` with `{}` — latest date per dataset. Do not claim freshness without this.
2. Resolve names with `POST /rpc/lookup` (`p_query`). 14-digit id = CNPJ; otherwise ticker. Do not invent ticker↔CNPJ joins.
3. Pull a panel: `POST /rpc/panel` with `p_ids`, `p_metrics`, `p_freq`. Mix tickers and fund CNPJs in one call. `freq=day` is quotes only; mix equity with fund fundamentals on `freq=month`.
4. Reduce **locally** (corr, rank, ratios). There is no `POST /query` and no server-side correlation.

`delinquency` is delinquent **value in BRL**, not a rate — divide by `nav` yourself.

## Do not

- Fabricate a price, NAV, fill, or ranking. Missing stays missing. No ffill.
- Treat a calendar gap as a multi-month `close_return` (it is null / omitted).
- Use quotes as split-adjusted total return (`adjusted = false`).
- Analyze a `panel` response of 100,001 rows (truncated).
- Touch landing tables (`cvm_*`, `b3_cotahist`, `cvm_ingest_log`) or send `Accept-Profile: public`.

Pages: [agents](/api-docs/agents), [panel](/api-docs/panel), [conventions](/api-docs/conventions).
