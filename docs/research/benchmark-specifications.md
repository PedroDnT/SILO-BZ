# Benchmark specifications

These checks separate reproducible arithmetic on cited published observations
from ingestion and longitudinal benchmarks that still require source archives.

| Candidate | Datasets | Check | Current evidence and status |
| --- | --- | --- | --- |
| CIA account-chart interpretation | CVM financial statement accounts + company/chart context; FCA mapping for ticker identity | Stratify account-code coverage by chart, verify labels, and reconcile account census denominators before using codes in cross-company metrics. | The repository's `docs/CIA_DATA_MAP.md` documents a 50,439-row statement census and 282 rows without code 3.11 (0.56%; 0.5591% by arithmetic). The code-only API returns NULL for these; the filed labels identify bank-B 3.09 as net income. This is a documented project census, not a fresh raw-file rerun. |
| FII property snapshot | CVM quarterly fund report + CVM property report | Match CNPJ/date/version, verify the fund/property row identities and units, calculate area × vacancy fraction, and retain source-reported revenue-share/delinquency values. | A test fixture reproduces a Via Parque Shopping row at 2025-03-31, 56,508.93 m², vacancy 0.124, delinquency 0.231726, revenue share 0.979772. Scripted calculations run; full-portfolio coverage and historical tracking are unverified. |
| Focus forecast error | BCB Focus vintage + IBGE realized IPCA | Match the report's 2025 IPCA median to the 2025 realized annual IPCA and calculate forecast minus actual in percentage points. | BCB 2024-12-06 median 4.59%; IBGE 2025 actual 4.26%; calculated error +0.33 pp. This is one vintage/target pair, not a multi-horizon accuracy benchmark. |

## Agent evaluation boundary

The runtime prompt for each case is only the professional question. It must
not name sources, tables, fields, join keys, dates or expected values. The agent
must discover available data using the SILO catalog and select bounded tools.
Store expected sources, joins, date rules and reference calculations only in
the evaluator's case specification. A future evaluation log should record
catalog discovery and selected tool calls, but no agent run or discovery log
was produced in this research pass.

## Ingestion gates still open

- CIA: download a fixed ITR/DFP source year, preserve version/scope/start date,
  reconcile account-level values, and verify derived quarters against annual
  DFP within rounding.
- FII: fetch official source archives and measure issuer/date coverage, latest
  version semantics, missingness and field stability across periods. CVM does
  not provide a stable property identifier, so no property-level time-series
  match should be claimed without additional validation.
- Focus: run a multi-year vintage-to-outcome panel with a stated target
  convention, source-date coverage and revision completeness checks.

Direct CVM archive download could not be completed in this environment; these
ingestion gates are specified, not passed. No production database, credential,
or OpenAI API was used.
