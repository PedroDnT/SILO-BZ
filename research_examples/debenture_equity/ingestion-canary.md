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

Credit ingestion can be evaluated independently. Its report always keeps
`research_snapshot_complete=false` and `strict_pit_certified=false`; a successful
credit canary is not an accepted development input or a model prediction. Before
recurring approval, also measure the existing seven-calendar-day refresh cost and
review daily/watchdog completion timing relative to the research cutoff.
