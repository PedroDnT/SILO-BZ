# 01 — PRD: Brazilian Markets Data Platform

## Vision
A single, queryable warehouse + API covering the public Brazilian capital markets,
sourced from CVM open data and BACEN, with a clean analytical layer and a web/API
surface. Two domains share one warehouse and one set of conventions but surface
separately to users.

## Why
CVM publishes ~54 open datasets across funds and listed companies, but they are
fragmented (yearly zips, latin-1 CSVs, inconsistent schemas, account-line formats).
The value is in a normalized, joinable, typed warehouse where a fund's portfolio can
be linked to the listed company that issued the asset, and where fund NAVs can be
benchmarked against BACEN macro series.

## Domains & primary entities
| Domain | Entities | Key | Grain |
|---|---|---|---|
| **A. Funds & Securities** | FI, FIDC, FII, FIP, FIAGRO, SECURIT (CRA/CRI/OTS) | `cnpj` (14) | daily (FI) / monthly / periodic |
| **B. Listed Companies** | `cia_aberta` issuers | `cd_cvm` + `cnpj_cia` | quarterly (ITR) / annual (DFP/FRE) / event (IPE) |
| **(shared) Macro** | BACEN SGS, PTAX, Expectativas | series/date | daily/monthly |

## Users & top use cases
1. **Fund analyst** — NAV trajectory, net flows, FIDC delinquency/subordination, FII yield, peer comparison; benchmark vs CDI/SELIC/IPCA.
2. **Credit/securitization analyst** — CRA/CRI series status, cash-flow schedules, tranche subordination over time.
3. **Equity/fundamentals analyst** — ITR/DFP financial-statement time series, margins, peer ranking; live material-facts feed.
4. **Cross-domain** — link a FIDC originator / CRA debtor to that listed company's financials (the platform's unique edge).

## API / webapp surfaces (kept separate)
- `/funds/*` — fund NAV, flows, composition, FIDC/FII metrics.
- `/securities/*` — CRA/CRI/OTS series, cash flows.
- `/companies/*` — financial statements, fundamentals time series, material-facts feed.
- `/macro/*` — BACEN series for benchmarking.
Served from the Neon Data API and/or the Flask/Next app on the canonical project.

## Success criteria
- **Coverage:** Domain A = all high-value fund datasets loaded 2019→present with <2% non-benign error rate. Domain B = ITR+DFP+IPE+cadastre loaded.
- **Legibility:** every meaningful CSV field is an explicit typed column; `raw` JSONB holds only not-yet-modeled residual fields (you never query JSON to understand a row).
- **Reproducibility:** a full reload from empty reproduces the exact same typed data with zero manual SQL.
- **Freshness:** daily ingest keeps FI/BACEN current; monthly/quarterly jobs keep the rest current.
- **Benchmarking unblocked:** BACEN SELIC/CDI/IPCA present and joined to fund returns.

## Non-goals (for now)
- B3/ANBIMA paid feeds, intraday equity prices, order books.
- The smaller CVM registries (auditors, autonomous agents, intermediaries) unless a use case demands them.
- A heavy BI tool; the serving layer is the Data API + a focused web app, not a third dashboard.

## Milestones
- **M0 — Stabilize:** repo reconciled, field-map refactor landed, funds domain reloads cleanly and deterministically. (W0, W1, then re-run)
- **M1 — Funds complete:** `fi-cad`→registry, precision audit, benchmarking live. (W2, W3)
- **M2 — Listed companies B0:** cadastre + IPE material-facts feed live on `/companies/*`. (W5, W6)
- **M3 — Fundamentals:** ITR+DFP financial statements warehouse + analytical views. (W7, W9)
- **M4 — Serving:** unified API surfaces + cross-domain linker; B2 enrichment as needed. (W10, W8)
