# Dataset notes

What is true about each dataset, for agents. The rules are in the root
`AGENTS.md`; this file holds the detail that was too long to keep there. Claude
Code loads it through `CLAUDE.md`. Any other agent reads it before touching these
tables.

Storage layout: ~30 tables named `cvm_<entity>_<doctype>` or `bacen_<series>` (plus the
`cia_*` and ETF tables and the `cvm_ingest_log` audit table). Trust `src/store/schema.sql`,
`migrations/` and `src/pipeline/` (`CVMIngestor.daily_update` / `backfill`) as the source
of truth, not the README's CSV table.
Wired ingest datasets include `cvm_fidc_tranche`, `cvm_fidc_aging`, `cvm_fidc_cedente` /
`cvm_fidc_sacado` / `cvm_fidc_setor` / `cvm_fidc_scr` (FIDC informe tabs I, VIII, II, X —
named originators, anonymized top-25 debtors, sector, SCR ladder; migration 38, with
per-tab first months in `_FIDC_TAB_FIRST_PERIOD`; served by `api.fidc_cedentes` /
`fidc_sacados` / `fidc_portfolio` and the panel metrics `receivables`, `sacado_top1`,
`sacado_top25`), `cvm_fidc_garantia` (tab `X_7`, guarantees on the credit rights as a
value and a %, as filed — the denominator is undocumented, so never call it
"coverage"; migration 45, key `(cnpj, period)`, first month 2019-11), `cvm_securit_serie`,
`cvm_securit_fluxo`, `cvm_fi_balancete`, `cvm_cia_*`, `cvm_etf_registry`,
`cvm_fi_cda_acoes`, `cvm_fi_cda_cotas` and `cvm_fi_cda_debentures` (fund holdings —
CDA blocks 4, 2 and 6, members of the archive `cda` already downloads. Block 4
carries `cd_ativo`, the B3 ticker, so it is the join between the fund universe and
the quote tape; block 2 carries the held fund's CNPJ and CVM's published
`emissor_ligado` flag; block 6 carries `cpf_cnpj_emissor`, the debenture issuer's
own CNPJ, which joins to `cia_*` with no bridge. Block 6 has no `CD_ATIVO`, so its
key ends in `row_hash` after (fund, month, issuer, maturity) — see migration 35 for
the audit. Blocks 3, 5, 7 and 8 are not ingested),
`anbima_class_monthly` (every ANBIMA class/type; `anbima_etf_class_monthly`
survives as an ETF-only compat view), `etf_market_snapshot` (scraped ETF NAV/cotistas — wired
into the daily run but **gated on the `APIFY_TOKEN` secret**; it self-skips when the
token is unset. See `docs/reference/ETF_AND_PERFORMANCE.md`), and `b3_cotahist` (B3 COTAHIST
quotes; daily run fetches the last 7 calendar days, yearly backfill is opt-in.
Serve cash quotes from `vw_b3_quote_vista` (`tpmerc = '010'`), not the option-heavy parent),
and the **B3 BDI** group — `b3_lending_open_position`, `b3_lending_rate`,
`b3_investor_participation`, `b3_investor_participation_monthly`,
`b3_index_portfolio`, `b3_instrument_registry`, `b3_lending_trade` (securities lending
including the trade-by-trade tape with the brokerage on each leg, investor-type
flow, index free float and the cash instrument registry; `src/fetchers/b3_bdi_fetcher.py`
carries the verified endpoint contract).

**Fixed income ETFs are not in COTAHIST** (migration 57). B3 lists them in segment
FORWARD, market FIXED INCOME, which the COTAHIST files do not carry, so they have no
`b3_cotahist` row and no CODBDI. Their prints are `b3_trade_consolidated`, from B3's
TradeInformationConsolidatedFile (`src/fetchers/b3_trade_consolidated_fetcher.py`), keyed
on (ticker, session) and on B3's segment, not on `cvm_etf_registry`. The source has no
opening price, and its volume is not comparable with COTAHIST's. Only a file marked
`Final` is stored; an empty file (no session, or before B3's retention edge, 2025-06-10
when checked on 2026-09-30) is logged `skipped`.

**The FI balancete has a summary** (migration 59): `cvm_fi_balancete_resumo` holds one row per
fund and month with the COFI group totals, as filed. `vl_receitas` and `vl_despesas` accumulate
from each fund's own fiscal-year start, which is not January for every fund, so a month's flow is
this month minus last month except in the reset month; derive it, never store it. `vl_patrim_liq`
there excludes the open result: equity + revenue + expenses is the NAV. The 3xxx/9xxx codes are
memorandum accounts (equal on both sides), never assets. A group a fund did not file is NULL.

**FII filings keep every version** (migration 43): `versao` is part of the key of
`cvm_fii_mensal` and `cvm_fii_periodic` (`UNIQUE NULLS NOT DISTINCT`), so a restatement
lands beside the original instead of overwriting it. Read the current filing through
`vw_fii_mensal_latest` / `vw_fii_periodic_latest`, never by picking a version yourself.

**The FNET register** (`fnet_document`, `fnet_document_filter`; migration 42,
`src/fetchers/fnet_fetcher.py` → `src/pipeline/fnet_pipeline.py`, audit entity `fnet`) is
B3 Fundos.NET's document list: metadata only, one row per FNET id, and every version is a
new id with `versao` and `modalidade` (AP original, RE voluntary restatement, RC
CVM-required). It is the only public record of FIDC restatements — CVM's FIDC CSVs carry
no version. FNET rows carry **no CNPJ**: a document's fund is a `cnpjFundo` row in
`fnet_document_filter` (the CNPJ we queried with) or it is unknown — never inferred from
`fund_name`. The daily run crawls the last 3 delivery days (day windows; a month-wide
query times out) and sweeps a rotating 1/150 of the FII/FIDC registry (about 70 funds
a night; a fund search averages ~25 s, so 1/14 overran the 60-minute step); history is
`backfill.yml` with `fnet_start` / `fnet_end` (one year per dispatch) and `fnet_sweep`.
Served by `api.fund_documents` / `api.fund_restatements` (analytical file 24).

**Restatement diffs** (migration 46, backlog B4, `docs/planning/DOCUMENTS.md`) say what a
re-filed FIDC informe mensal changed. `src/pipeline/fnet_diff.py` downloads the body and
its predecessor, paired by `fund_restatements`' own group key, and stores
`fnet_document_body` (hashes and header, **no raw XML**), `fnet_document_pair` (one row
per restatement, with a status for every one it could not compare) and
`fnet_document_diff` (one row per differing leaf; `match_basis` path / key / position,
position rows flagged, never hidden). Its own `daily_ingest` job (audit `fnet` / `diff`,
capped per run, the rest stays queued); history is `backfill.yml` `fnet_diff` over
`fnet_start..fnet_end`. Served by `api.fund_restatement_diff` and `fund_restatements`'
`diff_status` / `n_fields_changed` (catalog v40, analytical file 24).

**Lineage.** `cvm_ingest_log` carries `git_sha` (from `GITHUB_SHA`, NULL when unset —
never guessed) and `parser_version` (`PARSER_VERSION` in `src/pipeline/ingest_log.py`;
bump it only when a parser or field map changes what a stored value means).
`api.coverage()` exposes `landed_git_sha`, the commit of the run that set `landed_at`.

The **analytical layer** (`src/store/analytical/`, applied by `scripts/apply_analytical.sh`
after ingest) is the read side the dashboards query: `dim_fund` (a **materialized view**,
rebuilt by the apply; the pg_cron jobs in `08_cron_schedules.sql` do not run, because the
live database has no pg_cron, checked 2026-09-29) plus `dim_fund_category` / `dim_administrator`
/ `dim_gestor`; the `fact_fund_monthly` / `fact_security_monthly` matviews; the
`fraud_screen_*` suspicious-deal screens (15; served to API callers only as the
`api.screen_*` wrappers in 23 — the public functions hold no client grant); and the `fund_performance_*` / `etf_*` ranking
functions (16–17). ETFs are carved out of the fund universe and ranked separately —
`etf_daily` is empty for post-CVM-175 share classes (see the ETF doc).
`mv_savings_flow_monthly` / `api.mv_savings_flow_monthly` (18) is reproduced as-found so
CASCADE recreates of `fact_fund_monthly` cannot destroy it; nothing in this repo reads it.
`mv_b3_isin_subtype` and `mv_b3_monthly_activity` are created in `schema.sql`, not here,
and `22_b3_tape_matviews.sql` refreshes them in the same apply.
Schema `api` is 19 (the contract, `catalog()` / `coverage()`, `api.assert_row_cap`),
20–21 (short interest, lending participants), 23 (screens) and 24 (FNET). The row cap
and what a new endpoint needs are in `AGENTS.md`, "Adding an API endpoint".
