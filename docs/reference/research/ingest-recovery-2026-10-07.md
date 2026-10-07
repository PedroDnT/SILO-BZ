# Daily schema lock and COTAHIST recovery

Status on 2026-10-07 (UTC-3): local fix verified; production application and
data recovery are not performed. This is separate from the new DEB export.

## Confirmed cause

[Daily run 37579395989](https://github.com/PedroDnT/SILO-BZ/actions/runs/37579395989)
failed three times at line 240 of the generated, catalog-guarded schema:
`DROP INDEX IF EXISTS uq_fi_cda_acoes`. It exhausted the existing 15-second
lock timeout and retries; `Run daily update` was skipped. The identity of the
concurrent lock holder was not established. A dashboard build is a historical
possibility, not a confirmed explanation of this run.

Read-only production catalog inspection found the CDA equity and fund-quota
indexes already valid, unique and NULLS NOT DISTINCT, with the expected widened
keys. Rebuilding them on every schema/migration replay was unnecessary.
The same DROP/CREATE pair appears in historical migration 33.

COTAHIST ingestion already exists, with a trailing seven-calendar-day refresh.
Successful COTAHIST writes were recorded on 06/10. The 06/10 quotation ZIP
was unavailable when probed at 03:39 UTC-3 that morning, before that day's
market session; this skip was expected. On 07/10 the schema failure prevented
the next refresh. A later public request for that ZIP returned HTTP 200.
The watchdog recovery steps were skipped; a green watchdog run did not mean
the absent quotation session was recovered.

## Local correction and evidence

`scripts/guard_noop_ddl.py`, reused by the existing apply-schema action, now:

- Skips adjacent simple DROP/CREATE UNIQUE INDEX pairs only when their table,
  columns, valid/ready/immediate state, btree method, uniqueness, NULL semantics,
  lack of expressions/predicates/included columns, ordering, default operator
  classes and column collations match the intended definition.
- Skips top-level DROP CONSTRAINT IF EXISTS when the named constraint is absent.
- Retains the original DDL for required changes. Unsupported index expressions,
  partial definitions and non-adjacent statements are left unchanged.

Historical migration files, natural keys and stored data are unchanged.
Existing lock timeouts and retry limits remain in effect. This avoids redundant
locking; it cannot guarantee that a genuinely necessary DDL change will acquire
its lock under every production workload.

The executed SQL regression proves actual widening changes the index, replay
preserves its OID, and NULL uniqueness remains enforced. A two-connection local
Postgres test holds an AccessShareLock while replay runs with a 250 ms lock
timeout: the replay succeeds and retains the index OID. An absent constraint
drop also succeeds under that reader. These checks ran against a disposable
loopback database, not production.

## Reviewable production action, not yet executed

After owner approval, run the existing **Daily CVM Ingest** workflow against the
reviewed correction, with `mode=daily` and `rebuild_dashboard=false`. This applies
schema and migrations and refreshes the existing daily sources, including the
COTAHIST lookback; it is not limited to one quotation session. It also applies
any other pending migrations on that ref, so inspect the ref before dispatch.

Keep `B3_CREDIT_ENABLED` unset: enabling debenture ingestion is a separate decision.
Confirm successful schema apply, COTAHIST audit rows and actual cash-market rows
dated 2026-10-06 afterwards. Do not equate workflow completion with delivered
source coverage. Production writes require the owner's approval under AGENTS.md.
