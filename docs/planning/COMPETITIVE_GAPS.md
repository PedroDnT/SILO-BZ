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

_Filled from tracks 2–6._

## 3. The comparison matrix

_Filled from tracks 2–6._

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
  applies to `cvm_securit_fluxo` and `cvm_fi_perfil`.
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

_Filled from the follow-up track._

---

## 5. Gaps A: they have it, we don't

_Filled from tracks 2–6._

## 6. Gaps B: white space

_Filled from tracks 2–6._

## 7. The backlog

_Filled last._
