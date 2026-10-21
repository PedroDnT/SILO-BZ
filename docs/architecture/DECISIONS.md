# Decisions

These are decisions the repository already records. Each row links to its
source. A new decision that is hard to reverse gets its own file in
[`docs/adr/`](../adr/).

| Decision                                                                                  | Why                                                                                                                      | Source                                                  |
| ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------- |
| A failed fetch raises; nothing is fabricated | Fake data corrupts every downstream metric (`b3_calc_api` was deleted) | [AGENTS.md](../../AGENTS.md), integrity rules |
| Upsert on a named natural key; migrations are append-only | Every run can be repeated safely | [AGENTS.md](../../AGENTS.md) |
| No ingest HTTP API, no Docker or Alembic, no fake quote API | Scheduled jobs; Supabase is the only state | [README](../../README.md#what-is-intentionally-not-here) |
| Schema `api` is the only client surface; PostgREST never exposes `public` | One contract; landing tables can change | [API](../reference/API.md#layers) |
| Above 1,000 rows, refuse (22023); never truncate | A silent cut reads as complete data | `api.assert_row_cap`, [AGENTS.md](../../AGENTS.md) |
| Gate health on `landed_at`, not `complete_through` | The source's calendar is not our outage | [AGENTS.md](../../AGENTS.md) |
| FII filings keep every version | Restatements sit beside originals; read `*_latest` views | migration 43 |
| No backfill for the B3 BDI group | B3 keeps about 21 business days; a start year would promise the impossible | `B3Ingestor.backfill` docstring |
| Every Monday scheduled run whose analytical apply succeeds rebuilds the dashboard | The data step is about 20 min of the build, so the snapshot is at most a week old (2026-10-18); a red source does not block it | `daily_ingest.yml` (#473, #976) |
| FNET, market and B3 event steps run after publishing | Slow foreign hosts must not block the apply or deploy | `daily_ingest.yml` (2026-09-25, 2026-09-30) |
| A ticker is active only if it trades; history follows the company across an ISIN change only by strict rules | `is_active` reflects trading, not a stale register | [ADR 0002](../adr/0002-ticker-activity-and-lineage.md) |
| Portfolio analysis stores no user portfolios | Stateless by design | [ADR 0001](../adr/0001-stateless-portfolio-analysis.md) |
| Diagnosis traces (masked) go to private R2; the upload is never stored | Real runs improve the agents; Supabase holds no portfolios | [ADR 0003](../adr/0003-diagnosis-traces-in-r2.md) |
| Debenture rates from REUNE (stored, never served raw), volume from B3; no cash-flow engine | Observed trades beat model marks; B3 keeps 18 months | [ADR 0004](../adr/0004-debenture-market-data-sources.md) |
| ANBIMA debenture terms, agenda and 5-session indicative rates come from data.anbima.com.br's public pages through headless Chromium; stored, never served | REUNE publishes indicative, not traded, rates; full history is the paid ANBIMA Feed; the pages need a browser; the owner's permission covers collection and storage | [#1006](https://github.com/PedroDnT/SILO-BZ/issues/1006) |
| Investigator facts are quotes from public documents, tiered A/B/C; no number from a model | Every fact is checkable; Exa only after Fundos.NET and RAD; cached in R2 | [#605](https://github.com/PedroDnT/SILO-BZ/issues/605) |
| Proposed: refresh analytical matviews `CONCURRENTLY`; re-create a file only when its hash changes | Ends the daily lock and rebuild; baseline timings first | [ADR 0005](../adr/0005-analytical-refresh-concurrently-with-hash-ledger.md) |
| Proposed: a `schema_migrations` ledger (file, hash); apply only new files, fail on a changed applied one | Ends the 14-minute daily replay and its lock failures; reversible | [ADR 0006](../adr/0006-migration-ledger-instead-of-replay.md) |
| Times are shown in UTC-3 | The owner reads Brasília time; storage unchanged | [AGENTS.md](../../AGENTS.md) |
