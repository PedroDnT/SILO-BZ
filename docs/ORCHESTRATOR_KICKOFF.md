# ORCHESTRATOR KICKOFF

Paste the block below to start the orchestrating Claude Code session. It carries the
project, the launch order, and the **documentation-upkeep + file-hygiene protocol** that
keeps the repo clean as parallel agents work.

---

## ▶ Kickoff message (copy from here)

> You are the **orchestrator** for `iliquid_nightly`, a Brazilian markets data platform
> (CVM + BACEN → Neon Postgres). Your job is to plan, dispatch, and integrate work across
> multiple sub-agents — not to write all the code yourself.
>
> **Before anything, read, in order:** `docs/planning/00_CONTEXT.md`,
> `docs/planning/02_ARCHITECTURE_AND_CONVENTIONS.md`, `docs/planning/04_WORKSTREAMS.md`,
> `docs/planning/05_AGENT_TASK_BRIEFS.md`. Treat `02` as binding — it's the shared
> contract that lets parallel branches merge cleanly.
>
> **Current state:** the canonical DB is the Neon project behind `POSTGRES_URL`
> (host `ep-cold-moon-...`, db `neondb`). The funds domain is partially loaded; its schema
> was just aligned and a re-run of the backfill is pending. The listed-companies domain is
> not started. A reference field-map implementation exists at `src/parsers/field_maps/`
> (FII) plus the engine at `src/parsers/mapping.py`.
>
> **Launch order (respect dependencies in `04`):**
> 1. Dispatch **W0** (`chore/reconcile-main`) and **W1** (`refactor/declarative-field-maps`) — these land first. W1 extends the FII reference maps to all datasets and modularizes the two collision hotspots (`cvm_pipeline.py`, `schema.sql`). Do not start file-touching workstreams that overlap these until they merge.
> 2. After W1 merges, trigger the funds backfill re-run to validate the refactor end-to-end.
> 3. Then fan out in parallel: **W2, W3, W5**. After W5: **W6, W7**. After W7: **W9**. Finally **W10**. (**W4, W8** are deferred.)
>
> **For each sub-agent**, hand it the matching brief from `05_AGENT_TASK_BRIEFS.md`
> verbatim (with the preamble), assign its branch, and require its Definition of Done
> (`02 §8`) before merge. Each agent commits only its own `src/parsers/field_maps/*.py`
> and `src/store/migrations/NN_*.sql` so branches don't conflict.
>
> **Hard rules (enforce on every agent):**
> - Never commit secrets; the DB is reached only via the `POSTGRES_URL` env var.
> - Never run destructive SQL (`DROP TABLE`/`TRUNCATE`/`DELETE`) against the shared DB.
> - Schema changes are idempotent migrations only; no ad-hoc `UPDATE` patches (they don't survive a reload).
> - Confirm `POSTGRES_URL`'s host before any backfill (wrong-DB writes have happened before).
>
> **Documentation & hygiene protocol (apply continuously — see below).** Keep the docs in
> `docs/planning/` in sync with reality and keep the tree clean as part of every PR's
> Definition of Done. Do not let docs drift or dead files accumulate.
>
> Start by producing a dispatch plan: list the branches you'll open now, the brief each
> agent gets, and the integration checks you'll run after each merge.

---

## Documentation & hygiene protocol (binding)

This is part of every PR's Definition of Done. The reason it exists: this project has
already been bitten by docs that described a different system than the code, by three
stray Neon projects, and by dead config files. Keep it from recurring.

### Keep docs in sync (on every merged PR)
- **`00_CONTEXT.md`** — update the "Verified current state" section when load state, fixed
  bugs, or known traps change. It must always describe the DB as it actually is.
- **`03_DATA_CATALOG.md`** — flip a dataset from ❌/⚠️ to ✅ the moment its ingest lands and is verified.
- **`04_WORKSTREAMS.md`** — mark each workstream's status (`todo` / `in-progress <branch>` / `done <commit>`); update the dependency graph if scope changes.
- **`field_maps/README.md`** — move datasets from ⬜ to ✅ as maps are ported.
- If a convention in `02` changes, change it in `02` first, then the code — `02` is the source of truth, not the implementation.

### Keep the tree clean (every PR)
- No dead files: when you replace something (e.g. `supabase_client.py` → `pg_client.py`, the Streamlit-vs-Evidence decision), **delete the loser**, don't leave both.
- No orphaned scratch: temp scripts, one-off SQL, `*.bak`, downloaded zips, `__pycache__`, large data files do not get committed (keep `.gitignore` current).
- No dangling config: a `cvm_config.py` entry without an ingest path + table is a bug (e.g. `fi-doc-balancete`) — wire it or remove it.
- One source of truth per concern: one DB client module, one presentation layer, one migrations directory.
- Migrations are append-only and idempotent; never edit a merged migration — add a new one.

### Lightweight changelog
- Maintain `docs/planning/CHANGELOG.md`: one line per merged workstream — date, branch, what changed, any new manual step. This is the audit trail that replaces "I think a previous run did X."

### Integration check after each merge (orchestrator runs)
1. `python scripts/apply_schema.py` against the canonical DB (idempotent — safe).
2. Run a targeted backfill slice for the affected dataset.
3. Confirm `cvm_ingest_log` shows `ok`, re-run is idempotent (counts unchanged), and null rates are explained.
4. Update `00`, `03`, `04`, and `CHANGELOG.md` accordingly. Only then is the workstream `done`.
