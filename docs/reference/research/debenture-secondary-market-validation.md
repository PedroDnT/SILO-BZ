# B3 debenture capture: continuity and storage measurement

Measured on 2026-10-07 (UTC-3), after [PR #710](https://github.com/PedroDnT/SILO-BZ/pull/710)
merged. This validates a bounded sample, not the full historical window or
readiness of the bond→equity experiment. The parser, pipeline and migration used
here match the merged implementation. [Stored contract](debenture-secondary-market-capture.md).

## Observed coverage

Public B3 source: POST
`https://arquivos.b3.com.br/bdi/table/export/csv?lang=pt-br`, with
`Name=ConsolidatedRecords`, `ClientId=""`, `Filters={}` and the date bounds below.
Full real CSVs and measurement JSON remain in ignored local
`.context/b3-credit-validation/`; no market rows are committed or written to production.

| Requested range | Source rows, all instruments | DEB groups | Dropped rows | Decoded CSV bytes | Fetch / parse seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2026-09-30–2026-10-02 | 167,015 | 3,956 | 0 | 22,016,267 | 13.75 / 0.81 |
| 2026-09-30–2026-10-06 | 637,642 | 6,630 | 0 | 82,130,390 | 51.97 / 3.03 |

The seven-calendar-day export contains five dates and **1,181 distinct DEB
codes**, with nine long metrics per group. Codes are instruments, not issuers or
listed companies. All DEB groups in this sample have ISIN.

| Source trade date | DEB groups | Distinct DEB codes | Long facts | Missing oscillation |
| --- | ---: | ---: | ---: | ---: |
| 2026-09-30 | 1,497 | 843 | 13,473 | 342 |
| 2026-10-01 | 1,216 | 643 | 10,944 | 233 |
| 2026-10-02 | 1,243 | 659 | 11,187 | 315 |
| 2026-10-05 | 1,207 | 675 | 10,863 | 330 |
| 2026-10-06 | 1,467 | 775 | 13,203 | 370 |

A bounded, read-only SELECT against production `b3_cotahist`, cash market
`tpmerc='010'`, independently returned 30/09, 01/10, 02/10 and 05/10. All four
are present in the credit export. The warehouse had **no 06/10 cash session** at
measurement time, although B3 returned credit observations dated 06/10.
Consequently, the current calendar check confirms delivered known sessions; it
cannot detect a missing session that has not yet landed in COTAHIST. This is a
calendar-freshness limit, not proof of a missing credit date in this sample.

The 3,956 overlapping DEB groups were identical between the two real exports:
zero additions, removals or changed rows. This short comparison does not establish
the source's revision frequency or historical point-in-time availability.

SHA-256 of decoded CSV encoded as UTF-8:

- Three-day request: `4acea3099b68a334b99b74641a1af186b25fce159c573adc52c0e0cecb25481d`.
- Seven-day request: `2366a78e20955b69b7182197e0c390ade6b5dc5d6bce06fd48a7f74aa62790a8`.

The seven-day response arrived at 14:29:44 UTC-3. It is retrieval-time evidence,
not evidence that these exact versions were known on their original trade dates.

## Network and storage results

A subsequent live request for the same seven-day window failed with a transport
timeout at the configured 120-second read timeout. The full live ingest therefore
did not complete. No third identical network attempt was made.

Storage was measured separately using the successfully downloaded, hash-verified
real CSV. Its original response-arrival time was retained. The measurement used
the repository's parser, `facts`, `pg_client` upserts and shared ingest-audit
writer against a disposable loopback Postgres database. Each stored copy had
59,670 persisted facts, one `ok` audit identity and no missing known sessions.
These are local storage benchmarks, not successful production ingestion runs.

| Measurement | Result |
| --- | ---: |
| First copy: capture table, including TOAST and indexes, before manual VACUUM | 32,997,376 bytes |
| First copy: fact table, including indexes, before manual VACUUM | 21,913,600 bytes |
| First copy: combined allocated size after normal VACUUM/ANALYZE | 54,960,128 bytes |
| Two copies: combined allocated size | 93,437,952 bytes |
| Increment for second copy after first-copy maintenance | 38,477,824 bytes |
| Compressed live raw-CSV datum in first copy | 15,862,978 bytes |
| Parse-excluded local audited storage time, first / second copy | 2.97 / 2.80 seconds |
| Local WAL generated per copy, approximately | 68.7 MB |
| Process peak RSS, first / second benchmark | 0.94 / 1.30 GB |

Relation sizes include allocated space and indexes; VACUUM frees space for reuse
without guaranteeing it returns to the filesystem. The lower second-copy
increment is consistent with reusing freed space. Two copies are insufficient
to establish long-run vacuum behavior, index growth or database write latency.
WAL generation is cluster-wide during the local interval, not a retained-WAL forecast.

Local Postgres was 16.15/Homebrew with `pglz`; production reported 17.6 with
`pglz`. The local machine is not production compute. Production database size
was 87,349,275,795 bytes; this does **not** measure free disk or the plan's quota.
Read-only catalog checks found neither new credit table in production.

## Conditional storage scenarios

The implementation retains every retrieval, even when values are unchanged,
and currently has no pruning policy. If every daily seven-day capture resembled
this sample, with one retrieval per calendar day:

| Scenario | 30 captures | 365 captures |
| --- | ---: | ---: |
| Decoded raw CSV volume | 2.46 GB | 29.98 GB |
| Database growth using the measured second-copy increment | 1.15 GB | 14.04 GB |
| Database allocation using the first-copy post-maintenance size each time | 1.65 GB | 20.06 GB |

GB means decimal bytes. These are arithmetic scenarios, not forecasts or bounds.
They exclude backups, retained WAL, other datasets and additional failures/retries.
Historical bootstrap uses different, non-overlapping windows; the sample does
not justify applying these rates to all eighteen advertised months. The older
2025-12-11 one-day file was substantially smaller, as the stored contract records.

## Acceptance state

The bounded continuity check and local storage measurement are complete. The
parser accepted the observed layout, all known sessions arrived, and storage
preserved the expected long facts. No production deployment or enablement was
performed, and no implementation code changed during this measurement.

Production enablement still needs an explicit storage/retention budget, available
disk/quota verification and owner approval. Export latency and COTAHIST freshness
must be considered in that decision. Continuous deep history, the legacy route,
original publication vintages, REUNE rates and issuer/equity mapping remain
unverified or outstanding; this sample does not make the research experiment ready.
