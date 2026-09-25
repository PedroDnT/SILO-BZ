# Candidate data ranking

Reviewed 2026-09-23 against the repository's held/unserved inventory, the
parser and schema contracts, and publisher documentation. The ranking uses the
requested 0–5 component scale:

| Criterion | Weight | A high score means |
| --- | ---: | --- |
| Professional question value | 40% | It answers a concrete question analysts, allocators, or risk teams need |
| Difficulty obtaining/combining elsewhere | 25% | The joined, normalized history is hard to assemble independently, so SILO adds useful access |
| Source reliability and implementation feasibility | 20% | Official structured data, known schema/semantics, and a bounded path to a correct answer |
| Reuse | 15% | Multiple research questions or consumers benefit from it |

Weighted score = `0.40*value + 0.25*difficulty_elsewhere + 0.20*reliability_and_feasibility + 0.15*reuse`.
Eligibility is a separate gate: the source must already be held with a known
schema and semantics, or its public input contract must be verified before it
is called eligible. Conditional candidates remain visible below but are not
substituted into the top-three eligible set.

## Top three eligible additions

| Rank | Candidate | State | Value | Elsewhere difficulty | Reliability + feasibility | Reuse | Weighted / 5 |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | CVM CIA cash conversion and filing-version history (DFC-MD/DFC-MI + DRE) | Latest cash-flow lines served; version history/metadata gap | 4.8 | 4.5 | 4.5 | 4.8 | **4.67** |
| 2 | CVM FII property snapshot: area, reported vacancy, delinquency, and development progress | Dashboard-used; public schema/API/SDK gap | 4.5 | 4.7 | 4.4 | 4.3 | **4.50** |
| 3 | BCB Focus expectation revisions by indicator and target horizon | Dashboard-used; public schema/API/SDK gap | 4.6 | 3.8 | 4.7 | 4.8 | **4.45** |

### 1. CIA cash conversion

**Question:** Which listed non-financial companies repeatedly convert
operating earnings into cash, and does that pattern survive CVM filing
restatements?

`api.financials` already exposes latest-version DFC-MD/DFC-MI raw account lines.
The proposed addition is preserved filing-version history and filing metadata,
not first access to cash-flow data. `cia_account` also holds CVM ITR/DFP
statement rows. CVM publishes the
structured statements as yearly ITR/DFP ZIPs, with explicit fiscal start,
filing version, scope, and scale. `cd_cvm` joins `cia_company`; the published
FCA CNPJ↔ticker map supplies the valid company-to-ticker link for any price
comparison. It is not a name-based ticker guess.

Primary sources: [CVM ITR dataset](https://dados.cvm.gov.br/dataset/cia_aberta-doc-itr), [CVM DFP dataset](https://dados.cvm.gov.br/dataset/cia_aberta-doc-dfp), [CVM FCA dataset](https://dados.cvm.gov.br/dataset/cia_aberta-doc-fca).

### 2. FII property snapshots

**Question:** Which FII portfolios report the highest area-weighted vacancy
and delinquency, and what is the coverage of those property metrics?

`cvm_fii_imovel` already supports the dashboard's property explorer and
coverage views (`dashboard/pages/fii.md`); the gap is public schema/API/SDK
access. The verified CVM member contains
fund/class CNPJ, reporting date, filing version, area, vacancy and delinquency
percentages, rent and development fields. Aggregate at the published
fund/class CNPJ and reporting date; use the latest filing version for each
fund/date. Do not build a longitudinal property panel: CVM does not publish a
stable property identifier, and exact descriptive duplicates can represent
distinct units. The source map preserves full-row identity for ingestion.

Primary source: [CVM structured FII quarterly reports](https://dados.cvm.gov.br/dataset/fii-doc-inf_trimestral). The project parser and DDL document the exact property fields and row grain.

### 3. Focus expectation revisions

**Question:** How do published market medians for IPCA, Selic, and GDP change
by target year or month as new weekly Focus reports arrive?

`bacen_expectativas` already feeds the macro dashboard (`dashboard/pages/macro.md`);
the gap is public schema/API/SDK access. It holds market medians, mean,
standard deviation, survey date, endpoint, indicator, and forecast horizon.
Its natural key retains the horizon, and ingestion filters to the
standard 30-day statistic (and unsmoothed series where applicable), avoiding
collisions between unlike Focus products. Start with revisions only; scoring
forecast accuracy requires a separate, explicit mapping from forecast horizon
to realized BACEN series.

Primary sources: [BCB expectations and Focus products](https://www.bcb.gov.br/controleinflacao/expectativasmercado), [BCB Focus data-access page](https://www.bcb.gov.br/controleinflacao/expectativasmercado).

## Compared but not eligible yet

| Candidate | Score / 5 | Current state | Gate before selection |
| --- | ---: | --- | --- |
| FIDC tab V risk-retained maturity ladder + tab X.5 liquidity ladder | 4.32 | Public monthly/historical CVM ZIP members, not landed | Inspect a current and historical raw member; confirm field meanings, units, matching perimeter, and whether the figures support a defensible comparison. Do not infer liability maturity from asset liquidity. |
| B3 historic index-composition vintages | 4.35 | `b3_index_portfolio` already holds current composition and is used by analytics | Verify distinct historical archive availability, exact CIND parser layouts, effective dates, and join keys. The B3 preview example is not proof that a complete vintage series is available. |
| ANBIMA sovereign / credit curves | 4.06 | Public documentation and visible download/API products; developer-feed access/history requirements unclear | Confirm reusable no-cost access, historical coverage, and a documented source contract before treating it as open reproducible data. |

These scores are comparison aids. High value does not waive eligibility or
data-quality checks. No code in this vertical calls the OpenAI API.
