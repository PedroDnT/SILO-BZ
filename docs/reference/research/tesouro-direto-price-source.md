# Tesouro Direto price file: what it covers for the diagnosis

Issue #802, register item 20 gap 2. Measured 2026-10-09 on the public file, before any build. The
repository is public and a portfolio can identify a person (ADR 0003), so the two Tesouro titles of the
08/10 report (9,07% of the portfolio) are named by type and share only.

## Answer

The file gives a mark for one of the two titles and none for the other, and the one it covers pays
coupons. Built as proposed, gap 2 would move this portfolio's coverage by **0 of the 9,07%**, unless
the owner accepts a coupon computation (question 3). The file does fit the common Tesouro Direto
holder, whose titles pay no coupon.

## The source

| Item | Value |
| --- | --- |
| Publisher, dataset | Tesouro Transparente, ["Taxas dos Títulos Ofertados pelo Tesouro Direto"](https://www.tesourotransparente.gov.br/ckan/dataset/taxas-dos-titulos-ofertados-pelo-tesouro-direto) |
| File | One CSV, 14,6 MB, `;` separator and `,` decimal, refreshed daily. 177.202 rows from 2004-12-31 to 2026-10-08, eight title types |
| Licence | ODbL (Open Data Commons) |
| Columns | title type, maturity, base date, buy and sell rate, `PU Compra`, `PU Venda`, `PU Base` (all "Manhã") |
| The price to use | `PU Base Manhã`: per the [metadata sheet](https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/resource/1a8eb2e3-4902-4a38-a1eb-6410f23d90de/download/taxa.pdf), the price at the sell rate with same-day settlement, used "to mark to market the titles bought through Tesouro Direto". Empty on some recent rows |
| Revisions | The sheet states that values "may be revised" when the primary database changes. A stored copy would have to be refreshed in full, not appended |
| What it is | The Treasury's posted morning quote on its retail platform, not a trade |

## Coverage of the report's two titles

| Title (type, share) | In the file? | Month-ends of the window with a `PU Base` |
| --- | --- | --- |
| NTN-B, long maturity (5,78%) | Yes, as "Tesouro IPCA+ com Juros Semestrais" | 13 of 13 (2025-08 to 2026-08) |
| LTN, July maturity (3,29%) | **No.** The file has no row for that maturity. The Prefixado titles on offer now mature on 01-01; July maturities appear only for older titles | none |

The LTN is an institutional-market title. Its mark needs another source, which is not checked here.

## Why the covered title still has no return

- Its price over the window moves from 4.000,12 to 4.125,60 (+3,1%), but the title pays semiannual
  coupons, which the file does not carry: the price-only change leaves them out. Same shape as #774.
- The coupon months follow from the maturity, but the amount of an NTN-B coupon is a share of the
  nominal value updated by the IPCA, and the file has no nominal value. Recovering it means inverting
  the Treasury's quotation formula: exact, but a computation, and ADR 0004 and #605 ("no number from a
  model") make that the owner's call.
- A coupon-free title (Tesouro Selic, Prefixado, or IPCA+ without semiannual interest) needs none of
  this: its price change is the whole return.

## Decisions for the owner

1. **Licence.** ODbL asks for attribution, and for a database derived from it and used publicly to be
   offered under the same licence. Serving the series through `api` may count. I have not decided it:
   serve only a derived return, or the series, or neither?
2. **A posted quote as a mark.** The policy ranks observed trades above synthetic marks (ADR 0004). This
   is the Treasury's own executable quote, not a trade and not an indicative model. Accept it?
3. **Coupon titles.** Compute the NTN-B (and NTN-F) coupon from the title's published rules, or keep
   them "não avaliado"? Only "compute" gives this portfolio 5,78%.

## Recommendation

Do not build for this portfolio: it gains nothing without question 3, and the LTN stays out either way.
If the product should serve Tesouro Direto holders, a small build covers the coupon-free titles exactly
(one full refresh a day, one table, one `api` read); that is a product choice, not a fix for this report.
A build would sit on the contract files #796 is changing, so no `api.*` code is written until it merges.

Nothing here changes the engine, the report or a stored value.
