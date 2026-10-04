# Introduction

SILO is a read-only data layer for Brazilian public financial data. It ingests, validates, and serves data from four sources:

| Source    | What it holds                                                                                                           |
| --------- | ----------------------------------------------------------------------------------------------------------------------- |
| **CVM**   | Fund disclosures (FI, FIDC, FII, FIP, FIAGRO, SECURIT) and listed-company filings (ITR, DFP, IPE)                       |
| **B3**    | Daily COTAHIST quotes (2019–), lending and investor flows, index levels (IBOV since 1968), DI futures, reference curves |
| **BACEN** | SGS macro time series, PTAX closing rate, Focus expectations                                                            |
| **IBGE**  | IPCA item weights and monthly changes                                                                                   |

Everything is served through a single PostgREST endpoint:

```
https://zcjbtpxuhdekpwcxmepn.supabase.co/rest/v1
```

## What "trusted" means here

**Refuses over truncates.** Forty-five functions raise an error rather than returning a short result. The error says why and how to fix it. Four functions (`panel`, `quote_history`, `fund_nav`, `index_history`) have a cursor so you can walk a long series one page at a time.

**Provenance on every row.** Every ingest run writes a `cvm_ingest_log` row carrying `landed_at`, the GitHub commit SHA (`git_sha`), and a `parser_version` bumped only when a field's meaning changes. `coverage()` returns `landed_git_sha` for the run that set `landed_at`.

**As-of semantics for fundamentals.** Every fundamental function takes `p_as_of DATE`. A date T reads only the filings CVM received before T, keeping the highest version known at that date. A NULL means you are getting the latest version, which is not point-in-time.

**No derived store.** `close_adj` is computed at read time from B3's corporate-event history — it is never stored in a column. The underlying COTAHIST row is always available as `close`. Nothing is invented; a failed fetch raises, it does not return a plausible-looking default.

## What this is not

SILO is a **data layer**, not a widget API. It returns raw panels and series. Reductions — returns, correlations, regressions, factor loadings — happen in your notebook. There is no server-side `corr` endpoint. `api.catalog()` lists those reductions as `notebook_reducers` so you know which ones belong there.

## Two different ceilings

Reading one for the other is the most expensive mistake on this API.

**The row cap refuses.** The 45 capped functions raise SQLSTATE `22023` when the window would produce more than 1000 rows. Nothing is trimmed and the error gives you `DETAIL` (why) and `HINT` (how to fix it).

**PostgREST's server-wide ceiling silently truncates.** `db-max-rows = 1000` cuts every GET view response regardless of tier. Read `Content-Range: 0-999/*` as "this result is truncated." `Prefer: count=exact` turns the `*` into the total row count.

## Data freshness

`POST /rpc/coverage` returns the freshness of every dataset. Two fields matter:

- `landed_at` — when SILO last successfully ingested this dataset. This is ours to fix if it is old.
- `complete_through` — how far the source has published data. This is Brazil's filing calendar, not a SILO outage.

A fund with `complete_through` three months ago is not broken; CVM publishes it with a two-month lag.
