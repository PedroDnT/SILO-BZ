# Track 5 — Retail and accountability/research platforms (S4, with retail as context), Brazil

Research date: 2026-09-23. Evidence rule per TAXONOMY.md: Y/P only with a fetched URL or a search excerpt I saw; `?` = unknown; N = verified absent. Inferences are labelled.

**Access caveats (these limit what counts as evidence):**

- statusinvest.com.br returns HTTP 403 (Cloudflare) to WebFetch and to curl. Status Invest evidence comes from Parallel Search fetch excerpts (which did get through), search excerpts and its `lp.statusinvest.com.br` landing pages.
- investidor10.com.br was fetched directly (WebFetch and curl, including page headings).
- Case de Valor ticker "short" tabs render client-side. The server HTML has financials but no lending series, so history depth per ticker is `?`.
- B3 BDI retention facts come from SILO's own verified endpoint contract in `/home/user/SILO-BZ/src/fetchers/b3_bdi_fetcher.py` (verified live on 2026-09-16), not from a third party. The b3.com.br lending pages rendered empty to WebFetch because they are JS pages.

---

## 1. DEEP platforms

### 1.1 Status Invest (statusinvest.com.br)

**Profile.** Brazil's largest free retail fundamentals site. It is part of the Suno group: its menus link to `lp.sunoconsultoria.com.br` and its address is Av. Pres. Juscelino Kubitschek 2041. It covers Brazilian stocks, FIIs, open-ended funds ("Lista de Fundos de Investimentos", e.g. 13,544 multimercados), BDRs, ETFs, Tesouro, crypto, US stocks and REITs.

- **Stock pages:** price, indicators, dividends, payout, balance-sheet items and a per-ticker "aluguel de ações" block.
- **Fund pages:** return, volatility, Sharpe, fees, and a "PATRIMÔNIO" composition with a "Top 10 ativos do patrimônio", i.e. a CDA-derived look-through with a data base date.
- **Data sources:** public CVM/B3 data, plus FactSet for analyst consensus (Forecast module).
- **Paid tiers:**
  - Plano Bull: R$262.80/yr (12× R$21.90), portfolio management.
  - Módulo Forecast: R$250.80/yr list, R$200.64 on promo. FactSet consensus, price targets and 3-year projections.
  - Status Alpha: R$958.80/yr (12× R$79.90). An "AI + Factor Investing" rating engine ("more than 200 financial indicators") that issues buy/sell classifications for ~37–40k global stocks and sends "Alertas de Oportunidade".
  - Integração B3 and IR (tax) add-ons.
- **Segment:** retail (B3/S4 only incidentally).
- **Differentiators:** reach, free breadth, the screener with Excel download, per-ticker lending snapshot, fund composition.
- **Weaknesses vs SILO:**
  - The lending block is a single snapshot. The PETR4 excerpt showed "DATA BASE – 27/03/2024", i.e. stale.
  - No trade-level lending data and no broker legs.
  - No FIDC credit metrics, no forensic screens, no API.
  - It is behind Cloudflare, so it cannot be scraped by agents.
  - The AI product is a recommendation engine, which is the opposite of SILO's no-advice stance.

| ID  | value                                                            | evidence URL                                                                                                                                                                                                     | note                                                                                                              |
| --- | ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| C1  | Y                                                                | https://statusinvest.com.br/fundos-de-investimento ; https://statusinvest.com.br/fundos-de-investimento/wa-di-max-premium-fic-de-fi-rf-ref                                                                       | Fund list by class; per-fund cota, PL, 12m/24m return, vol, Sharpe. Flows (captação/resgate) not seen             |
| C2  | ?                                                                | —                                                                                                                                                                                                                | No FIDC informe metrics seen                                                                                      |
| C3  | Y                                                                | https://statusinvest.com.br/fundos-imobiliarios/mxrf11 ; https://statusinvest.com.br/fundos-imobiliarios/busca-avancada                                                                                          | FII pages have indicators, contábil, portfólio and comunicado tabs; FII screener                                  |
| C4  | ?                                                                | —                                                                                                                                                                                                                | FIAGRO/FIP not verified                                                                                           |
| C5  | ?                                                                | —                                                                                                                                                                                                                | CRI/CRA secondary data not seen                                                                                   |
| C6  | Y                                                                | https://statusinvest.com.br/fundos-de-investimento (menu: ETFs, "Tudo sobre ETFs")                                                                                                                               | BR and US ETFs                                                                                                    |
| C7  | P                                                                | https://statusinvest.com.br/fundos-de-investimento/encore-acoes-fia                                                                                                                                              | "PATRIMÔNIO DATA BASE 07/2024" plus "Top 10 ativos do patrimônio": asset-class split and top 10 only, often stale |
| C8  | Y                                                                | https://statusinvest.com.br/acoes/petr4                                                                                                                                                                          | Patrimônio líquido, ativos, payout; "HOJE / HISTÓRICO" indicators                                                 |
| C9  | P                                                                | https://statusinvest.com.br/fundos-imobiliarios/mxrf11                                                                                                                                                           | "Comunicado" tab on FII pages; stock fatos-relevantes feed not verified                                           |
| C10 | ?                                                                | —                                                                                                                                                                                                                | Shareholder table not verified (site blocked)                                                                     |
| C11 | Y                                                                | https://statusinvest.com.br/acoes/eua/rpm                                                                                                                                                                        | Dividend history, "MAPA DE CALOR DOS PROVENTOS"                                                                   |
| C12 | Y                                                                | https://lp.statusinvest.com.br/ao/forecast-relampago/                                                                                                                                                            | FactSet consensus, price target, 3-yr projections (paid)                                                          |
| C13 | Y                                                                | https://statusinvest.com.br/acoes/petr4                                                                                                                                                                          | Quotes, charts (30d to 5y)                                                                                        |
| C14 | ?                                                                | —                                                                                                                                                                                                                | "tempo real" claimed only in Alpha marketing                                                                      |
| C15 | ?                                                                | —                                                                                                                                                                                                                | No options chain seen                                                                                             |
| C16 | N?                                                               | —                                                                                                                                                                                                                | None seen; unverified                                                                                             |
| C17 | ?                                                                | —                                                                                                                                                                                                                | Tesouro Direto shown; debenture secondary prices not seen                                                         |
| C18 | P                                                                | https://statusinvest.com.br/acoes/aluguel ; search excerpt of https://statusinvest.com.br/acoes/petr4 ("aluguel de ações da PETR4 … DATA BASE - 27/03/2024. TOMADOR (média) 0,04% MIN 0,01% MAX 0,20% DOADOR …") | Rate snapshot per ticker plus a market list; no time series or broker data seen; data base was stale (2024)       |
| C19 | ?                                                                | —                                                                                                                                                                                                                | Not seen                                                                                                          |
| C20 | ?                                                                | —                                                                                                                                                                                                                | Not seen                                                                                                          |
| C21 | P                                                                | https://statusinvest.com.br/ (Dólar, Tesouro Direto on home)                                                                                                                                                     | FX and Tesouro only; no BACEN/Focus/IBGE panel seen                                                               |
| C22 | N?                                                               | —                                                                                                                                                                                                                | Links out to documents; no text search seen                                                                       |
| Q1  | P                                                                | https://statusinvest.com.br/fundos-de-investimento/encore-acoes-fia                                                                                                                                              | Fund monthly return up to "10 anos"; stock charts up to 5y; depth of fundamentals not verified                    |
| Q2  | ?                                                                | —                                                                                                                                                                                                                | No restatement/version history seen                                                                               |
| Q3  | N                                                                | https://statusinvest.com.br/acoes/busca-avancada                                                                                                                                                                 | Footer is generic: "dados calculados a partir das informações coletadas"; no per-number source                    |
| Q4  | ?                                                                | —                                                                                                                                                                                                                | —                                                                                                                 |
| Q5  | ?                                                                | —                                                                                                                                                                                                                | —                                                                                                                 |
| A1  | Y                                                                | https://statusinvest.com.br/acoes/busca-avancada                                                                                                                                                                 | Stock/FII/REIT screeners with saved filters; includes Forecast filters                                            |
| A2  | Y                                                                | https://statusinvest.com.br/fundos-de-investimento                                                                                                                                                               | "MAIOR RENTABILIDADE (12m)" rankings per class                                                                    |
| A3  | Y                                                                | https://statusinvest.com.br/fundos-imobiliarios/mxrf11                                                                                                                                                           | "Compare FIIs / Compare rentabilidade"                                                                            |
| A4  | P                                                                | https://statusinvest.com.br/fundos-de-investimento/encore-acoes-fia ; https://statusinvest.com.br/acoes/eua/rpm                                                                                                  | Vol, Sharpe, historical volatility                                                                                |
| A5  | N?                                                               | —                                                                                                                                                                                                                | No forensic screens seen; "Alertas de Oportunidade" are valuation signals, not integrity checks                   |
| A6  | Y                                                                | https://lp.statusinvest.com.br/ao/alpha/                                                                                                                                                                         | "Alertas de Oportunidade" (paid Alpha)                                                                            |
| A7  | Y                                                                | https://lp.statusinvest.com.br/ao/bull/                                                                                                                                                                          | Portfolio, lists, "seguindo" watchlists, B3 integration                                                           |
| A8  | N?                                                               | —                                                                                                                                                                                                                | No fund-to-issuer or issuer-to-lending linkage seen                                                               |
| X1  | Y                                                                | https://statusinvest.com.br/acoes/petr4                                                                                                                                                                          | Web plus iOS/Android apps                                                                                         |
| X2  | N?                                                               | —                                                                                                                                                                                                                | Excel download of screener results only (search excerpt), no add-in                                               |
| X3  | N?                                                               | —                                                                                                                                                                                                                | No public API found; statusinvest.com.br/assinatura is 404; the site blocks bots                                  |
| X4  | N?                                                               | —                                                                                                                                                                                                                | —                                                                                                                 |
| X5  | N?                                                               | —                                                                                                                                                                                                                | No MCP found                                                                                                      |
| X6  | P                                                                | https://lp.statusinvest.com.br/ao/alpha/                                                                                                                                                                         | "Status Alpha IA" is a rating engine, not a chat/NL assistant                                                     |
| X7  | P                                                                | search excerpt for statusinvest busca-avançada ("clicar em download… planilha Excel")                                                                                                                            | Screener snapshot to Excel only                                                                                   |
| T1  | N                                                                | https://statusinvest.com.br/fundos-de-investimento (footer)                                                                                                                                                      | Disclaimer only; no stance on fabrication or citation                                                             |
| T2  | P                                                                | https://statusinvest.com.br/acoes/petr4 (search excerpt)                                                                                                                                                         | Shows "DATA BASE" dates per block but no coverage page                                                            |
| B1  | Y                                                                | https://statusinvest.com.br/                                                                                                                                                                                     | Free core                                                                                                         |
| B2  | Bull R$262.80/yr; Forecast R$200.64–250.80/yr; Alpha R$958.80/yr | https://lp.statusinvest.com.br/ao/bull/ ; https://lp.statusinvest.com.br/ao/forecast-relampago/ ; https://lp.statusinvest.com.br/ao/alpha/                                                                       | —                                                                                                                 |
| B3  | Retail (S4 incidental)                                           | —                                                                                                                                                                                                                | "Mais de 100 mil investidores" (Bull LP)                                                                          |
| O1  | ?                                                                | —                                                                                                                                                                                                                | —                                                                                                                 |
| O2  | N?                                                               | —                                                                                                                                                                                                                | No auditability claims                                                                                            |

### 1.2 Investidor10 (investidor10.com.br)

**Profile.** A retail "all-in-one" site with more than 1 million users (per its PRO page).

- **Coverage:** stocks, FIIs, ETFs (BR and global), BDRs, US stocks, crypto, renda fixa (a distributor-offer showcase: CDB/LCI/LCA/CRI/CRA/debentures), Tesouro, and an open-ended funds list with classes Renda Fixa / Ações / Multimercado / Cambial / FIDC.
- **Stock pages** (headings verified): "POSIÇÃO ACIONÁRIA" (shareholder table), "HISTÓRICO DE INDICADORES FUNDAMENTALISTAS", "COMUNICADOS", dividends, Graham/Bazin "preço justo".
- **FII pages:** cotistas count, a documents feed (Informe Mensal, Relatório Gerencial), portfolio distribution.
- **PRO:** R$238.80/yr, or multi-year bundles of R$477.60 / R$716.40. Includes courses, recommended portfolios, the portfolio manager with B3 integration, IRPF/DARF, price alerts, and "até 30 anos de dados históricos" for BR assets.
- **AI:** "Chat IA" (Beta) at /chat-ia/ and "Análise Inteligente de Carteira" ("Turbinado pela Inteligência Artificial").
- **Sources:** "fontes públicas (B3, CVM e RI das empresas)".
- **Newsroom:** it produced a filing-gap story ("46 fundos deixam de publicar informações e acendem alerta"), which is a journalistic, one-off version of a coverage/non-filer screen.
- **Weaknesses vs SILO:**
  - No lending/short data: `/acoes/aluguel/` returns HTTP 410 Gone, and the PETR4 page has no lending section.
  - No CDA look-through shown, no FIDC credit metrics, no public API (only third-party scrapers such as parse.bot).
  - Recommendation-oriented ("Carteiras Recomendadas").

| ID  | value                                                         | evidence URL                                                                                                                                                     | note                                                                                                                                                                                                                                |
| --- | ------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C1  | Y                                                             | https://investidor10.com.br/fundos ; https://investidor10.com.br/fundos/ainvest-capital-inteligencia-artificial-global-fundo-de-investimento-financeiro-em-acoes | PL, 12m/24m return, vol, Sharpe, gestor, administrador, fees; flows not seen                                                                                                                                                        |
| C2  | P                                                             | https://investidor10.com.br/fundos                                                                                                                               | A "FIDC" class filter exists in the fund list; inference: NAV/return only, no informe metrics seen                                                                                                                                  |
| C3  | Y                                                             | https://investidor10.com.br/fiis/mxrf11/                                                                                                                         | Cotistas (1,529,305), P/VP, DY, taxa adm, documents, asset distribution                                                                                                                                                             |
| C4  | ?                                                             | —                                                                                                                                                                | FIAGRO not verified                                                                                                                                                                                                                 |
| C5  | P                                                             | https://investidor10.com.br/ (renda-fixa offers: "Debênture… Emissor Simpar… Distribuidor BTG")                                                                  | Primary retail offers via distributors, not CVM securitization data                                                                                                                                                                 |
| C6  | Y                                                             | https://investidor10.com.br/etfs/                                                                                                                                | BR and global ETFs                                                                                                                                                                                                                  |
| C7  | N?                                                            | https://investidor10.com.br/fundos/ainvest-capital-inteligencia-artificial-global-fundo-de-investimento-financeiro-em-acoes                                      | Fund page tabs are Resumo / Rentabilidade / Patrimônio; no holdings list seen                                                                                                                                                       |
| C8  | Y                                                             | https://investidor10.com.br/acoes/petr4/                                                                                                                         | "BALANÇO PATRIMONIAL", "Receitas e Lucros", indicator history                                                                                                                                                                       |
| C9  | Y                                                             | https://investidor10.com.br/acoes/fatos-relevantes-comunicados/ ; https://investidor10.com.br/acoes/petr4/ ("COMUNICADOS DO PETR4")                              | —                                                                                                                                                                                                                                   |
| C10 | Y                                                             | https://investidor10.com.br/acoes/petr4/ ("POSIÇÃO ACIONÁRIA DA Petrobras – Acionista % ON % PN % Total")                                                        | Snapshot                                                                                                                                                                                                                            |
| C11 | Y                                                             | https://investidor10.com.br/acoes/dividendos/                                                                                                                    | Dividend calendar plus "radar de dividendo inteligente"                                                                                                                                                                             |
| C12 | N?                                                            | —                                                                                                                                                                | Only its own Graham/Bazin "preço justo"; no consensus seen                                                                                                                                                                          |
| C13 | Y                                                             | https://investidor10.com.br/acoes/petr4/                                                                                                                         | —                                                                                                                                                                                                                                   |
| C14 | ?                                                             | —                                                                                                                                                                | —                                                                                                                                                                                                                                   |
| C15 | N?                                                            | —                                                                                                                                                                | Not seen                                                                                                                                                                                                                            |
| C16 | N?                                                            | —                                                                                                                                                                | —                                                                                                                                                                                                                                   |
| C17 | P                                                             | https://investidor10.com.br/renda-fixa/                                                                                                                          | Offer rates, not ANBIMA secondary prices                                                                                                                                                                                            |
| C18 | N                                                             | https://investidor10.com.br/acoes/aluguel/ (HTTP 410 Gone); https://investidor10.com.br/acoes/petr4/ (no lending heading)                                        | Removed or never offered                                                                                                                                                                                                            |
| C19 | N?                                                            | —                                                                                                                                                                | Not seen                                                                                                                                                                                                                            |
| C20 | ?                                                             | —                                                                                                                                                                | IFIX/IBOV comparisons only                                                                                                                                                                                                          |
| C21 | P                                                             | —                                                                                                                                                                | Indices and inflation used in "rentabilidade real"; no macro panel verified                                                                                                                                                         |
| C22 | P                                                             | https://investidor10.com.br/fiis/mxrf11/                                                                                                                         | Links to Relatório Gerencial PDFs; no text extraction                                                                                                                                                                               |
| Q1  | Y                                                             | https://investidor10.com.br/pro2/                                                                                                                                | "até 30 anos de dados históricos para ativos nacionais" (PRO)                                                                                                                                                                       |
| Q2  | ?                                                             | —                                                                                                                                                                | —                                                                                                                                                                                                                                   |
| Q3  | N                                                             | https://investidor10.com.br/acoes/petr4/                                                                                                                         | Generic "fontes públicas (B3, CVM e RI)" disclaimer                                                                                                                                                                                 |
| Q4  | ?                                                             | —                                                                                                                                                                | —                                                                                                                                                                                                                                   |
| Q5  | ?                                                             | —                                                                                                                                                                | —                                                                                                                                                                                                                                   |
| A1  | Y                                                             | https://investidor10.com.br/acoes/rastreador-acoes/                                                                                                              | "rastreador" screener                                                                                                                                                                                                               |
| A2  | Y                                                             | https://investidor10.com.br/acoes/rankings/ ; https://investidor10.com.br/pro2/                                                                                  | "mais de 40 rankings"                                                                                                                                                                                                               |
| A3  | Y                                                             | https://investidor10.com.br/acoes/comparar/                                                                                                                      | Compare up to 5 assets                                                                                                                                                                                                              |
| A4  | P                                                             | https://investidor10.com.br/fundos/ainvest-capital-inteligencia-artificial-global-fundo-de-investimento-financeiro-em-acoes                                      | Vol, Sharpe                                                                                                                                                                                                                         |
| A5  | N?                                                            | —                                                                                                                                                                | "Checklist buy and hold" is a quality filter, not a forensic screen. The newsroom did a one-off non-filer story (https://investidor10.com.br/noticias/46-fundos-deixam-de-publicar-informacoes-e-acendem-alerta-no-mercado-122330/) |
| A6  | Y                                                             | https://investidor10.com.br/pro2/                                                                                                                                | "alertas de preço"                                                                                                                                                                                                                  |
| A7  | Y                                                             | https://investidor10.com.br/pro2/                                                                                                                                | Portfolio manager, B3 integration                                                                                                                                                                                                   |
| A8  | N?                                                            | —                                                                                                                                                                | —                                                                                                                                                                                                                                   |
| X1  | Y                                                             | https://investidor10.com.br/                                                                                                                                     | —                                                                                                                                                                                                                                   |
| X2  | N?                                                            | —                                                                                                                                                                | —                                                                                                                                                                                                                                   |
| X3  | N                                                             | https://parse.bot/marketplace/fe86bbfe-6a00-46ea-897f-b5c3a3ec7dbf/investidor10-com-br-api                                                                       | No first-party API; third parties scrape it (parse.bot "Investidor10 API", GitHub scrapers)                                                                                                                                         |
| X4  | N?                                                            | —                                                                                                                                                                | —                                                                                                                                                                                                                                   |
| X5  | N? (first-party)                                              | https://parse.bot/marketplace/fe86bbfe-6a00-46ea-897f-b5c3a3ec7dbf/investidor10-com-br-api                                                                       | parse.bot shows an "MCP" button over its scraper, which is not first-party                                                                                                                                                          |
| X6  | Y                                                             | https://investidor10.com.br/chat-ia/                                                                                                                             | "Chat IA – Beta"                                                                                                                                                                                                                    |
| X7  | N?                                                            | —                                                                                                                                                                | —                                                                                                                                                                                                                                   |
| T1  | N                                                             | https://investidor10.com.br/acoes/petr4/                                                                                                                         | Disclaimer only                                                                                                                                                                                                                     |
| T2  | N?                                                            | —                                                                                                                                                                | —                                                                                                                                                                                                                                   |
| B1  | Y                                                             | https://investidor10.com.br/                                                                                                                                     | —                                                                                                                                                                                                                                   |
| B2  | PRO R$238.80/yr (12× R$19.90); 3 yrs R$477.60; 5 yrs R$716.40 | https://investidor10.com.br/pro2/                                                                                                                                | —                                                                                                                                                                                                                                   |
| B3  | Retail                                                        | https://investidor10.com.br/pro2/                                                                                                                                | "+1 milhão de investidores"                                                                                                                                                                                                         |
| O1  | ?                                                             | —                                                                                                                                                                | —                                                                                                                                                                                                                                   |
| O2  | N?                                                            | —                                                                                                                                                                | —                                                                                                                                                                                                                                   |

---

## 2. SHALLOW platforms

**Fundamentus** (fundamentus.com.br)

- A free, old-school fundamentals site with a stock screener (P/L, P/VP, PSR, DY), Excel downloads of historical balance sheets and DREs, price history from 1998, FII research, shareholder/administration info, fatos relevantes and proventos. (https://www.fundamentus.com.br/)
- Y: A1, C8, C9, C10, C11, X7 (Excel statements), Q1 (prices since 1998).
- Lacks versus SILO: funds beyond FII, FIDC, CDA, lending, API.

**Funds Explorer** (fundsexplorer.com.br)

- An FII-focused retail platform covering FIIs, FIAGROs and FIINFRAs, with a screener, comparator, rankings (DY, vacância, cotistas), IPO tracking, a distribution calendar and a premium subscriber area. (https://www.fundsexplorer.com.br/)
- Y: C3, C4 (FIAGRO), A1, A2, A7.
- Lacks versus SILO: FIDC/CRI-CRA credit data, forensic screens (no "captive FII" flag, although it does show cotistas), API.

**Clube FII** (clubefii.com.br)

- An FII ecosystem with recommended portfolios, courses, reports, and a "FII DATA PROFESSIONAL" plan for qualified investors/analysts. That plan claims property-level data "não encontradas nem mesmo nos relatórios gerenciais". (https://www.clubefii.com.br/plano-de-assinatura-fii-data-professional?ori=modulo_monitor ; https://www.clubefii.com.br/planos_assinatura)
- The site 403s to fetch, and price was not seen (`?`).
- P: C3 (deep property data, paid).
- Lacks versus SILO: free API, FIDC/CDA, lending.

**Case de Valor** (casedevalor.com.br)

- A new retail site built on Next.js with stocks, FIIs, ETFs, BDRs, US stocks, an options simulator, fatos relevantes, macro and a "Smart Money" radar.
- `/aluguel-de-acoes` is a ranked list of 1,030 assets with Quantity, Volume, % Free Float, Preço Médio, Taxa Tomador and Contratos. It is labelled "18/09/2026 — último boletim B3" and "Posições vendidas · B3". It is a single latest-session snapshot with no broker legs and no trade tape. (https://casedevalor.com.br/aluguel-de-acoes)
- Ticker pages have a `?tab=short` tab (ETFs use `?tab=aluguel`), but it renders client-side, so history depth is `?`.
- "Smart Money" (premium) blends insiders (CVM), derivatives OI, short/rental changes (B3), flow, technicals and analysts into a −100..+100 score. The page does not mention fund holdings. (https://casedevalor.com.br/smart-money)
- Plans: Free; Premium R$199.90/yr; Founder R$399.90 lifetime. Premium adds options Greeks/IV, Smart Money, analyst consensus and bank Basel data. No API or AI listed. (https://casedevalor.com.br/planos)
- Its methodology says formulas "são proprietárias". (https://casedevalor.com.br/sobre/metodologia)
- Y: C18 (snapshot), C15 (premium), C9, C12 (premium), A6 (dividend alerts).
- Lacks versus SILO: an archived lending history, trade tape with brokers, fund data, transparency (proprietary methods).

**Mais Retorno** (maisretorno.com; retail fund-comparison side)

- A fund comparator/ranking with gestor and administrador lists.
- Per-fund "carteira" pages have a month selector going back to SETEMBRO/2014, which is CDA look-through history. (https://maisretorno.com/fundo/itau-acoes-top-5-fi/carteira)
- It labels shell funds "Fundo (casca)". Its editorial desk has computed reverse lookups ("199 fundos… posição vendida em Petrobras", https://maisretorno.com/portal/fundos-investem-queda-petrobras).
- Offers Retorno Prime (retail), Retorno PRO (advisors), and an "API de dados… integração MCP" (Track 4 covers this).
- Disclaimer: "obtidas a partir de fontes públicas como a CVM… não faz conferência individual".
- Y: C1, C7 (Q1 ≥2014), A2, A3, X3, X5.
- Lacks versus SILO: lending tape, FIDC credit monitor, forensic screens beyond the "casca" label.

**Kinvo** (kinvo.com.br)

- A retail portfolio consolidator with a fund/stock comparator, dividend notifications and the "Kinvo Index". Freemium with a 14-day Premium trial. Sources: "B3, CVM, TESOURO NACIONAL". States it gives no recommendations. (https://kinvo.com.br/)
- Y: A7, A6, A3.
- Not a data or research product.

**Gorila** (gorila.com.br)

- A B2B2C portfolio consolidator: GorilaVIEW for advisors, MFOs and gestoras; GorilaCORE is an API for institutions. (https://gorila.com.br/)
- Y: A7, X3 (for custody consolidation, not market data).
- Not a competitor on public-data accountability.

**Official portals**

- **dados.cvm.gov.br:** bulk CSV under the ODbL licence.
  - CDA: 2005 onward in a non-updated archive, full files from 01/2021. The last 3 months refresh daily and months 4–12 weekly. Confidential holdings are consolidated until the embargo expires. (https://dados.cvm.gov.br/dataset/fi-doc-cda)
  - FIDC informe mensal. (https://dados.cvm.gov.br/dataset/fidc-doc-inf_mensal)
  - Y: C1–C8, X7, B1. N: A1–A8 (raw files only), X3 (no query API).
- **CVM RAD / ENET:** document search for listed companies. (https://www.rad.cvm.gov.br/ENET/frmConsultaExternaCVM.aspx)
  - Y: C9, C22 (as PDFs).
- **B3 Fundos.NET / FNET:** public document manager for structured funds (informes, relatórios, carteiras). (https://fnet.bmfbovespa.com.br/fnet/publico/abrirGerenciadorDocumentosCVM)
  - Y: C22, C3/C5 source documents. N: analytics.
- **B3 BDI (arquivos.b3.com.br/bdi):** publishes BTBLendingOpenPosition, BTBTrade and BTBLoanBalance.
  - Retention is about D-21 business days. Wider requests are silently clamped. There is no archive: the legacy `requestname` API does not know these tables, and the `pesquisapregao` archive returns empty zips. (SILO-verified contract, `src/fetchers/b3_bdi_fetcher.py`, 2026-09-16)
  - The b3.com.br "Histórico de empréstimos" and "Boletim Diário" landing pages rendered no content to fetch. (https://www.b3.com.br/pt_br/produtos-e-servicos/emprestimo-de-ativos/renda-variavel/historico-de-emprestimos/)

**NEFIN-USP** (nefin.com.br)

- Free CSV/XLS datasets:
  - Fama-French/momentum/illiquidity factors and the risk-free rate (updated Jul 2026).
  - **Short Interest:** daily, 7 Nov 2012 – 3 Jul 2026. Only three market-average series: short interest, days-to-cover and loan fee. The CSV has columns `date,average_short_interest`, so it is not per ticker.
  - Loan Fees: weekly, 2013 to Sep 2023, stale.
  - Sources: https://nefin.com.br/data/short-interest/ ; https://nefin.com.br/data/loan-fees/ ; https://nefin.com.br/nefindata/short-interest/average_short_interest.csv
- Y: C18 (aggregate), C21 (factors, rf), X7, B1, Q1 (2012+).
- Lacks versus SILO: per-ticker lending, trade tape, funds.

**Brasil.io** (brasil.io)

- Community open-data hub. Its datasets include "Sócios das Empresas Brasileiras" (the CNPJ partner/QSA register), government spending and deputies' expenses, with an `/api/v1/`. No CVM funds or markets datasets were listed. (https://brasil.io/datasets/)
- Relevance: a CNPJ→partners join is a possible complement to SILO's fund/issuer CNPJs.

**Base dos Dados** (basedosdados.org; found during search)

- Republishes CVM fund data (portfolio composition, informe diário, extrato, perfil mensal) as a queryable open dataset. (https://basedosdados.org/dataset/9c5a820f-09dd-4519-adfd-611819163ae0)
- Y: C1, C7, X7/SQL (inference: BigQuery; not verified on the page).
- No analytics or screens seen. This is the closest S4 "research infrastructure" peer.

**Journalism / data desks**

- No Agência Pública, Fiquem Sabendo or Abraji project on CVM funds was found (query below).
- Coverage of fund misuse (Operação Carbono Oculto, Banco Master) uses CVM public data case by case, e.g. Seu Dinheiro tracing Zeus FIDC PL from R$17.5m (Dec 2020) to R$89.8m (Apr 2026). (https://www.seudinheiro.com/2026/economia/nova-fase-da-carbono-oculto-avanca-sobre-fundos-de-investimento-e-trustee-reaparece-como-elo-entre-estruturas-investigadas-pela-pf-miql/)
- O Tempo (2026-09-07) on funds that can hide the beneficial owner relies on IIFA/ANBIMA aggregates and a doctoral thesis ("até 67% dos fundos têm até cinco cotistas, e 44%, um"). It publishes no tool. (https://www.otempo.com.br/economia/2026/9/7/explode-o-numero-de-fundos-que-podem-ocultar-o-dono-do-dinheiro-como-no-master-e-na-carbono-oculto)
- This is demand evidence for S4 with no standing tool serving it.

**Other names surfaced by the searches (not requested; noted for other tracks)**

- **Economatica:** paid terminal with daily BTC lending stock per stock since May 2014 (https://www.economatica.com/blog/aluguel-de-acoes-estoque-de-contratos-de-banco-de-titulos-btc/). Broker-level data not stated.
- **Painel FIDC** (painelfidc.com.br): institutional FIDC intelligence with aging buckets, PDD, subordination, multi-layer look-through and overlapping-cedente detection, plus "PainelFIDC.IA" doc summarisation. Claims every number has "origem, competência e método". Demo/login only, no API. (https://www.painelfidc.com.br/) This is a strong S2 competitor; I did not see zombie screens there.
- **Quantum Finance:** paid terminal with lending and % free float rented. (https://quantumfinance.com.br/aluguel-acoes-b3/)
- **TradersClub:** "Ações Mais Alugadas" ranking. (https://tc.tradersclub.com.br/mais-alugadas-b3)
- **ADVFN:** lending education pages plus a "cotação" page (403 to fetch). Its excerpt says B3 publishes "posições em aberto e aluguéis registrados dos últimos três dias". (https://br.advfn.com/investimentos/aluguel-acoes)
- **Oplab:** options tooling. No lending history found.

---

## 3. Gaps vs SILO (what these platforms offer that SILO lacks)

**S1 (primary, investment professionals):**

1. **Analyst consensus/estimates (C12).** Status Invest Forecast (FactSet) and Case de Valor Premium.
2. **Long per-ticker lending history.** Economatica holds daily BTC stock per stock since 2014 (paid), which SILO's ratchet cannot backfill. NEFIN has a free market-average series since 2012.
3. **Watchlists/alerts/portfolio with B3 integration (A6/A7).** Status Invest, Investidor10, Kinvo, Case de Valor.
4. **Deep price/fundamental history presented per asset (Q1).** Investidor10 claims 30 years; Fundamentus prices go back to 1998; Mais Retorno holdings go back to 2014.
5. **Options analytics with Greeks/IV (C15).** Case de Valor Premium. SILO has an option chain but no Greeks.

**S4 (this track's segment, accountability/research):**

1. **Long, citable lending history.** NEFIN's free aggregate series since 2012 comes with a "How to cite" block, which researchers expect.
2. **Queryable SQL/BigQuery republication of CVM fund data.** Base dos Dados. (SILO has PostgREST but no BigQuery/SQL notebook path.)
3. **CNPJ ownership graph (QSA/sócios).** Brasil.io. SILO does not join funds or issuers to company partners.
4. **Shell-fund labelling.** Mais Retorno shows "Fundo (casca)" on fund pages.
5. **NL chat over the data (X6).** Investidor10 Chat IA (beta). Status Alpha is a ratings engine, not chat.

---

## 4. What SILO has that none of these offer (white-space candidates)

**(a) An archive of B3's lending trade tape with the broker on each leg, beyond ~21 business days.** No public or retail archive was found.

- Case de Valor shows only the latest session aggregate, with no broker data.
- Status Invest shows a per-ticker rate snapshot (stale "DATA BASE 27/03/2024" in one excerpt) and a list page.
- Investidor10 has no lending data (`/acoes/aluguel/` 410 Gone).
- ADVFN excerpt: "últimos três dias". NEFIN is market-average only.
- Economatica has per-stock daily lending _stock_ since 2014, but no trade-level data or broker legs were stated, and it is paid.
- B3 itself keeps about D-21 with no archive (SILO contract).
- Queries run:
  - "casedevalor aluguel de ações histórico doador tomador"
  - "histórico aluguel de ações por ticker série histórica B3 empréstimo de ativos download site"
  - "B3 empréstimo de ativos negócios realizados corretora doadora tomadora arquivo histórico"
  - "Oplab aluguel de ações histórico taxa posição em aberto gráfico"
  - "ADVFN aluguel de ações ranking histórico BTC"
  - "Economatica empréstimo de ações aluguel dados históricos BTC"
  - "\"aluguel\" \"negócios\" B3 corretora doadora tomadora ranking corretoras…"
  - "quantumfinance aluguel de ações histórico saldo alugado free float série"
  - "\"Status Invest\" aluguel de ações \"histórico\" …"
  - "Investidor10 \"aluguel\" ação …"
- Pages checked: casedevalor /aluguel-de-acoes, /acoes/PETR4?tab=short, /smart-money, /planos, /sobre/metodologia; statusinvest /acoes/aluguel and /acoes/petr4; investidor10 /acoes/aluguel/ and /acoes/petr4/; nefin short-interest and loan-fees; the economatica blog; the b3.com.br lending pages.
- **Verdict:** the broker-legged trade tape is genuine white space. Long per-ticker open-position history is _not_ white space for paid S1 users (Economatica), but it is for free and S4 users, from the day SILO started accumulating onwards.

**(b) Public forensic screens: zombie FIDCs, captive FIIs, dormant funds, evergreen aging, overdue CRI/CRA.** None found as a standing public product.

- Painel FIDC (institutional, demo only) flags pattern shifts in PDD, aging and subordination, but no zombie or dormant screen is mentioned.
- Investidor10 ran a one-off article on 46 FIDCs that stopped filing.
- Mais Retorno labels "casca" funds.
- Journalism (Seu Dinheiro, O Tempo) analyses cases by hand.
- Queries run:
  - "FIDC zumbi fundos suspeitos levantamento dados CVM reportagem"
  - "fundos imobiliários exclusivos poucos cotistas levantamento dados CVM planejamento tributário reportagem"
  - "ferramenta pública detectar fundos de investimento suspeitos CVM dados abertos fraude FIDC painel"
  - "Fiquem Sabendo OR Abraji OR \"Agência Pública\" fundos de investimento CVM dados levantamento FIDC FIP"
  - "jornalismo de dados fundos de investimento CVM \"Banco Master\" FIDC …"
  - "fraudes FIDC operação Carbono Oculto fundos \"dados abertos\" CVM ferramenta …"
- **Verdict:** white space for free public S4 use, and demand is visible (Master, Carbono Oculto coverage). Watch Painel FIDC on the S2 side.

**(c) A public fund → holdings → issuer company → short book graph.** Not found.

- Mais Retorno has fund→holdings (CDA history back to 2014) and did an editorial reverse lookup (funds short Petrobras), but no stock→funds page and no lending join was seen.
- Status Invest shows only the top 10 holdings.
- Case de Valor "Smart Money" joins insiders, derivatives, short data and analysts into a score, with no fund holdings, and is proprietary.
- Painel FIDC does fund→fund look-through and cedente overlap (FIDC only, paid).
- Smart Money Research explains the CVM CDA manually.
- Queries run:
  - "quais fundos têm a ação carteira fundos CDA \"fundos que investem\" ação ticker site"
  - "Mais Retorno fundos que possuem ação posição fundos carteira PETR4"
  - "carteirafundos.com \"fundos que possuem\" ação"
  - "\"quais fundos compraram\" OR \"fundos que mais compraram\" ação CVM …"
  - "\"fundos que mais detêm\" OR \"fundos com maior posição\" ação ferramenta …"
- **Verdict:** white space, especially the debenture-issuer CNPJ → `cia_*` join, and the fund → stock → lending-book join.

**Also apparently unique among these platforms:**

- An explicit no-fabrication/provenance stance on a _free_ product. Painel FIDC makes a similar claim but is paid and FIDC-only.
- A free REST API over CVM + B3 + BACEN together. Mais Retorno has an API/MCP but is paid (Track 4).
- Investor-type flows (C19): none of these platforms showed it.

---

## 5. Sources

- https://statusinvest.com.br/acoes/petr4
- https://statusinvest.com.br/fundos-de-investimento
- https://statusinvest.com.br/fundos-de-investimento/encore-acoes-fia
- https://statusinvest.com.br/fundos-de-investimento/wa-di-max-premium-fic-de-fi-rf-ref
- https://statusinvest.com.br/fundos-imobiliarios/mxrf11
- https://statusinvest.com.br/acoes/aluguel
- https://statusinvest.com.br/acoes/busca-avancada
- https://statusinvest.com.br/fundos-imobiliarios/busca-avancada
- https://statusinvest.com.br/acoes/eua/rpm
- https://lp.statusinvest.com.br/ao/alpha/
- https://lp.statusinvest.com.br/ao/bull/
- https://lp.statusinvest.com.br/ao/forecast-relampago/
- https://investidor10.com.br/
- https://investidor10.com.br/acoes/petr4/
- https://investidor10.com.br/fiis/mxrf11/
- https://investidor10.com.br/fundos
- https://investidor10.com.br/fundos/ainvest-capital-inteligencia-artificial-global-fundo-de-investimento-financeiro-em-acoes
- https://investidor10.com.br/chat-ia/
- https://investidor10.com.br/pro2/
- https://investidor10.com.br/acoes/aluguel/ (410)
- https://investidor10.com.br/noticias/46-fundos-deixam-de-publicar-informacoes-e-acendem-alerta-no-mercado-122330/
- https://parse.bot/marketplace/fe86bbfe-6a00-46ea-897f-b5c3a3ec7dbf/investidor10-com-br-api
- https://casedevalor.com.br/aluguel-de-acoes
- https://casedevalor.com.br/acoes/PETR4?tab=short
- https://casedevalor.com.br/smart-money
- https://casedevalor.com.br/planos
- https://casedevalor.com.br/sobre/metodologia
- https://maisretorno.com/fundo/itau-acoes-top-5-fi/carteira
- https://maisretorno.com/portal/fundos-investem-queda-petrobras
- https://www.fundamentus.com.br/
- https://www.fundsexplorer.com.br/
- https://www.clubefii.com.br/planos_assinatura
- https://www.clubefii.com.br/plano-de-assinatura-fii-data-professional?ori=modulo_monitor
- https://kinvo.com.br/
- https://gorila.com.br/
- https://dados.cvm.gov.br/dataset/fi-doc-cda
- https://dados.cvm.gov.br/dataset/fidc-doc-inf_mensal
- https://www.rad.cvm.gov.br/ENET/frmConsultaExternaCVM.aspx
- https://fnet.bmfbovespa.com.br/fnet/publico/abrirGerenciadorDocumentosCVM
- https://www.b3.com.br/pt_br/produtos-e-servicos/emprestimo-de-ativos/renda-variavel/historico-de-emprestimos/
- /home/user/SILO-BZ/src/fetchers/b3_bdi_fetcher.py (SILO's verified BDI retention contract)
- https://nefin.com.br/data/short-interest/
- https://nefin.com.br/data/loan-fees/
- https://nefin.com.br/nefindata/short-interest/average_short_interest.csv
- https://brasil.io/datasets/
- https://basedosdados.org/dataset/9c5a820f-09dd-4519-adfd-611819163ae0
- https://www.economatica.com/blog/aluguel-de-acoes-estoque-de-contratos-de-banco-de-titulos-btc/
- https://www.economatica.com/blog/btc-banco-de-titulos-cblc/
- https://www.painelfidc.com.br/
- https://quantumfinance.com.br/aluguel-acoes-b3/
- https://tc.tradersclub.com.br/mais-alugadas-b3
- https://br.advfn.com/investimentos/aluguel-acoes
- https://smartmoneybrasil.com.br/uncategorized/descobrindo-as-carteiras-dos-fundos-de-investimento/
- https://www.otempo.com.br/economia/2026/9/7/explode-o-numero-de-fundos-que-podem-ocultar-o-dono-do-dinheiro-como-no-master-e-na-carbono-oculto
- https://www.seudinheiro.com/2026/economia/nova-fase-da-carbono-oculto-avanca-sobre-fundos-de-investimento-e-trustee-reaparece-como-elo-entre-estruturas-investigadas-pela-pf-miql/
