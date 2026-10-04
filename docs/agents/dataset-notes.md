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
`cvm_securit_fluxo`, `cvm_fi_balancete_resumo` (the FI balancete; the account-level
`cvm_fi_balancete` is retired and empty, migration 62), `cvm_cia_*`, `cvm_etf_registry`,
`cvm_fi_cda_acoes`, `cvm_fi_cda_cotas` and `cvm_fi_cda_debentures` (fund holdings —
CDA blocks 4, 2 and 6, members of the archive `cda` already downloads. Block 4
carries `cd_ativo`, the B3 ticker, so it is the join between the fund universe and
the quote tape; block 2 carries the held fund's CNPJ and CVM's published
`emissor_ligado` flag. Block 6 is CVM's private-credit block (debentures, private credit
and agribusiness titles), and it carries `cpf_cnpj_emissor`, the issuer's own CNPJ, which
joins to `cia_*` with no bridge. It is not where most fund debentures are: block 4 files them
under `tp_aplic = 'Debêntures'` (R$788.9bn on 2026-05, against R$34.4bn in block 6), keyed by
`cd_ativo` and the ISIN, with no issuer CNPJ. Block 6 has no `CD_ATIVO`, so its
key ends in `row_hash` after (fund, month, issuer, maturity) — see migration 35 for
the audit. A monthly CDA read replaces, per fund in the file, that fund's rows of the month
in all four blocks (`pg_client.replace_scoped_rows`, count in `cvm_ingest_log.rows_deleted`),
so a re-filed block-6 row does not land beside the old one; a fund missing from the file keeps
its rows, and a yearly HIST read only upserts. Blocks 3, 5, 7 and 8 are not ingested; the filing fund's name, DENOM_SOCIAL, is
`cvm_fi_cda_fund_name`, once per fund and month, not in each row's `raw`, migration 60),
`anbima_class_monthly` (every ANBIMA class/type; `anbima_etf_class_monthly`
survives as an ETF-only compat view), `etf_market_snapshot` (scraped ETF NAV/cotistas — wired
into the daily run but **gated on the `APIFY_TOKEN` secret**; it self-skips when the
token is unset. See `docs/reference/ETF_AND_PERFORMANCE.md`. Its `taxa_adm_pct` is the only ETF fee SILO holds:
CVM's Extrato, lâmina and cad_fi have none for the 178 active ETFs, checked 2026-10-03. `api.portfolio_fees` serves
it as `etf_site_*`, a third-party value, never as a disclosed fee, catalog v56; its `cotistas` and `nav` (R$, the
site's R$ MM x 1e6) are likewise the only cotistas and PL for a registry ETF, no 2026 `cvm_fi_diario` row, served from
the fee's row as `etf_site_nr_cotistas` / `etf_site_pl`, catalog v57, never summed), and `b3_cotahist` (B3 COTAHIST
quotes; daily run fetches the last 7 calendar days, yearly backfill is opt-in.
Serve cash quotes from `vw_b3_quote_vista` (`tpmerc = '010'`), not the option-heavy parent),
and the **B3 BDI** group — `b3_lending_open_position`, `b3_lending_rate`,
`b3_investor_participation`, `b3_investor_participation_monthly`,
`b3_index_portfolio`, `b3_instrument_registry`, `b3_lending_trade` (securities lending
including the trade-by-trade tape with the brokerage on each leg, investor-type
flow, index free float and the cash instrument registry; `src/fetchers/b3_bdi_fetcher.py`
carries the verified endpoint contract).

**Index levels** (`b3_index_level`, migration 55; `src/fetchers/b3_index_fetcher.py` →
`ingest_b3_index.py`, audit `b3` / `index_levels`) hold B3's published daily level for nine
indices: IBOV (1968), IBXX, IBXL, SMLL, IDIV, UTIL, ICON, IMOB, IFIX. They are levels as
published and not adjusted, and B3 labels each a total-return index (Manual, Feb 2023,
section 1.2), so compare them with `close_total_return`, never `close_adj`. `divisor_step` marks a
re-scaling session (IBOV has eleven); the ingest refuses any other one-session move beyond a
factor of two. `run_b3_events` refetches every year of every code each night, so a new code is
backfilled by the next run and there is no backfill mode. A null `results` is retried, and a
persistent one raises. IEEX is held back (an unexplained 1999-03 move). Served by
`api.index_history`, index codes only; IBOV11 and BOVA11 are not the index.

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
this month minus last month except in the reset month; derive it, never store it.
`vl_patrimonio_sem_resultado` (group 6) excludes the open result: it + revenue + expenses is the
NAV, so never compare it alone with `cvm_fi_diario.vl_patrim_liq`. The 3xxx/9xxx codes are
memorandum accounts (equal on both sides), never assets. A group a fund did not file is NULL.
The fee columns (`vl_taxa_administracao` and its parts, `vl_taxa_performance`, ...) are COFI
8.1.7 accounts, accumulated and negative like group 8. Many funds file the whole administration
fee in 81781001/81781056 and nothing in the management (`vl_taxa_gestao`) or distribution
split, so a NULL part is not a zero fee.

**The CVM 175 levels** (migration 67, #543): `cvm_registro_fundo`, `cvm_registro_classe` and
`cvm_registro_subclasse` are the three members of `registro_fundo_classe.zip`, one table each,
keyed on CVM's own ids (TEXT, as filed). Walk class → fund by `cvm_registro_classe.id_registro_fundo`
and subclass → class by `id_registro_classe`, never by CNPJ. `cvm_fund_registry` cannot do it: a
class that reuses its fund's CNPJ lands on the fund's `(cnpj, entity_type)` row and replaces its
`raw` (132 of 36,770 class rows found their fund there on 2026-10-03). A subclass has no CNPJ
(the file publishes none) and none is stamped on it; `id_subclasse` is the `ID_SUBCLASSE` of the
informe diário, lâmina and CDA. `classe_cotas` is `Classe_Cotas` S/N as TRUE/FALSE (NULL outside
FIF classes; another value fails the slice). Each member is one `cvm_ingest_log` row
(`fi` / `registro_*`).

**The disclosed fee in the registry** (migration 64): `cvm_fund_registry.taxa_adm`,
`taxa_perfm`, `inf_taxa_adm`, `inf_taxa_perfm`, `dt_ini_exerc`, `dt_fim_exerc` are
`cad_fi.csv`'s columns as filed; CVM's meta states no unit (values read as percent). Only
the legacy file publishes them, so they cover legacy funds: 7 of the 25,178 funds reporting
NAV on 2026-09-15 carry one. A NULL fee is "not filed there", never a zero fee.

**The lâmina** (`cvm_fi_lamina`, migration 65, audit `fi` / `lamina`) is the summary sheet each
fund files: `taxa_adm` (+ min/max/obs), `taxa_perfm` (TEXT in the source, never parsed), entry and exit
fees, `pr_pl_despesa`, minimums and the redemption terms (`qt_dia_conversao_cota_resgate`,
`qt_dia_pagto_resgate` + `tp_dia_pagto_resgate`). Only the main member of `lamina_fi_YYYYMM.zip` is read.
Key `(cnpj, dt_comptc, id_subclasse)`, `id_subclasse` NULL on almost every row (`NULLS NOT DISTINCT`).
Each month's file holds the lâminas filed that month, so read the current one through
`vw_fi_lamina_latest` (newest `dt_comptc` per fund and subclass, with `age_months`). Fees are as filed,
unit not stated by CVM; a NULL fee is "not filed", never zero. Not every active fund has a row.

**The Extrato das Informacoes** (`cvm_fi_extrato`, migration 66, audit `fi` / `extrato` for the current
file and `fi` / `extrato_ano` for a year) is the terms-and-fees sheet each fund or class files, and the
primary disclosed-fee source (owner decision, issue #515; measured in #524: a `TAXA_ADM` for 84.3% of the
26,046 active FI funds, against 15.9% for the lâmina). Two plain CSVs, latin-1, `;`, 117 columns:
`extrato_fi.csv` is the current file, one row per fund or class CNPJ (38,796 rows, refreshed daily, read by
the daily run), and `extrato_fi_YYYY.csv` holds every version filed that year (several rows per CNPJ,
refreshed weekly; `backfill.yml` `fi_doc_type=extrato` reads 2021 onward, and only the job that reaches the
current year also reads the current file; a month repair is refused). Key `(cnpj, dt_comptc)`; whether the
pair repeats inside a yearly file was not measured, so the ingest keeps the last row and logs the count.
Read the current version through `vw_fi_extrato_latest` (newest `dt_comptc` per CNPJ, with `age_days`).
`taxa_adm` is stored exactly as filed, and the unit is not stated by CVM (percent a year, by CVM's XML
standard and the balancete estimate): 16.7% of the values are exactly 0 and 115 are above 5 (maximum
14,638.38). Neither is rewritten in the table. `api.portfolio_fees` reads a 0 as "not informed"
(`filed_zero`) and withholds a value above 5 (`implausible_filed`, the value in `taxa_adm_filed_raw`); when
such an Extrato is older than a lâmina with a single fee in (0, 5], the newer lâmina is the source
(`fee_resolution = 'lamina_newer'`, catalog v55, #552), and either way the other document's fee is returned
beside it as filed, never rescaled. There
is no subclass column: a CVM 175 row is the class. `taxa_perfm` is numeric here (text in the lâmina), with
`param_taxa_perfm`, `calc_taxa_perfm` and `inf_taxa_perfm`; `taxa_saida_pagto_resgate` is an S/N flag, not a
rate. The 70 `PR_*_MIN` / `PR_*_MAX` exposure limits stay in `raw`. `DT_COMPTC` is the date of the filed
version, not how old the information is (median 597 days, and older rows agree with the balancete estimate
better than recent ones). 4,084 active funds (5.9% of PL) never filed one.

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
rebuilt by the apply; the pg*cron jobs in `08_cron_schedules.sql` do not run, because the
live database has no pg_cron, checked 2026-09-29) plus `dim_fund_category` / `dim_administrator`
/ `dim_gestor`; the `fact_fund_monthly` / `fact_security_monthly` matviews; the
`fraud_screen*_`suspicious-deal screens (15; served to API callers only as the`api.screen\__`wrappers in 23 — the public functions hold no client grant); and the`fund*performance*_`/`etf\__`ranking
functions (16–17). ETFs are carved out of the fund universe and ranked separately —`etf_daily`is empty for post-CVM-175 share classes (see the ETF doc).`mv_savings_flow_monthly`/`api.mv_savings_flow_monthly`(18) is reproduced as-found so
CASCADE recreates of`fact_fund_monthly`cannot destroy it; nothing in this repo reads it.`mv_fund_holdings_monthly`(30) is what funds hold per month from CDA blocks 4 and 2: stocks
by ticker, debentures by the issuer code in the ISIN (block 4 carries the debentures funds hold,
R$789bn on 2026-05 against R$34bn in block 6), and fund-quota totals with the same-group part.`mv_b3_isin_subtype`and`mv_b3_monthly_activity`are created in`schema.sql`, not here,
and `22_b3_tape_matviews.sql`refreshes them in the same apply.
Schema`api`is 19 (the contract,`catalog()`/`coverage()`, `api.assert_row_cap`),
20–21 (short interest, lending participants), 23 (screens) and 24 (FNET). The row cap
and what a new endpoint needs are in `AGENTS.md`, "Adding an API endpoint".
