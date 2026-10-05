# Open items

Written 2026-09-18, closing the session that shipped catalog v28 and v29.
Everything here is **deliberately not done**, not forgotten. Nothing in this
list is broken in production — see "Known good" below.

This is the **single** register of open work. Items 7–11 were merged the same day
as a second list, in `README.md` of this directory, written by another session
that could not see this one; they are folded in here and that list is now a
pointer. Anything provisional or missing goes in this file.

## Known good as of 2026-09-18

| Surface              | State                                                                                                                               |
| -------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| Data API (PostgREST) | catalog **v30** live (`inflation`, `inflation_items`), applied 2026-09-21                                                           |
| Docs site            | `octo-98895abd.mintlify.site` — 200, including `known-limitations` and `api-docs/inflation`                                         |
| Dashboard            | `silo-bz-deloslabs.vercel.app` and `silo-bz.vercel.app` — both 200 on the current build **only since a manual promote**; see item 8 |
| Test suite           | 1521 offline tests green on `main` (1463 before catalog v30)                                                                        |

Verified live, not inferred: `income_statements('PETR4')` returns
`chart=industrial`, net income R$37.01bn; `income_statements('19348')`
(Itaú Unibanco) returns R$42.13bn resolved from conta `3.09`.

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

## 3. `/growth` is fixed in the repo but not published anywhere

**Blocked 2026-09-25, cause established:** root `vercel.json` builds only
`dashboard/` (`cd dashboard && npm run build`), so `webapp/` is deployed by **no**
project; `CLAUDE.md`'s "both hosted under `silo-bz`" is wrong for `webapp/`.
Needs a decision: a new Vercel project rooted at `webapp/` (an account change),
or moving `/growth` and its sources into `dashboard/`.

`webapp/pages/growth.md` + `webapp/sources/supabase/cia_growth_*.sql`. The
fiscal-year bug is fixed on `main` (PR #270), but the page is **not reachable on
any public URL** — `/growth` is 404 on both dashboard hosts, which are the
`dashboard/` Evidence site, not `webapp/`.

So: no user ever saw the broken version, and no user sees the fixed one either.
Whoever owns the `webapp/` Vercel project needs to deploy it; this session could
not determine which project that is. (`webapp/README.md` records why none can
exist yet: `vercel.json` builds `dashboard/` only, so `webapp/` needs a second
Vercel project or another static host.) Evidence builds its parquet at deploy time,
so the source-query fix only takes effect on a rebuild.

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

## 10. Supabase storage near the plan allowance

**Measured 2026-10-05 (UTC-3): 87.18 GB, 65% of 135 GB** (`pg_database_size`), with
`cvm_fi_balancete` empty (migration 62). The account table is gone, the database is
under the 100 GB line, and what is left is the owner's call on a smaller compute size.

**Decided 2026-10-01 (owner): retire `cvm_fi_balancete` behind a summary.** Nothing reads the
account table (31 GB, 27% of the database, which was 116 GB that day). Steps: (1) the summary
`cvm_fi_balancete_resumo` (migration 59) and its backfill, `daily_ingest` mode=balancete-summary;
(2) the fee accounts, mapped from CVM's COFI chart (Instrução CVM 438) and carried in the same
summary (done in migration 59); (3) the owner sees the month-by-month check, then the account table is
emptied (migration 62: a guarded TRUNCATE, not a DROP, because migration 22 alters the table on every
schema apply; it fires only when every stored month has summary rows, and the ingest writes only the
summary from then on); (4) the CDA tables stop repeating the fund name in `raw` (about 4.8 GB, measured
2026-10-01). Deleting rows does not shrink the billed disk; the saving comes from a smaller
compute size once the database is under 100 GB, the owner's call.

**Decided 2026-09-29 (owner): measure first, alarm at 90%, retention ready.**
DB Health read **115.65 GB, 86% of 135 GB** on 2026-09-29, after the CDA
block 1 refill (#348) grew `cvm_fi_cda` from 4.2 GB to 6.3 GB. It read
113.57 GB the day before. That is below the 118.1 GB measured on
2026-09-25, so the size is not climbing at a steady ~1.1 GB/day.

1. **Measure.** Read the size from DB Health's daily log for seven days,
   through about 2026-10-06, before choosing between a plan upgrade and
   retention.
2. **Alarm.** DB Health fails above 90%. The 85% warning stays.
3. **Retention.** If the alarm fires, retention falls on `cvm_fi_balancete`.
   The default is to keep 2019 onward. Measure the per-year sizes in Supabase
   first, and get the owner's OK before the delete runs.

**Re-measured 2026-09-25, BLOCKED on a retention decision (Pedro's call).**
`pg_database_size` = **118.1 GB, 87% of 135 GB**, up from 81% (~109 GB) on
2026-09-17: ~1.1 GB/day, which fills the allowance around **2026-10-10**.
Largest relations (incl. partitions and indexes): `cvm_fi_balancete` 33.6 GB,
`cia_account` 29.6 GB, `cvm_fi_cda_acoes` 12.6 GB, `cvm_fi_cda_cotas` 11.0 GB,
`cvm_fi_diario` 8.6 GB, `b3_cotahist` 8.2 GB. Options: a plan upgrade, or
retention on `cvm_fi_balancete` (the largest, and backfillable from CVM, so
dropping old years loses nothing unrecoverable). The daily growth rate is
inferred from two points, not a series; re-measure before acting on the date.

Reported at 81% of the 135 GB allowance on 2026-09-17 and **not re-measured
since**. Ingest stops when it fills, and the largest tables (`cvm_fi_diario`,
`cia_account`, `b3_lending_trade`) grow every day. Worth a real measurement and
a retention decision before it is urgent rather than after.

## 11. `sdk/silo_client` is not published

**Blocked 2026-09-25:** needs a PyPI account/project name and a token secret;
no repo change unblocks it.

`pip install silo-client` does not resolve; callers vendor the directory. See
[SDK.md](SDK.md) for what else the client is missing (PyPI, wheel CI, async).

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

## 13. B7 agent loop: test passed, prompts written, nothing scheduled

[AGENTS.md](AGENTS.md) is approved (2026-09-24). The manual Builder run on FIDC
informe `tab_X_7` (AGENTS.md §5) passed: PR #291 merged on 2026-09-24 with 0
human-edited lines after the agent's commit and a green first CI. The prompt
files `.claude/agents/scout.md`, `builder.md` and `sentinel.md` exist
(2026-09-25). Still the owner's: create the `agent:<name>`
labels, schedule the routines one at a time and fill in their ids in the
AGENTS.md §3a registry, and (optionally) run
`docs/reference/security/sentinel_readonly_role.sql` so the Sentinel can read
`cvm_ingest_log` and `fnet_document`; without it the Sentinel runs on the
public API only.

`bash scripts/setup_agents_wizard.sh` (2026-10-05) walks the owner through the
labels, the Sentinel role and its own cloud environment; the routines are then
created from a Claude session, which fills in the §3a registry.

## 14. The gaps backlog: resolution plan (2026-09-24)

Sequences the [COMPETITIVE_GAPS.md](COMPETITIVE_GAPS.md) §7 backlog (B1 to B11).
B1, the FNET register, is built (migration 42) and served since catalog v33
(`api.fund_documents`, `api.fund_restatements`, #286). Waves run in order;
within a wave, items are independent unless marked.

### Wave 1: no decisions needed

| #   | Item                                                                                                                                                              | Catalog |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| 1a  | FNET backfill option in `backfill.yml`, so the `run_backfill --fnet-only --fnet-start … [--fnet-sweep]` load can be dispatched from Actions                       | none    |
| 1b  | Serve FNET: `api.fund_documents` and `api.fund_restatements`, following `19_api_contract.sql` (grants, catalog entry, contract test, OpenAPI, SDK version)        | v33     |
| 1c  | Lineage (B6): `git_sha` and `parser_version` on every `cvm_ingest_log` row, exposed through `coverage()`. After 1b, so the two catalog bumps do not collide       | v34     |
| 1d  | Housekeeping: the B3 BDI tables in `DATA_INVENTORY.md` §1 and §3, and `webapp/README.md` stating the site is built but not deployed (item 3). Done on this branch | none    |

Then run the FNET history backfill, **one year per dispatch, newest first**, so
a throttled or failed run costs one year and the most useful history lands
first.

### Decision gate 1: Pedro

Nothing in wave 2 that depends on these starts until each has an answer.

1. The older `fidc_*` endpoints trim silently at 500 / 5000 rows. Switch them
   to raise-only (SQLSTATE `22023`), like the newer ones?
   **Answered 2026-09-26: no.** Keep the silent trim; wave 2e is dropped.
2. Put `versao` into the keys of `cvm_fii_mensal` and `cvm_fii_periodic`? This
   changes their grain, and it is what stops a restatement overwriting the
   original (`DATA_INVENTORY.md` §2, `COMPETITIVE_GAPS.md` B4).
   **Answered 2026-09-26: yes.** Wave 2d is unblocked.
3. Where to host the read-only MCP (B2)? A new runtime; a Vercel function is
   the obvious candidate. **Answered:** a Supabase Edge Function, deployed
   2026-09-25 at `https://zcjbtpxuhdekpwcxmepn.supabase.co/functions/v1/silo-mcp`.
4. A read-only database role for the Sentinel agent ([AGENTS.md](AGENTS.md),
   item 13)?
   **Answered 2026-09-26: yes.** `docs/reference/security/sentinel_readonly_role.sql` plus
   `default_transaction_read_only = on`; the owner runs it by hand. Role not yet
   present (checked `pg_roles` 2026-09-26).

### Wave 2

| #   | Item                                                                                                                                                                                                                                                           | Needs              |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------ |
| 2a  | ~~`api.screen_restatements`: funds and months with restated filings, by `modalidade`~~ done, catalog v37 (`25_api_filing_screens.sql`)                                                                                                                                                                             | 1b                 |
| 2b  | ~~Filing punctuality and silent funds, from FNET delivery timestamps~~ done, catalog v37 (`screen_late_filers`, `screen_silent_filers`)                                                                                                                                                                                             | 1b                 |
| 2c  | B4, field-level restatement diffs (`fnet_document_diff`): designed in [DOCUMENTS.md](DOCUMENTS.md), §11 decided 2026-09-26 (slice 1: FIDC mensal, 2026 backfill); built: ingest (migration 46, `fnet_diff`) and serving (`fund_restatement_diff`, catalog v40) | 1b                 |
| 2d  | FII keys carry `versao`                                                                                                                                                                                                                                        | gate 1, yes to (2) |
| 2e  | ~~`fidc_*` caps raise instead of trimming~~ (dropped: gate 1 answered no)                                                                                                                                                                                      | gate 1, yes to (1) |
| 2f  | B4 backfill of 2025 and earlier: restatement diffs for older years, newest-first, one year per dispatch; depth and runner-time budget set from the 2026 run's runtime and FNET latency (DOCUMENTS.md §11, decision 6). **2026 evidence (2026-10-05):** 16 `fnet`/`diff` runs, all ok, 6.8 min on average and 27.5 at most, 333,988 diff rows; of 20,056 `fnet_document_pair` rows 1,986 are `compared`, 17,976 `unpairable_no_link` (no `cnpjFundo` link yet; decision 4 has them wait for the sweep, now 1/150 of the FII/FIDC registry a night), 88 `unsupported_root`, 6 `declared_mismatch`. Depth is Pedro's call                                          | 2c's 2026 run      |

### Wave 3

| #   | Item                                                                                                                                                                     |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 3a  | B2, the read-only MCP over schema `api`: **deployed 2026-09-25** (49 tools)                                                                                              |
| 3b  | ~~B3 remainder: `company_events`, `macro_series`, `ptax`~~; **done 2026-09-25** (catalog v38, `26_api_events_macro.sql`); CRI/CRA still parked: needs a third kind of id |
| 3c  | B5, Sheets and Excel recipes: `api-docs/spreadsheets.mdx`, shipped with 1d                                                                                               |

### Wave 4: later, in order

- **B7.** One manual Builder run on FIDC `tab_X_7` (item 13), then Scout and
  Sentinel only if it passes. **Passed 2026-09-24 (PR #291); prompts written
  2026-09-25; labels and routines pending.**
- **B8.** DI curve and futures (`INSTRUMENTS.md` Phases B and C). **Ingest done
  2026-09-27 (PR #355, migration 48):** DI1 per contract from 2018, B3 `PRE`,
  `DOC` and `DPL` curves from 2008; **history loaded 2026-09-28** by the
  `market_backfill.yml` dispatches, with the `EIA_API_KEY` secret set. Gaps
  are the source's: B3 serves empty archives for `TS150827` and `PR210610`,
  `PR210104`'s newest version is malformed, and on 2018-05-10 and 2025-09-11
  its Price Report omits open interest for contracts that held positions
  (research doc §10, missing sessions). **Served since catalog v42** (`27_api_rates.sql`):
  `future_curve`, `future_series`, `curve`, `curve_history`, live after the
  next analytics apply and a `deploy_mcp.yml` run. **Shown on the dashboard's
  `/rates` page since 2026-09-30** (curves, breakevens, DI1 open interest). The futures arm of
  `api.panel` (`id_type='future'`, phase B) is built (catalog v61). Owner decision: whether
  2021-01-04's DI1 may come from that day's earlier, well-formed versions of
  the Price Report. Owner-only, only if VIX itself is wanted: a signed Cboe
  licence (permissions@cboe.com) before setting the `CBOE_VIX_LICENSED`
  repository variable. Until then the risk regime is the OFR Financial Stress
  Index (`docs/reference/research/dustin_br_data_sources.md` §3.C).
- **B9.** Alerts, only on signals from waves 1 and 2 once they exist.
- **B10.** Document text (Stage 3), priority categories only.
- **B11.** Per-event adjusted prices, where verified.

## 15. Portfolio diagnosis: decisions still open (2026-09-26)

Fee comparison slice (#614 / #609): implemented as `api.portfolio_fee_peers` and
`fees.comparison`; see [method and rollout](../reference/portfolio/fee-peer-comparison.md).
Analytical SQL, MCP and engine deployment plus live coverage/cold performance
validation remain. Equivalent products are still undecided; this slice does not
complete #609, #606 (return engine) or #607 (brief).

**Superseded by map #510 (2026-10-03).** #340 and #341–#345 were closed as not
planned on 2026-09-30. The demo is now map #510 (label `demo-diagnostico`),
built on the Phase 0 note `docs/reference/research/portfolio-diagnosis-phase0.md`.
The owner's decisions of 2026-10-02 (UTC-3), recorded on #510:

- Hosting on Cloudflare: revised on #519 to one Worker (static assets) plus a
  Container for the Python engine, no Pages. The first safe deploy, a
  health-only Worker and Container (`deploy/cloudflare/`,
  `deploy_cloudflare.yml`), went green on 2026-10-03. The engine image
  (`deploy/cloudflare/engine/`, built and smoked by `engine_image.yml`) is
  step 1 of slice E; step 2 (#572) runs it as the Worker's Container behind
  `POST /diagnose` and an upload page, deployed on 2026-10-04, with silo-mcp and
  api.openai.com reached through the egress allow-list. **The report is blocked:**
  OpenAI answers 403 `model_not_found` for `gpt-6-luna` with the key in
  `OPENAI_API_KEY` (every gpt-6 model, per `probe_openai_models.yml`). Owner's
  choice of 2026-10-04: `gpt-5.1` at medium reasoning (`demo/llm-gpt-5-1`).
  Deploy run 37226627623 then produced a complete report (US$0.31, 218 s), but
  the marked one came back with narrative `unknown` and the privacy probe did
  not run; `fix/narrative-reason-header` names the cause in a header and runs
  the probe before failing. Run 37230811125 showed the Redator cut at 16,000
  output tokens (11,091 reasoning), so the OpenAI limit is 32,000
  (`fix/llm-max-tokens-32k`). Next: redeploy. OpenAI marks
  gpt-5.1 deprecated (shutdown 2027-04-01, replacement gpt-6-sol), so the model
  has to move again before then.
- Engine in Python `src/portfolio/`, set-based `api` functions in
  `31_api_portfolio.sql`, Supabase reached through the read-only `silo-mcp`.
- Sunday scope: spreadsheet input, blocks 1, 3, 10, 11, 14 (screens), 4, 2, PDF.
- The disclosed fund fee must be correct, not only the balancete estimate:
  slice A adds the `cad_fi` fee columns (migration 64) and the CVM lâmina.
- Cost cap US$1.00 per report; investigator cap 20 searches per report.
- Report LLM (owner, 2026-10-03): the Anthropic key has no credits, so the Redator and
  Revisor run on OpenAI at medium reasoning (`SILO_LLM_PROVIDER=openai`, branch
  `demo/openai-provider`), `gpt-5.1` since 2026-10-04 (was `gpt-6-luna`); `anthropic` stays selectable, the cap is unchanged.
- **Parked:** the material-restatement thresholds below. Restatements are
  reported as "revised, not assessed" until they are set. The abnormal-movement
  rule is no longer parked: owner's decisions of 2026-10-03 are implemented as
  `api.portfolio_movement` (catalog v54) and the engine's `movement` section
  (schema 1.3), branch `demo/movement`: atenção beyond 2 class standard
  deviations (table only), forte beyond 3 (text, Investigator trigger), class =
  the ANBIMA class as filed in the Extrato, winsorized at the 1st and 99th
  percentile, at least 30 peers. Live after an analytical apply and a
  `deploy_mcp.yml` dispatch. Measured flag rates are 5.2% to 5.7% (beyond 2) and
  2.4% to 2.9% (beyond 3), below the owner's 10% and 6%; see the CHANGELOG row.
- **Served since catalog v51** (`31_api_portfolio.sql`): `api.portfolio_resolve`,
  `api.portfolio_fees`, `api.portfolio_lookthrough` (blocks 1, 3, 2, 10 of the
  engine). Live after the next analytical apply and a `deploy_mcp.yml` dispatch.
- **Catalog v52** (branch `demo/extrato`): the disclosed fee is read from the CVM
  Extrato first (`cvm_fi_extrato`, migration 66), then the lâmina, then cad_fi,
  with `filed_zero` and `implausible_filed`. Live after the schema apply, an
  analytical apply and a `deploy_mcp.yml` dispatch; the table is empty until a
  `daily_ingest` run (current file) or a `backfill.yml` `fi_doc_type=extrato`
  dispatch (yearly files, 2021 onward) loads it.
- **Engine and report on catalog v52** (branch `demo/engine-extrato`): `src/portfolio/fees.py` reads the
  Extrato columns and follows `disclosed_origin`; the report reads the engine through `report/adapt.py`.
  Both were tested offline against canned rows, not against the live function.
- **Catalog v55, engine 1.4** (#552, branch `feat/lamina-beside-extrato-552`): when the Extrato files 0 or
  above 5% a.a., `api.portfolio_fees` returns the lâmina's fee beside it, or makes a NEWER lâmina with a
  fee in (0, 5] the source (`fee_resolution`), and flags a factor of exactly 10 or 100
  (`extrato_scale_factor`). Nothing is rescaled or summed. Live after an analytical apply and a
  `deploy_mcp.yml` dispatch.
- **Catalog v56, engine 1.5** (branch `feat/fee-totals-lamina-etf`, owner's decisions of 2026-10-03): a
  `lamina_newer` fee is summed and compared like any disclosed fee, still flagged "fontes divergem". ETFs carry
  a fee: `portfolio_resolve` maps an ETF ticker to its CNPJ (`etf_ticker`) and `portfolio_fees` serves the
  etfsbrasil.com.br fee (`etf_site_*`), summed apart in the engine. Live after an analytical apply and a
  `deploy_mcp.yml` dispatch. Open: the ETF fee is a third-party scrape that self-skips without `APIFY_TOKEN`;
  a CVM-filed ETF fee source (the regulamento) is not ingested.
- **Catalog v57, engine 1.6** (branch `feat/etf-cotistas-pl`, owner's decision of 2026-10-03): each ETF line
  also shows the site's cotistas and PL from the fee's snapshot (`etf_site_nr_cotistas`, `etf_site_pl`),
  credited to etfsbrasil.com.br with the date, never summed. Live after an analytical apply and a
  `deploy_mcp.yml` dispatch. Open: CVM has no 2026 daily report row for any registry ETF, so the same
  `APIFY_TOKEN` dependency applies.
- **Engine 1.7** (branch `fix/portfolio-diagnosis-usefulness`, owner's approval of 2026-10-04, after a real
  41-line statement lost 52% of its value to one `portfolio_resolve` timeout): resolve is split and retried, a
  statement CNPJ identifies its fund when resolve does not, an infrastructure failure answers 503 instead of a
  PDF, the spreadsheet takes `vencimento` and `taxa`, repeated assets merge, the gaps section is fixed text, and
  the report gains issuer, maturity and FGC tables. Open: CRA/CRI/debenture identification by code (next PR);
  concentration by manager and fund liquidity need an `api` path for the manager's CNPJ and the lâmina's
  `qt_dia_pagto_resgate`, which no function serves today.
- **Engine 1.8** (branch `feat/portfolio-report-charts-fees-risks`, owner's brief of 2026-10-04): the report gains
  static SVG charts beside their tables, the fee headline "Quanto a carteira paga em taxas" (`fees.summary`) and
  "Principais riscos" (`risks`, fixed thresholds in `src/portfolio/risks.py`). Open: the liquidity risk row stays
  "não avaliado" for the same missing `api` path as above.
- **Catalog v61** (branch `feat/api-portfolio-instruments-terms`, migration 73): the two `api` paths the items
  above were waiting for. `api.portfolio_instruments` maps a statement's CRA/CRI code to its series in
  `cvm_securit_serie` and a debenture ticker to CDA block 4 (ISIN, issuer code, funds holding it, their mark);
  `api.portfolio_fund_terms` serves the manager and administrator from `cvm_fund_registry` and the redemption
  terms from the Extrato, else the lâmina. Live after the schema apply (index), an analytical apply and a
  `deploy_mcp.yml` dispatch. Open: the engine side (identification by code, concentration by manager, the
  liquidity risk row) is a separate branch.
- **CVM 175 levels** (#543, branch `claude/cvm175-levels-543`, migration 67):
  `cvm_registro_fundo` / `_classe` / `_subclasse` let a class reach its fund by
  `ID_Registro_Fundo` and a subclass its class by `ID_Registro_Classe`. Empty until
  the next `daily_ingest` applies the migration and loads the registry; then check
  that class → fund links resolve (132 of 36,770 did in `cvm_fund_registry`). Not
  served yet: `api.portfolio_resolve` / `portfolio_lookthrough` would need a view
  over the three tables.

The list below is the 2026-09-26 state, kept for the parked thresholds and the
other open points. Design: `PORTFOLIO_DIAGNOSIS.md`. Old tickets: map #340
(#341–#345), closed.

Data blockers:

- **#348 is done.** CDA block 1 had kept one bond per fund. #357 fixed the
  key, and every year from 2005 to 2026 was re-ingested with `backfill.yml`
  `fi_force` (#358), in runs 36334547066 and 36507066869 (2026-09-27 and
  2026-09-28). The issue was closed on 2026-09-29.
- **#352 is open:** CDA block 2.

Neither blocks writing code; each blocks a demo number.

- **Equal-risk-contribution grouping.** Holding level is the default. Open:
  whether a what-if may group by issuer or asset class instead.
- **Minimum history per holding.** How many of the 60 monthly returns a holding
  needs before it enters the covariance; fewer is an unknown section, never a
  filled series.
- **Material-revision fields and thresholds.** The named field list and the
  numbers, keyed on `field_path` / `leaf` (`cvm_column` is NULL). Set when the
  demo FIDC is chosen.
- **Demo portfolio positions.** About eight real positions containing the three
  planted findings: a directly held stock also held through a fund, a material
  FIDC restatement, an NTN-B.
- **Warning severity scale.** Not designed.

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

## 17. Audit protocol and the 2026-10-02 architecture review: resolved and open

Written 2026-10-02 from an architecture review that found six deepening
candidates. Candidate 02 (one audit protocol for ingest slices) is mostly built;
the rest was looked at and deliberately left. Nothing here is broken in
production. The code changes below deploy with the next daily ingest, not at
merge.

### Resolved

| PR   | What it settled                                                                                                                                                                                                                                                                                                                |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| #495 | ANBIMA, ETF market and CVM could finish without a `cvm_ingest_log` row (integrity rule 3); they now always write one. `AGENTS.md` now states the real `upsert_rows` signature and chunk (500 by default, CI sets 5000).                                                                                                        |
| #496 | ANBIMA raises when a boletim parses to zero records (owner decision), instead of logging a clean empty run. `run_b3_events`'s docstring says what the step does.                                                                                                                                                               |
| #497 | `cnpj_length_check.yml`, a read-only, manual workflow with no secrets, that measures CNPJ digit lengths in CVM source files. It cannot touch the database or the dashboard.                                                                                                                                                    |
| #498 | Rule 4 says what `mapping.coerce("cnpj")` does (strip punctuation, zero-pad to 14). Measured 2026-10-02: every fund, class, company, FIDC and FII identity CNPJ already has 14 digits, so it pads nothing there. A column that can hold a CPF is typed `text`.                                                                 |
| #499 | `ingest_log.audited` can end a run `skipped`, or `error` without raising, through `Outcome(rows, status, error)`. A bare row count still means `ok`.                                                                                                                                                                           |
| #500 | Market and ANBIMA write their audit rows through `audited`; their own start and finish code is gone.                                                                                                                                                                                                                           |
| #501 | All 14 `B3Ingestor` methods go through one `_audited` helper; `_log_start`, `_log_finish` and `_doc_type_of` are gone. A partial B3 failure still writes an `error` row and returns normally, so the step stays green (owner decision). `audited` takes an optional `run_id` for the corporate-event sweep's proof provenance. |

Decisions taken by the owner on 2026-10-02: ANBIMA raises on an empty parse; B3
partial failure keeps exit 0 and the docstring says so; measure the CNPJ padding
before changing rule 4.

### Open

1. ~~**Check the B3 audit rows after the next daily run.**~~ Done 2026-10-05:
   the twelve `b3` `doc_type` values kept their names, and each of the four
   sweeps of the last three days carries a `run_id` matching its
   `corporate_events` row. The errors in the week are the source's (BTBTrade
   504/499 on 10-01, a FORWARD-less 2025-08-13 consolidated file) or the stale
   monthly caption #473 turned into a skip; `investor_participation` stops at
   2026-09-30 by design (T+2, the 10-01 reference needs the 10-05 session).
2. **Phase 4 of candidate 02: CVM.** `CVMIngestor` still has its own start and
   finish code. It is the largest writer and overlaps candidate 03, so plan it
   with 03 before touching code. Not started.
3. **ETF market is not migrated.** It is a synchronous call from `run_daily`;
   folding it into the async `audited` would change `run_daily` and the event
   loop. It already writes through `ingest_log.start` and `finish`.
4. **Candidate 01, one home for each API endpoint's facts.** The inventory found
   no drift across 67 endpoints, so the large refactor is not recommended. An
   optional small version: generate the `catalog.postgrest` dict and pin the SDK
   version. Owner has not decided.
5. **Candidates 03 to 06, untouched:** the CVM dataset matrix in one place; one
   source runner for the `run_*` entry points; row ingest as one module (parse,
   drop, count); a read-side seam so SQL rules are not restated in Python.
6. **Rule 4 says every record passes `DataValidator`, and the CVM ingests do not
   all do it.** Rule and code disagree; which one changes is the owner's call.
7. ~~**The CNPJ measurement did not cover** CDA, securitization, FIP, the ETF
   registry or company filings.~~ Measured 2026-10-05, every column a field map
   types `cnpj`, in every member the ingests read: CDA 2026-08 (all blocks,
   with block 2's `CNPJ_FUNDO_CLASSE_COTA`), FIP trimestral 2023 and
   quadrimestral 2025/2026, CRI/CRA/OTS informe mensal 2026, DFIN CRA/CRI 2025,
   IPE and FCA 2026, ITR 2026, DFP 2025, and the ETF seed (187 rows). All have
   14 digits, so `coerce` pads nothing there either. The one ragged column
   seen, `CNPJ` in the securitization `cedente_devedor` member (CPFs, text,
   10 to 33 digits), is not read by any ingest.
8. **CVM skip versus error is a substring match** on `"Data not found"`, from
   `ValueError(f"Data not found at {url}")` in `cvm_fetcher.py`. B3 and market use
   typed exceptions. A reworded message would turn a skip into an error.
   **Guarded 2026-10-04** (`tests/test_not_published_contract.py`): the fetcher's
   real messages are classified end to end, so a rewording fails CI. The typed
   exception itself waits for item 2 (it touches every `except` in
   `cvm_pipeline.py`).
9. **Smaller findings:** ~~nine `tests/conftest.py` fixtures with no users~~
   (re-checked 2026-10-04: twelve, removed by owner's OK on
   `claude/remove-unused-conftest-fixtures`). ~~No pipeline-level test for
   `ingest_etf_market.py`~~: stale, `TestIngestEtfMarket` has covered the
   scrape, skip, error and audit paths since 2026-10-02; the default
   registry-ticker path and the dropped-record count got tests on
   `claude/etf-market-pipeline-test`, which also fixed (owner's OK) `_run()`
   returning `ingest_etf_market(conn)` unawaited, so
   `python -m src.pipeline.ingest_etf_market` scraped nothing. (ANBIMA's log
   columns are now tested through `daily_update`.)
10. **Stale remote branch `claude/audit-row-gaps`** (merged as #495, with later
    commits lost; the follow-up went out as #496). Delete only if the owner says so.
