# Serving every B3 instrument class

How each instrument type gets ingested and served as an endpoint, and why the
structure is the same for a human with `curl` and an agent building a panel.
Sits on top of `DATA_MODELING.md` (long facts, natural keys, nothing
synthesized) and `SERVING.md` (caps in SQL, catalog honesty, no `/v1/query`).

## The two-layer rule

Every instrument class is served twice, from the same landing rows:

1. **A typed endpoint per class** — a PostgREST view or RPC whose columns are
   the class's own vocabulary (strike, expiry, settlement, tenor). This is the
   human surface: one `curl`, self-explanatory columns, one api-docs page.
2. **Rows in `api.panel`** — the long `(id, id_type, asset_class, date,
metric, value, source)` grain. This is the agent surface: any instrument
   composes with any other in one matrix without knowing its class's
   vocabulary.

A class earns a panel arm only when its series is honestly 1-D per id
(one value per `(id, date, metric)`). Anything 2-D gets a typed endpoint only —
flattening it into the panel would force a synthetic id, which is how honest
grains die.

Discovery is part of the contract, not an afterthought:

- `api.universe(asset_class)` and `api.lookup(query)` grow one `asset_class`
  value per new class, so both audiences find instruments the same way.
- `api.coverage()` grows one row per new dataset (what, as-of, source).
- The metric catalog goes public as `api.catalog()` returning the same JSON
  `serve/catalog.py` serves locally, so an agent on the Data API can
  self-describe without the local adapter. An offline test pins the SQL copy
  to `serve/catalog.py` (same pattern as the caps-lockstep test); catalog
  changes bump `CATALOG_VERSION`.

## Class by class

Status legend: **landed** = rows already in Supabase; **served** = reachable
through schema `api`.

### 1. Cash equities — stocks, units, BDRs, FII quotas, ETFs

`tpmerc 010/020/021` in COTAHIST. Landed and served (`api.quotes`,
`quote_history`, `quote_latest`, panel `close`/`volume`/`close_return`).
Nothing to do. The reference implementation for every class below.

### 2. Equity options (calls `070`, puts `080`, exercises `012/013`)

**Landed, unserved** — and ~89 % of every COTAHIST session (2026-08-25:
14,900 option rows vs 1,405 cash rows). `preco_exercicio` and
`data_vencimento` are already typed columns; no new ingest.

- **Typed:** `api.option_chain(p_prefix TEXT, p_expiry_from DATE DEFAULT
CURRENT_DATE, p_trade_date DATE DEFAULT NULL, p_limit INT)` — one row per
  series with side (call/put from `tpmerc`), strike, expiry, close, volume,
  open-interest-free COTAHIST fields. `p_prefix` is a required filter
  (`codneg LIKE p_prefix || '%'`): a whole-market chain is tens of thousands
  of rows and an unfiltered chain is exactly the query the caps exist to stop.
  Plus `api.option_history(p_codneg, p_from, p_to)` mirroring
  `quote_history` (same 5001 cap).
- **Panel:** ids are option `codneg`s, `id_type='option'`,
  `asset_class='derivative'`, metrics `close`/`volume`. Fits the 1-D grain.
- **Deliberately absent in v1: an `underlying` column.** The 4-letter root of
  `codneg` _usually_ names the underlying, but that is a naming convention,
  not a published mapping — deriving it would synthesize an identity join
  (integrity rule 3, and the same reason ticker↔CNPJ stays unjoined). Callers
  filter by prefix and own that inference; the docs page says so. If B3
  publishes an instrument registry with the underlying, ingest that and join
  for real.
- **Schema:** one migration adding a partial index,
  `(codneg, trade_date) WHERE tpmerc IN ('070','080')`, mirroring the
  existing `vista` partial index.

### 3. Forwards / termo (`030`)

Landed, unserved, small (135 rows/session). Same treatment as options minus
the chain: `api.termo_history(p_codneg, …)`, panel ids with
`id_type='termo'`. `prazot` (term days) is already a key column.

### 4. Futures — DI1, IND/WIN, DOL/WDL, commodities

**Not ingested.** COTAHIST does not carry them; B3 publishes daily settlement
prices separately (the "ajustes do pregão" file; rb3's
`b3-futures-settlement-prices` template documents the format).

- **Ingest:** new `B3FuturesFetcher` + `b3_futures_settlement` table, long and
  narrow per `DATA_MODELING.md`: `(contract TEXT, trade_date DATE,
settlement NUMERIC, prior_settlement NUMERIC, variation NUMERIC, raw JSONB)`
  with `UNIQUE (contract, trade_date)`. `contract` is B3's own code
  (`DI1F27`, `WINQ26`) — natural key, never decomposed into root+maturity
  columns by us (the code _is_ the provenance; a `commodity` prefix column
  can be a generated column later if queries need it, derived by B3's own
  published code table, not by string intuition). Wired into `run_daily`
  (same 7-day lookback pattern) and `run_backfill` behind a flag; follows
  the 6-step "Adding a dataset" checklist including the offline CSV fixture.
- **Typed:** `api.future_series(p_contract, p_from, p_to)` (5001 cap) and
  `api.future_curve(p_root TEXT, p_trade_date DATE)` — all live maturities of
  one root on one date, which is how humans actually read DI1.
- **Panel:** ids are contract codes, `id_type='future'`, metric
  `settlement`. 1-D per contract — fits.

### 5. Yield curves — PRE / DIC / DOC reference rates

**Not ingested.** B3 publishes the fitted curves ("taxas referenciais"; rb3's
`b3-reference-rates`). Ingest **as published** — never recomputed from DI1
futures, for the same reason we never compute a NAV: when the source
publishes a number, our job is provenance, not reproduction.

- **Ingest:** `b3_reference_rate (curve TEXT, trade_date DATE,
tenor_days INT, rate NUMERIC, raw JSONB)`, `UNIQUE (curve, trade_date,
tenor_days)`.
- **Typed:** `api.curve(p_curve, p_trade_date)` → one date's full term
  structure; `api.curve_history(p_curve, p_tenor_days, p_from, p_to)` → one
  tenor through time.
- **Panel: no.** A curve is 2-D (date × tenor). Panel ids like `PRE_252`
  would mint one synthetic id per tenor — a fabricated identifier, which the
  integrity rules exist to prevent. `curve_history` gives agents the 1-D
  slice when they've chosen a tenor; choosing the tenor is analysis, and
  analysis lives in the notebook.

### 6. Indexes — IBOV et al., composition and history

**Not ingested.** Two honest grains, two tables:
`b3_index_composition (index, date, ticker, weight)` and
`b3_index_history (index, date, points)`. History joins the panel
(`id_type='index'`, metric `points`/`return`); composition is typed-only
(`api.index_composition(p_index, p_date)`) — membership lists are not a time
series. Lowest priority: IBOV level is already obtainable via BACEN SGS, and
composition mainly serves benchmark-attribution work we don't do yet.

### 7. Funds and securitization (CVM side)

Already landed and served (`api.funds`, `fund_nav`, panel `nav`/
`delinquency`/…). Listed here only so the taxonomy is complete: the pattern
above is _their_ pattern, generalized.

## Why this structure serves both audiences

- **Humans** get one noun per class (`option_chain`, `future_curve`,
  `curve`), columns in the instrument's own vocabulary, one docs page per
  class in `api-docs/`, and errors/empties per the conventions page
  (PostgREST `200 []`, caps at N+1).
- **Agents** get exactly three things to learn, ever: `catalog()` (what
  exists), `universe`/`lookup` (which ids), `panel` (the data, one shape).
  A new instrument class changes _none_ of those signatures — it adds rows
  to their outputs. That is the property worth defending, and it is why the
  2-D shapes stay out of the panel instead of bending it.
- **Both** read the same landing rows, so a number can never differ between
  the human view and the agent panel.

## Phases

Ordered by value ÷ effort; each phase is releasable alone, in the usual
shape: config → field map → schema+migration → ingest method → wiring →
offline fixture test → analytical SQL → catalog bump → api-docs page.

| Phase | What                                                                                                                  | New ingest? | Effort                                   |
| ----- | --------------------------------------------------------------------------------------------------------------------- | ----------- | ---------------------------------------- |
| **A** | Options + termo endpoints, partial index, panel arms, `api.catalog()`, universe/lookup/coverage extension, docs pages | none        | small — SQL + docs only                  |
| **B** | Futures settlement: fetcher, table, `future_series`/`future_curve`, panel arm                                         | yes         | medium — first non-COTAHIST B3 file      |
| **C** | Reference-rate curves: fetcher, table, `curve`/`curve_history`                                                        | yes         | medium — piggybacks B's fetcher plumbing |
| **D** | Index composition + history                                                                                           | yes         | small, lowest value today                |

DI1 (phase B) and the PRE curve (phase C) are the highest-value additions for
the accountability mission: they are the discount curves behind FIDC and
fixed-income fund NAV, currently proxied by BACEN SGS policy rates.

Prerequisite for all phases: the serving SQL currently on `main` must be
applied to production first (`analytics-only`), since every new endpoint
lands in the same `19_api_contract.sql` + grants pattern.

## Runtime: is GitHub Actions enough?

**Yes — for daily and for backfill, including phases B–D — with three rules.**
Assessed against observed numbers, not runner marketing:

- **Daily headroom is ~5×.** The full daily run (28 datasets, ~5M rows
  upserted) takes 22–34 minutes against a 180-minute timeout. Phase B adds
  one small settlement file per day and phase C one reference-rate file —
  seconds of fetch, thousands of rows. Cron drift observed on this repo is
  06:03–06:25 for a 06:00 schedule; irrelevant at daily cadence, and the
  self-heal is `watchdog.yml`, not tighter scheduling.
- **Backfill fits because it shards.** The 6-hour job cap is the only hard
  GHA limit that could bind, and `backfill.yml` already answers it: FI runs
  one job per year (300-min timeouts, public repo = free minutes, 20
  concurrent jobs). New deep backfills MUST follow the same year-shard
  pattern — futures/curves history is ~250 small files per year, bound by
  HTTP round-trips, so one year per job with a polite per-request delay is
  comfortably inside the cap. Never one unsharded multi-year loop.
- **The binding constraint is the database, not the runner.** The 2026-08-26
  incident chain (overlapping readers → blocked `ALTER TABLE` → dead apply →
  Supabase quota warnings) was contention on the shared Postgres, and GHA
  compute was never the bottleneck. Hence rule three: all three writing
  workflows (`daily_ingest`, `backfill`, `watchdog`) now share a
  `concurrency: supabase-ingest` group with `cancel-in-progress: false` —
  one writer at a time; a run arriving mid-backfill queues instead of
  writing on top of it. The per-year matrix inside one backfill run still
  parallelizes; the group serializes workflows against each other, not jobs
  within a run.

Known GHA-specific risks and their standing answers:

| Risk                      | Answer                                                                                                                                                                                                                      |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CVM blocks a runner IP    | Already handled: the connect-failure breaker aborts fast; re-dispatch usually lands an unblocked IP. If it ever becomes chronic, the escape hatch is a self-hosted runner or egress proxy — a runtime swap, no code change. |
| 6-hour job cap            | Year-sharding (existing FI pattern; mandatory for new backfills).                                                                                                                                                           |
| Cron delay / skipped runs | Daily cadence tolerates it; `watchdog.yml` re-runs on staleness.                                                                                                                                                            |
| Runner disk (~14 GB)      | Largest artifact is a yearly COTAHIST zip (hundreds of MB). Non-issue.                                                                                                                                                      |
| Minutes budget            | Public repo: standard runners are free.                                                                                                                                                                                     |

What GHA is **not** enough for, so nobody discovers it mid-build: intraday or
guaranteed-time ingestion (cron has no SLA), and anything needing a static
egress IP for allowlisting. Neither is on this roadmap — everything here is
end-of-day public files.
