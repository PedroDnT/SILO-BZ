# 0006. Schema apply: a migration ledger with content hashes instead of replaying every file each run

Date: 2026-10-17. Status: Proposed (awaiting the owner; part of #865, issue #872). Nothing below
is built. The implementation (SQL, action, workflows, tests) is a separate PR after acceptance.

## Context

The composite action `.github/actions/apply-schema` runs `src/store/schema.sql` and then every file in
`src/store/migrations/` (78 files today) through `psql` on each run of `daily_ingest`, `watchdog`
(twice), `rj_collect`, `backfill`, `market_backfill` and `test.yml`. Nothing records what was already
applied. Reading the repo:

- **It is safe only because every file is written to be replayed.** Each uses `IF NOT EXISTS`,
  `DROP ... IF EXISTS` or a `DO` block with a catalog check. `scripts/guard_noop_ddl.py` exists only
  to make the replay safe against live readers: it wraps a no-op `ADD COLUMN IF NOT EXISTS` in a
  catalog probe, adds `WITH NO DATA` to `CREATE MATERIALIZED VIEW`, and keeps a matching unique index
  instead of dropping and building it. `lock_timeout=15s` with three retries (the action) bounds the
  rest.
- **The cost and the failures come from replaying, not from the new change.** Measured by the issue:
  up to 14 min 25 s (run 33547870143). The action's own comments and the guard's docstring date the
  failures: 2026-08-26 (`ADD COLUMN` hung 4 min 20 s behind two dashboard queries), 2026-08-27
  (`lock_timeout` three times on a no-op `ADD COLUMN`), 2026-08-28 (`pg_type` contention on a
  `CREATE MATERIALIZED VIEW`), 2026-08-31 (`column "tp_fundo" does not exist`, retried as if it were
  a lock) and 2026-10-07 (run 37579395989, a `DROP` before ingest). In every one the statement that
  failed was unchanged and already applied. Whether any of those days also carried a new migration is
  not in the repo.
- **The action prints no per-file durations**, so the 14 min is not split between lock waits, real
  DDL and the `guard` round trips. That split decides how much Option B saves (below).
- **The files do change, but rarely.** Since 2026-08-01: 7 commits touch `schema.sql` and 6 touch
  `migrations/`. In the 491 commits this clone holds (a shallow history) no migration was ever
  modified after it was added; the rule is held.
- **Eight migrations carry `UPDATE`, `DELETE` or `INSERT`** (13, 16, 33, 34, 43, 49, 52, 72), and
  `schema.sql` refreshes `mv_b3_isin_subtype` and `mv_b3_monthly_activity` if unpopulated. Replaying
  them is harmless today because each is guarded; applying them once is what a ledger does anyway.
- `test.yml` applies the same action to an empty database and compares the result with `schema.sql`
  alone, so the replay path is tested on every pull request.

## Options

**A. A `schema_migrations` table keyed by file, with a SHA-256 of the content.** A run applies a file
only when it has no row; after it succeeds the run writes `(file, sha256, applied_at, duration_ms)`.
`schema.sql` stays the snapshot for a fresh database (an empty ledger replays everything, as now).

- For: the daily run applies zero files on almost every day, takes no exclusive lock, and cannot fail
  on a statement it did not change. A new migration costs seconds. The five dated failures need a
  lock or a stale statement on an _already applied_ file, which a ledger never re-runs. The table
  also gives a per-file duration, the missing baseline.
- For: it turns "never edit historical migrations" from a convention into a check (below).
- Against: a ledger is state. A row with a wrong hash, or a database restored from a backup taken
  before the last migration, makes the ledger lie; the replay never could. A hand-dropped index or
  column is no longer repaired every night. Two workflows applying at once can both see a file
  missing (the files are idempotent, so the second apply is harmless and the insert is
  `ON CONFLICT DO NOTHING`).

**B. Keep the replay; skip it when nothing under `src/store/` changed since the last green apply.**
The workflow compares `git diff --name-only <last green sha> HEAD -- src/store/`.

- For: no new table, no change to any SQL file or to the rule.
- Against: the "last green sha" has to live somewhere. In the database it is a one-row ledger; in
  Actions (a variable, a cache) it is outside the system it describes, per workflow, and wrong after
  a restore. The comparison needs history (`fetch-depth`) in five workflows, and a manual
  `workflow_dispatch` from an older ref must not skip. The skip is all or nothing: any one-line edit
  to `schema.sql` or any new migration replays all 78 files, with the 14 min and every failure
  above, on that day. It saves the common day and none of the risky one, and it keeps
  `guard_noop_ddl.py` as the only safety on the day that matters.

**C. Do nothing.** The replay is simple and drift-repairing, and `test.yml` tests exactly the
production path. The cost is 14 min on the critical path of every ingest and a recurring class of
failures before ingest starts (the `DROP` of 2026-10-07 is six weeks after the guard of 2026-08-26).

## Recommendation

Adopt **A**, in two steps.

1. **Baseline first.** Print each file's duration in the action (no behaviour change) and read
   several daily runs. If lock waits and the guard dominate, A removes most of the 14 min; if a few
   files dominate, say so before building. This is the same step ADR 0005 asks for the analytical
   files (#871).
2. **Implement A**, with these rules:
   - **Bootstrap without guessing.** The table is created by the action's first `psql` call
     (`CREATE TABLE IF NOT EXISTS`, also in `schema.sql` and a new `migrations/79_*.sql`, with RLS on
     like the recent tables). An empty ledger replays every file and records each after it succeeds.
     Nothing is ever recorded as applied without having run, so production needs no "assume
     applied" baseline, and a fresh database and `test.yml` still take the full path.
   - **`schema.sql` is re-applied when its hash changes**, as it is edited alongside new migrations
     and is the one file meant to change. Every migration is applied once.
   - **A changed applied migration fails the run**, naming the file and both hashes. This is the
     rule "never edit historical migrations" made mechanical: the fix is a new migration, not an
     edit. A deliberate, reviewed edit (a comment typo also changes the hash) needs a
     `rebaseline` input on the dispatch that rewrites the stored hash and logs who did it; there is
     no silent path.
   - **A `force` input replays everything**, for drift repair and a restored database, and a weekly
     scheduled replay (watchdog) keeps the old repair behaviour at one day in seven. The closing
     `::regclass` assertion stays on every run.
   - **`guard_noop_ddl.py` stays.** A new file, a replay and the empty-ledger path all still run live
     DDL. Retiring it is not a goal of this change.
   - Write the row only after the file succeeded, inside the same session, and serialise the
     apply with `pg_advisory_lock` so two workflows do not interleave DDL.

## Relation to ADR 0005

[ADR 0005](https://github.com/PedroDnT/SILO-BZ/pull/973) (Proposed, #873) uses the same device for
`src/store/analytical/`: a ledger of file name and content hash, written after success, empty means
replay. The two agree and should share one table and one hashing helper, built by whichever lands
first, with a `kind` column (`schema`, `migration`, `analytical`). They differ in what a changed hash
means, and that stays per kind: an applied **migration** that changed is an error (append-only); an
**analytical** file that changed is re-created together with every later file (it is a re-creatable
definition). If both are accepted, the name `schema_migrations` from this issue is a poor fit for
analytical rows; the owner may prefer `schema_ledger`. This ADR does not decide that and does not
edit 0005.

## Consequences if accepted

- The rule "never edit historical migrations" gets a check; the cost is one `rebaseline` for a
  legitimate edit.
- Ordinary runs stop paying the replay: the DDL step drops from up to 14 min to the ledger
  comparison plus any new file, and the lock failures listed above cannot recur on applied files.
- A hand-dropped object is no longer repaired nightly; `force` and the weekly replay are the repair,
  and an object missing between replays now fails a query, not the apply. The `::regclass` assertion
  catches only the tables it names.
- The ledger is the first part of the schema that records _when_ a change reached the database, which
  `cvm_ingest_log` does not.
- Reversal is cheap: dropping `schema_migrations` returns every run to the full replay.
- `docs/reference/DATABASE_MAINTENANCE.md` and the comments in the action are rewritten in the
  implementation PR; this one changes docs only.
