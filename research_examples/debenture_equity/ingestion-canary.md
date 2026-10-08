# One-session ingestion canary: 08/10/2026

Prepared locally; **not executed or approved for production**. This is the credit
ingestion slice of milestone 1, not completion of the seven-component research
collector. It changes no dataset, schema, production environment or schedule.

## Concrete execution package

| Item | Frozen request / acceptance |
| --- | --- |
| Signal session | 2026-10-08 only; never repeat 01/07–29/09 or 06/10 COTAHIST |
| Execution | 2026-10-09 after the completed-day boundary and after COTAHIST establishes 08/10; operator target before 09:45 UTC-3 |
| Expiry | 2026-10-09 at 10:00 UTC-3; no rescheduling or backdating |
| Calendar | [B3 Circular 041/2026-VNC, Annex 1](https://www.b3.com.br/data/files/20/57/01/AA/06A1F910ADC36BE9AC094EA8/OC%20041-2026-VNC%20ERRATA%20-%20CALENDARIO%20DE%20FERIADOS%20EM%202026_PT.pdf): October closure 12/10. 08/10–09/10 are ordinary Thursday/Friday sessions by inference from this calendar. Recheck exceptional B3 notices before execution. Scheduled sessions are not evidence of actual future trading. |
| Public request | Existing B3BdiFetcher, ConsolidatedRecords, start=end=2026-10-08, one HTTP attempt, 300-second HTTP timeout |
| Pre-write limits | At most 30,000,000 decoded UTF-8 raw bytes and 30,000 parsed facts; established COTAHIST session; no already complete delivery; exact plan hash and unexpired cutoff |
| Storage stop thresholds | Database ceiling 135,000,000,000 bytes; credit relation growth 100,000,000 bytes from the fresh execution baseline. Recheck after ingestion; no automatic next execution or cleanup. These checks do not roll back landed writes or bound WAL/backups. |
| Baseline evidence | Read-only Supabase check on 08/10 at 17:01:27 UTC-3: credit relations 451,207,168 bytes; database 87,923,518,611 bytes; latest cash session 07/10; zero complete captures whose requested end is 07–08/10. Refresh at execution. |
| Local evidence | `.context/debenture-ingestion-canary-2026-10-08/`, exclusive directory; private plan, full source CSV, persisted credit export and report. Output bytes are measured separately from database allocation; this directory is not the research input archive. |
| Production writes | Existing B3CreditIngestor only: one new capture, facts and one audit identity; failed audit/capture evidence remains visible. No schema apply, COTAHIST ingest, deletion or B3_CREDIT_ENABLED change. |
| Integrity | Reparse persisted raw; match response/persisted SHA-256, exact date/census, every natural key/value/ISIN/issuer/source/row hash/unit, nine metrics/group, acknowledged facts and one `ok` audit; require response/capture/audit and completion before cutoff. |

Frozen request: [ingestion-canary-2026-10-08.json](ingestion-canary-2026-10-08.json).
Plan SHA-256:
`d63f084db7eb4912b047b9503ab384efa1dea7f839c74975fd140f3af9db23ae`.

Execution command, **only after specific owner approval of this package**:

```bash
.venv/bin/python -m research_examples.debenture_equity.ingestion_canary run \
  --plan research_examples/debenture_equity/ingestion-canary-2026-10-08.json \
  --destination .context/debenture-ingestion-canary-2026-10-08 \
  --execute \
  --approved-plan-sha256 d63f084db7eb4912b047b9503ab384efa1dea7f839c74975fd140f3af9db23ae
```

The hash/flag are interlocks, not proof of human authorization. Without `--execute`
the same command uses the public fetch/parse path and never opens the database;
use a separate destination for that rehearsal. `prepare` builds a new local
request from supplied calendar evidence and explicit limits without network/DB
access. A new date/hash requires new approval; this package expires in place.

On failure stop, inspect private `report.json` (`failed_phase`, error type and
measured counts/sizes), plus the warehouse audit if an ingest started. Do not
automatically retry into another directory, delete partial evidence or infer
empty/no-trade from an unavailable response. A duplicate delivery is refused by
preflight; the preflight is not a database-wide concurrency lock.

Successful completion requires CLI exit 0, `COMPLETE.json` matching the SHA-256
of `report.json`, and no `LATE.json`. A partial directory or a report alone is
not success. Publication is checked after report fsync and after completion-receipt
fsync; a crossed cutoff preserves a late marker and returns failure. These remain
local-clock/filesystem receipts, not externally authenticated research archives.

Limits are checked at phase boundaries. The public fetcher materializes its
response before the raw-size check, its HTTP timeout is not a total-job wall-clock
bound, and an in-flight SQL write cannot be interrupted by these checks. The
original-filesystem report is operational evidence, without external timestamp
or strict PIT certification. Recurring capture stays off regardless of outcome.

## Rehearsal and the remaining collector blocker

Offline tests run the existing ingestor against the explicitly synthetic credit
fixture and mocked warehouse/network boundaries. They exercise persisted raw,
actual ingestor facts/audit, exact-value tampering, delivery/size/expiry/approval
refusals and no-DB dry-run behavior. They do not prove live source latency or a
successful production cutoff.

The complete research archive additionally needs the seven components in
`snapshots.COMPONENTS`. Current warehouse export alone cannot honestly supply the
complete FCA filing inventory required by `prospective._latest_fca`:

- `src/pipeline/cvm_pipeline.py` FCA ingestion reads the securities member only;
  `cia_filing` is not an FCA inventory. Absence of securities rows does not prove
  a complete filing with zero equities.
- `cia_ticker.fetched_at` is an insertion default and is not supplied for every
  later content update; it cannot authenticate the vintage of changed content.
- Historical COTAHIST establishes past sessions, not tomorrow's session before
  its cutoff. Official scheduled-calendar evidence must be retained separately.

The bounded next integration is an adapter for retained **complete FCA source
evidence**, operator-verified calendar evidence, and current bounded credit,
quote/IBOV and sector exports. Never synthesize a `complete=true` FCA census from
existing ticker rows or substitute insertion time for actual source observation.
Obtaining/retaining missing source evidence and its acceptance remains open;
this continuation adds no new warehouse dataset or mapper.

Subsequent local preparation now supplies a [source-backed FCA/collector adapter](collector.md)
from the full existing FCA ZIP, with index/general/securities reconciliation and
raw-byte replay. It derived 26 current company filings/32 equity rows from a real
retained copy. This resolves that local adapter gap; warehouse rows alone still
cannot establish it. The read-only 08/10 export has no credit capture, and no real
seven-component cutoff archive, source/financial acceptance or production execution
is claimed. The canary request/date/limits/hash and approval boundary are unchanged.

Credit ingestion can be evaluated independently. Its report always keeps
`research_snapshot_complete=false` and `strict_pit_certified=false`; a successful
credit canary is not an accepted development input or a model prediction. Before
recurring approval, also measure the existing seven-calendar-day refresh cost and
review daily/watchdog completion timing relative to the research cutoff.

## Recurring rollout: exact remaining engineering boundary

Verified against the current checkout on 08/10: both
`.github/workflows/daily_ingest.yml` and `.github/workflows/watchdog.yml` call
`src.pipeline.run_b3_events`, whose credit branch requires the literal environment
value `1`. Neither workflow exports `B3_CREDIT_ENABLED`. Creating a repository
variable alone therefore does **not** activate this path.

After specific recurring approval, the smallest wiring change is a step-local
`env` entry on each existing B3 events step:

```yaml
env:
  B3_CREDIT_ENABLED: ${{ vars.B3_CREDIT_ENABLED }}
```

This is a proposed change, not applied wiring. Inspect the live repository
variable before merging that wiring: an existing value `1` would activate the
next eligible run. With no variable or a value other than `1`, credit remains off.
The approval must cover both workflow paths, activation and operational storage;
it must not be inferred from approval of the one-session canary.

`B3CreditIngestor.daily_update()` requests yesterday minus six calendar days
through yesterday. A successful full-window refresh retains another capture
vintage, including overlap with earlier captures. This is not a missing-date-only
fetch. On transport/export failure, `ingest_resilient` can issue one child request
per known cash session; parse, completeness and database failures do not trigger
this splitting. A one-session canary does not establish weekly-window latency,
repeated-vintage storage growth or the number/cost of fallback attempts.

Acceptance after approved activation requires the first three **scheduled cash
sessions**, with workflow/run identity and actual UTC-3 completion times, requested
and delivered date census, source bytes/hash, dropped rows, per-capture facts and
one audit each, cumulative relation/database growth, and research archive/replay
receipts before their cutoff. Include weekend/holiday refreshes in cumulative
cost even though they do not count as the three cash sessions. A green workflow
without credit capture/audit evidence does not pass. A watchdog recovery does not
replace a scheduled-session acceptance observation. Partial/failed captures remain
visible and are excluded from research reads.

The current workflow also applies schema before ingestion. Do not dispatch the
whole workflow as a substitute for the separately approved, no-schema canary.
The recurring package must explicitly acknowledge that existing workflow behavior.
Turning the variable off stops subsequent credit branch executions; it does not
cancel in-flight writes, undo captures, certify retention or delete evidence.
No automatic cleanup, new schedule, schema change or production variable change
is authorized or performed here.

## Owner-authorized retrospective operational canary: 07/10

On 08/10 the owner replaced the pending next-day canary with an immediate
operational capture of 07/10, retaining the same source/fact/storage limits and
no-schema/no-permanent-activation scope. The prior scheduled heartbeat is paused.
The new request is `ingestion-canary-2026-10-07-operational.json`; its canonical
schema-2 purpose is `retrospective_operational`. It preserves the original
research cutoff of 08/10 at 10:00 UTC-3, and records actual preparation plus a
separate operational deadline of 08/10 at 19:29 UTC-3. Operational requests must
use a completed prior day and expire within one hour of preparation. The original
08/10 research request is unchanged and is not used for this execution.

This change cannot admit the late capture as a timely research observation.
The result retains actual source/database observation times, purpose and original
research cutoff, with research snapshot/PIT/permanent flags false. The same
hash, full fact/audit reconciliation, private evidence and no-retry rules apply.

### Actual operational attempt and stop

Executed once on 08/10 at 18:44:00–18:44:25 UTC-3. The public export returned
32,893,413 decoded UTF-8 bytes (SHA-256
`45ed5677adeee5b3a5fe109a628f6e5ba9f07620e67a196501600f39afbda212`), exceeding
the approved 30,000,000-byte pre-write limit. The runner exited 1 in phase
`fetch` after 24.279 seconds, before raw retention, parsing or fact writes.
The hash/byte count in the private report cannot replace retained raw evidence.
There is no COMPLETE receipt, complete capture or successful ingestion claim.

Read-only verification at 18:44:46 UTC-3 found one error audit
`3fc8711a-f86f-4cba-998c-52dfdc6deaec`, zero upserted rows and no new capture for
07/10. Credit relation allocation remained 451,207,168 bytes, unchanged from
preflight. The local exclusive evidence directory is
`.context/debenture-ingestion-canary-2026-10-07-operational/` (plan/report only).
No retry, schema apply, cleanup, recurring activation or second-day execution
occurred. The superseded heartbeat remains paused. A larger source-byte allowance
requires a new explicit approval and newly frozen operational request; unchanged
30,000-fact and storage gates may still refuse a later response. This operational
failure does not alter the research cutoff or establish PIT availability.
