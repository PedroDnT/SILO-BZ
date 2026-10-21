# Session log

One entry per agent session that the owner asked to log: date (UTC-3), branch, what was done, decisions,
assumptions, and anything touched outside the asked scope. Newest first.

## 2026-10-21 · cclaude/compassionate-turing-hejjp3 · handoff (freeze cleanup, orchestrator runs, dollar futures)

This entry is the handoff for the next Claude session. Read it, then check the live state with `gh api repos/PedroDnT/SILO-BZ/...`
before you trust any line below. Times are UTC-3.

**Owner rules in force.** Development is frozen from 2026-10-18 except data reliability, ingest correctness, cost and build
reduction, security and the `adj_status 'refused'` safeguard. Only P0 and P1 protect an issue. The owner merges every PR that
changes ingest, a gate file or production behavior (no auto-merge). Dollar futures (DOL, WDO) are an explicit owner priority.
Production steps (analytics apply, `deploy_mcp.yml`, a backfill) need the owner's word each time; for the dollar futures he gave it on 2026-10-21.

**Done 2026-10-18 to 2026-10-21.**
- Issue cleanup: 18 issues parked in #990 (closed). #986, #991 and #875 closed (#875: COPY into staging gained 1.1x to 1.3x at pool size 4, numbers on the issue).
- Merged by the orchestrator: #989 (ETF status, #899), #992 (Worker rate limit, #892), #993 (shared fetch helpers, #876), #994 (stop 8 unread tables, #877), #995 (conditional CVM download, #874), #998 (market job time budget, #997), #1001 (DOL and WDO ingest, #999), #1002 (DOL and WDO through the API, #1000), #1003 (this handoff).
- The scheduled daily runs of 10-20 and 10-21 are green. The 10-18 and 10-19 runs were red from a BACEN SGS 432 outage and a B3 price-report outage (HTTP 500 after about 2 minutes per request); the market job then hit its 30-minute limit. The job showed `cancelled` and the GitHub annotation said "exceeded the maximum execution time". #998 bounds it.

**Dollar futures, state at the time of writing (2026-10-21, 11:35).** Part A (#999, ingest, PR #1001) and part B (#1000, `api.future_curve` and `api.future_series` for DI1, DOL and WDO, catalog v76, PR #1002) are merged. The owner said "run the action when ready"; I ran the production steps in this order. Merged, applied, deployed and loaded are four different states:

| Step | State |
|---|---|
| #1001 and #1002 merged | yes |
| SQL applied: `daily_ingest.yml`, `mode=analytics-only`, run 39612323250 | yes, 36 files applied, 0 warnings, 0 failures (`27_api_rates.sql` ok) |
| MCP deployed: `deploy_mcp.yml`, run 39616858547 | yes, "Live contract matches this commit" passed |
| History loaded: `market_backfill.yml`, `b3_price_report`, 2018 to 2026, `max_parallel` 1, run 39617548892 | yes, finished 18:08. 8 of 9 years green; the 2021 job is red on one file, `PR210104` (`ParseError: mismatched tag`), the known malformed file of B8. The run shows `failure` only for that job |

What to do next: read run 39617548892 (one job per year, up to 300 minutes each, 2018 first). When the 2018 job is done, call `future_series` for a DOL ticker of 2018 through the API. When all years are done, call `future_curve('DOL')` (newest session) and `future_curve()` for DI1 (must be unchanged). Nothing has read DOL or WDO rows through the API yet. The backfill reloads DI1 too (idempotent). It holds the `supabase-ingest` group, so the 03:00 daily run waits behind it.
Then: close or update this state table, and consider adding a `coverage()` row for the dollar futures (not done).

**Update 2026-10-21, 18:30 (checked through the Supabase MCP, read-only).** DOL and WDO cover 2018-01-02 to 2026-10-20 with the same session count as DI1 in every year (245 to 251 a year, 200 in 2026). `future_curve('DOL', '2018-03-01')` returns DOLH18 at 3244.9 BRL per USD 1,000; the newest session, 2026-10-20, has DOLX26 and WDOX26 at 5026.324. `future_curve()` for DI1 still returns 44 contracts. 2021-01-04 (malformed file) and 2021-06-10 (empty archive) are missing for every root, as they were for DI1 before. The owner decided on 2026-10-21 to keep that gap and not rerun 2021. Still not done: a `coverage()` row for the dollar futures.

**Facts about the data, so you do not redo the work.**
- DOL, WDO and DDI are in the B3 Price Report (`PR<yymmdd>.zip`) from 2018-01-02 to today. COTAHIST has no futures; its `DOL*` codes are ETFs and a BDR (`DOLA11`, `DOLB11`, `DOLX11`, `DOLL39`).
- `DOLX11` has the shape of a DOL contract (X is the November letter). Part A drops a DOL or WDO ticker whose maturity is before the session month.
- Options on the future (`DOLF27C004000`) are dropped on purpose. DDI is not stored (the cupom curve is `DOC` in `b3_reference_rate`).
- Units (DOL USD 50,000, WDO USD 10,000, BRL per USD 1,000) were reported by the agent from b3.com.br. I did not verify them. The price bound 0 to 100,000 is a sanity bound, not B3's.

**Traps met in this session.**
- Plan mode switches on in the middle of a session. Subagents inherit it, stop, and write a plan. Tell them plan mode is off and resume them with SendMessage.
- A finished subagent can keep sending the same "waiting on background work" notice. Stop it with TaskStop after its hand-back.
- GraphQL, `gh issue` and the search API return 403. Use `gh api repos/PedroDnT/SILO-BZ/...`. A bot assignee cannot be removed through REST; an issue update that sends the full assignee list works.
- A `git push` blocks the whole Bash command when a pre-push hook objects. Run it alone. The README and planning check comes once per branch.
- The open-issue list lags a few seconds after a close. Read it twice.
- A job conclusion `cancelled` can be a timeout. Read `repos/.../check-runs/<job id>/annotations`.
- The B3 host is reachable from the sandbox at times, and serves a file at one hour that returned HTTP 500 the hour before.

**Parked, not planned.** #996 (the price-report fetcher fails on B3 holidays while the rates fetcher skips them). Tolerating BACEN's XHTML page for a few days. A per-slice hash to skip unchanged rows before sending them (the idea left from #875). DDI and options on the dollar future. The lookback still re-requests weekdays already stored. `scripts/verify_pipeline.py` still reads `cvm_securit_mensal`.

**Left on the sandbox disk (not in the repo).** Agent worktrees under `.claude/worktrees/`, a benchmark Postgres data directory at `/var/tmp/pgdata_875` (port 5433) and a scratch cluster at `/tmp/pgscratch`. Remove them when you want the space back.

**Not verified by me.** Any SQL against the live database (the Supabase connection was not authorized in this session), the DOL and WDO units, and the 2018 backfill path.

## 2026-10-09 · codex/mrv-april-source-forensics · issuer workbook validation

**Done.** The owner supplied OPEA's `Memória de Cálculo.xlsx` from the issuer page for 24I1980390. The daily
series-1 schedule identifies the 15/04/2026 interest payment as R$77.89949 per certificate, R$41,962,040.37881
total over 538,669 certificates, with zero amortization. It also reports R$42,697,819.13929 interest on 15/10/2025.

Using the workbook's last-business-day residual PU observations for the 12 monthly intervals 2025-08-31 through
2026-08-31, and those issuer-filed flows divided by quantity, method A compounds to 16.103173%. BACEN SGS 12
compounds to 14.630634% over 252 daily rates; the resulting return is 110.0648% of CDI. This passes the MRV
acceptance sanity check. The production function remains unevaluated because the workbook flow is not in
`cvm_securit_serie` or consumed by the RPC; no production data or migration changed. Detailed provenance, monthly
method, and workbook hash are in `docs/reference/research/portfolio-return-coverage.md`; issue #798 remains open for
the source-to-warehouse path.

## 2026-10-09 · codex/mrv-april-source-forensics · source reconciliation

**Done.** Investigated issue #798 using read-only production records and the original 2026 CRI monthly ZIP. The
source class member confirms two senior series share one certificate identifier: series 1 maps to CETIP 24I1980390;
series 2 maps to 24I1980417. `Total_Integralizado` values for those tranches swap in April and May while the series
identifiers, quantities, and per-series PUs remain attached to their rows. Per-series `Rendimentos` and `Amortizacoes`
remain zero.

The separate flow member records R$46,257,835.20 senior interest in April but has only the shared certificate id and
class, with no CETIP/ISIN/series attribution. Applying the aggregate amount to 24I1980390 would imply +1.9014% for
April (~174.29% CDI using 20 SGS 12 daily rates), not the filed 110% CDI. Do not allocate this flow or infer a coupon
from `Total_Integralizado`; the MRV 12-month return stays unevaluated. Evidence and the source ZIP/member names are
in `docs/reference/research/portfolio-return-coverage.md` and issue #798. No production data or calculation changed.

## 2026-10-09 · codex/portfolio-credit-prod-verification · production validation

**Done.** Owner deferred B's PU-fall cutoff to issue #797 (“ship what can be shipped now”) and explicitly authorized
the production apply. PR #784 had already been merged externally. Dispatched `Daily CVM Ingest` in `analytics-only`
mode (run #37963283293): schema/migrations succeeded; all 32 analytical SQL files applied with 0 warnings and 0
failures; data-ingest, source-refresh and dashboard-publish steps were skipped. The standard bootstrap also ran the
existing migration 34 repair, which populated `cvm_fip_periodic.classe_cota` on 18,301 rows. No return cutoff was set.

**Production API.** Catalog v73 is live and both return RPCs are granted to `anon`. Read-only PostgREST calls returned
HTTP 200 (78 A rows for six CRA/CRI codes; 26 B rows for two debenture tickers), confirming the exposed API schema
recognized both signatures. Only CRA0250018H evaluated: 14.54413%, 99.3817% of CDI (252 SGS 12 rates; 14.634610%).
24I1980390 remains unknown at April 2026 (−6.11%, no filed interest/amortization). B remains unevaluated where PU
falls because the cutoff is NULL: CUTI11 has falls in Dec 2025, Mar 2026 and Jun 2026; ENAT11 in Dec 2025 and Jun
2026. The full row-level flags, source-month counts and monthly fund-count ranges are in
`docs/reference/research/portfolio-return-coverage.md`.

**Issues and evidence.** Opened owner-decision issue #797 for the cutoff and data-quality issue #798 for the MRV source
gap; both are linked to #766. Added the production outcome to #766 and PR #784's discussion. No dashboard publish or
manual ingest was triggered. Production execution was through the repository workflow, not local credentials.

**Outside scope.** No engine/container deployment, no change to the cutoff, no fabricated source flow, and no merge
action was performed in this session.

## 2026-10-09 · research/equity-vs-ibov (#786)

**Done.** Study 2 after #776: equity funds against the Ibovespa, read-only, run 12:03 UTC-3 (15:03 UTC). Ibovespa from
`b3_index_level` (IBOV, no divisor step since 1997); declared benchmark from `cvm_registro_classe.raw`
`Indicador_Desempenho`. 12 months: 620 funds, Ibovespa 27.42%, median fund 16.40%, median −11.03 p.p., holder-weighted
−7.05 p.p., PL-weighted −5.06 p.p. 36 and 60 months, annualized: medians −3.96 and −4.14 p.p. Offline test with a
synthetic fund and index; three largest funds checked by hand.

**Decisions.** Same rules as the CDI study for class, quota, holders and FICs. New, written in the document: the main
classes, the excluded groups (the owner's five plus Mono Ação, Fundos Fechados and FMP-FGTS), the p.p. metric,
annualization of both sides, the PL weighting and the closed-fund count.

**Owner decisions, 2026-10-09.** IBrX stays out of the main number; the 12-month window goes to the site; long-short gets no separate number.

**Outside scope.** None.
## 2026-10-09 · codex/portfolio-credit-mrv-stop · resumed

**Done.** Continued PR #784 after the owner asked to follow the plan despite the MRV acceptance case. Added method B
as `api.portfolio_debenture_returns`: one bounded call, exact ticker from CDA block 4, monthly median of fund PU,
minimum three funds, and no synthetic coupon/amortization. The owner deferred B's monthly fall cutoff, so the engine
passes NULL and any PU decline makes the window unknown (`limite_pendente`). C's 12-month contracted figure now joins
the same report table as A/B with an explicit method label, while remaining outside measured coverage and totals. The
BTG PDF rate reader was already verified in the prior run and remains the gate for C.

**Production check.** The previously rechecked production warehouse is current through 2026-08 for these sources.
Existing A RPC rows and read-only CDA source queries for all eight requested tickers are summarized in
`docs/reference/research/portfolio-return-coverage.md`. Production does not yet have the new B RPC; no migration or
DDL was run there. Therefore B is production-source checked, not production-function checked. The MRV 24I1980390
acceptance gate remains failed: April 2026 has a −6.11% PU fall and no filed cash flow; the API correctly keeps its
12-month return unknown. Per the owner's explicit instruction, implementation continued and the case is carried into
PR #784.

**Verification.** Local ephemeral PostgreSQL applied the analytical SQL and passed
`tests/sql/portfolio_behaviour.sql`, including B's 3-fund median, possible-event fall, pending NULL cutoff, missing
month, and A's changing-quantity/missing-month cases. The full offline suite passed (4,273 passed, 25 skipped); focused portfolio, contract, MCP and OpenAPI tests also passed. The report built with `--provider fake`; its return table has method, return, CDI, p.p. gap and % CDI columns.
OpenAPI, MCP contract and SDK contract were regenerated from the ephemeral catalog.

**Decisions.** B cutoff remains unset pending the owner; 1.9% is documented only as a possible follow-up candidate
because it catches the smallest observed ENAT11 event fall (−1.91%) while ordinary non-event marks can fall further.
Owner, 2026-10-09: show C in the same table as A/B, clearly marked contracted. The measured result remains separate.

**Coverage.** The measured result is 10.6523% of portfolio value (8.06% before, plus the 2.59 percentage points of
Marfrig A); B adds no measured coverage with NULL cutoff. C adds 18.4279% as a separate contracted share. The
planning estimate of about 30% evaluated by A+B is not met; this check shows 10.65% measured and 18.43% contracted.

**Outside scope.** No production migration, deployment, merge, or PR comment. The first test attempt found a fixture
fund-id mapping error; corrected and reran successfully. Existing unrelated local configuration in the main checkout
was preserved.

## 2026-10-09 · codex/portfolio-credit-mrv-stop

**Done.** Rechecked the live warehouse with read-only PostgreSQL (`transaction_read_only=on`). The production
`api.portfolio_credit_returns` response for MRV 24I1980390, ending 2026-08, still flags 2026-04
`queda_sem_evento_arquivado`: PU 1,071.48630 to 1,005.98531 (−6.11%), with no filed interest or amortization.
All 13 requested month-ends exist, but the guarded 12-month return is unknown. Per the brief's explicit stop
condition, implementation did not proceed. Source coverage was checked: the six CRA/CRI codes have rows through
2026-08 (CRA0260025T has four months); CUTI11 and ENAT11 each have 13 months through 2026-08, held by 91 and
210 distinct funds respectively.

**Decisions.** None. B's PU-drop threshold and C's placement were not decided or changed; no production migration
was run.

**Assumptions.** The 2026-10-08 report uses the 2026-08-31 portfolio snapshot, consistent with the tested
2025-08..2026-08 window. No new position weights or report generation were inferred.

**Outside scope.** Tests for B/C, the eight-paper run, and the fake-provider report were not run because method A's
acceptance gate failed and the brief says to stop at that point.

## 2026-10-08 · research/cdi-holder-gap (#776)

**Done.** Saved the CDI study the owner asked for: `docs/reference/research/cdi-fund-vs-holder-return.md`, one
read-only SELECT against production at 22:07 UTC-3 (01:07 UTC on 2026-10-09). The owner expected 230 funds, 97.7% and
87.6%. The query gives 231 funds, 97.73% and 87.60%, 1,031,484 holders. The one extra fund returned −77.31% of the CDI
with 1 holder; it is kept, because nothing in its filing marks it as an error. Without it the two figures do not change.

**Decisions.** Universe from the latest extrato's `classe_anbima`, quota on both ends on the same subclass, holders as
filed on 2026-09-30. No interpretation of why the gap exists beyond what was measured (fees were not measured).

**Outside scope.** A one-page site for the owner's company links this document; that work is in another repository.

## 2026-10-08 · claude/credit-return-method-a-c (#772, #766)

**Done.** Built #766 a second time in parallel with #771/#773 (`api.portfolio_credit_curve`, catalog v71). Both had
claimed the issue. On the owner's "resolve", main's build was kept whole (the merge's tree equals main) and the PR
carries only the "% do CDI" footnote fix (no "p.p.."). Measurements of that build (MRV 110.1% of the CDI on a complete
window; the eight papers; C on production CDI and IPCA) agree with main's and are not repeated here.

**Outside scope.** None kept.

## 2026-10-08 · claude/credit-direct-return-build (#766)

**Done.** The build that follows #768 (the measurement and the stop at MRV's test case), after the owner accepted the
two guards: `api.portfolio_credit_returns` (catalog v71, `31_api_portfolio.sql`), engine schema 2.1 (`returns.py`,
new `contracted.py`), the BTG reader keeps 'Data inicial', the Redator no longer receives the `contracted` block (annex only), the report shows A in the body table ("valor na curva";
"n/a" with the reason in #765's one footnote) and C in the annex only. On the real 2026-08-31 statement: measured 12-month coverage 8.06%
to 10.65% (Marfrig CRA, 14.54%, 99.38% of the CDI); contracted return apart, 18.43% (OMNI CDB IPCA + 6,20%: 10.69%;
CDCA 11,87% a.a.: 11.87%).

**Decisions.** Owner, 2026-10-08: guards `queda_sem_evento_arquivado` and `pu_repetido`; then "go with the
recommendations": the `pagamento_incompativel` band stays at 0.5 to 1.5, C stays in the annex only, and method B is
not built on a PU-fall threshold. Taken here and covered by that answer: the third guard `pagamento_acima_do_pu`; the band of `pagamento_incompativel` (0.5 to 1.5 times the line's
month with no payment), proposed from 7,788 payment months after the first real run published CRA02400AYL's 6-month
window at 340% of the CDI; C apart from every measured figure (annex only);
a CRA or CRI on the curve left out of the contribution sum (never mix methods in a total); "% do CDI" for credit from the
rate the statement prints, never the register's `taxa_juros`.

**Assumptions.** C needs the paper to exist for the whole window, so it reads the BTG 'Data inicial' (else the
spreadsheet's `data_aplicacao`). IPCA + s is an approximation (IPCA of the window's months, no lag or anniversary pro
rata), said on the window. The function was tested on a scratch local Postgres (CI's analytical apply, the SQL behaviour
checks, and the production rows of the six codes); it is not applied to production.

**Outside scope.** Method B (debentures): not built, by the owner's decision; section 8 shows no threshold evaluates a
semiannual payer. Register item 20.3 (B3 OTC prices) is the other route, not started. The Supabase MCP did not answer; production reads used `psql` in read-only mode. Seen, not fixed: the
tax block could read the same 'Data inicial' (it reads only `data_aplicacao`). Fixed while merging main: a stray
`||||||| d25f70ee` conflict marker main carried in this file.

## 2026-10-09 · claude/resolve-ambiguous-funds (#783)

**Done.** Register item 20, gap 1 (the owner chose it on 2026-10-09): the two `ambiguo` fund lines of the 2026-08-31
real report, 19,55% of its value. Measured on the live database first, read-only: the proposed fix (the last quota on or
before the date) would have resolved neither line. One line abbreviated the fund type (`FIRF`, `CrPr`), so the real fund
was no candidate; the other had five FIAGRO, which file no daily quota. `api.portfolio_resolve` (catalog v72, same
signature and columns) now adds a name-hint candidate (scored 0.5 at most, ranked behind candidates that scored on
their own unless its quota matches, ambiguous unless its quota matches) and compares a FIAGRO's `cvm_fiagro_mensal` quota
on a month-end date, with a half-cent tolerance.

**Decisions.** A hint only adds names below the 0.25 floor; a score that already counts is never changed (line 14 of the
real report, identified at 0.44, would have flipped to ambiguous otherwise). Every hint candidate reaches the quota
before the cut to 5: the advisor's check on the live names showed nine tied at the cap and the real fund fourth by CNPJ,
which a 2-slot cut dropped. FII is not read (its monthly figure is the patrimonial value, not a price).

**Assumptions.** The monthly informe quota is the month-end quota; supported by one line (0.009% from the statement), not
measured across funds. Token list of `fund_name_core` rests on two observed tokens plus six legal-form abbreviations.

**Outside scope.** Acceptance replayed the report's six fund lines through the old and new resolver on a read-only copy of
production's name history and 2026-08-31 and 2026-08 quotas (local scratch DBs, outside the repository): lines 13 and 17
resolve with `ambiguous` false, lines 14, 15, 16 and 18 unchanged. Not applied to production: run `daily_ingest`
`mode=analytics-only`, then `deploy_mcp.yml`, then resolve the two lines again. Seen, not fixed: `ship-api-change` and
AGENTS.md do not name `scripts/gen_catalog_sql.py`, which `tests/test_api_contract_sql.py` requires after a catalog edit.

## 2026-10-08 · claude/report-v2-trace-audit (#765)

**Done.** Phase 1: the trace of the real report of 2026-10-08 17:25 UTC-3 read through `scripts/trace_view.py`, its
engine JSON, HTML and PDF downloaded outside the repository; causes of problems A to G and the coverage gaps ranked by
share of the portfolio in `docs/reference/research/report-v2-trace-audit.md` (positions by type and share only, no
names: the repository is public). Phase 2, presentation only: page 1 in the reader's order (cost with its coverage of
the portfolio, return coverage, one line per risk row at atenção or moderado, one sentence on what was not assessed),
"% do CDI" as n/a with one footnote, Redator prompt rules 7 and 8 and Revisor rule 9 against restating the risk table,
the two English strings in Portuguese, and a test that fails if an internal word reaches the reader. Phase 3: proposal
in `OPEN_ITEMS.md` item 20, not built.

**Before and after** (`--provider fake`, outside the repository):

| Input | Pages | Words | "a conferir" | "estimativa" | "não avaliad" | Page 2 lines |
| --- | --- | --- | --- | --- | --- | --- |
| Real engine JSON, before | 35 | 13.601 | 56 | 42 | 66 | 46 |
| Real engine JSON, after | 35 | 13.581 | 55 | 42 | 65 | 46 |
| Demo fixture, before | 40 | 14.819 | 60 | 51 | 49 | 43 |
| Demo fixture, after | 40 | 14.861 | 58 | 51 | 49 | 43 |

The real PDF from the run (gpt-5.1) had 37 pages and 13.297 words; the fake writer gives different prose, so the
counts compare only within one input.

**Decisions.**
- Page 1 lists risk rows at atenção or moderado, against the stage-1 choice (#749 era) to keep them in the table only:
  the owner's item 7 asks for one line per finding. At most five lines, then "Mais N"; a row a fixed point already
  states is left out, and so is `movimento_anormal`, whose level is the table-only one.
- The coverage over the portfolio is one division of two engine fields in `adapt.py` (no engine change, nothing summed).
- The Revisor's restatement rule applies only to `riscos` and `resumo`, and runs after the older rules so their
  reasons stay.

**Assumptions.** Problem B (page 2 holding only the disclaimer) does not reproduce with the fake writer; it came from
the real Redator's three long findings on page 1, which no longer print there. Not checked with the paid Redator.

**Outside scope.** `brew install pango` and WeasyPrint in `.venv` to build PDFs locally, removed again at the end.
`test_the_pdf_carries_the_diagrams` fails with WeasyPrint installed, on `main` too; CI does not install WeasyPrint.

## 2026-10-08 · claude/credit-direct-return-cdi (#766)

**Done.** Measurement only, read-only against production; no code, migration, catalog or MCP change. The brief's
acceptance test for method A (MRV's CRI 24I1980390 near 110% of the CDI) failed on the report's window
(2025-08 to 2026-08): 53.0%, because the securitizer did not file the 2026-04 coupon. The brief says to stop there, so
the session stopped and wrote the case in `docs/reference/research/portfolio-return-coverage.md`, section 8: the
formula gives 109.9% to 110.1% on every complete window; guarded A evaluates 1 of 6 CRA/CRI (Marfrig, 99.4%);
B evaluates 0 of 2 debentures at any threshold (two coupon months in every 12-month window); coverage 8.06% to
about 10.65%, not 30%.

**Decisions.** None taken for the owner. Proposed, not built: guards `queda_sem_evento_arquivado`, `pu_repetido`,
`quantidade_mudou`, `mes_ausente`, and a third one for an implausible PU (CRA02500001).

**Assumptions.** The 08/10 report's position date is 2026-08-31 (its CDI, 14.63%, matches that window). The
paper values come from the report PDF on the owner's machine; no client data is in the repo.

**Outside scope.** Seen, not fixed: the report's rates for lines 1 and 2 (CDB "IPCA + 6,20%", NTN-B "IPCA + 7,00%")
may be shifted by one row; check against the PDF. The Supabase MCP did not answer in this session.
## 2026-10-07 · claude/risk-table-fgc-caveat-once (#754)

**Done.** Follow-up to #749, item 3c, `src/portfolio/report/render.py` only. The risk table row `fgc_acima_limite`
printed "a conferir: limite por CPF e instituição" twice: in its `explanation` (`risks.py:92`) and in its `check_label`
(`concentration.fgc.label`). The renderer now leaves the explanation's "a conferir" clause out when the row's
`check_label` already carries it word for word. Demo: "a conferir" 67 to 65 in the HTML (the compact and the full risk
table).

**Decisions.** Fixed in the renderer, not in `risks.py`, because the task forbids engine changes. A clause the label does
not carry stays: `credito_sem_fgc` keeps its conglomerado caveat.

**Outside scope.** None.

## 2026-10-07 · claude/report-presentation-fixes (#749)

**Done.** Three presentation fixes in the diagnosis report, `src/portfolio/report/` only.

1. Body table "Retorno passado contra o CDI": a "% do CDI" column of its own, read from
   `returns.lines[i].windows[j].pct_of_cdi`. Where the engine did not compute it, the column shows the fixed text of
   `pct_of_cdi_reason_code` (`common.REASON_TEXT`), also for a share or an FII. The difference stays in p.p.
2. Fee headline and page-1 "Custo": the disclosed fixed fee and the disclosed range side by side, same weight, each
   with its coverage of the fund value (`fees.summary.coverage_fixed_fund_value_pct`,
   `coverage_range_fund_value_pct`). The fake Redator's page-1 cost finding and the prompt's `resumo` item say the same.
3. Page 1 "Pontos a conferir": restatements grouped per fund (one point, each competência with its field count);
   a missing `n_fields_changed` reads "número de campos não disponível"; the FGC caveat once per Redator finding.

**Decisions.**
- No total of fixed fee plus range: `engine-output.md` says `fees.summary` carries none, so none is shown.
- 3a's example says "n/d" and 3b says "número de campos não disponível"; the explicit 3b wording is used.
- Restatements are grouped by statement line (`line_id`), not by fund name, which the view can lack.
- FGC repetition cause: the prompt asked for "a conferir" *with* `concentration.fgc.label` (which already starts with
  "a conferir"), and the risk row adds `explanation` and `check_label`, both with the same caveat. Fixed in the
  Redator prompt and in the fake writer's title. `risks.py` (engine) was not changed.

**Assumptions.** The prompt change was checked only with `--provider fake`; no live model call was made.

**Outside scope.** None in code. Local machine: `pango` was installed with Homebrew so WeasyPrint could build the PDF.
Seen, not fixed: the risk table's FGC row prints the caveat twice (its `check_label` and its `explanation`), which
needs an engine text change in `risks.py`.
