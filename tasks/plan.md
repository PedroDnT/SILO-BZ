# Implementation plan: debenture market serving

Prepared 09/10/2026, UTC-3. Implementation approved. Tasks tracked in GitHub parent [#789](https://github.com/PedroDnT/SILO-BZ/issues/789); no duplicate todo.md. Owner accepted implementation; production rollout remains separately gated.

## Existing evidence and boundaries

The store already has public.b3_credit_capture (full retained CSV, SHA-256, observed_at, census/status) and public.fact_credit_market (nine long metric rows per instrument/date/settlement/classification group). Migration 74 and tests/sql/b3_credit_behaviour.sql already protect snapshot removal semantics and private-table permissions. Current remote main has no credit-market serving function; serving precedent is 32_api_trade_consolidated.sql, which cannot be reused unchanged because it has a different grain and no capture vintages.

On 09/10 the first scheduled credit capture was reconciled against the retained original: 61,848 facts, 6,872 groups, nine metrics each, zero extra/missing records, numeric/provenance/hash differences or dropped rows. Its 02–08/10 window contains five verified cash sessions. This proves ingestion integrity, not total return or historic information availability.

A separate approved historical recovery is documented in #774 comments: 69 new captures over April/2025–June/2026, independent of our daily activation. They explain most records added during the +1.54 GB observation interval. Physical per-run allocation is not isolated. Recurring ingestion was disabled after the approved cumulative stop; the monitor is paused. This plan neither resets that budget nor restarts capture.

#774 is already claimed by another agent and concerns portfolio returns. Do not duplicate its code or overwrite its scope. Coupon/amortization source acceptance remains open there. Our first deliverable serves market observations; it does not invent cash flows, yield, adjusted returns or issuer-equity links. Review open PRs and #774 again before implementation.

## Approved read transformation

1. Select complete captures with successful, reconciled audits eligible at p_as_of. Both observed_at and audit finished_at must be no later than the cutoff. Default cutoff is current knowledge; historic backfills retain their actual late timestamps. This is SILO knowledge-time selection, not proof of source publication-time PIT.
2. Choose the latest eligible complete capture PER TRADE DATE across its requested/expected/delivered coverage, with deterministic tie-breaking, before filtering instrument/settlement/classification. A newer snapshot removing a bond must return absence, never revive the older record. Partial later captures are diagnostic and never hide an earlier complete capture.
3. Pivot exactly the nine stored metrics into one bounded observation row per (instrument_code, trade_date, settlement_date, trade_classification). No summing across classifications or liquidation dates; NULL stays unpublished. Last/reference prices are instrument-wide and repeated across groups, so never sum or volume-average their repeated copies. Reference price can be modeled and never substitutes for a traded price.
4. Carry units, ISIN, source-reported issuer name, capture ID/raw hash, observed_at and audit completion. No guessed CNPJ, fantasy name, stock ticker, rating, outstanding or yield. Machine-readable source identifiers remain intact; public prose need not name vendors.
5. Put selection/pivot in a read-only api SQL function, provisionally api.credit_market_history(p_code,p_from,p_to,p_as_of). Validate params, preserve existing unknown-code/empty-window conventions, raise 22023 above 1000 rows with assert_row_cap and ask callers to narrow the window. An optional classification filter must apply AFTER snapshot selection. No date-only pagination: several groups share one date. Defer a composite cursor until needed. No materialized table or new migration is justified initially; benchmark bounded reads before proposing an index.

This is a serving normalization, not economic repricing. Month-end selection, daily price aggregation, price-only return, coupon-adjusted total return and issuer mapping are separate contracts requiring explicit decisions. Do not call transaction volume outstanding/notional. No automatic portfolio or generic panel integration in this slice.

## Ordered task index
1. [Task 1](https://github.com/PedroDnT/SILO-BZ/issues/790)
2. [Task 2](https://github.com/PedroDnT/SILO-BZ/issues/791)
3. [Task 3](https://github.com/PedroDnT/SILO-BZ/issues/792)
4. [Task 4](https://github.com/PedroDnT/SILO-BZ/issues/793)
5. [Task 5](https://github.com/PedroDnT/SILO-BZ/issues/794)

Dependencies: 1 -> 2 -> 3 -> 4 -> 5. Each task has at most five likely files, three acceptance criteria and explicit verification in its issue. Reserve the next analytical SQL number and catalog version from current main at implementation time, not from this checkout.

## Checkpoints

- [x] Before implementation: owner accepts the observation-only contract, boundaries with #774 and task order.
- [ ] After tasks 1–2: SQL behavior tests run in ephemeral CI; later removal/partial capture, cutoff availability, NULL metrics, cap and serving-role security are executed, not merely compiled; catalog and OpenAPI agree.
- [ ] After tasks 3–4: offline adapter/SDK/MCP contracts agree, all offline tests and existing SQL CI pass; raw landing tables remain inaccessible to serving roles. Recheck regenerated outputs for unrelated main changes.
- [ ] After task 5: explicit production rollout approval; analytical function, HTTP, SDK and remote tool read the same bounded real sample; tools/list confirms deployment, stored private data stays private. Record distinct merged/applied/deployed states. No claim of full research/PIT completion.

## Estimates

Task 1: 1–2 hours. Tasks 2–4: 45–90 minutes each. Task 5: 60–90 minutes plus approved rollout. Total: roughly 4–8 focused hours, excluding CI queue and owner approval. Execute sequentially in one task by default; no parallel agent is required. Implementation approval received.

## Risks and mitigation

| Risk | Mitigation |
| --- | --- |
| Snapshot removal resurrected by ticker-first filtering | Select globally per trade date first; behavioral deletion fixture |
| Double counting settlements/classifications or repeated prices | Preserve full grain and instrument-wide price caveats |
| Backfill dates mistaken for historical knowledge | Actual observed/audit cutoff, explicit publication-time limitation |
| Coupon/amortization fall described as investment loss | No total-return calculation; separate #774 acceptance |
| Slow capture scans | Bounded code/date reads, explain/measure first; index only after evidence |
| Contract drift or exposed landing data | Catalog/OpenAPI/SDK/MCP checks and explicit privilege tests |
| Public source restriction vs provenance | Keep machine-readable identifiers, hashes and private evidence; neutral public prose |

## Owner decision / parking lot

Owner accepted the observation-only serving slice. No need to resolve coupon economics to serve observations honestly. Keep coupons, issuer-to-equity mapping, prospective research acceptance and recurring-ingestion restart in their existing scopes. Production SQL apply and remote tool deployment require specific approval under AGENTS.md. This planning approval is not that rollout authorization.

## Implementation status

09/10/2026: Task 1 SQL behavior scenarios passed against isolated local PostgreSQL; no production apply. Tasks 2–4 contracts and HTTP tests pass locally. Documentation and rollout checklist are complete. Full regression validation is in progress; CI and production acceptance remain distinct.
