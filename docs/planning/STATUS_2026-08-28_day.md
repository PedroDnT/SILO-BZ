# Status — 2026-08-28 (day session)

Follows the overnight run (`STATUS_2026-08-28.md`). Ordered by what the user
asked for, not by what was easiest.

## 1. Adjusted prices — the source is open, half the fix shipped

**Shipped:** `close_unit` = `close / quotation_factor`, both published COTAHIST
fields, on all six typed cash views and as a panel metric (catalog v10). A paper
quoted per lot printing 4,200 now also serves 4.20 per unit; verified on a real
Postgres. Raw `close` and `quotation_factor` are untouched beside it and
`adjusted` stays `FALSE`.

**Unblocked:** last night's probe of B3's listed-companies API returned an empty
body and was written off. That was wrong. The endpoint takes its parameters as a
**base64-encoded JSON object in the path** and answers `200` with no content
when the token is missing; it also double-encodes its response. With the token
it publishes, per ISIN: `DESDOBRAMENTO`, `GRUPAMENTO`, `BONIFICACAO` with
factors and entitlement dates, plus cash dividends and subscriptions.
`b3_corporate_event` (migration 26) now lands those verbatim, swept daily over
the issuers that actually print on our own tape. Verified live: 78 events for
three issuers, 72 stored, idempotent.

**Deliberately not shipped:** a derived adjustment factor. B3's `factor` means
different things under different labels — PETR `DESDOBRAMENTO` carries `100.0`
while MGLU `GRUPAMENTO` carries `0.1`, which fit two incompatible conventions.
Applying one to all labels would rescale real prices by a wrong constant, which
is worse than unadjusted-and-documented. `vw_b3_share_count_event` puts the unit
close on each side of every entitlement date next to the published factor, and
the health job's diagnostics reduce it per label. **The convention that
reproduces what the tape did is the convention** — and only then does
`close_adj` ship.

## 2. Dashboard findings

| Finding                                   | Root cause                                                                                                                                                                   | Status                                                                                                    |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| ETF "manager" is the index publisher      | The page used a curated seed-CSV label as issuer, and the published manager was being NULLed at ingest by the CVM-175 class row (see the correction below)                   | Fixed at the ingest — manager / brand / index are three columns; 185 of 187 ETFs named                    |
| ETF table all NULL                        | Every column joined only the APIFY-gated scrape, and the CVM fallbacks were themselves empty                                                                                 | Fixed — NAV 187/187 and manager 185/187 from CVM, price from B3 as a unit price; fee still unpublished    |
| ETF NAV vs price confusion                | They are different published facts                                                                                                                                           | Fixed — both shown, separate as-of dates, never blended                                                   |
| FIDC aging axis unreadable                | 10 long category labels on a vertical bar chart                                                                                                                              | Fixed — horizontal, plus the missing completeness clamp                                                   |
| Year-boundary jumps in industry structure | FIP files yearly; `dim_fund` stamps its first period on 1 January, so it spiked every January on a monthly chart                                                             | Fixed — monthly filers only                                                                               |
| FIAGRO empty left edge                    | Fixed 24-month window vs a file that starts 2025-05                                                                                                                          | Fixed — spine start clamped to first published period                                                     |
| IBOV11 as `cash_security`                 | It is the **Ibovespa index line** — codbdi 02, ESPECI `IBO/`, ISIN `BRIBOVINDM18` (IND segment). Not an ETF; an "ends in 11" rule would have mislabelled it                  | Fixed — new `index` type, requires ESPECI **and** ISIN segment                                            |
| ETF volume gap from 2019-08               | Not missing data: BOVA11/BOVV11/IVVB11 printed under **codbdi 02 instead of 14** for 92 sessions (2019-08-19 → 2019-12-30), and subtype came from codbdi alone               | Fixed — `mv_b3_isin_subtype`: an ISIN keeps the subtype its decisive sessions show                        |
| What is in `cash_security`                | Subscription rights (`DIR`) and bonus rights (`BNS`) by volume — **not** the "exchange-traded debt" the docs claimed                                                         | Fixed — `right` / `bonus` split out; docs corrected                                                       |
| Jump at 2025-05 across FI metrics         | Not a FI effect at all — FI declines smoothly (25,691 → 25,250) with AUM rising steadily, and FIDC is smooth too. FIAGRO's file **starts** 2025-05: 3 funds, then 18, 26, 32 | Resolved — real onboarding appearing on a stacked total, annotated not "fixed"                            |
| Quotaholders missing for some classes     | Measured over all 2.3M fact rows: `nr_cotst` is on 100% of FI and 99.9% of FII, and on **zero** FIDC, FIP or FIAGRO rows                                                     | Resolved — the three families publish no count; docs said FIAGRO did, corrected, and the page now says so |

All ten are now answered, and every one of them turned on a measurement rather
than a second guess. The two that stayed open longest did so **because** the
first hypothesis was wrong — the 2025-05 jump is not in fund counts — and both
closed the moment production could be queried directly: one is FIAGRO's file
beginning, the other is three fund families that simply do not publish the
number. Neither needed a code change to the data; both needed the page to stop
implying otherwise.

One more finding, unprompted: **the ETF registry enrichment is broken.** 187
ETFs carry 8 managers, 8 NAV figures and zero administration fees, so the ETF
page falls back to B3 prices for nearly every row. Suspected cause is the
CVM-175 fund-vs-class CNPJ split; a diagnostic now measures it rather than
assuming it.

### Correction, same day: the CVM-175 fallback was not the fix

The registry fallback shipped above (`coalesce(r.gestor, fr.gestor_name)`)
carried a claim that all 197 ETF CNPJs are in `cvm_fund_registry` "so the manager
comes from there". The join is real; the column was not. Measured on production
after the deploy: **20 of 187 ETFs**, up from 16. The comment implied 187. That
was my error and the comment is corrected.

The real cause is one layer down and worse than an ETF problem.
`registro_fundo.csv` and `registro_classe.csv` both upsert into
`cvm_fund_registry` on `(cnpj, entity_type)`, and CVM **reuses the fund's CNPJ
for its classes** — 36,492 of 36,606 `CNPJ_Classe` values are also a
`CNPJ_Fundo`. `registro_classe.csv` publishes no `Gestor` and no `Administrador`
column at all, so those mapped to `None` and the class row, loaded second, wrote
NULL over the fund row loaded moments earlier. **36,343 funds lost a published
manager on every run**, ETFs merely among them.

A file may now only assert the columns it publishes. Replaying both real CVM
files: `gestor_name` 25,732 → 62,104 rows (34% → 74%); ETF manager 20 → 185 of
187; ETF administrator 21 → 187. TREND ETF BLOOMBERG — the fund the user asked
about — resolves to XP Allocation Asset Management, with Bloomberg confined to
the index name.

Two things worth naming. `apply_map` returns `None` both for "this file reports
an empty value" and for "this file does not report this column", and every
consumer had been treating those as the same fact. And the ETF fallback was
plausible enough to ship without measuring what it actually covered — the
measurement is what caught it, a day later than it should have.

Net assets were being discarded the same way: both files publish
`Patrimonio_Liquido` with its own as-of date, the field map read neither, and
they sat unreadable in the `raw` JSONB. Migration 28 maps them — NAV for 187 of
187 ETFs, up from 16.

Also measured: only 12 tickers have a `fator_cotacao` other than 1 — but four
of them carry **1,000,000**, so before `close_unit` those four served prices a
million times too large.

## 3. API field test

A fresh agent with only the published docs and one open research question found
that `serve/catalog.py` — the artifact agents fetch first — described the local
Flask adapter as though it were the deployed API, and said an over-cap panel
answers `400`. It does on the adapter; on PostgREST the SQL's `cap+1` LIMIT
returns **100001 rows with a 200**. An agent following the documented check
would read `200` and analyse a truncated panel. Fixed in catalog v11 with a test
pinning it. Full report: `API_FIELD_TEST_2026-08-28.md`.

It also, correctly, **refused** the half of its question the data cannot answer
(FIDC sector exposure → listed companies), rather than inferring exposure from
fund names.

## 4. Health gate

`health.yml`, daily 07:30 UTC, fully read-only: ingest errors, ingest activity,
completeness drift per monthly family, `api.*` contract, database size vs plan.
On its first production run it reported **29 ingest errors in 26h** — and
exposed two bugs of its own: it queried `error_message` (the column is
`error_msg`), and GitHub's default `bash -e` aborted the step at the first
failing check, defeating the "collect every failure, report once" design.
Diagnostics were also gated on the checks passing, so the step that explains a
failure was skipped exactly when it was needed. All three fixed.

The 29 errors were `fi / balancete` **TimeoutError** rows from the previous
day's backfill — slices that timed out against CVM and succeeded on retry (that
backfill finished 91/91 months). So the data was fine and the ALARM was wrong:
counting every error row in a window means it fires after every backfill, and an
alarm that always fires is one people learn to ignore. It now counts only slices
with no later success — "still broken", which is the thing worth waking someone
for.

A later correction from PR #136: a subsequent `skipped` heals an error too. CVM
404s an unpublished month, and a timeout on a month that does not exist yet is
not a broken warehouse. That predicate is not mine to merge.

## 5. Deploying it took three attempts, and the third failure was self-inflicted

Worth recording, because two of the three were the deploy pipeline defending
against itself:

1. **Run #183 was CANCELLED** after sitting pending 70 minutes. `daily_ingest`,
   `backfill` and `watchdog` share the concurrency group `supabase-ingest` with
   `cancel-in-progress: false`, and GitHub keeps only **one** pending run per
   group — so when the watchdog joined the queue it evicted the deploy. Nothing
   logged an error; the run simply disappeared.
2. **The retry FAILED** on `CREATE OR REPLACE VIEW vw_b3_instrument_typed`
   (migration 27) with `canceling statement due to lock timeout`. I attributed
   it to a Vercel production build holding read locks and re-dispatched with
   `rebuild_dashboard=false`. PR #137 has the better diagnosis: `CREATE
MATERIALIZED VIEW … WITH DATA` holds its `pg_type` insert uncommitted for the
   whole population scan.
3. **That run FAILED too** — at `ANALYZE`. Twenty ANALYZEs in a single psql
   string is one backend held open for minutes, and the loaded server terminated
   it. The step had no `continue-on-error`, so it skipped "Build / refresh
   analytical layer", which carries `continue-on-error` **precisely so it cannot
   block a run**. Production stayed on catalog v9 because a statistics refresh
   failed. Now `continue-on-error`, one psql per table.

Migration 27 did land in attempt 3 (schema apply succeeded), and the 2019 ETF
gap is closed in production: BOVA11 / BOVV11 / IVVB11 type as `etf` on their
codbdi-02 sessions, from 897 ISINs learned by `mv_b3_isin_subtype`.

**Attempt 4 failed too, and this one I caused.** `19_b3_cotahist_serve.sql`
timed out on its lock three times running. The lock holders were two Vercel
**preview** builds — started by my own pushes to the PR branch, each running the
full Evidence source scan against production Postgres and holding
AccessShareLock on `b3_cotahist` for tens of minutes. The schema apply crawled
for ten minutes and then gave up.

Which is the structural point worth keeping: **every push to a PR branch runs a
25–45 minute production-database scan**, and a schema apply cannot take its
locks while one is in flight. The deploy has retries and a `lock_timeout`, but
three attempts inside ten minutes cannot outlast a build that runs for forty.
Until preview builds stop reading production (their own snapshot, or an ignore
step that skips `dashboard/`-less commits), the operational rule is: **do not
dispatch a schema apply while any Vercel deployment is BUILDING.** Check
`list_deployments` first — it is one call and it is the difference between a
ten-minute failure and a five-minute success.

## 6. Verified sound (checked, not assumed)

- The FCA ticker field map holds across all history: the CSV header is
  byte-identical in 2019, 2022 and 2026.
- A 404 for an unpublished slice is already classified `skipped`, not `error`,
  by the shared audit path — the new FCA ingest inherits that correctly.
- The `cia_aberta` backfill landed: ~31M rows / ~26.5 GB across 2019–2026
  (`docs/CIA_DATA_MAP.md` §8). Still served by nothing.

## Operator queue

1. **Supabase MCP now works** in the assistant session after the reconnect — the
   read-only prod checks in this document were run through it directly.
2. **`APIFY_TOKEN`** — set it if the scraped ETF snapshot is wanted; the CVM/B3
   fallbacks now cover NAV, fee, manager and price without it.
3. **Rotate the committed publishable key** before go-live (per-user keys + RLS
   remain the real gate — `SERVING.md`).
4. **Disk: 78 GB after the CIA backfill**, up from 71.9 GB. `PLAN_DISK_GB=8` is
   the Supabase Pro **included** allowance, not the invented denominator I called
   it — PR #134 is right and I was wrong. So the percentage is a real spend
   signal: either add disk / raise the cap, or make a retention decision on
   `cvm_fi_balancete` (30 GB). **Do not** drop `cvm_fi_balancete`, the yearly
   `cia_account_*` or `b3_cotahist_*` partitions, and do not `VACUUM FULL` from
   CI — that is the same ACCESS EXCLUSIVE lock class that killed a schema apply.
