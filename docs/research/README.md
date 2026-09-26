# Professional research vertical

This package ranks research additions, specifies questions and data checks, and
provides three reproducible cross-dataset demonstrations. It does not imply
that every candidate is served or that any finding is investment advice.

## Candidate ranking

Candidates are scored 0–5 on professional question value (40%), difficulty of
obtaining/combining elsewhere (25%), source reliability and implementation
feasibility (20%), and reuse (15%). Eligibility requires an existing SILO data
contract or a verified public source contract; candidates without that evidence
stay conditional.

See [candidate ranking](candidate-ranking.md), [question specifications](question-specifications.md), [benchmark specifications](benchmark-specifications.md), and the [API surface matrix](api-surface-matrix.md).

## Flagship demonstrations

Run from the repository root with `python research_examples/<script>.py`:

1. `01_cia_chart_mapping.py` combines a documented CVM financial-statement
   account census with company/chart context and quantifies the risk of using
   one account code as a universal net-income mapping.
2. `02_fii_property_concentration.py` joins a CVM FII fund report to its
   property report and calculates vacancy area and reported revenue reliance.
3. `03_focus_forecast_error.py` compares a dated BCB Focus median with IBGE's
   realized annual IPCA and calculates the forecast error.

The demonstrations use published evidence transcribed in code and calculate
their stated arithmetic locally. The CIA count is a project-documented census,
not a newly downloaded row-level extract. The FII and Focus results are single
published snapshots, not time-series benchmarks. Each script prints its source
and limitations. Direct CVM archive download was unavailable in this
environment, so no archive-ingestion benchmark is claimed as passed. The
separate live-agent evaluator is documented in
[research_examples/README.md](../../research_examples/README.md); its saved
[baseline grade](agent-evaluation-grade.md) and [latest reconciliation](agent-reconciliation-results.md)
keep API availability and answer quality separate.
