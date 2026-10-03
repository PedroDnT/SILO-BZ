# Portfolio diagnosis demo, phase 0: what SILO has, what is missing, what Sunday can hold

Phase 0 of the portfolio-diagnosis demo (design: `docs/planning/PORTFOLIO_DIAGNOSIS.md`;
original map #340). Read-only research done on 2026-10-02 from 19:00 UTC-3 (22:00 UTC) to
2026-10-03 about 01:30 UTC-3 (04:30 UTC), on commit `cc3ab2a` (the merge of #504). No code, no
migration, no DDL, no write to the database. Every claim below carries its
evidence (`path:lines`, a ticket, a SQL result, a URL with its access date) or
is marked **not measured**. For most of the session the cloud sandbox could not
reach Supabase, dados.cvm.gov.br, FNET or tesourotransparente.gov.br (the egress
proxy refused every CONNECT). After 00:05 UTC-3 on 2026-10-03 (03:05 UTC) the
Supabase MCP connected and the measurements in §4 ran as read-only SELECTs
against production, with the bounds of `scripts/health_diagnostics/19_portfolio_phase0.sql`
(§12). A third-party fetch service (Firecrawl) read four public pages the proxy
had refused: CVM's CDA and lâmina dataset pages, `meta_cad_fi.txt`, and the
Tesouro Direto dataset page with its metadata PDF. Those reads are dated
2026-10-03 (UTC-3) below. Times follow the owner's rule: UTC-3 first, UTC in
parentheses.

## Answer

1. **The engine starts from zero set-based functions, not from zero data.** None
   of the three `api` functions the design calls for (look-through recursion,
   set issuer resolution, monthly returns) exists
   (`docs/planning/PORTFOLIO_DIAGNOSIS.md:44`; map #340 and tickets #341–#345
   were closed as not planned on 2026-09-30). But the warehouse already holds
   the data for 9 of the 14 blocks and serves one-fund primitives for 6 of them
   (§2). What is missing is the set-based layer, the fee reader over
   `cvm_fi_balancete_resumo`, a CNPJ filter on the screens, and a price series
   for Tesouro.
2. **The measurements ran (§4), and three of them change the Sunday build.**
   The disclosed fee is not in SILO (`TAXA_ADM` is NULL in every registry row
   checked), so block 3 ships as an estimate from the balancete alone until the
   lâmina or `cad_fi` is ingested. A fund's obsolete name matched against current
   names by trigram finds the right fund 1 time in 10, so the resolver must search
   the whole name history and fall back on the quota. The two FIDCs the
   restatement spike named are still unpaired (no FNET link yet), so the demo's
   restatement finding moves to MN I FIDC (delinquency 0 to R$187.3M, compared).
   Also measured: the dormant screen refuses whole (8,218 rows) and must be
   pinned, `cvm_fi_perfil`'s liquidity fields have been empty since 2020-08, and
   FNET holds FII, FIDC and ETF documents only, so FI regulamentos are not there.
   The SQL pack (§12) re-runs everything with one `health.yml mode=diagnostics`
   dispatch on this branch (`.github/workflows/health.yml:562-587`).
3. **The Sunday scope as decided does not fit one day.** Seven full blocks plus
   two minimal ones plus upload and PDF, with no engine code yet, is two to
   three days of work. Recommended Sunday
   cut (§8): spreadsheet input (the BTG PDF reader waits for a sample), blocks
   1, 3, 10, 11 and 14 (screens only; the abnormal-movement rule waits for the
   thresholds), block 4 over the existing `api.fund_restatement_diff`, block 2 as
   one level plus master recursion, and the PDF. Blocks 6-minimal and 13-minimal
   move to the week. The brief's own fallback (spreadsheet, blocks 1, 3, 10, PDF)
   stays the floor.
4. **Two blockers are the owner's, not the code's:** the sample BTG statement
   (nothing in the repo reads a statement; `openpyxl` is only used for ANBIMA
   workbooks) and the thresholds for abnormal movement and material restatement
   (§9, proposals attached).
5. **Eight decisions are asked in §9**, each with a recommendation: hosting,
   engine location, thresholds, cost cap, investigator cap, what to do with #340,
   which blocks become agents, and the scope cut.

## 1. State of the work

| Fact | Evidence |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| #340 (map), #341, #342, #343, #344, #345 and #352 are **closed as not planned** since 2026-09-30, not paused | GitHub issues, read 2026-10-02. Closing comment on #340: "outside the quant-research focus the owner set for now (the research seam, #371 / #410). The settled design above stays valid. Reopen it when the demo is prioritized again." |
| #371 (research seam) closed completed on 2026-10-01, 11 of 11 sub-issues done | GitHub issue #371 |
| No open pull request; no branch named `demo/*` or `portfolio*` | `list_pull_requests state=open` returned 0; `list_branches` returned 16 branches, none matching |
| `supabase/functions/_shared/portfolio/` does not exist; only `silo-mcp/` does | `ls supabase/functions/` |
| Label `demo-diagnostico` does not exist | GitHub `get_label` returned 404 |
| `OPEN_ITEMS.md` item 15 still says "Paused 2026-09-28"; the planning index row still says "tickets under #340" | `docs/planning/OPEN_ITEMS.md:454-457`; `docs/planning/README.md:16`. Both are stale against the close. Not edited here (§9, decision 6) |
| #348 (CDA block 1 key) is done and every year 2005–2026 was re-ingested | `docs/planning/OPEN_ITEMS.md:463-466` |
| #352 (block 2 drops rows differing only by `ID_SUBCLASSE`) lost 95 of 80,301 rows in 2026-08 | Issue #352. About 0.1% of block-2 rows; it blurs a few sub-class positions, it does not block look-through |
| Owner decisions already on record for block 5 returns: price-only adjustment for share-count events, no cash reinvestment, unverified label months are unknown | #344 comments of 2026-09-27 |

## 2. Status by block

Fourteen blocks, read against schema `api` at commit `cc3ab2a`. "ready" means an
`api` function already returns what the block needs; "partial" means the data is
in the warehouse but no serving function or a key step is missing; "missing"
means the data is absent. Each status is a reading of the SQL and the schema; where §4 measured the
block live, the Sunday column says so. The Sunday column
is the owner's decision (blocks 1, 2, 3, 4, 10, 11, 14 full; 6 and 13 minimal;
5, 7, 8, 9, 12 not on Sunday) followed by one phrase on feasibility.

| # | Block | Status (ready / partial / missing) | Evidence (file:lines or ticket) | Sunday? (yes / minimal / no) |
| --- | --------------------------------------------------- | ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| 1 | Identification | ready | `api.search_funds` (ILIKE over `dim_fund.fund_name`, clamp 25 for anon; `src/store/analytical/19_api_contract.sql:2036-2067`), `api.lookup` (escaped ILIKE, LIMIT 20; `19_api_contract.sql:4582-4662`), `api.fund_profile`. pg_trgm is installed (`src/store/migrations/24_lookup_trgm.sql:14`) and `dim_fund.fund_name` has a GIN trigram index (`src/store/analytical/01_dim_fund.sql:89`), but no function calls `similarity()`. `cvm_fi_cda_fund_name` (migration 60) is read by nothing in `api` | yes; name match works today, fuzzy rank is one new query |
| 2 | Look-through and shared exposure | partial | `api.fund_holdings(p_cnpj, kind='equity'\|'fund')`: one fund, one level (`19_api_contract.sql:2106-2208`). `api.fund_debentures` serves block 6 (`19_api_contract.sql:2252-2378`). Block 1 is served by no `api` function (revoked, `src/store/analytical/12_grants_and_rls.sql:161`). `mv_fund_holdings_monthly` (`src/store/analytical/30_fund_holdings.sql`) aggregates blocks 4 and 2 per month, quota totals only. No recursion exists (#342–#344 closed not planned) | yes; one level is served, recursion is new SQL with a cycle guard |
| 3 | Fee cost | partial | Nothing reads `cvm_fi_balancete_resumo` (`src/store/migrations/61_fi_balancete_resumo_rename.sql:3-8`). Columns `vl_taxa_administracao`, `vl_taxa_adm_efetiva`, `vl_taxa_gestao`, `vl_taxa_distribuicao`, `vl_taxa_performance`, `vl_taxa_ingresso_saida`: accumulated from each fund's fiscal-year start, negative, NULL when not filed. The published rate (`cad_fi` TAXA_ADM) lands only in `cvm_fund_registry.raw`; no lâmina dataset (`src/fetchers/cvm_config.py:38-166`) | yes; a month-over-month difference and a % of NAV, fiscal-year reset handled |
| 4 | Material restatement | ready | `api.fund_restatement_diff(p_cnpj, p_from, p_to, p_tipo, p_fnet_id)` (`src/store/analytical/24_api_fnet.sql:394`); `api.fund_restatements` carries `diff_status` and `n_fields_changed`. `api.screen_restatements` has no CNPJ filter (`src/store/analytical/25_api_filing_screens.sql:106-127`). `cvm_column` is always NULL (crosswalk deferred) | yes; per-CNPJ diff is served, the materiality threshold is the owner's |
| 5 | Return vs CDI | partial | `api.fund_nav` / `api.panel` serve `quota` (FI only). The return is computed only in `public.fund_performance_series` (`src/store/analytical/17_performance_analysis.sql:41-105`), not in `api`. CDI is `api.macro_series('CDI')`, SGS 12, % per business day (`src/store/analytical/26_api_events_macro.sql:204`) | no; needs a monthly-returns function (#342–#344 closed not planned) |
| 6 | Benchmarks (min variance, ERC) | partial | Quota series exist (`api.fund_nav`); no monthly-returns set function (#342–#344 closed not planned); no NTN-B price series (#341 closed not planned) | minimal; a covariance over fund quotas only, no bond leg |
| 7 | Warnings (private credit, liquidity, concentration) | partial | `cvm_fi_perfil` types `pr_ativo_cred_priv`, `nr_dia_cinqu_perc`, `nr_dia_cem_perc`, `st_liqdez`, `pr_patrim_liq_convtd_caixa` (`src/store/schema.sql:1031-1097`). Whether any `api` function exposes them: not verified this session | no; `pr_ativo_cred_priv` is 94% filled, but every liquidity field has been empty since 2020-08 (§4) |
| 8 | Regulation terms | missing | No lâmina dataset (`src/fetchers/cvm_config.py:38-166`). `fnet_document` holds metadata only, no bodies and no URL column; download is `downloadDocumento?id=<fnet_id>` at 1 req/s (`src/fetchers/fnet_fetcher.py:223-258`, `:108-117`). CVM publishes `lamina_fi_YYYYMM.zip` monthly since 2019-01 (<https://dados.cvm.gov.br/dataset/fi-doc-lamina>, columns not verified) | no; a new ingest (lâmina). FNET holds FII, FIDC and ETF documents only, so FI regulamentos are not there (§4) |
| 9 | Private credit by issuer | partial | `api.fund_debentures` serves block 6 with `cpf_cnpj_emissor` and `issuer_tickers` (`19_api_contract.sql:2252-2378`). Block 4 files most fund debentures under `tp_aplic = 'Debêntures'` with no issuer CNPJ (R$788.9bn vs R$34.4bn on 2026-05, `src/store/analytical/30_fund_holdings.sql`); its issuer is ISIN chars 3–6 only. Set issuer resolution does not exist (#342–#344 closed not planned) | no; needs issuer resolution across blocks 4 and 6 |
| 10 | Exposure by indexer | partial | `fund_debentures.indexer` = `cd_indexador_posfx`, block 6 only. Block 1 has `tp_titpub` (`cvm_fi_cda`); block 4 has no indexer column. `cvm_securit_serie.taxas_indexadores` exists in the schema but is not in the field map (`src/parsers/field_maps/securit_serie.py:31-55`), so nothing writes it | yes; a versioned rules table over `tp_titpub`, `cd_indexador_posfx` and `tp_aplic` |
| 11 | Exposure by sector | partial | `cia_company.setor`; `dim_ticker_float.b3_sector` (view, `src/store/analytical/20_short_interest.sql:135-266`); `cvm_fii_periodic.segmento_atuacao`; `cvm_etf_registry.segment` (8 seed values); `cvm_fidc_setor` (32 sector columns). No function joins holdings to a sector | yes; a join from block 4 `cd_ativo` to `dim_ticker_float.b3_sector` |
| 12 | Correlation | partial | Same inputs as block 5: quota series in `api.fund_nav`, no monthly-returns function, no Tesouro price table | no; depends on block 5 |
| 13 | Rating and history | partial | `cvm_securit_serie.classificacao_risco_atual` is text with no agency column; FNET rating reports are metadata rows in `fnet_document` (no bodies). External: Austin Rating "Ratings Explorer" (<https://austin.com.br/Ratings-Explorer.html>), terms not read | minimal; show the stored text and the FNET document count, no history |
| 14 | Fund risk signals | ready | 10 `api.screen_*` wrappers (`src/store/analytical/23_api_screens.sql`, `25_api_filing_screens.sql`), each refuses above 1,000 rows, none accepts a CNPJ filter. Thresholds in `src/store/analytical/15_fraud_screens.sql`; dormant rule = 3 complete months with flows exactly 0, NULL disqualifies (`15_fraud_screens.sql:241-280`). Dashboard prose and SQL disagree in 3 places (evergreen strict `>70`, overdue 4 statuses, captive no minimum count) | yes; every screen but dormant fits one page with defaults; dormant refuses (8,218 rows) unless pinned (§4) |

## 3. Coverage matrix

What SILO can say about a statement line, at two levels: the line itself
("Direct position") and the same asset held through a fund ("Inside funds",
from the CVM CDA). Values are covered, partial or unknown. "unknown" covers two
different things, said in the reason: a source that is not ingested, and a
source that was not verified in this session. Rows that §4 measured (fund quotas, debentures, Tesouro inside funds, CRI/CRA
ratings) say so in the note column.

| Asset class | Direct position (statement line) | Inside funds (CDA) | Source / note |
| ---------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Listed stocks and units | covered — COTAHIST cash quotes, `vw_b3_quote_vista` (`tpmerc = '010'`) | covered — block 4 `cd_ativo` is the B3 ticker | `b3_cotahist` (`docs/agents/dataset-notes.md:39`); `cvm_fi_cda_acoes`. Units not separately verified |
| BDRs | partial — in COTAHIST; BDR tickers not verified this session | covered — block 4 (demais ativos codificados) carries BDRs by `cd_ativo` | `docs/reference/DATA_INVENTORY.md:206` |
| ETFs (equity) | covered — COTAHIST quote plus `cvm_etf_registry` | partial — block 2 (quota) or block 4 (ticker); which, not verified | `b3_cotahist`, `cvm_etf_registry`; `etf_daily` empty for post-CVM-175 share classes (`docs/agents/dataset-notes.md:110`) |
| ETFs (fixed income) | partial — `b3_trade_consolidated`, no open price, retention edge 2025-06-10 | partial — same block 2 / block 4 question, not verified | `src/store/migrations/57_b3_trade_consolidated.sql`; not in COTAHIST; retention edge as checked 2026-09-30 (`docs/agents/dataset-notes.md:53`) |
| FII quotas | covered — COTAHIST quote; filings via `vw_fii_mensal_latest` | partial — block 2 by CNPJ or block 4 by ticker; not verified | `b3_cotahist`; `cvm_fii_mensal` keeps every `versao` (migration 43; `docs/agents/dataset-notes.md:71`) |
| FI/FIC quotas | covered — `api.fund_nav`, `dim_fund` | covered — block 2 `cnpj_cota`, with CVM's `emissor_ligado` flag | `cvm_fi_cda_cotas`; #352 drops 95 of 80,301 rows (0.1%) |
| FIDC quotas | partial — monthly informe only (`cvm_fidc_*`); no daily quota in `api.fund_nav` | covered — block 2 by CNPJ | `cvm_fidc_*` tables; restatements in `fnet_document` |
| Tesouro Direto (NTN-B, NTN-B Principal, LFT, LTN, NTN-F, NTN-C, NTN-I) | partial — identification only; no price table (#341 closed) | covered — block 1 `tp_titpub`, `cd_selic`, `dt_venc`, qty, value; NTN-B vs NTN-B Principal label not verified | `cvm_fi_cda`; block 1 gives a derived unit price (`vl_merc_pos_final / qt_pos_final`), not a published one. Candidate: Tesouro Transparente `PrecoTaxaTesouroDireto.csv`, columns not verified |
| Debêntures | partial — no debenture registry or price; issuer via ISIN chars 3–6 only | covered — block 6 (issuer CNPJ, indexer, coupon) and block 4 `tp_aplic = 'Debêntures'` (no issuer CNPJ) | `cvm_fi_cda_debentures`, `cvm_fi_cda_acoes`; block 4 R$788.9bn vs block 6 R$34.4bn on 2026-05 |
| CRI/CRA | partial — `cvm_securit_serie` (rating text; `taxas_indexadores` never written); no price | partial — block 6 (títulos do agronegócio e de crédito privado) is ingested; whether CRI/CRA rows sit there or in block 5 was not measured | `cvm_securit_serie`, `cvm_securit_fluxo` |
| CDB/LCI/LCA/LF | unknown — no source ingested | unknown — block 5 (depósitos a prazo e outros títulos de IF) not ingested | none |
| COE | unknown — no source ingested | unknown — block 3 (swap) or block 8 (não codificados), neither ingested | none |
| Offshore funds/stocks | unknown — no source ingested | unknown — block 7 (investimento no exterior) not ingested | none |
| Cash | partial — a statement amount; SILO holds no source for it | unknown — block 8 (demais ativos não codificados) not ingested | `docs/reference/DATA_INVENTORY.md:211` |

The CDA archive has eight blocks and the repo reads four. The block names below
are CVM's own, from the dataset page
(<https://dados.cvm.gov.br/dataset/fi-doc-cda>, read 2026-10-03 UTC-3 through
Firecrawl), which lists them as the structure of the CDA XML standard; the repo's
shorter description is `docs/reference/DATA_INVENTORY.md:197-213`. The column
lists of blocks 3, 5, 7 and 8 are in `meta_cda_fi_txt.zip`, which was not read
(a zip, not fetchable through the service). The same page says that positions
under a confidentiality request are published consolidated in
`cda_fi_CONFID_AAAAMM.csv` until the request expires, that the three newest
months are re-published daily (Tuesday to Saturday, 08:00) with restatements,
and months 4 to 12 weekly; SILO reads a month once (#476), so the thin recent
months in §4 are CVM's publication lag plus confidentiality, not a parser
loss. The archive is already downloaded every month; adding a block costs a
field map, a migration, an `ingest_*` method and a test.

| Block | Content (CVM's block name) | Ingested? | Table | Serves which blocks |
| ----- | ----------------------------------------- | ------------------------------------------ | ----------------------- | ------------------------------------------------------------------ |
| BLC_1 | Títulos públicos do SELIC | yes (#348; re-ingested 2005–2026) | `cvm_fi_cda` | 2, 10; Tesouro row of the matrix. Not served by any `api` function |
| BLC_2 | Cotas de fundos de investimento | yes | `cvm_fi_cda_cotas` | 2 (recursion input), 1 (master/feeder pairs) |
| BLC_3 | Swap | no — "no consumer asked" | — | none; COE row stays unknown |
| BLC_4 | Demais ativos codificados (stocks, BDRs, and the debentures that carry an ISIN) | yes | `cvm_fi_cda_acoes` | 2, 9 (debentures by ISIN), 11 (sector by ticker) |
| BLC_5 | Depósitos a prazo e outros títulos de instituições financeiras (CDB, LF and the like: the "bank credit" block) | no | — | none; CRI/CRA, CDB/LCI/LCA/LF rows stay unknown |
| BLC_6 | Títulos do agronegócio e de crédito privado (debentures without an ISIN, CRI, CRA, private credit) | yes (migration 35; key ends in `row_hash`) | `cvm_fi_cda_debentures` | 2, 9, 10 |
| BLC_7 | Investimento no exterior | no | — | none; offshore row stays unknown |
| BLC_8 | Demais ativos não codificados (cash and "outros") | no — 28.9% of the archive by size | — | none; cash inside funds stays unknown |

## 4. Measured numbers

Measured on 2026-10-03 between 00:05 and 00:40 UTC-3 (03:05 to 03:40 UTC),
read-only SELECTs on the production project through the Supabase MCP, one query
at a time, each bounded as in `scripts/health_diagnostics/19_portfolio_phase0.sql`
(the `Q` ids below are that file's). CDA figures use 2026-05, the last month the
matview shows complete (§4, item 9).

| Brief item | Measurement | Result | Query |
| --- | --- | --- | --- |
| 3 | `pg_trgm` | installed, version 1.6. A GIN trigram index exists on `dim_fund.fund_name` (`src/store/analytical/01_dim_fund.sql:89`); no function calls `similarity()` | Q1 |
| 3 | Funds renamed since 2024 | 15,780 FI funds carry two or more distinct `denom_social` in `cvm_fi_cda_fund_name` since 2024-01; 1,159 carry three or more (the CVM 175 wave: "FIF ... Responsabilidade Limitada") | Q2 |
| 3 | Resolver test, 10 largest renamed funds (NAV R$70bn to R$287bn) | Oldest name vs 17,829 current names (latest name per fund filed since 2026-06), ranked by trigram similarity: the true fund came 1st in 1 of 10, 2nd in 1, then 6th, 11th, 47th, 374th and 3,630th, and 3 were absent (their newest name was filed 2026-05, so they fell outside the "current" window). Top-1 minus top-2 similarity was under 0.05 in 7 of 10. Exact names are unique: 24,794 funds named since 2026-05 with 0 duplicated names; the registry has 23,995 active FI with 23,995 distinct names. Consequence: match against the whole name history, every period, never only the current name; trigram alone on an obsolete or abbreviated name is not enough; the quota tie-break is for abbreviations | Q2, Q3 |
| 3 | XP Bancos pair | 2026-09-30: master 35.377.390/0001-06 quota 1.952607, NAV R$7.94bn, 1,147 holders; FIC 50.088.190/0001-19 quota 1.542011, NAV R$1.78bn, 9,865 holders. The quota separates them on each of the last 6 sessions | Q4 |
| 4 | Balancete fee to % per year, 5 funds, 2026-06 to 2026-08 (flow = this month's accumulated `vl_taxa_administracao` minus last month's, times 12, over NAV) | BB Renda Fixa Curto Prazo Automático FIC (42592315000115, NAV R$198bn): 1.65% to 1.97% p.a.; BB TOP RF CP Automático II (46133770000103): 1.18% to 1.41%; XP Bancos FIC: 0.18% to 0.21%; XP Bancos master: 0.11% to 0.12%; BB RF IV master (00822055000187): 0.003%. The fiscal-year reset is visible: XP master's May flow is +R$8.1M and XP FIC's June flow is +R$3.1M, so one month a year reads wrong without the reset date. **Error in p.p. against the disclosed fee: not measurable.** `cvm_fund_registry.raw->>'TAXA_ADM'` is NULL for all 5 (the CVM 175 registry rewrote `raw`); CVM's `cad_fi` carries `TAXA_ADM`, `TAXA_PERFM`, `INF_TAXA_ADM`, `INF_TAXA_PERFM` and `DT_INI_EXERC` / `DT_FIM_EXERC`, the fiscal year (`meta_cad_fi.txt`, read 2026-10-03), none in the field map (`src/parsers/field_maps/fund_registry.py:13-38`) | Q5, Q5b |
| 5 | Levels of fund quotas under 3 retail FICs, 2026-05 | BRASILPREV RT Clássico FIC (18630011000110): 1 level, one master, R$43.5bn. BB RF CP Automático FIC: 1 level, one master, R$198.6bn. XP Bancos FIC: 3 levels: XP Bancos master (R$1,832.6M) and XP Cash S1 (R$19.2M); the master holds XP Cash S1 (R$220.6M); XP Cash S1 holds Santander Cash Black (R$430.0M). The path guard found no cycle. #352's lost rows did not touch these roots | Q6 |
| 6 | FIDC restatements with a compared diff | `fnet_document_pair`: 1,598 compared (1,523 with at least one change), 18,367 unpairable_no_link, 80 unsupported_root, 5 declared_mismatch. Leaves changed with both numbers present: `VL_PATRIM_LIQ` in 111 pairs, `VL_CRED_EXISTE_INAD` in 53, each `VL_INAD_VENC_*` bucket in 26 to 54. The two FIDCs of the 2026-09-25 spike, ALDEBARAN II (FNET 1319631) and FARMERS FIRST I (1319967), are `unpairable_no_link`: the fortnightly sweep has not linked them, so they cannot carry the demo yet. Largest compared delinquency moves: MN I FIDC (32113885000121), 12/2025 RE delivered 2026-01-16, 1 day after the original, 152 leaves changed, `VL_CRED_EXISTE_INAD` 0.00 to 187,284,652.71; MULTIPLICA FIDC (23216398000101), 05/2026 RE, 6,237,182.71 to 176,248,408.07; FIDC 41778453000120, 04/2026, 473.0M to 523.0M | Q7 to Q7d |
| 7 | Funds with 60 month-end quotas in the last 61 months (`fact_fund_monthly`) | FI: 13,204 of 38,619 (34%); 21,967 have 36 or more. FIDC (5,657), FII (1,644), FIP, FIAGRO: 0, because the matview carries `vl_quota` for FI only. FIDC returns must come from `cvm_fidc_tranche.vl_cota`, FII and ETF from the tape | Q8 |
| 7 | NTN-B: what is missing | No price table (grep for `tesouro`, `NTN` in `src/store/`: only fund holdings in `cvm_fi_cda`, the DPL curve in `b3_reference_rate`, DAP futures). Block 1 gives a derived unit price per fund (`vl_merc_pos_final / qt_pos_final`), never a published one. The public source exists: Tesouro Transparente's `precotaxatesourodireto.csv` (13.8 MiB on 2026-10-02), daily since December 2004 per its metadata PDF (the dataset page says January 2002), columns Tipo Título, Data Vencimento, Data Base, Taxa Compra Manhã, Taxa Venda Manhã, PU Compra Manhã, PU Venda Manhã, PU Base Manhã; PU Base is the mark-to-market price (<https://www.tesourotransparente.gov.br/ckan/dataset/taxas-dos-titulos-ofertados-pelo-tesouro-direto>, read 2026-10-03 UTC-3) | — |
| 8 | `cvm_fi_perfil` fill at 2026-08-31 | 25,218 rows; `pr_ativo_cred_priv` 23,724 (94%); `pr_patrim_liq_maior_cotst` 25,218 (100%); `nr_dia_cinqu_perc`, `nr_dia_cem_perc`, `st_liqdez`, `pr_patrim_liq_convtd_caixa`: 0. Over 2019-01 to 2026-08 (1,984,754 rows) `nr_dia_cinqu_perc` was filled in 5 rows, the last in 2020-08, and `st_liqdez` never; the `raw` keys of a 2026-08 row carry no liquidity field. CVM's perfil no longer publishes them: block 7's liquidity leg has no source in SILO | Q9 |
| 9 | Block 4 debentures per month (`mv_fund_holdings_monthly`, kind debenture) | R$579.3bn in 2025-01 (3,814 funds, 1,794 issuer codes) rising to R$796.9bn in 2026-02 and R$788.9bn in 2026-05 (4,249 funds, 2,171 codes); then R$339.7bn, R$309.8bn, R$264.3bn for 2026-06, 07, 08 with 2,380, 2,324, 2,110 funds. The fall is CVM's publication lag (the three newest months are re-published daily until complete, §3) plus positions under confidentiality, which CVM publishes only consolidated. Last complete month: 2026-05 | Q10 |
| 9 | Block 6 per month | R$34bn to R$59bn a month through 2025 (1,377 to 2,114 funds); R$34.4bn in 2026-05 (1,154 funds); R$9.5bn in 2026-08 (491 funds). Same lag | Q10 |
| 9 | Block 4 debentures resolvable to an issuer, 2026-05 | 870 issuer codes (ISIN characters 3 to 6). 147 match a listed company's ISIN stem in `dim_ticker_float`: R$338.3bn of R$788.9bn, 43% by value. 57% by value is debt of issuers with no listed stock. The matview gives the code only, no CNPJ; CRI and CRA are not in it | Q10b |
| 13 | Block 1 by title, 2026-05 (for the indexer rules) | Held outright (`tp_aplic = 'Títulos Públicos'`): LFT R$2,281.3bn in 7,098 funds; NTN-B R$1,061.1bn in 4,548; LTN R$275.1bn in 1,026; NTN-F R$94.2bn in 462; NTN-C R$49.4bn in 160; NTN-I R$0.3bn in 7. Repo collateral (`Operações Compromissadas`) separately: LFT R$823.4bn, LTN R$369.4bn, NTN-B R$327.4bn, NTN-F R$196.6bn | Q13 (pack: block 1 is not queried; measured by hand) |
| 14 | Block 6 indexer codes since 2025-01, by value | DI1 "DI de um dia" R$543.1bn (2,702 funds); IAP (IPCA) R$123.7bn; OUT "OUTROS" R$69.5bn; NULL R$68.9bn; PRE R$5.5bn; DOL R$5.4bn; TR R$2.0bn; IGP R$0.7bn; IGM (IGP-M) R$0.35bn; SEL R$0.26bn; IPC (FIPE) R$0.25bn; TJL R$0.06bn; INP (INPC) R$0.01bn. Thirteen codes plus NULL; OUT and NULL together are R$138bn, 17%, unclassified at source | Q11 |
| 16 | `classificacao_risco_atual`, CRI and CRA since 2025 | 122,071 rows; 21,607 non-null (18%); 120 distinct values; 4,943 rows read as a grade (AAA to CCC with br, sf or bra decorations: 4% of rows, 23% of non-null); 16,133 say "não há", "não aplicável" or "0". A parser for agency scale and grade would yield about 5,000 rated rows and no history. FNET: "Relatório de Agência de Rating" 9,620 documents, 2020-12-11 to 2026-09-30, metadata only | Q12, Q12b |
| 19 | Regulamentos in `fnet_document` | No standalone regulamento type. "Instrumento Particular de Alteração do Regulamento" 6,600 documents (2016-09-22 to 2026-10-01). `fnet_document_filter` links 206,486 documents to tipoFundo 2 (FIDC), 89,872 to 3 (ETF), 88,411 to 1 (FII) and none else: FI and FIF regulamentos are not on FNET. No document was downloaded | Q13 |
| 20 | Anon read path | `has_schema_privilege('anon','public','USAGE')` is **true** (Supabase's default; the repo grants USAGE only on `api`), and true on `api`. 39 public tables have RLS off; 0 of them are SELECT-able by anon. Public relations anon can SELECT: the dims, facts, matviews and `vw_*` the repo grants on purpose (`12_grants_and_rls.sql:204-225`, `20_short_interest.sql:539-542`) plus six tables foreign to SILO (`messages`, `profiles`, `threads`, `thread_participants`, `thread_summaries`, `table_name`; RLS on, 0 to 3 policies, 16 to 48 kB each). Supabase security advisors: 31 ERROR security_definer_view (the `api` views and dims: the grant model relies on them), 53 WARN anon can execute SECURITY DEFINER functions (the `api` contract), 67 INFO RLS enabled with no policy, 35 WARN function search_path mutable (public analytical functions), 6 WARN matview in API, 1 WARN pg_trgm in public, 6 WARN auth_allow_anonymous_sign_ins on the foreign tables, 1 WARN leaked-password protection off. Conclusion for the engine: RLS off is not on its read path. The six foreign tables and the anonymous-sign-in setting are a discovery to ticket, not Phase 0 work | Q14 to Q14c |
| 17 | Screens with default arguments | zombie_growth 459 rows, captive_vehicles 358, evergreen_aging 8, overdue_securit 829, late_filers 17, silent_filers 46, restatements 57: each fits one page. `screen_dormant_funds(3)` refuses with 22023 (8,218 rows: 10 empty shells and 8,208 parked, of which 1,815 above R$100M and 185 above R$1bn); pinned to `empty_shell` it returns 10. The engine must pin a dormancy class or a NAV floor, or the wrapper gains a CNPJ filter | Q16 |
| 21 | Demo portfolio | measured candidates in §6 | Q15 |

Numbers measured earlier in the repo and reused as evidence: dormant funds 61
empty shells and 8,257 parked out of 25,974 filing (`src/store/analytical/15_fraud_screens.sql:208-209`,
earlier window); FIDC restated documents 608 in the 23 delivery days of
2026-09, about 14% of monthly filings (`docs/planning/DOCUMENTS.md:197-210`); CDA
2026-06 held 7,375 funds in block 1 against 11,860 in CVM's current zip
(CHANGELOG 2026-10-02, #476). The brief's figures (R$264.3bn block 4 and R$9.5bn
block 6 for 2026-08; 283 rating values in 74,424 rows; 2,561 companies with a
CVM sector; about 149 papers with a B3 sector) came from the owner; the first two
are reproduced above, the others were not re-measured.

## 5. Blockers

| Blocker | Why it blocks | Ticket / owner |
| ----------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| Cloud sessions behind this proxy reach Supabase only when the MCP connects (it did at 00:05 UTC-3 on 2026-10-03, not before); CVM, FNET and Tesouro stay unreachable except through a third-party fetch | a Sunday build session may again have no database for hours | the SQL pack (§12) runs in one `health.yml mode=diagnostics` dispatch on this branch; the engine itself reads PostgREST, which was not tested from here |
| No set-based `api` functions (look-through, issuer set, returns) | blocks 2, 5, 6, 9, 12 need them; blocks 1 and 3 need two new functions | #342, #343, #344 closed; new tickets under the demo label (§9 decision 6) |
| No fee reader, and no disclosed fee in SILO (`TAXA_ADM` NULL in every registry row checked) | block 3 ships as an estimate with no comparison | new function over `cvm_fi_balancete_resumo`; `cad_fi` or lâmina ingest for the disclosed fee and the fiscal-year reset date |
| The spike's FIDCs (ALDEBARAN II, FARMERS FIRST I) are `unpairable_no_link` | the planted restatement finding cannot use them yet | demo uses MN I FIDC 32113885000121 (compared, 152 leaves) or MULTIPLICA FIDC 23216398000101; or the owner dispatches `backfill.yml` `fnet_sweep` for the two CNPJs |
| `api.screen_*` take no CNPJ filter; `screen_dormant_funds(3)` refuses whole (8,218 rows) | block 14 fetches each screen whole and joins client-side; dormant needs a pinned class or NAV floor, or a `p_cnpj text[]` on the wrappers | `src/store/analytical/23_api_screens.sql`, `25_*.sql` |
| No Tesouro price series | NTN-B direct position has value from the statement only; blocks 5, 6, 12 partial for it | #341 closed; candidate source in §7.3 |
| Sample BTG statement not in the repo; no statement reader or CPF masking code exists | slice 1 | owner |
| Label `demo-diagnostico` missing | PR labelling | created with this PR if the API allowed it; otherwise owner |
| `silo-cvm-data-analyst` skill is stale (says the warehouse is mostly empty as of 2026-06) | an agent that trusts it will under-use the data | refresh in the week |

## 6. Demo portfolio (candidates)

Eight positions, each planting one finding. Rows marked measured were checked
on production on 2026-10-03 (UTC-3), on CDA month 2026-05 unless stated; the
SQL id is the pack's. The owner's real-portfolio smoke test stays separate and
is never part of this list.

| # | Position (candidate) | Planted finding | How it is confirmed (SQL id) | Status |
| --- | --- | --- | --- | --- |
| 1 | NTN-B 2035, held directly | A Tesouro line SILO identifies by title and maturity but cannot price: no price series (#341 closed); the report labels the benchmark partial. Block 1 shows 4,548 funds holding NTN-B outright (R$1,061bn) | block 1 by `tp_titpub` and `dt_venc`; no price query possible | measured (holdings), price absent by construction |
| 2 | PETR4, held directly | Shared exposure: the same stock inside a fund of the portfolio | Q15 (block 4, `cd_ativo = 'PETR4'`, 2026-05) | measured |
| 3 | GERAÇÃO L. PAR FIA (08935128000159) | Second leg of row 2: R$1,007.9M in PETR4 (23,996,548 shares) on 2026-05. Alternatives: KAPITALO MASTER I (11377282000167, R$1,420.7M), CAIEIRAS FIF (09577034000118, R$3,854.6M, looks exclusive) | Q15 | measured |
| 4 | XP Bancos master 35.377.390/0001-06 and FIC 50.088.190/0001-19 | Ambiguous pair when the statement abbreviates the name; the quota tells them apart: 1.952607 vs 1.542011 on 2026-09-30; NAV R$7.94bn vs R$1.78bn; 1,147 vs 9,865 holders. The FIC also plants the 3-level look-through: master, XP Cash S1, Santander Cash Black | Q4, Q6 | measured |
| 5 | MN I FIDC (32113885000121) | Material restatement: 12/2025 informe mensal re-filed (RE) on 2026-01-16, one day after the original, 152 leaves changed, delinquency (`VL_CRED_EXISTE_INAD`) 0.00 to R$187,284,652.71; a second compared restatement for 07/2026 (28 leaves). Alternate: MULTIPLICA FIDC (23216398000101), 05/2026 RE, delinquency R$6.2M to R$176.2M. The spike's ALDEBARAN II and FARMERS FIRST I are unpairable until the FNET sweep links them | Q7, Q7c, `api.fund_restatements('32113885000121')` | measured |
| 6 | XP LIQUIDEZ FIC (51488342000133) beside row 4's XP Bancos FIC | Overlap: both hold the XP Bancos master (R$3,358.5M and R$1,832.6M on 2026-05, `emissor_ligado = 'S'`), so two statement lines are one underlying book | Q15b (`cnpj_cota = '35377390000106'`) | measured |
| 7 | BB RENDA FIXA CURTO PRAZO AUTOMÁTICO FIC (42592315000115) | Renamed fund: "...FUNDO DE INVESTIMENTO EM COTAS DE FUNDOS DE INVESTIMENTO" (2024-01) to "...FIC FIF RESPONSABILIDADE LIMITADA" (2026-08); the old name ranks 374th by trigram against current names. Also one master (R$198.6bn) and an estimated fee of 1.65% to 1.97% p.a., so three findings in one line | Q2, Q3, Q5, Q6 | measured |
| 8 | One fixed-income ETF or one FII | Breadth for the indexer and sector tables: a non-FI quota with a segment | Q10, Q11 | candidate, not measured |

## 7. Input, hosting, missing data, skills and agents

### 7.1 Input (brief item 18)

- Nothing in the repo reads a broker statement. `openpyxl` is a dependency but
  is used only for ANBIMA workbooks (`src/pipeline/anbima_pipeline.py:67,267`)
  and the OFR workbook (`src/parsers/global_market.py:267-270`). No PDF library
  is installed or imported. CPF check-digit validation exists
  (`src/parsers/validation.py:124-140`); no masking code exists.
- The BTG sample statement is not in the repo and must come from the owner. Until
  it does, slice 1 reads the spreadsheet template only. Proposed template, one
  row per position: `linha_extrato` (the name as printed), `tipo` (one of ação,
  fundo, FII, ETF, FIDC, tesouro, debênture, CRI, CRA, CDB, LCI, LCA, outro),
  `codigo` (ticker, CNPJ, ISIN or Tesouro title plus maturity, when the statement
  gives one), `quantidade`, `preco_unitario`, `valor` and `data_posicao`; plus one
  cell for the statement's own total. The reader stops when the sum of `valor`
  differs from the total by more than R$0.01 times the number of rows, and says
  which rows it could not read.
- Masking before any log or LLM call: holder name, CPF and account number are
  replaced by fixed tokens at read time; the engine never receives them.

### 7.2 Hosting (brief item 18)

| Option | Fits the Python engine? | PDF parsing | Secrets | Supabase access | Cost (read 2026-10-02) |
| --------------------------------------------- | -------------------------------------------------------------------------- | ----------- | ---------------------------- | ---------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Cloudflare Workers (TS or Python via Pyodide) | no: 128 MB memory, CPU 30 s default on Paid | weak | Worker secrets | PostgREST with the anon key | in the US$5/month Workers Paid plan (<https://developers.cloudflare.com/workers/platform/pricing/>, <https://developers.cloudflare.com/workers/platform/limits/>) |
| Cloudflare Containers | yes: `lite` 1/16 vCPU 256 MiB to `standard-4` 4 vCPU 12 GiB, scale to zero | yes | Worker secrets passed as env | PostgREST with the anon key | billed per 10 ms active; 25 GiB-h, 375 vCPU-min, 200 GB-h per month included in Workers Paid (<https://developers.cloudflare.com/containers/platform/pricing/>, <https://developers.cloudflare.com/containers/platform/limits/>) |
| Cloudflare Pages | static page and Functions (Workers rules) | n/a | n/a | n/a | free tier for static (<https://developers.cloudflare.com/pages/platform/limits/>) |
| Supabase Edge Function | no: Deno/TypeScript; the original design's choice | weak | Supabase secrets | PostgREST | already in use for `silo-mcp` |
| GitHub Actions on dispatch | yes, batch only, no upload page | yes | repository secrets | `POSTGRES_URL` is available there, but the engine must still read only `api` | free minutes |
| Local only | yes | yes | `.env` | `POSTGRES_URL` or PostgREST | zero |

What can be live on Sunday: nothing on a host without a decision taken on
Saturday; the engine runs locally and produces the PDF. The page is slice 7.

### 7.3 Missing data and where it comes from (brief items 10 and 22)

Order of search when a value is missing, as decided: another SILO table, then
CVM's registry or lâmina and the FNET regulation, then the manager's site, then
the internet through Exa. A filled value carries source, date and excerpt and is
shown as external. Each gap below is also an ingest-backlog candidate.

| Gap (block) | First public source | What it gives | Terms / cost | Status |
| ---------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- | ------------------------------------ |
| Disclosed administration and performance fee (3); redemption terms (8) | CVM lâmina, `lamina_fi_YYYYMM.zip`, monthly since 2019-01 (<https://dados.cvm.gov.br/dataset/fi-doc-lamina>) | per fund and month: fees and redemption rules as declared; monthly files since 2019-01, a HIST folder since 2014, weekly updates (dataset page read 2026-10-03 UTC-3). Columns not read: the dictionary is `meta_lamina_fi_txt.zip` | open data | not ingested; six-step dataset add |
| Tesouro prices and rates (5, 6, 10, 12) | Tesouro Transparente, `PrecoTaxaTesouroDireto.csv` (<https://www.tesourotransparente.gov.br/ckan/dataset/taxas-dos-titulos-ofertados-pelo-tesouro-direto>) | daily buy and sell rates and PU per title and maturity, plus PU Base (mark-to-market), since December 2004; metadata PDF read 2026-10-03 UTC-3 | CKAN dataset by CODIP, updated daily (last 2026-10-02 10:24 UTC); licence text not read | not ingested (#341 closed) |
| Issuer facts for unlisted debenture and CRI/CRA issuers (9, 11) | Receita Federal CNPJ open data, monthly ZIPs (<https://dadosabertos.rfb.gov.br/CNPJ/dados_abertos_cnpj/>) | CNAE, situação cadastral, capital social, natureza jurídica | open data; tens of GB per month | not ingested; needs its own decision |
| Debenture indexer, maturity, price (9, 10, 13) | ANBIMA Data API, debentures (<https://developers.anbima.com.br/en/documentacao/precos-indices/apis-de-precos/debentures/>); debentures.com.br SND | secondary-market rates and unit prices with `grupo` (indexer) and `codigo_ativo`; SND has characteristics per issue | ANBIMA terms of use not read; SND has no documented bulk file | not evaluated beyond the pages found |
| Ratings with agency, scale and date (13) | Austin Rating public pages (<https://www.austin.com.br/Ratings-Explorer.html>); FNET rating reports (PDF) | Austin only: grade, action, date per FIDC, CRI, debenture | terms of use not read; scraping decision needed | not ingested |
| Lawsuits, judicial recovery (Investigator) | JUDIT API (<https://judit.io/>) | processes by CNPJ | price not public in the pages found | later |
| Trustee annual report (9) | FNET and the trustee's site (PDF) | covenants, guarantees | unstructured | agent candidate, later |

### 7.4 Skills in this session (brief item 23)

Present: `silo`, `run-silo-bz`, `fix-register`, `silo-cvm-data-analyst` (stale:
its notes say the warehouse was mostly empty as of 2026-06), `prepublish-review`,
`pdf`, `xlsx`, `docx`, `finance:reconciliation`, `data:validate-data`, `exa:search`
and `exa:exa-agent` (the skills are installed, but the Exa MCP did not connect
through this session's proxy), `deep-research`, `dataviz`, `research`,
`domain-modeling`, `grilling`, `wayfinder`, `claude-api`.

Absent: `pdf-reading` (the `pdf` skill covers it), `frontend-design` (nearest are
`superdesign` and the `design:*` skills), a Cloudflare plugin (Context7 can fetch
Cloudflare docs).

Worth writing: `extrato-corretora` (statement to positions, sum check, masking
rules, one broker layout per file); `revisor-numeros` (the Revisor protocol: every
number in the text must match a key in the engine JSON, every citation must match
its source, extreme values need a second path); `demo-diagnostico` (repo skill:
branch and label rules, slice conventions, the engine contract). And a refresh of
`silo-cvm-data-analyst` to the 2026-10 state.

### 7.5 Agents (brief item 24)

- **Redator and Revisor** are two single-turn calls to the Messages API behind a
  provider interface (`src/portfolio/llm.py`: `complete(system, user, schema)`),
  provider chosen by environment variable, Anthropic first, so the owner can swap
  the LLM without touching the engine. The Claude Agent SDK is not needed: it is
  a full coding harness, and these two roles make no tool calls. The Revisor
  returns a structured verdict per sentence (kept, removed, needs second path).
- **Where they run:** inside the engine process. Sunday: the local CLI. Week: the
  same code inside the Container (§9 decision 1). Not in a GitHub Action (no upload
  path) and not as scheduled sessions (`docs/planning/AGENTS.md` is for the
  repo's own Scout, Builder and Sentinel, which hold no DB credential).
- **Investigator** (after Sunday): a tool-use loop with Exa search as the tool,
  triggers as decided (screen hit, material restatement, abrupt or absent
  movement, downgrade, issuer material fact), capped per §9 decision 5, every
  finding with URL, access date and quoted excerpt.
- **Specialised agents for PDF blocks (8, 13):** each a function with a declared
  input (document id, question) and output (value, page, verbatim quote), whose
  text goes through the same Revisor check. Not before the week.
- **Cost per report:** about US$0.4 to 0.6 on Opus 5.5, about US$0.2 on Sonnet
  5.5, for the Redator and Revisor pair with one revision loop (estimate from
  about 70k input and 7k output tokens at US$4 / US$20 and US$2 / US$10 per
  million tokens; prices from Anthropic's table cached 2026-09-25). The
  Investigator's Exa cost is not verified.

## 8. Slice plan

Sunday 2026-10-04, in order. Every slice is one PR on a `demo/*` branch, ready
for review, with offline tests, a CHANGELOG row and docs in English.

| # | Slice | Files | Size | Day |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ | -------------- | ------------ |
| 0 | Run §12 (owner or dispatch); fix the demo portfolio from the results | `scripts/health_diagnostics/19_portfolio_phase0.sql` | 1 dispatch | Saturday |
| 1 | Statement ingest: spreadsheet template → positions; sum check against the statement total; masking of name, CPF, account before any log or LLM | `src/portfolio/statement.py`, `src/portfolio/mask.py`, `tests/test_portfolio_statement.py`, `docs/reference/portfolio/template.xlsx` spec | 1 PR, ~4 files | Sunday a.m. |
| 2 | Blocks 1 and 3: `api.portfolio_resolve(p_names text[], p_quotas numeric[])` (trigram over `cvm_fi_cda_fund_name` and `dim_fund`, quota tie-break, score and ambiguity flag) and `api.portfolio_fees(p_cnpj text[], p_month date)` (balancete flow annualised, labelled estimate); catalog, `openapi.json`, MCP contract | `src/store/analytical/31_api_portfolio.sql`, `serve/catalog.py`, `tests/sql/portfolio_behaviour.sql`, `tests/test_portfolio_catalog.py` | 1 PR, ~6 files | Sunday a.m. |
| 3 | Blocks 2, 10, 11: `api.portfolio_lookthrough(p_cnpj text[], p_month date)` over CDA blocks 1, 2, 4, 6 with `WITH RECURSIVE`, cycle guard, depth cap, refusal above one page; indexer rules table versioned in the repo (`type → indexer`, never from a name); sector join through `cia_company.setor`, `dim_ticker_float.b3_sector`, `cvm_fii_periodic.segmento_atuacao`, `cvm_etf_registry.segment`, `cvm_fidc_setor` | same SQL file, `src/portfolio/indexer_rules.csv`, `src/portfolio/exposure.py`, tests | 1 PR, ~6 files | Sunday p.m. |
| 4 | Blocks 4 and 14: client-side joins over `api.fund_restatement_diff` and the 10 `api.screen_*` by CNPJ; material-restatement rule and abnormal-movement rule as data (thresholds from §9) | `src/portfolio/signals.py`, tests | 1 PR, ~3 files | Sunday p.m. |
| 5 | Blocks 13 and 6 minimal | `src/portfolio/rating.py`, `src/portfolio/risk.py` (min variance over 60 month-end quotas, Ledoit-Wolf; positions with fewer months are unknown) | 1 PR | week |
| 6 | Report: engine JSON → Redator (Claude) → Revisor (Claude, structured verdict; a number not found in the engine JSON removes the sentence) → HTML → PDF; Portuguese, "SILO", owner's signature, sources footer with data dates | `src/portfolio/report.py`, `src/portfolio/llm.py`, `src/portfolio/templates/`, tests with a fake provider | 1 PR, ~6 files | Sunday night |
| 7 | Upload page as a thin client on the approved host; PDF alone if the page does not fit | TypeScript under the host's directory | 1 PR | week |

Later, in this order: 9, 5, 12, 6 full, 7, 13 full, Investigator, any broker,
8 if a deterministic citation is possible, MCP.

## 9. Decisions for the owner

1. **Hosting.** Options: (a) Cloudflare Pages for the TypeScript page plus a
   Cloudflare Container (`basic`: 1/4 vCPU, 1 GiB) running the Python engine
   behind a Worker that holds the LLM key as a secret; (b) a Supabase Edge
   Function, as the original design, which forces the engine into TypeScript;
   (c) GitHub Actions on dispatch, batch only; (d) local only on Sunday. Workers
   alone are not an option for the engine: 128 MB memory and Pyodide Python
   (`<https://developers.cloudflare.com/workers/platform/limits/>`, read
   2026-10-02). **Recommendation:** (d) on Sunday, (a) in the week. Containers
   bill per 10 ms of active time inside the US$5/month Workers Paid plan
   (`<https://developers.cloudflare.com/containers/platform/pricing/>`, read
   2026-10-02). A fourth infrastructure is the owner's call, as the brief says.
2. **Engine location and language.** Python package `src/portfolio/` for
   orchestration, rules, risk and report; the data-heavy set operations as
   `api` functions in `src/store/analytical/31_api_portfolio.sql`, reached over
   PostgREST with the anon key (ADR 0001); a CLI
   (`python -m src.portfolio.diagnose statement.xlsx`) first, HTTP later.
   `serve/` stays local-only. **Recommendation:** as stated.
3. **Thresholds** (proposals; the owner sets the numbers). Abnormal movement,
   per fund, read from `cvm_fi_diario`: a daily quota move beyond 5 times the
   fund's own 60-session standard deviation, or beyond 3% for a fund whose
   indexer exposure is over 80% post-fixed; a day's inflow or redemption above
   10% of NAV or above R$50M, whichever is lower; a NAV change above 10% in one
   day not explained by flows. No movement: identical `vl_quota` for 5
   consecutive sessions in a fund that is not a FIDC or FII, or the dashboard's
   dormant rule (3 complete months with zero flows). Material restatement, on
   `fund_restatement_diff` leaves: NAV changed by more than 1%; any delinquency
   leaf (`VL_CRED_EXISTE_INAD`, `VL_INAD_*`) changed by more than 0.5 p.p. of
   NAV or R$1M; subordination changed by more than 1 p.p.; an amortization or
   quota value set to zero. Everything else is "revised, not assessed", as the
   design says.
4. **Cost cap per report.** Redator plus Revisor with one revision loop is
   about 70k input and 7k output tokens: about US$0.4 to 0.6 on Opus 5.5
   (US$4 / US$20 per million tokens), about US$0.2 on Sonnet 5.5 (prices from
   Anthropic's table cached 2026-09-25; estimate, not measured).
   **Recommendation:** cap at US$1.00 per report, Opus 5.5 for both roles.
5. **Investigator search cap** (after Sunday). **Recommendation:** 20 Exa
   searches per report, 5 per trigger, each finding with URL, access date and
   quoted excerpt. Exa's per-search price was not verified.
6. **#340 and the planning docs.** Options: reopen #340 and its tickets; or
   open one new map issue labelled `demo-diagnostico` that links #340 for
   lineage and leaves #341–#345 closed; then update `OPEN_ITEMS.md` item 15 and
   the planning index row. **Recommendation:** the new map, because the brief
   isolates the demo and the old tickets carry the MCP-first order that no
   longer holds.
7. **Blocks that become specialised agents.** Candidates: 8 (regulation PDF:
   redemption terms and contractual fee, with page and verbatim quote), 13
   (rating PDFs on FNET), the fatos-relevantes reading inside 9, and the
   Investigator. Never agents: 1, 2, 3, 4, 10, 11, 14 (deterministic; the
   numbers come from SQL). **Recommendation:** none on Sunday; 8 and 13 in the
   week, each as a function with a declared input and output whose text passes
   the Revisor's citation check.
8. **Scope cut.** **Recommendation:** Sunday = spreadsheet input, blocks 1, 3,
   10, 11, 14 (screens only), 4, 2 (one level plus master recursion), PDF. Floor
   = spreadsheet, blocks 1, 3, 10, PDF. If a week improves it a lot: 11/10 with
   the BTG PDF reader, 6 and 13 minimal, the page.

## 10. Not verified

- The fee error in p.p. (item 4): no disclosed fee exists in SILO to compare
  against, so only the estimate side was measured.
- The resolver on abbreviated statement names (the real BTG case): only the
  obsolete-name case was measured; the statement sample is still missing.
- `health.yml mode=diagnostics` on this branch was not dispatched; the §4 numbers
  came from the same queries run one by one through the Supabase MCP.
- The column lists of CDA blocks 3, 5, 7 and 8 (`meta_cda_fi_txt.zip`): not
  read. The block names are confirmed from CVM's dataset page (§3); block 5 is
  "depósitos a prazo e outros títulos de IF", so "bank credit" holds.
- The columns of CVM's lâmina dataset (`meta_lamina_fi_txt.zip`): not read. The
  dataset page was read (monthly since 2019-01, HIST since 2014, weekly updates).
- Tesouro Direto's price file: the metadata PDF was read (columns A to H), the
  CSV itself was not downloaded, and the licence text was not read.
- Cloudflare limits beyond the two pages cited; Supabase Edge Function CPU
  limits.
- ANBIMA Data, debentures.com.br, Austin Rating and JUDIT terms of use and
  prices: not read.
- FNET regulation documents: no download was made, so whether they carry a text
  layer and a citable redemption clause is unknown (the 2026-09-23 spike found 9
  of 9 sampled PDFs born-digital, `docs/planning/COMPETITIVE_GAPS.md:292`).
- Whether the six foreign tables in `public` (`messages`, `profiles`, `threads`,
  `thread_participants`, `thread_summaries`, `table_name`) belong to another
  project sharing this Supabase instance; only their existence and policies
  were read.
- Whether adding the `demo-diagnostico` label through the API creates it (checked
  when the PR was opened; see the PR).

## 11. Sources

**Repository** (commit `cc3ab2a`): `AGENTS.md`; `docs/agents/dataset-notes.md`;
`docs/planning/PORTFOLIO_DIAGNOSIS.md`; `docs/planning/OPEN_ITEMS.md:454-482`;
`docs/planning/DOCUMENTS.md`; `docs/planning/COMPETITIVE_GAPS.md:179-404`;
`docs/adr/0001-stateless-portfolio-analysis.md`; `docs/reference/DATA_INVENTORY.md:197-213`;
`src/store/schema.sql`; `src/store/migrations/24, 35, 49, 59, 60, 61`;
`src/store/analytical/01, 12, 15, 19, 23, 24, 25, 26, 30`; `src/fetchers/cvm_config.py:38-166`;
`src/fetchers/fnet_fetcher.py`; `src/pipeline/fnet_diff.py`; `supabase/functions/silo-mcp/tools.ts`;
`.github/workflows/health.yml`; `.claude/hooks/pre-push-docs.sh`.

**GitHub** (read 2026-10-02 via the GitHub API): issues #340, #341, #342, #343,
#344, #345, #352, #371 and their comments; open pull requests; branches; label
lookup.

**Web** (read 2026-10-02 UTC-3 through search excerpts unless a line says the
page itself was read):

- Cloudflare Workers pricing and limits:
  <https://developers.cloudflare.com/workers/platform/pricing/>,
  <https://developers.cloudflare.com/workers/platform/limits/>; Containers:
  <https://developers.cloudflare.com/containers/platform/pricing/>,
  <https://developers.cloudflare.com/containers/platform/limits/>; Pages:
  <https://developers.cloudflare.com/pages/platform/limits/>.
- Tesouro Direto prices and rates, dataset page and metadata PDF (read
  2026-10-03 UTC-3 through Firecrawl):
  <https://www.tesourotransparente.gov.br/ckan/dataset/taxas-dos-titulos-ofertados-pelo-tesouro-direto>,
  <https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/resource/1a8eb2e3-4902-4a38-a1eb-6410f23d90de/download/taxa.pdf>.
- CVM CDA dataset page (block names, confidentiality file, update policy; read
  2026-10-03 UTC-3 through Firecrawl): <https://dados.cvm.gov.br/dataset/fi-doc-cda>.
- CVM lâmina dataset page (read 2026-10-03 UTC-3 through Firecrawl):
  <https://dados.cvm.gov.br/dataset/fi-doc-lamina>.
- CVM fund registry metadata (read 2026-10-03 UTC-3 through Firecrawl):
  <https://dados.cvm.gov.br/dados/FI/CAD/META/meta_cad_fi.txt>.
- Receita Federal CNPJ open data:
  <https://dadosabertos.rfb.gov.br/CNPJ/dados_abertos_cnpj/>.
- ANBIMA debentures API:
  <https://developers.anbima.com.br/en/documentacao/precos-indices/apis-de-precos/debentures/>.
- Austin Rating public ratings: <https://www.austin.com.br/Ratings-Explorer.html>.
- JUDIT API (lawsuits by CNPJ): <https://judit.io/>.
- Anthropic model prices: the `claude-api` skill table cached 2026-09-25.

## 12. SQL pack

`scripts/health_diagnostics/19_portfolio_phase0.sql`: 34 read-only statements,
every one bounded by a period, a CNPJ list or a LIMIT, no DDL, no temp tables,
no psql meta-commands. It runs with the other diagnostics when `health.yml` is
dispatched with `mode=diagnostics` (`.github/workflows/health.yml:562-587`): one
psql session per file, `default_transaction_read_only = on`, 90 s statement
timeout, results in the job log. The `api.*` calls sit last (Q15c, Q16) because a
22023 refusal aborts the file under `ON_ERROR_STOP`. The file was applied to a
throwaway PostgreSQL 16 cluster with `schema.sql`, the 63 migrations and the 30
analytical files, as CI's `sql-compile` job does: 34 result sets, no error. Live
timing on production volumes was not run as a file; §4 ran the same queries one
by one.

| Id | Measures | Brief item |
| --- | --- | --- |
| Q1 | `pg_trgm` version and schema | 3 |
| Q2, Q3 | renamed funds since 2024; trigram rank of the true fund for the 10 largest | 3 |
| Q4 | XP Bancos quota tie-break | 3 |
| Q5, Q5b | balancete fee flow to % p.a. for 3 funds plus the XP pair; fee-like keys left in `raw` | 4 |
| Q6 | recursive look-through depth for 3 retail FICs, cycle-safe | 5 |
| Q7 to Q7d | restatement pairs by status; pairs changing delinquency or NAV; samples; leaf frequency | 6 |
| Q8 | funds with 60 month-end quotas | 7 |
| Q9 | `cvm_fi_perfil` fill rates | 8 |
| Q10, Q10b | block 4 vs block 6 debentures per month; issuer codes with a listed stem | 9 |
| Q11 | block 6 indexer codes | 14 |
| Q12, Q12b | rating text values; FNET rating reports | 16 |
| Q13 | regulation documents on FNET | 19 |
| Q14 to Q14c | anon and authenticated privileges on tables without RLS; schema USAGE | 20 |
| Q15 to Q15c | PETR4 holders; feeders sharing a master; the candidate FIDCs' restatements | 21 |
| Q16 | screen counts and samples | 17 |
