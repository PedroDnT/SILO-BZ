# Track 2 — Platforms for investment & financial-markets professionals (S1), Brazil focus

Research date: 2026-09-23. The evidence rule in TAXONOMY.md applies: every Y or P value has a URL that was fetched or a search excerpt that was read. `?` means unknown: the capability was not found. It does not mean the capability is absent. Anything that is an inference says so.

Method note: the Parallel Search MCP hit its free-tier rate limit after two calls, so the rest of the research used WebSearch and WebFetch. Some vendor pages summarised badly. The Bloomberg ASKB page returned HTTP 403, and ANBIMA Data renders with JavaScript. Where a page could not be read, the value stays `?`.

---

## 1. DEEP profiles

### 1.1 Economatica (owned by TC / Traders Club; acquired for R$40M in 2021)

- **Who and what.** Economatica is a Brazilian financial database founded in 1986 with about 40 years of history. It covers Brazil, LatAm and the US. It reports "+420 clientes", "+5k companies" and "+25k funds covered", and uses CVM and ANBIMA as its regulatory base. It now sells one proprietary base through six surfaces: **Plataforma**, **Terminal** (real-time), **Excel Add-in**, **Kento** (an AI agent), **APIs** and **MCP**. It markets itself as "Financial Data for Humans and AI Agents" (https://www.economatica.com/, https://www.economatica.com/en).
- **Data sources.** CVM, ANBIMA and B3, plus a proprietary newsroom ("Mover", 180+ headlines a day, 40+ journalists) and Arko Advice political coverage.
- **APIs (v1).** Four APIs: News (REST and WebSocket, with sentiment and "CVM integrated"), Fundamentals & Market data (100+ indicators, EOD OHLC, Markowitz), Funds ("CVM universe of ~99k vehicles … composition and overlap") and Fixed Income ("~2k debentures, ~6k CRA/CRI, Treasury + DI1, credit risk"). The docs overview also lists earnings-call transcripts, an events calendar, ownership (CVM, funds, 13F, insiders), FIIs, BDRs and ETFs. Access is enabled per contract and authentication is HMAC or OAuth2 (https://www.economatica.com/en/apis, https://news-api.economatica.com/docs/en).
- **AI.**
  - **MCP.** Launched on 2026-05-11. It started with a news module and has since grown to five modules: News with Plantão CVM, Fundamentals, Funds (~99k), FIIs, and Fixed Income (CRI/CRA, DI1). It works with Claude, Copilot and ChatGPT. It requires an active contract, pricing is custom, and a trial is available (https://www.economatica.com/mcp, https://flj.com.br/mercados/economatica-lanca-mcp-inteligencia-de-mercado-agora-acessivel-por-ia/).
  - **Kento.** An agent that remembers context. It handles meeting briefs, committee risk analysis, comps, pre-market maps and earnings Q&A prep. Plans are per user per month: Go (30 portfolios), Pro (100) and Max (200). No R$ figures are public. Quotes are 15-minute delayed by default, with real-time as an option. Its grounding claim is "A credibilidade é da Economatica", and it makes no recommendations (https://www.economatica.com/kento).
- **Differentiators.**
  - 40 years of history with prices adjusted for corporate actions.
  - Fund-of-funds look-through with consolidated indirect holdings, plus the "effective administration fee" computed through FoF positions.
  - A securities-lending tool covering on-loan, lendable, rates, days-to-cover, short-interest % and crowded trades. This comes from an undated brochure (http://mkt.economatica.com/economatica-presentation.pdf, search excerpt).
  - Full Excel add-in (`=ECONOMATICA()`).
  - It is the incumbent Brazilian vendor that has moved furthest toward AI and MCP.
- **Weaknesses and gaps.**
  - No public pricing.
  - No FIDC credit fields (subordination, delinquency, cedentes) were found. The FIDC article shows only portfolio by segment, sourced from the CVM monthly reports since 2012 (https://www.economatica.com/blog/evolucao-das-carteiras-de-fidcs-12-meses-por-segmento-economatica/).
  - Its MCP answers are grounded in the Economatica base, but there is no stated citation back to the CVM or B3 source record.
  - No free tier.

| ID  | value                      | evidence URL                                                                                                               | note                                                                                                                      |
| --- | -------------------------- | -------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| C1  | Y                          | https://www.economatica.com/en/apis                                                                                        | "~99k funds, performance & risk"                                                                                          |
| C2  | P                          | https://www.economatica.com/blog/evolucao-das-carteiras-de-fidcs-12-meses-por-segmento-economatica/                        | FIDC portfolio by 11 segments, from CVM monthly reports since 2012. No subordination, delinquency or cedente fields found |
| C3  | Y                          | https://www.economatica.com/mcp                                                                                            | FII module: price, DY, P/VP, IFIX                                                                                         |
| C4  | ?                          | —                                                                                                                          | not found                                                                                                                 |
| C5  | Y                          | https://www.economatica.com/en/apis                                                                                        | "~6k CRA/CRI"                                                                                                             |
| C6  | Y                          | https://news-api.economatica.com/docs/en                                                                                   | ETFs in the funds domain                                                                                                  |
| C7  | Y                          | http://mkt.economatica.com/economatica-presentation.pdf ; https://www.economatica.com/blog/fundos-alocam-bilhoes-em-fidcs/ | FoF "indirect and consolidated holdings"; 1,658 funds found holding FIDCs                                                 |
| C8  | Y                          | https://www.economatica.com/plataforma                                                                                     | statements, 40y                                                                                                           |
| C9  | Y                          | https://www.economatica.com/mcp                                                                                            | "Plantão CVM", summarises CVM filings                                                                                     |
| C10 | Y                          | https://www.economatica.com/plataforma ; https://news-api.economatica.com/docs/en                                          | shareholder structure; ownership incl. insiders                                                                           |
| C11 | Y                          | https://www.economatica.com/plataforma                                                                                     | dividends, JCP                                                                                                            |
| C12 | ?                          | —                                                                                                                          | not found                                                                                                                 |
| C13 | Y                          | https://www.economatica.com/plataforma                                                                                     | adjusted quotes                                                                                                           |
| C14 | Y                          | https://www.economatica.com/                                                                                               | Terminal "Real-time B3 + globais"                                                                                         |
| C15 | ?                          | —                                                                                                                          | not found                                                                                                                 |
| C16 | Y                          | https://www.economatica.com/en/apis ; https://www.economatica.com/                                                         | "Treasury + DI1"; Terminal "Curva de juros"                                                                               |
| C17 | Y                          | https://www.economatica.com/en/apis ; brochure                                                                             | ~2k debentures; "priced by ANBIMA"                                                                                        |
| C18 | Y                          | http://mkt.economatica.com/economatica-presentation.pdf                                                                    | lending tool, short interest %, days to cover. Brochure is undated                                                        |
| C19 | ?                          | —                                                                                                                          | not found                                                                                                                 |
| C20 | ?                          | —                                                                                                                          | "benchmarks" only                                                                                                         |
| C21 | Y                          | https://www.economatica.com/                                                                                               | "+200 indicadores econômicos"                                                                                             |
| C22 | P                          | https://flj.com.br/mercados/economatica-lanca-mcp-inteligencia-de-mercado-agora-acessivel-por-ia/                          | news plus CVM filing summaries. Regulamentos and atas not found                                                           |
| Q1  | Y                          | https://www.economatica.com/plataforma                                                                                     | since 1986 (40y)                                                                                                          |
| Q2  | ?                          | —                                                                                                                          | not found                                                                                                                 |
| Q3  | P                          | brochure ("link to original filings") ; https://www.economatica.com/en/platform                                            | "traceable and documented". No per-number citation found                                                                  |
| Q4  | Y                          | https://www.economatica.com/en/solutions/asset-managers                                                                    | "Adjusted prices, corporate actions"                                                                                      |
| Q5  | ?                          | —                                                                                                                          | not found                                                                                                                 |
| A1  | Y                          | https://www.economatica.com/plataforma                                                                                     | screener                                                                                                                  |
| A2  | ?                          | —                                                                                                                          | not found                                                                                                                 |
| A3  | Y                          | https://www.economatica.com/plataforma                                                                                     | Matrixx comparatives                                                                                                      |
| A4  | Y                          | https://www.economatica.com/en/apis                                                                                        | fund risk; Markowitz                                                                                                      |
| A5  | ?                          | —                                                                                                                          | not found                                                                                                                 |
| A6  | Y                          | https://www.economatica.com/en/solutions/asset-managers                                                                    | Terminal "news alerts"                                                                                                    |
| A7  | Y                          | https://www.economatica.com/en/solutions/asset-managers                                                                    | watchlists; Kento portfolios                                                                                              |
| A8  | P                          | https://www.economatica.com/blog/fundos-alocam-bilhoes-em-fidcs/                                                           | fund→FIDC and FoF look-through. Fund→issuer→company join not found                                                        |
| X1  | Y                          | https://www.economatica.com/plataforma                                                                                     |                                                                                                                           |
| X2  | Y                          | https://www.economatica.com/en/excel-add-in                                                                                |                                                                                                                           |
| X3  | Y                          | https://www.economatica.com/en/apis                                                                                        | REST + WS                                                                                                                 |
| X4  | ?                          | —                                                                                                                          | not found                                                                                                                 |
| X5  | Y                          | https://www.economatica.com/mcp                                                                                            | Claude, Copilot, ChatGPT; requires contract                                                                               |
| X6  | Y                          | https://www.economatica.com/kento                                                                                          | Kento agent                                                                                                               |
| X7  | Y                          | https://www.economatica.com/en/solutions/asset-managers                                                                    | Data Feed CSV/JSON via FTP                                                                                                |
| T1  | P                          | https://www.economatica.com/kento                                                                                          | "credibilidade é da Economatica"; no advice. No explicit no-fabrication rule                                              |
| T2  | ?                          | —                                                                                                                          | not found                                                                                                                 |
| B1  | N                          | https://www.economatica.com/mcp                                                                                            | trial only; contract required                                                                                             |
| B2  | not public                 | https://www.economatica.com/kento                                                                                          | Kento per-user monthly (Go/Pro/Max)                                                                                       |
| B3  | S1 (+IR, wealth, academia) | https://www.economatica.com/                                                                                               |                                                                                                                           |
| O1  | ?                          | —                                                                                                                          |                                                                                                                           |
| O2  | P                          | https://www.economatica.com/                                                                                               | "governança, precisão e auditabilidade" (claim)                                                                           |

### 1.2 Quantum Axis (Quantum Finance)

- **Who and what.** Quantum Finance is a Brazilian data vendor. Axis is its flagship web platform for "gestoras, assessores, gestores de patrimônio, SFOs/MFOs, fundos de pensão, RPPS, seguradoras, tesourarias". It also sells Quantum Portfólio, Quantum Prev (pension plans), white label, integrations and **Quantum Developers** (an API on Azure API Management with market, analytical, cadastral and official-documents domains) (https://quantumfinance.com.br/, https://developers.quantumaxis.com.br/).
- **Coverage.** This is the broadest fixed-income and structured coverage of the three deep platforms (https://quantumfinance.com.br/bases-quantum/):
  - 2,300+ FIDCs and 4,300 series, with daily returns adjusted for amortisation, ratings and secondary-market trades
  - 226k private credit titles (CRI, CRA, CDB, CCB, LCA, LCI) with PU on curve and volatility surfaces
  - 7,300 debentures
  - 30k funds, 1,800 FIPs and 700 FIIs (with vacancy and tenants)
  - 19.1k PGBL/VGBL plans, 300+ EFPC, 2,100 RPPS
  - 381k options, 44k derivatives and 600 indices with component weights
- **FIDC toolset.** Quantum lists eight FIDC tools (https://quantumfinance.com.br/fidcs-8-ferramentas-poderosas-para-analisar-esses-ativos/):
  - individual and comparative sheets covering subordination %, amortisation and target return
  - receivables composition
  - official documents (regulamentos, atas, fatos relevantes)
  - **"FIDC buyers"**, which shows which funds hold a given FIDC
  - new-issuance tracker
  - weekly structured-assets report
- **AI.** "Atom Expert System (AES)" uses AI to cross-reference, deduplicate and standardise databases. This is a back-end curation process, not a user-facing assistant. No chat or MCP product was found (search "Quantum Finance MCP agente IA" returned nothing).
- **Access.** Web, mobile, API, "data link", and an Excel library/add-in ("Quantum Link de Dados"). It has alerts, automated reports (CSV, Excel, PDF), SSO and LDAP (https://quantumfinance.com.br/solucao/quantum-axis/).
- **Weaknesses.** No public pricing. No AI assistant or MCP found. No evidence of FIDC delinquency, cedente or sacado fields, securities lending, or investor-type flows. The terms page says "users don't pay … may establish charges" (http://www.quantumaxis.com.br/ T&C, search excerpt). That reads as boilerplate and is not evidence of a free tier.

| ID  | value                             | evidence URL                                                                            | note                                                                                        |
| --- | --------------------------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| C1  | Y                                 | https://quantumfinance.com.br/bases-quantum/                                            | 30k funds                                                                                   |
| C2  | Y                                 | https://quantumfinance.com.br/fidcs-8-ferramentas-poderosas-para-analisar-esses-ativos/ | subordination %, receivables composition, ratings. Delinquency, PDD and cedentes not stated |
| C3  | Y                                 | https://quantumfinance.com.br/bases-quantum/                                            | 700 FIIs, vacancy, tenants                                                                  |
| C4  | P                                 | https://quantumfinance.com.br/bases-quantum/                                            | FIP 1,800. FIAGRO not found                                                                 |
| C5  | Y                                 | https://quantumfinance.com.br/bases-quantum/                                            | 226k titles incl. CRI/CRA                                                                   |
| C6  | Y                                 | https://quantumfinance.com.br/bases-quantum/                                            | all BR ETFs, with portfolios                                                                |
| C7  | Y                                 | https://quantumfinance.com.br/fidcs-8-ferramentas-poderosas-para-analisar-esses-ativos/ | "FIDC buyers"; fund portfolio data                                                          |
| C8  | Y                                 | https://quantumfinance.com.br/bases-quantum/                                            | 1,700 listed and 26k private companies                                                      |
| C9  | Y                                 | https://developers.quantumaxis.com.br/                                                  | "Official Documents … material events"                                                      |
| C10 | P                                 | https://quantumfinance.com.br/bases-quantum/                                            | insider info; private-company shareholders                                                  |
| C11 | P                                 | https://quantumfinance.com.br/bases-quantum/                                            | dividends listed for US/LatAm stocks                                                        |
| C12 | ?                                 | —                                                                                       | not found                                                                                   |
| C13 | Y                                 | https://quantumfinance.com.br/bases-quantum/                                            |                                                                                             |
| C14 | P                                 | https://quantumfinance.com.br/solucao/quantum-axis/                                     | "quotes refresh within minutes"                                                             |
| C15 | Y                                 | https://quantumfinance.com.br/bases-quantum/                                            | 381k options                                                                                |
| C16 | Y                                 | https://quantumfinance.com.br/bases-quantum/                                            | 44k derivatives; yield curves                                                               |
| C17 | Y                                 | https://quantumfinance.com.br/bases-quantum/                                            | 7,300 debentures, curves                                                                    |
| C18 | ?                                 | —                                                                                       | not found                                                                                   |
| C19 | ?                                 | —                                                                                       | not found                                                                                   |
| C20 | Y                                 | https://quantumfinance.com.br/bases-quantum/                                            | 600 indices with component weights                                                          |
| C21 | ?                                 | —                                                                                       | not found                                                                                   |
| C22 | Y                                 | https://quantumfinance.com.br/fidcs-8-ferramentas-poderosas-para-analisar-esses-ativos/ | regulamentos, atas, fatos relevantes                                                        |
| Q1  | ?                                 | —                                                                                       |                                                                                             |
| Q2  | ?                                 | —                                                                                       |                                                                                             |
| Q3  | ?                                 | —                                                                                       |                                                                                             |
| Q4  | P                                 | search excerpt on quantumfinance.com.br/solucao/quantum-axis                            | FIDC returns "adjusted by amortizations"                                                    |
| Q5  | ?                                 | —                                                                                       |                                                                                             |
| A1  | P                                 | https://quantumfinance.com.br/fidcs-8-ferramentas-poderosas-para-analisar-esses-ativos/ | templates with pre-built filters                                                            |
| A2  | ?                                 | —                                                                                       |                                                                                             |
| A3  | Y                                 | same                                                                                    | comparative sheets                                                                          |
| A4  | Y                                 | https://quantumfinance.com.br/bases-quantum/                                            | Sharpe, VaR                                                                                 |
| A5  | ?                                 | —                                                                                       |                                                                                             |
| A6  | Y                                 | https://quantumfinance.com.br/solucao/quantum-axis/                                     | alert systems                                                                               |
| A7  | Y                                 | https://quantumfinance.com.br/solucao/quantum-axis/                                     | portfolio consolidation                                                                     |
| A8  | P                                 | FIDC tools page                                                                         | fund→FIDC (buyers). No fund→issuer→company join found                                       |
| X1  | Y                                 | https://quantumfinance.com.br/solucao/quantum-axis/                                     |                                                                                             |
| X2  | Y                                 | https://quantumfinance.com.br/en/solutions/quantum-axis/                                | Excel library / Link de Dados                                                               |
| X3  | Y                                 | https://developers.quantumaxis.com.br/                                                  |                                                                                             |
| X4  | ?                                 | —                                                                                       |                                                                                             |
| X5  | ?                                 | search: no Quantum MCP found                                                            |                                                                                             |
| X6  | ?                                 | —                                                                                       | AES is back-end AI, not chat                                                                |
| X7  | P                                 | https://quantumfinance.com.br/solucao/quantum-axis/                                     | "data link", CSV/Excel reports                                                              |
| T1  | ?                                 | —                                                                                       |                                                                                             |
| T2  | ?                                 | —                                                                                       |                                                                                             |
| B1  | ?                                 | T&C excerpt ambiguous                                                                   |                                                                                             |
| B2  | not public                        | —                                                                                       |                                                                                             |
| B3  | S1, S2 (+pension, RPPS, advisors) | https://quantumfinance.com.br/solucao/quantum-axis/                                     |                                                                                             |
| O1  | P                                 | https://quantumfinance.com.br/                                                          | AES AI cross-referencing plus expert curation                                               |
| O2  | P                                 | search excerpt                                                                          | "verification and curation by their experts" (claim)                                        |

### 1.3 Comdinheiro (Nelogica)

- **Who and what.** Comdinheiro is a Brazilian analysis platform acquired by Nelogica, the maker of Profit. It has three tiers:
  - **Comdinheiro PRO**: enterprise for banks, insurers, asset managers and corporates. It has 300+ tools and unlimited simultaneous access (https://comdinheiro.com.br/?id=&lang=pt&op=&pag=comdinheiro-full).
  - **Basic**: R$249.90/month, or 12 × R$199.90 (https://www.comdinheiro.com.br/?lang=pt&pag=comdinheiro-basic&op=&id=).
  - **Light**: R$79.90, R$99.90 with Fundos, or R$119.90 with Portfolio (https://www.comdinheiro.com.br/basic/).
- **Coverage.** 24,000+ funds with thousands of indicators, 20 fact-sheet formats and "14 formats for opening fund portfolios". Price and rate histories for public bonds and debentures. Fundamentals for 2,000+ companies. Fatos relevantes stored on its own servers. Real-time quotes "sem delay". Portfolio consolidation (onshore and offshore) and a Markowitz optimiser. The homepage summary lists FIDC and CRI/CRA, but the fetched pages did not describe them in detail.
- **AI.** A natural-language assistant (text or voice), launched in October 2024. It turns questions into search parameters and reports, starting with funds. The source is sponsored content (https://www.infomoney.com.br/onde-investir/comdinheiro-inova-e-implementa-ia-em-sua-plataforma/). No MCP was found.
- **API.** Gestoras such as Riza use it to pull recurring filtered datasets into spreadsheets. The source is sponsored (https://www.infomoney.com.br/mercados/gestoras-aceleram-uso-de-apis-para-facilitar-acesso-a-dados-do-mercado/).
- **Weaknesses.** Structured-credit depth is unclear. No MCP. No evidence of citations. Its AI is a query translator, not a grounded answerer.

| ID      | value                                                      | evidence URL                    | note                                                               |
| ------- | ---------------------------------------------------------- | ------------------------------- | ------------------------------------------------------------------ |
| C1      | Y                                                          | comdinheiro-full page           | 24k funds                                                          |
| C2      | P                                                          | https://www.comdinheiro.com.br/ | FIDC listed in coverage. No fields verified                        |
| C3      | Y                                                          | Basic page                      | FII sheets                                                         |
| C4      | ?                                                          | —                               |                                                                    |
| C5      | P                                                          | https://www.comdinheiro.com.br/ | listed in coverage only                                            |
| C6      | ?                                                          | —                               |                                                                    |
| C7      | Y                                                          | comdinheiro-full page ; /basic/ | "14 formats for opening fund portfolios"; Light+Fundos holdings    |
| C8      | Y                                                          | comdinheiro-full page           | 2,000+ companies                                                   |
| C9      | Y                                                          | comdinheiro-full page           | fatos relevantes                                                   |
| C10     | P                                                          | comdinheiro-full page           | "corporate structures"                                             |
| C11     | ?                                                          | —                               |                                                                    |
| C12     | ?                                                          | —                               |                                                                    |
| C13     | Y                                                          | Basic page                      | quote history                                                      |
| C14     | Y                                                          | Basic page                      | "real-time without delays"                                         |
| C15–C16 | ?                                                          | —                               |                                                                    |
| C17     | Y                                                          | comdinheiro-full page           | debenture price and rate histories                                 |
| C18–C20 | ?                                                          | —                               |                                                                    |
| C21     | P                                                          | https://www.comdinheiro.com.br/ | macro listed                                                       |
| C22     | P                                                          | comdinheiro-full page           | fatos relevantes only                                              |
| Q1–Q5   | ?                                                          | —                               |                                                                    |
| A1      | Y                                                          | comdinheiro-full page           | fund screener                                                      |
| A2      | ?                                                          | —                               |                                                                    |
| A3      | Y                                                          | comdinheiro-full page           | comparative charts                                                 |
| A4      | Y                                                          | comdinheiro-full page           | risk metrics, Markowitz                                            |
| A5      | ?                                                          | —                               |                                                                    |
| A6      | ?                                                          | —                               |                                                                    |
| A7      | Y                                                          | comdinheiro-full page           | consolidation                                                      |
| A8      | ?                                                          | —                               |                                                                    |
| X1      | Y                                                          |                                 |                                                                    |
| X2      | P                                                          | comdinheiro-full page           | "Total integração com planilhas". Not confirmed as a native add-in |
| X3      | Y                                                          | InfoMoney API article           |                                                                    |
| X4      | ?                                                          | —                               |                                                                    |
| X5      | ?                                                          | MCP search: none                |                                                                    |
| X6      | Y                                                          | InfoMoney AI article            | NL/voice → report                                                  |
| X7      | ?                                                          | —                               |                                                                    |
| T1–T2   | ?                                                          | —                               |                                                                    |
| B1      | N                                                          | /basic/                         | 7-day trial only                                                   |
| B2      | Light R$79.90–119.90/mo; Basic R$249.90/mo; PRO not public | pages above                     |                                                                    |
| B3      | S1 (PRO) + retail (Light/Basic)                            |                                 |                                                                    |
| O1–O2   | ?                                                          | —                               |                                                                    |

---

## 2. SHALLOW profiles

**Bloomberg Terminal.**

- About $31,980 per seat per year, or $2,665/month, as of March 2026, with a 2-year minimum. Third-party estimate: https://costbench.com/software/financial-data-terminals/bloomberg-terminal/.
- ASKB is agentic conversational AI in beta since around April/May 2026, drawing on structured data, news and research. It reached mobile in August 2026 (https://fintech.global/2026/08/19/bloomberg-extends-askb-ai-assistant-to-mobile-devices/). ASKB's citation behaviour could not be verified because the page returned 403.
- The Excel add-in (BDH) is Y (https://guides.smu.edu/bloomberg/excel).
- Individual Brazilian FIDC quote pages exist, e.g. https://www.bloomberg.com/quote/FIDCBZP:BZ. The depth of CVM FIDC informe coverage is **?**.
- Where SILO clearly differs: price (free), and forensic screens over CVM data (inference, not verified).

**LSEG Workspace.**

- LSEG MCP server is Y (https://www.lseg.com/en/solutions/ai-finance-solutions/lseg-mcp).
- Workspace AI is Y (https://www.lseg.com/en/data-analytics/products/workspace/workspace-ai-capabilities).
- Excel add-in is Y (https://www.lseg.com/en/data-analytics/products/workspace/updates/lseg-launches-workspace-add-in-for-excel-and-powerpoint).
- B3 market data is resold (https://www.lseg.com/en/data-analytics/financial-data/pricing-and-market-data/equities-market-data/b3-data).
- Lipper's classification lists 12 core markets and **Brazil is not among them** (search excerpt, https://www.lseg.com/en/data-catalogue/funds). Brazilian FIDC coverage is **?**.

**S&P Capital IQ Pro.**

- ChatIQ and Document Intelligence are Y.
- Claude connector, MCP (LLM-ready API) and the Kensho "S&P Global plugin" skills are Y (https://docs.kensho.com/agentskills, https://www.anthropic.com/news/advancing-claude-for-financial-services).
- Excel plug-in is Y (https://libraryhelp.qub.ac.uk/faq/281720).
- Brazil fund and FIDC coverage is **?**.

**FactSet.**

- Production MCP "sans intermediary", covering fund holdings, ownership and 86k companies in 116 countries (https://developer.factset.com/mcp/factset-ai-ready-data-mcp).
- Excel add-in, which includes estimates (https://devblogs.microsoft.com/microsoft365dev/factset-for-excel-leverages-the-equivalentaddin-element-for-com-add-in-compatibility/). Estimates are a C12 capability SILO lacks.
- CVM, FIDC and CDA coverage is **?**.

**AlphaSense.**

- Generative Search with snippet-level citations, and it now blends structured financials (https://www.alpha-sense.com/resources/product-articles/generative-search-next-generation/, https://www.alpha-sense.com/press/alphasense-launches-financial-data/).
- Coverage of Portuguese and CVM documents is **?**.
- This is the citation benchmark for C22 and Q3.

**Valor PRO.**

- Valor Econômico's real-time news terminal, with quotes (B3 and international), FX, derivatives, fixed income, funds, commodities and a database of 9k+ Brazilian companies (https://apps.apple.com/br/app/valor-pro/id616176310).
- Price and Excel support are **?**.

**Broadcast+ (Agência Estado).**

- Real-time news, B3 and OTC quotes (FX, fixed income, derivatives), fund portfolio composition, intraday charts and an order-entry module.
- An **Excel add-in with streaming data** is Y (https://www.aebroadcast.com.br/broadcast-plus/).
- Fixed-income trading through B3 Trademate integration.
- Price: **?**.

**TradeMap.**

- Current plans: Free (15-minute delay), **Plus R$29.90 with "MCP access for AI-powered investment analysis"**, Pro R$49.90 (order routing), and Trader (R$0 on condition of one mini-contract a month, real-time plus RocketAI) (https://trademap.com.br/planos/trademap-pro).
- An older excerpt priced Pro at R$349.90 and included "Stock Rental" (aluguel) and an options module (search excerpt, same URL family). Treat that as historical.
- This is the cheapest MCP in Brazil. It is aimed at retail and pro-sumers, not S1.

**ANBIMA Data / ANBIMA Feed.**

- ANBIMA Data is **free** and covers fund registry and daily PL, flows and quotaholders for 16k+ ICVM 555 funds. The announcement mentions history only for the past year (https://www.anbima.com.br/pt_br/noticias/dados-sobre-fundos-de-investimento-chegam-ao-anbima-data.htm).
- ANBIMA Feed is a paid OAuth2 REST API offering the official **debenture, government bond and CRI/CRA prices** (C17) and ANBIMA indices (https://developers.anbima.com.br/en/documentacao/precos-indices/apis-de-precos/debentures/). Package prices are not public.
- FIDC coverage is **?**. The funds package mentions only ICVM 555.

**B3 UP2DATA / UP2DATA On Demand.**

- The official paid source. It covers curves (80+, including pre-fixed DI), corporate actions, indices with portfolio composition, volatility surfaces, CRI/CRA, and **OTC trade-by-trade data for fixed income and securities lending** (https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/up2data/dados-disponiveis/).
- **Historical lending open positions are sold from R$100** in the On Demand store. The trade-by-trade lending file names the donor and taker participant (search excerpt, https://www.up2dataondemand.com.br/outros/emprestimos-de-ativos).
- **This qualifies SILO's "no archive" premise.** B3 publishes no _free_ archive, but a paid historical archive exists.

**Hebbia.** A document-reasoning workspace (Matrix) with sentence-level citations (ISD). It is used for private-credit extraction from credit agreements (https://www.hebbia.com/blog/how-private-credit-teams-use-hebbia). No Brazilian data is bundled: it works on the customer's own documents.

**Rogo.** An AI analyst for investment banking and research. It has 35k users at 250+ institutions and raised $160M in April 2026 (https://siliconangle.com/2026/04/29/rogo-raises-160m-speed-financial-analysis-ai-agents/). Brazil coverage is **?**.

**Fintool.** Cited answers over SEC filings and transcripts for about 8k US companies. **Microsoft acquired it in April 2026 and it is no longer a standalone product** (https://www.therundown.ai/tools/fintool). No Brazilian coverage.

**Perplexity Finance.** Has pages for B3 tickers (e.g. https://www.perplexity.ai/app/finance/BBAS3.SA/earnings). Its data comes from Financial Modeling Prep, and its stated coverage is North America and APAC (https://www.findmymoat.com/tools/perplexity-finance). No CVM fund or FIDC data.

**Adjacent finding (outside the brief).** **Mais Retorno MCP** exposes funds, stocks, FIIs and "composição CVM" in natural language (search excerpt, https://maisretorno.com/mcp; the page did not render). The Partnr MCP covers Brazilian fundamentals and macro (https://www.partnr.ai/api/mcp-dados-financeiros-brasileiros/). FIDC-specialist sites (Painel FIDC, fidcs.com.br, Clube FIDC, Portal FIDC) belong to Track S2.

---

## 3. Gaps vs SILO (capabilities they offer that SILO lacks)

**S1 (professionals):**

| Gap                                                                        | Offered by                                                                                                       |
| -------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Excel add-in (X2)                                                          | Economatica, Quantum ("Link de Dados"), Broadcast+ (streaming), Bloomberg, LSEG, FactSet, CapIQ; Comdinheiro (P) |
| NL assistant / agent (X6)                                                  | Economatica Kento, Comdinheiro AI, Bloomberg ASKB, CapIQ ChatIQ, LSEG, AlphaSense, TradeMap RocketAI             |
| Own MCP (X5)                                                               | Economatica (Claude/Copilot/ChatGPT), LSEG, FactSet, S&P/Kensho, TradeMap Plus (R$29.90), Mais Retorno           |
| Adjusted prices / corporate-action-adjusted series (Q4)                    | Economatica (40y); B3 UP2DATA corporate actions                                                                  |
| Real-time / intraday (C14)                                                 | Economatica Terminal, Comdinheiro, Broadcast+, Valor PRO, TradeMap Trader, Quantum (minutes)                     |
| DI curve / futures (C16)                                                   | Economatica (DI1), Quantum (curves), B3 UP2DATA (80+ curves), Broadcast+                                         |
| ANBIMA secondary prices for debentures, CRI/CRA and government bonds (C17) | ANBIMA Feed (source), Economatica, Quantum, Comdinheiro                                                          |
| Estimates / consensus (C12)                                                | FactSet (Excel add-in), and by inference Bloomberg, LSEG and CapIQ. Not found at any Brazilian vendor            |
| Alerts / watchlists (A6, A7)                                               | Economatica, Quantum, Comdinheiro (consolidation)                                                                |
| Unstructured documents: regulamentos, atas, rating reports (C22)           | Quantum (FIDC docs), Economatica (CVM filing summaries), AlphaSense and Hebbia (cited), Tomé                     |
| Long, deep history (Q1)                                                    | Economatica since 1986                                                                                           |
| Derivatives beyond COTAHIST options (C15/C16)                              | Quantum (381k options, 44k derivatives)                                                                          |

**S1 structured credit (overlap with S2):**

- Quantum has FIDC _series_-level returns adjusted for amortisation, ratings, secondary-market trades, a new-issuance tracker and a 226k-title private-credit base.
- Economatica has CRI/CRA with credit-risk reads.
- SILO has neither ratings nor secondary-market CRI/CRA prices.

## 4. What SILO has that none of these offer (white-space candidates)

Negative evidence covers the pages fetched and queries run in this track. It is not exhaustive: enterprise terminals such as Bloomberg and LSEG may hold data behind login.

1. **FIDC informe credit internals at tab level, free, via API.** SILO serves named cedentes (tab I), anonymised top-25 sacados (VIII), sector (II), the SCR ladder (X), delinquency/aging and the tranche split. Checked:
   - Quantum's FIDC tools page names subordination and receivables composition, but no delinquency, cedentes or sacados.
   - Economatica's FIDC article shows segment portfolio only.
   - Comdinheiro gave no field detail.
   - Query "plataforma FIDC cedentes sacados concentração top 25 … API" returned only CVM open data and SILO's own PRs (#232, #233).
2. **Trade-by-trade securities-lending tape with the broker on each leg, plus the open book, investor-type flows and index free float, all free.** Economatica has a lending _analytics_ tool (undated brochure) with no broker-leg tape. B3 sells the raw file (from R$100). No platform in this track was found exposing broker-leg lending analysis. Query "aluguel de ações negócio a negócio corretora doadora tomadora … plataforma" returned only explainers.
3. **Cross-entity join from fund holdings (CDA block 6) to the debenture issuer CNPJ to listed-company statements (A8).** Economatica and Quantum show fund→FIDC ("FIDC buyers", FoF look-through). Neither page shows a fund→issuer→company join.
4. **Forensic and accountability screens (A5): suspicious deals and dormant funds.** No evidence at any platform. Every vendor page fetched frames analytics as screening, valuation or risk. None frames it as accountability.
5. **Transparency about coverage and freshness (T2), plus an explicit no-fabrication stance (T1).** No vendor publishes a coverage API or a statement separating pipeline freshness from source completeness. Economatica's "credibilidade é da Economatica" is only an assertion of brand trust.
6. **Free, open, programmatic Brazilian structured data for agents.**
   - All deep incumbents are contract-only (B1 = N or ?).
   - The free alternatives are narrow. ANBIMA Data covers ICVM 555 funds and mentions only a year of history. TradeMap's MCP is a retail product.
   - SILO's free PostgREST API, catalog, llms.txt and skill.md are a candidate white space for S1 teams building their own agents. A limitation: SILO is not itself an MCP.

**Qualification to SILO's own positioning:** B3 sells historical lending data through UP2DATA On Demand. SILO's accumulated BDI history is therefore irreplaceable _for free_, not irreplaceable at any price.

## 5. Sources

- https://www.economatica.com/ · https://www.economatica.com/en · https://www.economatica.com/en/apis · https://news-api.economatica.com/docs/en · https://www.economatica.com/mcp · https://www.economatica.com/kento · https://www.economatica.com/en/excel-add-in · https://www.economatica.com/plataforma · https://www.economatica.com/en/platform · https://www.economatica.com/en/solutions/asset-managers · https://www.economatica.com/blog/evolucao-das-carteiras-de-fidcs-12-meses-por-segmento-economatica/ · https://www.economatica.com/blog/fundos-alocam-bilhoes-em-fidcs/ · http://mkt.economatica.com/economatica-presentation.pdf · https://flj.com.br/mercados/economatica-lanca-mcp-inteligencia-de-mercado-agora-acessivel-por-ia/ · https://exame.com/invest/mercados/tc-compra-economatica-por-r-40-milhoes-e-reforca-vertical-b2b/
- https://quantumfinance.com.br/ · https://quantumfinance.com.br/solucao/quantum-axis/ · https://quantumfinance.com.br/en/solutions/quantum-axis/ · https://quantumfinance.com.br/bases-quantum/ · https://quantumfinance.com.br/fidcs-8-ferramentas-poderosas-para-analisar-esses-ativos/ · https://quantumfinance.com.br/retornos-fidcs/ · https://developers.quantumaxis.com.br/ · http://www.quantumaxis.com.br/
- https://www.comdinheiro.com.br/ · https://comdinheiro.com.br/?id=&lang=pt&op=&pag=comdinheiro-full · https://www.comdinheiro.com.br/?lang=pt&pag=comdinheiro-basic&op=&id= · https://www.comdinheiro.com.br/basic/ · https://www.infomoney.com.br/onde-investir/comdinheiro-inova-e-implementa-ia-em-sua-plataforma/ · https://www.infomoney.com.br/mercados/gestoras-aceleram-uso-de-apis-para-facilitar-acesso-a-dados-do-mercado/ · https://br.lexlatin.com/noticias/nelogica-compra-plataforma-comdinheiro
- https://costbench.com/software/financial-data-terminals/bloomberg-terminal/ · https://fintech.global/2026/08/19/bloomberg-extends-askb-ai-assistant-to-mobile-devices/ · https://guides.smu.edu/bloomberg/excel · https://www.bloomberg.com/quote/FIDCBZP:BZ
- https://www.lseg.com/en/solutions/ai-finance-solutions/lseg-mcp · https://www.lseg.com/en/data-analytics/products/workspace/workspace-ai-capabilities · https://www.lseg.com/en/data-analytics/products/workspace/updates/lseg-launches-workspace-add-in-for-excel-and-powerpoint · https://www.lseg.com/en/data-catalogue/funds · https://www.lseg.com/en/data-analytics/financial-data/pricing-and-market-data/equities-market-data/b3-data
- https://docs.kensho.com/agentskills · https://www.anthropic.com/news/advancing-claude-for-financial-services · https://libraryhelp.qub.ac.uk/faq/281720
- https://developer.factset.com/mcp/factset-ai-ready-data-mcp · https://devblogs.microsoft.com/microsoft365dev/factset-for-excel-leverages-the-equivalentaddin-element-for-com-add-in-compatibility/
- https://www.alpha-sense.com/resources/product-articles/generative-search-next-generation/ · https://www.alpha-sense.com/press/alphasense-launches-financial-data/
- https://apps.apple.com/br/app/valor-pro/id616176310 · https://www.aebroadcast.com.br/broadcast-plus/ · https://trademap.com.br/planos/trademap-pro
- https://www.anbima.com.br/pt_br/noticias/dados-sobre-fundos-de-investimento-chegam-ao-anbima-data.htm · https://developers.anbima.com.br/en/documentacao/precos-indices/apis-de-precos/debentures/ · https://developers.anbima.com.br/en/documentacao/fundos/introducao-aos-pacotes/
- https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/up2data/dados-disponiveis/ · https://www.up2dataondemand.com.br/outros/emprestimos-de-ativos (search excerpt)
- https://www.hebbia.com/blog/how-private-credit-teams-use-hebbia · https://siliconangle.com/2026/04/29/rogo-raises-160m-speed-financial-analysis-ai-agents/ · https://www.therundown.ai/tools/fintool · https://www.findmymoat.com/tools/perplexity-finance · https://www.perplexity.ai/app/finance/BBAS3.SA/earnings
- https://maisretorno.com/mcp (search excerpt) · https://www.partnr.ai/api/mcp-dados-financeiros-brasileiros/ · https://github.com/PedroDnT/SILO-BZ/pull/232
