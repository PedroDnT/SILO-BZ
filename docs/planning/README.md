# iliquid_nightly — Platform Planning & Orchestration Pack

This folder is the **single source of truth** for spinning up and orchestrating
multiple Claude Code agents on the `iliquid_nightly` project. Every agent should
read `00_CONTEXT.md` and `02_ARCHITECTURE_AND_CONVENTIONS.md` before touching code.

## Reading order
1. **`00_CONTEXT.md`** — what the project is, verified current state, how to connect, what's done/broken. Ground truth.
2. **`01_PRD.md`** — product vision, the two domains, API surfaces, success criteria, non-goals.
3. **`02_ARCHITECTURE_AND_CONVENTIONS.md`** — the shared contracts ALL agents must follow (storage conventions, field-map standard, collision-avoidance rules). **This is what keeps parallel work from colliding.**
4. **`03_DATA_CATALOG.md`** — CVM dataset inventory (covered vs missing) + real CSV shapes for both domains.
5. **`04_WORKSTREAMS.md`** — the dependency graph and discrete, parallelizable branches.
6. **`05_AGENT_TASK_BRIEFS.md`** — copy-paste, self-contained briefs to hand each sub-agent.

## Orchestration model (summary)
- **One branch per workstream**, off `main`. Branch names are specified in `04`.
- **Two collision hotspots:** `src/pipeline/cvm_pipeline.py` (1,550 lines) and
  `src/store/schema.sql`. The first refactor task (W1) **modularizes parsing into
  per-dataset modules** and **splits schema migrations into per-domain files** so
  that, afterward, agents work in disjoint files and can run truly in parallel.
- **Sequencing rule:** W0 (repo reconciliation) and W1 (field-map refactor +
  modularization) land FIRST. They unblock everything else and remove the shared-file
  contention. After that, Domain-A completion, Domain-B (listed companies), and the
  analytical/serving work proceed in parallel.
- **Definition of done** for any ingestion task (non-negotiable, see `02`):
  deterministic reload (no manual SQL patches), typed columns populated via the
  declarative map, idempotent upsert verified, null-rate check passed, `apply_schema`
  migration committed.

## Hard rules for every agent
- Never commit secrets. The DB is reached via the `POSTGRES_URL` env var / GH secret only.
- Never write destructive SQL (`DROP TABLE`, `TRUNCATE`, `DELETE`) against the shared DB.
- Schema changes go in idempotent migrations (`CREATE … IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`), never as ad-hoc one-off SQL that won't survive a reload.
- The canonical database is the Neon project behind `POSTGRES_URL` (see `00`). Confirm the host before any backfill.
