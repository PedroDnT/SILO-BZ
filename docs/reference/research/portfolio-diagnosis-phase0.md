# Portfolio diagnosis demo, phase 0: what SILO has, what is missing, what Sunday can hold

Phase 0 of the portfolio-diagnosis demo (design: `docs/planning/PORTFOLIO_DIAGNOSIS.md`;
original map #340). Read-only research done on 2026-10-02 from 19:00 UTC-3 (22:00 UTC) to
2026-10-03 about 01:30 UTC-3 (04:30 UTC), on commit `cc3ab2a` (the merge of #504). No code, no
migration, no DDL, no write to the database. Every claim below carries its
evidence (`path:lines`, a ticket, a URL with its access date) or is marked
**not measured**. The cloud session that wrote this could not reach Supabase,
dados.cvm.gov.br, FNET or tesourotransparente.gov.br (the egress proxy refused
every CONNECT), so no live SQL ran. The SQL that would have run is §12 and
`scripts/health_diagnostics/19_portfolio_phase0.sql`, ready for the owner. Near
the end of the session a third-party fetch service (Firecrawl) became available
and read four public pages the proxy had refused: CVM's CDA and lâmina dataset
pages, `meta_cad_fi.txt`, and the Tesouro Direto dataset page with its metadata
PDF. Those reads are dated 2026-10-03 (UTC-3) below.

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
2. **Nothing was measured live.** Items 3 to 9, 15, 16, 19, 20 and 21 of the
   brief need SQL against production; this session had no path to the database
   (§4). The queries are written and bounded (§12). The owner can run them in the
   Supabase MCP, or dispatch `health.yml` with `mode=diagnostics` on this branch
   and read the job log (`.github/workflows/health.yml:562-587`).
3. **The Sunday scope as decided does not fit one day.** Seven full blocks plus
   two minimal ones plus upload and PDF, with no engine code yet and the
   measurements still to run, is two to three days of work. Recommended Sunday
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
means the data is absent. Nothing here was run against the database in this
session; every status is a reading of the SQL and the schema. The Sunday column
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
| 7 | Warnings (private credit, liquidity, concentration) | partial | `cvm_fi_perfil` types `pr_ativo_cred_priv`, `nr_dia_cinqu_perc`, `nr_dia_cem_perc`, `st_liqdez`, `pr_patrim_liq_convtd_caixa` (`src/store/schema.sql:1031-1097`). Whether any `api` function exposes them: not verified this session | no; fill rates not measured |
| 8 | Regulation terms | missing | No lâmina dataset (`src/fetchers/cvm_config.py:38-166`). `fnet_document` holds metadata only, no bodies and no URL column; download is `downloadDocumento?id=<fnet_id>` at 1 req/s (`src/fetchers/fnet_fetcher.py:223-258`, `:108-117`). CVM publishes `lamina_fi_YYYYMM.zip` monthly since 2019-01 (<https://dados.cvm.gov.br/dataset/fi-doc-lamina>, columns not verified) | no; a new ingest |
| 9 | Private credit by issuer | partial | `api.fund_debentures` serves block 6 with `cpf_cnpj_emissor` and `issuer_tickers` (`19_api_contract.sql:2252-2378`). Block 4 files most fund debentures under `tp_aplic = 'Debêntures'` with no issuer CNPJ (R$788.9bn vs R$34.4bn on 2026-05, `src/store/analytical/30_fund_holdings.sql`); its issuer is ISIN chars 3–6 only. Set issuer resolution does not exist (#342–#344 closed not planned) | no; needs issuer resolution across blocks 4 and 6 |
| 10 | Exposure by indexer | partial | `fund_debentures.indexer` = `cd_indexador_posfx`, block 6 only. Block 1 has `tp_titpub` (`cvm_fi_cda`); block 4 has no indexer column. `cvm_securit_serie.taxas_indexadores` exists in the schema but is not in the field map (`src/parsers/field_maps/securit_serie.py:31-55`), so nothing writes it | yes; a versioned rules table over `tp_titpub`, `cd_indexador_posfx` and `tp_aplic` |
| 11 | Exposure by sector | partial | `cia_company.setor`; `dim_ticker_float.b3_sector` (view, `src/store/analytical/20_short_interest.sql:135-266`); `cvm_fii_periodic.segmento_atuacao`; `cvm_etf_registry.segment` (8 seed values); `cvm_fidc_setor` (32 sector columns). No function joins holdings to a sector | yes; a join from block 4 `cd_ativo` to `dim_ticker_float.b3_sector` |
| 12 | Correlation | partial | Same inputs as block 5: quota series in `api.fund_nav`, no monthly-returns function, no Tesouro price table | no; depends on block 5 |
| 13 | Rating and history | partial | `cvm_securit_serie.classificacao_risco_atual` is text with no agency column; FNET rating reports are metadata rows in `fnet_document` (no bodies). External: Austin Rating "Ratings Explorer" (<https://austin.com.br/Ratings-Explorer.html>), terms not read | minimal; show the stored text and the FNET document count, no history |
| 14 | Fund risk signals | ready | 10 `api.screen_*` wrappers (`src/store/analytical/23_api_screens.sql`, `25_api_filing_screens.sql`), each refuses above 1,000 rows, none accepts a CNPJ filter. Thresholds in `src/store/analytical/15_fraud_screens.sql`; dormant rule = 3 complete months with flows exactly 0, NULL disqualifies (`15_fraud_screens.sql:241-280`). Dashboard prose and SQL disagree in 3 places (evergreen strict `>70`, overdue 4 statuses, captive no minimum count) | yes; fetch each screen and join by CNPJ client-side, or add `p_cnpj[]` |

## 3. Coverage matrix

What SILO can say about a statement line, at two levels: the line itself
("Direct position") and the same asset held through a fund ("Inside funds",
from the CVM CDA). Values are covered, partial or unknown. "unknown" covers two
different things, said in the reason: a source that is not ingested, and a
source that was not verified in this session. No row was checked against the
database.

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

Nothing in this table was measured in this session. The right-hand column names
the query in §12 that measures it; run it before the Sunday build.

| Brief item | Measurement | Result | Query |
| ---------- | ---------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| 3 | `pg_trgm` installed | **not measured**. In the repo: `CREATE EXTENSION IF NOT EXISTS pg_trgm` in `src/store/migrations/24_lookup_trgm.sql:14`; GIN trigram index on `dim_fund.fund_name` at `src/store/analytical/01_dim_fund.sql:89`; no function calls `similarity()` (five tests assert its absence) | Q1 |
| 3 | 10 large funds renamed since 2024: rank-1 hits and ambiguous matches by name similarity against `cvm_fi_cda_fund_name` | **not measured** | Q2, Q3 |
| 3 | XP Bancos pair tie-break by quota (master 35.377.390/0001-06, FIC 50.088.190/0001-19) | **not measured** | Q4 |
| 4 | Balancete fee accruals converted to % per year for 3 funds, against the disclosed fee, error in p.p. | **not measured**. Method: `vl_taxa_administracao` is accumulated from each fund's fiscal-year start and negative (`src/store/migrations/59_fi_balancete_resumo.sql:3-50`), so the monthly flow is this month minus last month, times 12, over the NAV (`vl_patrimonio_sem_resultado + vl_receitas + vl_despesas`, migration 61). The disclosed fee exists only as `cvm_fund_registry.raw->>'TAXA_ADM'` (legacy `cad_fi`, possibly overwritten by the CVM-175 registry; `src/pipeline/ingest_misc.py:177-185`) and typed only for ETFs (`cvm_etf_registry.taxa_adm`, `src/pipeline/ingest_etf.py:35-46`). CVM's `cad_fi` carries `TAXA_ADM` and `TAXA_PERFM` as numbers, `INF_TAXA_ADM` and `INF_TAXA_PERFM` as 400-character text, and `DT_INI_EXERC` / `DT_FIM_EXERC`, the fund's fiscal year, which is the reset month the balancete flow needs (`meta_cad_fi.txt`, read 2026-10-03 UTC-3; none of these is in the field map, `src/parsers/field_maps/fund_registry.py:13-38`) | Q5 |
| 5 | Levels of fund quotas under 3 retail FICs | **not measured** | Q6 |
| 6 | 2026 FIDC restatements with a compared diff; which changed delinquency or NAV | **not measured**. Documented earlier: the 2026-09-25 spike found ALDEBARAN II FIDC's 2026-08 RE moving delinquency from 0.00 to 127,092,378.18 and NAV from 1,498.3M to 1,457.6M (`docs/planning/DOCUMENTS.md:176`) | Q7 |
| 7 | Funds with 60 months of month-end quota | **not measured** | Q8 |
| 7 | NTN-B: what is missing | No price table exists (grep for `tesouro`, `NTN` in `src/store/`: only fund holdings in `cvm_fi_cda`, the DPL curve in `b3_reference_rate`, DAP futures). Block 1 gives a derived unit price per fund (`vl_merc_pos_final / qt_pos_final`), never a published one. The public source exists: Tesouro Transparente's `precotaxatesourodireto.csv` (13.8 MiB on 2026-10-02), daily since December 2004 per its metadata PDF (the dataset page says January 2002), columns Tipo Título, Data Vencimento, Data Base, Taxa Compra Manhã, Taxa Venda Manhã, PU Compra Manhã, PU Venda Manhã, PU Base Manhã; PU Base is the mark-to-market price (<https://www.tesourotransparente.gov.br/ckan/dataset/taxas-dos-titulos-ofertados-pelo-tesouro-direto>, read 2026-10-03 UTC-3) | — |
| 8 | Fill of `pr_ativo_cred_priv` and the liquidity fields in `cvm_fi_perfil` | **not measured**. Columns exist: `pr_ativo_cred_priv`, `nr_dia_cinqu_perc`, `nr_dia_cem_perc`, `st_liqdez`, `pr_patrim_liq_convtd_caixa` (`src/store/schema.sql:1031-1097`) | Q9 |
| 9 | Block 4 vs block 6 debentures month by month since 2025; share resolvable to an issuer; share with a listed issuer | **not measured**. Measured earlier by the matview build: block 4 R$788.9bn vs block 6 R$34.4bn on 2026-05 (`src/store/analytical/30_fund_holdings.sql:18-22`). The brief's 2026-08 figures (R$264.3bn / R$9.5bn) are from the brief, not re-measured here; they are consistent with CVM filing recent months thin and completing them late (#476, CHANGELOG 2026-10-02) | Q10 |
| 14 | Block 6 indexer values | **not measured**. The schema comment lists `'DI1', 'IPCA', …` (`src/store/schema.sql:314`); tests use `DI1` / `DI de um dia` | Q11 |
| 16 | `classificacao_risco_atual` values that become a valid grade with agency and scale | **not measured**. The brief's 283 distinct values in 74,424 rows is from the brief. No agency column exists; `taxas_indexadores` is in the schema but not in the field map, so nothing writes it (`src/parsers/field_maps/securit_serie.py:31-55`) | Q12 |
| 19 | Regulation documents in `fnet_document` for the candidates; 2 sample downloads | **not measured, not downloaded** (FNET unreachable from this session) | Q13 |
| 20 | Whether any of the 39 tables without RLS is on the anon read path | **not measured live**. In the repo the boundary is the GRANT sweep, not RLS: anon has USAGE only on schema `api` (`src/store/analytical/19_api_contract.sql:62`) and every `public` landing object is REVOKEd on each apply (`src/store/analytical/12_grants_and_rls.sql:118-199`); RLS is a hand-applied defence-in-depth script (`docs/reference/security/enable_rls.sql`). If the sweep ran, RLS off changes nothing for anon. Q14 confirms with `has_table_privilege` | Q14 |
| 21 | Demo portfolio positions | candidates only (§6) | Q15 |
| 17 | What each `api.screen_*` returns | from code (§2): 10 wrappers, one page cap, none takes a CNPJ | Q16 |

Numbers that are measured and dated elsewhere in the repo, reused here as
evidence: dormant funds 61 empty shells and 8,257 parked out of 25,974 filing
(`src/store/analytical/15_fraud_screens.sql:208-209`); FIDC restated documents
608 in the 23 delivery days of 2026-09, about 14% of monthly filings
(`docs/planning/DOCUMENTS.md:197-210`); CDA 2026-06 held 7,375 funds in block 1
against 11,860 in CVM's current zip (CHANGELOG 2026-10-02, #476).

## 5. Blockers

| Blocker | Why it blocks | Ticket / owner |
| ----------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| No database access from this cloud session (proxy refuses Supabase, CVM, FNET, Tesouro) | every live measurement; the SQL pack exists but did not run | owner runs §12, or dispatches `health.yml mode=diagnostics` on this branch |
| No set-based `api` functions (look-through, issuer set, returns) | blocks 2, 5, 6, 9, 12 need them; blocks 1 and 3 need two new functions | #342, #343, #344 closed; new tickets under the demo label (§9 decision 6) |
| No fee reader | block 3 | new function over `cvm_fi_balancete_resumo` |
| `api.screen_*` take no CNPJ filter | block 14 must fetch each screen whole (one page cap) and join client-side, or new wrappers get a `p_cnpj text[]` | `src/store/analytical/23_api_screens.sql`, `25_*.sql` |
| No Tesouro price series | NTN-B direct position has value from the statement only; blocks 5, 6, 12 partial for it | #341 closed; candidate source in §7.3 |
| Sample BTG statement not in the repo; no statement reader or CPF masking code exists | slice 1 | owner |
| Label `demo-diagnostico` missing | PR labelling | created with this PR if the API allowed it; otherwise owner |
| `silo-cvm-data-analyst` skill is stale (says the warehouse is mostly empty as of 2026-06) | an agent that trusts it will under-use the data | refresh in the week |

## 6. Demo portfolio (candidates)

Eight positions, each chosen so one finding of the diagnosis is planted in the
statement and can be confirmed by one query of the SQL pack. No candidate was
checked against the database in this session; the status says so. SQL ids refer
to the pack (`scripts/health_diagnostics/19_portfolio_phase0.sql`).

| # | Position (candidate) | Planted finding | How it is confirmed (SQL id) | Status |
| --- | --------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| 1 | NTN-B 2035, held directly | A Tesouro line SILO identifies but cannot price: no price series in SILO, labelled partial in the report | Schema inspection; no query possible (no Tesouro price table; #341 closed). Block 1 label match by `tp_titpub` and `dt_venc` only | candidate, to confirm |
| 2 | PETR4, held directly | Shared exposure: the same stock appears directly and inside a fund | Q15a (largest FIA positions in PETR4 from block 4, `cd_ativo = 'PETR4'`) | candidate, to confirm |
| 3 | A large FIA holding PETR4 | Second leg of the shared exposure in row 2; look-through one level | Q15a | candidate, to confirm |
| 4 | XP Bancos master 35.377.390/0001-06 and FIC 50.088.190/0001-19 | Ambiguous name pair: two funds, one name; the quota series breaks the tie | Q4 (quota tie-break between the two CNPJs) | candidate, to confirm |
| 5 | ALDEBARAN II FIDC 57833038000162 (alternate: FARMERS FIRST I FIDC 45829761000199) | Material restatement: 2026-08 RE (FNET 1319446 AP → 1319631 RE) moved delinquency from 0 to R$127,092,378.18 and PL from R$1,498.3M to R$1,457.6M, 37 leaves (`docs/planning/DOCUMENTS.md:81`, `:176`). Alternate: FARMERS FIRST I 2026-07 RE removed amortizations (`DOCUMENTS.md:21`, `:82`) | Q15c (2026 FIDC pairs `compared`, diffs on delinquency and PL leaves) | documented in repo (2026-09-25 spike), to re-confirm live |
| 6 | Two feeders of one master | Overlap: two statement lines resolve to the same underlying portfolio through block 2 | Q15b (feeders sharing a `cnpj_cota`) | candidate, to confirm |
| 7 | A renamed fund | Identification: the statement name differs from `dim_fund.fund_name`; `cvm_fi_cda_fund_name` shows the change | Q2 (renamed funds since 2024), Q3 (similarity rank) | candidate, to confirm |
| 8 | One fixed-income ETF or one FII | Breadth for the indexer and sector tables: a non-FI quota with a segment | Q10 (block 6 indexer values), Q11 (sector breadth) | candidate, to confirm |

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

- Every live count in §4: the database was unreachable.
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
- RLS state on production, and whether the GRANT sweep ran on the last apply.
- Whether `git push` from a cloud session creates the `demo-diagnostico` label
  on first use.

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
