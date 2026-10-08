# Prospective experiment: unactivated design candidate

Prepared 2026-10-08 (UTC-3). This is preparation under the research plan, not
production authorization or evidence of a successful prospective experiment.
[prospective_protocol.json](prospective_protocol.json) is a separately versioned
candidate. The executed [pilot](protocol.json) and its inconclusive findings stay
unchanged. The existing runner does **not** accept this candidate or certify PIT.

## Calendar and activation

Use 90 training, 50 validation and 100 untouched-test reference cash sessions,
plus 22 outcome sessions and 126 prior equity warm-up sessions. With strict
cross-split label purges the optimistic date ceilings are:

| Entry delay | Horizon | Training | Validation | Test |
| --- | --- | --- | --- | --- |
| 1 | 1 | 88 | 48 | 100 |
| 1 | 5 | 84 | 44 | 100 |
| 1 | 20 | 69 | 29 | 100 |
| 2 | 1 | 87 | 47 | 100 |
| 2 | 5 | 83 | 43 | 100 |
| 2 | 20 | 68 | 28 | 100 |

These are upper bounds for complete daily observations, not power estimates.
The original 30/10/60 date and 20-issuer inference floors remain. At least 21
issuers must survive untouched-test eligibility so removing the dominant issuer
can still leave 20. The 26 reviewed candidates are insufficient evidence for
that gate: currently only 18 issuers contribute primary test outcomes, and dated
issuer-transfer review remains incomplete.

Freeze method, link set, eligibility/exclusion rules and source contracts before
the first accepted signal. Choose the first session only after owner acceptance
and operational readiness, with no backdating. Record splits by verified session
ordinal and resolve their civil dates from the retained calendar. Do not replace
a missing issuer with a parent or an outcome-selected candidate. Report attrition.

Before activating the untouched test, complete the development-only power gate.
The 90/50 structure may supply too few nested out-of-sample development dates.
If so, it cannot activate a confirmatory test: freeze a new longer design before
test inspection. Never extend a test until significance or lower its thresholds.

## Information cutoff and retained inputs

For signal session D, the information cutoff is 10:00 Brasília on the next
verified cash session. Primary entry is that session's close; delayed entry is
one cash session later. Missing the cutoff excludes the signal, even if a later
download contains D. A source's reference date is never its availability time.
Record actual prediction completion separately; it must precede the entry close.

Prepare immutable, private, ignored local files for the initial operational
canary. Production retention/backup location remains an owner decision; a local
file is not durable production storage. No R2/Supabase architecture change is
implied. A collector would use exclusive file creation, SHA-256 and a staged/fsynced
readiness receipt published atomically without replacing an existing file, refuse overwrites and retain rejected/late snapshots as
diagnostic evidence. Do not implement or schedule that collector under this file.

The local [retention helper](snapshots.py) now implements private, exclusive file
archival, hash/budget/clock checks and atomic readiness-marker publication for already
fetched inputs. Verification checks original-filesystem publication time even
if a crash prevents a later error marker; restored copies require separate
provenance. It makes no network or database calls and never certifies strict
PIT. The [cutoff-input replay](prospective.py) now integrates verified archive
bytes with raw-credit reparse, availability/calendar checks, company-level full
FCA filing selection and exact frozen-feature comparison. Collector integration,
independent source/convention acceptance and prediction/label evaluation remain.

The per-cutoff manifest must retain:

| Component | Required evidence and acceptance |
| --- | --- |
| Calendar | Actual ordered cash sessions, source and query completion timestamp; no invented holiday or session |
| Credit | Existing full decoded CSV/hash, capture ID, observed_at, requested/expected/delivered/missing dates, status, audit run and acknowledged facts; reconcile all groups/nine metrics before selection |
| Equity | Exact bounded quote responses covering warm-up through D, ticker/ISIN/full-CNPJ links, total-return null reasons, volume and one coherent adjustment revision per response set |
| Benchmark | Exact IBOV response, total-return convention, revision/source identifiers and divisor-step exclusions |
| FCA/identity | Relevant full filing vintages, listing/negotiation intervals, document/version and actual observation times; documentary original-issuer evidence and dated changes, including removals from later filings |
| Sector | Exact dated ticker/sector observations actually available by cutoff, without filling earlier dates or using present classifications |
| Model | Protocol/link/input hashes, cutoff, feature values, frozen alpha/beta, model parameters, label-vintage IDs used in fitting and prediction completion time |

Each component needs source-response/query-start/query-end timestamps and a hash
of the exact persisted bytes. The manifest needs both information cutoff and
publication time. All required components must be complete and persisted before
cutoff. The existing credit observed_at correctly timestamps response arrival,
but alone cannot prove that validation/upserts or a later export were ready by
cutoff. Observe a complete, reconciled snapshot and publish its manifest in time.

Partition a large read-only export if necessary, retaining each partition's
start/end/hash and verifying repeated revisions and full-scope counts. All parts
must arrive before cutoff. If a revision changes between parts, reject the set
and do not combine them. Equal counts alone do not prove equal values. Treat
full-snapshot source removals before joining selected bonds, never resurrecting
older records. There is no zero-fill for missing bond activity.

The current read API returns current revisions. Saving its exact response before
a future forecast can establish what that forecast used; it cannot reconstruct
July knowledge or establish independent correctness of adjusted returns. Keep
the existing return/benchmark convention acceptance gate, including cash events,
splits, coverage and divisor changes. Changes to raw sources after the cutoff
must not mutate that forecast's features, class selection, alpha or beta.

## Labels and model availability

Archive each realized outcome at 10:00 Brasília on the first verified cash
session after its exit. Use a single coherent equity-response revision covering
both entry and exit; similarly keep coherent benchmark endpoints. Dividing entry
and exit levels taken from differently rebased snapshots can create a false
return and is forbidden. Future realized cash events may enter the outcome, but
cannot alter the already frozen feature snapshot.

If an outcome is unavailable at that cutoff, record it as late/missing. Its
reference date cannot make it eligible for an earlier model fit. Training and
validation may use only labels actually archived before the fit's information
cutoff, in addition to calendar purges. Keep initial label bytes and hashes;
later corrected labels form a separately frozen sensitivity report. Do not
overwrite the original evaluation. This needs an implemented and reviewed
prospective evaluator; the existing strict runner deliberately refuses it.

The calculation layer now separates `build_features` from `attach_outcomes`.
Frozen features retain equity ISIN/revision and class selection; future label
vintages cannot recompute those inputs, alpha or beta. Labels use coherent
endpoints, retain their separate equity revision and reject a changed ISIN. The
retrospective composition reproduces the prior 935-row result. This is the
evaluator foundation only: archive/source/calendar/label-availability integration
and the independent financial convention gates remain incomplete. The existing
IBOV response has no revision identifier; its retained response/partition evidence
must establish the label benchmark vintage rather than an assumed revision field.

The local `outcomes.py` replay now binds one explicit on-time outcome archive to
the exact verified input manifest/protocol, preserves its features and checks the
entry/exit calendar. Realized response collection and publication must occur on
the first post-exit cash session before 10:00 Brasília; price dates alone cannot
establish availability. Actual publication time controls eligibility at the
requested fit cutoff. Output retains input/label/response hashes and the separate
equity revision. This replay alone does not select the first version; the scoped
selector below handles that boundary. Late/revision sensitivity,
availability-aware fitting and frozen predictions remain unimplemented. The
independent source/convention gates remain.

`originals.py` now supplies exclusive original selection inside an externally
pinned first-input archive. The root's manifest hash must be accepted before
outcomes. One canonical slot per signal/horizon/delay refuses replacement,
including reserved partial/invalid slots; preflight failure before mkdir does
not reserve one. Only canonical slots are loaded, with the exact input binding,
verified context and actual availability. This proves exclusivity within that
scope, not global absence of earlier archives. Prediction-bound input selection,
late/missing-label reporting, separately frozen revision sensitivity and
availability-aware fitting remain required, alongside independent acceptance.

## Development power assessment

Predeclare relative-MSE gain grid 0%, 1%, 2.5%, 5%, 10%, 20%, target power 80%,
family alpha 5% across three horizons, seed 628 and 1,000 outer repetitions.
Calibrate against nested chronological rolling-origin out-of-sample paired losses
on development data only. Every fold must train/tune on earlier available labels;
validation-tuned in-sample gains and untouched-test losses are not power inputs.
Require at least 60 development out-of-sample dates, 20 full-CNPJ issuers and
eligible sector coverage, retaining dominant-issuer/day and delayed-entry checks.

For a loss-test sensitivity diagnostic, center the development paired loss-gain
series and shift its mean by each grid fraction of development baseline MSE.
Cross-resample issuers and non-circular 20/40-session calendar blocks using the
actual observation mask. Preserve issuer sparsity, within-date dependence and
overlapping labels; do not manufacture independent rows or dense daily trading.
Report null rejection frequency, Monte Carlo uncertainty, power by grid point,
attrition, and the smallest **tested** gain meeting the power target across the
predeclared block sensitivities. Do not interpolate a precise threshold.

This diagnostic is conditional on available paired losses, not end-to-end power
of learning a real credit signal. Training/selection uncertainty and the source
activity process require calibration before accepting a sample-size conclusion.
If development coverage, null calibration or nested losses are inadequate, return
`not_estimable` without an MDE claim or test activation. The present pilot has no
qualifying development loss series, so no power number is reported. The grid is
frozen preparation; an executable power assessment remains required.

## Production request boundary

No additional production execution is requested by this candidate. The authorized
13-lot recovery is complete and B3_CREDIT_ENABLED stays off. Do not apply schema,
start another historical window, add datasets or enable recurring capture.

The next separately approvable operational step is **one future signal session**,
captured and archived before its next-session cutoff using the existing ingestor:
`python -m src.pipeline.b3_credit_pipeline --start D --end D`. D must be a verified
cash session and must be supplied as an actual ISO date in the final request.
Before asking, prepare the collector/evaluator, exact source/export queries,
input archive path, live baseline, one-session storage/elapsed-time budget,
integrity checks, abort conditions and a fresh cutoff that has not elapsed.
That canary tests readiness/latency, not predictive performance or permission to
continue for 262 sessions. Do not widen or reschedule its date without approval.

The completed recovery's peak allocation implies approximately **1.642 GB** for
262 new sessions if its average layout repeats, before input snapshots, WAL,
backups or source variation. This exceeds the completed recovery's 1 GB allowance
and is a scenario, not a bound. Measure the canary before proposing a continuing
storage allowance and production retention policy.

## Completion evidence

| Plan requirement | Current evidence | Remaining acceptance |
| --- | --- | --- |
| Existing-data audit | Executable candidate census; source tables/fields, limits and missing rates/outstanding documented | Complete audit, not a complete confirmatory dataset |
| Approved recovery | All 13 lots; hash/audit/nine-metric reconciliation; 69/69 study sessions; allocation under stop | Complete; do not repeat |
| Original issuer mapping | 26 cited original issuers, exact full CNPJ/ISIN, FCA equity candidates and source aliases | Dated changes and at least 21 eligible untouched-test issuers after attrition |
| Retrospective experiment | Offline runner, purges, fixed floors, sector/delay/placebo/dominance methods; 935 overlapping rows | Current test/sector coverage fails; no predictive conclusion |
| Longer protocol | Version 2 candidate and explicit date ceilings | Owner acceptance, real session calendar and development power gate before activation |
| Prospective PIT | Local retention, frozen-input/outcome replay and canonical original slots within an externally pinned scope | Accepted pre-outcome root pin, availability-aware fitting/frozen predictions, late/missing/revision handling, collector integration, independent acceptance, exact canary approval, successful cutoff evidence and elapsed history |
| Adjusted returns/benchmark | Existing total-return exports with coherent revision checks | Independent convention/event acceptance and frozen prospective vintages |
| Power | Predeclared development grid, dependence and failure rules | Implemented/calibrated assessment on sufficient development-only OOS losses |
| Confirmatory result | None; every current study is inconclusive | Adequate untouched history, frozen scoring and all inference/robustness gates |
| Price/rate/tradability extensions | Explicitly excluded from liquidity-first claim; ADR 0004 retained | Cash-flow/event and observed-rate conventions plus execution cost/capacity evidence before any such claim |

The offline input replay is implemented and tested, including a new empty FCA
filing removing an older equity ticker. It does not authenticate completeness
attestations or clear the independent financial/PIT acceptance gates. The historical
export lacks the required raw/full-filing evidence and cannot stand in for a new
cutoff archive.

The full plan is **not complete**. Safe local implementation/preparation remains;
production approval and future elapsed history are additional dependencies, not
reasons to label the present pilot confirmatory.
