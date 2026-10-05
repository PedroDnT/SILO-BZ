# `serve/` — the local adapter (this is **not** the public API)

> **If you are looking for the read contract, you are in the wrong file.**
>
> The public surface is **`POST /rest/v1/rpc/<name>`** and **`GET /rest/v1/<view>`**
> on Supabase PostgREST:
>
> ```
> https://zcjbtpxuhdekpwcxmepn.supabase.co/rest/v1/
> ```
>
> Its documentation is the published site — **[Conventions &
> limits](https://octo-98895abd.mintlify.site/api-docs/conventions)** is the single
> source of truth for auth tiers, row caps, null semantics and regime breaks, and
> **`POST /rpc/catalog`** is the same contract as JSON. Start at
> [llms.txt](https://octo-98895abd.mintlify.site/llms.txt) or
> [Quickstart](https://octo-98895abd.mintlify.site/api-docs/quickstart).
>
> **Nothing in this file is normative for a caller.** It documents `serve/app.py`,
> a read-only Flask adapter you can run on your own machine. It is not
> necessarily deployed anywhere, and its `/v1/*` routes, query-string arguments
> and `format=wide` envelope exist **only** there.

`api.catalog()` says the same thing in its `agent` field: prefer the `postgrest`
section; the `/v1/*` routes in `endpoints` are this adapter's.

## Newly served held-data RPCs

These endpoints are available on the public PostgREST surface above, not as
additional `/v1` routes. Discover them through `POST /rest/v1/rpc/catalog`.

- `financial_statement_history(p_id, p_statement, p_from, p_to, p_scope,
  p_doc_type)` returns raw CIA account lines for one required statement across
  every stored version. Its grain is a filed account line and filed period;
  `period_start`/`period_end` distinguish quarterly from year-to-date rows.
  Filing metadata appears only on an exact header-key match. Values are already
  scaled at ingest and remain in the filed currency. It refuses above 1,000 rows.
- `fii_property_history(p_cnpj, p_from, p_to)` returns CVM property-register
  source rows for one exact fund CNPJ and reference-date window. CVM provides no
  stable property id, so `row_hash` identifies a source row, not a durable
  property. Missing measures remain `NULL`; percentages retain their filed
  meaning. It refuses above 1,000 rows.

- `focus_expectations(p_endpoint, p_horizon, p_indicator, p_from, p_to)` returns
  the Focus path across survey dates for one exact endpoint and target horizon.
  Each survey date is a published observation; successive dates form the
  weekly expectation revision path. It serves `baseCalculo=0` (the trailing
  30-day respondent sample), with 12-month inflation unsmoothed. It refuses
  above 1,000 rows. This is not a vintage archive of later corrections to an
  old survey date. The daily pipeline refreshes the trailing 30 days; older
  corrections are not guaranteed to be captured, and some pre-migration-16
  history may lack horizons lost to the earlier natural key.

## Why the adapter exists

The design premise, which the public API inherited: the main user is a
**researcher** doing correlation tests, factor models and cross-asset
relationships, mixing market prints with CVM fundamentals. They need a **panel**
— `(id, date, metric, value)` — not a quote widget. Analysis (corr, OLS, event
studies) is a _reduction_ of a panel, computed in a notebook. There is no
`POST /query` and no server-side `corr` on either surface; `api.catalog()` lists
those as `notebook_reducers`.

`serve/` predates the decision (2026-08-26) to expose schema `api` through
Supabase's own PostgREST. It survives for three things:

1. **Local development and notebooks** against a database you control, without a
   Supabase project or a network round trip.
2. **A shaped 404.** PostgREST has no adapter layer, so an unknown ticker and an
   empty window both return `200 []`. `serve/` distinguishes them (see
   [404 vs empty](#404-vs-empty)).
3. **A different envelope.** `format=wide` and `format=columnar` are chart- and
   correlation-shaped responses that PostgREST does not produce.

It is **not** an ingest trigger, and there is no ingest HTTP server anywhere in
this repository. Ingest is GitHub Actions cron plus `python -m src.pipeline.run_daily`
/ `run_backfill`.

## Layers

```
client  →  HTTP /v1/*   (serve/, bind 127.0.0.1 or a gateway)
              ↓  role silo_api: SELECT/EXECUTE on api.* only
         Postgres schema api     (views + functions)
              ↓  owner rights, not GRANT on landing tables
         public landing + dim_/fact_*     (ingest still writes here)
```

The deployed path skips the top box entirely: the browser or agent talks to
PostgREST as `anon` or `authenticated`, and the same schema `api` answers.

1. **`api` schema is the product.** English names, ticker/CNPJ keys, an explicit
   unadjusted flag, and automatic selection of each ticker's published BDI board.
   Clients never query `b3_cotahist`.
2. **HTTP is an adapter**, not a second database. Every handler is a single
   `SELECT` / `api.*()` call. No business logic that can invent a price.
3. **Do not turn on PostgREST for schema `public`.** Schema `api` is the whole
   public surface; landing tables are revoked from `anon` and `authenticated`, and
   `health.yml` asserts it on every run.
4. **Cache at the edge.** History whose `to` is in the past is immutable
   (`max-age=86400`). Latest quote is short (`max-age=300`). `serve/` also sends
   `X-Silo-Adjusted: false` so nobody assumes brapi-style split adjustment.

### 404 vs empty

On `serve/`, an unknown ticker or CNPJ is a `404`; a known ticker with no sessions
in the range is `200 { kind: "series", series: [] }`.

On PostgREST both are `200 []`, because there is no adapter to shape the error. A
caller that treats empty as 404 will silently mis-read a miss. Never a plausible
last-close fallback, on either surface.

## Point vs series

The same URL is a **point** until the caller asks for a window. Then it is a
**series** — dated observations at the grain actually stored (day for B3, month for
fund NAV). No invented weekly/monthly bars.

```
GET /v1/quotes/PETR4                         → one object (latest session)
GET /v1/quotes/PETR4?range=1y                → { kind: "series", series: [...] }
GET /v1/quotes/PETR4?from=2024-01-01&to=...  → same envelope
GET /v1/quotes/PETR4?range=1y&format=columnar
GET /v1/quotes/PETR4?range=1y&fields=close,volume
GET /v1/quotes/PETR4/history                 → alias (defaults to 1y)
GET /v1/funds/{cnpj}/nav                     → monthly series, same envelope
```

`range`: `5d` `1mo` `3mo` `6mo` `1y` `2y` `5y` `ytd` `max`.

Row envelope (default):

```json
{
  "ticker": "PETR4",
  "kind": "series",
  "grain": "day",
  "adjusted": false,
  "source": "b3_cotahist",
  "board": "02",
  "from": "2025-08-15",
  "to": "2026-08-14",
  "count": 248,
  "series": [
    {
      "date": "2025-08-15",
      "open": 41.1,
      "high": 41.5,
      "low": 40.9,
      "close": 41.2,
      "volume": 1.2e9,
      "trades": 40000
    }
  ]
}
```

Columnar (`format=columnar`) is for charts: `dates` plus one array per field,
aligned by index. Cap is 5000 points — over that is `400`, not a silent trim.

`format=wide` is the correlation input: `dates × columns` (`PETR4.close`,
`{cnpj}.delinquency`). Missing cells are JSON `null`; nothing is filled. **This
envelope exists only on `serve/`** — on PostgREST, `api.panel` returns long rows
and you pivot locally (the Python SDK's `panel(wide=True)` does it for you).

## Routes (v1) — adapter only

| Method | Path                                        | Postgres                                              |
| ------ | ------------------------------------------- | ----------------------------------------------------- |
| GET    | `/v1/catalog`                               | static metric map + constraints (no DB)               |
| GET    | `/v1/tools`                                 | OpenAI/AI-SDK tool specs pointing at these routes     |
| GET    | `/v1/health`                                | `SELECT 1 FROM api.quotes LIMIT 0`                    |
| GET    | `/v1/coverage`                              | `api.coverage()`                                      |
| GET    | `/v1/metric-coverage`                       | `api.metric_coverage()`                               |
| GET    | `/v1/panel?ids&metrics&freq&from&to`        | `api.panel(...)` long or wide                         |
| GET    | `/v1/lookup?q=`                             | `api.lookup(...)`                                     |
| GET    | `/v1/quotes/{ticker}`                       | `api.quote_latest` or `api.quote_history` if windowed |
| GET    | `/v1/quotes/{ticker}/history?from&to&range` | `api.quote_history(...)`                              |
| GET    | `/v1/funds?q&type&limit`                    | `api.search_funds(...)`                               |
| GET    | `/v1/funds/{cnpj}`                          | `api.fund_profile(cnpj)`                              |
| GET    | `/v1/funds/{cnpj}/nav?from&to&range`        | `api.fund_nav(...)`                                   |

CNPJ in the path may include punctuation (`12.345.678/0001-90`); it is stripped to
14 digits. Tickers are uppercased.

The adapter wraps a **subset** of schema `api`. Everything else — the typed cash
views, options, termo, holdings, debentures, FIDC concentration, FIDC tranches
and aging (`fidc_tranches`, `fidc_aging`, catalog v32 — history from 2025-01, as
CVM publishes no archive of those tabs), the FNET document register
(`fund_documents`, `fund_restatements`, catalog v33, and
`fund_restatement_diff`, catalog v40), ANBIMA classes, inflation,
company financials, company events, macro series and PTAX (catalog v38), and the
B3 lending and investor-flow views — has no `/v1`
twin and is reachable only over PostgREST. Read those on the published site.

### The FNET document register

`api.fund_documents` and `api.fund_restatements` (catalog v33,
`24_api_fnet.sql`) serve B3 Fundos.NET's register (migration 42,
`src/fetchers/fnet_fetcher.py`) — metadata only, one row per document id, and
**each version is a new id**. Caller documentation is [Fund documents and
restatements](https://octo-98895abd.mintlify.site/api-docs/fnet-documents).
The operator half, which is what a reviewer needs to check:

- **Fund by link, never by name.** FNET rows carry no CNPJ. `fund_documents`
  joins through `fnet_document_filter` rows with `filter_name = 'cnpjFundo'`,
  written by the fortnightly per-fund sweep (`FNET_SWEEP_SLICES`, default 14),
  so a document delivered since its fund's last sweep is not listed yet.
  `fund_restatements` serves such a document with `cnpj` NULL rather than
  dropping it. `fund_name` is never a join key.
- **Versions are paired by a stated key**, because FNET links none:
  `(cnpj link, categoria, tipo_documento, especie, reference_raw)`, the highest
  lower `versao`, the greatest `fnet_id` on a tie (a group can hold several v1
  documents — assemblies). No cnpj link or no reference text → never paired.
- `source_url` is FNET's public `downloadDocumento?id=<fnet_id>` link, built
  from the id; nothing is fetched at read time.
- **What a restatement changed** (catalog v40): `api.fund_restatement_diff`
  reads `fnet_document_pair` / `fnet_document_diff` (migration 46), filled by
  `src/pipeline/fnet_diff.py` for the FIDC informe mensal. It serves only pairs
  with status `compared`, and only against the predecessor
  `fund_restatements` pairs today: the queue re-diffs a document whose
  predecessor changed. `fund_restatements` gains `n_fields_changed` and
  `diff_status` from the pair row of that exact pair (`prev_fnet_id IS NOT
  DISTINCT FROM previous_fnet_id`), NULL when not diffed. Needs `p_cnpj` or
  `p_fnet_id`; raise-only.
- Grants follow `fidc_tranches`: DEFINER with an empty `search_path`, revoked
  from `PUBLIC`, granted to `anon` / `authenticated` and to `silo_api` (no `/v1`
  route yet). Both are raise-only above one page. `coverage()` gains an
  `fnet_documents` row (as_of = newest delivery day, complete_through the day
  before; landed_at from `cvm_ingest_log` entity `fnet`, doc_type `register`).

### Company events, macro series and PTAX (catalog v38)

`api.company_events`, `api.macro_series` and `api.ptax` (`26_api_events_macro.sql`)
serve three tables that were held and read only by the dashboards (`cia_event`,
the non-inflation `bacen_sgs` series, `bacen_ptax`). Caller documentation:
[Company events](https://octo-98895abd.mintlify.site/api-docs/company-events) and
[Macro series and PTAX](https://octo-98895abd.mintlify.site/api-docs/macro). The
operator half:

- **`company_events`** resolves `p_id` through `api.company_ref` — the resolver
  `financials` uses (FCA ticker map, CNPJ, CVM code; never a name) — and serves
  one row per `protocolo` at its newest `versao`, with `link_download` as
  `source_url`. History starts in 2015 because CVM's pre-2015 IPE rows (and a
  minority since) carry no protocol and `cia_event`'s key drops them
  (`DATA_INVENTORY.md` §2); the `coverage()` row says so.
- **`macro_series`** reads only the codes in `api.macro_registry()`, which
  `tests/test_wave3_contract.py` pins to `SGS_SERIES` minus `INFLATION_SERIES`
  in `src/pipeline/bacen_pipeline.py`. Add a series there and the test fails
  until the registry and the `coverage()` row's code list follow. IPCA codes
  are refused with a pointer to `api.inflation`.
- **`ptax`** serves `bacen_ptax` as stored. The ingest keeps the last bulletin
  Olinda returns per day (upsert last-write-wins), which for a completed day is
  the Fechamento PTAX; the bulletin type is not stored.
- Grants follow `fund_documents`: DEFINER with an empty `search_path`, revoked
  from `PUBLIC`, granted to `anon` / `authenticated` / `silo_api`. All three are
  raise-only above one page. `coverage()` gains `company_events` (landed_at from
  `cia_aberta` / `ipe`), `macro_series` (`bacen` / `sgs`) and `ptax` (`bacen` /
  `ptax`).

### The research universe (catalog v43)

`api.research_universe()` (`28_api_research.sql`; research-seam spec
`docs/planning/RESEARCH_SEAM.md` §4, ticket #411) returns one row per
ticker+ISIN pair of listed shares and units traded on the B3 cash market since
2019-01-02, so a research caller can build a historical universe without a
hard-coded ticker list. The operator half:

- **Membership is the ISIN's own instrument code**, characters 7-9: `ACN`
  (shares), `CDA` and `UNT` (units, whose ticker must end in `11`). It is not
  `instrument_type`: that field lets about 100 subscription receipts through
  (ISIN code `R01`..`R21`, ESPECI starting ON/PN), and without the `11` clause
  6 non-units pass (BPAC13, AZUL97-99). 639 pairs on 2026-09-29.
- **The ISIN is the identity.** A rename is a new row and nothing links it to
  the old one; two tickers can share an ISIN (NEOE3, NEOE3B). `n_sessions` far
  below the calendar span is a gap (NATU3).
- **Served from `mv_research_universe`**, a materialized view rebuilt by every
  analytical apply and refreshed by cron (`refresh-research-universe`, 06:13
  UTC, 03:13 UTC-3), because `anon`'s `statement_timeout` is 3 s and the bare
  aggregate takes 1.6 s warm. `last_observed` therefore lags the tape by up to
  a day; `built_at` on each row says when. No client role can read the view.
- **The company link says how it was made**: `cnpj_basis` is `fca_ticker` (that
  exact ticker in `vw_company_ticker`, one CNPJ claiming it), `fca_issuer_stem`
  (the ticker's 4-letter stem, when exactly one CNPJ holds an FCA ticker with
  it: an inference) or NULL. Placeholder FCA tickers (`0000`, `NÃO`) are
  filtered by shape. No name matching. 584 / 17 / 38 pairs on 2026-09-29.
- **`setor_current`** is `cia_company.setor` as of today. `cia_company.segmento`
  is CVM's registration category ("Categoria A/B"), not a market segment, so it
  is not served.
- **No listing / delisting dates and no `is_active`** (#373, #381). A caller
  reads the universe at a date T as `first_observed <= T <= last_observed`; a
  pair inside a gap still matches.
- Grants follow `curve_history`: DEFINER with an empty `search_path`, revoked
  from `PUBLIC`, granted to `anon` / `authenticated` / `silo_api`. Raise-only
  above one page, and since nothing narrows it the message says it has no
  cursor and one must be added.

### The benchmark index (catalog v45, v53)

`api.index_history(p_index, p_from, p_to, p_after)` (`29_api_index.sql`;
research-seam spec `docs/planning/RESEARCH_SEAM.md` §5, tickets #412 and #415)
serves the daily level of a B3-published index from `b3_index_level` (migration
55). The operator half:

- **Source.** B3's index statistics proxy, `indexStatisticsProxy/IndexCall/
  GetPortfolioDay`, one calendar year per call as a 31 x 12 grid with Brazilian
  decimals (`src/fetchers/b3_index_fetcher.py`). IBOV from 1968-01-02: 14,491
  sessions through 2026-10-02, 2025-12-30 = 161,125.37 (B3's year-end figure).
  Rows held, read from `b3_index_level` on 2026-10-03, all ending 2026-10-02:

  | Code | First session | Rows |
  | ---- | ------------- | ---- |
  | IBOV | 1968-01-02    | 14,491 |
  | IBXX | 1994-12-29    | 7,868 |
  | IBXL | 1997-12-30    | 7,126 |
  | SMLL | 2005-08-31    | 5,225 |
  | IDIV | 2005-12-29    | 5,143 |
  | UTIL | 2005-12-29    | 5,143 |
  | ICON | 2006-12-28    | 4,897 |
  | IMOB | 2007-12-28    | 4,652 |
  | IFIX | 2010-12-30    | 3,910 |

  The counts grow one per session; `api.coverage()` is the live figure.
- **The codes held (v53, #416).** IBOV, IBXX (first session 1994-12-29), IBXL
  (1997-12-30), IFIX (2010-12-30), SMLL (2005-08-31), IDIV and UTIL (2005-12-29),
  ICON (2006-12-28) and IMOB (2007-12-28), the list `INDEX_CODES` /
  `FIRST_YEAR` in `src/pipeline/ingest_b3_index.py`. Each is checked against its
  base value on its base date, and IBOV, IBXX, IBXL and IFIX against B3's daily
  bulletin (`docs/reference/research/index-candidates-416.md`). **IEEX is held
  back:** it moved +70% on 1999-03-15 and -29% on 1999-03-31 with no divisor
  step and nothing in B3's methodology history to explain it. Levels before an
  index's publication date are B3's back-calculation and the endpoint does not
  mark them. `coverage()` reads each index's first date from the table, so it
  reports every code's own depth with no SQL edit.
- **Every code is a total-return index, as B3 labels it.** B3's pages and its
  Manual (Feb 2023, section 1.2) call IBOV and each candidate an index of
  *retorno total*: dividends are reinvested in the index, so a level already
  includes them. Catalog v45 to v52 called the series "a price index, not total
  return", which B3 contradicts; v53 corrects it. A caller who wants the
  like-for-like stock series reads `close_total_return` from `quote_history`,
  never `close_adj` (price only). A price-return version, where B3 has one
  (IDIV B3 Price Return), carries its own name and is not on this endpoint.
- **Ingest.** `B3Ingestor.ingest_index_levels`, the third source of
  `run_b3_events` (audit `b3` / `index_levels`). It refetches every year of every
  configured index every night (about 250 calls for the nine codes, a few
  minutes): the upsert rewrites only rows that changed, so there is no backfill
  mode, the first run after a code is added loads its whole history, and a B3
  correction heals itself. It validates the whole series before any write.
  **A null `results` is retried** (3 attempts with backoff, the fetcher's
  `max_retries`) because B3 answered null once for a year it serves (UTIL 2012,
  2026-10-03). **A null on every attempt for a configured index is an error**
  (B3 answers HTTP 200 for a code it does not publish, and for any year it has
  nothing for), never an empty year; the one exception is the current year in
  the first ten days of January, before its first session. It sits in `run_b3_events`, not
  `run_daily`, for the reason #450 moved the other B3 calls there.
- **Levels are as published and the series is not adjusted.** B3 re-scaled IBOV
  eleven times (divided by 100 on 1983-10-04 and by 10 on ten other sessions,
  the last on 1997-03-03); `divisor_step` is TRUE on the first session after
  each. The list is `INDEX_DIVISOR_STEPS` in `src/pipeline/ingest_b3_index.py`,
  and the ingest refuses any other one-session move beyond a factor of two, so a
  new step is reviewed before it is served. +36% on 1991-02-04 is a real move.
- **Index codes only.** The accepted codes are those the table holds, so a
  ticker, BOVA11 (an ETF) and IBOV11 (the options settlement leg) all raise
  `22023` naming the codes held.
- **Paging.** Date cursor like `quote_history`; IBOV from 1968 is 15 pages. The
  tape-start refusal of `quote_history` does not apply. `coverage()` has an
  `index_history` row with the depth of each index in its notes.
- Grants follow `quote_history`: DEFINER with an empty `search_path`, revoked
  from `PUBLIC`, granted to `anon` / `authenticated` / `silo_api`. No client
  role can read `b3_index_level`.

### The fixed-income ETFs: B3's FORWARD segment (catalog v65)

`api.trade_consolidated_history(p_ticker, p_from, p_to, p_after)`
(`32_api_trade_consolidated.sql`; research #606,
`docs/reference/research/portfolio-return-coverage.md`) serves
`b3_trade_consolidated` (migration 57): B3's TradeInformationConsolidatedFile,
segment FORWARD only. That segment holds the 46 Brazilian fixed-income ETFs that
COTAHIST does not carry (IMAB11, B5P211, IRFM11, LFTS11, ...) and 21 other
tickers (67 on 2026-09-29), so `quote_history` and `panel` have nothing for them.

- **Columns, as published:** ticker, trade_date, isin, segment, min_price,
  max_price, avg_price, last_price, ref_price, oscillation_pct, trade_count,
  quantity, notional_brl, file_status, source.
- **The close is `last_price`.** `ref_price` is B3's reference price, not a trade
  and never a close: a session with no trade carries only `ref_price`, and
  `last_price` (with the other prices, count and volume) is NULL there.
- **No opening price.** The file has none, so there is no open column, and none
  is ever filled from another source.
- **`notional_brl` is not comparable** with COTAHIST's volume or B3's BDI
  (migration 57: BOVA11 on 2026-09-29 is R$587,459,700.14 here against
  R$588,765,462.41 in COTAHIST).
- **Not adjusted for distributions.** A return from `last_price` is a price-only
  return: it understates the real return of an ETF that distributes income (many
  fixed-income ETFs pay coupons); for one that reinvests the difference is small.
- **Retention.** The source's oldest session was 2025-06-10 when checked on
  2026-09-30, so history starts there.
- **Tickers held only.** A ticker not in the table, a COTAHIST ticker included,
  raises `22023` saying the function holds only the FORWARD segment and pointing
  at `quote_history`; it never returns an empty set. A NULL window also raises.
- **Paging.** Date cursor like `quote_history` and `index_history`.
  `coverage()` has a `trade_consolidated_history` row (first session held, landed
  from the `b3` / `trade_consolidated` audit rows).
- Grants follow `index_history`: DEFINER with an empty `search_path`, revoked
  from `PUBLIC`, granted to `anon` / `authenticated` / `silo_api`. No client role
  can read `b3_trade_consolidated`. Executed checks:
  `tests/sql/trade_consolidated_history_behaviour.sql`.

### The portfolio reads (catalog v51, v54, v61, v63, v66, v67, v68)

Nine functions for the portfolio-diagnosis engine (`31_api_portfolio.sql`;
map #510, `docs/reference/research/portfolio-diagnosis-phase0.md`): three since v51,
`portfolio_movement` since v54, `portfolio_instruments` and `portfolio_fund_terms`
since v61 (`portfolio_instruments` serves a CRA or CRI ISIN since v67), `portfolio_fee_peers` since v63,
`class_return_distribution` since v66 and `portfolio_equivalents` since v68.
All are raise-only on the one 1000-row page and anon-callable like the rest of
`api`. Seven take a set of funds, codes or lines; `class_return_distribution` takes
one ANBIMA class as filed and `portfolio_equivalents` a set of them. None is a name search that guesses.

- **`api.portfolio_resolve(p_names, p_cnpjs, p_quotas, p_quota_dates)`**: one row
  per line and candidate (up to 5, `rank`), arrays parallel, at most 200 lines
  (more is `22023`). A CNPJ the line carries wins (`match_kind` `cnpj`); else
  (catalog v56) a name that is exactly a ticker of the curated ETF registry
  (`cvm_etf_registry`) gives that ETF's CNPJ (`etf_ticker`, one candidate, never
  ambiguous: `api.lookup` returns no CNPJ for a ticker, and a fixed income ETF is
  not in COTAHIST); else an exact match, case and accents ignored, on **any name the fund ever filed**
  (`exact_current`, or `exact_history` for a former legal name); else trigram
  over the whole name history (`similarity`, 0.25 floor). The history is
  `mv_fund_name_history`: `cvm_fi_cda_fund_name` since 2005 plus the registry
  name, rebuilt by every analytical apply. A current-names-only trigram found the
  right fund 1 time in 10 on an obsolete name (Phase 0, 2026-10-03). A statement
  quota with its date is compared with `cvm_fi_diario.vl_quota` on that exact
  date; within 0.5% ranks first (the XP Bancos master and FIC, same words,
  quotas 1.952607 and 1.542011 on 2026-09-30). `ambiguous` is TRUE on every row
  of a line whose top two candidates are within 0.05 and the quota does not
  separate them: the line is unresolved, `reason` says why, nothing is picked.
  Unaccenting is a fixed `translate()` map (`unaccent` is not installed on
  Supabase). No indexer, sector or economic group is ever inferred from a name.
- **`api.portfolio_fees(p_cnpjs, p_month)`**: per CNPJ, the **disclosed** fee
  (`disclosed_*`: the CVM **Extrato** first, `cvm_fi_extrato` newest version, a fee
  for 84.3% of active FI funds; else the lâmina, `cvm_fi_lamina` newest reference
  month; else cad_fi `taxa_adm` / `taxa_perfm` from `cvm_fund_registry`. One source
  per fund, named in `disclosed_origin` (`extrato` | `lamina` | `cad_fi`) and
  `disclosed_source`, with `disclosed_as_of` (the filing date),
  `disclosed_age_months` and `disclosed_age_days`; NULL is not a zero fee; lâmina
  classes with different fees give a NULL single value, a min, a max and a note).
  Two reading rules on the single administration fee (% a year as filed): a filed
  **0** is returned as 0 with `filed_zero` TRUE (read it as "not informed", never as
  a zero cost; 16.7% of the Extrato's values are 0 and the balancete books a fee for
  most of those funds), and a filed value **above 5** (or below 0) is not the fee:
  `disclosed_taxa_adm` is NULL, `implausible_filed` is TRUE and the value as filed is
  in `taxa_adm_filed_raw`. The stored value is never rewritten. An Extrato row that
  exists is the source even then; it does not fall through to an OLDER source.
  Catalog v55 (#552): when the Extrato filed exactly 0 or above 5, the lâmina's single
  fee is in (0, 5] and the lâmina is NEWER than the Extrato, the newer lâmina is the
  source. `fee_resolution` names the rule that applied (`extrato`,
  `extrato_lamina_beside`, `extrato_to_check`, `lamina_newer`, `lamina`, `cad_fi`).
  The other document's fee comes back as filed for every fund (`lamina_taxa_adm`,
  `_min`, `_max`, `lamina_n_classes`, `lamina_age_months`; `extrato_taxa_adm_filed`
  with `extrato_as_of`), with `extrato_lamina_ratio` and `extrato_scale_factor` (10 or
  100 when an Extrato above 5 equals that factor times the lâmina within two-decimal
  rounding: a flag, never a correction). A fund whose `fee_resolution` is
  `extrato_lamina_beside` or `extrato_to_check` is to be checked: sum neither value.
  For `lamina_newer` the newer lâmina's fee is a disclosed fee like any other: use it
  as the cost, sum it and compare it with the estimate (owner, 2026-10-03, catalog
  v56); keep the fund flagged because the two documents disagree, and never sum the
  Extrato value beside it. These 10 columns are appended after `lamina_expense_note`.
  Catalog v56, ETFs: CVM's Extrato, lâmina and cad_fi hold no fee for any of the 178
  active registry ETFs (measured 2026-10-03), so five columns follow
  `extrato_scale_factor`: `etf_ticker` (the CNPJ's ticker in `cvm_etf_registry`) and
  `etf_site_taxa_adm`, `etf_site_as_of`, `etf_site_source`, `etf_site_note`, the
  "Taxa de administração total" etfsbrasil.com.br prints (`etf_market_snapshot`, the
  newest snapshot with a fee, joined by ticker; 171 of 178 tickers on 2026-10-03,
  BOVA11 0.10, IVVB11 0.23, B5P211 0.20). A third-party value, never in
  `disclosed_*`, returned as published.
  Catalog v57: CVM has no 2026 daily report row (no cotistas, no PL) for any registry
  ETF either, so two columns follow `etf_site_note`: `etf_site_nr_cotistas` and
  `etf_site_pl` (R$), the site's "Número de cotistas" and "Patrimônio líquido" from
  the SAME snapshot row as the fee, dated by `etf_site_as_of` (on 2026-10-03: BOVA11
  106,027 and R$ 15.32 bn; IVVB11 241,779 and R$ 7.78 bn; B5P211 43,321 and
  R$ 4.33 bn). The site prints PL in R$ millions with two decimals, so it resolves to
  R$ 10 thousand. Descriptive third-party facts: never summed, never a fee base.
  Catalog v68 (#606 Q36): the filed benchmark, whatever the fee source, as filed.
  `benchmark_extrato` is the Extrato's `PARAM_TAXA_PERFM` (the index the performance
  fee is measured against; the Extrato has no other benchmark column, and
  `extrato_param_taxa_perfm` stays NULL when the Extrato is not the fee source),
  dated `extrato_as_of`. `benchmark_lamina` is the lâmina's `INDICE_REFER` at
  `lamina_as_of` when every class filed the same non-blank value, and
  `benchmark_lamina_n` counts the distinct values (0 none, above 1 the classes
  differ). Nothing is matched or normalised in SQL: the engine's versioned rule file
  (`src/portfolio/rules/benchmark_cdi.yaml`) decides which spellings are CDI.
  The Extrato's own fields come back as filed (`extrato_taxa_perfm` numeric with
  `extrato_param_taxa_perfm`, `extrato_calc_taxa_perfm`, `extrato_inf_taxa_perfm`;
  `extrato_existe_taxa_ingresso` / `_saida` with `_pr` percent and `_real` reais;
  `extrato_taxa_custodia_max`; `extrato_tp_fundo_classe`, `extrato_classe_anbima` and
  `extrato_class_note`: a CVM 175 row is the class, there is no subclass column).
  `lamina_pr_pl_despesa` (with `lamina_dt_ini_despesa`, `lamina_dt_fim_despesa`,
  `lamina_as_of`) is the lâmina's declared total expense ratio, whatever the fee
  source, never added to the administration fee. Catalog v52 appended these 25
  columns after `estimate_label`; the 21 before it are unchanged. Beside them sits
  a separate **estimate** from the balancete accruals
  (`adm_fee_flow`, `perf_fee_flow`, `*_pct_annual_est`, `estimate_label`). The
  fee accounts accumulate from each fund's fiscal-year start and are filed
  negative: accrual = previous minus current accumulated value, times 12 over NAV
  (groups 6 + 7 + 8), served positive. In the reset month the accumulated fee
  falls: `fiscal_reset_suspect` is TRUE and the estimate NULL, unless cad_fi
  `DT_INI_EXERC` confirms the fiscal year starts that month, when the month's
  accumulated value alone is the accrual. The estimate is never the disclosed fee.
- **`api.portfolio_lookthrough(p_cnpjs, p_month, p_max_depth)`**: one CDA month
  (default: the last month whose block-2 filing count reaches 90% of the median
  of the 12 before it, the `/holdings` rule; 2026-05 on 2026-10-03), block 2
  followed recursively from each root (`WITH RECURSIVE ... CYCLE`, depth 1..6,
  default 4) to the assets of blocks 1 (government bonds; repo collateral apart
  as `repo`), 4 (stocks, debentures with `issuer_code` = ISIN characters 3-6) and
  6 (private credit, `issuer_cnpj` only for a PJ, indexer as filed). Weights are
  value over the holder's `fact_fund_monthly` NAV of the same month, multiplied
  down the path; a fund reached by two paths appears once per path, sum
  `weight_in_root` over every row but `fund_quota`. Blocks 3, 5, 7, 8 are not
  ingested, so weights need not sum to 1. Measured on production 2026-10-03: XP
  Bancos FIC 50088190000119 is 3 quota levels deep at 2026-05 (master
  35377390000106 R$1,832.6M, XP Cash S1 54891935000134, Santander Cash Black
  37525998000158), BB RF CP Automático FIC 42592315000115 is 1 level
  (R$198,595.9M); the recursion read 37 buffers. Every read of the 12 GB and 10 GB
  CDA tables is an index probe on `(cnpj, period, ...)`.
- **`api.portfolio_movement(p_cnpjs, p_month)`** (catalog v54): is a fund's month
  unusual for its own class (*movimento incomum*, owner's decisions of 2026-10-03).
  Per CNPJ and one month (default: `latest_complete_period('fi')`, 2026-09 on
  2026-10-03; an incomplete month is `nao_avaliado` for every fund), the fund's
  monthly **quota return** `own_value_pct = (month-end vl_quota / previous month's - 1) x 100`
  from `fact_fund_monthly` (the one stable quota subclass the matview follows; NAV
  is not used, a NAV change is mostly flows) is set against the same return over
  every FI fund of its **ANBIMA class as filed in the CVM Extrato**
  (`vw_fi_extrato_latest.classe_anbima`, the Extrato's newest filing, not the class
  on the month's date; `class_as_filed` is the peer group, `class` and `subclass`
  split that label at its first `' - '` for display; nothing is read from a fund's
  name). `class_mean_pct` and `class_sd_pct` are the mean and sample standard
  deviation of the peers' returns **winsorized at the class's own 1st and 99th
  percentile** of that month (`class_p01_pct`, `class_p99_pct`); the fund's own value
  is not winsorized. `z = (own - mean) / sd`. `level` is `forte` when `|z| > 3`
  (`investigator_trigger` TRUE, goes in the report's text), `atencao` when
  `|z| > 2` (a table only) and `normal` otherwise, strictly greater (exactly 2 is
  normal, exactly 3 is `atencao`); `nao_avaliado` with a Portuguese `reason` when
  the class has fewer than `min_peers` (30) funds with a return, its standard
  deviation is 0, the fund has no class (outside the Extrato, which covers about
  84% of the active FI funds, or no `classe_anbima`), no return (no positive quota
  in both months, or a quota-subclass change), is an ETF, a FIDC, FII, FIP or
  FIAGRO, or the month is incomplete. There is no fallback to a wider class. One
  row per distinct CNPJ, at most 200. Measured on production 2026-10-03 over six
  months (2025-12 to 2026-09), among the roughly 20,900 fund-months evaluated
  each month (about 83% of the FI funds with a return; the rest have no class,
  0.9% too few peers): `|z| > 2` flags 5.2% to 5.7% and `|z| > 3` 2.4% to 2.9%
  (5.6% and 2.7% in 2026-09), below the 10% and 6% of the owner's measurement of
  the same day, whose query is not on record; the five largest classes answer in
  0.5 s against anon's 3 s timeout. It states a number, a class, a sample size and
  a month: not a forecast, a verdict or a recommendation.
- **`api.portfolio_instruments(p_codes)`** (catalog v61): a statement's credit
  instruments by code. Each code is trimmed, upper-cased and loses a leading `CRA-`,
  `CRI-` or `DEB-` (the hyphen is required: `CRA0260025T` keeps its `CRA`).
  `match_kind = 'securit_cetip'`: every series of `cvm_securit_serie` whose
  `codigo_cetip` is the code, at the code's newest `data_referencia`, one row per
  (`numero_serie`, `classe`) at its highest `versao`, with `instrument_type`
  (`cra_mensal` / `cri_mensal`), `cnpj_securit`, `data_vencimento`, `situacao`,
  `taxa_juros` (text), `classificacao_risco_atual` and `valor_total_integralizado` as
  filed; since v67 also `cd_isin`, the series' `codigo_isin` as filed and not validated
  (NULL when not filed; B3 Fundos.NET finds a CRA or CRI document by ISIN, never by
  CETIP code), while `issuer_code` stays NULL (a CRA or CRI ISIN names the
  securitizer, not the debtor). Else `'cda_ticker'`: a debenture in CDA block 4 (`tp_aplic = 'Debêntures'`)
  at the newest month the code appears in (`cda_period`), with `cd_isin` (the most
  common ISIN), `issuer_code` (ISIN characters 3-6, never a CNPJ), `n_fundos` and
  `preco_marcacao_fundos` = sum of the funds' market value / sum of their quantity
  (their own mark, not a trade price). A code held that month as something else
  (a stock) is no match, and the reason says what it was held as. Else one row with
  `match_kind` NULL and a Portuguese `reason`. Measured 2026-10-05 on the 15 codes
  of the pinned statement: 9 CRA/CRI, 3 debentures (ORIG21, ENAT11, CUTI11), 3 in
  neither table; 228 ms warm for the body. Migration 73 indexes
  `cvm_securit_serie (codigo_cetip, data_referencia DESC)`. At most 200 codes.
- **`api.portfolio_fund_terms(p_cnpjs)`** (catalog v61): one row per input CNPJ.
  `gestor_id` (a CNPJ or a CPF), `gestor_name`, `admin_cnpj`, `admin_name` as filed
  in `cvm_fund_registry`; a CNPJ with several registry rows uses the one with
  `is_active`, then no `dt_cancel`, then the newest `dt_cancel`, `fetched_at`,
  `entity_type`, and the reason names it. Redemption terms (`qt_dia_conversao_cota`,
  `qt_dia_pagto_resgate`, `tp_dia_pagto_resgate`, `qt_dia_resgate_cotas` = lock-up)
  from the CVM Extrato (`terms_source = 'extrato'`, `terms_dt_comptc` = the filed
  version's date), else, only when there is no Extrato, from the lâmina
  (`'lamina'`; `QT_DIA_CONVERSAO_COTA_RESGATE` and `QT_DIA_CAREN` mapped by name to
  the same meanings; the row with no subclass, else the newest). As filed, NULL when
  not filed, never zero. A FII, FIDC, FIP or FIAGRO is in neither document (the
  Extrato holds only FI and FIF classes) and the reason says so. 24 ms cold for the
  12 pinned CNPJs. At most 200 CNPJs.
- **`api.portfolio_fee_peers(p_cnpjs, p_as_of)`** (catalog v63; ETF peers v66,
  #609): a fund's administration fee against the active FI funds of its exact
  ANBIMA class, FUNDO_COTAS and document scope (method:
  [`fee-peer-comparison.md`](portfolio/fee-peer-comparison.md)). Since v66 ETFs enter
  the group: CVM files no ANBIMA class for an ETF, so an active ETF joins a class
  only when its `underlying_index` is mapped to it in
  `src/portfolio/rules/equivalents/class_index.yaml` (owner-reviewed, generated into
  the internal view `public.portfolio_class_index` by
  `scripts/gen_class_index_sql.py`), and it is a peer in every FUNDO_COTAS and scope
  cell of that class, once per CNPJ. Its fee is the third-party etfsbrasil value
  (`etf_market_snapshot.taxa_adm_pct`, newest snapshot dated no later than
  `p_as_of`, the same `0 < fee <= 5` and 36-month rules), never a CVM-disclosed fee.
  Seven columns appended: `n_fund_peers`, `n_etf_peers` (`n_peers` is their sum and
  the statistics are over both), `n_etf_excluded`, `etf_peer_tickers`,
  `etf_peer_fee_oldest` / `_newest` and `etf_peer_fee_source`, which says the ETF fee
  is a third-party site's. Still at least 30 usable fees, no wider fallback.
- **`api.class_return_distribution(p_classe_anbima, p_fundo_cotas, p_month)`**
  (catalog v66, #609): what an equivalent ETF's return is set against. Two rows,
  `window_months` 12 and 6, ending at the close of `p_month` (NULL = the last
  complete FI month). Funds: FI funds whose newest Extrato files exactly that class
  and FUNDO_COTAS (S or N), active as in `portfolio_fee_peers` (`n_universe`). Return
  = closing quota of `end_month` over that of `start_month`, minus 1, from
  `fact_fund_monthly`'s stable quota subclass (the quota `fund_nav` serves, net of
  the class's fees, research #610). `p25_pct`, `median_pct`, `p75_pct` over the
  `n_funds` returns; `n_excluded_no_quota` and `n_excluded_subclass` count the
  excluded funds. Fewer than 30 funds or an incomplete month: `nao_avaliado`, NULL
  statistics and a reason, never a wider class. ETFs are not in the universe.
  Measured 2026-10-05 (bounded SELECT of the same query, 0.19 s): 17 active funds
  in `AÇÕES - ATIVO - SMALL CAPS` / N, so that class is not evaluated today.
- **`api.portfolio_equivalents(p_classes, p_as_of)`** (catalog v68, #609): the
  market equivalent of an ANBIMA class. For each class as filed (1 to 50), the active
  ETFs (`cvm_etf_registry.is_active`, one row per CNPJ, the fee-peer universe) that
  track an index the reviewed list maps to the class (only `status = aprovada`
  pairs of `public.portfolio_class_index`, read in reverse); `class_indices` and
  `n_etfs` say which and how many. `pl_brl` / `pl_as_of` and `fee_pct_year` /
  `fee_as_of` are the third-party etfsbrasil values (`etf_market_snapshot.nav` and
  `taxa_adm_pct`, each the newest snapshot that has one dated no later than
  `p_as_of`), the same ones `portfolio_fees` serves as `etf_site_*`. `is_equivalent`
  marks the largest by PL across all of the class's indices (`pl_rank` 1, ties by
  ticker); an ETF with no PL is never ranked. `segment` is the registry's:
  `fixed_income_br` prices are in `trade_consolidated_history`, the others in
  `quote_history`. A class with no approved pair (`sem_par`) or no active ETF
  (`sem_etf`) is one row with NULL ETF columns; with no PL anywhere every row is
  `sem_pl`. Measured 2026-10-05: `RENDA FIXA SIMPLES` and
  `RENDA FIXA BAIXA DURAÇÃO - SOBERANO` give BLFT11 (R$ 13.82 bn, TEVA LFT Curto
  Prazo), `AÇÕES - ATIVO - SMALL CAPS` SMAL11 (R$ 2.79 bn), `AÇÕES - ATIVO -
  DIVIDENDOS` DIVO11 and `AÇÕES - ATIVO - SUSTENTABILIDADE / GOVERNANÇA` ISUS11.
  It names an ETF with the same objective, not a recommendation.
- A merge deploys nothing: the functions go live on the next analytical apply
  (`daily_ingest` `mode=analytics-only`), the MCP tools after `deploy_mcp.yml`.

### Using the research seam

The caller-facing guide is [`api-docs/guides/research.mdx`](../../api-docs/guides/research.mdx)
(published as "Pulling a research universe"): the survivorship rule
(`first_observed <= T <= last_observed`, a pair inside a gap such as NATU3 still
matches, a rename is two rows), `close_adj` and total-return prices with what each
refuses or leaves NULL, the 2019-01-02 floor, the `index_history` warnings (BOVA11
and IBOV11 are not the index, eleven divisor steps), the as-of fundamentals recipe
and macro by date split. The SDK side is `prices()` (many tickers from one data
revision, every refusal named), `research_universe(as_of=)` and
`index_history` / `iter_index_history` / `index_history_all`.

### The total-return close (catalog v46)

`close_total_return` is a `quote_history` field (select it in `p_fields`,
catalog v48): `close_adj` with cash distributions reinvested on the ex session,
anchored to the instrument's latest session like `close_adj`. The level is
divided by the product of `1 + cash / ex-session close` over every distribution
that went ex after the session. The latest session equals `close_adj`, and an
earlier level is lower by the cash paid since. Unlike `close_adj` it never
refuses: a session it cannot value is NULL with a reason.

- **Cash** is B3's full history (`b3_cash_dividend`): `DIVIDENDO`, `JRS CAP PROPRIO`
  (gross of withholding tax), `RENDIMENTO` and `REST CAP DIN`. Installments are
  identical history rows and each counts once (PETR4 2026-06-01: two JCP of
  0.35048636). A distribution counts only where its ISIN is resolved against the
  tape and B3's published pre-ex close agrees with the tape's close (7,459 of 8,190
  since 2019, all 7,459 agreeing on 2026-09-30).
- **The ex session** is the ISIN's first printed session after the last cum session,
  within 7 calendar days. A paper that does not print within a week has no price to
  reinvest at (189 events print 30+ days later, all in the research universe).
- **Where it is NULL**, each with a reason in `close_total_return_null_reason`: `close_adj`
  cannot be served for the session (the same causes it refuses for); the ISIN has no resolved distribution in B3's history
  (a non-payer, or an issuer B3's history does not match: the two look identical, so
  neither is given a price return labelled as a total return; 188 of 639 universe
  ISINs on 2026-09-30); a later distribution of the issuer's share class has no proven
  ISIN (731 events, 53 issuers, hitting 101 of 639 tickers, none of the large caps);
  a distribution B3's supplement lists is missing from the history (48 from September,
  which the history had not caught up with, and 3 older holes: FRAS, BRST); a later
  distribution has no ex-date close within 7 days.
- **Why a matview.** `vw_b3_cash_dividend_isin` resolves every distribution's ISIN
  with a dated join into the tape: 5.3 s over all rows, and an ISIN filter cannot be
  pushed down (`anon` has a 3 s timeout). `mv_b3_cash_event` (migration 56, no client
  grant) holds the events once, refreshed by `22_b3_tape_matviews.sql` (about 7 s).
- **Overlap check** (the lag and the holes are countable at any time):

```sql
SELECT kind, count(*) FROM mv_b3_cash_event GROUP BY kind ORDER BY 2 DESC;
SELECT issuing_company, isin, action, event_date FROM mv_b3_cash_event
WHERE kind = 'pending' ORDER BY event_date DESC;
```

### The tape starts at 2019-01-02

`api.quote_history` refuses (`22023`, `DETAIL reason=outside_coverage`) a window
that starts before the instrument's first session on the tape, and one that holds
no session of it at all; for an instrument that traded on the first session of the
tape, the message names the tape start (the research price contract, catalog v48).
The refusal is read from the data, as the first session of the cash tape, not from
a literal. Below that date the adjusted and total-return closes would be built on
corporate events and cash distributions nobody swept, and a window that started
earlier would come back beginning on 2019-01-02 and look complete.

Three literals still have to agree with that first session, and
`tests/test_quote_history_tape_window.py` pins them to one date: the corporate-event
sweep (`B3Ingestor.TAPE_START`), `mv_b3_cash_event` (migration 56) and
`mv_research_universe`.

- **2019-01-01 is refused** for an instrument already trading on 2019-01-02. It is
  a holiday with no session, so nothing would be lost, but the rule is the
  instrument's first session. The documented examples use 2019-01-02.
- **`api.coverage()` says so** in the notes of its `quotes` row, read from the tape.
- **`api.index_history` is not bound by it:** IBOV is held from 1968-01-02, and
  each other index from its own first session.
- `serve/` maps the `22023` to a caller error like every other refusal.

### Fundamentals as of a date (catalog v47)

`financials`, `company_financials`, `income_statements`, `balance_sheets` and
`cash_flow_statements` take a trailing `p_as_of DATE DEFAULT NULL`, carried by
the shared internal reader `api.cia_statement_rows`. NULL is unchanged and now
labelled not point-in-time. A date T reads only the documents CVM received
before T (`cia_filing.dt_receb < T`, the exact `(cd_cvm, doc_type, dt_refer,
versao)` header; a document received on T is out and one with no header is
dropped), keeps the highest remaining version of each and all its lines. The
filter sits before the `MAX(versao)` window, so the version kept is the highest
one known at T. No new function and no new column: rows already carry `version`,
and `financial_statement_history` shows `filing_received_date` for every stored
version. The recipe is #375's (`docs/reference/research/pit-fundamentals.md`).

The old signatures are dropped, because an old overload beside a new one makes
the RPC ambiguous for PostgREST. Measured on production 2026-09-30, read-only:
PETR's DFP 2023 v1 was received 2024-03-08 and the ITR 2023-09-30 on 2023-11-09,
so `as_of = 2024-02-29` returns that ITR; the filter costs about 450 ms over six
years of PETR's consolidated lines.

### DI futures and B3 reference curves (catalog v42)

`api.future_curve`, `api.future_series`, `api.curve` and `api.curve_history`
(`27_api_rates.sql`) serve the two B3 landing tables of migration 48
(`b3_futures_settlement`, `b3_reference_rate`; `INSTRUMENTS.md` phases B and C,
typed endpoints only). Caller documentation:
[DI futures and B3 reference curves](https://octo-98895abd.mintlify.site/api-docs/rates).
The operator half:

- **Nothing is derived** except `contract_month`, read from the ticker with
  B3's month letters (the same `_MONTH_LETTERS` the Price Report parser keeps
  outright contracts with). DI1 is quoted in rate, so the quote columns are
  % a.a.; `settlement_price` is the PU.
- **`curve` / `curve_history` read only the curves in `api.curve_registry()`**,
  which `tests/test_rates_contract.py` pins to `DEFAULT_CURVES` in
  `src/parsers/b3_taxa_swap.py`, with each curve's `rate_basis` (`DOC` is
  linear on 360 days). Add a curve to the ingest and the test fails until the
  registry follows.
- **`curve_history` serves B3's fixed vertices only**, by nominal tenor
  (`vertex_code`); any other tenor is refused with the list. Its access path
  is `idx_b3_reference_rate_fixed` in `11_indexes.sql` (partial, `vertex_type =
  'F'`); without it a tenor's history reads every vertex of every session.
- **The long end is B3's extrapolation** (Manual de Curvas v21): the function
  comments, the `coverage()` notes and the docs page say so. Where the tail
  starts is left to research code (`research_examples/dustin_br/`).
- Grants follow `macro_series`: DEFINER with an empty `search_path`, revoked
  from `PUBLIC`, granted to `anon` / `authenticated` / `silo_api`. All four are
  raise-only above one page. `coverage()` gains `di_futures` (landed_at from
  `market` / `b3_price_report`) and `reference_curves` (`market` /
  `b3_reference_rate`).
- The futures arm of `api.panel`, which `INSTRUMENTS.md` phase B also lists,
  came in catalog v61: `id_type='future'`, `asset_class` `derivative`, source
  `b3_price_report`. Its metrics are `settlement_rate` (the default), `settlement_price`
  and `open_interest`, not one `settlement`: DI1 publishes both a rate and a PU.
  Only a settlement B3 marks final (F) is served, because the panel has no status
  column; 23 sessions from 2018-02 to 2018-05 are P and stay in `future_series`.

### Row caps refuse, and say why (catalog v34)

`fidc_cedentes`, `fidc_sacados` and `fidc_portfolio` used to trim **silently**
at a tier ceiling (500 rows anonymous, 5,000 signed in): a result over the
ceiling came back short with a 200. Since v34 they are raise-only on the one
1000-row page like every other capped function (twenty-five in all,
`catalog().limits.page.all`): the page CTE fetches 1001 rows and
`api.assert_row_cap` raises `22023` above 1000. Their `*_rows` entries left
`limits.tiers`; the tier time budget (3 s / 8 s) is unchanged. `p_limit` stays
in the signature as an **explicit** newest-first head: 1..1000 is served as
asked, `NULL` or anything above one page means the whole window (served whole
or refused), and `< 1` is `22023` rather than a silent clamp to 1. Nothing in
`dashboard/` or `webapp/` calls these functions (the Evidence sources read the
landing tables directly), so no page relied on the trim.

### The holdings pair stops trimming (catalog v41)

`fund_holdings` and `fund_debentures` were the last two functions that trimmed
**silently** at a tier ceiling (500 rows anonymous, 5,000 signed in). The
silo-mcp server always calls as anonymous, so a ticker held by more than 500
funds, or a fund's full history, reached an agent short and looking complete.
Since v41 both follow the v34 pattern exactly: the page CTE fetches 1001 rows,
`api.assert_row_cap` raises `22023` above 1000, `p_limit` is an explicit
newest-first head (1..1000; `NULL` or above one page is the whole window;
`< 1` is `22023`), and their `*_rows` entries left `limits.tiers`. The capped
count is thirty-nine. The fix for a refusal is a narrower `p_from`/`p_to` (a
`p_ticker` / `p_issuer` lookup spans many funds, so it needs fewer months than
one fund's holdings) or an explicit `p_limit`. Nothing in `dashboard/` or
`webapp/` calls either function.

`api.assert_row_cap` now builds its message centrally from the function name:
`<fn>: refused, this request would return more than 1000 rows.`, then the
**why** (one 1000-row page; SILO never returns a silently truncated result),
then `To fix:` and the **how** for that function (the cursor for `panel` /
`quote_history` / `fund_nav`, thresholds for a `screen_*`, the window or
`p_limit` for the FIDC trio, the window otherwise). The same two halves go out
as `DETAIL` and `HINT`, which PostgREST returns as `details` / `hint`; the SDK's
`SiloOverCap.server_hint` carries the latter. "more than 1000 rows" is
load-bearing: `SiloOverCap` matches on it.

### Lineage: which code produced this data (catalog v34)

Migration `44_ingest_lineage.sql` adds `git_sha` and `parser_version` to
`cvm_ingest_log`. `git_sha` is `GITHUB_SHA` (set on every Actions run), `NULL`
when unset — never invented and never read off the working tree.
`parser_version` is `src.pipeline.ingest_log.PARSER_VERSION`, bumped only when
a parser or field map changes what a stored value means. Every audit writer
stamps both: the shared `src/pipeline/ingest_log.py` (ANBIMA, B3, BACEN, IBGE,
FNET) on start and finish, and CVM's own writer in `cvm_pipeline.py` on its
start upsert and finish `UPDATE`. `api.coverage()` gains a trailing typed
column `landed_git_sha`: the `git_sha` of the very run that set `landed_at`
(newest finished `ok` row, `id` breaking a tie). A `NULL` there is served as
`NULL`, never borrowed from an older run. `/v1/coverage` forwards it.

### The B3 lending and investor-flow views

Five public views — `short_interest`, `short_interest_by_sector`,
`investor_flow`, `lending_trades` and `lending_participants` — have no `/v1`
twin either. They are documented on the published site: [Securities
lending](https://octo-98895abd.mintlify.site/api-docs/lending) and [Investor
flow](https://octo-98895abd.mintlify.site/api-docs/flows), with first-class SDK
methods since catalog v27.

They were parked in this file while nothing else covered them. That is no longer
true, so the caveats live with the pages that own them rather than here.

### The forensic screens

The seven `api.screen_*` functions (catalog v31, `23_api_screens.sql`) have no
`/v1` twin and `silo_api` holds no grant on them — the same decision as the
lending views. They wrap the public `fraud_screen_*` / `fidc_delinquency_drivers`
functions the dashboard reads (`15_fraud_screens.sql`), so there is one
definition of each screen. Caller documentation, including the "signals, not
verdicts" contract and what each screen cannot tell apart, is
[Forensic screens](https://octo-98895abd.mintlify.site/api-docs/screens).

Operator half: the public functions were `GRANT EXECUTE … TO anon,
authenticated` until v31 and reachable only because `public` is not an exposed
schema. They are now revoked from `PUBLIC`, `anon` and `authenticated`, and
`23_api_screens.sql` fails the apply if either client role can still execute
one. The Evidence build is unaffected: it connects as the `postgres` login
(`EVIDENCE_SOURCE__supabase__user`), which owns them.

### The filing-behaviour screens

`api.screen_restatements`, `api.screen_late_filers` and `api.screen_silent_filers`
(catalog v37, `25_api_filing_screens.sql`) follow the same contract as the seven
above — signals, `screen` + `params` on every row, raise-only above one page, no
`/v1` twin, no `silo_api` grant — but are native functions, not wrappers: no
dashboard page runs them, so the API function is the one definition. The two
FNET screens know a fund only by its `cnpjFundo` link. `screen_late_filers`
measures the first FNET delivery of the monthly informe against the deadline
Resolução CVM 175 states (FIDC: Anexo Normativo II, art. 27, III; FII: Anexo
Normativo III, art. 36, I — 15 days after month end; text read 2026-09-25) and
only from the first full month after each family's adaptation deadline (2024-12
FIDC, 2025-07 FII); the citation is on every row. `screen_silent_filers` reads
`dim_fund` against `latest_complete_period`, not FNET. Caller documentation:
[Filing-behaviour screens](https://octo-98895abd.mintlify.site/api-docs/filing-screens).

## Run

```bash
bash scripts/apply_analytical.sh    # creates api.* after ingest
python -m serve.app                 # 127.0.0.1:8080
curl -s localhost:8080/v1/quotes/PETR4
```

`serve/` needs `POSTGRES_URL` or `SILO_API_DATABASE_URL`. If it is ever hosted,
point `SILO_API_DATABASE_URL` at a login member of the **read-only** `silo_api`
role (created by `12_grants_and_rls.sql`; see the operator comment there).
Transaction pooler is correct here; ingest keeps the session pooler / direct URL.

---

## Operator notes on the deployed surface

Caller-facing versions of everything below live on
[Conventions & limits](https://octo-98895abd.mintlify.site/api-docs/conventions#row-caps).
What is kept here is the operator half: the decision, the measurement, and the
levers that are a dashboard setting rather than a code change.

### Enabling it on a fresh project

Supabase Dashboard → Settings → API → add `api` to **Exposed schemas**. The
generic form is `https://<project-ref>.supabase.co/rest/v1/`; views are read as
`/rest/v1/quotes?select=...`, functions called as `POST /rest/v1/rpc/<name>` with
named arguments in the JSON body. The grants in `19_api_contract.sql`
(`anon`/`authenticated`: `USAGE` on schema `api`, `SELECT` on the api views,
`EXECUTE` on the api functions — and nothing on the `public` landing tables) are
exactly the surface this exposes.

### 1. PostgREST caps every response at 1,000 rows (`db-max-rows`)

Found by an independent audit of the live deployment (2026-08-27) and reproduced
against production on 2026-08-28. The measurement that forced the current design:

```
POST /rest/v1/rpc/panel  p_ids=[PETR4] p_metrics=[close] p_freq=day p_to=2026-08-26
  p_from=2019-01-01  -> 1000 rows, 2019-01-02 .. 2023-01-09   TRUNCATED, HTTP 200
  p_from=2022-01-01  -> 1000 rows, 2022-01-03 .. 2026-01-02   TRUNCATED, HTTP 200
  p_from=2024-01-01  ->  664 rows, 2024-01-02 .. 2026-08-26   complete
```

A caller charting "PETR4 since 2019" got a plausible line that simply stopped in
January 2023.

The in-function caps used to `LIMIT` at cap+1 (panel 100001, series 5001) so a
caller could detect truncation by counting one extra row; behind a 1,000-row
ceiling those sentinels could never fire, so the advice to "check for exactly
100001 rows" detected nothing. Both sentinels are gone — panel in catalog v24, the
series and statement functions in v25/v26.

**Current behaviour, and the correction to what this file used to say:** every
set-returning function now fetches one page plus one row and **raises `22023`**
rather than returning a trimmed result. This file previously stated that "a panel
cannot be paged" — that stopped being true two catalog versions ago. **`panel`,
`quote_history`, `fund_nav`, `index_history` and `trade_consolidated_history`
page with a `p_after` cursor**; the others
(`option_history`, `termo_history`, `financials`, `company_financials`,
`anbima_classes`, `inflation`, `inflation_items`, `fidc_tranches`, `fidc_aging`,
`fund_documents`, `fund_restatements`, `fund_restatement_diff`,
`company_events`, `macro_series`, `ptax`, `future_curve`, `future_series`,
`curve`, `curve_history`, `research_universe`, `portfolio_resolve`, `portfolio_fees`,
`portfolio_lookthrough`, `portfolio_movement`, `portfolio_instruments`, `portfolio_fund_terms`,
`portfolio_fee_peers`, `class_return_distribution`, `portfolio_equivalents` and the ten `screen_*` functions) have no cursor and
ask you to narrow the window or send fewer funds. `fund_nav` also
requires `p_entity_type` to page, because its cursor is a bare period and 385
CNPJs file under two families in the same month.

`Range` paging genuinely does not work on RPC — `Range: 1000-1999` on
`/rest/v1/rpc/panel` returns the _same first page_, verified, same
`Content-Range: 0-999/1906`. `Range` / `limit` / `offset` remain the **view**
cursor, and `GET` views on schema `api` still truncate silently, so
`Content-Range` is still the only signal there.

Raising `db-max-rows` (Dashboard → Settings → API → Max rows) is an operator
decision, not a code change.

### 2. The `statement_timeout` that applies is `anon`'s 3s, not `silo_api`'s 15s

`12_grants_and_rls.sql` sets 15s on `silo_api` — but that role serves only this
local adapter. The deployed PostgREST surface runs as `anon`, which carries
Supabase's default 3s (`authenticated` gets 8s). Anything over ~3s returns
`57014 canceling statement due to statement timeout`.

Cold calls are the practical consequence: on a warehouse this size the first call
after idle can take 16–43s and is cancelled at the ceiling, so a first-time caller
meets an API that looks comprehensively down. Warm, the same calls return in
0.3–1.9s. Warming the endpoints, or raising the `anon` timeout, is an operator
decision.

## Why not the alternatives

| Approach                                            | Why not as the user API                                                                  |
| --------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Raw PostgREST on `public`                           | Leaks `cvm_ingest_log`, options tape, Portuguese columns; users must learn the warehouse |
| `supabase.rpc` only, undocumented                   | Fine as a power-user escape hatch; terrible onboarding without the pages and the catalog |
| Revive the old ingest Flask (`app.py` / `src/api/`) | No auth, ingest triggers, localhost-only — mixing operators and readers                  |
| Rebuilding FastAPI microservices                    | Already deleted; duplicates the warehouse                                                |

Roadmap for how "ingested" became "a researcher pulls a panel":
[docs/planning/SERVING.md](../planning/SERVING.md).
