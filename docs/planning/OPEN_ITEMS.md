# Open items

Written 2026-09-18, closing the session that shipped catalog v28 and v29.
Everything here is **deliberately not done**, not forgotten. Nothing in this
list is broken in production — see "Known good" below. The one exception is
item 16, added 2026-09-30: a defect that is live.

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

## 7. The docs site is on Mintlify's generated subdomain

**Blocked 2026-09-25:** DNS record plus Mintlify plan; account action, no repo change.

`octo-98895abd.mintlify.site` works and is linked correctly from everywhere. But
a hex-string hostname reads as provisional to a first-time visitor, which is the
wrong signal for the one surface a stranger is most likely to open.

A custom domain needs a DNS record and a Mintlify plan that allows one — an
account change, not a repo change, so it cannot be done from here.

## 8. Production deployments stopped taking the public hostnames

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

**Blocked 2026-09-25:** the cause needs Pedro: the Vercel audit log or support.

1. ~~**`VERCEL_TOKEN` is not set**~~ (done 2026-09-26). Pedro added the
   repository secret; a dispatched Publish Check (run 36212626171) promoted
   `dpl_Ei4YqaQyKpQNQ7zYL4X2oCKDB8Ws` after three red days (09-23 to 09-25)
   and verified it. Checked independently the same hour: `/data/manifest.json`
   is byte-identical on `silo-bz-deloslabs.vercel.app`, `silo-bz.vercel.app`
   and the `git-main` alias. The guard now fixes a freeze, not just detects it.
2. **The cause** (still open). Find and undo whatever the 2026-09-17/18 alias attempts left
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
`error_msg` as a note (`_log_finish(..., note=)`). A span where nothing landed
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
(2026-09-25). Still the owner's: create the `agent-ok` / `agent:<name>`
labels, schedule the routines one at a time and fill in their ids in the
AGENTS.md §3a registry, and (optionally) run
`docs/security/sentinel_readonly_role.sql` so the Sentinel can read
`cvm_ingest_log` and `fnet_document`; without it the Sentinel runs on the
public API only.

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
   **Answered 2026-09-26: yes.** `docs/security/sentinel_readonly_role.sql` plus
   `default_transaction_read_only = on`; the owner runs it by hand. Role not yet
   present (checked `pg_roles` 2026-09-26).

### Wave 2

| #   | Item                                                                                                                                                                                                                                                           | Needs              |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------ |
| 2a  | `api.screen_restatements`: funds and months with restated filings, by `modalidade`                                                                                                                                                                             | 1b                 |
| 2b  | Filing punctuality and silent funds, from FNET delivery timestamps                                                                                                                                                                                             | 1b                 |
| 2c  | B4, field-level restatement diffs (`fnet_document_diff`): designed in [DOCUMENTS.md](DOCUMENTS.md), §11 decided 2026-09-26 (slice 1: FIDC mensal, 2026 backfill); built: ingest (migration 46, `fnet_diff`) and serving (`fund_restatement_diff`, catalog v40) | 1b                 |
| 2d  | FII keys carry `versao`                                                                                                                                                                                                                                        | gate 1, yes to (2) |
| 2e  | ~~`fidc_*` caps raise instead of trimming~~ (dropped: gate 1 answered no)                                                                                                                                                                                                                        | gate 1, yes to (1) |
| 2f  | B4 backfill of 2025 and earlier: restatement diffs for older years, newest-first, one year per dispatch; depth and runner-time budget set from the 2026 run's runtime and FNET latency (DOCUMENTS.md §11, decision 6)                                          | 2c's 2026 run      |

### Wave 3

| #   | Item                                                                                                      |
| --- | --------------------------------------------------------------------------------------------------------- |
| 3a  | B2, the read-only MCP over schema `api`: **deployed 2026-09-25** (49 tools)                               |
| 3b  | B3 remainder: `company_events`, `macro_series`, `ptax`; CRI/CRA last, because it needs a third kind of id |
| 3c  | B5, Sheets and Excel recipes: `api-docs/spreadsheets.mdx`, shipped with 1d                                |

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
  next analytics apply and a `deploy_mcp.yml` run. Still open: the futures arm
  of `api.panel` (`id_type='future'`, phase B). Owner decision: whether
  2021-01-04's DI1 may come from that day's earlier, well-formed versions of
  the Price Report. Owner-only, only if VIX itself is wanted: a signed Cboe
  licence (permissions@cboe.com) before setting the `CBOE_VIX_LICENSED`
  repository variable. Until then the risk regime is the OFR Financial Stress
  Index (`docs/research/dustin_br_data_sources.md` §3.C).
- **B9.** Alerts, only on signals from waves 1 and 2 once they exist.
- **B10.** Document text (Stage 3), priority categories only.
- **B11.** Per-event adjusted prices, where verified.

## 15. Portfolio diagnosis: decisions still open (2026-09-26)

**Paused 2026-09-28 (owner):** the active map is #371, and this map's tickets
are labelled `P2-later`.

Design: `PORTFOLIO_DIAGNOSIS.md`. Tickets: map #340 (#341–#345).

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

## 16. Two B3 matviews have no refresh path (found 2026-09-29)

**Reported 2026-09-30, not prioritized.** Found while tracing the system for
`docs/architecture/`. Nothing here is fixed or started.

`mv_b3_isin_subtype` and `mv_b3_monthly_activity` are created in `schema.sql`
(migrations 27 and 30) `WITH NO DATA`, and the `REFRESH` beside each one runs
only while the matview is unpopulated. Their daily refresh is two pg_cron jobs
in `08_cron_schedules.sql`, at 03:12 and 03:18 UTC-3 (06:12 and 06:18 UTC). The
live database has no `pg_cron` extension (`pg_extension`, checked 2026-09-29),
so that file only raises a NOTICE, and `apply_analytical.sh` does not rebuild
these two. Neither has changed since it was first populated around 2026-08-28.

Measured 2026-09-29:

| Observation                                  | Result                                                                                       |
| -------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `mv_b3_isin_subtype` rows                    | 897, the count `archive/STATUS_2026-08-28_day.md` recorded                                    |
| Fund-quota ISINs traded in the last 60 days  | 627, of which **9** are not in the matview                                                   |
| `mv_b3_monthly_activity`, newest period      | 2026-08-01; September is absent                                                              |
| August, standard lot (`tpmerc = '010'`)      | **19** sessions and R$ 481.0 bn in the matview; **21** sessions and R$ 529.8 bn in `b3_cotahist` |

What reads them:

- `mv_b3_monthly_activity`: `/markets` (`b3_monthly_volume`, `b3_market_overview`,
  `b3_asset_class_volume`, `b3_options_activity`), `/etf` (`etf_market_series`)
  and `/flows` (`flow_adtv_monthly`, `flow_headline`). Those pages show a
  partial August as a full month.
- `mv_b3_isin_subtype`: `vw_b3_instrument_typed.instrument_subtype`, served as
  `fund_type` by `api.fund_quotas`, for a fund quota whose board code is not
  decisive.

No check covers it. DB Health's matview-lag check reads `fact_fund_monthly`
only, and `docs/DATABASE_MAINTENANCE.md` still says the analytical re-create
"is the daily refresh", which is not true for these two.

Open: where the refresh should live (enable pg_cron, or a step of the daily
run). Not decided.
