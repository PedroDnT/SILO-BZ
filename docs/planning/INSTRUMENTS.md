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
| **Adj** | Label `close_return` as unadjusted (catalog v3 + docs — done); jump screen (`abs(close_return) > 40%` × `cia_event`) still open | none | small — SQL against data we already have |
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

## Source appendix: the `cotacao.b3.com.br` quote feed

Surveyed via [PedroDnT/lse-terminal-brazil](https://github.com/PedroDnT/lse-terminal-brazil),
which reads it directly. `https://cotacao.b3.com.br/mds/api/v1` is the JSON
feed behind B3's own quote pages: `instrumentQuotation/{SYMBOL}` returns a
last price (~15-minute delay) for **any** listed symbol — including the BM&F
contracts (`WIN`, `IND`, `WDO`, `DOL`) and `IBOV`, which COTAHIST never
carries — plus the current session's minute prints. No key; B3's edge
challenges a bare client, so requests need a browser `User-Agent`.

**What it is fit for here — and what it is not.** The feed is a delayed
*snapshot* of the current session: no history, no official close, no
settlement. Ingesting "last price whenever the cron happened to run" would be
weaker provenance than everything else in this warehouse, so it does **not**
replace phase B's settlement files, which are B3's official, archived,
auditable record. Its legitimate uses:

- **Phase D shortcut:** `IBOV` (and the other indices) answer on this feed,
  so index *levels* may be obtainable here if the historical index files
  prove awkward — but only as a dated last-print with `source` saying exactly
  that, never presented as an official close.
- **Reference implementation:** the repo encodes B3's own published roll
  rules (`front_month`: index contracts on even months expiring the
  Wednesday nearest the 15th; FX contracts monthly) and the month-code
  table. If a convenience endpoint ever needs "the front month", implement
  it as B3's documented rule with a citation — though the cleaner posture
  stays: serve every contract, let the caller pick.
- **Operational detail worth stealing:** the `User-Agent` requirement, and
  its `BizSts.cd != "OK"` error envelope.

Phase B's primary source is unchanged: daily settlement prices (ajustes do
pregão), because settlement is the number that is official, historical, and
verifiable — the three properties this warehouse exists to preserve.

## Adjustment: how do you know a series is correctly adjusted?

Short answer, today: **it isn't adjusted at all, and the API says so.**
COTAHIST is B3's raw record — `src/parsers/cotahist.py` states it in the
header ("unadjusted for splits or proventos"), and `api.quotes` carries a
hardcoded `adjusted = FALSE`. That flag is honest, and it must stay honest.

### The trap that is already live

`close` is unadjusted, which is fine and clearly labelled. But
**`close_return` is derived from those unadjusted closes**, so on the day a
ticker splits 2:1 the panel reports roughly **−50 %** and calls it a return.
Nothing in the pipeline is wrong — the arithmetic faithfully describes the
prices B3 published — but a reader doing an event study, a correlation, or a
drawdown will silently eat a fabricated shock. That is the single most
dangerous number in the warehouse right now, precisely because everything
around it is correct.

Until adjustment lands, the trap is labelled, not fixed. Catalog `meaning`
for `close_return` (version 3) and the api-docs panel page both say
"unadjusted; corporate actions appear as spurious jumps". A caption is not
a fix, but an unlabelled trap is worse than a labelled one. The jump
screen below remains the first *code* deliverable.

### Where the adjustment information actually lives

There is no adjustment factor hiding in the file we already parse.
`fator_cotacao` (FATCOT, positions 211–217) is the **quotation factor** — how
many units a quoted price refers to (1, or 1000 for some instruments). It is
not a split ratio and must never be used as one; that mistake produces a
plausible, wrong series, which is the worst kind.

The real sources, in the order worth trying:

1. **B3 corporate events** — "Proventos em Dinheiro" (cash dividends, JCP)
   and the events that change share count: *desdobramento* (split),
   *grupamento* (reverse split), *bonificação* (stock dividend),
   *subscrição* (rights). B3 publishes these per ticker on its listed-company
   pages, and the `rb3` R package parses some of them — check its templates
   before writing a fetcher, the same way `rb3` settled the futures question.
   This is the primary source: it is the exchange's own record, with the
   ratio stated.
2. **CVM IPE — already ingested.** `cia_event` carries the *Aviso aos
   Acionistas* / *Comunicado ao Mercado* filings in which a company announces
   a split or bonus, with `categoria` / `tipo` / `especie` / `assunto`
   columns to filter on. These are **documents, not structured ratios** — a
   discovery and cross-check aid ("did anything happen to this ticker on this
   date?"), not something to parse a factor out of.
3. **ISIN continuity** in `b3_cotahist` — a ticker whose ISIN changes is
   telling you the instrument changed. Free signal, already in the table.

### How to *verify* a series, whatever the source

The honest test is not "did we apply a factor" but "does the series still
contain unexplained discontinuities":

- **Jump screen.** Flag every `|close_return| > 40 %` on a day with no
  extreme volume. Cross-reference each hit against `cia_event` for that
  issuer and date. A hit with a matching *Aviso aos Acionistas* is a
  corporate action; a hit with nothing is either real news or a data bug, and
  both deserve a look. This is runnable **today** against data we already
  have, and it is the recommended first deliverable — it measures the size of
  the problem before anyone builds a fetcher.
- **Share-count sanity.** After adjustment, price × shares should be
  continuous across the event even though price is not.
- **Independent comparison.** Spot-check a handful of adjusted series against
  any second source. Note that
  [lse-terminal-brazil](https://github.com/PedroDnT/lse-terminal-brazil)
  reads the same COTAHIST files and is **also unadjusted**, so it is a
  parser cross-check (its `_PRICE_SCALE = 100.0` agrees with our `_implied`
  two-decimal convention) — not an adjustment cross-check.

### The shape adjustment should take here

When it is built, it follows the rules already in force:

- Ingest the **published event and its stated ratio** into its own table
  (`b3_corporate_event (ticker, ex_date, event_type, ratio, cash_value,
  source, raw)`), keyed on `(ticker, ex_date, event_type)`. Deriving a
  cumulative factor by multiplying published ratios is arithmetic on
  published data, which is allowed; **inferring** a ratio from a price gap is
  fabrication, which is not.
- Serve adjustment as a **separate metric** — `close_adj`, with
  `adjusted = TRUE` and the event table as its `source` — never by mutating
  `close`. Both must remain fetchable, because "what did it actually trade
  at" and "what is the comparable series" are different questions and the
  warehouse should answer both.
- A ticker with **no** event coverage returns `close_adj` as **null**, not as
  a copy of `close`. Silently passing an unadjusted price through an
  "adjusted" column is exactly the fabrication the integrity rules exist to
  prevent.

Sequencing: this is worth doing **before** phase D and arguably before
phase C — an unadjusted `close_return` is a wrong number being served today,
whereas the missing curves are merely absent ones.
