# Report v2: audit of the 2026-10-08 real report through its trace

Issue #765. The owner read the report of a real run and found it poor. This note gives the cause of
each problem from the run's trace, ranks the coverage gaps by share of the portfolio, and lists what
would close each gap. Phase 2 of #765 fixes the presentation. Phase 3 is a proposal in
`docs/planning/OPEN_ITEMS.md`.

The repository is public, and a portfolio can identify a person (ADR 0003). So this note names
positions only by type and share of the portfolio: no issuer or fund name and no R$ per line. The
trace, the engine JSON, the HTML and the PDF stay outside the repository.

## The run

| Item | Value |
| --- | --- |
| Trace | `traces/2026/10/08/374012432d6c69b86d9b6a419a849b30.json` |
| Started | 2026-10-08 17:24:50 UTC-3 (20:24:50 UTC), HTTP 200, 533,6 s, US$ 0,52 |
| Engine | rev `e7e3a28b103b`, schema 2.0 |
| Portfolio | R$ 1,1 milhão, 21 positions (BTG performance PDF): 17 identified, 2 ambiguous, 2 unknown |
| Report | 37 pages, 13.297 words; "a conferir" 50 times, "estimativa" 33, "não avaliad" 24 |
| Redator | gpt-5.1, 1 call, 63.749 tokens in, 17.428 out (13.677 reasoning), US$ 0,254, 19 findings kept |
| Revisor | gpt-5.1, 1 call, 74.019 tokens in, 6.658 out, US$ 0,159, 7 removals |
| Investigator | 0 calls, US$ 0,106 booked |

Section status: `allocation`, `concentration`, `indexer`, `sector` and `risk_signals` complete;
`restatements` not applicable (no FIDC or FII line resolved); every other section partial.

Revisor removals: 4 by its LLM pass (3 in `identificacao`, 1 in `exposicao`), 1 whole finding in
`taxas` for a source outside the provenance, and 1 in `sinais_de_risco` (a part, then the whole
finding when no sentence was left).

## Cause of each problem

| # | Problem | Cause | Where |
| --- | --- | --- | --- |
| A | Page 1 says no screen found a point to check, then prints 3 bold findings at "atenção" | Render. `_points_to_check` looks only at FGC issuers above the limit, restated reports and strong movement. None fired, so the fixed sentence printed. The Redator's `resumo` findings follow it, and prompt rule 7 tells the Redator to put the risks at "atenção" first. The risk table had 4 rows at "atenção" and 1 at "moderado". | `render._resumo`, `redator.SYSTEM_PROMPT` rule 7 |
| B | Page 2 holds only the disclaimer line | Render (print CSS and content). `.brief { break-after: page }` forces a break after page 1. Page 1 was one line too long, mostly because of the 3 Redator findings (about 14 lines, one a run-on sentence), so the last line moved to page 2 and the forced break followed. | `report.css`, `render._resumo` |
| C | "R$ 367,78 por ano, 0,03% da carteira" reads as the cost | Render. The headline prints the fixed fee as a share of the portfolio but its coverage only as a share of the value in funds (30,85%). Funds, ETFs included, are 22,67% of the portfolio, so the fee covers about 7% of the portfolio. The ETF site fee (R$ 498,11) is apart, as the engine contract requires. The spread inside direct credit (47,97% of the portfolio) is not a published fee: it is in "Não incluído no total", not on page 1. | `render._fee_pair_html`, `render._resumo` |
| D | Return against the CDI covers 2 of 21 positions; the "% do CDI" column repeats a long text | Render for the column: `_returns_summary` prints `pct_of_cdi_reason` in every row where `pct_of_cdi` is null. Both evaluated lines are ETFs, so both get the reason. The low coverage is missing data (G). | `render._returns_summary` |
| E | The Redator restates the risk table in prose; much bold text; the FGC caveat repeated | Redator prompt. Rule 8 asks for up to 3 findings that name each row's risk, value, subject, level and explanation, which is the table row in prose. Rule 7 puts the same rows on page 1. So 3 facts appear 3 times (page 1, table, prose). Each finding title is bold. The Revisor's LLM prompt has no rule against restating a table. | `redator.SYSTEM_PROMPT` rules 7 and 8, `revisor.SYSTEM_PROMPT` |
| F | English reaches the reader | Engine strings, printed as they are. `restatements.py:33` writes the assessment "thresholds parked by the owner", which the gaps section prints under "Materialidade das reapresentações". `signals.py:51` writes the dormant-screen note with "screen", "empty_shell" and "parked". | `restatements.py`, `signals.py` |
| G | Low coverage | Missing data in SILO for most gaps, one rule gap (the ambiguous-fund tie-break) and two suspected join gaps. Table below. | engine, SILO |

## Coverage gaps by share of the portfolio

A position can be in more than one row. "Return" is the 12-month return against the CDI.

| # | Positions | Gap and reason code | % of portfolio | What would close it | Kind |
| --- | --- | --- | --- | --- | --- |
| 1 | 6 CRA and CRI | No return: `retorno_credito_sem_serie` | 21,52 | The securitizer's curve in `cvm_securit_serie` (PU = `valor_certificados` / `quantidade_certificados`) gives a return when the filing is complete. #766 measured it on this portfolio: with its guards it evaluates 1 of the 6, because filing gaps break the rest (`portfolio-return-coverage.md` section 8). The owner decides the guards. | Rule over existing data (#766) |
| 2 | 2 funds | Ambiguous identification: `ambiguo` ("a cota não desempatou"). Blocks fee, return, look-through, liquidity and movement for both. | 19,55 | The statement prints no CNPJ, so a CNPJ tie-break does not apply to this layout. `api.portfolio_resolve` compares the quota only on the exact position date; both lines had "no quota filed on 2026-08-31". A tie-break on the last quota on or before that date, or on the quota implied by value and quantity from the "Detalhamento" table (#751), would separate them. **Corrected in #783:** measured on the live database, neither line was a date problem. One abbreviated the fund type, so the real fund was no candidate; the other was five FIAGRO, which file no daily quota. | Rule fix |
| 3 | 1 CDB | Unknown: `bancario_sem_fonte`; no return | 15,45 | SILO has no CDB source (CDA block 5 and bank issuance registries are not ingested). | New data |
| 4 | 4 funds (FII, FIP, 2 multimercado) | No look-through: CDA 2026-04 not filed (`no_cda_filing`) | 14,60 | FII and FIP do not file CDA (7,61). The 2 multimercado funds (6,99) should. To check: whether CDA 2026-04 is incomplete or the CDA is filed under a CVM 175 class CNPJ. | Correction to check |
| 5 | 2 Tesouro titles (NTN-B, LTN) | No return: `retorno_tesouro_sem_serie` | 9,07 | Tesouro Direto price and rate history. Its public file was not checked in this session. | New data |
| 6 | 2 debentures | No return: `retorno_credito_sem_serie` | 8,03 | The median fund mark (CDA block 4) evaluates 0 of the 2 (#766). SILO also captures B3 OTC debenture prices (`b3_credit_observations`, migration 74), with no serving grant and no return series yet. | Rule over existing data |
| 7 | 2 funds (FII, FIP) | No usable fee: `taxa divulgada não encontrada` | 7,61 | FII and FIP are not in the Extrato or the lâmina. | New data |
| 8 | 2 multimercado funds | No return: `serie_incompleta` (9 and 10 of 13 month-ends missing) | 6,99 | To check: why `fund_nav` lacks those months (class CNPJ against fund CNPJ is one candidate). | Correction to check |
| 9 | 1 CDCA | Unknown: `outro_sem_ticker` | 2,98 | No public CDCA registry in SILO. | New data |
| 10 | FII and FIP | No return: `retorno_sem_regra`, `retorno_fip_sem_serie` | 7,61 | FII without a ticker and FIP with no monthly quota in SILO. | New data |

Return coverage: 2 of 21 positions, 8,06% of the portfolio, both ETFs. Fee coverage: the fixed
disclosed fee covers 30,85% of the value in funds, about 7% of the portfolio; the ETF site fee
covers 35,57% of the value in funds.

## Not verified

- Gaps 4 and 8: the class-CNPJ hypothesis was not tested against the database.
- Gap 2: whether a quota on an earlier date exists for both candidates.
- Gap 5: the Tesouro Direto public file and its terms.
- Why the Investigator booked US$ 0,106 with 0 calls.
