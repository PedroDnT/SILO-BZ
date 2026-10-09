# Credit observation serving: rollout acceptance

Implementation approved on 09/10/2026 (UTC-3), tracked in #789–#794.
Production analytical apply and remote tool deployment require specific owner
approval. Recurring ingestion remains disabled after the storage stop.

## Reviewed rollout sequence

1. Confirm the serving PR merged, its commit and green Python/SQL CI.
2. After specific production approval, use the existing analytical-only workflow
   (`daily_ingest.yml`, `mode=analytics-only`, `rebuild_dashboard=false`).
   Review its existing schema bootstrap before dispatch; it is a production write.
   Do not dispatch daily/backfill or enable recurring capture.
3. Verify live `api.catalog()` version and `api.coverage()` credit entry through
   bounded read-only calls. Call `credit_market_history` for one stored code and
   one trade date, with a timezone-aware cutoff after its audit completion.
4. After specific remote deployment approval, dispatch `deploy_mcp.yml`. Its
   live tools/list verification must include `credit_market_history`; a merge
   alone is insufficient.
5. Compare the same bounded sample through SQL/PostgREST, local HTTP adapter,
   SDK RPC and remote tool. Record commit/run IDs, parameters, group keys, nine
   metrics/units, NULLs, capture/hash and observation/audit timestamps.

## Acceptance boundaries

Local rollback fixtures exercise selection-before-filtering, newer removals,
incomplete captures, audit delays, empty windows, invalid input, the 1,000-group
refusal and serving-role execution without landing-table SELECT. They are
synthetic test data, not production observations. CI repeats executed SQL.

Deployment acceptance requires matching real returned groups and provenance,
not just a successful workflow or a published tool name. Use one-date reads
first and record query latency; benchmark a longer bounded window only if
needed. Do not add an index or materialized dataset without measured need.

Keep merged, analytical-applied, HTTP-local and remote-deployed evidence
separate. Preserve retained captures; no new ingestion, schema design, mapping,
economic return calculation or scientific PIT acceptance is included.

## Current state

Local implementation and regression evidence are recorded in the PR.
Production apply, live sample parity and remote deployment are pending.
