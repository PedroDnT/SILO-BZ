# Track 3 — Structured-credit platforms (S2: FIDC, CRI/CRA, FII), Brazil

Research date: 2026-09-23. Evidence rule from TAXONOMY.md applies: Y/P only with a URL fetched or a search excerpt seen; `?` = unknown. "Outside stated scope" means the vendor's own pages list their instrument scope and the item is not in it; that is an inference, so it is marked `?`, not `N`.

Important caveat on Painel FIDC: its public pages show product screens that are explicitly labelled "interface ilustrativa / dados demonstrativos". Features seen only in those mockups or in marketing copy are graded **P (claimed)**. I did not log in anywhere, so I checked no gated feature in a live product.

---

## 1. DEEP profiles

### 1.1 Uqbar (home.uqbar.com.br / uqbar.com.br; legacy product TLON)

- **Who:** Uqbar, a São Paulo firm that has covered Brazilian structured finance for about 20 years. The search excerpt says it has collected data "since 2003" ([quem-somos](https://uqbar.com.br/quem-somos/)). It publishes the reference **Anuários** (yearbooks) for CRI, CRA, FIDC and FII, plus service-provider **league tables "desde 2007"**. Law firms and auditors cite these rankings in their own marketing (e.g. [VBSO](https://vbso.com.br/en/vbso-securitizacao-ranking-uqbar/), [Next Auditores](https://nextauditores.com.br/noticia/next-mais-uma-vez-lider-no-ranking-uqbar-em-numero-de-operacoes-em-fidc/)). The old TLON platform (tlon.com.br) is migrating into the new Uqbar Platform (search excerpt).
- **What:** "Dados, análises e conexões do mercado de crédito e de capitais reunidos em uma única assinatura". The platform claims 11.5k+ operations of CRA/CRI/FIDC/FII, 6.5k+ articles, 100k+ organised documents and 2.6k+ institutions. Each operation has its own page with "informações avançadas sobre o mercado secundário e histórico de classificação de risco". Other features: CSV export of saved screens (PL evolution, atrasos, PDD, documentation), rankings exportable as CSV/PDF, a personal "Radar" of market indicators, and a fixed-income / fund-quota pricing calculator ([plataforma-institucional](https://uqbar.com.br/plataforma-institucional/)). It also runs a marketplace, courses and networking ([home](https://home.uqbar.com.br)).
- **Sources/licensors:** analyst-curated. "Estrutura e processa... através da expertise de analistas" ([quem-somos](https://uqbar.com.br/quem-somos/)). Specific licensors are not stated. The inference is that it draws on CVM, B3/FNET and offering documents.
- **Pricing:** not public. The pricing pages (/planos, /precos-e-planos, lp.uqbar.com.br/planos-de-assinatura) are JS-rendered, returned 404, or were empty to fetch. A search excerpt mentions an "Equipe" (team) plan. Institutional, demo-led sales.
- **Segment:** S2 core: structurers, originators ("tomadores"), investors ("doadores"), and service providers (law firms, auditors, trustees) who buy ranking visibility and anuário sponsorship ([anuarios2026](https://anuarios2026.uqbar.com.br/)).
- **AI features:** none found. A search for Uqbar AI/radar alerts returned nothing relevant.
- **Differentiators:** CRI/CRA **operation-level** coverage with rating history and secondary-market data; 20 years of curated history; the de-facto league tables of the industry; a document library; an editorial/news brand; an events and education business.
- **Weaknesses:** no public API or MCP found; opaque pricing; aimed at humans. It shows no forensic screening, no citation per number, and no restatement versioning. Its FI/listed-company/B3 coverage is outside stated scope.

| ID      | value                     | evidence URL                                                                | note                                                             |
| ------- | ------------------------- | --------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| C1      | ?                         | https://home.uqbar.com.br                                                   | outside stated scope (CRA/CRI/FIDC/FII)                          |
| C2      | Y                         | https://uqbar.com.br/plataforma-institucional/                              | PL evolution, atrasos, PDD per FIDC                              |
| C3      | Y                         | https://home.uqbar.com.br                                                   | FII operations and anuário                                       |
| C4      | ?                         | —                                                                           | search excerpt mentions FIP and debentures in scope; no detail   |
| C5      | Y                         | https://uqbar.com.br/plataforma-institucional/                              | operation pages, secondary market, rating history                |
| C6      | ?                         | —                                                                           |                                                                  |
| C7      | ?                         | —                                                                           |                                                                  |
| C8      | ?                         | —                                                                           | outside scope                                                    |
| C9      | P                         | https://uqbar.com.br/plataforma-institucional/                              | news and 100k docs; not company fatos relevantes as a feed       |
| C10     | ?                         | —                                                                           |                                                                  |
| C11     | ?                         | —                                                                           |                                                                  |
| C12     | ?                         | —                                                                           |                                                                  |
| C13–C16 | ?                         | —                                                                           | outside scope                                                    |
| C17     | P                         | https://uqbar.com.br/plataforma-institucional/                              | "mercado secundário" data per operation; source not stated       |
| C18–C20 | ?                         | —                                                                           | outside scope                                                    |
| C21     | ?                         | —                                                                           |                                                                  |
| C22     | Y                         | https://uqbar.com.br/plataforma-institucional/                              | "mais de 100 mil documentos organizados"                         |
| Q1      | Y                         | https://uqbar.com.br/quem-somos/                                            | data since 2003 (search excerpt); rankings since 2007            |
| Q2      | ?                         | —                                                                           |                                                                  |
| Q3      | ?                         | —                                                                           |                                                                  |
| Q4      | ?                         | —                                                                           |                                                                  |
| Q5      | ?                         | —                                                                           |                                                                  |
| A1      | Y                         | https://uqbar.com.br/plataforma-institucional/                              | saved filters plus CSV export                                    |
| A2      | Y                         | https://uqbar.com.br/plataforma-institucional/                              | league tables since 2007, CSV/PDF                                |
| A3      | P                         | https://home.uqbar.com.br                                                   | "rankings e comparações de desempenho"                           |
| A4      | P                         | https://home.uqbar.com.br/doadores-de-recursos/                             | "informações de risco de crédito", rating history                |
| A5      | ?                         | —                                                                           | nothing found                                                    |
| A6      | P                         | https://uqbar.com.br/plataforma-institucional/                              | "Radar pessoal" of indicators; not verified as push alerts       |
| A7      | P                         | https://home.uqbar.com.br/doadores-de-recursos/                             | "monitore o desempenho de fundos e certificados", custom reports |
| A8      | P                         | https://home.uqbar.com.br                                                   | institutions (2.6k) linked to operations; inference              |
| X1      | Y                         | https://www.uqbar.com.br/login                                              |                                                                  |
| X2      | ?                         | —                                                                           | CSV only seen                                                    |
| X3      | ?                         | —                                                                           | no API docs found (search)                                       |
| X4      | ?                         | —                                                                           |                                                                  |
| X5      | ?                         | —                                                                           |                                                                  |
| X6      | ?                         | —                                                                           |                                                                  |
| X7      | P                         | https://uqbar.com.br/plataforma-institucional/                              | CSV export of screens                                            |
| T1      | ?                         | —                                                                           |                                                                  |
| T2      | ?                         | —                                                                           |                                                                  |
| B1      | P                         | https://uqbar.com.br/artigo/os-lideres-em-pl-ranking-dos-maiores-fi-is/6239 | some free articles; data needs a subscription                    |
| B2      | ?                         | https://uqbar.com.br/precos-e-planos/                                       | not public; "Equipe" plan exists                                 |
| B3      | S2 (plus S4 for anuários) |                                                                             |                                                                  |
| O1      | manual (analyst-curated)  | https://uqbar.com.br/quem-somos/                                            |                                                                  |
| O2      | ?                         | —                                                                           |                                                                  |

### 1.2 FIDCs.com.br (fidcs.com.br)

- **Who:** an individual-run site. The footer has a "Sobre mim" link ([plataforma](https://fidcs.com.br/plataforma)).
- **What:** free per-fund pages for 4,000+ FIDCs built from CVM data. They show PL by quota class, subordination index, inadimplência, PDD, flows (captação, resgate, amortização), portfolio by segment/devedor/prazo, senior vs subordinated returns, investor data, and "Insights e análise gerados por IA". Other features: FIC-FIDC look-through ("explosão de ativos investidos"), industry aggregates (24-month PL and flows, top managers), a "Quem investe nos FIDCs" section, and an offerings radar under CVM Res. 160 covering CRI/CRA/debentures/FIDC/FII. Rankings cover PL, cotistas and **% vencido**, plus 10 ANBIMA-focus segments ([rankings](https://fidcs.com.br/rankings), [ofertas](https://fidcs.com.br/ofertas)).
- **Sources:** "Todos os dados apresentados são obtidos da CVM"; 60 months of history (WebFetch summary of /plataforma).
- **Pricing:** the free tier needs no signup. **Premium is R$ 600/yr billed monthly or R$ 500/yr billed annually** ("Equivale a R$ 41,67 por mês"; Stripe checkout; curl of [premium](https://fidcs.com.br/premium)). Premium adds the Excel export ("Demonstrativo CVM hierárquico, todo o histórico mensal e nove abas"), a custom dashboard, bulk PDF reports, full offering history and FIC-FIDC look-through.
- **Segment:** S2 (analysts, small allocators) and retail.
- **AI:** "Insights e análise gerados por IA" on fund pages (claim).
- **Differentiators:** very cheap Excel export of the full CVM informe; % vencido ranking; FoF look-through.
- **Weaknesses:** FIDC only; CVM informe only (no FNET documents); no alerts found; no API; no restatement handling; no named cedentes or sacados.

| ID     | value                                        | evidence URL                    | note                                                          |
| ------ | -------------------------------------------- | ------------------------------- | ------------------------------------------------------------- |
| C1     | ?                                            | —                               | "Renda Fixa" menu exists; not examined                        |
| C2     | Y                                            | https://fidcs.com.br/plataforma | PL, subordination, inadimplência, PDD, flows, segment         |
| C3     | ?                                            | —                               |                                                               |
| C4     | ?                                            | —                               |                                                               |
| C5     | P                                            | https://fidcs.com.br/ofertas    | CRI/CRA only as public offerings (Res.160)                    |
| C6     | ?                                            | —                               |                                                               |
| C7     | P                                            | https://fidcs.com.br/plataforma | FIC-FIDC look-through; "Quem investe nos FIDCs"               |
| C8–C21 | ?                                            | —                               | outside scope                                                 |
| C22    | ?                                            | —                               | none seen                                                     |
| Q1     | P                                            | https://fidcs.com.br/plataforma | 60 months                                                     |
| Q2     | ?                                            | —                               |                                                               |
| Q3     | P                                            | https://fidcs.com.br/plataforma | site-level "obtidos da CVM", not per number                   |
| Q4, Q5 | ?                                            | —                               |                                                               |
| A1     | P                                            | https://fidcs.com.br/plataforma | search by name/CNPJ; filters implied                          |
| A2     | Y                                            | https://fidcs.com.br/rankings   | PL, cotistas, % vencido, managers, admins, segment            |
| A3     | P                                            | https://fidcs.com.br/premium    | custom dashboard combining funds                              |
| A4     | P                                            | https://fidcs.com.br/plataforma | inadimplência, PDD, subordination                             |
| A5     | P                                            | https://fidcs.com.br/rankings   | "Maior Percentual Vencido" ranking is a crude anomaly surface |
| A6     | ?                                            | —                               | not mentioned on premium page                                 |
| A7     | P                                            | https://fidcs.com.br/premium    | "Monte sua sala de análise"                                   |
| A8     | P                                            | https://fidcs.com.br/plataforma | FoF → FIDC look-through; no cedente → company join            |
| X1     | Y                                            | https://fidcs.com.br/plataforma |                                                               |
| X2     | P                                            | https://fidcs.com.br/premium    | Excel file export, not an add-in                              |
| X3–X6  | ?                                            | —                               | apart from the fund-page "IA" insight claim (X6 P?)           |
| X7     | P                                            | https://fidcs.com.br/premium    | per-fund Excel with full history                              |
| T1     | P                                            | https://fidcs.com.br/plataforma | "Todos os dados... obtidos da CVM"                            |
| T2     | P                                            | https://fidcs.com.br/plataforma | "Indicador de dados 'em consolidação'"                        |
| B1     | Y                                            | https://fidcs.com.br/plataforma | "Consulta gratuita e sem cadastro"                            |
| B2     | R$500–600/yr                                 | https://fidcs.com.br/premium    |                                                               |
| B3     | S2 plus retail                               |                                 |                                                               |
| O1     | unknown (automated CVM ingest, by inference) |                                 |                                                               |
| O2     | ?                                            | —                               |                                                               |

### 1.3 Painel FIDC (painelfidc.com.br) — the closest S2 analogue to SILO plus Tomé

- **Who:** Painel FIDC Dados e Inteligência de Crédito LTDA ([sobre](https://www.painelfidc.com.br/sobre)). Founders are not disclosed.
- **What (claimed):** reconciled coverage of 5,738 FIDC/FIC-FIDC (4,208 operating as of Aug-2026) with monthly history since **Jan-2021** (77,628 fund-months). Per-fund modules cover identity, PL, portfolio, risk (PDD, aging, **subordination vs regulatory/contractual minimum**, concentration by cedente and sacado vs regulamento limit), documents and events. Also claimed:
  - "Minha Carteira" with look-through and overlap ("Mesmo cedente identificado em dois fundos da carteira")
  - a **Radar de Ofertas**
  - **Avisos** (alerts) on new FNET publications, PDD rising more than 0.5pp, rating changes and limit breaches
  - institutional PDF reports
  - Excel/CSV in and out
  - a private audit module with SHA-256 integrity
  - **PainelFIDC.IA**: document summaries/comparison and regulatory Q&A with citations, "declining to extrapolate beyond available sources" ([home](https://www.painelfidc.com.br/))

  The route map in the page source shows more product surface: `/painel-credito/monitor-pdd`, `/painel-credito/fidcs-x-bancos`, `/pdd-bancos`, `/exposicao-devedor`, `/nucleo-auditoria/investigacoes`, `/robo-auditoria`, `/renda-fixa`, `/crm-ofertas-fidc`, `/academia-fidc`. All of these are login-gated. What they do is **not verified**; reading them as forensic/audit tooling is inference.

- **Governance claims (strong, and very close to SILO's stance):**
  - "Campos sem dado validado na competência exibida são omitidos, nunca estimados" ([fidcs](https://www.painelfidc.com.br/fidcs))
  - "o que a fonte não informa é apresentado como ausente, nunca como zero" ([sobre](https://www.painelfidc.com.br/sobre))
  - "Glass Box": every indicator carries origin, competência and documentary evidence
  - "Informes, documentos, posições de carteira e eventos, com **controle de reapresentação**" and "Versões anteriores são preservadas. Atualizações e reapresentações são reprocessadas e verificadas" (curl of home)
  - Regulamento limits are shown "só... quando a cláusula está comprovada no documento, com a classe abrangida e a vigência identificadas" (home), i.e. **covenant/limit extraction from regulamentos with provenance**
- **Sources:** CVM cadastro (Res. 175), CVM informes, FNET/B3 (regulamentos, informes estruturados, DFs, **ratings**, events), ANBIMA (industry stats, manager ranking, private-credit asset data), and manager lâminas. "Toda a coleta é automatizada" ([sobre](https://www.painelfidc.com.br/sobre)).
- **Pricing:** not public. "A base completa da plataforma exige assinatura" (home JSON-LD). Sales are demo-led.
- **Segment:** S2: managers, administrators, lawyers/auditors, allocators ([para-alocadores](https://www.painelfidc.com.br/para-alocadores), [para-advogados-e-auditores](https://www.painelfidc.com.br/para-advogados-e-auditores)).
- **Differentiators:** document plus informe fusion, subordination-vs-minimum, restatement control, alerts and a citation-grade AI. It directly overlaps SILO's accountability stance and Tomé's radar.
- **Weaknesses:** FIDC only (no CRI/CRA vehicles, no listed companies, no B3 market data); history only from 2021; no public API or MCP found; closed and paid; much of the public UI is illustrative.

| ID     | value                                         | evidence URL                                  | note                                                                       |
| ------ | --------------------------------------------- | --------------------------------------------- | -------------------------------------------------------------------------- |
| C1     | ?                                             | —                                             | `/renda-fixa` route exists; unverified                                     |
| C2     | Y                                             | https://www.painelfidc.com.br/                | PL, PDD, aging, subordination, concentration                               |
| C3     | ?                                             | —                                             |                                                                            |
| C4     | ?                                             | —                                             |                                                                            |
| C5     | P                                             | https://www.painelfidc.com.br/                | CRI/CRA only as FIDC portfolio assets in look-through                      |
| C6     | ?                                             | —                                             |                                                                            |
| C7     | P                                             | https://www.painelfidc.com.br/                | look-through of FIDC holdings and CDA "posições públicas em FIDCs"         |
| C8–C21 | ?                                             | —                                             | outside scope; `/pdd-bancos` hints at bank data (unverified)               |
| C22    | Y                                             | https://www.painelfidc.com.br/sobre           | FNET regulamentos, lâminas, informes, atos e fatos, ratings                |
| Q1     | P                                             | https://www.painelfidc.com.br/                | since Jan-2021 only                                                        |
| Q2     | P (claimed)                                   | https://www.painelfidc.com.br/                | "controle de reapresentação... Versões anteriores são preservadas"         |
| Q3     | Y (claimed)                                   | https://www.painelfidc.com.br/sobre           | "Cada número... carrega a sua fonte e a sua competência"                   |
| Q4     | ?                                             | —                                             |                                                                            |
| Q5     | P (claimed)                                   | https://www.painelfidc.com.br/                | versioned monthly portfolios, "sem sobrescrita"                            |
| A1     | P (claimed)                                   | https://www.painelfidc.com.br/para-alocadores | "Filtre o universo de FIDCs por segmento, porte, estrutura e indicadores"  |
| A2     | P                                             | https://www.painelfidc.com.br/sobre           | manager rankings (ANBIMA-sourced)                                          |
| A3     | P (claimed)                                   | https://www.painelfidc.com.br/                | `/comparativo`, "mutual benchmarking"                                      |
| A4     | Y (claimed)                                   | https://www.painelfidc.com.br/                | PDD, aging, subordination vs minimum, concentration vs limit               |
| A5     | P (inferred)                                  | https://www.painelfidc.com.br/                | `/robo-auditoria`, `/nucleo-auditoria/investigacoes` routes; content gated |
| A6     | Y (claimed)                                   | https://www.painelfidc.com.br/                | Avisos: FNET doc, PDD > 0.5pp, rating change, limit breach                 |
| A7     | Y (claimed)                                   | https://www.painelfidc.com.br/                | Minha Carteira, versioned monthly book                                     |
| A8     | P (claimed)                                   | https://www.painelfidc.com.br/                | cedente and sacado overlap across funds; no company/ticker join seen       |
| X1     | Y                                             | https://www.painelfidc.com.br/fidcs           |                                                                            |
| X2     | P                                             | https://www.painelfidc.com.br/                | Excel/CSV import and export; no add-in                                     |
| X3     | ?                                             | —                                             | none found                                                                 |
| X4, X5 | ?                                             | —                                             |                                                                            |
| X6     | Y (claimed)                                   | https://www.painelfidc.com.br/                | PainelFIDC.IA with citations                                               |
| X7     | P                                             | https://www.painelfidc.com.br/                | exports; `/dataset-fidc` product (gated)                                   |
| T1     | Y                                             | https://www.painelfidc.com.br/fidcs           | "omitidos, nunca estimados"                                                |
| T2     | P                                             | https://www.painelfidc.com.br/                | competência on each number; "Com informe 12 de 12"                         |
| B1     | P                                             | https://www.painelfidc.com.br/fidcs           | free public index only                                                     |
| B2     | ?                                             | —                                             | demo-led, not public                                                       |
| B3     | S2                                            |                                               |                                                                            |
| O1     | automated ("sem dependência de envio manual") | https://www.painelfidc.com.br/sobre           |                                                                            |
| O2     | P (claimed)                                   | https://www.painelfidc.com.br/                | SHA-256 audit module, `/versoes` changelog page                            |

---

## 2. SHALLOW profiles

**Tradar (tradar.com.br/fidcs)**: per-FIDC pages with carteira, cedentes (header only), inadimplência, subordination (e.g. 33.24%), structure by tier, returns by class, PDD, admin fee, and B3 trading data when available. Source is CVM, current to 08/2026. Login is gated ("Entrar ou criar conta"). Notable: C2 Y, C13-style B3 quote join P ([vectro page](https://tradar.com.br/fidcs/vectro-capital-fidc)). It lacks named cedentes/sacados, aging, alerts and forensic screens, all of which SILO has (cedentes/sacados/aging).

**Vórtx (vortx.com.br)**: a trustee/agent. Its "Área do Investidor" covers Assembleias e Eventos, Fundos and Títulos de Dívida. Vórtx ONE (DCM: guarantees agent, calculation, assemblies, liens). A developer API exists at vortx.dev ([home](https://www.vortx.com.br/)), probably operational for clients (inference). Notable: C22 P (assembly notices and documents for the deals it trustees); X3 P (vortx.dev, not an analytics API). It does no cross-market analytics or screening.

**Oliveira Trust (oliveiratrust.com.br/investidor)**: an asset list (funds, debentures, CRI, CRA, NC, NP) with current PU. Detail pages carry Relatórios Anuais, Informes Mensais FIDC, documents, price history and Editais de Convocação (assembly notices). Partly login-gated. There is also an App OT Investidor ([ativos](https://www.oliveiratrust.com.br/investidor/ativos)). Notable: C5 P and C17 P (PU for its own deals), C22 P (trustee annual reports, assembly notices). Scope is its own book only; no cross-issuer analytics.

**Quantum (Axis) FIDC and CRI/CRA module (credit only)**: covers individual and comparative FIDC lâminas, custom reports, templates/filters, portfolio composition, export of official documents, **"quais fundos possuem em carteira determinados FIDCs"** (holders look-through) and new-series tracking ([8 ferramentas](https://quantumfinance.com.br/fidcs-8-ferramentas-poderosas-para-analisar-esses-ativos/)). For CRI/CRA: emission history, curve and secondary-market prices, securitisation terms and aditamentos, interest and amortisation payments ([CRI/CRA](https://quantumfinance.com.br/cris-e-cras-historico-de-emissoes-e-securitizadoras/)). Notable: C2 Y, C5 Y (payments), C7 Y, C17 Y, C22 P. Pricing is covered by Track 2.

**Clube FII: CR Data Solution (discovered)**: CRI/CRA/FII/Fiagro data "sobre emissões, negociações e fluxos de pagamento" collected from CVM and B3. It has an **Excel plugin** (Microsoft AppSource listing "Clube FII CRData") and an **API** (a `/cr-data-api-doc` page exists; 403 to fetch). Targets originators, managers, securitisers, private banking, distributors and **rating agencies** ([Capital Aberto](https://capitalaberto.com.br/mercados/clube-fii-funcionalidade-para-tratar-dados-de-cri-cra-e-fiagro/); search excerpts). Notable: C5 Y, X2 Y, X3 P (docs page seen in search, not fetched). This is the clearest **CRI/CRA-level data plus Excel/API** vendor.

**Clube FIDC (clubefidc.com.br, discovered)**: covers regulamentos, **atas, AGE**, offerings, fatos relevantes and comunicados, "organizados, pesquisáveis e históricos". It offers **email alerts on favourited funds** (new docs, assemblies, relevant events, issuances), senior vs subordinated comparison, downloadable lâminas, and **AI chat over regulamentos/atas/ofertas** ([home](https://www.clubefidc.com.br/)). Sources are CVM, ANBIMA and FundosNet; pricing is undisclosed. Notable: C22 Y, A6 Y, X6 Y. It directly covers "assembly minutes" and "alerts", both of which SILO lacks.

**Portal FIDC (portalfidc.com.br, discovered)**: run by Tech Intelligence (CNPJ 43.632.100/0001-43). A "community of data analysis and AI" for FIDCs with a 360° market panorama, benchmarking and rankings of administrators/managers/funds, aging, proprietary scores, and an offers radar. Registration is required ([home](https://portalfidc.com.br/)). Notable: A2 Y, proprietary scores (which SILO deliberately avoids), and an AI claim.

**ANBIMA Data (free)**: a FIDC dashboard launched 18-Dec-2025 covering industry PL, classes, accounts by investor segment, offering volume and managers/admins ([news](https://www.anbima.com.br/pt_br/noticias/anbima-data-lanca-dashboard-de-fidcs.htm)). CRI/CRA pages (since 2021, gradual coverage) show series characteristics, offering documents, **indicative rates and historical PU**, and an events agenda. ANBIMA also has a paid developer API for CRI/CRA prices ([news](https://www.anbima.com.br/pt_br/noticias/dados-de-cris-e-cras-sao-disponibilizados-no-anbima-data.htm), [developers](https://developers.anbima.com.br/en/documentacao/precos-indices/apis-de-precos/cri-cra/)). Notable: C5 Y, C17 Y, X3 Y (paid). This is the authoritative CRI/CRA pricing source SILO lacks.

**Rating agencies**:

- **Austin Rating** publishes a public, free table of FIDC ratings by class, with grade, outlook, action (Confirmação/Elevação/Rebaixamento) and date, plus per-fund rating history pages ([Ratings-FIDCs](https://www.austin.com.br/Ratings-FIDCs.html), [histórico](https://www.austin.com.br/Historico-Rating/3294/OS_FIDC)).
- **Moody's Local Brasil** publishes rating-action PDFs for FIDC series ([example PDF](https://moodyslocal.com.br/wp-content/uploads/2025/01/MLBR_PR_FIDC-Inclusao-Financeira_publicacao_1.25.pdf); site 403 to fetch).
- **Liberum** has FIDC rating reports (e.g. [Libra FIDC 2016](https://terconbr.com.br/wp-content/uploads/2015/07/FIDC-Libra-rating-Liberum.pdf)); its site gave no product detail.
- **Fitch / S&P**: I verified no Brazil structured-finance surveillance data product. A search excerpt says S&P and Moody's Local rating-action tables are JS-rendered and a community GitHub scraper exists. XP's "Guia de Rating" aggregates agency ratings for fixed income ([XP](https://conteudos.xpi.com.br/renda-fixa/relatorios/guia-de-rating/)).

Net: rating **actions are public, scattered and unstructured**. No one found offers a free structured, cross-agency FIDC/CRI/CRA rating-action feed. Painel FIDC claims rating-change alerts via FNET. Uqbar has per-operation rating history.

**Fidc News**: no data product found. Searches return FIDCs.com.br, Portal FIDC, Painel FIDC, Clube FIDC and tudosobrefidcs.com.br (a news site).

---

## 3. Gaps vs SILO

### S2 (structured credit): what others offer and SILO lacks

| Gap                                                                                                                          | Offered by                                                                                                                                              |
| ---------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Subordination vs regulamento minimum / concentration vs limit** (covenant extraction with clause provenance)               | Painel FIDC (claimed); Tomé (radar). The concept also appears in Painel FIDC editorial ("O mínimo relevante é o previsto no regulamento daquele fundo") |
| **Alerts / watchlist** (new FNET doc, assembly, PDD jump, rating change, limit breach)                                       | Painel FIDC (Avisos), Clube FIDC (email alerts), Uqbar (Radar, partial), Tomé                                                                           |
| **Document layer**: regulamentos, atas/AGE, fatos relevantes, trustee annual reports, rating reports, searchable and AI-chat | Clube FIDC, Painel FIDC, Uqbar (100k docs), Quantum, Oliveira Trust and Vórtx (own deals), Tomé                                                         |
| **Restatement (reapresentação) version history**                                                                             | Painel FIDC (claimed), Tomé                                                                                                                             |
| **CRI/CRA operation-level data**: PU, payment schedule and events, secondary-market prices, rating history                   | Uqbar, Quantum, CR Data (Clube FII), ANBIMA Data (free, partial), trustees (own deals)                                                                  |
| **Rating actions** (structured)                                                                                              | Uqbar (history per op), Painel FIDC (alerts, claimed), Austin (public table, own ratings only)                                                          |
| **Industry league tables / anuários** (structurers, law firms, auditors, trustees by volume)                                 | Uqbar (since 2007), FIDCs.com.br (managers/admins), Portal FIDC                                                                                         |
| **Offerings radar** (Res. 160 pipeline, CRI/CRA/FIDC)                                                                        | FIDCs.com.br, Painel FIDC, Quantum, Uqbar marketplace                                                                                                   |
| **Excel add-in / cheap Excel export**                                                                                        | CR Data (plugin), FIDCs.com.br (R$500/yr export)                                                                                                        |
| **Portfolio book / committee PDF reports**                                                                                   | Painel FIDC, FIDCs.com.br Premium, Quantum                                                                                                              |

### S1 (primary segment), from this track's vantage

1. **Alerts and watchlists**: every S2 paid product has or claims them; SILO has none.
2. **Document text plus AI Q&A with citations** (Painel FIDC.IA, Clube FIDC chat, Tomé).
3. **Secondary fixed-income pricing / PU for CRI, CRA and debentures** (ANBIMA, Quantum, Uqbar, CR Data).
4. **Rating-action history** as structured data (Uqbar, Painel FIDC claimed).
5. **Excel delivery** (CR Data plugin, FIDCs.com.br export).

---

## 4. What SILO has that none of these offer (white-space candidates)

| Candidate                                                                                                                    | Negative evidence                                                                                                                                                                                                                                                                                                                       |
| ---------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Free public REST API** (plus catalog, llms.txt, skill.md) over FIDC tabs **and** CRI/CRA **and** B3/BACEN/listed companies | No API docs found for Uqbar (search "Uqbar API dados CRI CRA"), FIDCs.com.br (premium page lists no API), Painel FIDC (home, sobre, route map show no `/api` or developer page). CR Data API is paid; ANBIMA API is paid and price-only. Search "API gratuita dados FIDC CVM informe mensal JSON REST" returned only raw CVM CSV files. |
| **Named cedente → listed company/ticker join** (fund → originator → `cia_*` financials / B3 tape)                            | Painel FIDC shows cedente overlap across funds but no company/ticker join; search "FIDC cedentes nomeados empresas listadas ticker" found nothing; no other platform links cedentes to listed-company statements.                                                                                                                       |
| **Rules-based forensic screens published openly** (zombie growth, evergreen aging, overdue CRI/CRA, delinquency drivers)     | Only proxies found: FIDCs.com.br "% vencido" ranking; Painel FIDC gated `/robo-auditoria` (content unknown); Portal FIDC proprietary scores. Search "FIDC triagem anomalias fraude sinais de alerta plataforma" returned only doc-fraud vendor blogs. Treat as **contested**: Painel FIDC may have it behind login.                     |
| **Cross-universe breadth in one free warehouse** (FIDC and CRI/CRA and FII and funds, plus B3 lending and flows plus macro)  | Every S2 vendor is scoped to one asset family: FIDC only (Painel FIDC, FIDCs.com.br, Clube FIDC, Portal FIDC, Tradar) or CRI/CRA/FII/FIDC without markets and listed companies (Uqbar, CR Data).                                                                                                                                        |
| **Full-depth history for free**                                                                                              | Painel FIDC starts 2021; FIDCs.com.br keeps 60 months; SILO's informe history is deeper (tranche data 2025+ only).                                                                                                                                                                                                                      |
| **Top-25 anonymised sacado concentration and SCR rating ladder as queryable data**                                           | Painel FIDC claims sacado concentration in its UI, but not as an API; no one else exposes these tabs.                                                                                                                                                                                                                                   |

Stance overlap: Painel FIDC's "omitidos, nunca estimados" / "ausente, nunca como zero" mirrors SILO's no-fabrication rule. SILO's differentiator is openness (free, API, auditable pipeline), not the stance itself.

---

## 5. Sources

- https://home.uqbar.com.br · https://uqbar.com.br/plataforma-institucional/ · https://home.uqbar.com.br/doadores-de-recursos/ · https://uqbar.com.br/quem-somos/ · https://uqbar.com.br/precos-e-planos/ (404) · https://anuarios2026.uqbar.com.br/ · https://vbso.com.br/en/vbso-securitizacao-ranking-uqbar/ · https://nextauditores.com.br/noticia/next-mais-uma-vez-lider-no-ranking-uqbar-em-numero-de-operacoes-em-fidc/
- https://fidcs.com.br/plataforma · https://fidcs.com.br/premium · https://fidcs.com.br/rankings · https://fidcs.com.br/ofertas
- https://www.painelfidc.com.br/ · https://www.painelfidc.com.br/sobre · https://www.painelfidc.com.br/fidcs · https://www.painelfidc.com.br/para-alocadores · https://www.painelfidc.com.br/para-advogados-e-auditores · https://www.painelfidc.com.br/monitorar-carteira-fidc · /robo-auditoria and /painel-credito (login-gated)
- https://tradar.com.br/fidcs/vectro-capital-fidc
- https://www.vortx.com.br/ · https://vortx.dev/docs/introducao (linked, not fetched)
- https://www.oliveiratrust.com.br/investidor/ativos
- https://quantumfinance.com.br/fidcs-8-ferramentas-poderosas-para-analisar-esses-ativos/ · https://quantumfinance.com.br/cris-e-cras-historico-de-emissoes-e-securitizadoras/
- https://capitalaberto.com.br/mercados/clube-fii-funcionalidade-para-tratar-dados-de-cri-cra-e-fiagro/ · https://www.clubefii.com.br/cr-data-solution (403) · https://www.clubefii.com.br/cr-data-api-doc (403) · https://marketplace.microsoft.com/en-us/product/office/wa200006710 (search excerpt)
- https://www.clubefidc.com.br/ · https://portalfidc.com.br/
- https://www.anbima.com.br/pt_br/noticias/anbima-data-lanca-dashboard-de-fidcs.htm · https://www.anbima.com.br/pt_br/noticias/dados-de-cris-e-cras-sao-disponibilizados-no-anbima-data.htm · https://developers.anbima.com.br/en/documentacao/precos-indices/apis-de-precos/cri-cra/
- https://www.austin.com.br/Ratings-FIDCs.html · https://www.austin.com.br/Historico-Rating/3294/OS_FIDC · https://moodyslocal.com.br/wp-content/uploads/2025/01/MLBR_PR_FIDC-Inclusao-Financeira_publicacao_1.25.pdf · https://www.liberumratings.com.br/ · https://conteudos.xpi.com.br/renda-fixa/relatorios/guia-de-rating/
- https://dados.cvm.gov.br/dataset/fidc-doc-inf_mensal
