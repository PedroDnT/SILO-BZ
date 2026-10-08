# Open items

Written 2026-09-18, closing the session that shipped catalog v28 and v29.
Everything here is **deliberately not done**, not forgotten. Nothing in this
list is broken in production — see "Known good" below.

This is the **single** register of open work. Items 7–11 were merged the same day
as a second list, in `README.md` of this directory, written by another session
that could not see this one; they are folded in here and that list is now a
pointer. Anything provisional or missing goes in this file.

## Known good as of 2026-10-06

| Surface              | State                                                                                                                                           |
| -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Data API (PostgREST) | catalog **v68** live (`api.catalog()` read 2026-10-06)                                                                                          |
| Docs site            | Scalar, from `scalar/` and `scalar.config.json`, synced from GitHub on merge (item 7); Mintlify is no longer the host                           |
| Dashboard            | `silo-bz-deloslabs.vercel.app` and `silo-bz.vercel.app`, both 200 on 2026-10-06                                                                 |
| MCP                  | `silo-mcp` Edge Function answers at its public URL (405 to a bare GET, as a POST-only endpoint should)                                          |
| Test suite           | 3850 passed, 20 skipped on `main` with `requirements-dev.txt` installed (the suite needs it; `requirements.txt` alone collects 23 errors, #680) |

The done items (1, 2, 4, 5, 6, 7, 8, 9, 12, 16) are in
[`docs/archive/OPEN_ITEMS_DONE.md`](../archive/OPEN_ITEMS_DONE.md); each keeps a
one-line pointer below so the numbering holds.

---

## 1. ~~`balance_sheets` and `cash_flow_statements` — the other two endpoints~~ (done)

Moved to [`docs/archive/OPEN_ITEMS_DONE.md`](../archive/OPEN_ITEMS_DONE.md) on 2026-10-06.

## 2. ~~`company_financials` and `income_statements` disagree on net income~~ (done)

Moved to [`docs/archive/OPEN_ITEMS_DONE.md`](../archive/OPEN_ITEMS_DONE.md) on 2026-10-06.

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

Moved to [`docs/archive/OPEN_ITEMS_DONE.md`](../archive/OPEN_ITEMS_DONE.md) on 2026-10-06.

## 5. ~~A `MAX()` over a filing date is not a period — check for more of these~~ (done)

Moved to [`docs/archive/OPEN_ITEMS_DONE.md`](../archive/OPEN_ITEMS_DONE.md) on 2026-10-06.

## 6. ~~Deploying the API is manual, and that is easy to forget~~ (done)

Moved to [`docs/archive/OPEN_ITEMS_DONE.md`](../archive/OPEN_ITEMS_DONE.md) on 2026-10-06.

## 7. ~~The docs site is on Mintlify's generated subdomain~~ (superseded)

Moved to [`docs/archive/OPEN_ITEMS_DONE.md`](../archive/OPEN_ITEMS_DONE.md) on 2026-10-06.

## 8. ~~Production deployments stopped taking the public hostnames~~ (done)

Moved to [`docs/archive/OPEN_ITEMS_DONE.md`](../archive/OPEN_ITEMS_DONE.md) on 2026-10-06.

## 9. ~~`coverage().landed_at` reads a day stale for the B3 lending group~~ (done)

Moved to [`docs/archive/OPEN_ITEMS_DONE.md`](../archive/OPEN_ITEMS_DONE.md) on 2026-10-06.

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

Moved to [`docs/archive/OPEN_ITEMS_DONE.md`](../archive/OPEN_ITEMS_DONE.md) on 2026-10-06.

## 13. B7 agent loop: Sentinel scheduled, Builder and Scout paused

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

**2026-10-06: the Sentinel is scheduled** (`trig_012S452r8KbfeRNkua8DVwzr`, daily
08:51 UTC, public mode). The owner chose to run only the Sentinel and to judge
it after about 2 weeks before the Builder and the Scout get routines. What the
setup showed:

- A routine made through the Claude Code MCP (`create_trigger`) has no
  repository and no GitHub access (403). Create it in claude.ai, Routines,
  with the repository attached. Remove the connectors it offers: the Sentinel
  is read-only.
- The routine's environment must allow `dados.cvm.gov.br`,
  `fnet.bmfbovespa.com.br` and the Supabase REST host in its network policy.
  The first test run got 403 from the proxy on all three.
- A raw TCP connection from the cloud sandbox to the Postgres pooler timed
  out (HTTPS worked), so the Sentinel's database mode is not usable there.
- First test with the network open: checks A (CVM headers) and C
  (`coverage()`) ran with no drift. Check B (FNET) did not finish: it needs
  about 15 paced day crawls, which is more than the foreground wait allowed.
  Open: make check B fit a run.

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

| #   | Item                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | Needs              |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------ |
| 2a  | ~~`api.screen_restatements`: funds and months with restated filings, by `modalidade`~~ done, catalog v37 (`25_api_filing_screens.sql`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | 1b                 |
| 2b  | ~~Filing punctuality and silent funds, from FNET delivery timestamps~~ done, catalog v37 (`screen_late_filers`, `screen_silent_filers`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | 1b                 |
| 2c  | B4, field-level restatement diffs (`fnet_document_diff`): designed in [DOCUMENTS.md](DOCUMENTS.md), §11 decided 2026-09-26 (slice 1: FIDC mensal, 2026 backfill); built: ingest (migration 46, `fnet_diff`) and serving (`fund_restatement_diff`, catalog v40)                                                                                                                                                                                                                                                                                                                                                         | 1b                 |
| 2d  | FII keys carry `versao`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | gate 1, yes to (2) |
| 2e  | ~~`fidc_*` caps raise instead of trimming~~ (dropped: gate 1 answered no)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | gate 1, yes to (1) |
| 2f  | B4 backfill of 2025 and earlier: restatement diffs for older years, newest-first, one year per dispatch; depth and runner-time budget set from the 2026 run's runtime and FNET latency (DOCUMENTS.md §11, decision 6). **2026 evidence (2026-10-05):** 16 `fnet`/`diff` runs, all ok, 6.8 min on average and 27.5 at most, 333,988 diff rows; of 20,056 `fnet_document_pair` rows 1,986 are `compared`, 17,976 `unpairable_no_link` (no `cnpjFundo` link yet; decision 4 has them wait for the sweep, now 1/150 of the FII/FIDC registry a night), 88 `unsupported_root`, 6 `declared_mismatch`. Depth is Pedro's call | 2c's 2026 run      |

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
validation remain. #609 was resolved by the owner on 2026-10-05; its data side
(branch `demo/equivalents-etf-peers`, catalog v66) adds ETF fee peers through the
class → index YAML (`src/portfolio/rules/equivalents/class_index.yaml`, every pair
`proposta` until the owner approves it) and `api.class_return_distribution`. The
engine copies the fund/ETF peer split and the report prints it (`demo/report-returns-tax`).
The owner approved the YAML's 11 pairs. The equivalente de mercado is wired in the engine (schema 1.13,
`equivalents`, `src/portfolio/market_equivalent.py`) and the report (branch `demo/equivalente-pct-cdi`), through
the new `api.portfolio_equivalents` (catalog v68). Open: the analytics-only apply and `deploy_mcp.yml` for
catalog v66 and v68, then live coverage. This does not complete #607 (brief).

Return block (#610, owner's resolution of 2026-10-05): implemented in the engine
only, schema 1.10 `returns` (`src/portfolio/returns.py`; keys in
[engine-output.md](../reference/portfolio/engine-output.md)); the report shows it,
and the tax block (#613, engine 1.11), since `demo/report-returns-tax`. "% do CDI" (engine 1.13, #606
addendum Q36) is computed only for a fund whose own filed benchmark (Extrato `PARAM_TAXA_PERFM` or lâmina
`INDICE_REFER`, served by `portfolio_fees` since catalog v68) is CDI or DI by the spelling list
`src/portfolio/rules/benchmark_cdi.yaml`. Remaining: fixed-income ETFs stay "não avaliado" until
`api.trade_consolidated_history` (catalog v65, #632) is deployed to the live MCP.
The per-asset performance attribution (owner, 2026-10-06) is the retroactive contribution of engine 1.15,
`returns.contribution`: back-cast from today's values, labelled, with the evaluated part's coverage and no portfolio
total.

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
- Cost cap US$1.00 per report; investigator cap 20 searches per report. The
  investigator is built (engine 1.12, #605, branch `demo/investigator`): inside
  the same US$1.00 cap (at most US$0.30 of it, LLM and Exa), 5 searches per item,
  180 s. It ships `on` since 2026-10-06 (`SILO_INVESTIGATOR` in `wrangler.jsonc`,
  owner's Q49, in place of a supervised run first). **Owner review:** the coordinator
  domains in `src/portfolio/rules/investigator/coordinators.yaml`: BTG (2026-10-05)
  and XP (2026-10-06) are `aprovada`; more can be proposed from
  `docs/reference/research/issue-document-sites.md`. Still open: the report's HTML section, `portfolio_instruments`
  serving the CRA/CRI ISIN (branch `demo/instruments-isin`), and a read path from
  R2 for the document cache.
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

Moved to [`docs/archive/OPEN_ITEMS_DONE.md`](../archive/OPEN_ITEMS_DONE.md) on 2026-10-06.

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
   version. Owner has not decided. Partly done 2026-10-07 (architecture
   review, `claude/arch-endpoint-manifest`): `serve/endpoint_manifest.py` reads
   each endpoint's kind, parameters, grant and paging off the SQL; the row-cap
   lists and counts in `serve/catalog.py` come from one declaration that
   `tests/test_endpoint_manifest.py` pins against it. The `postgrest` dict is
   still typed by hand (now checked against the manifest). Also 2026-10-07
   (`claude/arch-mcp-tools-manifest`): the MCP tool names are generated from the
   manifest into `contract.generated.ts`; `tools.ts` keeps only titles.
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

## 18. Brief and client constraints (#607, #614)

Implemented on `demo/brief-client-fit`: brief, expandable appendix, HTML upload delivery with browser PDF on request, optional declared client constraints and factual maturity/cash checks. Profile suitability remains not assessed. Deploy and live owner-portfolio validation pending. Contract: `docs/reference/portfolio/brief-client-fit.md`.

## 18. Debenture secondary-market capture (#662)

**Approved recovery validated; experiment still inconclusive (2026-10-08,
UTC-3).** PR #734 merged as `2c1ef8c38989820f5678bd4df193e420d24156ac`.
Following specific owner approvals, migration 74 and captures for 06/10 and
30/09–06/10 landed in production. Read-only recheck: both snapshots complete,
zero drops; the five-session capture contains 59,670 facts and 1,181 DEB codes.
COTAHIST 06/10 was recovered once: 17,453 rows, including 1,533 cash rows.
Do not repeat that recovery or run an annual backfill. Permanent credit capture
remains off under the approved rollout scope.

The [executable audit and experiment gates](../reference/research/debenture-equity-experiment.md)
now reproduce existing-data coverage and name candidates, including commercial
names: 804 unique CNPJ candidates, two ambiguous, 375 unmatched. Of the unique
candidates, 365 bond codes reach equities with positive cash closes in this
window, representing 82 candidate CNPJs. These are not verified issuance links.
The [read-only runner](../../research_examples/debenture_equity/README.md) never
loads data or certifies strict historical PIT from retrieval dates.

Offline experiment/preparation now implemented; twenty-six documented original-issuer
links are available (ALPA13, ALUP18, ANIM18, ASAI18, BSA318, BRKMA6, CAMLB1, CSED12,
ARML13, CSAN18, CCROA5, CTEE18, CGASA1, ENEV13, DXCO13, EGIE27, BRST15, DESK17, HYPEA8, IOCHA3, IRBR12, ITSA17, JHSF1A, MATD12, JALL13, MILSA0). The runner uses current total-return equity/IBOV exports, trailing
beta, past-liquidity equity selection, chronological purges and dependence checks.
Initial live run: four one-session outcomes, no primary five-session outcomes.
Owner approved all 13 recovery slices for 01/07–29/09. After an initial transport
failure, all 13 are now complete: 770,562 facts, zero drops, valid hashes, audits
`ok` and nine distinct metrics per source group. The execution-time peak credit
allocation increase was 400,982,016 bytes (later 386,850,816), below the 1 GB stop.
All 69 known study sessions are delivered;
no recovery windows remain. Expanded twenty-six-link offline run: 935 overlapping horizon rows from 22 issuers
(355/336/244 at 1/5/20 sessions; ENEV3/BRST3 lack trailing beta history, MATD12/MILSA0 only have excluded intragroup trades), all inconclusive; strict PIT still zero. FCA recorded
listing intervals are enforced and exact-date sector robustness is implemented;
available B3 sector history starts 16/09 and cannot cover training. The three-month pilot
cannot meet fixed training/validation/test floors despite completed recovery;
dated identity changes, longer protocol, sector coverage and power assessment remain.
The documentary candidate target is met, but the primary untouched test still has
18 issuers/15 dates, below its unchanged acceptance floors.

A [versioned prospective design candidate](../../research_examples/debenture_equity/prospective-design.md)
now specifies 90/50/100 reference sessions, cutoff and immutable label/input
requirements, a development-only power grid and the requirement-by-requirement
completion audit. It is unactivated. A local retention helper now verifies hashes, byte budgets and
actual-clock cutoffs without fetching or certifying PIT; collector/evaluator and
power assessment implementation, owner acceptance and future elapsed history remain.
The evaluator foundation now separates frozen features from coherent realized
label vintages, preserving class/ISIN, alpha/beta and prior pilot behavior.
Archive/input integration now reparses raw credit, validates availability and
calendar coverage, and selects complete company FCA filings without resurrecting
removed tickers. Independent completeness/source acceptance, prediction/label
availability and power assessment remain open.

The approved three-month recovery and its storage checks are complete. Open
acceptance, in order: broader documentary dated identity evidence (#660); a longer
frozen protocol and power assessment; deeper coverage/PIT, with a new storage
allowance and specific approval for any expanded production window; adjusted
returns/benchmark acceptance; confirmatory residual-return experiment. REUNE traded
rates/access and benchmark conventions (#661) remain separate dependencies under
ADR 0004. Neither #662 nor #628 is closed by this pilot recovery.

Historical [local capture/storage measurements](../reference/research/debenture-secondary-market-validation.md)
and [schema-lock recovery](../reference/research/ingest-recovery-2026-10-07.md)
remain timestamped evidence of their earlier state. The production approvals and
recoveries above supersede their then-pending rollout status.


## 19. COTAHIST preserved fields and code reference (#720)

Implemented on `codex/cotahist-complete-serving`, catalog v70: market 021 is block trading;
sourced supplemental interpretations accompany dated labels. The existing SQL
routes expose preserved market/board/term identity and contract fields; HTTP
history accepts additional raw fields explicitly. The catalog publishes dated
CODBDI/TPMERC/INDOPC references without inventing unknown descriptions.
Production analytical apply, MCP redeployment and live acceptance remain pending.
No new collection or source-vintage archive is part of this change.
[Audit and field map](../reference/research/cotahist-storage-serving-map.md).
