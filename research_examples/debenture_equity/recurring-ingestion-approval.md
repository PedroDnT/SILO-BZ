# Recurring credit ingestion: reviewable activation package

Prepared 08/10/2026; not authorized or activated. Reuse existing ingestion and
schedules. No new production measurement is needed to repeat the seven-day
window already captured. This package follows the successful 07/10 canary.

## Evidence reused and revalidated

| Evidence | Result | Scope / limitation |
| --- | --- | --- |
| Production seven-day capture, 30/09–06/10 | 82,130,390 source bytes; 637,642 source rows; 6,630 debenture groups; 59,670 facts; successful audit in 73.103 seconds | Capture `f7d46926-0349-4d54-a198-ffbad8045065`; latest bounded SELECT, not a new ingest |
| Coverage / raw integrity | Expected and delivered dates both 30/09, 01/10, 02/10, 05/10, 06/10; no missing dates/drops. Stored raw SHA-256 recomputed in Postgres matches retained local raw | `2366a78e20955b69b7182197e0c390ade6b5dc5d6bce06fd48a7f74aa62790a8`; local reparse independently yielded 59,670 facts and zero drops |
| Repeated-vintage local storage benchmark of that real CSV | First allocation 54,910,976 bytes; second 93,437,952; incremental repeat 38,526,976 bytes | Existing PostgreSQL 16 local evidence, not measured production weekly growth. Full repeats preserve new capture vintages despite identical source content |
| Local resource observations | Existing benchmark reports roughly 68.7 MB WAL and 1.30 GB peak process RSS on repeat | Includes allocator/process effects; not production WAL/backups, hard memory limits or measured GitHub runner peak |
| Latest one-day production canary, 07/10 | 32,893,413 source bytes; 13,806 facts; 141.195 seconds including verification; +14,270,464 credit relation bytes | One day was slower than the measured week; latency is variable, not linear in row count |

Local repeated-week scenario: 30 executions × 38,526,976 = **1,155,809,280 bytes**
(about 1.16 GB) additional allocation. This is a scenario, not a bound or a
production forecast. Weekends, holidays, watchdog recoveries and failed/partial
captures can add vintages too. A seven-day refresh is not missing-date-only.
The prior 30 MB and 30,000-fact **single-day** limits cannot be reused for the
weekly path: the already observed week exceeds both.

Production weekly incremental allocation is still unmeasured in isolation.
Do not label local storage/WAL/RSS evidence as production measurement. It can be
measured on the first approved scheduled run without repeating recovered data now.

## Exact change offered for approval

[recurring-credit-wiring.patch](recurring-credit-wiring.patch) adds only the
step-local `B3_CREDIT_ENABLED: ${{ vars.B3_CREDIT_ENABLED }}` environment entry to
the existing B3 events steps in daily and watchdog. Patch SHA-256:
`77e7d10aa87cf3853921562accdb9bc0705d3201b3c24432d5db307bd8a866e1`.
`git apply --check` passed on the current checkout. The patch is retained for
review, not applied to workflows. Recheck open-PR overlap before implementation.

A successful GitHub repository-variable list on 08/10 found no
`B3_CREDIT_ENABLED`. The patch therefore leaves credit off until explicit
activation. Recheck immediately before rollout. After separately approved code
integration, activating the existing repository variable is:

```bash
gh variable set B3_CREDIT_ENABLED --repo PedroDnT/SILO-BZ --body 1
```

This command has **not** run. Approval must cover the workflow wiring, production
activation and preservation of overlapping capture vintages. The existing daily
starts at 03:00 UTC-3 (06:00 UTC); watchdog starts at 05:00 UTC-3 (08:00 UTC),
queues on the shared ingest concurrency group and invokes recovery conditionally.
No new cron or immediate full-workflow dispatch is proposed. These workflows
already apply schema; activation permits that existing scheduled workflow
behavior but introduces no schema change or separate schema dispatch.

`daily_update()` selects yesterday minus six days through yesterday. Its default
fetcher uses 120-second HTTP timeout/two attempts. `ingest_resilient()` may split
failed transport requests by known cash session. The approved one-day canary's
one-attempt 300-second policy is not the daily policy. This package does not
silently change defaults or attach the canary's guards to production daily code.

## First-three-session acceptance and stop rules

Verify the first three scheduled cash-session deliveries after activation:
record workflow/run and capture identities, actual request/delivery census,
raw SHA-256, exact selected facts and full census, nine metrics/group, zero drops,
one audit per capture and cutoff archive/replay when all required research inputs
exist. A complete capture alone is not seven-component/PIT acceptance. Watchdog
recovery cannot substitute for a scheduled acceptance observation. The warehouse
calendar and complete capture must prove delivery, not merely cron execution.

Record credit-relation/database allocation immediately before activation and
after every daily/recovery run. Count weekend/holiday/partial captures in total
cost. Proposed operational stops for this initial acceptance period:
**100 MB credit allocation growth in any run, 300 MB cumulative growth,
or database size reaching 135 GB**. These are operator checks, not enforced
transaction limits in the existing daily code. At a stop or integrity failure,
set the repository variable to `0`, stop further rollout and report evidence;
turning it off does not cancel in-flight writes or undo captures. No deletion or
retention trimming is authorized. A later normal daily run must not be claimed
accepted just because the shared workflow is green.

The 300 MB threshold is about 7.8 local repeated-week increments, leaving limited
headroom for extra recovery runs while observing three cash sessions. It is not
a guarantee that all sessions will fit. Report actual weekly production growth
before deciding continuing cost is acceptable. Source failures remain visible;
no silent prior-day fallback, invented zero trading or backdated availability.

## Current decision

No production write, fetch retry, workflow change, variable mutation, schema apply
or new automation was performed for this preparation. The superseded canary
heartbeat remains paused. Request approval for **daily/watchdog wiring and
activation under these initial acceptance/stop rules**. Scientific protocol,
issuer review dates, source conventions, archival acceptance and elapsed-market
history remain separate open requirements. Do not close the overall research goal.


## Approval and rollout in progress

Owner approved daily/watchdog activation on 08/10. The reviewed environment
patch is now applied locally; publication, green CI and merged-main verification
must precede setting the repository variable. No immediate full-workflow dispatch
is required. The next three scheduled cash-session observations and operational
stop checks remain pending. Earlier “unapplied/unapproved” statements above
describe the package as presented before this approval.
