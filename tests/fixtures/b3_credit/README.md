# ConsolidatedRecords parser fixture

`consolidated_records.csv` is **synthetic**, not a downloaded market observation.
Its labels and grouping follow B3's Negociação Consolidada glossary of
15/12/2025 (URL in the fixture). It deliberately repeats one test code across
settlement dates and intra/extragroup rows, and includes NULLs and another asset
type. TEST/NULL codes and prices are test-only, with no economic interpretation.

After earlier timeouts, real one-day exports for 2026-10-06 and 2025-12-11 were
retrieved on 2026-10-07 (UTC-3) and passed the parser with zero dropped rows.
The full exports remain in ignored `.context/`; no real market rows are committed.
`test_observed_b3_header_order_and_case_with_synthetic_values` uses the exact
observed header with synthetic values. Counts, hashes and remaining coverage
limits are recorded in the capture contract. Daily enablement awaits rollout
and representative storage/continuity checks.
