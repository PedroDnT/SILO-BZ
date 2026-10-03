# Index candidates after IBOV: what B3's endpoint serves, and what B3 calls it

Build ticket #416, part of epic #410 (spec `docs/planning/RESEARCH_SEAM.md` §5).
Measured and read on 2026-10-03 (UTC-3), between 13:35 and 14:15 (16:35 and 17:15
UTC). Every B3 page, PDF and bulletin below was read through Firecrawl on that
date, except where a line says it is a search-result excerpt: B3's SMLL history
page ("desde janeiro de 2005"), its IFIX history page ("desde dezembro de 2010")
and the Smart Dividends return-type sentence were read as excerpts only, and
Firecrawl served the Ibovespa page from a cache dated 2026-10-01. Every endpoint number comes from three read-only runs of a throwaway
workflow on the branch `research/indices-416` (no secrets, no database, never
merged): run 37138333487 at 13:50 (16:50 UTC), run 37138739075 at 13:57 (16:57
UTC) and run 37138825101 at 13:59 (16:59 UTC), all dispatched from
`lamina_header_probe.yml`, the one dispatch-only workflow main already had. The
probe scripts are in git history of that branch, not here.

## Answer

**No candidate is added to `INDEX_CODES` by this ticket.** The one thing the ticket
asked to check, whether a code is a total-return variant, has an answer that
changes what `index_history` may call its series:

- **B3 says that every candidate, and IBOV itself, is a total-return index.**
  Its own page for each one says so (section 1). The served text says the
  opposite: catalog v45 onwards, the `19_api_contract.sql` and
  `29_api_index.sql` comments, `api-docs/market-coverage.mdx`, the SDK
  docstring and the usage guide call the series "a price index, not total return".
- The values themselves check out: all ten codes return B3's published base
  value on its base date, IBOV, IBXX, IBXL and IFIX also match B3's daily
  bulletin (section 2), and none has a gap against IBOV's sessions except UTIL's
  one transient answer (section 3).
- Adding the codes under the current wording would spread a label that
  the administrator's own methodology contradicts, and the ticket's own rule is
  that a total-return index is recorded as such and kept out of a price series.
  Which way to fix it is the owner's call (section 5). Nothing here changes a
  served function, so there is no catalog bump and no regenerated contract.

| Code | B3 name           | B3 return type (section 1)                     | Published value matched (section 2)                                    | First session served | Sessions to 2026-10-02         | Verdict                                                 |
| ---- | ----------------- | ---------------------------------------------- | ---------------------------------------------------------------------- | -------------------- | ------------------------------ | ------------------------------------------------------- |
| IBOV | Ibovespa B3       | Total (R$)                                     | 2025-12-30 = 161,125.37 (B3 news, #412); BDI 2025-10-13 and 2025-11-11 | 1968-01-02           | 14,491                         | Already served; its label is the open question          |
| IBXX | IBrX 100          | Total (R$)                                     | BDI 2025-10-13; base 1,000 on 1995-12-28                               | 1994-12-29           | 7,868                          | Verified, held on the label                             |
| IBXL | IBrX 50           | Total (R$)                                     | BDI 2025-09-10, 2025-10-13, 2025-11-11; base 1,000 on 1997-12-30       | 1997-12-30           | 7,126                          | Verified, held on the label                             |
| IFIX | IFIX B3           | Total                                          | BDI 2025-10-13; base 1,000 on 2010-12-30                               | 2010-12-30           | 3,910                          | Verified, held on the label                             |
| SMLL | Small Cap         | Total                                          | Base 1,000 on 2008-04-30 only                                          | 2005-08-31           | 5,225                          | Verified by base only, held on the label                |
| IDIV | Dividendos        | Total (a separate Price Return version exists) | Base 1,000 on 2005-12-29 only                                          | 2005-12-29           | 5,143                          | Verified by base only, held on the label                |
| ICON | Consumo           | Total                                          | Base 1,000 on 2006-12-28 only                                          | 2006-12-28           | 4,897                          | Verified by base only, held on the label                |
| IMOB | Imobiliário       | Total                                          | Base 1,000 on 2007-12-28 only                                          | 2007-12-28           | 4,652                          | Verified by base only, held on the label                |
| IEEX | Energia Elétrica  | Total, with reinvestment in the asset itself   | Base 1,000 on 1994-12-29 only                                          | 1994-01-03           | 8,112                          | Verified by base only, held on the label; an unexplained move in 1999-03 (section 3)        |
| UTIL | Utilidade Pública | Total                                          | Base 1,000 on 2005-12-29 only                                          | 2005-12-29           | 5,143 (4,897 in run 1) | Verified by base only, held on the label; one transient null (sections 3, 4) |

## 1. What B3 calls each index

B3's own definition, _Manual de Definições e Procedimentos dos Índices da B3_
(Feb 2023), <https://www.b3.com.br/data/files/CA/A5/9F/28/14F35810F534EB48AC094EA8/Manual%20de%20defini%C3%A7%C3%B5es%20e%20procedimentos%20de%20%C3%8Dndices-PT.pdf>,
read 2026-10-03, section 1.2:

> ÍNDICE DE RETORNO TOTAL. É um indicador que procura refletir não apenas as variações nos preços dos ativos integrantes do índice no tempo, mas também o impacto que a distribuição de proventos por parte das companhias emissoras desses ativos teria no retorno do índice.

> Após o encerramento do último pregão "com-direito", o provento, em dinheiro, é incorporado em todos os demais ativos integrantes da carteira, na proporção de suas respectivas participações.

Each index page, read 2026-10-03:

| Code | URL                                                                                                                                                                                                                   | Quote                                                                                                                                    |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| IBOV | <https://www.b3.com.br/pt_br/market-data-e-indices/indices/indices-amplos/ibovespa.htm> and the methodology <https://www.b3.com.br/data/files/9C/15/76/F6/3F6947102255C247AC094EA8/IBOV-Metodologia-pt-br__Novo_.pdf> | `Tipo de retorno \| Total (R$)`; "O Ibovespa é um índice de retorno total (ver Manual de Definições e Procedimentos dos Índices da B3)." |
| IBXX | <https://www.b3.com.br/pt_br/market-data-e-indices/indices/indices-amplos/indice-brasil-100-ibrx-100-b3.htm>                                                                                                          | "O IBrX 100 é um índice de retorno total (ver Manual de Definições e Procedimentos dos Índices da B3)."; `Tipo de retorno \| Total (R$)` |
| IBXL | <https://www.b3.com.br/pt_br/market-data-e-indices/indices/indices-amplos/indice-brasil-50-ibrx-50-b3.htm>                                                                                                            | "O IBrX 50 é um índice de retorno total (ver Manual …)."; `Tipo de retorno \| Total (R$)`                                                |
| SMLL | <https://www.b3.com.br/pt_br/market-data-e-indices/indices/indices-de-segmentos-e-setoriais/indice-small-cap-smll-b3.htm>                                                                                             | "O SMLL é um índice de retorno total (ver Manual …)."                                                                                    |
| IFIX | <https://www.b3.com.br/pt_br/market-data-e-indices/indices/indices-de-segmentos-e-setoriais/indice-de-fundos-de-investimentos-imobiliarios-ifix-b3.htm>                                                               | "O IFIX é um índice de retorno total (ver Manual …)."                                                                                    |
| IDIV | <https://www.b3.com.br/pt_br/market-data-e-indices/indices/indices-de-segmentos-e-setoriais/indice-dividendos-idiv-b3.htm>                                                                                            | "O IDIV B3 é um índice de retorno total." and "O IDIV B3 Price Return é um índice de retorno preço."                                     |
| IEEX | <https://www.b3.com.br/pt_br/market-data-e-indices/indices/indices-de-segmentos-e-setoriais/indice-de-energia-eletrica-iee-b3.htm>                                                                                    | "O IEE é um índice de retorno total com reinvestimento no próprio ativo."                                                                |
| ICON | <https://www.b3.com.br/pt_br/market-data-e-indices/indices/indices-de-segmentos-e-setoriais/indice-de-consumo-icon-b3.htm>                                                                                            | "O ICON é um índice de retorno total (ver Manual …)."                                                                                    |
| IMOB | <https://www.b3.com.br/pt_br/market-data-e-indices/indices/indices-de-segmentos-e-setoriais/indice-imobiliario-imob-b3.htm>                                                                                           | "O IMOB é um índice de retorno total (ver Manual …)."                                                                                    |
| UTIL | <https://www.b3.com.br/pt_br/market-data-e-indices/indices/indices-de-segmentos-e-setoriais/indice-utilidade-publica-util-b3.htm>                                                                                     | "O UTIL é um índice de retorno total (ver Manual …)."                                                                                    |

**Where a price-return version exists, B3 names it apart.** The IDIV page above
says "IDIV B3 Price Return". The _Índices on Demand_ page
(<https://www.b3.com.br/en_us/market-data-and-indices/indexes/indices-on-demand/>)
lists "IDIV B3 Price Return" and "Ibov Smart Dividends Price Return B3" as
spreadsheet downloads (`IDIVB3_PR_EN.xlsx`, `IBOV_SMART_DIV_EN.xlsx`), and B3's
Smart Dividends page says (search excerpt) "O Ibov Smart Dividendos Total Return B3 é um índice de
retorno total. O Ibov Smart Dividendos Price Return B3 é um índice de retorno
preço." The daily bulletin labels the total-return Smart Dividends series
`IBOV SD TR`. So the naming rule is: the base code is the total-return index and
the price version carries "Price Return" in its name.

**No code on the endpoint carries that marker.** B3's own membership endpoint,
`indexProxy/indexCall/GetStockIndex` (HTTP 200, 469 rows), names 40 index codes:
AGFS, BDRX, BNCO, GPTW, IBBC, IBBE, IBBR, IBEE, IBEP, IBEW, IBHB, IBLV, IBOV,
IBRA, IBSD, IBST, IBXL, IBXX, ICO2, ICON, IDIV, IDVR, IEEX, IFES, IFIL, IFIX,
IFNC, IGCT, IGCX, IGNM, IMAT, IMOB, INDX, ISEE, ITAG, IVBX, MLCX, SCSR, SMLL,
UTIL. None contains TR or PR. **Not tested:** whether `GetPortfolioDay` accepts a
code that is not on that list (for example a price-return IDIV). B3 publishes no
code for it in any page read here, and none was guessed.

## 2. Published values against the endpoint

Two kinds of primary source, neither of them the statistics proxy itself (B3's
"Estatísticas históricas" pages render that proxy, so a match there would prove
nothing):

**B3's daily bulletin (BDI, `Indicadores e Informativos`)**, published by B3 at
`arquivos.b3.com.br`. Its date is the session: the 2025-01-22 bulletin is headed
"REFERENTE A QUARTA-FEIRA - 22 DE JANEIRO DE 2025" (the 2025-09-10 one: "REFERENTE A QUARTA-FEIRA - 10 DE SETEMBRO DE 2025"). It prints each index in whole
points, and the endpoint's value is that number truncated, not rounded.

| Bulletin (read 2026-10-03)                                                   | Index    | Bulletin `Fechamento` | Endpoint, same session |
| ---------------------------------------------------------------------------- | -------- | --------------------- | ---------------------- |
| <https://arquivos.b3.com.br/bdi/download/bdi/2025-10-13/BDI_02_20251013.pdf> | IBOVESPA | 141.783               | IBOV 141,783.36        |
| same                                                                         | IFIX     | 3.569                 | IFIX 3,569.96          |
| same                                                                         | IBRX50   | 23.751                | IBXL 23,751.08         |
| same                                                                         | IBrX100  | 59.921                | IBXX 59,921.70         |
| <https://arquivos.b3.com.br/bdi/download/bdi/2025-11-11/BDI_02_20251111.pdf> | IBOVESPA | 157.748               | IBOV 157,748.60        |
| same                                                                         | IBRX50   | 26.425                | IBXL 26,425.33         |
| <https://arquivos.b3.com.br/bdi/download/bdi/2025-09-10/BDI_02_20250910.pdf> | IBOVESPA | 142.348 | IBOV 142,348.70 |
| same | IBRX50 | 23.847 | IBXL 23,847.24 |

Nine of nine agree. The BDI pages read held no closing table for SMLL, IDIV,
IEE, ICON, IMOB or UTIL (the first 10 and 20 pages of two bulletins), so those six
have no second source of this kind.

**The administrator's methodology: base value on base date.** _Histórico de
Adequações Metodológicas dos Índices da B3_ (Feb 2021),
<https://www.b3.com.br/data/files/A0/12/BB/92/12AC77101FCDCB77AC094EA8/Historico-das-Adequacoes-Metodologicas%20Port%20Fev21.pdf>,
read 2026-10-03, states each base. The endpoint returns exactly that value on
exactly that date for all ten:

| Code | Methodology quote                                                                                                      | Endpoint on the base date |
| ---- | ---------------------------------------------------------------------------------------------------------------------- | ------------------------- |
| IBOV | "A base do Ibovespa foi fixada em 100 (cem) pontos para a data de 02/01/1968."                                         | 1968-01-02 = 100.00       |
| IBXX | "A base do IBrX 100 foi fixada em 1.000 pontos para a data de 28/12/1995, e sua divulgação teve início em 02/01/1997." | 1995-12-28 = 1000.00      |
| IBXL | "A base do IBrX 50 foi fixada em 1.000 pontos para a data de 30/12/1997, e sua divulgação teve início em 02/01/2003."  | 1997-12-30 = 1000.00      |
| SMLL | "A base do SMLL foi fixada em 1.000 pontos para a data de 30/04/2008, e sua divulgação teve início em 01/09/2008."     | 2008-04-30 = 1000.00      |
| IFIX | "A base do IFIX foi fixada em 1.000 pontos para a data de 30/12/2010, e sua divulgação teve início em 03/09/2012."     | 2010-12-30 = 1000.00      |
| IDIV | "A base do IDIV foi fixada em 1.000 pontos para a data de 29/12/2005, e sua divulgação teve início em 02/05/2011."     | 2005-12-29 = 1000.00      |
| IEEX | "A base do IEE foi fixada em 1.000 pontos para a data de 29/12/1994, e sua divulgação teve início em 01/08/1996."      | 1994-12-29 = 1000.00      |
| ICON | "A base do ICON foi fixada em 1.000 pontos para a data de 28/12/2006, e sua divulgação teve início em 02/01/2009."     | 2006-12-28 = 1000.00      |
| IMOB | "A base do IMOB foi fixada em 1.000 pontos para a data de 28/12/2007, e sua divulgação teve início em 02/01/2009."     | 2007-12-28 = 1000.00      |
| UTIL | "A base do UTIL foi fixada em 1.000 pontos para a data de 29/12/2005, e sua divulgação teve início em 02/05/2011."     | 2005-12-29 = 1000.00      |

Read this check for what it is: a series that is re-based to 1,000 on a date
returns 1,000 there by construction, so it shows the endpoint serves B3's
series on B3's scale, not that every later level is right. The later levels are
what the bulletin rows test, and only for IBOV, IBXX, IBXL and IFIX.

**Back-calculated history.** Every index except IBOV starts before its
publication date or before its base date: IBXX serves from 1994-12-29 (base
1995-12-28, published 1997-01-02), IEEX from 1994-01-03 (base 1994-12-29) and
SMLL from 2005-08-31 (base 2008-04-30, published 2008-09-01). Those earlier
levels were computed by B3 after the fact. The endpoint does not mark them.
B3's SMLL history page says (search excerpt) "desde janeiro de 2005"
(<https://www.b3.com.br/pt_br/market-data-e-indices/indices/indices-de-segmentos-e-setoriais/indice-small-cap-smll-estatisticas-historicas.htm>);
the endpoint's first session is 2005-08-31, which that sentence does not explain.
IFIX's history page says (search excerpt) "desde dezembro de 2010", which matches 2010-12-30.

## 3. Depth, gaps and what the shipped checks would say

Run 37138333487 fetched every year from 1960 to 2026 for each code, ran the
shipped `parse_year` and `mark_divisor_steps` on the result, and compared its
session dates with IBOV's.

- **Depth** is the table above. All ten end on 2026-10-02. IBOV's 14,491 sessions
  equal the 14,491 rows of `b3_index_level` read from production the same day.
- **Gaps:** none longer than 10 calendar days, and for IBXX, IBXL, SMLL, IFIX,
  IDIV, IEEX, ICON and IMOB the session dates equal IBOV's over the span (0
  missing, 0 extra). 2022-12-30 and 2023-12-29 are absent from every code, IBOV
  included.
- **`mark_divisor_steps` returned without raising for all ten**, so none has a
  one-session move beyond a factor of two that the guard would reject, and none
  needs an entry in `INDEX_DIVISOR_STEPS`. The only one-session moves outside
  0.8 to 1.25 are IBOV's 16 (the 11 listed steps, and 1990-03-20, 1990-03-21,
  1991-02-04, 1995-03-10 and 1999-01-15, which are market moves this note does
  not source), the same 1999-01-15 move in IBXX and IBXL, and IEEX on 1999-03-15
  and 1999-03-31.
- **IEEX 1999-03-15 and 1999-03-31 are unexplained.** IEEX rose 70% in one
  session on 1999-03-15 (2,943.90 to 5,010.15) and fell 29% on 1999-03-31
  (5,291.52 to 3,743.21), after +18% and +24% on 03-10 and 03-11. IBOV moved
  +8.8% and -3.0% on those two days, IBXX +4.7% and -0.7%. No divisor step
  explains it, the guard's factor of two does not catch it, and the methodology
  history says nothing about 1999. It is stored as published if IEEX is ever
  added, and a caller should not read 1999-03 as a market move without a source.
- **UTIL had a hole in run 1 that was not there in the next two.** The first
  run got `results=null` for UTIL 2012, so its series showed no session between
  2011-12-29 and 2013-01-02 (246 sessions short of IBOV's). Run 37138739075 then
  fetched UTIL 2011, 2012 and 2013 twice each: all six answers were HTTP 200 with
  non-null results (249, 246 and 248 session cells). UTIL's history is therefore
  complete as served now (5,143 sessions, the same span as IDIV), and the null
  was a transient answer. Section 4 is about why that matters.

## 4. What the null result looks like

The shipped fetcher raises `B3IndexNoResults` on the first `results=null` and does
not retry it (`src/fetchers/b3_index_fetcher.py`: "Retrying does not fill it").
That is right for a code B3 does not publish (IFNM answered null for 2025,
the fixture of #412, captured 2026-09-30). It is not right for a year B3 does serve, and run 1
caught one: UTIL 2012 came back null once and non-null on every later fetch.

Run 37138825101 then asked for every served year of the ten codes three times,
837 requests in all, and got 837 non-null answers, no empty body and no error.
Across the three runs that is one null in about 1,140 requests for years that
exist, a small sample, so the rate is "rare", not "zero" and not measurable more
finely here. IBOV alone has not met it in production: the last 8 `index_levels`
rows of `cvm_ingest_log` (2026-10-01 to 2026-10-03, read 2026-10-03) are all
`ok` (each fetches 1968 through the current year by the code, 59 calendar years).

Why it matters for adding codes: `ingest_index_levels` fetches every year of every
configured code, validates the whole set, and upserts once at the end, so one
null for any code fails the run and writes nothing, IBOV's refresh included.
IBOV's 59 calls a night leave that risk small. Ten codes make about 272 calls a
night, which at one null in about 1,140 is roughly a one-in-five chance on a
given night that `run_b3_events` goes red and IBOV is not refreshed. So the
change that adds codes should first retry a null a few times with a pause before
raising, and keep raising when every try answers null (an unconfigured code still
fails, as it should). That is a change to the fetcher and its test, not made here.

## 5. What would ship, and the decision that is the owner's

The change that adds the verified codes is small and is written down here
so it is not rediscovered, but it is **not made** because its wording is not
settled:

1. `INDEX_CODES` and `FIRST_YEAR` in `src/pipeline/ingest_b3_index.py`: IBXX 1994,
   IBXL 1997, SMLL 2005, IFIX 2010, IDIV 2005, ICON 2006, IMOB 2007, with IEEX
   1994 and UTIL 2005 once their open points (sections 3 and 4) are answered. Add
   the retry on `results=null` of section 4 in the same change, before any code.
2. Tests: the accepted-codes list in the refusal message comes from the table
   (`SELECT DISTINCT index_code`), so it follows the backfill with no SQL edit;
   `tests/test_b3_index_levels.py` and `tests/test_index_history_contract.py` pin
   the configured list.
3. `api.coverage()` already reads the depth of every code from the table
   (`29_api_index.sql`, `19_api_contract.sql` v45), so each index shows its first
   date once loaded. The `index_history` COMMENT and the catalog text name IBOV
   ("IBOV from 1968-01-02") and say "price index", and would change with a
   catalog bump, `openapi.json`, the MCP contract and `tools.ts`.
4. The backfill is the nightly run: `run_b3_events` refetches every year of
   every configured code, so the first run after the merge loads the history. No
   backfill mode exists or is needed.

**The decision.** B3 labels every one of these total return, IBOV included. The
served text calls the series a price index. Either the label changes to "levels
as published by B3, each a total-return index per B3" (and `index_history`
documents that a caller needs `close_total_return` from `quote_history`, not
this series, to compare like with like), or the series is restricted to
something B3 labels price return, which no code on this endpoint is. The first
is a documentation correction of a shipped contract (catalog text, SQL
comments, the usage guide, the SDK docstring), and the ticket asked only for a
check, so it is left to the owner.

## 6. Not verified

- Any published close for SMLL, IDIV, IEEX, ICON, IMOB or UTIL on a date other
  than its base date. The bulletin pages read held no closing table for them.
- Whether B3 re-states pre-publication levels when it rebalances (the back-
  calculated sections in section 2 were compared with nothing).
- The cause of IEEX 1999-03, of UTIL's null answer, and of SMLL starting on
  2005-08-31 when B3's page says January 2005.
- Whether `GetPortfolioDay` serves a price-return code that B3 lists nowhere.
- The BDI before 2025-09 and after 2025-11, and the other 112 to 243 pages of the
  two bulletins (only their first 10 and 20 pages were read).
- Total return versus price by the numbers: this note relies on B3's stated
  type. It did not compute either series from constituents.
