# Track 6: CNN (CNN Stocks deep profile, plus a sweep of CNN Brasil and CNN Business coverage)

Research date: 2026-09-23. The evidence rule from TAXONOMY.md applies throughout. Y and P values cite a URL that was fetched or a search excerpt that was seen. Inferences are labelled as inferences.

---

## 1. DEEP: CNN Stocks (stocks.cnnbrasil.com.br)

### Profile

- **Who:** CNN Brasil, as an extension of its CNN Money finance channel (the channel launched in November 2024). CNN Stocks launched on Monday, 13 April 2026 (Portal Tela). Trade press covered it on 14 April (adnews, Tela Viva) and later Meio & Mensagem. Tela Viva frames it as part of CNN Brasil's 2026 digital-innovation plan, which aims to make the broadcaster a technology-services provider as well as a news source.
- **What it is:** a retail market dashboard built from modular widgets, with CNN Money journalism layered on top. It is a quote, chart and news hub, not a data warehouse.
- **Data sources / licensors:** the press releases only say "parcerias estratégicas com provedores de infraestrutura de dados" and name no vendor. The **only third-party partner named on the site is TradingView.** The homepage embeds a "Markets — By TradingView" widget. The partner strip ("Conectado à inteligência de quem define o mercado") shows exactly two logos: CNN Brasil Money and TradingView, which links to br.tradingview.com. I checked this in the page HTML. The Terms of Use name no licensor. They say the data comes from "bolsas de valores", providers and APIs, and "podem sofrer atrasos". No B3, CVM, BACEN, ANBIMA or other data licensor is named anywhere I looked.
- **Coverage:** equities (Ibovespa ticker, quotes, heat map, gainers and losers), FIIs (quotes only; the meta description says "cotações de ações, FIIs, forex"), forex, quotes converted to BRL, a fixed-income calculator (a simulator, not a price feed), a macro event calendar, a corporate-events calendar, fatos relevantes and a dividend calendar. **Nothing I found mentions funds (FI), FIDC, FIP, FIAGRO, CRI/CRA, CDA holdings, statements/ITR/DFP data, lending/short interest, or investor-type flows.**
- **Pricing (from the site's plan table and the embedded plan JSON, which has `"price":"00.00"` and `"price":"49.90"`):**
  - _Plano Essencial_, free. Includes CNN Money streaming, quick quote, gainers and losers, currency converter, fixed-income calculator and technical analysis. Quotes in BRL, the market map, forex and the quote panel are "Limitado"; the quote panel is capped at 10 assets.
  - _Plano Premium_, **R$ 49,90 per month**. Everything in Essencial without limits, plus advanced charts, fatos relevantes, the corporate-events calendar, the dividend calendar ("Calendário de Proventos", feature code `DIVIDENDS_RADAR`), a watchlist and "Carteiras Recomendadas Exclusivas (em breve)".
- **Segment:** retail and self-directed investors "de todos os níveis de conhecimento". It is not built for S1 professionals, S2 structured credit, S3 developers or S4 accountability.
- **AI features:** **none is visible.** The 13–14 April press releases mention none (adnews, Portal Tela, Tela Viva). The homepage's feature list has none. The one mention is a line in the Terms of Use about "Recursos baseados em inteligência artificial para apoio informacional", with no named feature, no grounding approach and no disclaimer. The brief's phrase "AI tools" is **not supported by the evidence I found**. CNN Brasil's separate "vertical de Inteligência Artificial" (Tela Viva, 01 June 2026) is editorial coverage plus research with Instituto Locomotiva, not a product. Its "Plataforma de Dados Unificada" (Tela Viva, 17 November 2025) is an advertising audience-data platform.
- **Differentiators:** the CNN brand and audience, CNN Money streaming inside the dashboard, news curated for the user's assets, and a cheap premium tier.
- **Weaknesses:** it is a thin layer over TradingView widgets. There is no fund or structured-credit data, no API, no bulk download and no stated history. The disclaimers expressly say CNN "não garante exatidão absoluta" and that quotes "podem não ser precisos ou atualizados em tempo real". The feature copy includes leftover template text: "notificações regulares em tempo real sobre **pedidos, pagamentos e atividades do cliente**". Recommended portfolios are still marked "em breve" five months after launch, which sits oddly next to its "no advice" disclaimer.

### Grid

| ID                                   | value | evidence URL                                                                                                                                              | note                                                                                                                     |
| ------------------------------------ | ----- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| C1 FI funds NAV/flows                | ?     | https://stocks.cnnbrasil.com.br/                                                                                                                          | Not mentioned anywhere; absence inferred                                                                                 |
| C2 FIDC                              | ?     | https://stocks.cnnbrasil.com.br/                                                                                                                          | Not mentioned                                                                                                            |
| C3 FII                               | P     | https://stocks.cnnbrasil.com.br/ (meta description "cotações de ações, FIIs, forex")                                                                      | Quotes only; no informe data                                                                                             |
| C4 FIP/FIAGRO                        | ?     | —                                                                                                                                                         | Not mentioned                                                                                                            |
| C5 CRI/CRA                           | ?     | —                                                                                                                                                         | Not mentioned                                                                                                            |
| C6 ETF                               | ?     | —                                                                                                                                                         | Not mentioned (TradingView probably quotes ETFs; inference)                                                              |
| C7 CDA holdings                      | ?     | —                                                                                                                                                         | Not mentioned                                                                                                            |
| C8 listed-co statements              | ?     | https://stocks.cnnbrasil.com.br/                                                                                                                          | The homepage claims "análise técnica e fundamentalista" (marketing copy); no statements feature seen                     |
| C9 events / fatos relevantes         | Y     | https://stocks.cnnbrasil.com.br/ ; https://www.portaltela.com/noticias/economia/2026/04/13/cnn-brasil-lanca-cnn-stocks-plataforma-de-insights-de-mercado/ | Premium: `MATERIAL_FACTS` "Fatos Relevantes", `CORPORATE_EVENTS` calendar                                                |
| C10 ownership                        | ?     | —                                                                                                                                                         | —                                                                                                                        |
| C11 dividends                        | Y     | https://stocks.cnnbrasil.com.br/                                                                                                                          | Premium `DIVIDENDS_RADAR` "Calendário de Proventos"                                                                      |
| C12 estimates                        | ?     | —                                                                                                                                                         | —                                                                                                                        |
| C13 equities EOD                     | Y     | https://stocks.cnnbrasil.com.br/                                                                                                                          | Quotes, charts, heat map, gainers and losers                                                                             |
| C14 intraday / real-time             | P     | https://stocks.cnnbrasil.com.br/                                                                                                                          | `FAST_QUOTE` is described as "Cotações em tempo real", but the legal notice says quotes "podem não ser... em tempo real" |
| C15 options                          | ?     | —                                                                                                                                                         | —                                                                                                                        |
| C16 futures / DI                     | ?     | —                                                                                                                                                         | —                                                                                                                        |
| C17 secondary FI prices              | ?     | —                                                                                                                                                         | The fixed-income calculator is a simulator, not prices                                                                   |
| C18 lending / short                  | ?     | —                                                                                                                                                         | —                                                                                                                        |
| C19 investor-type flows              | ?     | —                                                                                                                                                         | —                                                                                                                        |
| C20 index composition                | ?     | —                                                                                                                                                         | Only the Ibovespa ticker is shown                                                                                        |
| C21 macro                            | P     | https://telaviva.com.br/14/04/2026/cnn-brasil-lanca-plataforma-de-insights-de-mercado-com-inteligencia-de-dados-para-investidores/                        | A macro event calendar (Premium) plus forex; no series data                                                              |
| C22 unstructured docs                | ?     | —                                                                                                                                                         | Fatos relevantes are shown as a feed; no full-text search seen                                                           |
| Q1 history depth                     | ?     | —                                                                                                                                                         | Not stated                                                                                                               |
| Q2 restatements                      | ?     | —                                                                                                                                                         | —                                                                                                                        |
| Q3 per-number citation               | ?     | https://stocks.cnnbrasil.com.br/termos-de-uso                                                                                                             | The terms only say data come from third parties in general                                                               |
| Q4 adjusted prices                   | ?     | —                                                                                                                                                         | —                                                                                                                        |
| Q5 point-in-time                     | ?     | —                                                                                                                                                         | —                                                                                                                        |
| A1 screeners                         | ?     | —                                                                                                                                                         | None seen                                                                                                                |
| A2 rankings                          | P     | https://adnews.com.br/post/cnn-brasil-lanca-cnn-stocks-nova-plataforma-de-inteligencia-e-dados-para-investidores                                          | Gainers, losers and most-traded lists                                                                                    |
| A3 peer comparison                   | ?     | —                                                                                                                                                         | —                                                                                                                        |
| A4 risk metrics                      | ?     | —                                                                                                                                                         | —                                                                                                                        |
| A5 forensic screens                  | ?     | —                                                                                                                                                         | —                                                                                                                        |
| A6 alerts                            | P     | https://stocks.cnnbrasil.com.br/                                                                                                                          | "Receba os fatos relevantes que impactam a sua carteira em tempo real"; the notification copy is template text           |
| A7 watchlist / portfolio             | Y     | https://stocks.cnnbrasil.com.br/                                                                                                                          | Premium `WATCHLIST`; quote panel limited to 10 assets on the free tier                                                   |
| A8 cross-entity joins                | ?     | —                                                                                                                                                         | —                                                                                                                        |
| X1 web UI                            | Y     | https://stocks.cnnbrasil.com.br/                                                                                                                          | Modular dashboard                                                                                                        |
| X2 Excel                             | ?     | —                                                                                                                                                         | —                                                                                                                        |
| X3 REST API                          | ?     | —                                                                                                                                                         | Not offered anywhere seen                                                                                                |
| X4 SDK                               | ?     | —                                                                                                                                                         | —                                                                                                                        |
| X5 MCP                               | ?     | —                                                                                                                                                         | —                                                                                                                        |
| X6 NL chat / AI                      | P     | https://stocks.cnnbrasil.com.br/termos-de-uso                                                                                                             | Only a terms line about "recursos baseados em IA para apoio informacional"; no feature seen                              |
| X7 bulk download                     | ?     | —                                                                                                                                                         | —                                                                                                                        |
| T1 no-fabrication / citation stance  | N     | https://stocks.cnnbrasil.com.br/ ; /termos-de-uso                                                                                                         | The legal text expressly disclaims accuracy ("não garante exatidão absoluta") instead of committing to citation          |
| T2 coverage / freshness transparency | P     | https://stocks.cnnbrasil.com.br/termos-de-uso                                                                                                             | Generic statements that data may be delayed; no per-dataset freshness                                                    |
| B1 free tier                         | Y     | https://stocks.cnnbrasil.com.br/                                                                                                                          | Plano Essencial                                                                                                          |
| B2 price                             | Y     | https://stocks.cnnbrasil.com.br/                                                                                                                          | Premium R$ 49,90 per month                                                                                               |
| B3 segment                           | —     | https://portaltela...                                                                                                                                     | Retail investors; not S1–S4 in SILO's sense                                                                              |
| O1 coverage growth                   | ?     | —                                                                                                                                                         | Vendor-fed (TradingView widgets; inference)                                                                              |
| O2 auditability                      | ?     | —                                                                                                                                                         | No claims                                                                                                                |

---

## 2. SHALLOW: new platforms found in the CNN sweep

**Trillia (B3's data and analytics brand).** Segments S1 (marginal) and S4 (marginal).
B3 launched Trillia in January–February 2026. It consolidates Neoway, Neurotech, PDTech, DataStock and the UIF. Its verticals are market intelligence/marketing, compliance and fraud, insurance, and credit and recovery. It claims more than 6,000 clients, about 150 data scientists and about 10% of B3 revenue (https://www.mobiletime.com.br/noticias/10/03/2026/trillia-ia-b3/ ; https://capitalaberto.com.br/empresas/2026/02/b3-lanca-trillia-marca-para-organizar-e-expandir-negocios-de-dados). CNN mentioned it in "B3 lança produto dados" results. It is enterprise B2B (credit scoring, KYC, fraud), not investor market data. Its overlap with the already-covered B3 UP2DATA is unclear; the mobiletime article does not mention UP2DATA. Notable capabilities: A5 P (AI fraud and anomaly detection, but for insurance and credit rather than securities), C22 P (it processes unstructured data such as audio). SILO has CVM fund and FIDC data and a free public API, which Trillia does not appear to offer (no investor product was found).

**Inteligência de Investimentos Itaú (bank AI investment agent).** Segment: retail and private clients, not S1–S4.
An agent in the Itaú Superapp that gives "assessoria hiperpersonalizada" 24/7. It draws on "curadoria de produtos, projeções internas e externas, algoritmos, avaliações de especialistas e bases específicas de conhecimento". Access expanded to 100k clients on 2 December 2025 (https://www.cnnbrasil.com.br/economia/negocios/itau-amplia-acesso-a-agente-de-investimentos-de-ia-para-100-mil-clientes/). X6 Y (closed, customers only). It recommends products within the client's shelf and cites no sources. SILO's no-advice, source-cited public data is the opposite model.

**ChatGPT for Financial Services (OpenAI).** Segment S1.
Covered by CNN Brasil on 10 September 2026. It runs on the GPT-6 Astra model, with Morgan Stanley and Evercore as design partners. Built-in data comes from LSEG, PitchBook, Daloopa, Crunchbase and Quartr; FactSet, S&P Global, Preqin and Datasite can be connected. It targets investment banking and equity research (https://www.cnnbrasil.com.br/economia/money/inteligencia-artificial/openai-lanca-versao-do-chatgpt-voltada-ao-setor-financeiro/). Capabilities: X6 Y, X5 P (connectors), C8 Y via licensors, C12 P (PitchBook, Daloopa). **No Brazilian data source (CVM, B3, BACEN) was mentioned.** That is an integration opening for SILO as a connector or MCP source (inference).

**Painel Receita (Receita Federal).** Segment S4 (marginal).
Launched 30 April 2026. It is free. Companies registered in Simples Nacional, or their representatives, see their own liquidity, profit, assets, revenue and debt. The data come from income-tax and Simples filings, with sector comparisons, 5-year history and projections (https://www.cnnbrasil.com.br/economia/negocios/receita-lanca-sistema-com-dados-sobre-todas-empresas-do-pais/). Access is restricted to the company itself (the headline wording "dados sobre todas empresas" is misleading). A3 Y for the company's own benchmark. It is not public investor data.

**NeoSpace (financial generative-AI foundation models; Itaú holds a 15% stake for US$15M).** Segment: bank infrastructure, not S1–S4.
It builds foundation models for personalization, credit modelling and conversational financial tips. Itaú has a commercial agreement with it (https://www.cnnbrasil.com.br/economia/negocios/itau-compra-participacao-em-startup-focada-em-ia-ao-mercado-financeiro/). It is not a data product. There are no Y capabilities in the grid.

**Yubb (investment search engine).** Segment: retail.
A free comparison engine covering more than 1,800 products from 170 banks, brokers and fintechs. It earns money from referrals (https://yubb.com.br/ ; Gazeta do Povo). Its founder was quoted in CNN's 31 May 2026 article on AI in investing. A2 P (product-yield comparison). I found no AI feature. It has no FIDC or CVM informe analytics.

Mentioned but not profiled (not data platforms): Inter's "Seven" AI assistant (a banking chatbot for Pix and similar tasks); Bull (a credit-infrastructure startup, R$20M seed); Clear Conta Global; B3's issuance platform for bank assets; Núclea.

**Regulatory items relevant to SILO (not platforms):**

- The BC–CVM agreement of 13 April 2026 on sharing credit-operation data, including securitizadoras and investment funds. The article frames it as supervisory and does not say the data will be public (https://www.cnnbrasil.com.br/economia/seu-bolso/meu-dinheiro/bc-e-cvm-fecham-acordo-para-integracao-de-dados-sobre-operacoes-de-credito/).
- CVM's new fund management system (SGF) (https://www.cnnbrasil.com.br/economia/macroeconomia/com-novo-sgf-cvm-preve-menor-custo-para-cumprir-obrigacoes-regulatorias/). Not fetched; it could change the fund-filing feeds (inference).

---

## 3. Gaps vs SILO (capabilities these platforms offer that SILO lacks)

**S1 (market professionals):**

1. Intraday / real-time quotes (C14): CNN Stocks via TradingView (P).
2. Watchlist and portfolio (A7): CNN Stocks Premium; Itaú's agent (portfolio optimisation).
3. Alerts and news tied to the user's holdings (A6): CNN Stocks (P).
4. NL chat grounded in licensed global data (X6/X5): ChatGPT for Financial Services (LSEG, FactSet, S&P and others). Itaú's agent is closed and customers only.
5. Technical-analysis charting with indicators (not in the grid; closest is X1): CNN Stocks advanced charts via TradingView.
6. A dividend calendar as a feature: CNN Stocks has one. SILO has corporate events, but no dedicated calendar UI (to confirm against the repo).

**Track segment (retail / media audience; closest SILO segment is S4):**

1. A news and journalism layer next to the data (CNN Money streaming and curated news).
2. A freemium consumer UX with a personal dashboard.
3. A fatos relevantes feed plus a corporate-events calendar in one consumer UI. SILO has the IPE data (C9) but serves it via API and pages, not a personal feed.
4. Macro event calendar (forward-looking dates). SILO has macro series, not a calendar.
5. Distribution through a broadcast brand.

---

## 4. What SILO has that none of these offer (white-space candidates)

Negative evidence: the CNN Stocks homepage (full HTML, including the embedded plan and feature JSON with 15 feature codes), its Terms of Use, four launch articles (adnews, Portal Tela, Tela Viva, Meio & Mensagem), and 14 searches restricted to cnnbrasil.com.br or cnn.com (listed below).

- **Fund-level CVM data (C1, C2, C4, C7) and FIDC credit metrics (tranches, aging, cedentes, sacados).** None of CNN Stocks' 15 feature codes covers funds. The site query for "FIDC plataforma dados" returned only explainers and market news. No CNN article covers a FIDC or structured-credit data platform.
- **Securities lending, short interest and investor-type flows (C18, C19).** Absent from CNN Stocks' feature list; no platform found in the sweep.
- **Forensic and suspicious-deal screens and dormant-fund screens (A5).** The only anomaly detection found is Trillia's insurance and credit fraud work, not securities.
- **A free public REST API with agent docs (X3, X5).** No API on CNN Stocks. OpenAI's financial ChatGPT names no Brazilian source, so a CVM, B3 or BACEN connector is an open slot (inference).
- **An explicit no-fabrication, provenance-first stance (T1, Q3).** CNN Stocks' legal text disclaims accuracy instead.
- **Cross-entity joins (A8), such as a fund to a debenture issuer to a listed company.** Not found anywhere in the sweep.

---

## 5. Queries run (Part B sweep)

Result counts are the number of links the search tool returned. "Relevant" means a new platform or data item, excluding platforms on the exclusion list.

| #   | Query                                                                  | Domain filter    | Results | Relevant                                                                                                                                                                                       |
| --- | ---------------------------------------------------------------------- | ---------------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | "CNN Stocks" CNN Brasil plataforma lançamento                          | none             | 10      | CNN Stocks press                                                                                                                                                                               |
| 2   | telaviva CNN Stocks CNN Brasil dados parceiros inteligência artificial | none             | 10      | CNN Stocks; CNN AI vertical; CNN data platform (adtech)                                                                                                                                        |
| 3   | plataforma dados investidores lança 2026                               | cnnbrasil.com.br | 10      | Painel Receita                                                                                                                                                                                 |
| 4   | inteligência artificial investimentos lança plataforma                 | cnnbrasil.com.br | 10      | OpenAI ChatGPT FS; Inter Seven                                                                                                                                                                 |
| 5   | fintech dados mercado financeiro plataforma                            | cnnbrasil.com.br | 10      | none                                                                                                                                                                                           |
| 6   | agente IA fundos de investimento                                       | cnnbrasil.com.br | 10      | Itaú agent                                                                                                                                                                                     |
| 7   | FIDC plataforma dados                                                  | cnnbrasil.com.br | 10      | none (explainers only)                                                                                                                                                                         |
| 8   | CVM dados abertos                                                      | cnnbrasil.com.br | 10      | BC–CVM agreement; CVM SGF; CVM survey (2022)                                                                                                                                                   |
| 9   | corretora lança assistente IA investidores XP BTG Nubank               | cnnbrasil.com.br | 10      | none new                                                                                                                                                                                       |
| 10  | B3 inteligência artificial Área do Investidor análise ações            | cnnbrasil.com.br | 10      | One excerpt says B3's Área do Investidor has offered an AI/ML stock-comparison tool since 2025. No article URL isolated it; the fetched 31 May article did not name it, so it stays unverified |
| 11  | terminal dados mercado financeiro startup brasileira lança             | cnnbrasil.com.br | 10      | NeoSpace; Bull                                                                                                                                                                                 |
| 12  | crédito privado plataforma monitoramento dados lança debêntures        | cnnbrasil.com.br | 10      | none                                                                                                                                                                                           |
| 13  | securitização CRI CRA plataforma tecnologia dados                      | cnnbrasil.com.br | 10      | none                                                                                                                                                                                           |
| 14  | B3 lança produto dados investidores 2026                               | cnnbrasil.com.br | 10      | Trillia                                                                                                                                                                                        |
| 15  | Brazil fintech AI investment data platform                             | cnn.com          | 10      | none                                                                                                                                                                                           |
| 16  | Trillia B3 marca dados analytics                                       | none             | 9       | Trillia details                                                                                                                                                                                |
| 17  | Yubb comparador investimentos inteligência artificial                  | none             | 9       | Yubb                                                                                                                                                                                           |
| 18  | NeoSpace IA mercado financeiro modelo fundacional Itaú                 | cnnbrasil.com.br | 10      | NeoSpace                                                                                                                                                                                       |

---

## 6. Sources

- https://stocks.cnnbrasil.com.br/ (fetched, including the raw HTML with the plan JSON)
- https://stocks.cnnbrasil.com.br/termos-de-uso
- https://adnews.com.br/post/cnn-brasil-lanca-cnn-stocks-nova-plataforma-de-inteligencia-e-dados-para-investidores
- https://www.portaltela.com/noticias/economia/2026/04/13/cnn-brasil-lanca-cnn-stocks-plataforma-de-insights-de-mercado/
- https://telaviva.com.br/14/04/2026/cnn-brasil-lanca-plataforma-de-insights-de-mercado-com-inteligencia-de-dados-para-investidores/
- https://www.meioemensagem.com.br/midia/cnn-stocks-veiculo-cria-plataforma-voltada-a-investidores
- https://www.portaltvstreaming.com.br/2026/04/cnn-brasil-lanca-cnn-stocks-plataforma.html (search excerpt only)
- https://telaviva.com.br/01/06/2026/cnn-brasil-lanca-vertical-de-inteligencia-artificial/ (excerpt)
- https://telaviva.com.br/17/11/2025/cnn-brasil-lanca-plataforma-de-dados-unificada/ (excerpt)
- https://www.cnnbrasil.com.br/economia/money/mercado/ia-avanca-no-mercado-financeiro-e-molda-decisoes-de-investimento/
- https://www.cnnbrasil.com.br/economia/negocios/itau-amplia-acesso-a-agente-de-investimentos-de-ia-para-100-mil-clientes/
- https://www.cnnbrasil.com.br/economia/money/inteligencia-artificial/openai-lanca-versao-do-chatgpt-voltada-ao-setor-financeiro/
- https://www.cnnbrasil.com.br/economia/negocios/receita-lanca-sistema-com-dados-sobre-todas-empresas-do-pais/
- https://www.cnnbrasil.com.br/economia/seu-bolso/meu-dinheiro/bc-e-cvm-fecham-acordo-para-integracao-de-dados-sobre-operacoes-de-credito/
- https://www.cnnbrasil.com.br/economia/seu-bolso/meu-dinheiro/cvm-lanca-pesquisa-sobre-como-investidores-acessam-dados-das-demonstracoes-financeiras/
- https://www.cnnbrasil.com.br/economia/negocios/itau-compra-participacao-em-startup-focada-em-ia-ao-mercado-financeiro/ (excerpt)
- https://www.mobiletime.com.br/noticias/10/03/2026/trillia-ia-b3/
- https://capitalaberto.com.br/empresas/2026/02/b3-lanca-trillia-marca-para-organizar-e-expandir-negocios-de-dados (excerpt)
- https://yubb.com.br/ (excerpt)
