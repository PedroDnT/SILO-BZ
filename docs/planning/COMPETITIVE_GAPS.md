# Competitive gaps

What SILO does for whom, who else does it, what they have that we don't, and
what nobody has. Researched 2026-09-23. Tomé (agentetome.com, by Liqi) is the
benchmark.

This is a snapshot, not a queue. The actions it recommends go to
`OPEN_ITEMS.md` once Pedro picks them (§7).

**Evidence rule.** Every Y or P in the matrix has a URL. `?` means nobody
checked; it does not mean "no". Anything said about a competitor's internals
that its own pages don't state is marked _inference_. It is the same rule the
warehouse follows, applied to research: an unknown stays unknown.

**Segments**, in priority order:

| #   | Segment                                       | Who                                                                                    |
| --- | --------------------------------------------- | -------------------------------------------------------------------------------------- |
| S1  | Investment and financial-market professionals | buy- and sell-side analysts, gestoras, allocators, traders, credit and equity research |
| S2  | Structured-credit professionals               | FIDC, CRI/CRA and FII analysts and allocators                                          |
| S3  | AI agents and developers                      | anyone calling an API or MCP to answer a question                                      |
| S4  | Accountability and research                   | journalists, academics, people working next to regulators                              |

---

## 1. SILO today

### What each layer holds, by population

Measured against `docs/DATA_INVENTORY.md`, `19_api_contract.sql`–`21_*` and a
live `api.coverage()` call on 2026-09-23. Every dataset listed there had landed
that morning.

| Population                            | Ingest                                                                                                                                                                                                                                                                       | Analytical layer                                                                                                                               | API (`api.*`)                                                                                                                                                                                         | Dashboard                                                                                            |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| **Funds**: FI, FIDC, FII, FIP, FIAGRO | daily FI NAV and flows from 2019; FIDC monthly back to 2013 for some tabs (tranches and aging from 2025 only, because CVM publishes no archive of them); FII from 2019/2021; FIP from 2010; FIAGRO from 2025-05; CDA holdings blocks 2, 4 and 6 from 2005                    | `dim_fund`, `fact_fund_monthly`, performance by family, administrator and gestor league tables, **forensic screens**, FIDC delinquency drivers | `funds`, `fund_profile`, `fund_nav`, `search_funds`, `fund_holdings` (both directions), `fund_debentures`, `fidc_cedentes`, `fidc_sacados`, `fidc_portfolio`, `panel` fund metrics, `anbima_classes`  | `/fi`, `/fidc`, `/fii`, `/fund`, `/performance`, `/managers`, `/industry`, `/suspicious`, `/dormant` |
| **CRI/CRA**                           | vehicles, series, cash flows and statements from 2019                                                                                                                                                                                                                        | `fraud_screen_overdue_securit`, maturity wall                                                                                                  | **not served**                                                                                                                                                                                        | `/securit`                                                                                           |
| **Listed companies**                  | ITR/DFP account lines from 2019; IPE events from 2015; the FCA ticker map                                                                                                                                                                                                    | company, ticker and sector joins                                                                                                               | `financials`, `company_financials`, `income_statements`, `lookup`                                                                                                                                     | `webapp/` built but **not deployed**                                                                 |
| **Markets**                           | B3 COTAHIST (every print: equities, BDRs, units, fund quotas, options, termo); the BDI lending book, lending rates and trade-by-trade lending tape with brokers on each leg; investor-type participation; IBOV/IBRA/SMLL constituents; instrument registry; corporate events | short interest (% of float, days to cover), investor flow, ADTV                                                                                | `quotes` and typed views, `quote_history`, `option_chain`, `option_history`, `termo_history`, `short_interest`, `short_interest_by_sector`, `investor_flow`, `lending_trades`, `lending_participants` | `/markets`, `/short`, `/flows`, `/etf`                                                               |
| **Macro**                             | 35 BACEN SGS series (IPCA from 1980), PTAX, Focus; the IBGE IPCA item tree                                                                                                                                                                                                   | —                                                                                                                                              | `inflation`, `inflation_items` (the IPCA set only)                                                                                                                                                    | `/macro`                                                                                             |

Also: `catalog()` and `coverage()` for agents, `llms.txt`, `skill.md`, nine
notebooks, and a Python SDK that is not on PyPI.

Absent throughout:

- no LLM, chat or MCP server of our own
- no user alerts or watchlists
- no Excel add-in or exports
- no per-user API keys
- no adjusted prices, no intraday data, no DI curve, no estimates
- no unstructured documents
- no restatement history (§4.3)

### The jobs it does today

The questions a user can answer with SILO today, and nowhere else free, is a
claim §6 tests.

- **S1**
  - Which funds hold this ticker, or this issuer's debentures, and how much,
    month by month?
  - How short is this stock: % of float, days to cover, borrow rate, and
    which brokerages are lending and borrowing?
  - Are foreigners net buyers this month?
  - What did this company actually file: which income-statement line, and
    in which filing version?
  - What moved the IPCA this month, by item weight?
- **S2**
  - Is this FIDC's delinquency rising, and is the rise real, hidden by asset
    growth, or only a shrinking denominator?
  - How are its receivables aged?
  - How concentrated are its top-25 debtors, and who are the named
    originators, joined to their listed ticker where one exists?
  - Did the senior tranche get what it was promised?
  - Which CRI/CRA series are past maturity and not settled?
- **S3**
  - One `panel` call that mixes tickers and fund CNPJs.
  - A catalog an agent can read, a coverage answer that separates `as_of`
    from `complete_through`, and refusals the agent can act on.
- **S4**
  - Which funds match a suspicious pattern: zombie FIDCs, captive FIIs,
    evergreen aging, dormant shells versus parked capital?
  - Which administrators concentrate them?

---

## 2. The landscape

About 45 platforms, grouped by segment. The full profiles, the per-capability
grids and every source URL are in
[`archive/competitive_research_2026-09-23/`](archive/competitive_research_2026-09-23/),
one file per track. This table is the short version.

| Platform                                                     | Segment     | What it is                                                                                                                                                                                                    | Price                                   | AI / agent                                                  |
| ------------------------------------------------------------ | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- | ----------------------------------------------------------- |
| **Tomé** (Liqi)                                              | S2, S4, S3  | chat agent over CVM/FNET documents; restatement diffs; radar; collateral monitor                                                                                                                              | free, with a quota; enterprise via Liqi | chat, MCP (OAuth), Sheets feed                              |
| **Economatica**                                              | S1          | 40-year database since 1986; terminal, Excel add-in, APIs; adjusted prices; FoF look-through; lending analytics                                                                                               | contract                                | Kento agent; MCP since 2026-05 (contract only)              |
| **Quantum Axis**                                             | S1, S2      | broadest fixed-income base: 2,300+ FIDCs at series level, 226k private-credit titles with PU, 7,300 debentures, curves                                                                                        | contract                                | none found                                                  |
| **Comdinheiro** (Nelogica)                                   | S1          | 24k funds, portfolio consolidation, real-time                                                                                                                                                                 | R$79.90–249.90/mo; PRO enterprise       | NL query assistant; no MCP                                  |
| Bloomberg, LSEG, Capital IQ, FactSet, AlphaSense             | S1          | global terminals; estimates, Excel, documents                                                                                                                                                                 | enterprise                              | assistants, MCPs                                            |
| **ChatGPT for Financial Services** (OpenAI, 2026-09)         | S1          | assistant grounded in LSEG, FactSet, S&P, PitchBook                                                                                                                                                           | enterprise                              | the product is the assistant; **no Brazilian source named** |
| Valor PRO, Broadcast+, TradeMap                              | S1          | news terminals, real-time; TradeMap has retail MCP                                                                                                                                                            | subscription                            | TradeMap MCP (R$29.90)                                      |
| B3 UP2DATA / Trillia                                         | S1          | B3's own paid feeds (curves, corporate actions, historical lending); Trillia = B3's credit/KYC data brand                                                                                                     | paid                                    | —                                                           |
| **Uqbar**                                                    | S2          | CRI/CRA/FIDC/FII operations, 100k documents, league tables since 2007                                                                                                                                         | subscription                            | none found                                                  |
| **Painel FIDC**                                              | S2          | **closest S2 analogue to SILO + Tomé**: FIDCs from 2021, subordination vs regulamento minimum, alerts, restatements, look-through; `PainelFIDC.IA` with citations (much of it claimed, shown in demo screens) | paid                                    | chat with citations                                         |
| FIDCs.com.br, Portal FIDC, Clube FIDC, Tradar                | S2          | FIDC-only portals; Clube FIDC has regulamentos/atas with AI chat and email alerts                                                                                                                             | freemium to paid                        | Clube FIDC chat                                             |
| CR Data (Clube FII)                                          | S2          | CRI/CRA/FII/Fiagro payment flows; **Excel plugin**, API                                                                                                                                                       | paid                                    | —                                                           |
| ANBIMA Data                                                  | S2, S1      | free FIDC dashboard (2025-12); CRI/CRA indicative rates and PU; paid price API                                                                                                                                | free / paid API                         | —                                                           |
| Rating agencies (Austin, Moody's Local, Liberum, Fitch, S&P) | S2          | rating actions, public but scattered and unstructured                                                                                                                                                         | free PDFs                               | —                                                           |
| **brapi**                                                    | S3          | leading BR data API: 75 MCP tools, SDKs; **FIDC monthly + CDA on Pro plan**                                                                                                                                   | R$139.99/mo for FIDC                    | MCP (OAuth)                                                 |
| Mais Retorno                                                 | S3, S4      | fund data API + MCP (no FIDC); holdings since 2014; "casca" (shell-fund) labels                                                                                                                               | paid credits                            | MCP                                                         |
| bolsai, Dados de Mercado, Partnr, Fintz, HG Brasil, OkaneBox | S3          | equity-first APIs; Dados de Mercado has investor flows and bulk dumps; Fintz has point-in-time data                                                                                                           | freemium                                | bolsai MCP                                                  |
| Financial Datasets (US)                                      | S3          | the reference design for agent-first APIs; in Claude's Connectors Directory                                                                                                                                   | freemium                                | MCP                                                         |
| **Status Invest, Investidor10**                              | S4 / retail | stock/FII screeners, watchlists; Status Invest has FactSet consensus; Investidor10 has beta chat                                                                                                              | freemium                                | Investidor10 Chat IA (beta)                                 |
| Fundamentus, Funds Explorer, Clube FII, Kinvo, Gorila        | retail      | screeners, portfolio consolidation                                                                                                                                                                            | freemium                                | —                                                           |
| Case de Valor                                                | retail, S1  | short interest (latest session only), options Greeks, "Smart Money" score                                                                                                                                     | freemium                                | —                                                           |
| **CNN Stocks** (2026-04)                                     | retail      | widget dashboard over TradingView plus CNN Money news; **no funds, FIDC, lending or flows**                                                                                                                   | free / R$49.90                          | —                                                           |
| NEFIN-USP, Base dos Dados, Brasil.io                         | S4          | academic factors and market-average lending since 2012; CVM data in BigQuery; CNPJ ownership graph                                                                                                            | free                                    | —                                                           |
| CVM RAD, FNET, dados.cvm, B3 BDI                             | all         | the raw sources everyone above builds on                                                                                                                                                                      | free                                    | —                                                           |

Three things the landscape says:

1. **The incumbents that professionals pay for already have MCPs and
   agents.** Economatica shipped its MCP in May 2026; FactSet, LSEG and S&P
   have theirs. "AI access to financial data" is no longer a gap anyone can
   own. What is still open is **which data** that access reaches.
2. **Structured credit is crowded at the UI layer and empty at the API
   layer.** There are five or more FIDC portals. The only API with FIDC data
   is brapi's, which returns the top 2 cedentes behind a R$139.99/month plan.
3. **Media and bank assistants don't touch Brazilian filings.** CNN Stocks is
   quotes and news. OpenAI's financial ChatGPT names no CVM, B3 or BACEN
   source. The Itaú agent is closed to customers and recommends products.

## 3. The comparison matrix

Organised by capability: who has it, and where SILO stands. A platform named
in a row has a cited Y or P in its track file. A platform left out is
unknown, not absent.

| Capability                                                                     | SILO                                                                      | Who offers it                                                                                                               |
| ------------------------------------------------------------------------------ | ------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| FIDC informe internals (cedentes, top-25 sacados, SCR ladder, aging, tranches) | **Y, free API**                                                           | Painel FIDC (UI, paid), Tradar (partial), brapi (top 2 only, paid), Tomé (chat)                                             |
| CRI/CRA at operation level (PU, payments, events)                              | P: held, **not served**                                                   | Uqbar, Quantum, CR Data, ANBIMA Data, trustees (own deals)                                                                  |
| Fund holdings look-through                                                     | Y (CDA blocks 2, 4, 6)                                                    | Economatica, Quantum, Mais Retorno, brapi (Pro)                                                                             |
| **Fund → debenture issuer → listed-company statements**                        | **Y**                                                                     | none found                                                                                                                  |
| **Fund → stock → lending book**                                                | **Y** (joinable)                                                          | none found                                                                                                                  |
| Listed-company statements                                                      | Y (as filed)                                                              | everyone in S1; Economatica with 40-year history                                                                            |
| Company events / fatos relevantes                                              | P: held, **not served**                                                   | Economatica, Comdinheiro, CNN Stocks, Tomé                                                                                  |
| Analyst estimates                                                              | N                                                                         | FactSet (via Status Invest), global terminals                                                                               |
| EOD equities and options                                                       | Y (unadjusted)                                                            | everyone                                                                                                                    |
| Adjusted / total-return prices                                                 | **N**                                                                     | Economatica, Mais Retorno, bolsai, brapi, Dados de Mercado, Fintz                                                           |
| Intraday / real-time                                                           | N                                                                         | Economatica, Comdinheiro, Broadcast+, Valor PRO, CNN Stocks (via TradingView)                                               |
| DI curve, futures                                                              | N                                                                         | Economatica, Quantum, UP2DATA, brapi, Dados de Mercado                                                                      |
| Secondary fixed-income prices (ANBIMA)                                         | N                                                                         | ANBIMA (source, paid API), Economatica, Quantum, Comdinheiro                                                                |
| Securities lending: open book, % of float                                      | Y                                                                         | Economatica (per stock, since 2014, paid), Status Invest (snapshot), Case de Valor (latest session), NEFIN (market average) |
| **Lending trade tape with the brokerage on each leg**                          | **Y** (archived since capture began)                                      | none found; B3 sells raw history                                                                                            |
| Investor-type flows                                                            | Y                                                                         | Dados de Mercado                                                                                                            |
| Macro (BACEN, Focus, IBGE)                                                     | Y (IPCA served; the rest held)                                            | most S1 and S3 vendors                                                                                                      |
| Unstructured documents (regulamentos, atas, ratings)                           | **N**                                                                     | Tomé, Painel FIDC, Clube FIDC, Uqbar, Quantum, AlphaSense                                                                   |
| Restatement / version history                                                  | **N**                                                                     | Tomé, Painel FIDC (claimed)                                                                                                 |
| Subordination vs regulamento minimum                                           | **N**                                                                     | Tomé (radar), Painel FIDC (claimed)                                                                                         |
| Rating actions, structured                                                     | N                                                                         | Uqbar (per operation), Painel FIDC (alerts, claimed); no free cross-agency feed                                             |
| **Forensic screens** (zombie, captive, evergreen, dormant, overdue)            | **Y** (dashboard only, **not in the API**)                                | none found as a standing product; Painel FIDC's gated "robo-auditoria" is unknown                                           |
| Alerts / watchlists                                                            | **N**                                                                     | Painel FIDC, Clube FIDC, Economatica, Quantum, Status Invest, Investidor10, CNN Stocks, Tomé                                |
| Screeners                                                                      | P (dashboard)                                                             | bolsai, brapi, Status Invest, Investidor10, Mais Retorno                                                                    |
| Fund risk statistics (Sharpe, drawdown)                                        | N                                                                         | Mais Retorno, Dados de Mercado                                                                                              |
| Excel / Sheets                                                                 | **N**                                                                     | Economatica, Quantum, CR Data, FactSet, Tomé (Sheets), brapi (recipes)                                                      |
| REST API                                                                       | **Y, free, no signup**                                                    | every S3 vendor, with signup; incumbents by contract                                                                        |
| Own remote MCP                                                                 | **N**                                                                     | brapi, Mais Retorno, bolsai, Economatica, TradeMap, Tomé, Financial Datasets                                                |
| NL chat                                                                        | N (by design so far)                                                      | Tomé, Economatica Kento, Comdinheiro, Clube FIDC, Painel FIDC, Investidor10                                                 |
| Coverage / freshness contract                                                  | **Y** (`coverage()`, `as_of` ≠ `complete_through`)                        | Tomé (manifest; worst-case reporting); no API vendor                                                                        |
| Explicit no-fabrication stance                                                 | Y                                                                         | Tomé, Painel FIDC ("ausente, nunca como zero")                                                                              |
| Process lineage (which code produced a number; reproducible)                   | P: deterministic code and an audit row per ingest; no commit SHA recorded | none claims it (§4.5)                                                                                                       |

---

## 4. Tomé, and what its document layer would take us

### 4.1 What Tomé is

A free AI agent over CVM filings, built by Liqi, a securitizadora that
tokenizes assets. Public since about July 2026. It had had 24,149 questions by
2026-09-23 (`/api/stats`). The main source for this section is Tomé's own
[`/como-funciona`](https://www.agentetome.com/como-funciona), which explains
its pipeline "in 10 acts".

**The structured numbers come from the same place ours do.** Its entity pages
cite dados.cvm.gov.br for the FIDC and CRI/CRA informes and are refreshed about
weekly ("Base do informe de agosto · atualizado em 16/09"). Its lead is in
three layers it builds **over B3's Fundos.NET (FNET)**, and none of the three
is in SILO today.

### 4.2 Its pipeline

Stated on its pages unless marked _inference_.

1. **Acquisition.**
   - Nine public sources and 36 document types: FNET, dados.cvm, CVM RAD,
     COTAHIST, BCB, and the Receita Federal CNPJ registry.
   - About 1,900 automated runs a day, looking for new filings several times
     a day.
   - A filing becomes answerable about 14 hours after it is filed; 90% of
     filings do so within 22 hours.
2. **Formats.**
   - PDF, the CVM CSV zips, FNET XML (224,807 files), and old portal pages.
   - About 3% of documents are images only; OCR recovers 95.4% of them.
   - The average regulamento is 53 pages.
3. **Extraction.**
   - An LLM proposes a fact **together with a quote and a page**.
   - A separate deterministic program checks three things: that the quote
     is on that page, that the value is plausible, and that the date fits
     the fund's timeline. A fact that fails is discarded, not repaired.
   - 22,447 invented quotes were rejected in regulamentos alone.
   - A second, stronger model audits a sample and found problems in 12.2% of
     documents.
   - 28 extraction scripts cover 409 fields: covenants, subordinação mínima,
     fees, series rates from AGE minutes, ratings, CRI cedentes.
   - About 70% of regulamentos are covered.
4. **Versions.** FNET marks every filing's `modalidade`: AP for the original,
   RE for a voluntary restatement, RC for one required by CVM. It also gives
   `versao`, and old versions stay downloadable. Tomé:
   - pairs the versions
   - diffs them field by field
   - flags "risco subiu" when delinquency, provisions or credit
     classification go up
   - measures the lag between versions (mean 312 days)

   It has counted 29,846 restatements. Re-uploads that are identical under a
   new protocol, about 7% of the archive, are removed as duplicates.

5. **Entity resolution.**
   - 359k identifiers.
   - One administrator is matched across the several legal names it files
     under.
   - A provider graph of 98,475 links across 25 roles and 3,432 institutions.
   - Portfolios are linked to CRI/CRA by ISIN.
6. **Answering.**
   - "O Tomé não faz isso" about embeddings: it searches exact text and
     declared numbers.
   - It has 143 tools, the model "não tem permissão de gerar número", and
     seven checks run before an answer is shown.
   - Every answer carries an FNET `informe_id` that the "prova dos nove"
     button resolves to the document.
   - It refuses in three states: an answer, "não tenho isso", and "eu não
     olhei".
   - _Inference:_ Postgres full-text search; 91 Portuguese full-text indexes
     are mentioned.
7. **Access.**
   - The MCP needs OAuth with PKCE or a `tome_…` key. An unauthenticated
     `POST /api/mcp` returns 401, so its tool list is not public.
   - Free with a quota: 80 questions a day with an account.
   - A Sheets/Excel feed, capped at 60 calls an hour.
   - Enterprise is sold through Liqi.

Not knowable from outside:

- which LLM and OCR engine it uses
- the MCP tool list
- the schema of an extracted fact
- how covenants pass the curation step
- accuracy: only an 81% grader agreement on its 1,004-question test set is
  published
- enterprise prices

Liqi's operating model, the agents that update themselves, is in §4.5.

### 4.3 What the FNET spike showed we could do

49 read-only requests on 2026-09-23, at 1 per second.

- **The endpoint is public.**
  `GET https://fnet.bmfbovespa.com.br/fnet/publico/pesquisarGerenciadorDocumentosDados`
  with `X-Requested-With: XMLHttpRequest`. No login, cookie or session.
  - Pages of at most 200 rows.
  - Queries need a date window; without one only 533 rows come back.
  - `tipoFundo`: 1 = FII, 2 = FIDC, 3 = ETF.
  - CRI/CRA sit behind a separate certificates endpoint, which was not
    tested.
- **Versions are explicit, and old ones can still be downloaded.**
  - Each version gets a new `id`; the superseded one moves to status `IC`
    and stays downloadable.
  - HGLG11's quarterly informe for 2025-12 went v1 → v2 → v3 (ids 1116059,
    1199333, 1237221).
  - FIDC PCG Brasil's 2024-12 monthly informe has three versions.
  - Nothing links a version to its parent, so they are grouped by (fund,
    category, type, species, reference date).
- **Structured informes are plain XML**, and the FIDC one uses the same
  `TAB_*` fields as the CVM CSVs we already parse. A diff is therefore field
  by field against our existing field maps.
- **PDFs are born-digital.** All 9 of the 9 sampled had a text layer.
  Financial statements can be encrypted; relatórios gerenciais are mostly
  images.
- **Scale.** About 979k documents from 2016 to 2026-09-23. The 2026 pace is
  about 267k a year.
- **Quirks.**
  - Search rows leave `cnpjFundo` null; the CNPJ is only in the download
    filename.
  - Some downloads take 60–120 s.
  - There is no `robots.txt` (404) and no published terms.
  - A firewall cookie is set on every response, so throttling could start
    without notice.

**Our own version loss, found while checking.**

- `cvm_fii_mensal` and `cvm_fii_periodic` receive CVM's `Versao` but keep it
  out of the natural key, so a restatement overwrites the original. The same
  applies to `cvm_securit_fluxo` and `cvm_fi_perfil`. **FII fixed 2026-09-24**
  (migration 43, see B4): both FII keys now include `versao`.
- CVM's FIDC CSVs carry no version field at all (all 18 metadata files were
  checked). **FNET is the only public source of FIDC restatement history.**
- `cia_event.link_download` already points at versioned CVM RAD PDFs
  (`numVersao`) that can be fetched and have text.

**Storage** (Supabase has about 25.6 GB of headroom at 81% of 135 GB):

| What is stored                     | Estimate                                                   | Fits?                                             |
| ---------------------------------- | ---------------------------------------------------------- | ------------------------------------------------- |
| FNET metadata, one row per version | 0.5–1.0 GB, +0.27 GB/yr                                    | yes                                               |
| Extracted text, ~590k PDFs         | ~8–12 GB compressed (unverified; assumes ~20 pages × 2 KB) | a third to a half of the headroom                 |
| The PDFs themselves                | ~300 GB (mean 506 KB), +80 GB/yr                           | no; needs object storage or on-demand fetch by id |
| Embeddings                         | ~70 GB                                                     | no, and Tomé shows they aren't needed             |

For comparison, Tomé states 222–462 GB of data.

### 4.4 Where Tomé's value comes from, and what each piece needs

| Capability                                                                           | What it needs                                              | Do we have it?                                     |
| ------------------------------------------------------------------------------------ | ---------------------------------------------------------- | -------------------------------------------------- |
| Restatement history, voluntary vs required by CVM, "risco subiu"                     | **FNET version metadata + XML** only                       | no, and our FII keys discard it                    |
| Filing deadlines, "silent" funds, filing lag                                         | **FNET delivery dates** vs the CVM calendar                | no                                                 |
| Provider graph (one institution across roles)                                        | structured registry fields, plus FNET administrator fields | partial: `dim_administrator` and `dim_gestor`      |
| Look-through and simple signals (portfolio → CRI/CRA by ISIN; unpaid credits rising) | structured data **we already hold**                        | mostly yes; not served for CRI/CRA                 |
| Subordination vs its **minimum**; covenant headroom                                  | the minimum is in the regulamento, **unstructured**        | no                                                 |
| Event feed with verbatim quotes (AGE decisions, fatos relevantes, CRI waivers)       | **unstructured** FNET PDFs                                 | no; `cia_event` holds the links for companies only |
| Ratings (grade, outlook, up- and downgrades)                                         | **unstructured** rating PDFs on FNET                       | no                                                 |

The two most valuable pieces for S2, versions and delivery metadata, **need no
PDF reading and no LLM**. They are metadata and XML, the kind of source SILO is
already built to ingest under its integrity rules.

### 4.5 Liqi's operating model

Pedro heard Liqi's CEO say in a talk that they "don't even know which agents
are running because they self-update". The full evidence is in
[`liqi_operating_model.md`](archive/competitive_research_2026-09-23/liqi_operating_model.md).

- **The quote is not in any public transcript.** Both were read in full:
  Talkenização ep. 187, "constelação de agentes", Part 1 (2026-09-16), and
  "Liqi faz 5 anos" (2026-04-29). Part 2 is teased with "quem garante que
  esses agentes não erram, quem vigia eles?" and was not yet published on
  2026-09-23. It is the likeliest recorded source.
- **What is on record:**
  - agent "identities" are updated as agents take on tasks
  - agents learn from corrections while in use
  - some processes no longer get human review
  - "Tudo que eles fazem é registrado e fica auditável"
- **The agent count is 13, 15+, 16, 17, 18 or 20+ depending on the source.**
  Pipeline counts run from 71 to 144, and daily runs from 201 to about 1,900.
  An outsider cannot reconstruct what is running. That fits the spirit of
  the quote, even though the words are not on record.
- **For Tomé itself, Liqi says the opposite.** On `/como-funciona`, the
  improvement loop is automatic "até a fila": gaps are detected and queued
  automatically, but "a construção da capacidade nova ainda passa pela mão de
  quem desenvolve". The velocity is AI-assisted engineering, about 125
  commits a day from a 2026-07-16 start. It is not a system building itself.

**What a regulated buyer cannot answer about a Tomé number.** Each item is
_inference_ from what Tomé does not publish.

- Which extractor, model and prompt version produced it.
- Whether re-running would reproduce it. LLM extraction is admitted to be
  non-deterministic.
- Whether it was in the 12.2% of audited documents with a finding.
- Which regulamento version applied to a derived figure such as covenant
  headroom.
- Whether Tomé's own re-extractions changed it after an answer was given.

Tomé is excellent at **finding and citing** a source. It does not yet claim
to be a **system of record** for the number itself.

**Copy:**

- "Every line starts the day red": a check fails when a slice ran but
  produced nothing.
- A third state, "didn't check", kept separate from pass.
- Treat the gap log as the build queue.
- A public "how it works" page with measured numbers.
- Restatement pairs.
- If an LLM ever reads text here: the model proposes, deterministic code
  verifies, and a failure is rejected, never repaired.

**Avoid:**

- Unversioned learning at runtime. What SILO computes must stay a pure
  function of (source file, git commit).
- Self-descriptions nobody generated from the system.
- Autonomy claims as a selling point.
- Chasing PDF coverage at Liqi's pace, which brings Liqi's error class
  with it.

---

## 5. Gaps A: they have it, we don't

Tagged **Adopt** (build it our way), **Adapt** (build a narrower version
that fits our rules), or **Skip** (conflicts with "will not do", or needs
licensed data).

| Gap                                                                                           | Segments   | Who has it                                      | Tag              | Why                                                                                                                                                                         |
| --------------------------------------------------------------------------------------------- | ---------- | ----------------------------------------------- | ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Restatement / version history                                                                 | S2, S4, S1 | Tomé, Painel FIDC                               | **Adopt**        | FNET publishes it (§4.3). Metadata and XML only. The only public source of FIDC restatements.                                                                               |
| Filing punctuality, "silent" funds                                                            | S2, S4     | Tomé                                            | **Adopt**        | FNET delivery dates vs the CVM calendar. Structured.                                                                                                                        |
| Own remote MCP (read-only, free)                                                              | S3, S1     | brapi, Mais Retorno, bolsai, Economatica, Tomé  | **Adopt**        | Table stakes for agent traffic. A thin layer over schema `api`; tool descriptions carry the refusal semantics.                                                              |
| Serve what we hold: CRI/CRA, FIDC tranches and aging, screens, IPE events, macro, PTAX, Focus | S2, S4, S1 | Uqbar, Quantum, ANBIMA (CRI/CRA)                | **Adopt**        | Already in the warehouse (`DATA_INVENTORY.md` §3). Cost is endpoints and tests.                                                                                             |
| Excel / Sheets delivery                                                                       | S1, S2     | Economatica, Quantum, CR Data, Tomé             | **Adapt**        | CSV straight from PostgREST (`Accept: text/csv`) plus documented Sheets and Excel recipes. No add-in. Needs verifying that a Sheets import can pass the key.                |
| Alerts / watchlists                                                                           | S1, S2     | nearly everyone paid                            | **Adapt**        | Only on signals we compute (restatement filed, delinquency driver flips, screen entry, filing missed). Needs per-user state, so it comes after B1–B3 in §7.                 |
| Subordination vs regulamento minimum                                                          | S2         | Tomé, Painel FIDC                               | **Adapt, later** | The minimum lives in the regulamento, so this needs the document layer (Stage 3) with deterministic quote verification.                                                     |
| Adjusted / total-return prices                                                                | S1         | Economatica, Mais Retorno, bolsai, brapi, Fintz | **Adapt**        | The factor convention was measured below the 90% bar (`INSTRUMENTS.md`). Serve the events and let the caller adjust. Publish adjusted series only where verified per event. |
| DI curve, futures                                                                             | S1         | Economatica, Quantum, brapi, Dados de Mercado   | **Adopt**        | Public B3 files; already `INSTRUMENTS.md` Phases B and C.                                                                                                                   |
| Fund risk statistics                                                                          | S1, S3     | Mais Retorno, Dados de Mercado                  | **Skip**         | Reductions of a panel. The notebook stance holds; document a recipe instead.                                                                                                |
| Structured rating actions                                                                     | S2         | Uqbar, Painel FIDC                              | **Adapt, later** | FNET carries rating PDFs. The type and date alone are metadata (Stage 1); the grade needs the text.                                                                         |
| Document search and chat                                                                      | S2, S1     | Tomé, Painel FIDC, Clube FIDC                   | **Adapt, later** | Stage 3: exact-text search over per-page text, quotes only, no generated numbers. No chat of our own; the MCP lets the caller's model do the talking.                       |
| Analyst estimates                                                                             | S1         | FactSet, terminals                              | **Skip**         | Licensed.                                                                                                                                                                   |
| Intraday / real-time                                                                          | S1         | terminals                                       | **Skip**         | Not public end-of-day data; `INSTRUMENTS.md` scopes it out.                                                                                                                 |
| Secondary prices (ANBIMA)                                                                     | S1, S2     | ANBIMA (paid), vendors                          | **Skip**         | The paid API makes it licensed data. Revisit if ANBIMA publishes openly.                                                                                                    |
| Proprietary scores / rankings of good and bad                                                 | S2         | Portal FIDC, Status Alpha                       | **Skip**         | "No rating" is a rule here, and Tomé holds the same line.                                                                                                                   |
| NL chat UI of our own                                                                         | S1–S4      | many                                            | **Skip for now** | The MCP puts SILO inside the caller's assistant. A chat of our own is a product and cost decision, not a data gap.                                                          |

## 6. Gaps B: white space

What nobody offers, checked with negative searches. The queries and pages
checked are listed in each track file's §4.

| Candidate                                                                                              | Verdict                                                       | Evidence                                                                                                                                                                                                                                                                                                                                  |
| ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **(a) Lending trade tape with the brokerage on each leg, archived beyond B3's ~21 days**               | **White space, confirmed** by tracks 2, 4 and 5 independently | No API vendor has any lending data. Case de Valor shows the latest session only; ADVFN three days; Status Invest a snapshot. Economatica has per-stock daily lending stock since 2014 (paid) but no trades or brokers. **Qualification:** B3 sells history through UP2DATA, so the archive is irreplaceable _for free_, not at any price. |
| **(b) Fund → debenture issuer → listed-company statements; fund → stock → lending book**               | **White space, confirmed**                                    | brapi's CDA carries `issuerCnpj` with no company join. Mais Retorno has fund → holdings, no reverse page, no lending. Painel FIDC has FIDC-only look-through.                                                                                                                                                                             |
| **(c) Forensic screens as a standing public product**                                                  | **White space for free and public use; contested on S2**      | None found as a product. Demand shows in press coverage of the Master and Carbono Oculto cases, done by hand. Painel FIDC's gated "robo-auditoria" is unknown. Mais Retorno labels shells. **Today ours are dashboard-only.**                                                                                                             |
| **(d) An agent API that is honest about coverage**                                                     | **Shared with Tomé, unique among API vendors**                | brapi's coverage endpoint is per ticker; nobody else separates `as_of` from `complete_through`.                                                                                                                                                                                                                                           |
| **(e) One free warehouse across FIDC + CRI/CRA + FII + funds + B3 tape + lending + macro + companies** | **White space**                                               | Every S2 vendor covers one family. Every S3 vendor is equity-first. The incumbents that span it are contract-only.                                                                                                                                                                                                                        |
| **(f) Process lineage as a trust feature**                                                             | **Unclaimed**; demand untested                                | No vendor claims number-level reproducibility (§4.5). We are one field short of claiming it ourselves: `cvm_ingest_log` does not record the commit.                                                                                                                                                                                       |
| FIDC internals as free API data (top-25 sacados, SCR ladder, named cedentes → ticker)                  | **White space**                                               | brapi returns only the top 2 cedentes, paid. Painel FIDC is a UI.                                                                                                                                                                                                                                                                         |
| **Brazilian filings inside the big assistants**                                                        | **An open slot** (_inference_)                                | OpenAI's financial ChatGPT names LSEG, FactSet, S&P and others, and no Brazilian source. Economatica's MCP is contract-only.                                                                                                                                                                                                              |

**The pattern.** Our white space is not one feature. It is **free, joined,
honest structured data that nobody else holds in one place**. The gaps
that matter most are all about **reach**: an MCP, a spreadsheet recipe, the
datasets we hold but don't serve, and the version and delivery metadata that
FNET gives away. Almost nothing on the Adopt list needs licensed data, an LLM
in the pipeline, or a change to the integrity rules.

---

## 7. The backlog

Ranked by value to the primary segments over cost. Each item is written as a
branch: hypothesis, key assumption, smallest useful test, rejection evidence.
Nothing here is scheduled until Pedro picks it; the picked items then go to
`OPEN_ITEMS.md`.

### B1. FNET register, Stage 1: one row per document version (**recommended first**)

**Status 2026-09-24: built, and the smallest test passed** (migration 42, `src/pipeline/fnet_pipeline.py`). A live backfill of delivery days 2026-09-01..23 counts **608 restated FIDC monthly informes (603 voluntary, 5 CVM-required)**; Tomé's "reapresentações do mês" page, updated 23/09, shows 598 with ~1% CVM-required. Within 2% (the rejection bar was ±5%); the gap is plausibly the 23rd's late filings. August 2026 in full: 26,440 documents, 3,483 of them versions ≥ 2. Serving it through `api` is the next step.

- **Serves:** S2, S4, S1.
- **Cost:** a new fetcher, one table, one migration, wiring into `run_daily`
  through the gap-aware window, and offline tests with a JSON fixture.
- **Storage:** about 1 GB, plus 0.27 GB a year.
- **Integrity:** natural key `(fnet_id)`, carrying `versao`, `modalidade` and
  `status`. There is nothing to infer. The fund CNPJ is read from the file
  name as published, and the risks are documented in §4.3.
- **Hypothesis.** Version and delivery metadata alone support three
  products, with no PDFs and no LLM: restatement counts (voluntary vs
  required), filing punctuality and silent funds, and the provider graph.
- **Key assumption.** FNET keeps answering unauthenticated, date-windowed
  queries at 1 request per second.
- **Smallest test.** Backfill one month of FIDC documents. Then reproduce
  Tomé's "reapresentações do mês" count for that month within ±5%.
- **Reject if** throttling or blocking stops a one-month backfill, or the
  count can't be reconciled.

### B2. A read-only remote MCP over schema `api`

**Status 2026-09-24: built, not deployed.** `supabase/functions/silo-mcp/` is a Supabase Edge Function (the owner chose Supabase over Vercel for hosting). It speaks stateless streamable HTTP and exposes 49 tools, one for each `catalog().postgrest` endpoint plus `catalog` itself. Every tool is `readOnlyHint`, makes one PostgREST call with the public key, and returns PostgREST errors verbatim as `isError`. `tests/test_mcp_contract.py` pins the tool list to the catalog and to `openapi.json`. The function goes live after merge, with `supabase functions deploy silo-mcp --project-ref zcjbtpxuhdekpwcxmepn --no-verify-jwt`. The smallest test below is still to run. Docs: `api-docs/mcp.mdx`.

- **Serves:** S3, S1.
- **Cost:** a thin server. It calls PostgREST, with one tool per `api`
  function (`catalog`, `coverage`, `lookup`, `panel`, `fund_*`, `fidc_*`,
  `short_interest`, `lending_*`, `investor_flow`, `financials`), all marked
  `readOnlyHint`.
- **This is a new runtime,** so hosting is Pedro's call. A Vercel function is
  the obvious candidate, since Vercel already hosts the dashboard.
- **Hypothesis.** Agents prefer a free, no-signup MCP whose tools refuse
  honestly. It then becomes the default Brazilian source inside Claude and
  ChatGPT.
- **Key assumption.** Anonymous limits (3 ids, 1,000 rows) are enough for a
  useful first answer.
- **Smallest test.** Rerun `archive/API_FIELD_TEST_2026-08-28.md`: give a
  fresh agent its FIDC delinquency × sector equity question, with only the
  MCP connected.
- **Reject if** it rates discoverability no better than the REST run's 6/10,
  or can't finish the query plan.

### B3. Serve what we already hold

- **Serves:** S2, S4, S1.
- **The endpoints:**
  - `fidc_tranches` and `fidc_aging`, in the `fund_nav` style
  - the forensic screens, moved into schema `api` as views, which also
    closes the `public` grants gap in `DATA_INVENTORY.md` §3
  - `company_events`
  - `macro_series` and `ptax`
  - CRI/CRA last, because it needs a third kind of id
- **Cost:** each one is an endpoint, a catalog entry and a test, following
  `19_api_contract.sql`.
- **Hypothesis.** The two confirmed white spaces we hold, (c) and FIDC
  internals, only count once a caller can reach them.
- **Smallest test:** ship `fidc_tranches` and the screens. Check that the
  B2 MCP can answer "which FIDCs match the evergreen-aging screen and how did
  their senior tranche do".
- **Reject if** the screens produce false positives the catalog cannot
  explain. The fix then is the screen, not the serving.

### B4. Restatement diffs, Stage 2, and our own version loss

- **Serves:** S2, S4.
- **Depends on:** B1.
- **What it does.** Fetch the XML for every group with more than one
  version, parse it with the existing FIDC and FII field maps, and store the
  diffs field by field.
- **Our own version loss: decided and done for FII (2026-09-24).** Pedro
  approved putting `versao` into the keys of `cvm_fii_mensal` and
  `cvm_fii_periodic`. Migration 43 does it (`NULLS NOT DISTINCT`, backfilled
  from `raw`), and every reader moved to `vw_fii_mensal_latest` /
  `vw_fii_periodic_latest`, one row per former key at the highest version, so
  no downstream number changed meaning. Rows stored before the change hold
  only the version CVM shipped at our last fetch. From now on every version
  CVM's files carry is kept, which gives Stage 2 an FII diff source of our
  own. `cvm_securit_fluxo` and `cvm_fi_perfil` are still open.
- **Hypothesis.** "What did the fund first declare, and what did it change?"
  is answerable for FIDCs only through FNET, and only SILO would serve it as
  data.
- **Smallest test.** One FIDC with three versions (PCG Brasil, 2024-12). The
  diff matches a manual reading.

### B5. Sheets and Excel recipes over CSV

- **Serves:** S1, S2.
- **Cost:** documentation, plus a check that the anon key can be passed where
  `IMPORTDATA` can't set headers.
- **Hypothesis.** Professionals live in spreadsheets, and a recipe gets us
  most of what an add-in would.
- **Reject if** a key can't be passed safely. The fallback is signed
  one-hour export links, like Tomé's.

### B6. Lineage you can see

- **Serves:** S1 (regulated buyers), S4.
- **What it does.** Record the git commit and parser version in every
  `cvm_ingest_log` row, and expose it through `coverage()`.
- **Hypothesis.** "Which code produced this number, and would it produce it
  again" is a question no competitor can answer (§4.5 and white-space (f)).
  One field lets us.
- **Smallest test:** it's a one-migration change. Then ask two allocators or
  auditors whether it changes what they would rely on. **Reject if** neither
  cares.

### B7. The governed agent loop (Scout, Builder, Sentinel)

- **Serves:** how the backlog gets done, not a segment.
- **Design:** the registry, prompts versioned in the repo, one PR per run, a
  3-PR budget, and retirement if fewer than half its PRs merge. Picked, and
  written up as [`AGENTS.md`](AGENTS.md) on 2026-09-24.
- **Smallest test:** one manual Builder run on FIDC `tab_X_7`. **Reject if**
  the PR needs rework comparable to writing it by hand.

### Later, in order

- **B8. DI curve and futures.** `INSTRUMENTS.md` Phases B and C. An S1 table
  stake.
- **B9. Alerts.** Only on B1, B3 and B4 signals, and only after they exist.
- **B10. Document text, Stage 3.** Priority categories only; object storage
  for the PDFs; deterministic quote verification. Subordination vs minimum
  and rating grades come from here.
- **B11. Per-event adjusted prices,** where verified.

### Recommendation

- **First build: B1.** It closes the biggest part of Tomé's structural lead,
  which is versions and delivery, not PDFs. It serves S2 and S4 directly,
  fits the architecture and the integrity rules without exception, and
  fits the storage headroom.
- **Next: B3 and B2.** B3 is cheap and puts the white space we already own
  within reach. B2 is the reach itself.
- **B6 is a one-migration change.** It can ride along with any of the above.
