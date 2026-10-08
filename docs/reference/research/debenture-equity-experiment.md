# Debenture signals and subsequent issuer equity residual returns

Owner-authorized implementation sequence, 2026-10-07 (UTC-3). This records the
plan agreed in the conversation, the executable audit and the offline experiment.
The approved three-month historical capture is complete. Broad identity acceptance
and confirmatory evaluation remain open. Predictability has not been demonstrated.
[ADR 0004](../../adr/0004-debenture-market-data-sources.md) remains authoritative.

## Execution reset: reviewed 2026-10-08 (UTC-3)

This section supersedes the **execution order**, not the frozen protocols,
acceptance floors, historical evidence or production authorization below.
Requested by the owner to evaluate progress and finish faster. Track execution
under existing #662/#628 and OPEN_ITEMS item 18; do not create a parallel backlog.

Owner clarification: **ingestion is a required deliverable of this plan**, from
the B3 export through persisted raw capture, validated facts and audit log, then
the research archive. A successful local export/replay alone cannot finish the
engineering work. Recurring ingestion must be specifically approved, activated
and observed operating before that delivery is accepted. This scope clarification
does not itself authorize production execution or permanent enablement.

### Goal and progress assessment

The scientific question is whether secondary-market debenture signals improve
out-of-sample issuer-equity residual-return prediction beyond equity information.
The implemented first experiment tests **extragroup liquidity activity**, not
yield/spread or cash-flow-adjusted bond returns. A negative liquidity result would
not reject every possible credit signal. Statistical evidence is not a proof of
causality or tradability.

| Deliverable | Evidence at this review | Acceptance status |
| --- | --- | --- |
| Existing-data audit and approved recovery | 13 approved slices reconciled; 69/69 study sessions; recovery process exit 0 | Complete within the approved scope; never repeat it |
| Identity and retrospective pilot | 26 documented original issuers; 22 with outcomes; 935 overlapping horizon rows; primary test 18 issuers/15 dates | Useful plumbing evidence; dated identity and unchanged test floors not accepted |
| Local prospective machinery | Archive/replay, canonical originals, fitting/publication, nested losses and conditional simulation exist | Implementation evidence; no successful real cutoff archive or independent PIT acceptance |
| Recurring production ingestion | Existing B3CreditIngestor and gated run_b3_events path; permanent capture remains off | Pending approved activation, measured recurring cost and observed scheduled coverage |
| Confirmatory evidence | Historical strict PIT has zero eligible rows; sector training coverage fails; no qualifying prospective history | Incomplete; no predictive conclusion, accepted power or MDE |

The execution drift was building downstream statistical machinery before closing
the upstream collection path. Additional synthetic tests and statistical helpers
cannot supply absent prospective observations. The broad goal “complete the plan”
also mixes finite engineering work with elapsed-market-time research. The goal
tool currently reports `usageLimited`; this review does not restart it, enlarge
its budget or declare it complete. No percentage complete is inferred from code
volume, test counts or commit counts.

### Replacement sequence and stopping rules

Time estimates below are active engineering effort, not promises of elapsed
research duration. Start with milestone 1; do not implement the later machinery
merely because production execution is waiting for approval.

| Order / bounded outcome | Work and dependencies | Acceptance / stop | Effort estimate |
| --- | --- | --- | --- |
| 1. One-session capture package ready for review | Reuse the existing ingestor and local archive/replay modules. Prepare exact seven-component exports, full-company FCA census, dated identity/sector inputs, equity/IBOV conventions and official next-session calendar evidence. Specify actual ISO signal date, cutoff, archive path, source queries, runner, fresh read-only storage baseline, resource limits and abort checks. | Local rehearsal exercises fetch/export → archive → replay, with raw hashes, complete census, nine metrics/group, zero drops and explicit exclusions. No production write. If any required component is unavailable, record the concrete failing seam and fix only that seam. Stop after one focused session with the package or a reproducible blocker; no detour into power/robustness features. | 2–4 hours; checkpoint after 2 hours |
| 2. Approved one-session production ingestion canary | Depends on milestone 1 and specific owner approval for its production date/window and limits. Execute existing B3CreditIngestor: fetch → persist raw/hash → parse/validate → upsert facts → audit, then export/archive/replay. Keep B3_CREDIT_ENABLED off; no schema apply or automatic continuation. | Persisted complete capture, recomputed raw hash, acknowledged fact counts, nine metrics/group, zero drops/missing sessions and exactly one successful audit for the capture. Report actual arrival/archive times, replay, exclusions, relation growth, snapshot/staging bytes and elapsed time. The required snapshot must precede the next verified cash-session 10:00 cutoff (UTC-3). Expired dates are not rolled. Preserve visible partial/failure evidence; no automatic cleanup. Ingestion success alone is not financial/PIT certification. | One execution, approximately 15–30 minutes; source latency may cause failure |
| 3. Deliver recurring ingestion and accept the development contract | Depends on canary evidence. Prepare the existing run_b3_events daily/watchdog integration, its B3_CREDIT_ENABLED gate, actual cutoff schedule, storage/retention and alert/stop runbook; obtain specific approval before activation. Measure existing trailing-seven-day re-fetch/revision cost before proposing any change. Reuse existing equity/IBOV/FCA/sector pipelines; do not create parallel ingestion. Resolve source/convention and dated identity gaps, accepted root/inventory and missing/late/revision policy. Present V3 separately, preserving V2/defaults. | After approval, verify the first three scheduled cash-session captures and their archives against the same integrity/cutoff checks; report fresh coverage, visible failures and cumulative cost. New snapshots retain actual observation times and distinct revisions; retries do not duplicate facts within a capture. Recurring ingestion acceptance does not depend on trained models or estimated power; research eligibility separately needs pre-outcome acceptance and at least 21 eligible issuers after attrition. V2 fails the horizon-20 power date floor; V3's 302 sessions are a scenario, not sufficient power. | 1–2 focused engineering sessions after the canary, then three observed scheduled cash sessions; approval and research acceptance may take longer |
| 4. Development decision before untouched test | Depends on real prospective development inputs and available original labels. Run existing nested comparisons first; implement only missing calibration/sector/dominance/delay/placebo and late/revision checks required for acceptance. | Development-only coverage and independent learning/activity/inference calibration pass; freeze test model, scope and scoring before test outcomes. Conditional simulation alone never activates a test. If gates fail, return insufficient evidence and propose a separately approved revision without using test outcomes. | Engineering estimated after real attrition is measured; elapsed sessions dominate |
| 5. Untouched-test result and finite closeout | Depends on accepted milestone 4 and elapsed test/outcome sessions. Execute frozen scoring and all existing inference/robustness gates. | Publish incremental evidence, unsupported hypothesis or insufficient evidence, with effect/uncertainty, attrition and provenance. A valid inconclusive result closes the execution milestone; it must not trigger endless unapproved expansion. Trading claims remain excluded. | Approximately 1 focused analysis session once qualifying observations exist |

Milestone 1 is the next **finite completion target**. Milestones 2–5 remain open;
ready-for-review is not authorization to execute them. A single-session canary
needs no trained test model and no power estimate: it validates input collection,
timing and replay. It is operational evidence only and is not automatically a
development observation or an accepted pre-outcome root.
Milestone 3 is mandatory for ingestion delivery. Prepare operational approval as
soon as the canary measures cost and coverage; do not wait for statistical power
or a fitted model to start preserving approved future observations. Until the
activation is approved, the permanent gate remains off.

The [one-session ingestion package](../../../research_examples/debenture_equity/ingestion-canary.md)
now prepares credit ingestion for 08/10, execution on 09/10 before 10:00 UTC-3,
with explicit limits and a default no-DB fetch-only runner. It reuses the existing
ingestor and checks persisted raw, exact facts, capture census and audit identity.
It has not executed in production. Milestone 1 remains partial: the warehouse
does not establish complete FCA filing inventory (including zero-equity filings)
or historical observation times for later changed ticker contents. The local
[source-backed collector](../../../research_examples/debenture_equity/collector.md)
now retains/rederives current FCA ZIP evidence and assembles seven components.
The actual current ZIP covers all 26 reviewed CNPJs with 32 equity/unit rows;
this certifies neither historical PIT nor independent source completeness.
The bounded SELECT ran with 5,790 equity, 192 IBOV and 43 sector rows, but zero
qualifying credit captures. No real seven-component archive exists yet. Links
reviewed only through 06/10 must be reviewed for 08/10 before eligible mapped
observations can be claimed; an empty rehearsal panel is not scientific readiness.
No production activation follows from this local implementation.

The owner subsequently approved an immediate 07/10 retrospective operational
attempt, replacing the next-day schedule. On 08/10 at 18:44 UTC-3, the B3 response
was 32,893,413 bytes, above the approved 30 MB pre-write gate. The executor
stopped with one error audit, zero facts, no capture and unchanged credit relation
allocation. The separate operational request preserves the expired research
cutoff; no PIT or live-rehearsal success is inferred. The heartbeat is paused,
and no retry or limit increase is authorized by this failure.

### Work parked until its dependency exists

Do not add more power simulators, model variants or general orchestration before
milestone 1 closes. Reuse the already implemented code; do not rewrite it. Do not
expand issuance searches to all 82 name candidates before measuring the canary's
eligible sample. Review dated changes for the bounded cohort where acceptance
requires them. Yield/spread, outstanding, new sources/mappers and trading-cost
extensions stay outside this liquidity-first continuation.

Do not lower date/issuer floors, remove horizons or replace inference methods to
shorten the calendar without an explicit scope decision and a separately frozen
protocol. Finishing engineering faster cannot manufacture historical PIT or
future sessions. The immediate next action is to prepare and rehearse the exact
collector/archive path; retain failures as evidence, not reasons for open-ended
additional infrastructure.

## 1. Identity and coverage gate: implemented candidate census

[Runner and instructions](../../../research_examples/debenture_equity/README.md)
provide a read-only, single-capture SQL audit and an offline JSON-to-table report.
No production credentials are read by the runner. No dataset, mapping table,
schema, workflow or public API is added. Name matches remain candidate evidence;
full CNPJ → stock ticker comes from FCA. No issuer stock ticker is required for
a debenture to exist. A parent's stock is never substituted automatically.

The query was executed through Supabase MCP on 2026-10-07 (UTC-3), against existing
capture `f7d46926-0349-4d54-a198-ffbad8045065`. Its hash verified, status was complete,
zero rows were dropped and all five expected sessions arrived. Source interval:
2026-09-30–2026-10-06; retrieved 2026-10-07 at 17:44:29 UTC-3. Stored raw UTF-8
payload: 82,130,390 bytes. The capture contains 59,670 facts, 6,630 source groups,
1,181 DEB codes and nine metrics. These are five observed sessions, not continuous
deep history or original publication vintages.

| Candidate classification | Debenture codes |
| --- | ---: |
| Unique full-CNPJ name candidate | 804 |
| Multiple CNPJ candidates | 2 |
| No candidate | 375 |
| Unique candidate with any registered equity/unit | 428 |
| Unique candidate with positive equity cash closes in the window | 365 |

The last row covers **82 distinct candidate CNPJs**, not 365 independent equity
outcomes. The extra name aliases include `cia_company.raw.DENOM_COMERC`; no
additional unique match depends solely on that commercial-name field in the
prior staged audit. The present query includes all cash short names within the
window rather than only 05/10. It reproduced the same unique/ambiguous/unmatched
census. Its output retains each alias and source; it does not rank a name as proof.

| Ambiguous bond | Candidate CNPJs | Disposition |
| --- | --- | --- |
| CMTC11, BRCMTCDBS004, Construtora Metrocasa | 27743642000137; 27743642000218 | Same 8-digit root, different establishments; no full-CNPJ choice inferred |
| MGPRA0, BRMGPRDBS076, Concessão Metroviária do Rio de Janeiro | 02327817000102; 10324624000118 | Different roots with the same normalized legal name; issuer link unresolved |

Bounded company-register inspection finds Metrocasa CVM 27340 under the first
CNPJ; the second is an FCA-name candidate. The two metro CNPJs have CVM 16810 and
22144, and commercial names METRÔ RIO / METRÔRIO. Neither ambiguous candidate has
an eligible equity/unit ticker in the audited registration set. These facts do
not identify the issuance's contractual issuer. Keep these bonds outside the
confirmed sample until issuance evidence settles the link.

Current verdict: **PARTIALLY READY**. Price/PU and quantity/count/volume exist;
rate/spread and outstanding are absent from this captured source. Turnover can
only be volume or quantity activity without an outstanding denominator. Holdings
marks are not market trades. Yield cannot be derived from PU alone under V1.

## 2. Dated evidence and PIT gate: implemented checks, partial evidence

Review each selected bond's issuer using issuance code/ISIN and a documentary
CNPJ reference. Record citation, validity dates and when SILO knew the evidence.
Legal/commercial-name agreement alone cannot clear this gate. Distinguish issuer
from ultimate obligor; any guarantor study is separately evidenced under #660.

Audit by session: delivery versus absence of a bond; null metrics; classifications;
revisions; and calendar freshness. Select the whole latest complete snapshot per
source/date available at the cutoff before joining facts, so later removals do
not resurrect old bonds. Do not forward-fill. Current historical downloads are
retrospective observation-date evidence; strict historical PIT cannot be recovered
by relabeling their trade date. Separate that study from prospective knowledge-time
validation. FCA reference dates and latest aliases do not establish publication times.

The bounded export now carries FCA negotiation and listing start/end dates. For
each full CNPJ/ticker, the runner takes the latest reference/version no later than
the signal, then requires that signal to fall within both recorded intervals,
including their endpoints. All listing rows within that reference/version remain
eligible for interval checks, preserving segment changes. Null bounds remain
unknown; the export cannot establish delisting
from a ticker's absence in a later full filing. Existing bundles lacking the four
date fields require a fresh export. These checks improve retrospective identity
selection without certifying original-date publication knowledge.

The local [reviewed links](../../../research_examples/debenture_equity/reviewed_links.json)
cite issuance documents, fiduciary reports and instrument records for twenty-six
**original issuers**:

| Bond / ISIN | Original issuer full CNPJ | Existing FCA equities |
| --- | --- | --- |
| ALPA13 / BRALPADBS051 | 61079117000105, Alpargatas | ALPA3, ALPA4 |
| ALUP18 / BRALUPDBS0C9 | 08364948000138, Alupar | ALUP11 |
| ANIM18 / BRANIMDBS073 | 09288252000132, Ânima | ANIM3 |
| ASAI18 / BRASAIDBS069 | 06057223000171, Sendas Distribuidora | ASAI3 |
| BSA318 / BRB3SADBS081 | 09346601000125, B3 | B3SA3 |
| BRKMA6 / BRBRKMDBS0A1 | 42150391000170, Braskem | BRKM3, BRKM5, BRKM6 |
| CAMLB1 / BRCAMLDBS070 | 64904295000103, Camil Alimentos | CAML3 |
| CSED12 / BRCSEDDBS001 | 62984091000102, Cruzeiro do Sul Educacional | CSED3 |
| ARML13 / BRARMLDBS029 | 00242184000104, Armac Locação, Logística e Serviços | ARML3 |
| CSAN18 / BRCSANDBS0D4 | 50746577000115, Cosan | CSAN3 |
| CCROA5 / BRCCRODBS0L5 | 02846056000197, Motiva (formerly CCR) | MOTV3 |
| CTEE18 / BRISAEDBS0E7 | 02998611000104, ISA Energia Brasil (formerly CTEEP) | ISAE3, ISAE4 |
| CGASA1 / BRCGASDBS0E1 | 61856571000117, Comgás | CGAS3, CGAS5 |
| ENEV13 / BRENEVDBS034 | 04423567000121, Eneva | ENEV3 |
| DXCO13 / BRDXCODBS018 | 97837181000147, Dexco | DXCO3 |
| EGIE27 / BREGIEDBS043 | 02474103000119, Engie Brasil Energia | EGIE3 |
| BRST15 / BRBRSTDBS043 | 04601397000128, Brisanet Serviços de Telecomunicações | BRST3 |
| DESK17 / BRDESKDBS053 | 08170849000115, Desktop | DESK3 |
| HYPEA8 / BRHYPEDBS0N4 | 02932074000191, Hypera | HYPE3 |
| IOCHA3 / BRMYPKDBS0C2 | 61156113000175, Iochpe-Maxion | MYPK3 |
| IRBR12 / BRIRBRDBS022 | 33376989000191, IRB Brasil Resseguros | IRBR3 |
| ITSA17 / BRITSADBS093 | 61532644000115, Itaúsa | ITSA3, ITSA4 |
| JHSF1A / BRJHSFDBS061 | 08294224000165, JHSF Participações | JHSF3 |
| MATD12 / BRMATDDBS014 | 16676520000159, Hospital Mater Dei | MATD3 |
| JALL13 / BRJALLDBS028 | 02635522000195, Jalles Machado | JALL3 |
| MILSA0 / BRMILSDBS0C8 | 27093558000115, Mills Locação, Serviços e Logística | MILS3 |

Each link records citation/page, original issuance date, review cutoff and actual
knowledge timestamp. Retrospective use assumes no intervening issuer transfer;
the cited original documents are not a comprehensive review of every amendment.
This pilot does not verify all 82 candidate issuers. AURE12 is excluded pending
dated reorganization review; a parent's ticker is never substituted for Aura Almas.

The export reconciles full-capture fact/group counts against capture metadata and
selected-bond export counts independently. The runner rejects missing whole groups,
incomplete nine-metric groups, duplicate facts, equal-time revision ambiguity,
mixed equity revisions/ISINs and incompatible return bases. It chooses a whole
complete, hash-verified snapshot before joining bonds. Source classification
comparison ignores case; original values remain unchanged. Missing observations
and unpublished metrics are excluded, never filled with zero or forward-filled.

## 3. Bounded historical preparation gate: approved recovery verified

Reuse the current ingestor after checking actual missing coverage. Start with a
three-month pilot only after an explicit window and storage allowance are approved;
expand to at least twelve months if continuity, issuer activity and statistical
power justify it. Do not repeat the recovered 06/10 COTAHIST session, run an annual
backfill, or enable permanent credit capture. The existing five-session production
load was separately approved; authorization is not extended to another window.
REUNE rates follow ADR 0004; this continuation adds no REUNE dataset or collection.

Read-only export on 2026-10-07 at **22:01:24 UTC-3** found 191 existing cash/IBOV
sessions from January, 764 equity rows for the four tickers above, and 171 credit
metric rows across the two captures. Both capture censuses reconciled: 13,203 facts /
1,467 groups and 59,670 facts / 6,630 groups. Existing equity and IBOV total-return
series are used directly, with revision and missing-value checks.

Between 01/07 and 06/10 there are 69 known cash sessions, five already captured in
credit and **64 missing sessions**. The proposal covers only 01/07–29/09:

| Sequential slice | Start | End | Known sessions |
| --- | --- | --- | ---: |
| 1 | 2026-07-01 | 2026-07-07 | 5 |
| 2 | 2026-07-08 | 2026-07-14 | 5 |
| 3 | 2026-07-15 | 2026-07-21 | 5 |
| 4 | 2026-07-22 | 2026-07-28 | 5 |
| 5 | 2026-07-29 | 2026-08-04 | 5 |
| 6 | 2026-08-05 | 2026-08-11 | 5 |
| 7 | 2026-08-12 | 2026-08-18 | 5 |
| 8 | 2026-08-19 | 2026-08-25 | 5 |
| 9 | 2026-08-26 | 2026-09-01 | 5 |
| 10 | 2026-09-02 | 2026-09-09 | 5 |
| 11 | 2026-09-10 | 2026-09-16 | 5 |
| 12 | 2026-09-17 | 2026-09-23 | 5 |
| 13 | 2026-09-24 | 2026-09-29 | 4 |

If the approved five-session sample repeated, arithmetic implies 644,979,098 bytes
of additional allocated relations (~0.65 GB) and 1,051,268,992 raw UTF-8 bytes
(~1.05 GB). These are scenarios, not forecasts or caps; allocation differs from raw
size and excludes WAL/backups. At preparation time actual quota/headroom was
unverified; the subsequent execution preflight is recorded below.
Execution should stop between slices once newly allocated credit relations reach
1 GB; the last slice can overshoot that threshold. Approval must cover that
behavior and adequate headroom must be verified first.

After specific approval, reuse the existing command for each listed slice, starting
with slice 1 only, then inspect its audit, hash, delivery and storage increase:

```sh
.venv/bin/python -m src.pipeline.b3_credit_pipeline --start 2026-07-01 --end 2026-07-07
```

No new ingestor, schema apply, daily enablement or COTAHIST recovery is needed.
The existing ingestor stores all published DEB groups, not just these three bonds.
Before every subsequent slice, recheck coverage to avoid duplicate recovery;
stop on errors, incompleteness, drops, lost headroom or the allocation threshold.
After completion, regenerate the bounded research export and repeat the audit.
Source latency and split retries determine runtime; no throughput was measured
for this proposed window. Source history availability is not yet validated.

### Initial approved execution checkpoint, 2026-10-07 (UTC-3)

The owner explicitly approved all 13 slices in the conversation. Preflight found
87,420,218,515 database bytes against the health workflow's recorded purchased
135 GB allowance; today's DB Health run `37589512910` succeeded. No replication
slots retained WAL. This checks the repository's operational allowance, not direct
filesystem free-space telemetry. Credit relations initially totaled 64,356,352 bytes.

| Slice | Outcome | Authoritative evidence |
| --- | --- | --- |
| 01/07–07/07 | Complete; five delivered sessions, zero drops | Capture `290b974f-246c-4fdb-98f1-e8682755eadb`, audit `ok` |
| 08/07–14/07 | Export transport failure after two attempts | Audit `c7c87c2d-2869-42c0-8d93-d2d2eca626b3`, zero facts written |
| Daily fallback 08/07 | Export transport failure after two attempts | Audit `c096de43-3760-423d-ad75-2732c9ca81f2`, zero facts written |
| Slices 3–13 | Not started | Sequence stopped on the existing ingestor's terminal error |

Successful capture observed at **22:08:49 UTC-3**, completed at 22:08:56. Its
175,737 source rows yielded 6,738 DEB groups, 1,222 bond codes and **60,642 facts**.
All groups had nine distinct metrics. Persisted UTF-8 payload: 23,842,689 bytes;
SHA-256 `82008ec327218286ef2dc0c8a92a335b30883b0e2a33084997e13c6d5260731f`,
recomputed successfully. Source dates remain July; knowledge time remains October.

The weekly failure ran 22:09:27–22:13:32; the existing daily fallback ran
22:13:32–22:17:37. Both logged `B3BdiFetchError`. The logs do not preserve the
underlying transport exception type/message, so its exact network cause is unknown.
Do not reinterpret this as empty trading data or unavailable historical publication.
At this initial checkpoint the terminal process exited 1, with no recovery process
or current audit running. The later successful recovery is recorded below.

Allocated credit relations ended at **86,646,784 bytes**, an increase of
**22,290,432 bytes**. The 1 GB stop threshold was not reached. Ten of the 69 known
signal-window sessions now have complete captures; **59 remain missing**. The next
unrecovered approved interval is 08/07–14/07. Resume only after diagnosing/rechecking
the export failure, rechecking coverage and preserving the already captured dates.
The existing approval is recorded; source transport, not owner permission, is now
the immediate blocker at this checkpoint. No schema apply, annual backfill, COTAHIST recovery or
permanent enablement occurred.

### Full approved recovery verified, 2026-10-08 (UTC-3)

A fresh read-only export at **10:16:12 UTC-3** confirmed all 13 approved July–September
slices complete. The first slice was reused; later slices landed through the existing
ingestor. Their audit rows are `ok`, with `rows_upserted = 9 × debenture_rows`;
all full-capture groups have nine distinct metrics, no drops or missing sessions,
and every persisted payload hash recomputes correctly. The final slice's audit
finished on 07/10 at **22:35:23 UTC-3**. The earlier failures remain preserved;
this successful retry does not establish their original network cause.

| Approved interval | Complete capture / audit UUID | Facts |
| --- | --- | --- |
| 2026-07-01–2026-07-07 | `290b974f-246c-4fdb-98f1-e8682755eadb` | 60642 |
| 2026-07-08–2026-07-14 | `659eea99-ed0f-4dfa-b795-7897db852f0e` | 57942 |
| 2026-07-15–2026-07-21 | `bc92619f-d30c-4d8c-9bb7-0ed14b35c551` | 59094 |
| 2026-07-22–2026-07-28 | `f7aedc74-c761-4ba8-8a99-a905c3c4581d` | 54243 |
| 2026-07-29–2026-08-04 | `cd53c851-af20-4a9f-9a3c-4f554743d46d` | 57690 |
| 2026-08-05–2026-08-11 | `1ccf4111-67e8-4d0e-97c0-2f0e758bef87` | 56511 |
| 2026-08-12–2026-08-18 | `c4d9fc1e-3928-44f9-9709-22835a6c5905` | 59202 |
| 2026-08-19–2026-08-25 | `edc9b530-5c36-421e-95ce-29ef3de296eb` | 64458 |
| 2026-08-26–2026-09-01 | `c5a3592f-cf8a-444d-85ec-dfbe93742ee1` | 63711 |
| 2026-09-02–2026-09-09 | `58b674ab-0ba9-4231-b9b5-f0230b42bce3` | 63576 |
| 2026-09-10–2026-09-16 | `fb5fbae1-dacd-4b47-88f5-4dbf30283aae` | 62352 |
| 2026-09-17–2026-09-23 | `134c22cf-9582-494e-89b0-a4c8a53cfbc2` | 61254 |
| 2026-09-24–2026-09-29 | `68f9aeba-673f-43e8-b256-f7484b1bc442` | 49887 |

These 13 captures contain **770,562 facts / 85,618 source groups**, covering all
64 originally missing sessions. Including the separately approved September/October
captures, the study now has **69/69 known cash sessions**, with no recovery window
remaining. This proves captured-session coverage, not that every bond traded daily.
Total allocated credit relations are **451,207,168 bytes**, a **386,850,816-byte**
increase from the original 64,356,352-byte baseline, below the approved 1 GB stop.
The contemporaneous database size was **87,923,518,611 bytes**, below the recorded
135 GB operational allowance. No additional recovery or permanent enablement is
needed for this approved window.

The finite recovery process also terminated successfully (exit 0) on 07/10 at
22:35:23 UTC-3. It reused slice 1 and completed the other twelve in 8 min 45 s;
each export succeeded on its single configured attempt. The largest observed
between-slice allocation increase was **400,982,016 bytes** (total relations
465,338,368 bytes), still below the stop. This is the execution-time measurement;
the 386,850,816-byte increase above is the later read-only measurement, not the
peak. The cause of that allocation difference is not established. Persisted raw
UTF-8 payloads across the thirteen slices total **557,818,677 bytes**. No recovery
process remains active.

The new research bundle carries **1,746 selected credit metric rows**, 764 equity
rows, 191 benchmark/cash sessions, 36 FCA rows with listing intervals, and 84 B3
sector records across indices. Its SHA-256 is
`acbf077a7cea4494956911ee53f22747a7a24768ee608997298243a6731b1329`;
protocol and identity hashes remain unchanged. Raw bundles stay local and ignored.

The retrospective runner produced **172 overlapping outcomes**: 63 at one session,
59 at five and 50 at twenty. Delayed entry produced 170. All horizons are
**inconclusive**, with no estimated predictive effect or p-value: fixed chronological
floors still fail. Sector observations retain only 13 horizon rows and none from
training; sector acceptance is inconclusive. Strict PIT still yields zero historical
rows because captures were observed in October. The completed recovery does not
complete the broader identity, statistical-power, PIT or tradability gates.

## 4. Experiment contract: offline implementation, pilot only

Primary target: issuer equity residual return over five trading sessions after
signal availability. Secondary horizons: one and twenty sessions. Select the
issuer's equity class using prior liquidity only. Use verified compatible adjusted
or total returns for equities and the market benchmark; estimate beta on a trailing
window that ends before the signal. Freeze the estimation window and date splits
before inspecting predictive results. Sector controls are robustness checks.

Compare an equity-only baseline with the same baseline plus credit activity and
price signals. Keep price changes distinct from bond total returns: amortization,
coupons, maturities and stale quotes can move PU mechanically. If necessary cash-flow
information is absent, exclude affected price windows or restrict the first model
to liquidity signals. Add rate/spread signals only after conventions and observed
rates exist. Aggregate to one issuer/date observation without treating repeated
last/reference PU or multiple bonds as independent issuer outcomes.

[protocol.json](../../../research_examples/debenture_equity/protocol.json) freezes
January equity warm-up, July–October signals, 14/08 training and 04/09 validation
cutoffs, next-session close entry, 126-session beta (100 valid pairs minimum),
20-session prior liquidity (10 observations minimum), and ridge penalties tuned
only on validation. Baseline features are equity momentum, volatility and volume;
credit additions are extragroup volume, trade count and distinct active bonds.
The target subtracts trailing alpha and beta times IBOV log total return.
Labels crossing the next split are purged; test targets never tune or refit models.

**This protocol is a plumbing-only pilot.** Even assuming complete coverage and
daily issuer trading, its primary horizon permits at most **27 training, nine
validation and 15 test dates** after purges and future-label availability, below
the declared 30/10/60 floors. Three reviewed issuers also cannot meet the 20-issuer
test floor. Recovering the 64 sessions cannot make this protocol confirmatory.
Do not lower floors after seeing outcomes. A separate longer protocol, broader
documentary sample and sample/power assessment must precede confirmatory scoring.

## 5. Evaluation and decision gate: implemented method, no usable primary sample

Freeze chronological development, validation and untouched-test intervals. Account
for overlapping horizons and dependence across issuers/dates; predeclare multiple
comparison handling. Run issuer shuffles, realistic availability delays and exclusions
of dominant issuers/days. Report sample attrition, effect sizes and uncertainty.
Costs and capacity are required before a tradability claim. Distinguish incremental
out-of-sample evidence, unsupported hypothesis and insufficient evidence. No five-day
capture can settle the research question.

The runner implements paired out-of-sample MSE gain, crossed issuer/calendar-block
bootstrap, Bonferroni adjustment for the three horizons, within-date issuer credit
vector shuffles, two-session delayed entry, and refits excluding dominant issuers
or activity dates. These are methodological checks, not a validated power analysis.
Sector robustness uses existing dated `b3_index_portfolio` labels, joining the
exact ticker/signal date only when observed by signal-day end in Brasília and
before export. It never fills earlier sessions. Conflicting labels across indices
refuse evaluation. Both models receive the same training-only sector indicators;
validation/test categories absent from purged training are excluded and counted.
The sector placebo shuffles whole credit vectors within date and sector. Both
original and delayed sector studies must pass their sample and inference gates
alongside the uncontrolled studies before an incremental-evidence verdict.

A bounded live check on 08/10 confirmed 14 dated sessions from 16/09 through
06/10 for ALPA4, ALUP11 and ANIM3; ALPA3 has no sector observations in this window.
This is no sector history for the pilot's July/August training period, so sector
acceptance remains inconclusive despite completed credit recovery. No missing
classification is inferred from a current label.

### Historical checkpoints before full recovery

The initial real-data execution produced **four issuer/date outcomes, all horizon one**;
zero five- or twenty-session outcomes fit the stored capture and fixed outcome end.
The 64 missing credit sessions were reported separately. All horizons are
**inconclusive**, and no p-value or predictive effect was estimated. Strict PIT
mode yielded zero rows: all historical credit was retrieved later, and equity/index
endpoints expose current revisions rather than original-date vintages.

Reproducibility identifiers (SHA-256; source payloads/results remain ignored locally):

```text
protocol c26a949418ebc10f5d948f27cfcd16460c0d79512b648d2b898d7d6b657c5122
bundle   d243b0ccc99afc4d45eb303b63bda0004e7288a4bb5ef91efae381146697dbfa
links    3ccc7afbfadb73bad95548c4856a923ade783f02f50c59c9310c71aaefdae7c3
```

After the approved partial recovery, a fresh bounded export at **22:17:54 UTC-3**
reconciled all three stored captures and 297 selected metric rows. The runner
produced **19 rows across horizons: nine at one session, five at five sessions and
five at twenty sessions**. These are overlapping issuer/date outcomes, not 19
independent observations. Training/validation/test coverage remains insufficient;
all horizons remain inconclusive and strict PIT still yields zero rows.
The new bundle SHA-256 is
`30a28ffe602694235c9f7bb8cf2383ef6cd075389fe1c3f6ccb2c4b0c8506826`;
protocol and identity hashes are unchanged. The earlier four-row run above is
retained as evidence before recovery, not current coverage. Both this 19-row run
and the initial four-row run are historical checkpoints. The current full-recovery
result is the 172-row run and `acbf077a…` bundle recorded in section 3 above.

Execution estimates after gate clearance: documentary review initially 2–4 hours;
coverage audit about one day; historical preparation 1–3 days subject to source
latency and approval; model/evaluation 2–4 days. Prospective validation requires
elapsed market history. The full research plan remains open; offline implementation
and a prepared capture proposal do not complete its empirical acceptance gates.

## 6. Expanded documentary pilot and next protocol requirements

On 08/10, documentary review added ASAI18, BSA318 and BRKMA6, using the cited
fiduciary reports and instrument characteristics. Report pages were visually
checked, complete PDF payloads fingerprinted, and full CNPJs joined through FCA.
Published CVM commercial names are Sendas Distribuidora S.A., B3 and Braskem;
no different brand alias or parent identity was inferred. Coupon formulas and
original issuance quantities in these reports remain contractual/snapshot facts,
not secondary-market yields or a daily outstanding denominator.

A new bounded export at **10:25:26 UTC-3** contains 3,177 selected credit metric
rows, 1,505 equity rows, 77 FCA rows and 154 sector/index records. The six-issuer
runner produces **288 overlapping outcomes** (112/102/74 at 1/5/20 sessions), all
inconclusive. Only 27 horizon rows retain observed exact-date sectors, with none
in training. Strict PIT still yields zero rows. No fitted performance is now
reported when untouched-test date/issuer floors fail; the floor is checked before
ridge tuning, fitting or scoring, including sensitivity/placebo refits.

The initial six-issuer diagnostic run computed exploratory one-session MSE before
rejecting its inadequate 14-date/four-issuer test sample. That exposed a gate-order
defect, now corrected; those metrics do not inform sample selection, protocol
tuning or a predictive claim. The corrected local result supersedes that diagnostic.

```text
six-issuer bundle e9348ed02c508e138524649d23a85457e50a7971e5e7de07b10ce90dcf77e5c2
six-issuer links  b185588d862dfee8f123fae8451f633117c8d204add6fec99800fc15ae8b7a29
```

Earlier three-issuer results and their fingerprints remain historical checkpoints.
The original protocol is unchanged; adding identities cannot repair its date ceiling.
These six original-issuer links still assume no intervening issuer transfer and
do not satisfy broad dated identity acceptance or the 20-issuer test floor.

A subsequent documentary pass added **CAMLB1, CSED12 and ARML13**, bringing
the link file to nine original issuers. Camil's deed identifies the full CNPJ;
its 11th-issuance report identifies the second-series code/ISIN. Cruzeiro's
opening announcement identifies the full CNPJ/ISIN; its second-issuance report
identifies the code and issuance date. Armac's report contains the entire tuple.
Each cited PDF was downloaded completely, fingerprinted and its relevant page
visually checked. ARML13 was chosen because primary evidence was available,
without selecting on predictive outcomes.

A fresh read-only export at **10:40:48 UTC-3** contains 3,672 credit metric rows, 2,078 equity rows, 98 FCA rows and 210 sector/index records. It yields
**326 overlapping outcomes** (127/116/83 at 1/5/20 sessions) across nine issuers,
all inconclusive before fitting/scoring. Only 34 outcomes have eligible exact-date
sectors; strict PIT remains zero (all 69 credit sessions unavailable at historical
knowledge cutoffs). The 288 outcomes above remain the earlier six-issuer result.
Fingerprints:

```text
nine-issuer bundle aa2c69fc54d25cff7dfa7d7fd0a59cbcc84be7e88884b4b3a03e28081d82d67c
nine-issuer links  0e590a40544e17493ee10995d00112710347f31b5321f8ada79de6dcb3c49fec
```
Published company/FCA names support
Camil Alimentos, Cruzeiro do Sul Educacional and Armac; no extra brand alias was
inferred. Original quantities and report-date PU remain dated document snapshots,
not daily outstanding or traded-price observations.

**AALR13 remains excluded.** Its [2025 fiduciary report](https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx?Tela=ext&descTipo=IPE&CodigoInstituicao=1&numProtocolo=1513198&numSequencia=1037904&numVersao=1),
PDF page 3, identifies AALR13 / BRAALRDBS057 with **42771949001883**;
the name-derived FCA equity candidate AALR3 has **42771949000135**. The
document SHA256 is `ee2454d1281fd6767319f1b5df39f2fe7ce47a32af017b7db876399674c4e33f`.
The common CNPJ root does not establish the required exact legal-issuer join;
neither a presumed typo nor a matrix/branch substitution is accepted.

Auren's June documents were also recovered completely. The
[01/06 notice](https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx?Tela=ext&descTipo=IPE&CodigoInstituicao=1&numProtocolo=1529026&numSequencia=1053732&numVersao=1)
concerns AURP12/AURP13 issuer succession; the
[24/06 notice](https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx?Tela=ext&descTipo=IPE&CodigoInstituicao=1&numProtocolo=1538165&numSequencia=1062871&numVersao=1) proposes moving
the **third** Auren Energia issuance to CESP, subject to conditions. Neither
alone establishes a transfer of AURE12, the second issuance. AURE12 remains
outside the reviewed link file pending a complete relevant amendment review;
group reorganization alone is not a reason to substitute its issuer CNPJ.

The next documentary pass added **CSAN18, CCROA5, CTEE18, CGASA1 and ENEV13**,
using the full CNPJ/code/date on each 2025 fiduciary report's PDF page 2 and
SND's exact code/ISIN/issuance characteristics. Complete PDFs were fingerprinted
and the cited pages visually checked. ENEV13 was chosen from an available
primary report, without selecting on model performance; CESE32 was not inferred
from Eneva's name. Motiva's report page 3 records the 23/04/2025 change from CCR;
ISA's cover identifies its previous CTEEP name. These names do not change the
full-CNPJ key or justify substituting any related company's stock.

The bounded `public.cia_company` lookup retains published commercial names:
Motiva = MOTIVA INFRAESTRUTURA DE MOBILIDADE S.A.; ISA = CTEEP;
Cosan = COSAN SA INDUSTRIA E COMERCIO; Eneva = ENEVA SA;
Comgás = COMPANHIA DE GÁS DE SÃO PAULO - COMGÁS. These are current register
aliases, not evidence of when an alias became historically public. Each source
row was selected by its complete CNPJ; no external brand was invented.

The **10:44:33 UTC-3** export contains 8,325 credit metric rows, 3,279 equity
rows, 142 FCA rows and 336 sector/index rows. The unchanged pilot yields
**602 overlapping outcomes** (230/217/155 at 1/5/20 sessions), all inconclusive
before model scoring. Only **13 of the 14 reviewed issuers** produce panel rows:
ENEV3 fails the existing trailing-beta requirement (37 excluded signal rows).
Exact-date sectors retain 64 outcomes; strict PIT remains zero, with all 69
historical credit sessions unavailable at knowledge cutoffs. No confirmatory
floor, protocol date or missing-history rule was relaxed.

```text
fourteen-issuer bundle 1aff1b5ad5a397d8a3e5d3a6e5d6c9c827e4a171718b3aedee03d3ba7ca89304
fourteen-issuer links  ba12125a91462fd4fb5c768e36b0d8ed14366cb5d3bd43e3fa4f2164f19f529f
```

The nine-issuer and six-issuer results above remain historical checkpoints.
Annual quantities in circulation and coupon/amortization payments found in these
reports are useful dated documentary evidence; they have not been turned into
continuous outstanding, a complete cash-flow archive or observed market yields.
C&A's CEAB13 review also remains open: its report prints an invalid header
issuance date and no ISIN, while SND identifies a unique series and the report
labels a first series. A board approval proves C&A's full CNPJ but does not by
itself resolve those issuance fields. No link was admitted by ignoring them.

A further documentary pass added **DXCO13, EGIE27, BRST15 and DESK17**.
Dexco's report page 3 contains the full identity tuple. Engie's report page 3
identifies its full CNPJ, and page 4 identifies the seventh issuance's second
series EGIE27/ISIN/date. Brisanet's fifth-issuance report page 3 identifies the
CNPJ/code/date; SND supplies its otherwise blank ISIN. Desktop's seventh-issuance
deed page 2 identifies the full CNPJ, with exact code/ISIN/date supplied by SND.
Complete source payloads were fingerprinted and cited PDF pages visually checked.
Primary evidence availability, not model outcomes, determined these choices.
Current `cia_company.DENOM_COMERC` reports DEXCO S.A., DESKTOP S.A and
TRACTEBEL ENERGIA (Engie); Brisanet's commercial name is null and remains null.

The **10:48:47 UTC-3** export contains 10,638 credit metric rows, 4,043 equity
rows, 165 FCA rows and 420 sector/index rows. It yields **752 overlapping
outcomes** (286/269/197 at 1/5/20 sessions), all inconclusive before fitting.
**16 of 18 reviewed issuers** produce panel outcomes: ENEV3 and BRST3 fail the
trailing-beta floor; 65 signal rows are excluded for that floor in total.
A missing earlier ticker history is not silently stitched to a later stock code.
Exact-date sectors retain 77 outcomes; strict PIT still yields zero, with all
69 credit sessions unavailable at historical knowledge cutoffs. The fourteen-
and nine-issuer exports above are historical checkpoints, not current totals.

```text
eighteen-issuer bundle 4b52aad593c253910dcca33f7d35ef561ec6f2a0164ce72ea0739b4719d828f5
eighteen-issuer links  358909f07ba48f4b665dffef42d5ad616953a042eabe0c28702bac4ed4686f02
```

**BRIT11 was not substituted for BRST15.** Its [2025 report](https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx?Tela=ext&descTipo=IPE&CodigoInstituicao=1&numProtocolo=1510869&numSequencia=1035575&numVersao=1)
page 3 prints BRBRITDBS002 and a first issuance, whereas the current
[SND record](https://www.debentures.com.br/exploreosnd/consultaadados/emissoesdedebentures/caracteristicas_d.asp?selecao=BRIT11&tip_deb=publicas)
and warehouse identify BRBRSTDBS019, with SND calling it a second issuance.
The report hash is `59ee54fb44978117de0521e44a67a78b4c80a3047451a5b5533d3094debbfd85`.
This identity/history discrepancy remains unresolved; no value was silently
corrected. BCBF16 also remains outside the original-issuer sample: Hapvida's
[official debt page](https://ri.hapvida.com.br/informacoes-financeiras/divida-e-ratings/)
identifies BCBF Participações for that issuance, requiring dated legal succession
evidence before a Hapvida stock linkage can be accepted. Current name agreement
cannot certify its original issuer or date a transfer.

Documentary review then added **HYPEA8, IOCHA3, IRBR12 and ITSA17**. The
2025 reports identify full CNPJ/code/issuance date on PDF pages 6/2/2/2,
respectively; SND supplies each exact ISIN. Complete PDF hashes and page locators
are retained in the link file; relevant pages were visually checked. Hypera's
PDF begins with other-emission disclosures before its own report, so its issuer
page is page 6, not page 2. Current company-register commercial names are
HYPERA PHARMA S/A, IOCHPE-MAXION and ITAÚSA; IRB's is null and remains null.

The **10:52:06 UTC-3** export contains 12,123 credit metric rows, 4,998 equity
rows, 209 FCA rows and 546 sector/index rows. The unchanged pilot produces
**894 overlapping outcomes** (340/322/232 at 1/5/20 sessions) from **20 of the
22 documented issuers**, all inconclusive before fitting/scoring. ENEV3 and
BRST3 remain excluded by trailing-beta history; 108 outcomes have eligible
exact-date sectors. Strict PIT remains zero (69 unavailable historical credit
sessions). Twenty issuers anywhere in the panel are not proof of the required
21 eligible issuers in the untouched test after exclusions and dominance refits.
For signal dates after 04/09, the one-session panel has 17 issuers/19 dates and
the primary five-session panel has 17 issuers/15 dates; the twenty-session panel
has no such outcomes. This is below both issuer and date acceptance floors.
The prior eighteen-issuer run remains a historical checkpoint.

```text
twenty-two-issuer bundle d460a425a8b6561de6393339465890b7bab219e57526873be39275b1c1bc8d0f
twenty-two-issuer links  8d5c6fe22e4a263b569ae5f0bd0c24a66190ebb44066d211a9926f42f2b579a7
```

Documentary review then added **JHSF1A, MATD12, JALL13 and MILSA0**, reaching
**26 original-issuer links**. Complete 2025 fiduciary reports identify full
CNPJ/code/issuance date on PDF pages 3/2/3/2, respectively; JHSF and Jalles also
identify ISIN on those pages, while SND supplies the exact Mater Dei/Mills ISINs.
Hashes and page locators are retained in the link file; relevant pages were
visually checked. Existing FCA records match each full CNPJ to JHSF3, MATD3,
JALL3 and MILS3. Current company-register commercial names are JHSF, HOSPITAL
MATER DEI S.A., JALLES MACHADO S.A and MILLS ESTRUTURAS E SERVIÇOS DE ENGENHARIA
S/A; these current aliases do not date a historical identity change.

JALL13 and MILSA0 were chosen because their original-issuer documents were
available, not because of predictive outcomes. The JALL11 report omits issuance
fields and says no securities remain in circulation; it does not establish the
required original tuple. Some other CVM download responses were HTML despite
successful HTTP status and were rejected as PDFs; no incomplete response was
accepted as documentary evidence.

The latest bounded export ran **10:59:27–10:59:41 UTC-3 on 08/10**. The full
response exceeded the connector's 8 MiB limit, so two read-only credit partitions
were combined only after all repeated datasets and full selected-fact censuses
compared equal. The bundle preserves both timestamps; this is not a single
transaction or a historical vintage. It contains 13,608 credit metric rows,
5,762 equity rows, 239 FCA rows and 602 sector/index rows. The unchanged pilot
produces **935 overlapping outcomes** (355/336/244 at 1/5/20 sessions) from
**22 of 26 documented issuers**. JHSF3 contributes three rows and JALL3 38;
MATD12's 14 volume observations and MILSA0's five are all INTRAGRUPO and excluded
by the pre-existing EXTRAGRUPO rule. ENEV3 and BRST3 still lack trailing beta
history. These exclusions must not be repaired by relaxing the protocol.

All horizons remain inconclusive before fitting/scoring. Only 108 outcomes have
eligible exact-date sectors, with no sector training history. For signal dates
after 04/09, one-session outcomes cover 18 issuers/19 dates and five-session
outcomes 18 issuers/15 dates; twenty-session outcomes have no untouched-test
coverage. Strict PIT still yields zero rows because all 69 historical credit
sessions were captured after their decision dates. Reaching the initial target
of 25 documentary candidates does not satisfy the 21 eligible untouched-test
issuers, dated-amendment review or statistical-power requirements. The prior
22-link run remains a historical checkpoint.

```text
twenty-six-issuer bundle e12c6796f53ad1b2b7e7fc840778c7989b36988a1722456f7d6a1825f0e6e0d4
twenty-six-issuer links  bcb38d37a60125b1cbbdceebd8b245cd8ac88e1bc154647d086457b293cab9a3
```

A separately versioned [prospective design candidate](../../../research_examples/debenture_equity/prospective-design.md)
and [machine-readable candidate](../../../research_examples/debenture_equity/prospective_protocol.json)
now specify the 90/50/100-session structure, information and label cutoffs,
immutable input requirements, development-only power grid and a full completion
audit. Candidate fingerprint: `83eebc6a7c3ffbd7ead97235dd73767a25535d500bdfa460cf3d33fdbe9d7555`.
It is not activated or accepted by the pilot runner. Collector/evaluator and
power-calibration implementation remain local work; a future production canary
needs an exact date, budget and specific approval before execution.

The [local retention helper](../../../research_examples/debenture_equity/snapshots.py)
now archives already fetched files with private permissions, byte/hash checks,
actual-clock cutoff enforcement and no overwrite. Interrupted/late archives are
diagnostic evidence only; verification refuses changed manifests/components. It
does not fetch, validate source semantics or certify strict PIT. Collector and
prospective evaluator integration remain outstanding.

The calculation layer now separates frozen issuer/date features from realized
labels. Later label revisions cannot change class selection, alpha, beta or
features; equity ISIN is retained and checked, and feature/label equity revisions
are recorded separately. The original 935-row pilot result and prior columns
were compared before/after and are unchanged. Archive/source/calendar and actual
label-availability integration remain open; this is not strict-PIT acceptance.

An [offline cutoff-input replay](../../../research_examples/debenture_equity/prospective.py)
now reads verified archive bytes, reparses raw credit and compares selected facts,
checks receipt/revision/calendar availability, and selects the latest complete
company FCA filing before ticker selection (including zero-equity filings).
Frozen feature records must replay exactly against the externally pinned candidate.
Completeness assertions still need source evidence; prediction/label availability,
independent financial conventions and PIT acceptance remain open.

The remaining implementation sequence is conditional, not a new production approval:

1. Review at least 21 independent full-CNPJ issuers and their dated changes using
   primary documentary evidence. Freeze eligibility without selecting on predictive
   outcomes. Retain commercial/legal aliases with their source; ambiguous ownership,
   unlisted issuers and missing equity history are exclusions, not parent substitutions.
   At least 21 must remain eligible in the untouched test sample so a leave-one-issuer
   refit still meets the unchanged 20-issuer floor; identity review alone cannot
   guarantee trading, sector or date coverage. Target 25 documentary candidates
   initially to allow attrition, without relaxing the 21-eligible-issuer requirement.
2. Freeze a separately versioned protocol before confirmatory scoring. The preserved
   V2 90/50/100 draft passes ordinary train/validation/test date ceilings but fails
   the nested development power-date floor: only 34 delayed horizon-20 OOS dates
   versus 60 required. A separate unactivated V3 120/60/100 proposal plus 22 outcome
   sessions allows at most 74 such dates, with 126 prior equity warm-up sessions.
   Actual activity, availability and sector gaps can only reduce that ceiling.
   Neither candidate is accepted or calibrated by a date count; the detailed
   design and completion evidence below retain those gates.
3. Establish actual decision-time snapshots before claiming prospective PIT.
   Proposed cutoff: 10:00 Brasília on the next cash session, using only data then
   observed for the prior session. Primary entry is that next session's close;
   delayed robustness enters one session later. Archive the exact credit, equity
   adjustment revision, benchmark, FCA identity and sector inputs known at the
   cutoff. A reference date or a later export is insufficient. The current strict
   runner deliberately cannot certify this: a prospective evaluator and retention
   design must be separately accepted before enabling a new capture schedule.
4. Assess power on development data before inspecting untouched outcomes. Report
   minimum detectable loss gains across a predeclared relative-MSE grid, preserving
   issuer/date dependence, activity sparsity and overlapping labels. Floors alone
   are insufficient. Keep price/rate additions and tradability outside any claim
   until their cash-flow/convention and execution-cost/capacity gates are evidenced.
5. Obtain specific production approval for any expanded window or continuing capture,
   including snapshot retention and a measured storage allowance. The executed pilot's
   peak implies about 6.27 MB per recovered session; the V3 proposal's 302 new
   sessions would be about 1.89 GB if that layout repeated, before additional input
   snapshots, duplicate prediction staging, WAL or backups.
   This is a scenario, not a bound, and exceeds the prior 1 GB allowance. Keep daily
   credit disabled and do not start another recovery under the completed 13-lot approval.

Prospective acceptance also requires elapsed trading history; no amount of present
backfill reconstructs the original knowledge vintages now missing. Historical
research may remain explicitly retrospective, with its limitations retained.

The local [outcome replay](../../../research_examples/debenture_equity/outcomes.py)
now connects one on-time realized-return archive to frozen input features, with
calendar/revision checks and actual publication-time eligibility at a requested
fit cutoff. It rejects collection/publication before the first post-exit cash
session. It does not select the first label version or fit/freeze predictions;
those integrations, independent financial/PIT acceptance and future elapsed
history remain required. No additional production execution is authorized.

The local [original-selection helper](../../../research_examples/debenture_equity/originals.py)
now reserves one exclusive outcome slot per signal/horizon/delay inside an
externally pinned first-input archive. Reserved partial/invalid originals cannot
be replaced; verification never searches alternative revision paths. This is
scope-local exclusivity, not proof of globally earliest source history. The root
pin must be accepted before outcomes, and fitting must bind the same input hashes.
Late/missing/revision sensitivity and actual frozen predictions remain open.

The local [model preparation](../../../research_examples/debenture_equity/fitting.py)
now uses canonical development originals available at the fixed first-test cutoff,
with separate training/validation availability and exit purges. Model parameters,
scaling and exact data lineage are retained. Offline preparation does not prove
timely prediction publication or later-signal reuse; those integrations, power,
sector robustness, inventory completeness and independent acceptance remain open.

The local [prediction publication helper](../../../research_examples/debenture_equity/predictions.py)
now enforces actual-clock cutoff publication and exact original model/lineage
replay. Later signals reuse the stored original parameters within the fixed
test interval, with exact input/model hashes and no test-label fitting. This is
private candidate evidence, not activation, entry-close verification or empirical
acceptance. Power, sector robustness, missing/late/revisions, scope/inventory and
independent financial/PIT acceptance remain open; production is unchanged.

The [development date audit](../../../research_examples/debenture_equity/power.py)
proves the preserved V2 candidate cannot meet the 60-date nested-OOS power gate
for horizon 20: its best-case ceilings are 37 primary / 34 delayed dates. A
separate unactivated [V3 proposal](../../../research_examples/debenture_equity/prospective_protocol_v3.json)
uses 120/60/100 references plus 22 outcome sessions, allowing at most 74 delayed
development OOS dates. Floors/methods remain unchanged and V2 stays the default.
This is a necessary calendar condition only: both candidates still report power
not estimable, no MDE and no activation. Actual nested losses, calibration,
issuer/sector coverage, acceptance and future elapsed observations remain required.

The local [nested development loss generator](../../../research_examples/debenture_equity/development.py)
now replays canonical original development archives at causally purged rolling
cuts, tunes/refits each model pair using only available earlier labels, and joins
OOS targets after prediction. It preserves sparse issuer/date activity, hashes,
parameters and lineage; no test outcome is loaded. Its deterministic expanding
training/minimum-length rolling validation rule needs pre-outcome acceptance.
This is development diagnostic replay, not on-time forecast publication. Synthetic
checks reach the V3 best-case 74 dates with real floors; there are no qualifying
real prospective archives. Sector/issuer robustness, calibrated null/block power,
MC uncertainty and independent acceptance remain; reports grant no MDE,
activation, production authority or PIT certification.

The [conditional sensitivity simulator](../../../research_examples/debenture_equity/sensitivity.py)
now consumes canonical nested development losses, keeps the full OOS cash-session
axis including gaps, and crosses issuer draws with non-circular calendar blocks.
Independent inner tests on outer centered-null panels report conditional null
rejection and gain-grid Monte Carlo frequencies/intervals, with empty draws and
short-history block geometry exposed. This is not independent calibration of
training, source activity or the hybrid inference rule. Actual development
observations and sector/dominance/delay robustness remain required; every report
continues to refuse power/MDE acceptance, activation and PIT certification.

The development comparison now optionally adds sector controls to both model
variants using only categories learned from available, purged training labels.
Missing/unseen sectors are excluded and unchanged date floors are rechecked;
frozen feature/label sectors must agree, and controlled/uncontrolled loss scopes
cannot be mixed. Successful folds retain category and attrition counts; failed
folds give explicit reasons. This prepares a required robustness diagnostic,
without changing primary predictions, collecting classifications or establishing
real coverage. Held-out sector-controlled publication/scoring, dominance/delay/
placebo checks and independent training/activity calibration remain open.


The separately approved 40 MB 07/10 operational canary succeeded on 08/10 at
18:49:55 UTC-3: 13,806 facts / 1,534 nine-metric groups, zero drops/missing dates,
raw hash and exact persisted facts reconciled, one successful audit, exit 0 and
valid completion receipt. Credit allocation grew 14,270,464 bytes; elapsed time
141.195 seconds. Evidence and limitations are in the debenture ingestion-canary
runbook. The earlier failed audit remains visible. No schema, permanent activation,
new dataset or PIT certification; the next-day heartbeat stays paused. Recurring
weekly-window cost and the first three scheduled cash sessions remain unverified.
