# Decisions

These are decisions the repository already records. Each row links to its
source. A new decision that is hard to reverse gets its own file in
[`docs/adr/`](../adr/).

| Decision                                                                   | Why                                                                     | Source                                                              |
| -------------------------------------------------------------------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------- |
| A failed fetch raises; nothing is fabricated                                | Fake data corrupts every downstream metric (`b3_calc_api` was deleted) | [CLAUDE.md](../../CLAUDE.md), integrity rules                       |
| Upsert on a named natural key; migrations are append-only                  | Every run can be repeated safely                                        | [CLAUDE.md](../../CLAUDE.md)                                        |
| No ingest HTTP API, no Docker or Alembic, no fake quote API                 | Ingest is scheduled jobs; Supabase is the only state                    | [README](../../README.md#whats-intentionally-not-here)              |
| Schema `api` is the only client surface; PostgREST never exposes `public`  | One contract; landing tables can change                                 | [API](../API.md#layers)                                             |
| Above 1,000 rows, refuse (22023); never truncate                            | A silent cut reads as complete data                                     | `api.assert_row_cap`, [CLAUDE.md](../../CLAUDE.md)                  |
| Gate health on `landed_at`, not `complete_through`                         | The source's calendar is not our outage                                 | [CLAUDE.md](../../CLAUDE.md)                                        |
| FII filings keep every version                                             | Restatements sit beside originals; read `*_latest` views                | migration 43                                                        |
| No backfill for the B3 BDI group                                           | B3 keeps about 21 business days; a start year would promise the impossible | `B3Ingestor.backfill` docstring                                  |
| Every green scheduled run rebuilds the dashboard                           | The snapshot is never more than a day behind (2026-09-14)               | `daily_ingest.yml`                                                  |
| FNET and market steps run after publishing                                 | Slow foreign hosts must not block the analytical apply or the deploy    | `daily_ingest.yml` (2026-09-25)                                     |
| Portfolio analysis stores no user portfolios                               | Stateless by design                                                     | [ADR 0001](../adr/0001-stateless-portfolio-analysis.md)             |
| Times are shown in UTC-3                                                   | The owner reads Brasília time; stored values are unchanged              | [CLAUDE.md](../../CLAUDE.md)                                        |
