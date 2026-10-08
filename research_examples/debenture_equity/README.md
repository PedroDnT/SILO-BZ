# Debenture → issuer → equity: audit and offline experiment

This is the first executable gate of the [experiment plan](../../docs/reference/research/debenture-equity-experiment.md).
It reads existing data only. There is no ingest, database connection, migration,
API, daily enablement, paid service, or automatic mapping acceptance here.

From the repository root:

```sh
.venv/bin/python research_examples/debenture_equity/audit.py \
  --capture-id f7d46926-0349-4d54-a198-ffbad8045065
```

Execute the printed **SELECT** with the Supabase MCP for project
`zcjbtpxuhdekpwcxmepn`. Save the returned `audit` JSON object, without the MCP
wrapper, to an ignored local path. Then:

```sh
.venv/bin/python research_examples/debenture_equity/audit.py \
  --input .context/debenture-equity-audit.json
```

Redirect stdout to an ignored Markdown file if desired. Never commit the full
candidate export or raw market data. The SQL is bounded to a single capture and
its requested date window for COTAHIST and the instrument registry. Company/FCA
aliases use stored vintages to find candidates, **not** to infer historic knowledge.
The query can return many candidates; preserve the complete JSON without tool
output truncation. It returns no raw CSV or sensitive contact metadata.

The report reconciles counts and checks payload hash, complete status, drops,
source consistency and requested/known-session delivery. It distinguishes
registered equities from positive raw cash closes. A quoted equity is not proof
of adjusted-return coverage, current listing status, issuer identity or PIT.
The result is deliberately capped at PARTIALLY READY for this first gate, even
if every bond has a unique name candidate. Definitive dated mappings and the
later experiment gates are outside this audit's certification scope.

Names are normalized by uppercasing, translating the listed Portuguese accents,
and removing non-alphanumeric characters. No fuzzy matching, ISIN-prefix join,
CNPJ-root collapse, parent substitution, or guessed ticker is performed.
Legal names, FCA `Nome_Empresarial`, company `DENOM_COMERC`, COTAHIST short names
and registry institution names all retain their source in each candidate.
One bond can have zero, one or several candidates. An issuer need not have equity.

## Bounded existing-data export and recovery proposal

The reviewed sample now contains 26 documentary **original-issuer** links in
`reviewed_links.json`. Their retrospective validity assumes no intervening transfer;
they do not certify original-date knowledge or the full candidate universe.
`protocol.json` freezes the method and chronological splits. This three-month
pilot cannot meet its confirmatory date/issuer floors even after recovery.

Print a read-only export using existing total-return API functions and stored credit.
This example selects the initial six-link subset; pass every reviewed bond and its
FCA equity candidates to reproduce the full sample documented in the plan:

```sh
.venv/bin/python -m research_examples.debenture_equity.prepare \
  --bonds ALPA13 ALUP18 ANIM18 ASAI18 BSA318 BRKMA6 \
  --tickers ALPA3 ALPA4 ALUP11 ANIM3 ASAI3 B3SA3 BRKM3 BRKM5 BRKM6
```

Execute the printed SELECT through Supabase MCP. Save only its `bundle` object
locally, without truncation. Credit capture censuses validate both all stored groups
and the selected export scope. Never commit the bundle or raw source data.

The export includes FCA negotiation/listing start and end dates. The runner uses
the latest reference/version per full CNPJ and ticker as of each signal date,
then retains all listing rows in that filing and respects both recorded intervals
(inclusive endpoints). Segment changes may legitimately close one row and open
another within the same filing. An older open record cannot
override a newer closure. Missing interval dates and tickers removed entirely from
a later filing remain unproven: this bounded export is not a full FCA snapshot
absence audit, and reference dates do not prove publication-time availability.
Older local bundles must be exported again to include these date fields.

```sh
.venv/bin/python -m research_examples.debenture_equity.prepare \
  --plan-bundle .context/debenture-equity-bundle.json
```

This prints nonoverlapping missing-session slices, an explicitly conditional storage
scenario and the optimistic date ceiling after label purges. It never executes
ingest or authorizes production access. The [plan](../../docs/reference/research/debenture-equity-experiment.md)
records the concrete proposed recovery and its approval/stop conditions.

## Offline experiment

```sh
.venv/bin/python -m research_examples.debenture_equity.experiment \
  --bundle .context/debenture-equity-bundle.json \
  --links research_examples/debenture_equity/reviewed_links.json \
  --out-dir .context/debenture-equity-strict
```

Default `strict_pit` refuses an end-to-end historical claim from current equity/index
revisions. Add `--mode retrospective` for the explicitly retrospective pilot. Output
is local `result.json` plus `issuer_panel.csv`; no database/network access occurs.
The result includes protocol, bundle and identity fingerprints and exclusion counts.
One issuer/date/horizon is one outcome; absent trades are never imputed as zero.
PU changes and rates remain excluded. Missing history, sample floors or sector
robustness prevent a favorable overall research verdict. No tradability is certified.

Sector robustness reads existing `b3_index_portfolio` classifications for the exact
ticker/signal date, observed by that date's end in Brasília and before export.
There is no historical fill or inference from today's company sector. Conflicting
index labels refuse evaluation. Categories come only from purged training rows;
unknown validation/test sectors are excluded and counted. The same sector controls
enter both models; placebos shuffle whole credit vectors within date and sector.
The original and delayed studies must both pass sector robustness as well as the
uncontrolled checks before an incremental-evidence verdict. Missing history or fewer
than two training sectors gives an inconclusive result, with coverage reported.

Focused checks:

```sh
.venv/bin/python -m pytest tests/test_debenture_equity_audit.py tests/test_debenture_equity_experiment.py -q
```

## Unactivated prospective design

[prospective-design.md](prospective-design.md) and
[prospective_protocol.json](prospective_protocol.json) preserve the longer calendar
candidate, information/label cutoff rules, immutable inputs, development-only
power grid and completion audit. These are design artifacts, not an implemented
collector, an input accepted by the pilot CLI, production approval or evidence of
strict PIT. The original `protocol.json` and its results stay unchanged.

## Private local retention helper

`snapshots.py` archives **already fetched** input files, without network, credentials
or database access. Supply a request JSON with `signal_date`, `cutoff_at`,
`protocol_sha256`, `links_sha256` and exactly the seven component names listed in
`prospective_protocol.json`. Each component receipt contains `path`, byte-level
`sha256`, `source_observed_at`, `read_started_at` and `read_finished_at`. All
timestamps need a timezone. These receipts must come from actual collection; the
helper cannot independently authenticate their source or content semantics.

```sh
.venv/bin/python -m research_examples.debenture_equity.snapshots \
  --request .context/snapshot-request.json --out-dir .context/new-snapshot
.venv/bin/python -m research_examples.debenture_equity.snapshots \
  --verify .context/new-snapshot
```

The destination must be new and its parent must exist. The helper checks hashes,
receipt ordering and the actual local clock, then writes private files with a
100,000,000-byte component budget by default. Manifest overhead is additional.
It fsyncs components, manifest and a staged readiness receipt, then atomically
publishes the receipt with an exclusive hard link. Verification also checks the
original filesystem inode-change time of that publication; crossing
the cutoff leaves partial diagnostic files and refuses readiness. It never
overwrites or automatically deletes them. Verification rejects changed manifests
or components, component symlinks and late/incomplete archives. It does not use
filesystem modification time to invent an earlier observation.

A successful report says `retention_verified=true`, **strict_pit_certified=false**.
Local clocks/caller receipts are attestations, not trusted external timestamps.
Kernel inode-change time must be consistent with the archive clock/cutoff; an
unsupported or inconsistent filesystem refuses verification. Copying/restoring
the readiness receipt after cutoff changes that evidence and cannot establish
timely original publication; such copies need separate provenance, not this
helper's certification. Keep the original archive unchanged.
The helper does not validate the next cash session, full source coverage, identity
changes, return conventions, financial payloads or predictive models. The
collector and prospective evaluator remain required, and a local archive is not
a durable production-retention policy. Do not create a retrospective manifest
that labels October retrieval as July knowledge. No canary has been run.

## Separate frozen features and realized outcomes

`experiment.build_features(bundle, links, protocol)` now calculates one row per
issuer/date without requiring future return observations. It retains the chosen
share class, equity ISIN/revision, alpha, beta and input features.
`experiment.attach_outcomes(features, label_bundle, protocol)` attaches realized
returns using coherent entry/exit levels from the label bundle. It never
reselects the share class or recalculates frozen features, alpha or beta. It
refuses duplicate issuer/date features and mixed label revisions, and excludes
a ticker whose label ISIN differs from the frozen equity identity. Label inputs
need equities/benchmark/calendar/return basis/export timestamp, not credit, FCA
or volume. Output retains both feature and label equity revision identifiers.

The existing `build_panel` composes these functions for the retrospective pilot.
Its 26-issuer result and every prior column of all 935 panel rows were compared
before/after and are unchanged; `equity_isin` and `label_equity_revision` are
additional provenance columns. Strict historical PIT still yields no outcomes.
These are financial calculation boundaries, not a completed prospective evaluator:
archive integration, verified next-session calendars, actual label availability,
identity-transfer and source/convention acceptance remain required. Neither
function establishes a label's knowledge time from its reference date. The current
IBOV response has no revision identifier; benchmark-vintage coherence still needs
the exact retained response/partition evidence and independent convention review.

## Archived cutoff-input replay

`prospective.py` now integrates the local archive with one-cutoff financial input
replay. It reads only the exact bytes returned by archive verification; no
network, database connection, capture or scheduling occurs.

```sh
.venv/bin/python -m research_examples.debenture_equity.prospective \
  --archive .context/new-snapshot
```

The external `--protocol` defaults to `prospective_protocol.json`; both the
embedded candidate and manifest must match it. An archive cannot choose a
different method merely by changing its own hashes. Input component JSON must
have these contracts, in addition to the real collection receipts:

| Component | Payload contract |
| --- | --- |
| Calendar | `sessions` ordered/unique ISO cash dates, including D and its next session; `source_url` and `observed_at` |
| Credit | `selected_bonds`, `captures`, `credit_census`, `credit`, `audits`; every capture includes full `raw_csv`, UTF-8 hash, requested/delivered/expected dates and parser counts; audit has capture ID, status, acknowledged row count and `finished_at` |
| Equity | `equities`, `return_basis`, `exported_at`; exact quote response through D with actual timestamp-valued `data_revision` |
| IBOV | `benchmark`, `benchmark_code`, `return_basis`, `exported_at`; retained exact response covering verified sessions through D |
| FCA/identity | `fca`, `links`, `filing_census`; each full-company filing census records CNPJ/reference/version/document ID, `fetched_at`, `complete`, `equity_rows`, `equity_rows_sha256` (semantic fingerprint of all its equity/listing records, including inactive records) |
| Sector | `sectors` with exact ticker/reference date/sector and `fetched_at` |
| Frozen model/features | `protocol` and the exact `features` records calculated before archival; this replay does not fit or certify a model |

`compute_features` prepares the frozen records from already fetched payloads.
`replay_archive` checks them again after archival. Both compare every selected
credit fact against a fresh parse of the retained full CSV, including Decimal
values, units and source-row hashes. Counts alone cannot clear this check. Preserve
credit values as decimal strings or exact JSON decimals when exporting; do not
round-trip source NUMERIC through JavaScript floating-point numbers. The archived
credit JSON is decoded with Decimal precision.

The replay enforces the verified next-session 10:00 Brasília cutoff, receipt
availability, no future feature dates/revisions and full benchmark-calendar
coverage. FCA selection uses the latest complete **company filing**, including a
new filing with zero equity rows, so a removed ticker cannot survive through its
older per-ticker record. Full-filing row counts/hashes and tied/orphan filings are
checked. Those census completeness assertions still require actual full-filing
source evidence; a name candidate or filtered ticker export cannot supply them.
Sectors use observations for exactly D, available by the next-session cutoff;
there is no historical filling. Replayed feature records must match the frozen
manifest exactly.

A successful report says `input_consistency_checked=true`, while
`strict_pit_certified=false`. Calendar/FCA completeness and caller receipts remain
attestations; dated transfers, independent source/convention acceptance, actual
prediction/label availability and durable retention remain outstanding. The
current historical export lacks raw CSV and full-filing censuses and is **not**
this input format. Do not repackage October retrieval as July knowledge. This
module supplies no predictive result and no new production authorization.

## Archived realized-outcome replay

`outcomes.py` links one explicit outcome archive to the exact verified input
manifest and external protocol. It uses frozen features, stock class/ISIN,
alpha and beta. The outcome archive uses the same private, exclusive-creation
retention helper, with schema 2, `kind="outcome"`, the original `signal_date`,
protocol/link hashes and `outcome={horizon, entry_delay_sessions,
input_manifest_sha256}`. Its three components are:

| Component | Payload contract |
| --- | --- |
| `verified_cash_calendar` | Same dated/source contract as inputs; preserves the entire frozen calendar prefix and establishes entry, exit and first session after exit |
| `realized_return_response` | `equities`, `benchmark`, `return_basis`, `benchmark_code`, `exported_at`; one coherent equity revision per ticker, one retained benchmark response, exactly signal-through-exit dates |
| `frozen_feature_reference` | Exactly `{input_manifest_sha256}` referencing the verified original input manifest |

Supply these already fetched files to `snapshots --request ... --out-dir ...`.
All source/read receipts and actual publication must meet the next-after-exit
10:00 Brasília deadline. Collection of the realized response and publication
must also occur **on that first post-exit cash session**; future-dated price rows
cannot authorize early labeling. A verified exchange-close schedule is not
assumed. Late archives fail this on-time path and cannot replace the original.

```sh
.venv/bin/python -m research_examples.debenture_equity.outcomes \
  --input-archive .context/new-snapshot \
  --outcome-archive .context/new-outcome \
  --as-of '2026-10-15T10:00:00-03:00'
```

The timestamp above is syntax only, not an approved capture date. `--as-of` is
the requested fit's information cutoff. Replay refuses labels published after
it, retains the actual original-filesystem publication as `label_available_at`,
and adds input/label manifest and realized-response hashes. Missing prices or
changed equity ISIN are counted as exclusions. A wrong calendar, mixed equity
revisions or mismatched parent archive fails. The exact input bytes are read
once, verified, and reused for feature replay and label linkage.

This verifies one caller-selected archive, **not which archive was first**.
The canonical selector below supplies scoped first-version exclusivity; accepted
pre-outcome pinning, late-label/revision sensitivity selection,
training/validation availability integration and actual frozen predictions remain
required. Source completeness, benchmark vintage and financial conventions
also remain independent acceptance gates. No network, production write,
schedule, predictive conclusion or strict-PIT certification is added.

## Canonical original-outcome selection

`originals.py` makes original selection exclusive inside one externally pinned
scope. Use the first accepted **input archive itself** as the registry root;
its immutable manifest/components are preserved and no duplicate input snapshot
is created. Record its manifest hash in the accepted run design **before any
outcomes are observed**. That acceptance is not established by the helper.

```sh
.venv/bin/python -m research_examples.debenture_equity.originals \
  --registry .context/first-input --registry-sha256 "$REGISTRY_SHA256" \
  --input-archive .context/first-input archive --request .context/outcome-request.json

.venv/bin/python -m research_examples.debenture_equity.originals \
  --registry .context/first-input --registry-sha256 "$REGISTRY_SHA256" \
  --input-archive .context/first-input verify --horizon 5 --delay 1 \
  --as-of '2026-10-15T10:00:00-03:00'
```

The dates are syntax examples, not production approval. Subsequent signal inputs
must share the externally pinned protocol/link universe, have publication no
earlier than the root and signal dates no earlier than its first signal. Another
archive for that first signal is refused. A different root hash is refused.

For each `(signal_date, horizon, entry_delay_sessions)` there is one canonical
child directory. `archive` uses the existing retention helper's exclusive mkdir,
hash/clock/deadline and byte-budget checks. Once a slot is created, a second
attempt fails even if the first write was partial or its financial replay failed.
Preflight failures before mkdir do not reserve a slot. Correcting a source file
cannot replace reserved original bytes. Inspect failures and report missing
labels rather than silently switching to a new revision. `verify` loads only
that canonical slot, checks its exact input binding and context, and preserves
the actual archive publication as label availability. It does not search other
directories for a convenient alternative. Output includes the registry hash.

This establishes exclusive original selection **within the pinned scope**, not
global proof that no earlier source/archive exists. Future prediction/fitting
integration must use the pinned root and exact prediction-bound input hashes;
it must not select alternative feature archives after observing outcomes. Late
outcomes, missing-label reports and separately frozen revision sensitivity are
still pending. No collector, production retention policy, model acceptance,
financial convention acceptance or strict-PIT certification is supplied.

## Availability-aware first-test model preparation

`fitting.fit_originals(registry_path, prediction_input, development_inputs,
registry_sha256=..., horizon=..., delay=..., candidate=None)` prepares the two
ridge models and first-test feature predictions from verified archives. It has
no fetch, database access, publication or activation side effect. The external
candidate defaults through input replay to `prospective_protocol.json`.

The first test signal is fixed at the registry calendar's first signal plus
90 training and 50 validation reference sessions. The prediction archive must
establish that signal and its next-session cutoff. Its calendar must preserve
the root's frozen prefix. The bounded development inventory accepts at most
140 unique earlier signal inputs with the same protocol/link scope. Missing
and omitted original slots are counted; invalid reserved originals fail rather
than being replaced. Original publication after the fit cutoff is excluded
before decoding its outcome through replay. No test outcome is requested.

For tuning, training outcomes must exit before the first validation signal and
be available by its next-session 10:00 cutoff. Validation outcomes must exit
before the fixed first test signal and be available at the fit cutoff. Both
original date floors remain, measured after purging. Each ridge penalty is
chosen on validation using training-only centering/scaling. The final model
refits on eligible development labels available at the first test cutoff, with
exit strictly before the first test signal. Predictions use the frozen current
feature vector; future test targets cannot enter tuning, fitting or scaling.

Output retains feature names, ridge penalties, centers, scales and coefficients,
the prediction input/registry hashes, and separate training, validation and final
fit lineage with exact input/label hashes and actual label availability. This
initialization accepts only the **first test signal**; it supplies no silently
expanding test-label refit. The separate arithmetic `fit_available_pair` boundary
also rejects test labels, duplicate issuer/dates and mixed horizons/delays/scopes.

The offline candidate can be prepared after the recorded cutoff. That does not
prove a timely forecast: atomic model/prediction publication before entry,
prediction-bound input reuse on later signals, accepted development inventory
completeness, sector robustness, power and independent source/financial/PIT gates
remain required. Tests use a clearly separate short synthetic design for archive
integration; the real 90/50/100 design and inference floors are unchanged. There
is no new empirical result or production authorization.

## Local prediction publication and fixed-model reuse

`predictions.py` adds private, deadline-bound publication using the existing
retention helper. This is **local candidate evidence, not experiment activation**.
All functions require the externally pinned root hash, horizon/delay and accepted
input archives; no network, database, collector or schedule is added.

- `publish_first(root, input_path, development_inputs, registry_sha256=...,
  horizon=..., delay=..., candidate=None)` computes the original fit internally
  and publishes its models, exact predictions, training/validation/final-fit
  lineage and fit report. It cannot publish an arbitrarily supplied model.
- `verify_first(..., as_of=...)` verifies actual availability and reproduces the
  entire original payload from the same ordered development inventory. Changed
  models, predictions, lineage or inventory are refused.
- `publish_reuse(root, input_path, initial_input, development_inputs, ...)`
  audits that first fit, then uses the **stored original** centers/scales and
  coefficients for a later signal. No test outcome is used for fitting.
- `verify_reuse(..., as_of=...)` reproduces the later predictions and checks the
  exact original model hash, input binding, calendar interval and availability.

Predictions use schema 3, `kind="prediction"`, with two hashed components:
`frozen_feature_reference` and `frozen_model_prediction`. The context records the
input/registry hashes, horizon/delay and initial-model manifest hash (null only
for the first model's own receipt). The first model is itself the canonical
first-test prediction receipt. Later signals must preserve its calendar prefix
and remain inside the fixed untouched-test reference interval. Original fitting
replay is a bounded audit of development originals, not a new fit on test data.

Computation must begin after the input was published and finish before its
10:00 Brasília cutoff. Both computation crossing that deadline and starting late
fail. Initial-model publication must precede reuse computation. Actual receipt
publication uses the existing staged/fsynced readiness mechanism and is checked
against requested `as_of`. Each signal/horizon/delay has an exclusive canonical
prediction directory and private staging sibling; neither is overwritten. Failed
staging remains diagnostic evidence. The byte budget covers archive components;
staging retains another copy and filesystem/manifest overhead, so this is not a
total production storage allowance.

The report retains `strict_pit_certified=false`. Actual exchange entry-close
evidence, accepted pre-outcome scope/inventory and power gate, sector robustness,
missing/late/revision sensitivity, source/financial conventions, collector
integration and durable production retention remain required. The mechanism
never backdates a publication and cannot turn a later historical replay into an
on-time forecast. Exact replay also requires a compatible frozen implementation
and numerical runtime. No empirical predictability or trading claim follows.

## Necessary development-power date audit

```sh
.venv/bin/python -m research_examples.debenture_equity.power
.venv/bin/python -m research_examples.debenture_equity.power \
  --protocol research_examples/debenture_equity/prospective_protocol_v3.json
```

This checks only the optimistic nested-OOS calendar ceiling. With `N` development
references, `T`/`V` training/validation date floors and `g=horizon+entry_delay`,
strict train→validation→OOS→test exit purges leave at most `N-T-V-3g` dates.
No pre-study credit training signals or missing coverage are assumed. Independent
tests enumerate all feasible fold/split positions instead of repeating that formula.

V2's 140 development references supply at most **34** delayed horizon-20 dates,
below the unchanged **60** floor; primary horizon 20 permits only 37. It is a
structural no-go for this power gate. A minimum of 166 perfect-coverage references
is necessary across all scenarios. The separate unactivated V3 proposal uses
120/60 development references (180 total), giving an optimistic worst-case **74**.
Its method, inference/identity/power floors and labels are unchanged. V2 remains
intact and the default; no helper silently adopts V3 or relabels existing roots.

The checker returns `power_status=not_estimable`, `minimum_detectable_gain=null`
and `test_activation_allowed=false` for **both** candidates. Passing a necessary
date ceiling supplies no loss series, calibration or power estimate. Nested
development observations, issuer/sector coverage, dependence/null calibration,
Monte Carlo uncertainty and owner acceptance remain required. See the versioned
[design audit](prospective-design.md#structural-date-audit-and-longer-candidate).
The V3 302-session storage scenario is about 1.892 GB before snapshots/staging,
WAL/backups or source variation; it grants no capture or storage authorization.

## Nested development loss preparation

`development.nested_original_losses(root, boundary_input, development_inputs,
registry_sha256=..., horizon=..., delay=..., candidate=...)` replays canonical
original labels and frozen features using the first-test input's fixed boundary.
It returns an issuer/date loss frame and a diagnostic report. No test outcome is
loaded, no network or file write occurs, and missing/omitted archives are counted.
The pure `nested_losses` interface expects already verified tables; it alone
cannot authenticate archival provenance or completeness.

Each development OOS signal uses expanding training and a rolling validation
reference window equal to the validation date floor, with exit-before-split and
actual-label-availability purges. Ridge tuning and scaling stay inside each fold.
Targets are joined only after prediction. Outputs retain original input/label
hashes, paired squared losses, per-fold parameters and fit lineage; sparse activity
is preserved. This diagnostic does not claim timely publication of nested
predictions. Accept its fold rule and implementation before inspecting outcomes.

Both interfaces always report `not_estimable`, no MDE, no test activation and no
PIT certification. Real qualifying prospective inputs, sector/issuer robustness,
calibrated null/block resampling and MC uncertainty remain required. See the
[development design](prospective-design.md#nested-development-losses).

## Conditional null/block sensitivity diagnostic

```sh
.venv/bin/python -m research_examples.debenture_equity.sensitivity \
  --registry .context/accepted-first-input \
  --registry-sha256 EXTERNALLY_PINNED_MANIFEST_SHA256 \
  --boundary-input .context/first-test-input \
  --development-input .context/development-input-1 \
  --development-input .context/development-input-2 \
  --horizon 5 --delay 1 \
  --protocol research_examples/debenture_equity/prospective_protocol_v3.json
```

These are placeholders for an accepted root and the complete development input
inventory, not existing qualifying archives. Repeat `--development-input` for the
inventory; omissions/missing slots are counted. No data is fetched or written,
and no test label is read. Numeric/table users can call `conditional_sensitivity`
only with independently verified nested losses/report; raw tables alone do not
authenticate original provenance or completeness.

The full possible OOS cash-calendar interval is retained, including sessions with
no observations. Whole-issuer draws cross non-circular 20/40-session blocks on
that calendar. Outer centered-null panels receive independent inner centered
bootstrap tests; all predeclared mean shifts share each inner bank. Output reports
conditional rejection frequencies/95% Wilson MC intervals, null diagnostics,
missing cells, block geometry and empty/incomplete draws without redrawing them.
The real design uses 1,000 outer and 1,000 inner draws per block/horizon/delay.

This is conditional simulation, not calibrated learning power. Sector/dominance/
delay robustness, training/selection/source-activity calibration and actual
prospective data remain required. All results keep `not_estimable`, no MDE,
no activation and no PIT certification. A favorable hypothetical grid point
cannot clear those gates. See the [numerical design and limits](prospective-design.md#conditional-loss-test-simulation).

Add `--sector-controls` to run the development robustness comparison. Each fold
learns categories only from available purged training labels, requires at least
two sectors and adds identical training-derived controls to both models. Missing
or unseen sectors are excluded; date floors are checked again after filtering.
Reports retain category lists and missing/unseen row counts on successful folds,
with explicit reasons for failed folds. Loss rows/reports identify the mode,
and mixed controlled/uncontrolled losses are refused by the conditional diagnostic.
The underlying protocol/default primary comparison and production remain unchanged.
Real dated-sector coverage, held-out sector-controlled prediction/scoring,
dominance/delay/placebos and independent calibration remain required; no acceptance
is granted by this option. See the [causal sector design](prospective-design.md#causal-sector-controlled-development-comparison).
