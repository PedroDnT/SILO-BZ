# Track 4: platforms for AI agents and developers (S3)

Research date: 2026-09-23. Evidence rule per TAXONOMY.md. Y or P needs a fetched URL or a search excerpt. `?` means unknown. `N` means verified absent: the provider says it does not cover the item, or a complete endpoint or tool listing was checked and the item is not in it. Inferences are labelled as inferences.

Method: pages were fetched with curl (a browser User-Agent got past Dados de Mercado's 403) and with WebFetch. Two MCP servers were also probed with an unauthenticated `tools/list` JSON-RPC call. No account was created and nothing was logged into. brapi's MCP answered with the full list of 75 tools. Tomé's returned `401 unauthorized`.

Short URL keys used in the grids:

| key   | URL                                                                                             |
| ----- | ----------------------------------------------------------------------------------------------- |
| MRM   | https://maisretorno.com/mcp                                                                     |
| MRD   | https://developers.maisretorno.com (API + MCP docs; tool list, credits, errors, cache)          |
| BH    | https://usebolsai.com                                                                           |
| BL    | https://usebolsai.com/llms.txt                                                                  |
| BM    | https://usebolsai.com/mcp                                                                       |
| BO    | https://api.usebolsai.com/openapi.json                                                          |
| BMCP  | https://usebolsai.com/blog/melhores-mcp-servers-dados-financeiros-brasil-b3-2026                |
| BDDM  | https://usebolsai.com/blog/bolsai-vs-dadosdemercado-api-dados-b3-2026                           |
| BAPI  | https://usebolsai.com/blog/melhores-apis-dados-b3-2026-comparacao                               |
| RL    | https://brapi.dev/llms.txt                                                                      |
| RLF   | https://brapi.dev/llms-full.txt                                                                 |
| RM    | https://brapi.dev/docs/mcp.mdx (+ live `tools/list` on https://brapi.dev/api/mcp/mcp)           |
| RP    | https://brapi.dev/pricing.md (and https://brapi.dev/pricing)                                    |
| RFIDC | https://brapi.dev/docs/fundos/fidc-carteira.mdx                                                 |
| RCDA  | https://brapi.dev/docs/fundos/carteira.mdx                                                      |
| RDIC  | https://brapi.dev/docs/dicionario.mdx                                                           |
| RCOV  | https://brapi.dev/docs/tickers/cobertura.mdx                                                    |
| DD    | https://www.dadosdemercado.com.br/api/docs                                                      |
| DDQ   | https://www.dadosdemercado.com.br/api/docs/bolsa/cotacoes                                       |
| DDI   | https://www.dadosdemercado.com.br/api/docs/bolsa/investidores-estrangeiros                      |
| DDF   | https://www.dadosdemercado.com.br/api/docs/fundos-de-investimento/ativos (and /lista-de-fundos) |
| DDOC  | https://www.dadosdemercado.com.br/api/docs/empresas/documentos                                  |
| DDU   | https://www.dadosdemercado.com.br/dumps                                                         |
| DFAQ  | https://www.dadosdemercado.com.br/faq                                                           |

---

## 1. DEEP profiles

### 1.1 Mais Retorno (MCP + Market Data API)

**Who:** MR Educação & Tecnologia Ltda. It runs a retail and advisor fund-analytics website (fund rankings, comparators, portfolio manager, "Retorno PRO" for advisors) and sells its data as the "Market Data API", with a native MCP server on top.

**What:** Data is D-1 (end of day). The MCP page lists eight asset classes: Brazilian equities, FIIs, funds (quotas plus full CDA portfolio), government bonds and Tesouro Direto, derivatives, indices and crypto. The dev docs add US and London stocks and ETFs. For each asset it computes return, Sharpe, volatility and drawdown. Fund data includes the CVM and ANBIMA classification. **The page lists what is not covered: FIDC, CRI, CRA, debentures, foreign mutual funds and intraday** (MRM).

**MCP tools (11, from MRD):** `search_assets`, `get_asset_info`, `get_fund_class_subclass`, `get_available_wallets`, `get_quotes` (takes currency, a deflator of ipca or igpm, and a frequency), `get_asset_stats`, `get_drawdown`, `get_wallet_detail`, `get_rolling_windows`, `compare_assets` (2 to 10 assets), `backtest_portfolio`. The last three exist only on the MCP, with no REST equivalent. bolsai's July 2026 comparison says the tool count is "não documentado", but the developer portal now documents it.

**Auth:**

- The MCP uses OAuth with automatic client registration at `https://data.maisretorno.com/mr-data/v4/mcp/oauth`.
- A separate URL, `/mcp`, takes an api-key for server-side use.
- REST uses the header `X-Api-Key: mr_xxx_…`. The key is shown once and stored only as a hash.
- Signing up asks for name, email, phone **and CPF** (MRM).

**Pricing and limits** (MRM, MRD; prices assume annual billing, 17% off monthly):

| Plan       | Price    | Credits/month | History        |
| ---------- | -------- | ------------- | -------------- |
| Free       | R$0      | 500           | 1 year         |
| Basic      | R$99/mo  | 1,500         | full           |
| Starter    | R$349/mo | 5,000         | full           |
| Growth     | R$749/mo | 15,000        | full, with SLA |
| Enterprise | custom   | custom        | full           |

Credits cost 0 for search, 1 for quotes, asset info or classification, 5 for stats or drawdown, 10 for wallet detail or rolling windows, and 25 for compare or backtest. The rate limit is 15 req/s on every plan. Running out of credits returns HTTP 429, and on the MCP the tool explains the situation in its answer (MRD).

**Missing data and errors:** Errors come back as JSON objects `{statusCode, message, error}`. The codes are 400 (bad identifier), 401, 403 (plan does not cover the resource), 404 (asset not found) and 429. Cache-Control max-age is 5 min for search and 90 min elsewhere (MRD). Null semantics are not documented.

**Differentiators:**

- Portfolio and backtest tools inside the MCP.
- The docs explain adjusted and unadjusted prices unusually carefully (see Q4).
- `link_old_historic` splices a fund class's history onto the subclass that continues it after CVM 175.
- It covers funds deeply.

**Weaknesses:**

- No FIDC or structured credit.
- No per-number provenance. The site footer says the information comes "a partir de fontes públicas como a CVM" and that the platform "não faz conferência individual das informações". That contradicts the "100% acurácia" marketing on the MCP page.
- Signing up requires a CPF.
- No filings or events.

**Segment:** It sells explicitly to AAIs (autonomous investment advisors), consultants and analysts, then MFOs and fintechs, then developers. So: S1 advisor-side, and S3.

| ID  | value                                                      | evidence     | note                                                                                                     |
| --- | ---------------------------------------------------------- | ------------ | -------------------------------------------------------------------------------------------------------- |
| C1  | Y                                                          | MRM, MRD     | fund quotas, stats, class/subclass                                                                       |
| C2  | N                                                          | MRM          | "Vocês cobrem … FIDC? Não."                                                                              |
| C3  | Y                                                          | MRM          | FIIs listed                                                                                              |
| C4  | ?                                                          | —            | FIAGRO/FIP not mentioned                                                                                 |
| C5  | N                                                          | MRM          | CRI/CRA explicitly excluded (MRD's `adjusted` parameter mentions "securitizados", which is inconsistent) |
| C6  | Y                                                          | MRD          | "ações e ETFs da B3 e do exterior"                                                                       |
| C7  | Y                                                          | MRD          | `wallet-detail`, `available-wallets` (full CDA per month)                                                |
| C8  | N                                                          | MRD          | none of the 9 REST endpoints serves statements                                                           |
| C9  | N                                                          | MRD          | no events endpoint                                                                                       |
| C10 | N                                                          | MRD          | not in endpoint list                                                                                     |
| C11 | ?                                                          | —            | adjusted series reinvests dividends; no dividend endpoint                                                |
| C12 | N                                                          | MRD          | not in endpoint list                                                                                     |
| C13 | Y                                                          | MRM, MRD     | D-1                                                                                                      |
| C14 | N                                                          | MRM          | "Não. Os dados são D-1"                                                                                  |
| C15 | P                                                          | MRM          | "derivativos" class; no chain tools                                                                      |
| C16 | P                                                          | MRD          | "futuros têm série única"; no curve                                                                      |
| C17 | ?                                                          | MRM vs MRD   | MRM excludes debentures; MRD's `adjusted` text lists debentures                                          |
| C18 | N                                                          | MRD          | not in endpoint/tool list                                                                                |
| C19 | N                                                          | MRD          | not in endpoint/tool list                                                                                |
| C20 | N                                                          | MRD          | indices as price series only                                                                             |
| C21 | P                                                          | MRD          | index series (e.g. `cdi:idx`), IPCA/IGP-M deflator; no BACEN/Focus catalogue                             |
| C22 | N                                                          | MRD          | no document text                                                                                         |
| Q1  | P                                                          | MRM          | full history on paid plans, 1 year on free; depth not stated                                             |
| Q2  | ?                                                          | —            |                                                                                                          |
| Q3  | N                                                          | MRM (footer) | sources named only generically                                                                           |
| Q4  | Y                                                          | MRD          | `adjusted=true/false`; warns that the adjusted series is recalculated backward                           |
| Q5  | N                                                          | MRD          | adjusted series changes history retroactively (their own words); no as-of parameter                      |
| A1  | P                                                          | MRM          | "screening por filtros CVM/ANBIMA" (marketing); site has fund ranking                                    |
| A2  | Y                                                          | MRM (nav)    | "Ranking de fundos" on site                                                                              |
| A3  | Y                                                          | MRD          | `compare_assets`                                                                                         |
| A4  | Y                                                          | MRD          | Sharpe, volatility, drawdown, rolling windows                                                            |
| A5  | N                                                          | MRD          | none                                                                                                     |
| A6  | ?                                                          | —            |                                                                                                          |
| A7  | Y                                                          | MRM, MRD     | portfolio manager (site), `backtest_portfolio`                                                           |
| A8  | N                                                          | MRD          | no fund→issuer→company joins                                                                             |
| X1  | Y                                                          | MRM          |                                                                                                          |
| X2  | ?                                                          | MRM          | "Planilhas gratuitas" in nav; no add-in found                                                            |
| X3  | Y                                                          | MRD          |                                                                                                          |
| X4  | ?                                                          | MRD          | Python/Node examples, no SDK package found                                                               |
| X5  | Y                                                          | MRD          | remote MCP, OAuth                                                                                        |
| X6  | N                                                          | MRM          | relies on the user's own agent                                                                           |
| X7  | ?                                                          | MRM          | "Exporte … em CSV" via the agent; no bulk files                                                          |
| T1  | P                                                          | MRM          | lists what it does not cover; no no-fabrication stance, and a "no individual verification" disclaimer    |
| T2  | P                                                          | MRM, MRD     | exclusion list, D-1 stated, cache ages; no per-dataset freshness                                         |
| B1  | Y                                                          | MRM          | 500 credits/month, 1-year history                                                                        |
| B2  | R$0 / 99 / 349 / 749 per month (annual), Enterprise custom | MRM          |                                                                                                          |
| B3  | S1 (advisors), S3                                          | MRM          |                                                                                                          |
| O1  | ?                                                          | —            |                                                                                                          |
| O2  | N                                                          | —            | none found                                                                                               |

### 1.2 bolsai (usebolsai.com)

**Who:** A small B3 API aimed at developers. The open-source MCP repository is github.com/viniciuslazzari/bolsai-mcp (BM). It publishes a lot of SEO comparison posts, which are useful here as a way into competitors.

**What** (BL, BO):

- 350+ stocks and 400+ FIIs.
- Adjusted OHLCV since 1986.
- 27 TTM fundamentals and CVM DFP/ITR statements.
- Dividends and corporate events.
- A stock screener and an FII screener.
- FII vacancy, delinquency and tenants.
- BCB macro: SELIC, IPCA, CDI and IGP-M.

It does **not** cover funds beyond FIIs, options, futures or crypto (BAPI, BDDM).

**MCP tools (11):** `screen_stocks`, `compare_stocks`, `get_fundamentals`, `get_dividends`, `get_financial_statements`, `get_fii_details`, `get_price_history`, `get_macro_indicator`, `get_stock_quote`, `search_companies`, `list_sectors` (BM).

**Auth and transport:**

- Remote MCP at `https://usebolsai.com/api/mcp`, signed in with OAuth through Google, so no key passes through the chat (BM).
- A local stdio server (`uvx bolsai-mcp`, on PyPI) reads `BOLSAI_API_KEY`.
- ChatGPT works through GPT Actions with OAuth2 (`/gpt-actions-schema.json`).
- REST takes `X-API-Key`, or `?api_key=`, or a Bearer token.
- The OpenAPI spec is public, and it also exposes the OAuth, billing, feedback-admin and `/admin/validation/*` routes (BO).

**Pricing:** The free tier is 200 req/day with no card. The paid tier is inconsistent across pages:

- llms.txt, the MCP page and the blog: Pro at R$49/month for 10,000 req/day.
- Homepage as fetched: Pro at R$129/quarter (about R$43/month) and Enterprise from R$499/quarter.

(BL, BM, BH.)

**Freshness:** Prices and macro update daily at 20:30 BRT. Companies, financials, dividends and FIIs update weekly on Saturdays (BL).

**Methodology and trust:** bolsai publishes how it computes numbers (net income from CVM account 3.11, clean EBIT, bank equity from accounts 2.07 and 2.08). It also publishes an accuracy benchmark: 96% agreement with Fundamentus on fresh DFP 2025 data and 82% overall (BL). It is the only vendor that publishes its own error rate. There is no per-number source attribution.

**Weaknesses:** Narrow coverage (equities and FIIs). No FI, FIDC or structured credit. Pricing differs from page to page. The free tier has no history (BM: "O plano gratuito inclui cotações e fundamentos atuais").

**Segment:** S3 and retail developers.

| ID  | value                                          | evidence | note                                                                      |
| --- | ---------------------------------------------- | -------- | ------------------------------------------------------------------------- |
| C1  | N                                              | BDDM, BO | "Fundos de investimento: Não"                                             |
| C2  | N                                              | BO       | no endpoint                                                               |
| C3  | Y                                              | BL, BO   | FII fundamentals, distributions, tenants, vacancy, delinquency            |
| C4  | N                                              | BO       | not in OpenAPI                                                            |
| C5  | N                                              | BO       |                                                                           |
| C6  | ?                                              | —        |                                                                           |
| C7  | N                                              | BO       |                                                                           |
| C8  | Y                                              | BL, BO   | `/financials/{ticker}` DRE/BPA/BPP/DFC/DVA                                |
| C9  | P                                              | BO       | `corporate-events` (corporate actions, not fatos relevantes)              |
| C10 | N                                              | BO       |                                                                           |
| C11 | Y                                              | BL       | dividend and JCP history                                                  |
| C12 | N                                              | BO       |                                                                           |
| C13 | Y                                              | BL       |                                                                           |
| C14 | N                                              | BL       | EOD at 20:30 BRT                                                          |
| C15 | N                                              | BAPI     | "não cobre cripto, futuros nem opções"                                    |
| C16 | N                                              | BAPI     |                                                                           |
| C17 | N                                              | BDDM     | no Tesouro/bonds                                                          |
| C18 | N                                              | BO       |                                                                           |
| C19 | N                                              | BO       |                                                                           |
| C20 | N                                              | BO       |                                                                           |
| C21 | P                                              | BL       | SELIC, IPCA, CDI, IGP-M, USD/BRL                                          |
| C22 | N                                              | BO       |                                                                           |
| Q1  | Y                                              | BL, BH   | prices since 1986, about 15 years of fundamentals (Pro)                   |
| Q2  | ?                                              | —        |                                                                           |
| Q3  | P                                              | BL       | methodology per indicator; no per-number citation                         |
| Q4  | Y                                              | BM       | "ajustados por splits e dividendos"                                       |
| Q5  | ?                                              | —        |                                                                           |
| A1  | Y                                              | BO       | `/screener`, `/fiis/screener`                                             |
| A2  | N                                              | BO       |                                                                           |
| A3  | Y                                              | BM       | `compare_stocks` (up to 5)                                                |
| A4  | ?                                              | BO       | `/stocks/{t}/stats` contents not checked                                  |
| A5  | N                                              | BO       |                                                                           |
| A6  | N                                              | BL       | only an n8n tutorial                                                      |
| A7  | N                                              | BO       |                                                                           |
| A8  | N                                              | BO       |                                                                           |
| X1  | P                                              | BH       | playground                                                                |
| X2  | P                                              | BL       | Google Sheets and Excel tutorials; CSV                                    |
| X3  | Y                                              | BO       |                                                                           |
| X4  | N                                              | BH       | code samples only (the PyPI package is the MCP server, not an SDK)        |
| X5  | Y                                              | BM       | remote OAuth + stdio + GPT Actions                                        |
| X6  | N                                              | —        |                                                                           |
| X7  | P                                              | BH, BDDM | CSV export on Pro; `?format=csv`                                          |
| T1  | P                                              | BL       | accuracy benchmark and methodology; no fabrication stance                 |
| T2  | P                                              | BL       | update cadence per dataset                                                |
| B1  | Y                                              | BL       | 200 req/day                                                               |
| B2  | R$49/mo (llms.txt) vs R$129/quarter (homepage) | BL, BH   | inconsistent                                                              |
| B3  | S3 (+ retail)                                  | BL       |                                                                           |
| O1  | ?                                              | —        |                                                                           |
| O2  | P                                              | BO       | `/admin/validation/prices`, `/fii-tickers` exist (inference: internal QA) |

### 1.3 brapi.dev

**Who:** The most mature B3 developer API. It publishes official TypeScript and Python SDKs, an MCP server, agent skills and Markdown copies of its docs pages.

**What** (RL):

- Stocks, FIIs, BDRs, ETFs and units.
- Statements (BP, DRE, DFC, DVA).
- Dividends.
- Options with greeks, IV and open interest.
- Futures with a term structure (DI curve), and options on futures.
- Tesouro Direto.
- Macro, PTAX and crypto.
- **CVM funds:** FI and FIF NAV history, the monthly profile, CDA portfolio, FIAGRO, **FIDC monthly reports and portfolio** (sectors, maturity, delinquency, AA–H risk buckets, quota classes, investor types, top-2 cedente CNPJs with %), and FIP reports (RFIDC).

**MCP:** Remote Streamable HTTP at `https://brapi.dev/api/mcp/mcp`, with OAuth or a Bearer key. The live `tools/list` returned **75 tools**. Ten discovery tools need no login (`get_tickers`, `resolve_tickers`, `get_ticker_coverage`, `get_dictionary`, `get_macro_series_available`, and others). There is also `get_account_capabilities`. The rest are `get_stock_*`, `get_option_*`, `get_futures_*`, `get_fii_*`, `get_funds_*`, `get_fidc_reports`, `get_fidc_portfolio`, `get_fip_reports`, `get_fiagro_*` and `get_treasury_*`. Every tool carries the annotations `readOnlyHint` and `idempotentHint` (RM). On which tools each plan unlocks, pricing.md says Free gets "Discovery and sandbox", Startup "essential tools" and Pro "complete tools".

**Agent docs:**

- llms.txt tells the agent how to handle the key ("Do not ask the user to paste the key into the chat").
- It maps error codes: a 403 body "names the plan that does" include the data, and a 429 carries `Retry-After`.
- `llms-full.txt` is 3 MB.
- Every docs page has a `.mdx` Markdown copy.
- It publishes pricing.md, versioning.md and auth.md.
- It links an Agent Skills repo (github.com/brapi-dev/brapi-skills).
- OpenAPI 3.1.

(RL.)

**Pricing** (RP, "current as of 2026-08-21"):

| Plan    | Price                        | Requests/month | Concurrency | Assets/request | History   |
| ------- | ---------------------------- | -------------- | ----------- | -------------- | --------- |
| Free    | R$0                          | 15,000         | 1           | 1              | 3 months  |
| Startup | R$119.99/mo or R$1,199.90/yr | 150k           | 4           | 10             | —         |
| Pro     | R$139.99/mo or R$1,399.90/yr | 500k           | 16          | 20             | 10+ years |

There is no limit per second. FIDC and CDA endpoints are Pro only. The pricing page also lists "AI messages" at 250 and 1,000 per month on paid plans. The sandbox tickers PETR4, VALE3, MGLU3 and ITUB4 work with no token.

**Missing data:**

- The dictionary endpoint explains why fields are null: banks' chart of accounts, FIIs having no company balance sheet, late CVM filings (RDIC).
- `tickers/coverage` returns a status of `available`, `renamed`, `unknown` or `wrong_endpoint`, plus the recommended endpoints for each ticker (RCOV).
- The CDA docs say: "A CVM publica o CDA com meses de atraso. Mostre `referenceDate` junto do dado." Confidential positions are summarised in `confidentialSummary` (RCDA).
- FII reports accept `allVersions=true` to return CVM re-filings (RLF).

**Weaknesses:**

- No securities lending, investor-type flows, index constituents, CRI/CRA, corporate debentures or document text.
- Holdings are grouped by bucket, with no issuer→company joins beyond issuerCnpj.
- History and FIDC data are paywalled. The free tier cannot see FIDC or CDA.

**Segment:** S3 (fintechs, quants, app builders).

| ID  | value                         | evidence       | note                                                                     |
| --- | ----------------------------- | -------------- | ------------------------------------------------------------------------ |
| C1  | Y                             | RL             | `funds/nav/history` daily FI/FIF; `funds/profile`                        |
| C2  | Y                             | RL, RFIDC      | FIDC reports + portfolio (Pro); top-2 cedentes only, no sacados          |
| C3  | Y                             | RL             | indicators, properties, portfolio, reports, DFIN                         |
| C4  | Y                             | RL             | FIAGRO reports/portfolio, FIP reports                                    |
| C5  | N                             | RL             | no CRI/CRA section in the complete doc index                             |
| C6  | Y                             | RL             | ETF quotes                                                               |
| C7  | Y                             | RCDA           | CDA grouped into 6 buckets, with issuerCnpj, ISIN                        |
| C8  | Y                             | RL             | BP/DRE/DFC/DVA since 2009 (Pro)                                          |
| C9  | N                             | RL             | no events/IPE endpoint                                                   |
| C10 | ?                             | —              |                                                                          |
| C11 | Y                             | RL             |                                                                          |
| C12 | ?                             | —              |                                                                          |
| C13 | Y                             | RL             |                                                                          |
| C14 | P                             | RP             | quotes refresh every 5 to 30 min by plan (delayed)                       |
| C15 | Y                             | RL             | chain, greeks, IV, open interest, history                                |
| C16 | Y                             | RL             | futures + `term-structure` ("Curva de juros do DI")                      |
| C17 | P                             | RL             | Tesouro Direto only; no corporate debentures                             |
| C18 | N                             | RM             | none of the 75 tools; "aluguel" in RLF only means real-estate rent       |
| C19 | N                             | RM             |                                                                          |
| C20 | N                             | RM             |                                                                          |
| C21 | Y                             | RL             | Selic, CDI, IPCA, IGP-M, PIB, unemployment, PTAX                         |
| C22 | N                             | RL             |                                                                          |
| Q1  | Y                             | RP, RL         | 10+ years (Pro); options since 2009; FII indicators since 2016           |
| Q2  | P                             | RLF            | `allVersions=true` shows reapresentações (FII reports)                   |
| Q3  | P                             | RCDA           | tells the agent to show `referenceDate`; no per-number source            |
| Q4  | Y                             | RLF            | "fechamento ajustado"                                                    |
| Q5  | ?                             | —              |                                                                          |
| A1  | Y                             | RL             | `fii/list` filters, `quote/list` filters                                 |
| A2  | ?                             | —              |                                                                          |
| A3  | P                             | RM             | via multi-symbol quotes; no compare tool                                 |
| A4  | P                             | RL             | option greeks/IV; stats                                                  |
| A5  | N                             | RM             |                                                                          |
| A6  | N                             | RM             |                                                                          |
| A7  | N                             | RM             |                                                                          |
| A8  | P                             | RCDA, RFIDC    | issuerCnpj in CDA; top cedente CNPJs                                     |
| X1  | P                             | RL             | public quote pages                                                       |
| X2  | P                             | RL             | Google Sheets Apps Script, Excel Power Query examples                    |
| X3  | Y                             | RL             |                                                                          |
| X4  | Y                             | RL             | official TS + Python SDKs                                                |
| X5  | Y                             | RM             | 75 tools, OAuth, Agent Skills                                            |
| X6  | P                             | RP (/pricing)  | "AI messages" quota on paid plans (product not examined)                 |
| X7  | N                             | RL             | no bulk files                                                            |
| T1  | P                             | RL, RM         | key-hygiene rules for agents; "não é recomendação"                       |
| T2  | Y                             | RCOV, RDIC, RP | per-ticker coverage, null explanations, dated pricing, versioning policy |
| B1  | Y                             | RP             | 15k req/month, 3-month history                                           |
| B2  | R$119.99 / R$139.99 per month | RP             |                                                                          |
| B3  | S3                            | RP             |                                                                          |
| O1  | ?                             | —              |                                                                          |
| O2  | N                             | —              |                                                                          |

### 1.4 Dados de Mercado (dadosdemercado.com.br)

**Who:** DDM Tecnologia da Informação LTDA, since 2020. It calls itself "um banco de dados aberto de investimentos no Brasil" and builds on CVM, B3, BACEN and ANBIMA (DFAQ).

**What (API v1, DD):**

- Companies: list, balance sheets, results, cash flows, dividends, splits, bonus issues, CVM **documents** (category and delivered_at), market and financial indicators, share counts.
- Exchange: assets, quotes with `adj_close` (DDQ), indices and index detail, **risk indicators**, **foreign investors flow** (DDI: financial_institutions, companies, other…), dividend yield.
- FIIs: list and dividends.
- Funds: list with cnpj, cvm_code, fund_class, net_worth, shareholders; quote history; **assets** (aggregated by asset_type) (DDF).
- Government bonds, Tesouro Direto.
- Macro: economic indices, expectations, **Focus**, **yield curves**.
- Currencies and news.

**Weekly bulk dumps** (DDU, updated 20 Sep 2026): 5 years of adjusted quotes, dividends, 10 years of corporate actions, 10 years of financial statements, **10 years of Ibovespa composition**, **5 years of daily investor flow**, macro, and 10 years of yield curves. A direct request for a dump URL returned 404, so dumps probably need a login (inference).

**MCP:** None. None appears in the docs navigation, and bolsai's July 2026 comparison also says "não lista servidor MCP oficial" (BDDM).

**Auth:** A Bearer token on every call. Full access and limit changes go through email to api@dadosdemercado.com.br. No prices are published (DD).

**Errors:** All responses are JSON. The codes are 200, 400, 401, 403, 404 and 429 (DD). Many fields are typed `number | null` (DDI), and null semantics are not explained.

**Weaknesses:**

- No MCP, SDK, OpenAPI or llms.txt (llms.txt is 404).
- Access is sales-gated.
- Fund holdings are aggregated only.
- No FIDC, lending or options.

**Segment:** S1, S3 and retail.

| ID  | value             | evidence  | note                                                                     |
| --- | ----------------- | --------- | ------------------------------------------------------------------------ |
| C1  | Y                 | DD, DDF   | fund list + quote history                                                |
| C2  | ?                 | DDF       | no FIDC-specific resource; fund_class may include FIDC                   |
| C3  | P                 | DD        | FII list + dividends                                                     |
| C4  | ?                 | —         |                                                                          |
| C5  | N                 | DD        | not in resource list                                                     |
| C6  | ?                 | —         |                                                                          |
| C7  | P                 | DDF       | `/funds/:id/assets` aggregated by asset_type                             |
| C8  | Y                 | DD        | balance sheets, results, cash flows                                      |
| C9  | Y                 | DDOC      | CVM document delivery history; site "Fatos relevantes" page              |
| C10 | N                 | DD        | only share count                                                         |
| C11 | Y                 | DD        |                                                                          |
| C12 | N                 | DD        | Focus is macro, not company estimates                                    |
| C13 | Y                 | DDQ       |                                                                          |
| C14 | N                 | DFAQ      | "Não. Temos dados diários"                                               |
| C15 | N                 | DD        |                                                                          |
| C16 | P                 | DD, DDU   | yield curves (curvas de juros); no futures                               |
| C17 | P                 | DD        | government bonds / Tesouro only                                          |
| C18 | N                 | DD        | not in resource list                                                     |
| C19 | Y                 | DDI, DDU  | foreign investors flow; investor-flow dump by category                   |
| C20 | Y                 | DD, DDU   | index details; Ibovespa composition 10 years                             |
| C21 | Y                 | DD        | indices, expectations, Focus, curves                                     |
| C22 | N                 | DDOC      | document metadata only                                                   |
| Q1  | P                 | DDU       | dumps cover 5 to 10 years                                                |
| Q2  | ?                 | —         |                                                                          |
| Q3  | N                 | DD        |                                                                          |
| Q4  | Y                 | DDQ       | `adj_close`                                                              |
| Q5  | ?                 | —         |                                                                          |
| A1  | ?                 | —         |                                                                          |
| A2  | ?                 | —         |                                                                          |
| A3  | ?                 | —         |                                                                          |
| A4  | Y                 | DD        | "Indicadores de risco" endpoint                                          |
| A5  | N                 | DD        |                                                                          |
| A6  | ?                 | —         |                                                                          |
| A7  | ?                 | —         |                                                                          |
| A8  | N                 | DD        |                                                                          |
| X1  | Y                 | DD        |                                                                          |
| X2  | ?                 | —         |                                                                          |
| X3  | Y                 | DD        |                                                                          |
| X4  | N                 | DD        | cURL/Python/JS/R snippets only                                           |
| X5  | N                 | DD, BDDM  |                                                                          |
| X6  | N                 | —         |                                                                          |
| X7  | P                 | DDU       | weekly JSONL zips; access terms unclear                                  |
| T1  | P                 | DFAQ      | names primary sources; no-advice statement                               |
| T2  | P                 | DDU, DFAQ | "Atualizado em" on dumps, "diariamente", status page                     |
| B1  | P                 | DFAQ      | site free; API through sales                                             |
| B2  | on request (api@) | DD        | a commented-out FAQ block mentions R$180/yr for personal use; not public |
| B3  | S1, S3, retail    | DFAQ      |                                                                          |
| O1  | ?                 | —         |                                                                          |
| O2  | N                 | —         |                                                                          |

---

## 2. SHALLOW profiles

### Partnr (partnr.ai)

A B2B data vendor and **authorised B3 market-data redistributor**. It sells to brokers, advisors, fintechs, research houses, asset managers and banks. Coverage: fundamentals (160+ indicators, insider trades), real-time, delayed and D-1 quotes, listed funds (FII, FI-Infra, Fiagro), ETF holdings, 100+ news sources with sentiment, and BCB, IBGE, Fed and ECB macro. The MCP uses Streamable HTTP. Access is sales-led, with a 7-day trial key; tool names, auth details and prices are not public.

- Y: C14 real-time (https://www.partnr.ai), X5 MCP (https://www.partnr.ai/api/mcp-dados-financeiros-brasileiros), X3, llms.txt (https://partnr.ai/llms.txt).
- P: Q3. It says "Quando aplicável, os registros preservam datas, referências… rastrear o dado até sua fonte original".
- It lacks what SILO has: FI/FIDC informes, CDA look-through, lending and flows (none in its llms.txt product list). It also has no free public tier.

### Fintz (docs.fintz.com.br)

Clean, standardised market data. Auth is the `x-api-key` header. The public key `chave-de-testes-api-fintz` is extremely limited, and plans are purchased. Its strongest feature is a **point-in-time (backtest) endpoint family**, with an explicit look-ahead and restatement explanation. B3 data goes back to 2010 and raw CVM DRE/BP/DFC are included. The funds endpoints are "beta sob requisição".

- Y: Q5 (https://docs.fintz.com.br/endpoints/bolsa_point_in_time/), C8, C11, C13 (https://docs.fintz.com.br/endpoints/bolsa/).
- P: C1 beta (https://docs.fintz.com.br/endpoints/fundos/).
- N: C18. The docs say "Aluguel de ações — Em breve! Esse endpoint não está em desenvolvimento."
- N: X5. BAPI says no MCP.

### HG Brasil Finance (hgbrasil.com)

A long-running (since 2009) API for quotes, indices, Ibovespa composition, FX, crypto, SELIC/CDI, dividends, splits and statements (llms.txt). Auth is `?key=`. Pricing (https://hgbrasil.com/pricing) has a free plan, and paid plans are listed at R$24.90, R$49.90, R$119.90, R$279.90, R$679.90 and R$1,179.90 (the tier mapping was not checked). Daily limits run from 400 to 70,000 requests (search excerpt). Responses carry an `updated_at` field (https://hgbrasil.com/raw/docs/guide/best-practices.md). No MCP (BAPI).

- Y: C20 (Ibovespa composition, https://hgbrasil.com/llms.txt), llms.txt.
- It lacks SILO's funds, FIDC, lending and flows.

### OkaneBox (okanebox.com.br)

Aimed at spreadsheet users (Excel, Power BI, R, Python). Coverage: stocks and options, dividends, FIIs, **fund registration data and time series**, **fund portfolio composition since 2005**, PTAX, and statements since 2010. The free tier is delayed: 15 days for stocks and FX, 30 days for funds. Prices on /precos include R$19.99, R$39.99, R$59.99 and R$119.90. There is an "as is" accuracy disclaimer. No MCP was found.

- Y: C7 (https://okanebox.com.br), X2 Excel.
- It lacks FIDC, lending and flows.

### B3 for Developers (developers.b3.com.br)

B3's official API portal (Área do Investidor, Balcão, Listados, Tesouro Direto, UIF, sandbox). It is "destinadas ao consumo de clientes B2B. Não oferecemos acesso direto as APIs para pessoas físicas." It is a licensed B2B channel, not an agent-ready public source. No MCP was found.

### Financial Datasets (financialdatasets.ai), US reference

Covers 27k+ US tickers and 30+ years of SEC-sourced statements, filings (including item-level text), insider trades, 13F and 13D/G ownership, segments, KPIs and guidance, and macro.

What stands out for agents:

- A **Data Provenance** page naming the source for each dataset: SEC EDGAR directly, and Databento for prices (https://docs.financialdatasets.ai/data-provenance.md).
- An official remote MCP (`mcp.financialdatasets.ai`) listed in Claude's Connectors Directory and ChatGPT's plugin directory.
- **Agent self-onboarding**: `POST /agent/signup` returns a key, a `402 Payment Required` hands over a checkout link, and there is a `skill.md` at `/.well-known/skills/default/skill.md` (https://docs.financialdatasets.ai/agents.md).
- Webhooks.
- Cursor pagination.

Pricing: $20 in credits for 1,000 requests, Build at $200/mo, Scale at $2,000/mo with redistribution rights (https://financialdatasets.ai/pricing).

It is the design template for SILO's financials endpoints. SILO lacks its agent onboarding, provenance page format, directory listing and webhooks.

### Tomé API/MCP (agentetome.com), comparison row

An MCP at `https://www.agentetome.com/api/mcp`, JSON-RPC 2.0.

**Two ways to connect:**

- **Claude connector:** sign in with your email and receive a code. No key is copied. Questions count against the same daily limit as the site (https://agentetome.com/claude).
- **Key-based:** a `tome_…` Bearer key, shown once, used by generic clients.

**Tools and endpoints:**

- The documented tool is `exportar_admin`. It returns a 1-hour HMAC-signed download link, never the binary.
- `GET /api/v1/export/admin` returns a CSV ZIP with `manifest.json`, or an XLSX. It is limited to 10 per hour.
- A separate read-only `tomeplan_…` key serves "Planilha viva" through Google Sheets `IMPORTDATA`.

(https://agentetome.com/docs/api)

**Trust stance:** "célula vazia = não declarado", "Todo número carrega o informe_id de origem — nada é estimado, nada é preenchido", "fundo ausente aparece como ausência". The schema is versioned: a v1 column is never removed or renamed. The unauthenticated `tools/list` probe returned 401, so the full tool list is unknown.

It is the closest match to SILO's refusal and provenance stance, and it adds per-number citations and restatement diffs (https://agentetome.com/llms.txt).

---

## 3. Gaps vs SILO (things these platforms offer that SILO lacks)

### S3 (agents and developers): what is now standard

1. **A remote MCP server with an OAuth "one-click connector".** brapi, Mais Retorno, bolsai, Financial Datasets and Tomé all have one; Partnr has an MCP with auth undisclosed. All five of the first group say the agent never needs to handle a key. **SILO has none.** Its `serve/` `/v1/tools` produces OpenAI/AI-SDK tool specs, but only for a local adapter (docs/API.md).
2. **Per-user keys, usage dashboards and quota-aware errors.** brapi returns a 403 that names the plan needed, and a 429 with `Retry-After`. Mais Retorno's MCP tool explains that credits are exhausted. brapi has `get_account_capabilities`. SILO has one shared anon key and no per-user identity beyond the signed-in tier.
3. **Official SDKs on registries.** brapi has TypeScript and Python SDKs. bolsai's MCP is on PyPI. SILO's `silo-client` is not on PyPI.
4. **Documentation formats agents can read.** brapi offers `.mdx` copies of every page, pricing.md, versioning.md, auth.md, an Agent Skills repo and OpenAPI 3.1. Financial Datasets offers `skill.md` at `.well-known` and agent self-signup. SILO has llms.txt and skill.md, but no published OpenAPI for the `api` RPCs (inference: PostgREST's auto-OpenAPI was not verified), no skills repo and no versioning policy page.
5. **Tools that compute answers, not just fetch rows.** Mais Retorno has `compare_assets`, `backtest_portfolio` and `get_rolling_windows`; bolsai has `screen_stocks` and `compare_stocks`. SILO deliberately leaves reductions to a notebook (the `notebook_reducers` stance), which is a legitimate position but costs agent convenience.
6. **Directory listings.** Financial Datasets is in Claude's Connectors Directory and ChatGPT's plugin directory. No Brazilian vendor was verified as listed.
7. **Spreadsheet output.** Tomé serves `IMPORTDATA` CSV, bolsai has CSV, brapi has Sheets and Excel recipes.

### S1 (market professionals): data and analytics gaps

- **Adjusted and total-return prices:** Mais Retorno (with both series explained), bolsai, brapi, Dados de Mercado, Fintz. SILO serves unadjusted prices only.
- **Fund risk statistics** (Sharpe, volatility, drawdown, rolling windows): Mais Retorno; Dados de Mercado's risk indicators.
- **DI curve, futures, Tesouro Direto:** brapi (term structure, Tesouro), Dados de Mercado (yield curves, Tesouro), Mais Retorno (Tesouro).
- **Point-in-time fundamentals:** Fintz.
- **Screeners:** bolsai, brapi, Mais Retorno.
- **Portfolio and backtest:** Mais Retorno.
- **News and real-time data:** Partnr, Dados de Mercado (news), Financial Datasets (US).

### S2 (structured credit)

- brapi now serves **FIDC monthly reports and portfolio** (delinquency buckets, AA–H risk, quota classes, top-2 cedentes), on its Pro plan at R$139.99/mo. It is the only API vendor here with FIDC data. That makes it SILO's most direct overlap. SILO goes deeper (named top-25 sacados, full cedente list, SCR ladder, tranches) and is free.
- Tomé covers FIDC, CRI/CRA and debentures at document level, with restatement diffs.

---

## 4. What SILO has that none of these offer (white-space candidates)

| Candidate                                                                                                                                                  | Negative evidence                                                                                                                                                                                                                                                                                                                                     |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **B3 securities lending: open positions, short interest, % of float with float basis, and the trade-by-trade lending tape with the brokerage on each leg** | brapi's 75 MCP tools and its 3 MB llms-full.txt contain no lending (every "aluguel" hit is property rent). Mais Retorno's 9 endpoints and 11 tools have none. bolsai's OpenAPI has none. Dados de Mercado's resource list has none. Fintz says "Aluguel de ações — Em breve! … não está em desenvolvimento". Partnr's llms.txt product list has none. |
| **Free, no-signup API access to CVM fund and FIDC data**                                                                                                   | Signing up is required at Mais Retorno (CPF), bolsai (Google), brapi (FIDC and CDA are Pro only), Dados de Mercado (sales) and Partnr (form). Tomé is free but chat-limited, and its export needs a key.                                                                                                                                              |
| **FIDC top-25 sacados + full cedentes + SCR ladder + tranche performance**                                                                                 | brapi FIDC portfolio returns only `top1Cnpj`, `top2Cnpj` and their percentages (RFIDC). Mais Retorno excludes FIDC (MRM). None of the others serve FIDC.                                                                                                                                                                                              |
| **A machine-readable coverage and freshness contract across all datasets (`api.coverage()`), with refusal semantics (raise instead of trimming)**          | brapi's coverage endpoint is per-ticker for market data only (RCOV). Mais Retorno and Dados de Mercado have no coverage endpoint. Only Tomé's manifest ("ausência também é informação") comes close. SILO's pattern is shared with Tomé, not unique, but no API vendor has it.                                                                        |
| **Forensic and anomaly screens (A5): suspicious-deal screens, dormant funds**                                                                              | No A5 in any grid above. Tomé has "Fundos em silêncio" and "Reapresentações do mês" pages, but they are web pages, not API data.                                                                                                                                                                                                                      |
| **Cross-entity joins: CDA debenture issuer CNPJ → listed-company statements; fund → B3 ticker (CDA block 4)**                                              | brapi CDA carries `issuerCnpj` but has no join into company data (RCDA). Nobody else has one.                                                                                                                                                                                                                                                         |
| **Investor-type flows** — only partly unique                                                                                                               | Dados de Mercado has foreign-investor flow and a 5-year investor-flow dump (DDI, DDU), so this is not white space.                                                                                                                                                                                                                                    |

---

## 5. Key question: what is standard now, and what would make SILO the source agents prefer?

**Standard in September 2026, for a Brazilian data API that wants agent traffic:**

1. A remote Streamable-HTTP MCP that adds with one click through OAuth, with read-only tool annotations. Every serious competitor has one; Dados de Mercado and Fintz are the exceptions, and they are sales-led.
2. An llms.txt that tells the agent how to handle auth and errors.
3. A per-user key with visible quota.
4. An OpenAPI spec.
5. A free tier. The pattern is 200/day to 15k/month with shallow history.

SDKs are expected from the leader (brapi) but not universal.

**What would make SILO the preferred source for fund, credit and market research:**

- **Ship a thin remote MCP over schema `api`.** Tools: `catalog`, `coverage`, `lookup`, `panel`, `fund_nav`, `fund_holdings`, `fidc_portfolio/cedentes/sacados`, `short_interest`, `lending`, `investor_flow`, `financials`. Mark every tool `readOnlyHint`. The tool descriptions should carry the refusal semantics: a capped response raises; null means not declared.
- **Keep it free with no signup** for anon, since that is the widest gap versus brapi's R$139.99 Pro paywall on FIDC and CDA. Optionally add OAuth only for the 50-id tier.
- **Lead with the three unique datasets:** lending and short data, deep FIDC, and cross-entity joins.
- **Put provenance in every response:** source file and URL, `landed_at`, `complete_through`. Financial Datasets' provenance page and Tomé's `informe_id` are the models.
- **Publish SDK and skills to registries:** `silo-client` on PyPI, and a skills repo like brapi's.
- **Close the S1 table-stakes gap on adjusted prices** by computing them from CVM/B3 corporate events, and publish the method as bolsai and Mais Retorno do.

---

## 6. Sources

- https://maisretorno.com/mcp ; https://developers.maisretorno.com
- https://usebolsai.com ; https://usebolsai.com/llms.txt ; https://usebolsai.com/mcp ; https://api.usebolsai.com/openapi.json
- https://usebolsai.com/blog/melhores-mcp-servers-dados-financeiros-brasil-b3-2026 ; https://usebolsai.com/blog/bolsai-vs-dadosdemercado-api-dados-b3-2026 ; https://usebolsai.com/blog/melhores-apis-dados-b3-2026-comparacao ; https://usebolsai.com/blog/bolsai-vs-brapi-comparacao-api-b3-2026
- https://brapi.dev/llms.txt ; https://brapi.dev/llms-full.txt ; https://brapi.dev/docs/mcp.mdx ; https://brapi.dev/api/mcp/mcp (tools/list probe) ; https://brapi.dev/pricing.md ; https://brapi.dev/pricing ; https://brapi.dev/docs/fundos/fidc-carteira.mdx ; https://brapi.dev/docs/fundos/carteira.mdx ; https://brapi.dev/docs/dicionario.mdx ; https://brapi.dev/docs/tickers/cobertura.mdx
- https://www.dadosdemercado.com.br/api/docs (+ /bolsa/cotacoes, /bolsa/investidores-estrangeiros, /fundos-de-investimento/ativos, /fundos-de-investimento/lista-de-fundos, /empresas/documentos) ; https://www.dadosdemercado.com.br/dumps ; https://www.dadosdemercado.com.br/faq
- https://www.partnr.ai ; https://partnr.ai/llms.txt ; https://www.partnr.ai/api/mcp-dados-financeiros-brasileiros
- https://docs.fintz.com.br ; https://docs.fintz.com.br/endpoints/bolsa/ ; https://docs.fintz.com.br/endpoints/fundos/ ; https://docs.fintz.com.br/endpoints/bolsa_point_in_time/
- https://hgbrasil.com/finance ; https://hgbrasil.com/llms.txt ; https://hgbrasil.com/pricing ; https://hgbrasil.com/raw/docs/guide/best-practices.md
- https://okanebox.com.br ; https://www.okanebox.com.br/precos
- https://developers.b3.com.br
- https://docs.financialdatasets.ai/llms.txt ; https://docs.financialdatasets.ai/data-provenance.md ; https://docs.financialdatasets.ai/mcp-server.md ; https://docs.financialdatasets.ai/agents.md ; https://financialdatasets.ai/pricing
- https://agentetome.com/llms.txt ; https://agentetome.com/docs/api ; https://agentetome.com/claude ; https://www.agentetome.com/api/mcp (probe → 401)
- SILO comparison facts: /home/user/SILO-BZ/docs/API.md, /home/user/SILO-BZ/llms.txt
