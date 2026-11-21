# The shape of the system: 4 infra, 4 products

Moved from the root `AGENTS.md` (#1186), which points here. The structure
itself, with the boundaries, is `docs/architecture/SYSTEM.md`.

Reach for this before reporting a problem — it decides whose problem it is, and
symptoms routinely surface one layer away from their cause.

**Infrastructure** (four, and only four):

|                    | Runs                                                              | Fails as                                        |
| ------------------ | ----------------------------------------------------------------- | ----------------------------------------------- |
| **GitHub Actions** | ingestion + parse (`run_daily`, `run_backfill`, health, watchdog) | a red run, a slice in `cvm_ingest_log`          |
| **Supabase**       | the Postgres store                                                | disk pressure, a failing query, a missing grant |
| **Vercel**         | hosting for `dashboard/` only; `webapp/` is not deployed          | a build error, a stale or mis-pointed domain    |
| **Cloudflare**     | the portfolio-diagnosis demo: a Worker, the engine Container, private R2 for traces, an LLM provider (`deploy/cloudflare/`) | a Worker error, a Container timeout, a missing secret, an LLM refusal |

**Products** (what anyone actually consumes):

|                     | Is                      | Contract                                         |
| ------------------- | ----------------------- | ------------------------------------------------ |
| **the API**         | schema `api` + `serve/` | `docs/reference/API.md`, `api.catalog()`, `api.coverage()` |
| **the dashboard**   | the Evidence sites      | parquet built at deploy time                     |
| **the stored data** | the warehouse itself    | the integrity rules in the root `AGENTS.md`      |
| **the diagnosis**   | `src/portfolio/` (statement readers, engine, report, investigator) behind the Cloudflare Worker | `docs/reference/portfolio/`, ADR 0001 (stateless), ADR 0003 (traces in R2) |

Two consequences worth stating, both learned the expensive way:

1. **Diagnose at the right layer.** A dashboard showing no data has at least
   four possible causes across three layers — the data never landed (GitHub),
   the analytical view is stale or wrong (Supabase), the build read a fine
   database but the domain serves an older deployment (Vercel), or the page
   is guarding correctly against a source that is genuinely empty. Row counts
   in a build log and pixels on the public URL are different observations;
   on 2026-09-16 they disagreed, and only the second was true for users.
2. **Do not confuse OUR health with the SOURCE's.** `landed_at` says the
   pipeline ran and succeeded — that is ours to fix. `complete_through` says
   how much CVM has published — that is Brazil's filing calendar, not an
   outage. Gating red/green on the second is how DB Health taught itself to
   cry wolf.
