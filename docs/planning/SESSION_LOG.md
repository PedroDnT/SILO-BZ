# Session log

One entry per agent session that the owner asked to log: date (UTC-3), branch, what was done, decisions,
assumptions, and anything touched outside the asked scope. Newest first.

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
