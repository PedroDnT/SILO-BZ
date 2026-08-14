# iliquid dashboard

Evidence.dev analytics dashboard backed by the Supabase Postgres pipeline.

## Pages

Thirteen routes in three groups. `/` is the entry point: it carries the headline
figures, a "start here" reading path, and the grouped index below. Evidence builds
the nav automatically from the file stems, so the grouping lives in `index.md`, in
the cross-links between pages, and in the page titles — not in config.

**Industry-wide** — the market as a whole and the houses that run it.

| Page               | Path           | What it shows                                                                                                               |
| ------------------ | -------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Overview           | `/`            | Headline scale + freshness tiles, net assets by family (12mo), FIDC sector delinquency (12mo), grouped page index           |
| Industry Structure | `/industry`    | Net assets by family, concentration (HHI, top-N share), asset-class composition, FI flow, formation, investors, FIP, FIAGRO |
| Managers           | `/managers`    | Administrator and gestor league tables by net assets and net flow, led by the registry-name coverage disclosure             |
| Fund Explorer      | `/fund`        | Searchable fund universe first, then net assets / quota / return / flow series for the largest funds                        |
| Performance        | `/performance` | Per-asset-class ranking (who beat their peers), with the per-class return basis and the coverage caveat                     |

**By asset class** — one page per CVM family, plus the securitisation market.

| Page                | Path       | What it shows                                                                                                                                 |
| ------------------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| FI Industry         | `/fi`      | Net assets, daily flow, quotaholder base, investor mix (`cvm_fi_perfil`), single-holder screen, allocation (`cvm_fi_cda`)                     |
| FIDC Credit Monitor | `/fidc`    | Sector delinquency, worst funds, both aging bands, tranche promised-vs-realised, subordination, tranche flows                                 |
| FII Market          | `/fii`     | FII vs FIAGRO net assets, yield distribution, top payers, filing coverage, payout coverage, property explorer                                 |
| Securitização       | `/securit` | CRI/CRA/OTS reported value, maturity wall, payment waterfall, ratings, subordination, distressed series                                       |
| ETF                 | `/etf`     | ETF universe by provider / segment / index from `cvm_etf_registry`, plus the scraped market snapshot (NAV/return largely absent post-CVM-175) |

**Context and scrutiny** — what the numbers should be read against, and whether they landed.

| Page               | Path          | What it shows                                                                                             |
| ------------------ | ------------- | --------------------------------------------------------------------------------------------------------- |
| Macro Context      | `/macro`      | SELIC / CDI / IPCA / IGP-M series, PTAX FX and spreads, BACEN Focus consensus + dispersion, SGS inventory |
| Suspicious Screens | `/suspicious` | Zombie growth, evergreen aging, overdue securit series, captive vehicles — with thresholds stated         |
| Pipeline Health    | `/ops`        | Ingest freshness per entity, rows/day, status breakdown, table freshness, coverage, audit-log triage      |

### Page conventions

Applied uniformly across all thirteen pages, so a reader who learns them once can
read any page:

- **Structure.** Frontmatter `title` matches the `# H1` exactly. A `>` blockquote
  lede follows the H1 and states the headline finding **and** what the data does
  not support. Optional `<BigValue>` strip next, then `---`-separated `##`
  sections ordered by importance, each with its own `>` note where a caveat
  applies.
- **Units live in the column title.** Scaling happens in SQL: `(R$mm)`, `(R$bn)`,
  `(R$tn)`, `(%)`, `(pp)`, `(R$)`. Fields CVM publishes without a documented scale
  are labelled **source units** and shown unconverted.
- **Number formats** are drawn only from `num0 | num1 | num2 | '#,##0.00'`:
  counts and HHI `num0`; `R$mm` `num1`; `R$bn` / `R$tn` and quota counts `num2`;
  prices, FX and per-quota values `'#,##0.00'`; shares and rates `num1`; returns,
  yields and small ratios `num2`. `BigValue` tiles round one step coarser.
  **Years, series codes and série numbers carry no `fmt`** — `num0` renders 2026
  as "2,026".
- **Never suffix a percentage-point column with `_pct`.** Evidence treats the
  token after the last underscore as a format tag: `growth_pct` means "this
  value is a 0–1 fraction, display as percent" and multiplies by 100. This
  dashboard stores percentage points in SQL (1.5 = 1.5%). Tables overrode the
  tag with `fmt=num1` so they looked right; charts inherited `_pct` and showed
  150% for a 1.5% rate (live `/fidc` delinquency, `/fund` returns, `/macro`
  IPCA). Name the column `*_num1` or `*_num2` instead — those are the formats
  we actually use.
- **Chart type follows data shape.** Stock or level over time → `LineChart`, or
  `AreaChart` when it is a composition; per-period flows and counts → `BarChart`
  (high-frequency daily flows stay lines for legibility); categorical ranking →
  `BarChart swapXY=true`.
- **Terminology.** "Net assets" is CVM's `vl_patrim_liq`; "quotaholders" is
  `nr_cotst`, a count of positions rather than of people.

## Data source

Connects to Supabase Postgres via `@evidence-dev/postgres`. The `supabase` source is configured in `sources/supabase/connection.yaml`. Credentials are injected at build time via environment variables or the Evidence settings UI.

```bash
npm install
npm run sources   # pull schema from Supabase
npm run dev       # http://localhost:3000
```

## Build

```bash
npm run build     # outputs to build/
```

Deployed to **Vercel** (project `iliquid-nightly`, primary live target). Can also be served as
a static build — point any static host at `build/`.

### Vercel configuration (`vercel.json`)

The build settings are pinned in the **repo-root** `vercel.json` rather than left to
Vercel's dashboard, deliberately:

```json
{
  "framework": null,
  "installCommand": "cd dashboard && npm install",
  "buildCommand": "cd dashboard && npm run preflight && npm run sources && npm run build",
  "outputDirectory": "dashboard/build"
}
```

It lives at the repo root (not in `dashboard/`) because the Vercel project's root
directory is the repository root — a `dashboard/vercel.json` is silently ignored there.
`"framework": null` (the "Other" preset) is the important part. With the root directory
unset, Vercel auto-detects the repo as a **Python** project (Flask `app.py` +
`requirements.txt`) and deploys the localhost-only control plane as a serverless
function, which crashes every request with `500 FUNCTION_INVOCATION_FAILED`. Pinning
framework to null and the build to the Evidence static output removes the functions
entirely.

Vercel **project settings must not override this** — leave Build & Output Settings
unoverridden so `vercel.json` wins. Keeping it in the repo also means the config is
reviewable and survives project re-creation; host config that lives only in a provider
dashboard leaves a failing build with nothing in the repo to fix.

**Required environment variables** (Vercel → Settings → Environment Variables). Evidence
reads datasource credentials from `EVIDENCE_SOURCE__<source>__<option>`; the source is named
`supabase` (`sources/supabase/connection.yaml`), so `npm run sources` needs:

```
EVIDENCE_SOURCE__supabase__host
EVIDENCE_SOURCE__supabase__port          # 5432
EVIDENCE_SOURCE__supabase__database      # postgres
EVIDENCE_SOURCE__supabase__user          # postgres.<project-ref> for the pooler
EVIDENCE_SOURCE__supabase__password
```

TLS is **not** an env var — it is pinned in `sources/supabase/connection.yaml`, because
Supabase rejects unencrypted connections (`connection is insecure — try using
sslmode=require`) and the setting is not a secret.

`npm run sources` queries Postgres at **build time** and bakes the results into the static
output, so a broken/expired database credential fails the build — the same credential
problem that has stalled the ingestion pipeline will also break dashboard deploys.

### Build preflight

`npm run preflight` (wired into the Vercel `buildCommand` ahead of `sources`)
connects with the same `EVIDENCE_SOURCE__supabase__*` variables Evidence uses
and asserts that a handful of expected tables exist.

It exists because the failure it replaces is close to undiagnosable.
`@evidence-dev/postgres` discards the underlying Postgres error:

```js
const lengthQuery = await connection.query(...).catch(() => undefined);
const rowCount = lengthQuery.rows[0].rows;   // TypeError on undefined
```

so pointing the dashboard at the wrong database makes every source fail with
`Cannot read properties of undefined (reading 'rows')` — the same message for a
missing table, a typo'd column, or a permissions problem — and the build then
hangs until the pooler drops the connection (~5 minutes) and reports
`Connection terminated unexpectedly`. The preflight turns that into one line
naming the host, the database, and the tables it could not find.

The most common cause is `EVIDENCE_SOURCE__supabase__host` pointing at a
Supabase **preview-branch** database (empty by design) rather than the project
`POSTGRES_URL` ingests into. Compare the two hosts first.

### Source queries must not return zero rows

Evidence writes a **zero-byte** file when a source query returns no rows, and the
build then fails reading it back:

```
Invalid Input Error: File 'supabase_<name>.parquet' too small to be a Parquet file
```

One empty source therefore breaks the whole dashboard, not just its own page. When
a query can legitimately be empty — a screen with no current hits, or a feed that
has not landed yet — drive it from a table that is always populated and `LEFT
JOIN` the optional data, so the columns come back NULL rather than the result
coming back empty. `sources/supabase/etf_market.sql` is the worked example.
