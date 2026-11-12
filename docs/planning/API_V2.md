# API v2: a gateway with 14 resources in front of schema `api`

Epic: #1052. Owner decisions on 2026-11-01 and 2026-11-03 (UTC-3). This is the
spec the epic's children build against; it replaces the working drafts v0.1 and
v0.2 of 2026-11-01.

**Status.** The skeleton is built (#1053): the Edge Function
`supabase/functions/silo-api/`, its resource registry, and the resources
`search` and `coverage`. `funds`, `fidc` and `events` are built too (#1056),
and so are `prices` and `statements` (#1055), `screens`, `panel` and
`portfolio` (#1058), and `derivatives`, `curves`, `macro` and
`positioning` (#1057). All 14 resources are built. Every list kind pages with
one opaque cursor, and the tier page sizes and caps apply (#1059, section 5
"Paging, as built" and section 6). The pro tier and the requests-per-minute
limit are built too, counted in Postgres (#1064, section 6); the limit covers
the v2 paths only while v1 stays public. MCP v2 is built too (#1060):
`supabase/functions/silo-mcp-v2/`, 14 tools `silo_<resource>` whose schemas
come from the registry and whose calls run the gateway in process; `silo-mcp`
(v1) stays beside it. The v2 docs are written, marked preview: the quickstart,
the cheatsheet and the researchers page under `api-docs/v2/`, and a "try it"
playground from `api-docs/v2/openapi.json`, generated from the registry by
`scripts/gen_openapi_v2.py`. `meta.data_version` (section 2) is not built yet;
the researchers page says to read `landed_at` and `landed_git_sha` from
`coverage` until it is.
**Deployed preview since 2026-11-04.** The owner-approved rollout activated
`silo-api` and `silo-mcp-v2`; live catalog v82, all 14 resource help pages,
search, prices, cursor paging and tier/error behavior were checked
([rollout evidence](https://github.com/PedroDnT/SILO-BZ/issues/1061#issuecomment-6641311719)).
A merge still deploys no Edge Function. V1 remains live until the consumer
migration and privilege changes in #1065 are accepted.

The native MCP v2 evaluator is built (#1076). Its 2026-11-06 live preflight
passed all required research probes, but the paid attempt stopped on Q1 with
OpenAI HTTP 401 and no observed usage. No case completed and no new rubric
score exists. The ledger retains the US$1.56 whole-case reserve; cumulative
accounted estimates/reserves are US$2.164687, not reconciled billing. With a
cheaper model and an enforced 70,000-token input cap per request, a full
12-case retry reserves US$17.55, within the US$20 cumulative cap
(`research_examples/README.md`). Owner pro
access also remains unverified because the configured database connection
was refused. #1061 tracks these remaining rollout gates.

## Why

The public API has 85 paths (18 views, 67 functions), 245 function arguments
with 81 different names (`p_cnpj`, `p_cnpjs`, `p_id`, `p_ids`, `p_ticker`,
`p_code`, `p_codneg` all mean "the thing I want"), and views that expose up to
37 columns as filters. Seven near-identical price views. Names that mislead:
`lookup` vs `search_funds`, `financials` vs `company_financials` vs
`financial_statement_history`, `curve` vs `reference_rate` vs `curve_history`.
Four paging behaviours. The owner's words: too many endpoints, confusing names,
endless parameters.

## Decisions (owner)

1. A gateway in front of PostgREST. The SQL in schema `api` stays the single
   source of truth, and nothing in schema `api` changes for this epic.
2. 14 resources replace 85 paths (section 4).
3. Shared parameters on every list resource: `id`, `from`, `to`, `limit`, `cursor`.
4. **At most 3 main parameters per resource, and `kind` counts as one of
   them** (decided 2026-11-03). Other parameters work but are hidden: not in
   the quickstart, not in the main docs table, not in the MCP tool's main
   schema (they go in one `options` object).
5. **Every parameter has a default.** With no `id`, a resource lists the ids it holds.
6. **`prices` defaults to `adjust=split`** (today's `close_adj`; decided
   2026-11-03). `adjust=none` is the raw tape.
7. One envelope and one error object (section 5).
8. Lower limits for anonymous callers. The numbers are the owner's to set (section 6).
9. Host: a Supabase Edge Function `silo-api`, the same pattern as `silo-mcp`.
   Path prefix `/v2/`. Both are reversible defaults.

Out of scope: the ANBIMA-linked endpoints (section 8), deploying anything, and
new data (dividend-adjusted returns, corporate actions, bulk snapshots).

## 1. Best practices taken

| Source | Rule | Decision |
| --- | --- | --- |
| Microsoft REST guidelines, Azure API design | A meaningful default for every optional parameter; `fields` for projection. | Every parameter has a default. `fields` is a shared hidden parameter. |
| Microsoft REST guidelines | One error object: `code`, `message`, `target`, `innererror`; about 20 codes at most. | Adopted, with 10 codes. The SQLSTATE goes in `innererror`. |
| Google AIP-158 | Page size optional with a default; above the maximum it is coerced; a missing next token is the only end-of-list signal. | `limit` is the page size, coerced to the tier maximum, and `next_page_url` says more rows exist, so a cut is never silent. |
| Google AIP-160 | One `filter` string, not one parameter per column. | The view columns become one hidden `filter` parameter. |
| Rippling | Cursor pagination on every list. | Same pattern (section 5). |
| Progressive disclosure (Apple WWDC22, SDK guides) | The common case needs 0 to 3 arguments; no hidden modes. | 3 main parameters. `kind` is always explicit, never inferred from which other parameters are present. |
| Anthropic, "Writing effective tools for agents" | Fewer tools with a clear purpose; a concise/detailed switch; errors that say how to fix the call. | 14 MCP tools `silo_<resource>`; `fields=core` concise, `fields=all` detailed; SILO's why/how error text stays. |

One departure: where Google returns an error for a bad argument combination,
SILO already refuses, and more strongly: a request that crosses a ceiling with
no cursor still refuses with `22023`.

## 2. What a quant researcher or a grad student needs

| Need | SILO today | In the gateway |
| --- | --- | --- |
| Point-in-time reads (no look-ahead) | `p_as_of` on 8 functions | Shared hidden `as_of` wherever the SQL can honour it |
| No survivorship bias | `research_universe` first and last observed dates | `search?kind=universe&as_of=2020-01-31`: the names that traded then, dead ones included |
| Stable identity | ISIN in `research_universe`; CNPJ for funds and companies | Every row carries `isin` or `cnpj` beside the ticker |
| Raw and adjusted prices kept apart | Raw `close`, split-adjusted `close_adj`, no dividend adjustment | `adjust=split` (default) or `none`; rows carry `adjusted`; no dividend-adjusted series exists, and the docs say so |
| Tidy, long tables | Long rows, column names vary | Long everywhere; one name per thing (`date`, `id`, `value`) |
| Clear date meaning | Per endpoint | `period_end` and `filed_at` on filings, `date` on sessions |
| Reproducibility | `landed_git_sha`, `landed_at` in `coverage` | `meta.request` echoes every parameter; `meta.data_version` on every response |
| CSV | None | Shared hidden `format=json` (default) or `csv` |
| Citation | None | One docs page with a citation line and the data version |

No dividend-adjusted return series and no corporate-actions resource: both are
in the parking lot for the owner to rank.

## 3. Parameter rules

1. **Shared parameters:** `id`, `from`, `to`, `limit`, `cursor`, one meaning
   everywhere. A resource declares which of them it takes; sending one it does
   not take is `unknown_parameter`.
2. **Main parameters: at most 3 per resource, `kind` included.**
3. **Hidden parameters:** everything else. They work and are listed in
   `?help=all` and on the resource's advanced docs page only.
4. **Shared hidden parameters:** `fields`, `format`, `as_of`, `filter`.
5. **Every parameter has a default.** No call fails because a parameter is missing.
6. **`id` default:** none, and with no `id` the resource lists the ids it holds,
   paged, with names. This is also the discovery path.
7. **Date defaults:** `to` = the latest complete period (from `coverage`);
   `from` = a per-resource window (section 4). An explicit `from` or `to` is
   served as given.
8. **Names:** plain words, `snake_case`, no `p_` prefix.
9. **An unknown name is refused** (`unknown_parameter`, naming it in `target`).
   Today a typo in a `panel` metric is silently ignored. A known parameter with
   a non-default value that the chosen `kind` cannot use is `bad_request`,
   never ignored.
10. **`as_of` means point in time only.** The freshness field of `coverage` is
    returned as `data_through`.
11. Never fill, never trim silently, `null` stays `null` (root `AGENTS.md`).

`limit` is the page size on every resource (#1059). Its default is the tier's
page maximum, and a larger value is coerced to it (Google AIP-158). No plan
sends it to the SQL as `p_limit`.

## 4. The 14 resources

Main parameters, defaults in brackets.

| Resource | Main parameters (max 3, `kind` included) | Default window | Hidden parameters | Status |
| --- | --- | --- | --- | --- |
| `search` | `q` [empty: list the universe], `kind` [`any`; `company`, `fund`, `universe`], `family` [all] | n/a | `as_of` [none] | built |
| `prices` | `kind` [`history`; `latest`, `session`, `index`, `forward`], `freq` [`day`; `month`], `adjust` [`split`; `none`] | 1 year | `board` [all], `asset_class` [all], `fields` [core], `date` [latest session] | built |
| `statements` | `kind` [`all`; `income`, `balance`, `cashflow`, `headline`, `versions`], `period` [`both`; `quarterly`, `annual`], `scope` [`consolidated`; `individual`] | 5 years | `as_of` [none], `statement` [`DRE`] | built |
| `funds` | `kind` [`profile`; `nav`, `holdings`, `debentures`, `properties`], `family` [all; `fi`, `fidc`, `fii`, `fip`, ...] | 3 years | `holding` [none: reverse lookup by ticker or issuer], `status` [all] | built |
| `fidc` | `kind` [`portfolio`; `tranches`, `aging`, `cedentes`, `sacados`] | 2 years | `series`, `cedente`, `item` [all] | built |
| `derivatives` | `kind` [`chain`; `history`, `exercises`, `termo`, `futures`, `futures_curve`, `di_settlement`], `date` [latest session] | 1 year | `expiry_from` [today] | built |
| `curves` | `kind` [`snapshot`; `history`, `vertices`], `curve` [`PRE`; `DOC`, `DPL`], `tenor` [360 calendar days, the one-year fixed vertex, for history] | 1 year | `date` [latest session] | built |
| `macro` | `kind` [`series`; `inflation`, `inflation_items`, `fx`, `expectations`] | 1 year; 3 years for inflation | `family`, `currency` [`USD`], `horizon` | built |
| `positioning` | `kind` [`short_interest`; `short_by_sector`, `lending`, `lending_brokers`, `investor_flow`] | 3 months | `sector`, `investor_type` [all] | built |
| `events` | `kind` [`company`; `fund`, `restatements`, `restatement_diff`, `judicial_recovery`], `category` [all] | 12 months | `family` [all] | built |
| `screens` | `kind` [`list`: the screens with one-line descriptions; one kind per `screen_*` function] | per screen | each screen's thresholds, with today's SQL defaults | built |
| `panel` | `metric` [`auto`: each family's default metric, as today], `freq` [`month`; `day` for quotes only], `family` [`auto`] | 3 years | `min_nav`, `min_months` [none] | built |
| `portfolio` (POST) | `kind` [`resolve`; `fees`, `fee_peers`, `lookthrough`, `movement`, `instruments`, `fund_terms`, `equivalents`, `debenture_returns`], `month` [latest complete] | n/a | `max_depth` [4], `as_of` [today], `max_monthly_drop_pct` [none] | built |
| `coverage` | `kind` [`freshness`; `metrics`, `catalog`], `dataset` [all] | n/a | none | built |

Notes:

- "As today" defaults come from the SQL function defaults in `openapi.json`
  (`curve` defaults to `PRE`, `quote_history` to one year, `screen_dormant_funds`
  to a 3-month lookback).
- `curves` names the B3 reference vertices (`reference_rate` today) `vertices`.
- `prices` with `adjust=split` returns today's `close_adj` (splits, groupings,
  bonus shares; no dividends); `adjust=none` returns the raw `close`.
- `search`, as built: kind `any` and `company` call `lookup` (at most 20 rows;
  `truncated` says when more matched; `company` keeps the rows with `id_type`
  `cd_cvm`), `fund` calls `search_funds` (the whole match, refused above the
  SQL's tier ceiling: `over_limit`), `universe` calls `research_universe`. An empty `q` with kind
  `any` or `company` lists the research universe. `family` narrows kind `fund`;
  `as_of` reads the universe at a date (`first_observed <= as_of <= last_observed`).
- `coverage`, as built: `freshness` calls `coverage` and returns `as_of` as
  `data_through`; `metrics` calls `metric_coverage`; `catalog` calls `catalog`
  and returns the one JSON object as `data[0]`. `dataset` narrows freshness by
  dataset name and metrics by fund family; a name no row carries is refused
  with the known names.
- Default windows, as built (#1056): with no `from`, a kind that takes one
  gets `from` = `to` minus the window, or today (UTC-3) minus the window when
  `to` is not sent. With no `to`, the endpoint's own default applies (for
  `fund_nav`, the family's latest complete period). `meta.request` echoes the
  `from` applied. A `from` after `to` is `bad_request`.
- A required id, as built: a kind whose SQL needs an id (or exactly one of an
  id and a reverse-lookup parameter) is refused with `bad_request` before any
  call, because the SQL's own refusal is `22023` and would read as `over_limit`.
- `funds`, as built: `id` is a fund CNPJ (punctuation stripped, 14 digits or
  `bad_request`). `profile` calls `fund_profile`; with no `id` it reads the
  `funds` view (a GET, ordered by `cnpj`, `family` and `status` as eq.
  filters). That read pages with order + limit + offset (#1059), asking for
  one row more than the page to know whether more remain (no exact count since
  #1098; `meta.rows_total` is null). `nav` calls `fund_nav` (`family` ->
  `p_entity_type`); `holdings` and `debentures` take exactly one of `id` and
  the hidden `holding` (`p_ticker` / `p_issuer`); `properties` calls
  `fii_property_history`. `?help` carries the FIDC delinquency regime break.
- `fidc`, as built: one kind per `fidc_*` function. `series` -> `p_series`,
  `cedente` -> `p_cedente` (exactly one of `id` and `cedente`), `item` ->
  `fidc_portfolio`'s `p_kind` (`sector`, `scr_debtor`, `scr_operation`,
  `tax_debt`). With no `id`, `portfolio` lists the FIDC registry from the
  `funds` view. `?help` carries the 2020-11 delinquency regime break.
- `events`, as built: `category` is the source's own label (`p_category`,
  `p_tipo` or `p_doc_type`); the hidden `family` is `fund_restatements`'
  `p_tipo_fundo` (`fii`, `fidc`, `etf`). `company`, `fund` and
  `restatement_diff` need an `id`; `restatements` and `judicial_recovery`
  list every fund or company without one. The fund kinds take a fund CNPJ.
- `prices`, as built (#1055): `history` calls `quote_history` (`adjust=split`
  selects `close_adj`, `none` the raw `close`; `fields=core` adds `isin`),
  `latest` calls `quote_latest`, `index` calls `index_history`, `forward`
  calls `trade_consolidated_history`. `session` is one GET on a view:
  `asset_class=all` reads `quotes` (standard lot); each other class reads its
  own view (`equities`, `bdrs`, `units`, `fund_quotas`, `cash_securities`,
  `auctions`) so no column and no odd or block lot is lost. Its hidden `date`
  defaults to the newest session in the 14 days to today, found with one GET
  of one row and pinned in the cursor. The session is then read through the
  one `callView` a page at a time (#1059), so a
  session of any size is served whole, never cut. `freq=month`
  keeps the last session of each month from the daily rows. Every price row carries `adjusted`.
  With no `id`, `history` and `latest` list the research universe; `index`
  without an id gets the SQL refusal, which names the codes held.
- `statements`, as built (#1055): `period` is sent as `p_doc_type` (`itr`,
  `dfp`) and `scope` as `p_scope` (`con`, `ind`). `company_financials` takes no
  `p_doc_type`, so for `headline` the period is a selection on the rows'
  `doc_type`. `versions` needs one statement, so it takes a hidden `statement`
  (default `DRE`) and no `as_of`. With no `id`, every kind lists the research
  universe, whose `cnpj` links a ticker to its filer.
- `screens`, as built (#1058): with no `kind` (`list`) it reads `catalog()`
  and returns one row per screen: its kind, one line, the family it reads and
  its SQL defaults under v2 names. Any other kind calls `screen_<kind>`. Every
  threshold is hidden (`?help=all`); one left out is sent as the SQL
  function's own default, so `meta.request` echoes it (a test pins each to the
  SQL). `p_period` and `p_end` are `date`, `p_modalidade` is `modality` (`RE`,
  `RC`), `p_family` is `family`. Every response carries `meta.signal`:
  "Signal, not a verdict".
- `panel`, as built (#1058): one kind, so no `kind` parameter. `id` is a
  comma-separated list sent as `p_ids`. The gateway's tier ceiling (1
  anonymous, 3 signed in; #1059) is refused above it (`forbidden_for_tier`),
  and the SQL's own (3 anonymous, 50 signed in) is its refusal (`over_limit`);
  never a trim. `metric=auto`
  sends no `p_metrics`. A metric name outside `catalog().metrics` is
  `unknown_parameter` with the name in `target`; the gateway's list is pinned
  to the SQL catalog by a test, so no catalog call is made per request. With no
  `id`, a `family` walks it (universe mode, monthly); `min_nav` and
  `min_months` apply only there, and are `bad_request` with an `id`. The
  gateway serves universe mode to the pro tier only (#1059); a user reaches
  pro through a row in `public.api_user_tier` (#1064).
- `portfolio`, as built (#1058): the one POST route. `kind`, `month` and the
  hidden parameters go in the query string; the lists go in a JSON body: `id`
  (CNPJs, instrument codes, filed class labels or debenture tickers, by kind)
  and, for `resolve`, `names`, `quotas`, `quota_dates`. Each kind is one
  read-only `portfolio_*` rpc. A list the kind cannot use, an unknown body
  field or a list in the query string is refused. `debenture_returns` has no
  SQL default month, so it needs `month`. `portfolio_credit_returns` is not
  served (held back, section 8). `fees`, `fee_peers`, `movement` and
  `equivalents` read the ANBIMA class label as filed in the CVM Extrato
  (`cvm_fi_extrato.classe_anbima`); none reads an `anbima_*` table, so all
  four are built.
- A view read with a window, as built (#1057): a registry `range` names the
  view's date column, and `from`/`to` become `gte`/`lte` on it (PostgREST
  `and=(...)`), through the one `callView`. A kind can carry its own
  `window_months`, and a `when_empty` can name a value (`currency=all`) that
  selects its fallback.
- `derivatives`, as built (#1057): `chain` calls `option_chain` (`id` is the
  option prefix), `history` `option_history`, `exercises` `option_exercises`,
  `termo` `termo_history`, `futures` `future_series`, `futures_curve`
  `future_curve` (`id` is the root; none sends the SQL default `DI1`), and
  `di_settlement` reads the `di_settlement` view, newest first. `date` applies
  to `chain` and `futures_curve`; `expiry_from` to `chain`. Ids are sent upper
  case. `option_chain` and `option_exercises` cut at a tier ceiling without
  refusing, so the gateway asks for 1,001 rows: a count above 1,000 or equal
  to a known ceiling cannot be told from a cut. `chain` refuses it
  (`over_limit`); `exercises` halves its date window and tries again, and
  refuses only a single day still cut (#1059).
- `curves`, as built (#1057): `snapshot` calls `curve`, `history` calls
  `curve_history`, `vertices` reads the `reference_rate` view for one curve on
  one session (the newest in the 14 days to today unless `date` is given).
  `tenor` is B3's nominal tenor in calendar days (`p_tenor_days`, default 360,
  the one-year fixed vertex), not 252 business days: the SQL takes only a fixed
  vertex and refuses any other tenor with the list, and the gateway never
  interpolates.
- `macro`, as built (#1057): `series` calls `macro_series` (`id` required),
  `inflation` calls `inflation` (`family` -> `p_family`), `inflation_items`
  calls `inflation_items` (with an `id`, `p_level` is NULL so the item is
  found at its own level; with none, the SQL's level 1, the groups), `fx`
  calls `ptax` (`currency` -> `p_currency`; `currency=all` reads the
  `ptax_daily` view), `expectations` calls `focus_expectations`. There the
  hidden `family` is the Focus survey (`annual` by default, `monthly`,
  `selic`, `inflation_12m` -> `p_endpoint`), and `horizon` defaults to the
  current year (UTC-3) for `annual` and is required for the others. A family
  of the other kind is `bad_request`.
- `positioning`, as built (#1057): one GET per kind on `short_interest`,
  `short_interest_by_sector`, `lending_trades`, `lending_participants` or
  `investor_flow`, newest first, `from`/`to` as a range, `sector` and
  `investor_type` as eq. filters, paged with order + limit + offset (#1059).
  `?help` carries the BDI notes: short interest
  reads only B3's `Total` rows (`is_total`), `pct_float` goes with
  `float_basis`, a lending broker (`doador` / `tomador`) is not the beneficial
  owner, and a missed session is lost.

### The first five minutes

```
GET /v2/                                   -> the 14 resources, one line and one example each
GET /v2/search?q=petrobras                 -> ids, names, tickers, ISIN, CNPJ
GET /v2/prices?id=PETR4                    -> one year of split-adjusted daily closes
GET /v2/statements?id=PETR4&kind=income    -> five years of income statements
GET /v2/prices?help                        -> kinds, main parameters, defaults, data span
```

No call above needs a parameter beyond `id` and `kind`.

## 5. Paths, response, paging, errors

Paths: `GET /v2/` (the index), `GET /v2/<resource>`, `GET /v2/<resource>?help`
(`?help=all` adds the hidden parameters), and `POST /v2/portfolio` with a
JSON body of lists (#1058). The gateway calls PostgREST with the
publishable key and schema `api`, exactly as `silo-mcp` does, and forwards a
caller's `Authorization: Bearer` JWT so the signed-in tier applies. It never
uses a secret key.

```json
{
  "data": [ { "date": "2026-10-30", "id": "PETR4", "isin": "BRPETRACNPR6", "close": 38.12, "adjusted": true } ],
  "meta": {
    "resource": "prices", "kind": "history",
    "request": { "id": "PETR4", "from": "2025-10-31", "to": "2026-10-30", "adjust": "split" },
    "data_through": "2026-10-30", "data_version": "landed 2026-10-31T03:41 UTC-3, git 1a2b3c4",
    "id_known": true, "source": "B3 COTAHIST"
  },
  "next_page_url": "https://<gateway>/v2/prices?cursor=..."
}
```

(Values illustrative, not real data.)

- `data` is always the array key. `meta.request` echoes every parameter,
  including the defaults applied, so it can be pasted into a methods section.
- `meta.id_known` says whether an id is one SILO holds, so an empty `data` says
  why; it is `null` for a call that names no id.
- `limit` is the page size: default the tier's page maximum, coerced down to
  it (section 6).
- `next_page_url` is present only when more rows remain. The cursor is opaque
  and fixes the other parameters.

```json
{ "error": {
    "code": "over_limit",
    "message": "macro_series: refused, this request would return more than 1000 rows. ...",
    "target": null,
    "innererror": { "sqlstate": "22023", "hint": "..." } } }
```

### Paging, as built (#1059)

- **One cursor on every list kind.** `next_page_url` is the same path with
  `?cursor=<token>`. The token is base64url of a JSON state: the resource,
  every original query parameter as sent, the paging method, the position,
  the rows served so far, and the request day (UTC-3) the first page counted
  a defaulted `from`/`to` from, so a walk that crosses midnight keeps its
  window (#1103); a day other than today or yesterday is refused. A request that sends a cursor and another parameter
  with a different value is `bad_request`, naming that parameter; repeating
  the same value is allowed. On `POST /v2/portfolio` the cursor carries a
  digest of the body, and the next page is a POST with the same body.
- **Unsigned.** The cursor is not signed, so the gateway trusts nothing in it.
  Its parameters are parsed again exactly like a fresh request, the position
  is validated by the method that reads it (a date window must lie inside the
  request's own `from`..`to`), and the page size and the rows-per-call cap are
  the current caller's tier, never the cursor's. Editing a cursor can at most
  restart a walk at a position a fresh request could reach.
- **Four methods**, declared on every plan in the registry (`paging`; a test
  checks every plan has one):
  - `p_after`: the function's own cursor (`panel`, `quote_history`,
    `fund_nav`, `index_history`, `trade_consolidated_history`). Each call reads
    one 1,000-row SQL page after the last served row's key. With
    `freq=month`, a full SQL page's last month is read again from the next
    page, so a month-end is never picked from half a month. `fund_nav` pages
    with `p_after` only with a `family` (its cursor is unique only within one
    family); with `family=all` it walks date windows.
  - `date_window`: every other function with `from`/`to`. The first call is
    the whole window as asked. A window the SQL refuses for its row cap (the
    `22023` whose message says "more than 1000 rows") is halved and tried
    again; a single day still refused is `over_limit` with the SQL's message,
    verbatim. Any other refusal (an unknown id, a bad tenor) is returned at
    once. Inside a window the position is an offset into its rows. Windows go
    in the function's own date order (a test pins it to the SQL's `ORDER BY`).
    When a split needs an end the request left open, `to` is today (UTC-3).
  - `view_offset`: every GET view, `order` + `limit` + `offset`, asking for
    one row more than the page: the extra row says more remain and is not
    served. No `Prefer: count=exact` since #1098 (an exact count over the
    lending views outran the anon statement timeout); `meta.rows_total` is
    null. `prices
    kind=session` and `curves kind=vertices` find the newest session once and
    pin it in the cursor.
  - `single_page`: one call holds the whole answer (or refuses), and pages are
    slices of it. Each such plan states why it cannot page upstream (for
    example `lookup` returns at most 20 rows; a screen is one call).
- **One request makes at most 12 PostgREST requests** (`MAX_UPSTREAM_CALLS`
  in `config.ts`). When a walk spends them, the page is served short, with
  `next_page_url`, never cut.
- `meta.page_size`, `meta.rows_served` (all pages so far), `meta.tier`, and
  `meta.limit_coerced_from` when `limit` was above the tier maximum.

Top-level codes (10): `bad_request`, `unknown_parameter`, `unknown_id`,
`unauthorized`, `forbidden_for_tier`, `over_limit`, `rate_limited`, `timeout`,
`unavailable`, `internal`. A PostgREST `22023` maps to `over_limit` and keeps
its message, details and hint verbatim; `57014` maps to `timeout`.

## 6. Tiers

PostgREST has one server-wide `db-max-rows`, so no tier can have its own page
size there; the gateway can. A lower page size is harmless only because every
list pages (section 5). Owner decision 2026-11-03 (#1061); the numbers are
constants in one block, `supabase/functions/silo-api/config.ts`, and a test
pins them:

| | anonymous (try it) | signed in (free) | pro (paid) |
| --- | ---: | ---: | ---: |
| Page size maximum (`limit` default) | 10 | 100 | 1,000 |
| Rows per call, all pages | 50 | 1,000 | unlimited |
| Date window on daily data | 3 months | 2 years | none |
| `panel` ids per call | 1 | 3 | 50 |
| `screens`, `portfolio` | no | yes | yes |
| `panel` universe mode | no | no | yes |
| Requests per minute | 10 | 30 | 300 |

As built (#1059):

- **The tier** (#1064, `tier.ts`). No `Authorization: Bearer` (or the
  publishable key sent as one) is anonymous, with no call. Any other token
  asks `api.my_tier()` (`39_api_tiers.sql`) with that token, and the answer is
  cached per token for 60 s in the isolate's memory: `pro` for a user with a
  row in the private `public.api_user_tier`, `signed_in` for any other user,
  `anonymous` for a Supabase anonymous sign-in. PostgREST verifies the token
  (an invalid one is `unauthorized`). The gateway does not decode the JWT.
  Rows in `api_user_tier` are inserted by the owner by hand; no API writes
  there.
- **Requests per minute** (#1064). Every data request, after its parameters
  parse and before any data call, runs `api.rate_hit()`, which adds one hit to
  this minute's bucket in `public.api_rate_counter` and returns the count.
  Above the tier's number the answer is `rate_limited`, HTTP 429, with
  `Retry-After` (seconds to the next minute) and no data read. A refused
  request is counted too. Every 200 carries `RateLimit-Limit` and
  `RateLimit-Remaining`. The index and `?help` read no data and are not
  counted. A signed-in caller's bucket is `u:<user id>`, chosen by SQL from
  `auth.uid()`. An anonymous-tier caller's bucket is `ip:<address>`, sent
  whenever the resolved tier is `anonymous`, so an anonymous sign-in's token
  carries it too (#1101; before, any Bearer sent none and got 503): the gateway
  trusts `cf-connecting-ip`, which Cloudflare overwrites in front of hosted
  Supabase. `x-forwarded-for` is appended to, so its first hop is the
  caller's own word; it is used only when `cf-connecting-ip` is missing (a
  local `supabase functions serve`), where every header is spoofable. With
  no usable address, callers share the bucket `ip:0.0.0.0`.
- **Fail closed.** When `my_tier` or `rate_hit` cannot be read (network,
  timeout, a function not yet applied), the request is `unavailable` and no
  data is read. So the analytical apply must precede the next deploy of
  `silo-api`.
- **Honest limit.** The limit protects the v2 surface only. While the v1
  PostgREST paths stay public (`/rest/v1/rpc/*` with the publishable key), a
  caller can skip the gateway and its limit entirely; retiring v1 is the
  owner's call (#1061, #1065). And anyone holding the publishable key can call
  `api.rate_hit` directly with any `ip:` bucket, so another address's count
  can be inflated. The limit stops ordinary overuse, not an attacker.
- **Rows per call.** When a walk reaches the cap, the response has no
  `next_page_url`, and `meta.tier_cap_reached` is `true` with
  `meta.tier_cap_message`, which says how to get a higher tier. Never a silent
  stop. Rows may remain past the cap; the message says so.
- **Daily data.** A plan marked `daily` in the registry (`prices` history,
  index and forward; `derivatives` history, exercises, termo, futures and
  `di_settlement`; `curves` history; `macro` fx; every `positioning` kind;
  `panel` with `freq=day`) reads at most the tier's window. A default window
  wider than it is narrowed to it (`meta.request.from` and
  `meta.window_narrowed_to_tier` say so); a `from` the caller sent that is
  earlier is `forbidden_for_tier`. `macro` series is not marked: its SGS
  series mix daily and monthly codes.
- **`screens` and `portfolio`** are `forbidden_for_tier` for anonymous
  callers (`?help` stays open). `panel` above the tier's ids, or in universe
  mode below pro, is `forbidden_for_tier` before any call.
- Statement timeouts stay the SQL's (3 s anonymous, 8 s signed in).

## 7. Plan

| Step | What | Gate |
| --- | --- | --- |
| 1 | Skeleton, registry, `search`, `coverage` (#1053) | Offline tests green |
| 2 | Deno tests in CI | CI runs them |
| 3 | The other 12 resources | Contract tests: each old endpoint and the new resource return the same rows for a fixed sample |
| 4 | Cursors on every list; tiers and rate limits | Load test on the anonymous limits |
| 5 | MCP v2 (14 tools `silo_<resource>`) | Rerun the agent evaluation (baseline 2/12); it must beat it |
| 6 | Docs, quickstart, SDK, `llms.txt`, a "For researchers" page (point in time, survivorship, adjustment, data version, citation) | Someone new completes the three-call quickstart |
| 7 | Deploy; later, mark the old paths deprecated | The owner |

The children of #1052 are the authoritative order.

## 8. Old to new: all 85 paths

| New | Replaces |
| --- | --- |
| `search` | `lookup`, `search_funds`, `research_universe` |
| `prices` | `quote_history`, `quote_latest`, `quotes`, `equities`, `bdrs`, `units`, `fund_quotas`, `cash_securities`, `auctions`, `index_history`, `trade_consolidated_history` |
| `statements` | `financials`, `income_statements`, `balance_sheets`, `cash_flow_statements`, `company_financials`, `financial_statement_history` |
| `funds` | `funds`, `fund_profile`, `fund_nav`, `fund_holdings`, `fund_debentures`, `fii_property_history` |
| `fidc` | `fidc_portfolio`, `fidc_tranches`, `fidc_aging`, `fidc_cedentes`, `fidc_sacados` |
| `derivatives` | `option_chain`, `option_history`, `option_exercises`, `termo_history`, `future_series`, `future_curve`, `di_settlement` |
| `curves` | `curve`, `curve_history`, `reference_rate` |
| `macro` | `macro_series`, `inflation`, `inflation_items`, `ptax`, `ptax_daily`, `focus_expectations` |
| `positioning` | `short_interest`, `short_interest_by_sector`, `lending_trades`, `lending_participants`, `investor_flow` |
| `events` | `company_events`, `fund_documents`, `fund_restatements`, `fund_restatement_diff`, `rj_listed_documents` |
| `screens` | `screen_captive_vehicles`, `screen_delinquency_drivers`, `screen_dormant_funds`, `screen_dormant_trend`, `screen_evergreen_aging`, `screen_late_filers`, `screen_overdue_securit`, `screen_restatements`, `screen_silent_filers`, `screen_zombie_growth` |
| `panel` | `panel` |
| `portfolio` | `portfolio_resolve`, `portfolio_fees`, `portfolio_fee_peers`, `portfolio_lookthrough`, `portfolio_movement`, `portfolio_instruments`, `portfolio_fund_terms`, `portfolio_equivalents`, `portfolio_debenture_returns` |
| `coverage` | `coverage`, `metric_coverage`, `catalog` |
| **Held back (ANBIMA)** | `anbima_classes`, `class_return_distribution`, `credit_implied_rate`, `credit_market_history`, `portfolio_credit_returns` |

The held-back group waits until the ANBIMA drop (owner, 2026-10-31) settles.
`credit_market_history` and `portfolio_credit_returns` are not clearly ANBIMA;
their sources were not verified. `portfolio_equivalents`, `portfolio_fees`,
`portfolio_fee_peers` and `portfolio_movement` mention an ANBIMA class: checked
for #1058, it is the class label as filed in the CVM Extrato, and none of them
reads an `anbima_*` table (a test pins this), so `portfolio` serves them.

### Parameters that disappear

| Old | New |
| --- | --- |
| `p_id`, `p_ids`, `p_cnpj`, `p_cnpjs`, `p_ticker`, `p_tickers`, `p_code`, `p_codes`, `p_codneg`, `p_root`, `p_index`, `p_series` (as an id) | `id` (a list where the old one was a list) |
| `p_from`, `p_to` | `from`, `to` |
| `p_limit`, `p_after` | `limit`, `cursor` |
| `p_entity_type`, `p_family`, `p_modalidade`, `p_tipo_fundo` | `family` |
| `p_doc_type` | `period` (`quarterly` or `annual`) |
| `p_as_of` | `as_of` (hidden; point in time only) |
| `p_statement` | `kind` |
| `p_kind`, `p_category`, `p_tipo`, `p_level`, `p_endpoint` | `kind` or `category`, one per resource |
| 35 view columns used as filters | `board`, `asset_class`, `fields`, and the hidden `filter` |
| `p_trade_date`, `p_month`, `p_end_month`, `p_end` | `date` (or `month` on `portfolio`) |

The count falls from 81 argument names to about 20 across the API.

## 9. Parking lot

Bulk Parquet or CSV snapshots per dataset; dividend-adjusted total returns; a
corporate-actions resource; line-item normalization; Brazil insider and
large-stake data; a cited plain-English search; per-user keys.

## Sources

Microsoft REST API guidelines and Azure API design best practices; Google
AIP-158 and AIP-160; Rippling, "How Rippling builds enterprise-grade APIs"
(2026-07); Apple WWDC22, "The craft of SwiftUI API design"; Anthropic, "Writing
effective tools for AI agents" (2025-09); QVeris, DataCamp and QuantConnect
data guides; the HyperDB reproducible-pipeline README.
