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

### The benchmark index (catalog v45)

`api.index_history(p_index, p_from, p_to, p_after)` (`29_api_index.sql`;
research-seam spec `docs/planning/RESEARCH_SEAM.md` §5, tickets #412 and #415)
serves the daily level of a B3-published index from `b3_index_level` (migration
55). The operator half:

- **Source.** B3's index statistics proxy, `indexStatisticsProxy/IndexCall/
  GetPortfolioDay`, one calendar year per call as a 31 x 12 grid with Brazilian
  decimals (`src/fetchers/b3_index_fetcher.py`). IBOV from 1968-01-02: 14,489
  sessions on 2026-09-30, 2025-12-30 = 161,125.37 (B3's year-end figure).
- **Ingest.** `B3Ingestor.ingest_index_levels`, the third source of
  `run_b3_events` (audit `b3` / `index_levels`). It refetches every year every
  night (59 calls, about a minute): the upsert rewrites only rows that changed,
  so there is no backfill mode and a B3 correction heals itself. It validates the
  whole series before any write. **A null `results` for a configured index is an
  error** (B3 answers HTTP 200 for a code it does not publish, and for any year
  it has nothing for); the one exception is the current year in the first ten
  days of January, before its first session. It sits in `run_b3_events`, not
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

### The total-return close (catalog v46)

`quote_history.close_total_return` is the price-adjusted close with cash
distributions reinvested on the ex session, anchored to the latest session like
`close_price_adjusted`: the level is divided by the product of
`1 + cash / ex-session close` over every distribution that went ex after the
session. The latest session equals the price-adjusted close, and an earlier level
is lower by the cash paid since. It needs no new function and no new column.

- **Cash** is B3's full history (`b3_cash_dividend`): `DIVIDENDO`, `JRS CAP PROPRIO`
  (gross of withholding tax), `RENDIMENTO` and `REST CAP DIN`. Installments are
  identical history rows and each counts once (PETR4 2026-06-01: two JCP of
  0.35048636). A distribution counts only where its ISIN is resolved against the
  tape and B3's published pre-ex close agrees with the tape's close (7,459 of 8,190
  since 2019, all 7,459 agreeing on 2026-10-01).
- **The ex session** is the ISIN's first printed session after the last cum session,
  within 7 calendar days. A paper that does not print within a week has no price to
  reinvest at (189 events print 30+ days later, all in the research universe).
- **Where it is NULL**, each with a reason in `close_total_return_null_reason`: the
  price-adjusted close is NULL; the ISIN has no resolved distribution in B3's history
  (a non-payer, or an issuer B3's history does not match: the two look identical, so
  neither is given a price return labelled as a total return; 188 of 639 universe
  ISINs on 2026-10-01); a later distribution of the issuer's share class has no proven
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
- Not built: the futures arm of `api.panel` (`id_type='future'`, metric
  `settlement`), which `INSTRUMENTS.md` phase B also lists.

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
`quote_history`, `fund_nav` and `index_history` page with a `p_after` cursor**; the others
(`option_history`, `termo_history`, `financials`, `company_financials`,
`anbima_classes`, `inflation`, `inflation_items`, `fidc_tranches`, `fidc_aging`,
`fund_documents`, `fund_restatements`, `fund_restatement_diff`,
`company_events`, `macro_series`, `ptax`, `future_curve`, `future_series`,
`curve`, `curve_history`, `research_universe` and the ten `screen_*` functions) have no cursor and
ask you to narrow the window. `fund_nav` also
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
