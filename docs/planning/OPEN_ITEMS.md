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

## 2. `company_financials` and `income_statements` disagree on net income

**Blocked 2026-09-25 on a decision:** option 1 (leave) vs option 2 (re-key on
the label, catalog bump). A product call, not a code fix.

Not a bug; a deliberate asymmetry, recorded so nobody "fixes" it by accident.

`company_financials.net_income` reads conta `3.11` alone and returns NULL for
the ~282 statements filed under the chart that has no `3.11`. That set is small
by row count (0.56%) but **large by substance — it includes Itaú Unibanco and
BTG Pactual**. `income_statements` resolves them, because it keys on the filed
label rather than the code.

Options, in preference order:

1. Leave it, and point callers at `income_statements` (current state; the
   `api-docs/known-limitations.mdx` note and the SDK docstring both do this).
2. Re-key `company_financials.net_income` on the label too, so both surfaces
   agree. Cheap, and arguably what a caller expects. Needs a catalog bump and a
   changelog row explaining that NULLs became numbers.

Do **not** reinstate a `COALESCE(3.11, 3.09)`: that is code-keyed and unsound —
`3.09` is `Resultado Líquido das Operações Continuadas` on the industrial chart,
a different quantity. `tests/test_company_financials_contract.py` asserts
`'3.09'` appears nowhere in that function.

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

## 5. A `MAX()` over a filing date is not a period — check for more of these

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

**Blocked 2026-09-25:** both remaining points need Pedro: the `VERCEL_TOKEN`
repository secret, and the Vercel audit log or support for the cause.

Two things remain open:

1. **`VERCEL_TOKEN` is not set**, so the guard can detect but not fix. Until
   Pedro adds it (Vercel → Account Settings → Tokens, scope team `deloslabs`,
   stored as the repository secret), a freeze produces a red run at 08:00 UTC
   instead of a silent four-day stall — better, but still manual to clear.
2. **The cause.** Find and undo whatever the 2026-09-17/18 alias attempts left
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

## 13. B7 agent loop: designed, smallest test pending

[AGENTS.md](AGENTS.md) is approved (2026-09-24) and nothing runs. Before any
routine is scheduled, one manual Builder run on FIDC informe `tab_X_7`
(AGENTS.md §5) has to show that its PR needs clearly less rework than writing
it by hand. Until then the prompt files under `.claude/agents/`, the
`agent-ok` / `agent:<name>` labels and the routines stay uncreated, and the
Sentinel's read-only database credential is Pedro's open call.

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
2. Put `versao` into the keys of `cvm_fii_mensal` and `cvm_fii_periodic`? This
   changes their grain, and it is what stops a restatement overwriting the
   original (`DATA_INVENTORY.md` §2, `COMPETITIVE_GAPS.md` B4).
3. Where to host the read-only MCP (B2)? A new runtime; a Vercel function is
   the obvious candidate.
4. A read-only database role for the Sentinel agent ([AGENTS.md](AGENTS.md),
   item 13)?

### Wave 2

| #   | Item                                                                                                            | Needs              |
| --- | --------------------------------------------------------------------------------------------------------------- | ------------------ |
| 2a  | `api.screen_restatements`: funds and months with restated filings, by `modalidade`                              | 1b                 |
| 2b  | Filing punctuality and silent funds, from FNET delivery timestamps                                              | 1b                 |
| 2c  | B4, field-level restatement diffs (`fnet_document_diff`): fetch the XML of each multi-version group and diff it | 1b                 |
| 2d  | FII keys carry `versao`                                                                                         | gate 1, yes to (2) |
| 2e  | `fidc_*` caps raise instead of trimming                                                                         | gate 1, yes to (1) |

### Wave 3

| #   | Item                                                                                                      |
| --- | --------------------------------------------------------------------------------------------------------- |
| 3a  | B2, the read-only MCP over schema `api` (needs gate 1, question 3)                                        |
| 3b  | B3 remainder: `company_events`, `macro_series`, `ptax`; CRI/CRA last, because it needs a third kind of id |
| 3c  | B5, Sheets and Excel recipes: `api-docs/spreadsheets.mdx`, shipped with 1d                                |

### Wave 4: later, in order

- **B7.** One manual Builder run on FIDC `tab_X_7` (item 13), then Scout and
  Sentinel only if it passes.
- **B8.** DI curve and futures (`INSTRUMENTS.md` Phases B and C).
- **B9.** Alerts, only on signals from waves 1 and 2 once they exist.
- **B10.** Document text (Stage 3), priority categories only.
- **B11.** Per-event adjusted prices, where verified.
