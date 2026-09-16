---
name: silo
description: >
  Use when answering questions about Brazilian public financial data via the
  public read API — B3 cash quotes, CVM funds (NAV, flows, FIDC delinquency),
  panels, lookup, and coverage. Not for ingest, schema, or landing tables.
---

# SILO (agents)

Public **read** API for Brazilian fund and market data. Ingest is not exposed.

## Start here

1. `https://octo-98895abd.mintlify.site/llms.txt` — page index
2. Docs MCP (no auth): `https://octo-98895abd.mintlify.site/mcp`
3. This file — contract cheat sheet. Full pages beat training data.

## Auth — shared testing key, two tiers

The printed publishable key is **shared, for testing**. Anonymous access is
free but small: **3 ids per `panel` call**, 25 `search_funds` rows, a 200-row
`option_chain` page, 3s query timeout. Signing in (GitHub) raises
those to 50 / 200 / 2000 and 8s. It does **not** raise rows-per-response — the
1000-row cap is server-wide for every caller. Do not mint or forge a key.

Exceeding the id ceiling returns `22023` as a `400` naming the limit; nothing is
ever silently truncated. Since catalog v25 that holds for **every** set-returning
function, not just the panel: a call whose result would pass one 1000-row page
raises `22023` instead of trimming. Three of them page with a `p_after` cursor —
`panel` (key `date|id|metric|asset_class`), `quote_history` (the last row's
`trade_date`) and `fund_nav` (the last row's `period`, and paging there also
requires `p_entity_type`, because one CNPJ can file under two families in the
same month). The other five — `option_history`, `termo_history`, `financials`,
`company_financials`, `anbima_classes` — have no cursor: narrow the window.

Call `coverage` before claiming freshness, and read `as_of` (the newest period
that has actually elapsed), not `newest_period` (the newest period key, which
sits in the future for FIP — it files annually keyed to 31-December).
`metric_coverage` says which `(family, metric)` pairs are filed at all and since
when; a pair missing from it is one the family never files, not one that is
late. Landing tables are closed to both tiers. The same ceilings, as numbers,
are `POST /rpc/catalog` → `.limits`.

To sign in, send a human to https://silo-bz.vercel.app/signin.html — it returns an access token. Then send
BOTH headers:

```
apikey: sb_publishable__yfFQsykAglrvc9GS6_PYw_B24ex437
Authorization: Bearer <access token>
```

**The token expires in about an hour**, and expiry does not surface as an auth
error: you drop silently back to anonymous limits, so a 4-id panel starts
returning `22023`. Treat that error on a call that used to work as "my token
died", not as "my request is malformed".

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
FIDC `delinquency` is null on every row before 2025-01 and filed from 2025-01 (a
source-format boundary, `catalog().regime_breaks` / `coverage().notes`): start the
series at 2025-01, never chain-link through it. `fund_nav` nulls outside a family's
`catalog().applicability` list are not applicable, not missing.

## Do not

- Fabricate a price, NAV, fill, or ranking. Missing stays missing. No ffill.
- Treat a calendar gap as a multi-month `close_return` (it is null / omitted).
- Use quotes as split-adjusted total return (`adjusted = false`).
- Retry a refused `panel` (22023 "more than 1000 rows") by shrinking the ask blindly: page it with `p_after` ('' first, then the last row's `date|id|metric|asset_class`) or narrow it. Never pivot a panel on (id, date, metric) alone — the grain includes `asset_class`.
- Touch landing tables (`cvm_*`, `b3_cotahist`, `cvm_ingest_log`) or send `Accept-Profile: public`.

Pages: [agents](/api-docs/agents), [panel](/api-docs/panel), [conventions](/api-docs/conventions).
