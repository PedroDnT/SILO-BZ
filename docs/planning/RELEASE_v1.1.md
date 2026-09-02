<!--
This file is the annotation for the v1.1 tag. It lives in the repo because the
tag could not be pushed from the session that wrote it: that session's git
credential is scoped to branch refs, so `git push origin refs/tags/v1.1`
returned HTTP 403 while branch pushes to the same remote succeeded.

To create the tag from a checkout that can push tags:

    git fetch origin
    git tag -a v1.1 -F docs/planning/RELEASE_v1.1.md 75e536d3e1bbbe5a40dacb487c5dc9d19062cefe
    git push origin v1.1

75e536d is the merge of #190, and the commit every reading below was measured
against (DB Health run 33666952637, 2026-09-02T18:24Z, HEALTH: PASS).
-->

# v1.1 — the data-loss release

First tagged release. The theme is not new features: it is **finding data the
pipeline was silently discarding, and detection so the next one cannot hide.**

## Five silent data-loss bugs

All the same class — a unique key documented as intentional while
`ON CONFLICT DO UPDATE` discarded the rest. It keeps the last-written row; it
does not aggregate.

| #   | Where                     | Loss                                                                                                                                     | Fix                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| --- | ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | Historical CDA, 2005–2022 | 11 of 12 months per year                                                                                                                 | `ingest_fi_hist_cda` passed `month=1` for a yearly archive holding twelve competency months. `month=None` derives each row's period from its own `DT_COMPTC`; backfilled.                                                                                                                                                                                                                                                                                                |
| 2   | `cvm_fip_periodic`        | 72–77% of filings, measured on the real 2015/2022/2025 files                                                                             | Keyed on `period_year` while `DT_COMPTC` sat unread in `raw`. New key `(cnpj, doc_type, period, classe_cota, row_hash)`, migration 34.                                                                                                                                                                                                                                                                                                                                   |
| 3   | CDA holdings keys         | 395 collisions in 2005 alone                                                                                                             | Widened with `tp_fundo` / `tp_negoc`, migration 33.                                                                                                                                                                                                                                                                                                                                                                                                                      |
| 4   | `cvm_fi_cda` BLC_1        | **80.4%** — 257 government bonds collapse onto one row (R$261.6M true vs R$39.3M stored)                                                 | **Not fixed, deliberately.** The fix is an additive `cvm_fi_cda_titpub` keyed on the security (~98.8% retention), never a rekey of `cvm_fi_cda`, which would change its grain and break every consumer. Written up in `docs/DATA_INVENTORY.md` §2 for the owner's call.                                                                                                                                                                                                  |
| 5   | `cia_event` (IPE)         | **100% of 2010–2014 and 12% of 2015** — CVM assigned no protocol number to IPE filings before 2015, and the key is `(protocolo, versao)` | **Not fixed, deliberately.** Found 2026-09-02 by the "fetched N, upserted 0" contract on its first live outing, then measured on the real files: header identical to today's, `Protocolo_Entrega`/`Versao` empty in 26,880/26,880 rows of 2012 and 3,615/30,175 of 2015. A key is never synthesized; the fix is a `row_hash` era for protocol-less filings (the debentures pattern), which changes the table's grain — the owner's call, in `docs/DATA_INVENTORY.md` §2. |

## Two silent _failures_ — real errors reporting green

- **The schema gate had been down since 2026-08-31**, taking the 06:00 daily
  ingest and every backfill with it. The first diagnosis was wrong: psql reports
  a statement's error at its LAST line, so `duplicate key ... uq_fi_cda_cotas` at
  line 113 was the repair `UPDATE`, not the `CREATE UNIQUE INDEX`. The real
  defect was migration 33's block-2 repair assigning both key columns whenever
  either was null, reading `TP_NEGOC` out of a `raw` that `upsert_rows` strips
  once a typed column of that name exists — writing NULL over a value CVM had
  filed. No data was lost, because the error is what prevented the write.
- **`fact_fund_monthly` had not refreshed since 2026-08-30** and every run said
  green. Three things hid it: the workflow step was `continue-on-error`; the
  health check that claimed to catch a broken analytical apply read only
  `api.catalog()` / `api.coverage()`; and the file is one transaction, so the
  `DROP ... CASCADE` rolled back with the failed build and left the matview
  present, queryable and **frozen** — the exact shape every existence check
  passes.

## New data

- **`cvm_fi_cda_debentures`** (CDA block 6, migration 35) — the
  fund→corporate-credit edge. Keyed `(fund, month, issuer, maturity, …, row_hash)`
  after an audit on both file eras showed a natural key alone loses 15.8%.
  253,563 source rows → 253,563 stored, verified end to end.
- Holdings history filled: `cda_cotas` 2010–2016, `cda_acoes` 2025–2026,
  `fip` 2010–2026, `cda_debentures` 2005–2026, `fidc` 2019–2024.
- Repairs found by the health gate going red and the table-reading gap scan,
  not by the audit log: `cda_acoes` 2026-01..04 (1,282,397 rows that a
  refused-connection backfill had left missing) and `cda_cotas` 2017–2020
  re-run through the yearly HIST path (2017: 833,967 · 2018: 997,928 ·
  2020: 1,560,712 rows processed; 2019 re-run after a runner network fault).

## New serving

- **`api.fund_holdings`** (catalog **v17**) answers both directions — what a
  fund holds, and which funds hold a ticker — returning rows as filed and never
  summing across application types.
- `api.option_exercises` is tier-capped (500 / 5000) instead of a `LIMIT 5001`
  sentinel no caller could observe past PostgREST's 1000-row cap.

## API / SDK correctness

- Three SDK methods sent parameter names the SQL functions do not declare
  (`p_underlying` vs `p_prefix`; `p_codneg` vs `p_ticker`, twice) and could only
  ever 404. `tests/test_sdk_rpc_params_match_sql.py` now joins the two sides by AST.
- silo-client **0.2.0**: truncation detection via `Content-Range`, `SiloTimeout`,
  bearer-token tier.
- `serve/` returns JSON on every error path.

## close_adj: still `adjusted=false`, and no factor guessed

Diagnostic 11 proved the inputs exist (1,382 share-count events, 705 with both
sides of the tape), and migration 36's `(isin, trade_date)` index makes the
verification query answerable at all — it had been silently skipped on every
health run for exceeding 90 s. B3's factor convention differs by label and has
not verified cleanly, so nothing is adjusted. **A guessed adjustment factor is
worse than no adjustment**, and this release does not ship one.

## Detection, so none of it can hide again

- `tests/test_schema_upgrade_path.py` — static assertions that every indexed
  column is reachable from `schema.sql` alone on an **existing** database (both
  fresh-database verifications passed; that is precisely why they missed it),
  plus that migration 33's repair can never overwrite a filed value.
- CI grew an upgrade-path fixture that rewinds a seeded database and replays the
  current schema.
- The analytical apply step no longer swallows failures (`continue-on-error`
  removed) — daily runs now go red on an analytical failure.
- Health **check 4b**: `fact_fund_monthly` must not trail
  `latest_complete_period('fi')` by more than 31 days. It would have gone red on
  2026-08-31.
- CI seeds the FIP collision shape before the analytical apply and asserts the
  fact table's FIP branch does not double-count.
- **Health check 4b no longer calls a fresh matview "missing" for being ahead**
  (#190). `fact_fund_monthly` aggregates `cvm_fi_diario` through the *current*
  month while `latest_complete_period('fi')` counts only *complete* months, so a
  freshly rebuilt fact table is always one calendar month ahead — and the guard
  was `[ "$lag" -ge 0 ]`. Run 33666142198 reported "missing, unpopulated, or
  empty" about a matview rebuilt 44 minutes earlier that answered −31. The check
  had read 0 an hour before only because the matview had not been rebuilt since
  2026-08-30: the staleness it exists to catch was concealing its own false
  alarm. Numeric-ness is now tested apart from range; `> 31` stale, `< -31`
  future-dated `DT_COMPTC`, else healthy. Nine tests execute the branch under
  bash rather than reading its text, because the defect was in shell control
  flow.
- **A backfill that lands nothing because the source has nothing now exits 0**
  (#189). Confirming #184 against the live 2005 archive exposed the same defect
  one layer up: the fetcher correctly refused, `_classify_finish` correctly said
  `skipped`, and then `run_backfill`'s zero-row guard failed the job with "every
  fetch likely failed; check network/CVM availability" — false in every clause.
  The guard now tells three zeros apart: every slice skipped (log them, exit 0),
  slices failed (stay quiet, `ensure_no_failed_slices` names them), and the
  unexplained zero it was built for, which stays fatal. The skip ledger is
  recorded in `_log_finish` beside `_record_failure` so it cannot drift from
  the audit table.
- Health **check 1** now fails only on slices the daily run would retry —
  undated, current-year yearly, and monthly periods inside
  `CVM_DAILY_LOOKBACK_MONTHS` (#174). `daily_update` never probes 2005, so a
  26-hour alarm on a 2005 slice was a red light only a backfill could clear,
  and the watchdog's remedy — re-run daily — is a no-op for it. **Diagnostic 15**
  (#187) is the other half: the backlog check 1 no longer fails on is now
  *visible* rather than merely non-fatal, split into what the gate sees and
  what it excludes, with a reconciliation of its own 26h counts. Three tests
  hold the diagnostic's restated predicate to the workflow's, so the two
  cannot drift into disagreeing about what "the daily window" means.

## Docs

- **`docs/DATA_INVENTORY.md`** — what we ingest, what we could ingest and don't,
  what we ingest and don't serve, and the serving grain per family.
- README table/page counts corrected, api-docs conventions overhauled against the
  deployed PostgREST rather than the local adapter.

## Disk: what was reclaimable, measured before anything was dropped

`docs/DATABASE_MAINTENANCE.md` §9 forbids dropping landing tables and
`VACUUM FULL` on balancete from CI. Health diagnostic 14 measured the one
sanctioned reclaim (never-used indexes) instead of guessing at it:

- Statistics never reset, so every `idx_scan = 0` is real. TOAST is 8 KB on
  every large table — `raw` is inline, there is no JSONB lever. Zero
  structurally redundant indexes.
- **Migration 37** drops `cvm_fi_cda_acoes_pkey` — 517 MB, never scanned,
  surrogate `id` referenced nowhere. The cotas twin stays: 30 scans, and the
  reader is the `$cotas_dedup$` guard that a test pins. **That is the entire
  sanctioned reclaim: ~0.5 GB.**
- The real finding is what _generates_ the disk: `cia_account_2019…2022` at
  **55–78 updates per insert**, `cvm_fi_perfil` at 31 — whole yearly files
  re-upserted daily, unchanged, by an unconditional `DO UPDATE`. `upsert_rows`
  now guards the update with `WHERE (cols) IS DISTINCT FROM (EXCLUDED.cols)`.
  It returns no bytes; it stops the daily rewrite that was eating them.
  `cvm_fi_balancete` sits at 8.1% dead (15M tuples) with its last autovacuum
  on Aug 27 — the default 20% threshold on 172M rows will not fire until 34M.

## Operational notes for this release

- The backfill's schema apply had crept to 14m25s against a 15-minute job
  limit. A run whose apply **succeeded** with one second to spare was marked
  `cancelled` at teardown, `needs:` failed, and all 22 FI year jobs were
  skipped — a slow success turned into a silent no-op. Now 25 minutes. The
  trend is not finished: the same apply took **16m48s** on 2026-09-02. It is
  O(holdings size) — migration 33's repair UPDATEs and the `$cotas_dedup$`
  guard full-scan 12 GB + 6.5 GB on every apply — so the new limit buys
  months, not years. Filed, not fixed.

- **The ETF scrape no longer needs a Console permission grant** (#186).
  `apify/web-scraper` was upgraded to full permissions on 2026-08-31 and
  started returning HTTP 403 `full-permission-actor-not-approved`, which took
  the 06:00 daily's analytical refresh down with it. The default actor is now
  `apify/playwright-scraper` (limited permissions), the shared `pageFunction`
  polls `page.evaluate` instead of `waitForFunction` — whose options argument
  sits in a different slot on Puppeteer and Playwright — and the 403 is raised
  as `ApifyActorNotApprovedError` and skipped like an unset token, because the
  scrape never started. Unproven against the live site: only a `mode=daily`
  run exercises the new actor.

- The Supabase **session pooler drops a quiet client** during a long
  `CREATE MATERIALIZED VIEW` while the backend holds `AccessExclusiveLock` from
  `DROP ... CASCADE`. `apply_analytical.sh` now sends the same TCP keepalives as
  `pg_client.py`, and the FI branch is a single scan of `cvm_fi_diario`.
- Database at **105.61 GB of the 135 GB** plan allowance (78%) as measured by
  the health run on 2026-09-02T17:18Z, which passed every check: 0 unhealed
  ingest errors in the daily window, all monthly families complete inside the
  75-day bound, `api.catalog()` at **v17** with 9 coverage rows,
  `fact_fund_monthly` **0 days** behind ingested fi completeness, and all four
  landing tables still closed to the anon key. Offline suite: **906 passed**.
