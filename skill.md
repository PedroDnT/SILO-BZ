---
name: silo
description: >
  Use when answering questions about Brazilian public financial data via the
  public read API — B3 cash quotes, CVM funds (NAV, flows, FIDC delinquency),
  panels, lookup, and coverage. Not for ingest, schema, or landing tables.
---

# SILO (agents)

Public **read** API for Brazilian fund and market data. Ingest is not exposed.

This file is the loader: credentials, the first call, and the shape of an
answer. **It does not restate the contract.** The row caps, the tier ceilings,
the null semantics and the regime breaks live in exactly two places — the
[Conventions & limits](https://octo-98895abd.mintlify.site/api-docs/conventions)
page for humans and `POST /rpc/catalog` for code. Read one of them before you
reason about a limit; do not reason from this file's summary, because it does
not have one.

## Start here

1. `https://octo-98895abd.mintlify.site/llms.txt` — index of every page
2. Docs MCP (no auth): `https://octo-98895abd.mintlify.site/mcp`
3. `POST /rpc/catalog` — the contract as JSON. Call it once, cache it, and read
   `limits`, `metrics`, `applicability`, `regime_breaks` and `constraints` off
   the payload instead of from memory. `version` says which contract the server
   is serving.

Full pages beat training data. When the two disagree, the pages win; when a
page and the catalog disagree, the catalog wins.

## Credentials

Base URL (no trailing slash when joining `/rpc/...`):

```
https://zcjbtpxuhdekpwcxmepn.supabase.co/rest/v1
```

The publishable key is **shared, for testing**. Send it only as `apikey`, never
as `Authorization: Bearer` — it is not a JWT:

```
apikey: sb_publishable__yfFQsykAglrvc9GS6_PYw_B24ex437
```

Never `sb_secret_…` / `service_role`. Never `Accept-Profile: public`. You cannot
mint or forge a key, and there is no endpoint that issues one.

Anonymous access is free and deliberately small. To raise the ceilings, send a
human to https://silo-bz.vercel.app/signin.html (GitHub) and then send **both**
headers:

```
apikey: sb_publishable__yfFQsykAglrvc9GS6_PYw_B24ex437
Authorization: Bearer <access token>
```

**The token expires in about an hour and expiry is silent** — you drop back to
anonymous limits rather than getting a `401`, so a call that worked an hour ago
starts failing on an id ceiling. Read that as "my token died".

The numbers for both tiers are `catalog().limits.tiers`, and in prose on
[Conventions & limits](https://octo-98895abd.mintlify.site/api-docs/conventions#authentication).
Do not carry them in your head; they change.

## How to answer a finance question

1. `POST /rpc/coverage` with `{}` — one row per dataset. **Do not claim
   freshness without it.** Read `as_of`, not `newest_period`; read `notes`
   before differencing anything.
2. Resolve names with `POST /rpc/lookup` (`p_query`). A 14-digit id is a CNPJ;
   anything else is a ticker. Do not invent ticker↔CNPJ joins — the only
   published one is CVM's FCA map, which `lookup` already returns as `tickers`.
3. Pull a panel: `POST /rpc/panel` with `p_ids`, `p_metrics`, `p_freq`. Mix
   tickers and fund CNPJs in one call. `freq=day` is quotes only; mix equity
   with fund fundamentals on `freq=month`. Take metric names from
   `catalog().metrics` — an unrecognised one is **ignored, not rejected**, and
   the panel comes back smaller and plausible.
4. Reduce **locally** (corr, rank, ratios, regressions). There is no
   `POST /query` and no server-side correlation; the catalog lists these as
   `notebook_reducers`.
5. Before reading a null as a gap, call `coverage` and `metric_coverage`. A null
   outside a family's column set is **not applicable**, and a `(family, metric)`
   pair absent from `metric_coverage` is one that family never files.

Worked end-to-end examples, runnable: [`notebooks/`](https://github.com/PedroDnT/SILO-BZ/tree/main/notebooks)
in the repository, and the [Python SDK](https://octo-98895abd.mintlify.site/api-docs/sdk)
(`pip install -e sdk/`), which wraps the paging cursors and raises on a
truncated response.

## Do not

- Fabricate a price, NAV, fill, ranking, or identifier match. Missing stays
  missing. No ffill, no interpolation, no carried-forward last observation.
- Treat a calendar gap as a multi-month `close_return` (it is null / omitted),
  or read `close_return` as a total return — quotes are unadjusted
  (`adjusted = false`) and a 2:1 split reports roughly −50 %.
- Read `delinquency` as a rate. It is **BRL value**; divide by `nav` yourself.
- Chain-link a FIDC `delinquency` series across 2024-12 → 2025-01. It is null on
  every row before 2025-01 (a source-format boundary, `catalog().regime_breaks`);
  the series **starts** there.
- Pivot a panel on `(id, date, metric)`. The grain includes `asset_class` —
  one CNPJ can file under two families in the same month.
- Retry a refused call by shrinking the ask blindly. Over one page, functions
  raise `22023` rather than trim: page `panel` / `quote_history` / `fund_nav`
  with `p_after`, and narrow the window on the rest. Nothing is ever silently
  truncated on an RPC call.
- Touch landing tables (`cvm_*`, `b3_cotahist`, `cia_*`, `bacen_*`,
  `cvm_ingest_log`) or send `Accept-Profile: public`. Schema `api` is the whole
  public surface.

Pages: [conventions](https://octo-98895abd.mintlify.site/api-docs/conventions)
(the contract) · [for agents](https://octo-98895abd.mintlify.site/api-docs/agents)
(the operator guide) · [panel](https://octo-98895abd.mintlify.site/api-docs/panel)
· [coverage](https://octo-98895abd.mintlify.site/api-docs/coverage).
