# Open items: done

The numbered items of `docs/planning/OPEN_ITEMS.md` that were done or superseded,
moved here on 2026-10-06 so the live register holds open work only (#679). The
numbers are the register's; nothing here is a queue.

Verified live on 2026-09-18, not inferred: `income_statements('PETR4')` returned
`chart=industrial`, net income R$37.01bn; `income_statements('19348')` (Itaú
Unibanco) returned R$42.13bn resolved from conta `3.09`.

---

## 1. ~~`balance_sheets` and `cash_flow_statements` — the other two endpoints~~ (done)

**Done 2026-09-25** (`feat/balance-sheets-cash-flows`, catalog v35). Census
run first; equity sits on 2.03 / 2.07 / 2.08, and `Empréstimos e
Financiamentos` is filed twice per industrial filing, so the balance sheet
matches label + parent label. Cash flows map totals only; capex and dividends
are free text per filer and stay in `api.financials`. Not live until
`apply_analytical.sh` runs (see item 6).

`docs/planning/FINANCIALS_API.md` §8 step 2. `income_statements` shipped first
because it carries the sector problem and proves the design; the other two
follow the same pattern with their own label maps.

**Do the measurement first.** The design lesson from the income statement is
that the surprises live in the data, not the SQL. Before writing anything, run
the label census for `BPA`/`BPP` and `DFC_MD`/`DFC_MI`:

```sql
SELECT cd_conta, ds_conta, count(DISTINCT cd_cvm) AS companies
  FROM cia_account
 WHERE grupo = 'BPA'            -- then BPP, DFC_MD, DFC_MI
   AND escopo='con' AND ordem_exerc='ÚLTIMO' AND doc_type='dfp'
   AND dt_refer >= '2024-01-01' AND dt_refer < '2025-01-01'
 GROUP BY 1,2 HAVING count(DISTINCT cd_cvm) >= 2
 ORDER BY cd_conta, companies DESC;
```

Expect the same shape of finding: one concept sitting on different codes across
charts. For the DRE that was net income on `3.09` / `3.11` / `3.13`.

Copy the structure of `api.income_statements` in
`src/store/analytical/19_api_contract.sql`, including:

- match on `lower(btrim(account_name))` — **never** fold accents or
  prepositions, `de` vs `da` separates two real bank charts;
- a `chart` column, informational, never consulted by the field mapping;
- NULL for a concept a chart does not file, never a borrowed neighbouring line;
- `DROP FUNCTION IF EXISTS` before `CREATE OR REPLACE` (a widened `RETURNS
TABLE` cannot be replaced in place on a deployed cluster);
- grants to `anon, authenticated` **and** `silo_api`;
- a contract test modelled on `tests/test_income_statements_contract.py`,
  fault-injected before it is trusted.

Bump `CATALOG_VERSION`, regenerate `openapi.json`, bump
`KNOWN_CATALOG_VERSION` in the SDK.

## 2. ~~`company_financials` and `income_statements` disagree on net income~~ (done)

**Done 2026-09-25** (`feat/company-financials-label`, catalog v36): option 2,
Pedro's call. `net_income` now matches the same two filed labels as
`income_statements`; bank B resolves from 3.09's net-income label and insurers
from 3.13. No code fallback. Live after `apply_analytical.sh`.

## 4. ~~Two changelog rows render with phantom columns~~ (done)

**Done 2026-09-25** (`fix/changelog-pipes`): the pipes inside the two rows'
code spans are escaped as `\|`, and `test_every_row_has_exactly_three_cells`
now pins the cell count (fails on the unescaped file, passes on the fixed one).

`docs/planning/CHANGELOG.md` has two historical rows containing an unescaped
`|` inside their prose — one of them is literally the panel cursor format
`date|id|metric|asset_class`. Markdown splits those cells, so both rows render
with extra columns.

Two-character fix (escape the pipes). Left as found rather than silently
rewriting historical entries. `tests/test_changelog_integrity.py` deliberately
does **not** pin cell count because of them.

## 5. ~~A `MAX()` over a filing date is not a period — check for more of these~~ (done)

**Done 2026-09-25** (`fix/max-period-sweep`). Swept by measurement, not by
reading: row counts at the latest vs previous period for every table a dashboard
source reads with a bare `max()`. One live instance: `distressed_securities()`
defaulted to `MAX(period)` of `fact_security_monthly`, which held **24** rows at
2026-08 against **3,260** at 2026-07, so `/securit` showed **10** distressed
series instead of **173**. It now defaults to the newest period with at least
half the previous period's rows; guarded by
`tests/test_distressed_period_resolution.py`. Clean at measurement:
`cvm_fidc_tranche`, `cvm_fidc_aging`, `cvm_fidc_tranche_flows`, `cvm_fii_imovel`
(latest periods fully populated), FIP (31-Dec key, already guarded per class).
Live after the next `apply_analytical.sh` run and dashboard rebuild.

**Addendum 2026-09-30 (#436):** the sweep missed a second instance.
`securit_issuance_trend.sql` put its `max(data_referencia)` inside `least()`, so
its trend ended on partial months: 2026-08 held 1,247 series against 2026-07's
6,810. It now uses the same half-the-previous-period rule.

PR #270 fixed one instance: `/growth` selected its comparison year with
`MAX(fy)`, which pinned the whole page to the 8 companies that had filed fiscal
2026, against fiscal 2025's 438. `CLAUDE.md` already warns about the same class
of error for `complete_through` and FIP being keyed 31-December.

That makes two independent instances of one mistake, which is enough to justify
sweeping for others rather than waiting for the third. Candidates are anywhere a
"latest period" is derived from the data instead of from coverage.

## 6. ~~Deploying the API is manual, and that is easy to forget~~ (done)

**Done 2026-09-25** (`fix/deploy-checklist`): the release-checklist route. The
`iliquid_nightly` skill, loaded for any `19_*.sql` / catalog / dashboard change,
now has a "Shipping: merging to `main` deploys nothing" section with both
manual steps and how to confirm each. An on-merge trigger was not added: it
would start a ~28 min matview rebuild on every merge.

`scripts/apply_analytical.sh` is what makes a merged catalog change live. It runs
on the 06:00 UTC `daily_ingest` schedule or a `workflow_dispatch` with
`mode=analytics-only` (leave `rebuild_dashboard` off for an API-only change — it
otherwise starts a 25–45 min production Evidence build). A full run takes ~28
minutes, most of it rebuilding materialized views before it reaches the contract.

Merging to `main` does **not** deploy. On 2026-09-17 the live catalog sat two
versions behind `main` for several hours for exactly this reason. Worth a line in
the release checklist, or an on-merge trigger.

The same is true of the dashboard, for a different reason: since 2026-09-17
`vercel.json` sets `git.deploymentEnabled.main = false`, so a merge creates no
production deployment at all. The site rebuilds once a day, from the deploy hook
the `daily_ingest` run POSTs at the end. Verified 2026-09-18: run #241 logged
`deploy hook responded 201` at 06:56:44 and `dpl_2SD7pSab…` was created one
second later with `deployHookName: nightly-ingest`, while ~13 merges overnight
created none. So a documentation change to `dashboard/pages/` is live on GitHub
immediately and on the public site the next morning, unless someone dispatches
`daily_ingest` with `rebuild_dashboard=true`.

## 7. ~~The docs site is on Mintlify's generated subdomain~~ (superseded)

**Superseded 2026-10-03 (`docs/scalar-rewrite`):** documentation rewritten from
scratch on Scalar. Mintlify is no longer the docs host. The `api-docs/` directory
and `docs.json` remain in the repo but are no longer the source; `scalar/` and
`scalar.config.json` are. Scalar syncs from GitHub on merge.

~~**Blocked 2026-09-25:** DNS record plus Mintlify plan; account action, no repo change.~~

## 8. ~~Production deployments stopped taking the public hostnames~~ (done)

**Cause found 2026-10-05 (#559), and auto-assignment is back.** Vercel turns off
the auto-assignment of production domains when production is moved to an older
deployment, and turns it back on when a deployment is promoted ("After a
rollback, Vercel turns off auto-assignment of production domains… To restore
normal deployment behavior, you need to undo the rollback by promoting a
different deployment", vercel.com/docs/instant-rollback). The 2026-09-18
manual promote below pinned both hostnames to an existing deployment, which is
that state. The first promote of a new build, 2026-09-26 (`promote responded
201`), ended it: since then the newest production build already holds the
hostnames when the 08:00 UTC check runs. On 2026-10-03 the check's promote of
`dpl_CWNAEhkR5Avo1mJgQ22cvEgPBR8A`, built that morning, answered `409 … is
already the current production deployment`. The rename itself did not cause
it. The audit log that would show the 09-18 action is not readable with the
project token (403), so the sequence is matched to Vercel's documented rule,
not read from the log. `promote_dashboard.sh` stays: it is a no-op while
auto-assignment works, and it is what restores it after the next rollback.

This is the one that bit. Between 2026-09-18 and 2026-09-22 the published site
did not move at all, while four production deployments went READY on top of it.
On 2026-09-22 Pedro reported not seeing the inflation section on `/macro`; it
had been built correctly and published nowhere.

Measured 2026-09-22, in this order:

| Observation                                                          | Result                                                                                     |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `GET silo-bz-deloslabs.vercel.app/macro`                             | 200, 31,867 bytes, **0** occurrences of "Inside the IPCA"                                  |
| `GET silo-bz-git-main-deloslabs.vercel.app/macro`                    | 200, 39,505 bytes, the section present                                                     |
| aliases on `dpl_f9YsSJ…` (f85e9f3, the newest production deployment) | `silo-bz-git-main-deloslabs.vercel.app` **only**                                           |
| aliases on the project                                               | both `vercel.app` hostnames bound to `dpl_54vMGARv4w1DAhyxD9ivfg7yCVXc` (6646c0c, PR #275) |
| that binding's `updatedAt`                                           | 1789743476015 = **2026-09-18T00:17:56Z**, and never since                                  |
| `list_promote_aliases`                                               | both hostnames `status: completed` — a **promote** was the last thing that moved them      |

So both hostnames are project domains (`gitBranch: null`, verified) that a
manual promote pinned on 2026-09-18, and nothing has reassigned them since. A
new production deployment now only takes the branch alias. The daily deploy
hook still builds, and the build is still correct — it is simply not published.

Fixed on 2026-09-22 by promoting `dpl_f9YsSJYKCx1LaQDbhGuDig6wzPt2`; both
hostnames now serve it, verified by fetching `/macro` on each and by pulling
the two inflation parquet files (9 group rows, 36 series rows) off the public
host.

**Guarded 2026-09-22, not diagnosed.** Why a production deployment no longer
auto-assigns the project domains is still unestablished — build logs do not
record aliasing and the API does not expose the decision, so there was nothing
to read. What exists now is a guard that makes the question moot rather than
answered:

`scripts/promote_dashboard.sh`, run daily at 08:00 UTC by
`.github/workflows/publish_check.yml`, promotes the newest READY production
deployment and then **verifies the public host actually serves it** by
comparing `/data/manifest.json` against the branch alias. An explicit promote
of a deployment that already holds the domains is a no-op, so the guard is
safe whether or not auto-assignment comes back. Verified 2026-09-22 against
the live hosts both ways: green when they match, and red when `PUBLIC_HOST` is
pointed at `silo-j01uw6fds-deloslabs.vercel.app` (the #275 build that was
actually being served during the freeze).

**Interim fix 2026-10-01 (not the durable one).** A dispatch with
`rebuild_dashboard=true` built a production deployment that nothing published
until a manual promote: the 08:00 UTC check only covers the scheduled run.
`publish_check.yml` now also runs when a `Daily CVM Ingest` run succeeds, waits
up to 45 minutes for the hook's build to leave BUILDING, and promotes it
(`WAIT_FOR_BUILD_MINUTES`, `scripts/promote_dashboard.sh`). It treats the symptom
only. The durable fix is the cause below; when Vercel assigns the project
domains to a production build again, delete the `workflow_run` trigger.

~~**Blocked 2026-09-25:** the cause needs Pedro: the Vercel audit log or support.~~ Found from Vercel's docs and the Publish Check logs instead; see the top of this item.

1. ~~**`VERCEL_TOKEN` is not set**~~ (done 2026-09-26). Pedro added the
   repository secret; a dispatched Publish Check (run 36212626171) promoted
   `dpl_Ei4YqaQyKpQNQ7zYL4X2oCKDB8Ws` after three red days (09-23 to 09-25)
   and verified it. Checked independently the same hour: `/data/manifest.json`
   is byte-identical on `silo-bz-deloslabs.vercel.app`, `silo-bz.vercel.app`
   and the `git-main` alias. The guard now fixes a freeze, not just detects it.
2. ~~**The cause**~~ (found 2026-10-05, above). Find and undo whatever the 2026-09-17/18 alias attempts left
   behind; they are recorded below because they are the likeliest culprit.
   Pedro does not remember making the change, so there is no memory to rely on
   here — it needs reading the Vercel project's audit log or support.

What those attempts were: the old `silo-bz.vercel.app` hostname was
reassigned five times on 2026-09-17 (`400: already assigned to another
project`; `--scope 0xpedro` fails with "You cannot set your Personal Account as
the scope"). The 2026-09-18 promote that pinned both hostnames came out of that
sequence. Note the old hostname is **no longer** frozen separately — the
2026-09-22 promote moved it too, so both now track the same deployment.

**The method lesson, again.** The session that shipped the inflation feature
reported it live on the strength of row counts in a build log and a deployment
reaching READY. Both were true. Neither was the site. `CLAUDE.md` already says
"row counts in a build log and pixels on the public URL are different
observations"; this is the second time that has cost a day. Fetch the public
URL and grep it for the thing you claim to have shipped.

## 9. ~~`coverage().landed_at` reads a day stale for the B3 lending group~~ (done)

**Done 2026-09-25** (`fix/b3-landed-at`): `_ingest_bdi_span` now logs `ok` when
older sessions landed and only the newest is missing, with the shortfall kept in
`error_msg` as a note (today `Outcome(rows, "ok", note)` in `ingest_log.audited`). A span where nothing landed
stays `skipped`; any older gap stays `error`. The PR #242 gate is unaffected:
`check_staleness.py` and diagnostic 15 treat `ok` and `skipped` alike. Live
`landed_at` moves on the first daily run after merge.

`landed_at` is documented as "when ingest last SUCCEEDED for that source", and
counts only `cvm_ingest_log` rows with status `ok`. But when B3 has not yet
published the newest session — most days at 06:00 UTC, since the open-position
book lags the trade tape by one session — `_log_finish(..., skipped=True)`
(`src/pipeline/b3_pipeline.py`) marks the slice skipped, even though the run
fetched and upserted the sessions that _were_ delivered.

Measured 2026-09-18: the run upserted 2,962 `b3_lending_open_position` rows at
06:32 UTC and logged `B3 delivered 1/2 requested sessions; missing 2026-09-17 —
newest session, not published yet`, while `coverage()` still reported
`short_interest.landed_at = 2026-09-17T08:55`. Our pipeline reported as stale
because of the source's calendar: the exact confusion `CLAUDE.md` names in "Do
not confuse OUR health with the SOURCE's", landing in the one field that is
supposed to be ours.

The fix is to log `ok` when rows landed and only the newest session is missing,
keeping `skipped` for the zero-row case. It is not a drive-by: the `skipped`
status is what PR #242 introduced to stop DB Health crying wolf, so any change
has to be read together with that gate and its tests.

## 12. ~~The inflation history is two one-off loads that have not run~~ (done)

Both ran on 2026-09-21 from **CVM Historical Backfill**. Run 35651030075
landed 81,104 `ibge_ipca_item_monthly` rows (2012-01 → 2026-08); run
35656620365 landed 72,060 `bacen_sgs` rows after `_SGS_MAX_WINDOW_YEARS`
dropped to 5. Verified on the published dashboard 2026-09-22:
`macro_inflation_series` carries 36 months ending 2026-08 with
`ipca_mes = -0.32` and `ipca_12m = 4.22`, and `macro_inflation_groups_latest`
carries all nine groups, whose contributions sum to -0.31 against a headline
of -0.32.

The inputs added to `backfill.yml` stay, so the loads are repeatable:
`bacen_only = true`, `bacen_sources = sgs`, `bacen_start = 1980-01-01`,
`ibge = true`.

## 16. ~~Two B3 matviews have no refresh path (found 2026-09-29)~~ (done)

**Done 2026-09-30** (`claude/refresh-b3-tape-matviews`, #439), on the owner's
instruction, and confirmed on the live database and the public site the same
day (checks below).

`src/store/analytical/22_b3_tape_matviews.sql` refreshes both matviews in every
analytical apply: the ISIN map first, then the monthly aggregate, CONCURRENTLY
so no reader is blocked, with a plain `REFRESH` for an empty matview. It is a
file of its own because `apply_analytical.sh` downgrades a failure of
`08_cron_schedules.sql` to a warning. pg_cron was not enabled: that is an
extension change on production, its jobs fire at 03:12 to 03:40 UTC-3 (06:12
to 06:40 UTC) while the ingest is still writing, and the apply already is the
daily refresh of every other matview.

Proved on a local Postgres 16 with the schema and the whole analytical layer
applied: with today's code, new tape rows reach neither matview; with the new
file they reach both, a second run changes nothing, an emptied matview is
refilled, and a failed refresh fails the apply. `tests/test_b3_tape_matview_refresh.py`
pins it, and fails if the refresh is removed or moved into the cron file.

**Confirmed 2026-09-30**, after `daily_ingest` run 36752752981 applied all 28
analytical files with no failure. `22_b3_tape_matviews.sql` took 3 min 37 s of
it, read from the log timestamps.

1. `mv_b3_monthly_activity` has a 2026-09 period (20 sessions so far). The month
   is still open, so the dashboard shows it from 2026-10-01.
2. August on `tpmerc = '010'`: 21 sessions and R$ 529.76 bn in the matview,
   equal to the tape.
3. Fund-quota ISINs traded in the last 60 days and missing from
   `mv_b3_isin_subtype`: 0 of 627. The map holds 906 ISINs, up from 897.
4. The public `/markets` data (`b3_monthly_volume`) reads August as
   R$ 529.76 bn over 21 sessions, after Publish Check run 36760305426 promoted
   the rebuilt deployment. Before, it read R$ 480.96 bn over 19.

**Going live, 2026-09-30.** `daily_ingest` with `mode=analytics-only` and
`rebuild_dashboard=true` was dispatched at 14:37 UTC-3 (17:37 UTC), run
36752752981, on `main` at the merge of this fix. Before it, the public `/markets`
data (`b3_monthly_volume`) read August 2026 as R$ 480.96 bn over 19 sessions.
The apply gains one full pass over the tape: the matview's first population
took 2 min 10 s on production (Daily CVM Ingest run 33207753376, 2026-08-28,
read from the log timestamps).

The record of what was found:

`mv_b3_isin_subtype` and `mv_b3_monthly_activity` are created in `schema.sql`
(migrations 27 and 30) `WITH NO DATA`, and the `REFRESH` beside each one runs
only while the matview is unpopulated. Their daily refresh is two pg_cron jobs
in `08_cron_schedules.sql`, at 03:12 and 03:18 UTC-3 (06:12 and 06:18 UTC). The
live database has no `pg_cron` extension (`pg_extension`, checked 2026-09-29),
so that file only raises a NOTICE, and `apply_analytical.sh` does not rebuild
these two. Neither has changed since it was first populated around 2026-08-28.

Measured 2026-09-29:

| Observation                                 | Result                                                                                           |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `mv_b3_isin_subtype` rows                   | 897, the count the 2026-08-28 status snapshot recorded                                           |
| Fund-quota ISINs traded in the last 60 days | 627, of which **9** are not in the matview                                                       |
| `mv_b3_monthly_activity`, newest period     | 2026-08-01; September is absent                                                                  |
| August, standard lot (`tpmerc = '010'`)     | **19** sessions and R$ 481.0 bn in the matview; **21** sessions and R$ 529.8 bn in `b3_cotahist` |

What reads them:

- `mv_b3_monthly_activity`: `/markets` (`b3_monthly_volume`, `b3_market_overview`,
  `b3_asset_class_volume`, `b3_options_activity`), `/etf` (`etf_market_series`)
  and `/flows` (`flow_adtv_monthly`, `flow_headline`). Those pages show a
  partial August as a full month.
- `mv_b3_isin_subtype`: `vw_b3_instrument_typed.instrument_subtype`, served as
  `fund_type` by `api.fund_quotas`, for a fund quota whose board code is not
  decisive.

No check covers it. DB Health's matview-lag check reads `fact_fund_monthly`
only, and `docs/reference/DATABASE_MAINTENANCE.md` still says the analytical re-create
"is the daily refresh", which is not true for these two.

Decided 2026-09-30: the refresh is a step of the daily run (the analytical
apply), not pg_cron. See the top of this item.

Found alongside: `mv_etf_landscape` existed on the live database and was defined
nowhere in this repository, so nothing refreshed it either, and nothing read it.
Migration 54 (`claude/drop-mv-etf-landscape`, 2026-09-30) drops it and keeps its
one-line definition, a `rank()` over `cvm_etf_registry`, in the file's comment.
On its first production apply (daily run of 2026-10-01, 03:00 UTC-3) the drop
failed: an object on the live database, defined nowhere here, now depends on the
matview, and that failure skipped the day's ingest and apply. Migration 54 is now
guarded (`claude/guard-migration-54`): it drops the matview only when nothing
depends on it, and otherwise raises a NOTICE naming the dependents in the
apply log. The NOTICE (run 36842444079) named `api.mv_etf_landscape`, an
equally unowned object in schema `api`. Owner's call on 2026-10-01: drop both
(migration 58, `claude/etf-universe-aum`), and show net assets, their date and
the size rank on `/etf`'s "ETF Universe" from the live registry instead. Closed
once migration 58's apply logs both drops.
