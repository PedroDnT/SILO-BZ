# 0005. Analytical layer: refresh matviews concurrently, re-create a file only when its hash changes

Date: 2026-10-17. Status: Proposed (awaiting the owner; part of #865, issue #873). Nothing below
is built. Accepting it changes the rule "the re-create is the daily refresh" in
`docs/reference/DATABASE_MAINTENANCE.md` section 7, in the implementation PR.

## Context

`scripts/apply_analytical.sh` runs every `src/store/analytical/NN_*.sql` file (36 today) on each
daily run, changed or not. Reading the files:

- Six matviews are dropped with `CASCADE` and created again (`dim_fund`, `fact_fund_monthly`,
  `fact_security_monthly`, `mv_savings_flow_monthly`, `mv_b3_adtv_21`, `mv_research_universe`);
  `mv_period_completeness`, `mv_fund_holdings_monthly` and `mv_fund_name_history` are dropped
  without it. `mv_metric_coverage` is created in `04` and goes with `fact_fund_monthly`.
- `DROP MATERIALIZED VIEW` takes `AccessExclusiveLock`. API readers and dashboard builds wait for
  the whole `CREATE`. The issue states about 28 min for the apply; no per-file timing is recorded
  yet (the timing ticket, #871, added the summary to the script).
- A pooler drop mid-`CREATE` left the backend holding that lock and failed four files in a row
  (#207, the comment in `04_fact_fund_monthly.sql`; the keepalives in the script are its patch).
- Only `22_b3_tape_matviews.sql` refreshes with `CONCURRENTLY`. `08_cron_schedules.sql` lists
  `CONCURRENTLY` refreshes for most of the others but never runs: `pg_cron` is absent.
- Unique indexes, which `CONCURRENTLY` needs, exist on `dim_fund`, `fact_fund_monthly`,
  `fact_security_monthly`, `mv_period_completeness`, `mv_metric_coverage`, `mv_b3_adtv_21`,
  `mv_research_universe` and `mv_fund_name_history`. They do **not** exist on
  `mv_savings_flow_monthly` (no index in `18`) or `mv_fund_holdings_monthly` (a non-unique index
  only, `30`).
- The `CASCADE` is load-bearing. Dropping `dim_fund` or `fact_fund_monthly` also drops the views and
  functions in later files that read them; those files re-create them. A file cannot be skipped in
  isolation while something earlier is dropped.

## Options

**A. Hash ledger plus `REFRESH ... CONCURRENTLY`.** A ledger table (name, content hash, applied
at) records each file after it succeeds. A run compares hashes. If none changed, it only refreshes
the matviews, in dependency order, with `CONCURRENTLY`. If a file changed, it re-creates that file
and every later file (the numeric order is the dependency order, so the suffix is the safe set).

- For: the common day takes no exclusive lock, readers keep the old rows until the swap, and a
  dropped connection leaves the old data in place. Cuts the failure mode of #207.
- Against: it needs a ledger, a refresh order, two new unique indexes, and a rule for a changed file
  (replay the suffix). A matview refreshed concurrently is slower than a plain refresh and needs
  disk for the diff; the saving is the lock and the re-create, **not proven to be most of the 28
  min**. A hash does not see a hand-edited database object or a changed table the SQL reads.

**B. Keep re-creating, drop `CASCADE` where nothing depends.** Smaller change, keeps the rule.

- Against: it keeps the lock and the full rebuild every day. Most `CASCADE`s have dependents (see
  above), so few can go. It does not change the cost, only some blast radius.

**C. Do nothing.** The ledger-free apply is simple and its test (`test.yml` applies it to a fresh
database) is the same path as production. The cost is the lock window and the #207 exposure.

## Recommendation

Adopt **A**, in two steps so each is checkable:

1. Baseline. Take the per-file timings from several consecutive daily runs (#871). Decide on those,
   not on the stated 28 min. If the matviews are a small share, B or C wins.
2. Implement A. Create `mv_savings_flow_monthly` and `mv_fund_holdings_monthly` with a unique index
   (a key must be proven unique in the data first, as `04` did for `fact_fund_monthly`). The ledger
   lives in `public`, has a named UNIQUE constraint on the file name and is written only after the
   file succeeded. An empty ledger (a fresh database, CI) replays every file, so `test.yml` still
   exercises the full path. A `force` input on `daily_ingest` replays everything.

The first `CONCURRENTLY` refresh of a matview needs it populated, so the first run after the change
is still a full apply. Freshness stays the same: every matview is refreshed every run, by the
apply and not by `pg_cron`.

## Consequences if accepted

- Section 7 of `DATABASE_MAINTENANCE.md` is rewritten: refresh is `CONCURRENTLY` on a day with no
  changed file; re-create happens on a change. The sentence in `08_cron_schedules.sql` that nothing
  may depend on it stays true.
- A drifted object (edited by hand) is no longer repaired by the nightly re-create. `force` is the
  repair; the ledger should say when it last ran.
- Refresh failures need the same handling as an apply failure: any failure is fatal, as today.
- Implementation is a separate PR (SQL, script, workflow, tests); this one changes docs only.
