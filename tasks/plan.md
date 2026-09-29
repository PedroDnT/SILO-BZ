# Approved dispatch plan — SILO-BZ, 2026-09-26

## Current authority and state

This section supersedes historical status and ordering below. Preserve the historical evidence and acceptance criteria; never interpret old production errors or catalog versions as current facts.

GitHub Issues are the task tracker; no tasks/todo.md is introduced. Native Codex tasks hold execution history. The Coordinator board holds bounded ownership only. Pedro approved dispatch and requested prompts whenever an action or approval is needed.

Verified: PRs #295/#306/#317 and #324/#325/#327/#330/#331 are merged; #323 is closed. #331 no longer needs marking ready. The local checkout remains divergent at 9b876b5 with staged CLAUDE.md and untracked skill/tasks changes: preserve all of them. Merged code does not prove deployed availability.

At dispatch preparation, backfill 36247755984 is in progress and daily ingest 36251044809 is pending. Inspect live state and exact run inputs before any run action. SUPABASE_ACCESS_TOKEN is absent from the repository-secret name list; do not request it unless the approved deployment path still needs it. Sentinel role/grant/credential existence is unverified.

## Owners and ordered assignments

| Owner | Issues and complete outcome | Dependencies | Estimate |
| --- | --- | --- | --- |
| Implement SILO-BZ research reliability | #296: reconcile main/local implementation, refresh issue evidence and integration state, reuse existing workers | None | 30–45 min |
| SILO-BZ data and API reliability | #297/#299: bounded read-only exact SDK/live preflight for all three research RPCs; verify deployed coverage latency after #331 | Source inspection; release approval only if required | 45–90 min |
| SILO-BZ professional research and agent… | #298/#300: reconcile missing tool/rubric changes only; #301: independently graded benchmark | Safe integration and passing live preflight before paid calls | 60–120 min plus benchmark |
| Existing Claude session `Guard CHANGELOG against dropped rows` | #332: audit merged PR #333 against the approved guard acceptance criteria; do not duplicate the implementation | PR #333 merged 2026-09-26 15:31:23Z, but audit is pending. It compares from merge-base and truncates diagnostics at 160 rather than the required 200 characters. Branch-protection proposal is preparation only; no settings change is authorized | Audit before closing #332 |
| Existing Claude session `Restore CHANGELOG rows main lost before #322` | Separate in-progress recovery of historical CHANGELOG rows; preserve this owner and do not duplicate its edits | Session is running; coordinate any shared CHANGELOG write | Existing session |
| Existing Claude session `Skip FNET date tests when date is not GNU` | Likely #206 FNET owner; finish its current date-test patch and ready-for-review PR first, then perform the bounded read-only recovery investigation | Direct handoff delivered by Pedro through Claude desktop. First check whether another session owns or already implemented sweep changes; original sweep ownership remains unverified | 30–45 min investigation after current PR |

- #332: https://github.com/PedroDnT/SILO-BZ/issues/332 (PR #333 merged; existing Claude owner is auditing remaining acceptance gaps)
- #206 FNET handoff comment: https://github.com/PedroDnT/SILO-BZ/issues/206#issuecomment-5847471077 (direct handoff delivered to likely owner `Skip FNET date tests when date is not GNU`; investigation is pending the current PR, and sweep ownership is unverified)
- #296 research map: https://github.com/PedroDnT/SILO-BZ/issues/296

## Dispatch and integration rules

The existing goal-coordination owner sends one complete bounded GOAL_ASSIGNMENT to each existing suitable worker after checking native status and claims. No duplicate coordinator or new durable task is needed. Workers claim exact paths before substantial writes and retain the same primary checkout/current branch. Initial investigation is read-only. Establish safe integration of the divergent checkout before code edits; no destructive Git operation or overwrite of foreign changes. Serialize shared generated contract, workflow, and changelog writes.

Pedro directly handed #332 to the existing Claude session `Guard CHANGELOG against dropped rows`; PR #333 is merged, but merge is not acceptance. Its current implementation uses merge-base rather than the approved `origin/main` tip and truncates at 160 characters rather than 200, so the acceptance audit remains pending. A branch-protection/required-check proposal is being prepared; no repository settings change is authorized. The separate session `Restore CHANGELOG rows main lost before #322` is already running; preserve its ownership. Pedro directly handed the #206 FNET investigation to the existing `Skip FNET date tests when date is not GNU` session as the likely owner. That session must finish its current date-test patch and ready-for-review PR before beginning a read-only #206 investigation. It must first check whether another session owns or already implemented the sweep changes; the original sweep ownership remains unverified. No duplicate worker or production/run action is authorized.

The changelog issue specifies exact origin/main/HEAD row preservation, at most five missing rows truncated to 200 characters, a nonempty branch-only Changelog-removes trailer, PR-base/merge-result CI comparison, missing-base handling, scratch-repo tests, mutation verification, documentation, and ready-for-review PR. No-changelog alone permits no deletion. CI helps only when completed before merge; no branch protection claim.

FNET investigation performs no dispatch/cancellation/scheduling. If main lacks durable resume/FIDC priority/bounded daily work/terminal cleanup, prepare a small design with storage and compatibility implications. Consequential schema choices return to Pedro before implementation. Do not repeat merged restatement API work.

## Verification checkpoints

- [ ] Issues #297–#301 have current owner, evidence, dependency, and next action; no closure solely from a merged PR.
- [ ] Research RPCs pass bounded exact SDK calls with grants/response/row-cap checks, or failures have reproducible release blockers.
- [ ] Missing harness/rubric behavior is reconciled with current main; focused tests, SQL/OpenAPI parity and full offline pytest pass at the integrated commit.
- [ ] Paid evaluation uses a passing preflight less than six hours old for the same API and stays inside cumulative US$20. Runtime case input contains only the professional question.
- [ ] All three limitation cases pass; at least eight of nine answerable cases pass; three flagship cases succeed twice with independently verified arithmetic and citations. Availability, accuracy, usefulness, latency and cost are separate.
- [ ] Changelog guard has deny/escape/mutation evidence, full offline suite and applicable PR CI; PR ready for review.
- [ ] FNET run scope/queue/failures are established; production inputs approved separately and post-run linkage/throughput/query measurements reported.

## Pedro action and approval gates

| Action | Trigger and preparation required | Time |
| --- | --- | --- |
| Review FNET recovery investigation for #206 | Likely owner first completes the GNU-date PR, then reports whether another session owns or implemented sweep changes | 30–45 min |
| Review #332 guard audit / branch-protection proposal | Existing Claude owner provides the acceptance audit and concrete proposal; no settings change until separately authorized | 5–10 min |
| Sentinel role/credential creation | Agent first checks existence/script/grants; prepare private operator steps. Re-running the script rotates the password, so never rerun only to verify | 5–10 min |
| SUPABASE_ACCESS_TOKEN private setup | Only if an approved MCP deployment path still requires the absent secret | About 5 min |
| Review and merge PRs / approve production actions | Concrete PR diff/checks, or exact migration/deploy/run inputs and recovery steps, are ready | 5–10 min |
| Extra restatement-diff backfill | Only after linkage sweep re-measurement, with exact inputs and queue check | About 2 min |

Prompt Pedro at the actual gate with what/why, exact PR/page/private terminal step, time, and what it unblocks. Prepare all authorized work first. Never expose secrets. Preserve previous approvals; do not request them again. Do not deploy, mutate production, or start backfills under dispatch authority. No new Routine/heartbeat is created; no unverified claim that external Claude routines were cancelled.

---

# Historical research plan and retained acceptance criteria

## Outcome

Make the research-agent benchmark measure whether an agent can answer useful
professional questions from SILO, instead of measuring whether an unpublished
endpoint or a weak tool wrapper fails. Keep database/source facts, API exposure,
agent behavior, and grading as separate failure categories.

## Evidence and current baseline

- The latest live evaluation record contains 12 cases: 11 returned an answer and
  one hit `MaxTurnsExceeded`. “Completed” is a run status, not a rubric pass;
  numeric and analytical review remains necessary.
- The SDK methods for FII property history and Focus expectations call their
  expected RPC names and parameters, but bounded live calls returned PostgREST
  `PGRST202`. The production schema cache does not expose those functions even
  though this branch defines them in `src/store/analytical/19_api_contract.sql`.
- Agent events contain repeated argument `TypeError`s. The evaluation adapter
  offers generic JSON arguments and strips underlying error detail before
  returning it to the model, making recovery difficult.
- A direct anonymous `coverage` read returned 24 rows in 2.132 seconds under a
  three-second client timeout. Treat the earlier timeout as transient unless it
  is reproduced by the preflight.
- Therefore the first diagnosis is a production API rollout gap plus a weak
  agent-tool contract. The current evidence does not justify redesigning the
  underlying relational schema.

## Handoff snapshot — 2026-09-25

### Parallel task threads

| Task thread | State | Handoff |
| --- | --- | --- |
| `SILO-BZ data and API reliability` | Active | PR #295's SQL-apply and offline pytest checks passed at commit `6b2a077`; current `main` has advanced and the PR now conflicts. |
| `Implement SILO-BZ research reliability` | Idle | Production probes found `PGRST202` for the FII-property and Focus RPCs. This is an API deployment/schema-cache gap, not evidence of a bad relational model. |
| `SILO-BZ professional research and agent…` | Idle | Research ranking, 12-case baseline, and evaluator-private references exist. The baseline has not established answer quality for answerable cases. |

### What is done

- PR #295 publishes the CIA filing-history, FII property-history, and BCB
  Focus-expectations endpoints through SQL, catalog/coverage, SDK, OpenAPI,
  docs, and MCP contract. Its manual workflow supports a SQL-only dispatch.
- The PR event now triggers Actions. On `6b2a077`, ephemeral PostgreSQL
  schema/migration/analytical SQL apply and offline pytest both passed; the
  read-only API smoke job was skipped by design. A separate macOS local smoke
  then applied the current schema/migrations and analytical SQL in an isolated
  PostgreSQL instance; `/v1/catalog`, `/v1/tools`, and `/v1/coverage` returned
  200, while `/v1/quotes/NOPE9` returned the expected 404.
- A local follow-up commit `9b876b5` adds schema-aware research-agent tools,
  bounded error reporting, baseline grading, and tests. It is on the local
  `codex/research-quality` checkout, not on PR #295's remote head.
- The independent baseline grade reports 2/12 full rubric passes (L1 and L3)
  and 0/9 answerable cases verified as full passes. Live API availability and
  numeric answer accuracy remain separate gates.

### What changed after those checks

- PR #295 is open at `6b2a077`; its checks are green, but it is now
  `CONFLICTING` with `main` at `b92f86d` after the balance-sheet/cash-flow API
  merge. A fresh merge preview reports conflicts in `serve/catalog.py`,
  `src/store/analytical/19_api_contract.sql`,
  `supabase/functions/silo-mcp/tools.ts`, and
  `tests/test_api_contract_sql.py`.
- `main` now owns catalog version 35. Reconcile the catalog version and RPC
  counts from both sides after merging; do not carry forward stale version/count
  text from the 2026-09-23 snapshots.
- A separate remote `feat/company-financials-label` branch at `6ee151c` already
  proposes catalog v36. Check whether it is still active and coordinate the
  next version assignment before resolving the catalog conflict; do not assume
  v36 is free.
- PR #306 also conflicts with `main` and updates agent/MCP documentation. Check
  its deployed-MCP claims against current live evidence before combining docs;
  do not infer deployment from a code merge.
- The root checkout is on local `codex/research-quality` at `9b876b5`, one local
  commit ahead and 59 commits behind its tracking branch, with a modified
  `CLAUDE.md` and untracked `.claude/skills/fix-register/` and `tasks/` content.
  Preserve those user changes. Do not push this checkout or force-update a
  branch from it; port the intended `9b876b5` work into an isolated checkout
  after reviewing overlap with PR #295 and #306.
- The six tracker issues #296–#301 remain open. The PR success is an integration
  checkpoint for its tested SHA, not completion of production release or the
  research benchmark.

## Architecture and sequencing decisions

1. Reconcile the committed SQL, grants, catalog version, OpenAPI, SDK, and docs
   before changing schema design. The production PGRST202 must be resolved at
   the deployed PostgREST/API layer.
2. Establish deterministic local and read-only live contract checks before
   spending on another agent run. A failed required preflight stops the paid
   benchmark and records an availability failure.
3. Give the model machine-readable endpoint arguments and safe actionable API
   errors while preserving discovery-first behavior. Case-specific runtime
   input remains the professional question only; datasets, joins, and reference
   answers remain evaluator-private.
4. Grade completed answers independently. Keep technical failures separate
   from numeric, citation, limitation, and professional-usefulness scores.
5. Production migrations, schema-cache refresh, deployment, and backfills are
   separate release actions and require explicit release authorization. This
   plan prepares and verifies them; it does not authorize production changes.

## Task list

Tasks are tracked in GitHub Issues per repository policy. [Issue #296 is the
map](https://github.com/PedroDnT/SILO-BZ/issues/296); the ordered children
are:

1. [#297 Reconcile research RPCs with production PostgREST](https://github.com/PedroDnT/SILO-BZ/issues/297)
2. [#299 Add deterministic live-contract preflight](https://github.com/PedroDnT/SILO-BZ/issues/299)
3. [#298 Make research-agent API tools schema-aware](https://github.com/PedroDnT/SILO-BZ/issues/298)
4. [#300 Harden the discovery-first benchmark rubric](https://github.com/PedroDnT/SILO-BZ/issues/300)
5. [#301 Rerun and independently grade the 12-case benchmark](https://github.com/PedroDnT/SILO-BZ/issues/301)

The local Postgres contract work in #299 may proceed while #297 prepares the
release package. The live part of #299 and #301 wait for authorized API release
and successful post-release probes. #298 can proceed against the committed
OpenAPI/SDK contract, then #300 uses the stabilized tool/error behavior.

Current status: #297 remains blocked on release/deployment evidence; #298 and
#300 have implementation work in local commit `9b876b5` that still needs safe
integration and CI; #299's deterministic local checks are part of the PR CI,
but its live post-release checks are outstanding; #301 has a graded baseline,
but the final rerun and acceptance thresholds remain outstanding. Keep all
tracker issues open until their acceptance criteria are independently met.

### Handoff sequence

1. In an isolated checkout, reconcile PR #295 against current `main` (`b92f86d`),
   resolve the four reported conflicts, and account for the balance-sheet and
   cash-flow RPCs. Coordinate catalog numbering with
   `feat/company-financials-label` and review how to port `9b876b5` and combine
   docs from PR #306 before committing.
2. Refresh the API inventory, RPC counts/version, research reliability snapshot,
   and MCP/agent deployment wording from the final merged SQL, grants, catalog,
   OpenAPI, SDK, CI, and live probes. Mark production availability only after
   the live calls prove it.
3. Rerun the full CI workflow on the integrated branch. Require SQL apply,
   OpenAPI parity, SDK/contract tests, and offline pytest to pass; track Vercel
   checks separately.
4. Prepare the production release package and deterministic live-contract
   preflight for #297/#299. Deployment, schema-cache refresh, and any production
   database operation require separate explicit release authorization.
5. After the live preflight succeeds, complete #298/#300 integration, rerun all
   12 cases under the US$20 cap for #301, and independently grade each answer
   against evaluator-private references before making a product-value claim.

## Checkpoints

### API contract checkpoint

- [ ] Local Postgres applies the SQL and exact SDK requests validate response
      keys/types, argument names, grants, row caps, and empty results.
- [ ] The live API release state for all three research RPCs is known. After
      separate approval and release, direct SDK probes no longer return
      `PGRST202`.
- [ ] Coverage timeout classification matches observed results; no timeout fix
      is claimed without a reproducible failure.

### Agent harness checkpoint

- [ ] Tools expose required and optional parameter names and types from the
      published contract.
- [ ] Invalid parameters fail before the network call with a useful message.
- [ ] Safe API status/code/message reaches the agent and logs without secrets,
      request headers, or sensitive values.
- [ ] A test confirms the model receives only each professional question, not
      evaluator guidance or a prescribed dataset.

### Evaluation checkpoint

- [ ] All 12 cases run inside the overall US$20 baseline-plus-final budget.
- [ ] All three limitation cases are handled correctly.
- [ ] Three flagship cases succeed twice with reproducible calculations and
      source citations.
- [ ] At least eight of nine answerable cases meet the full rubric.
- [ ] Independent grading rejects invented joins, materially incorrect values,
      incompatible periods, unsupported causality, or missing material caveats.
- [ ] Report technical availability, discovery, calculation accuracy, usefulness,
      latency, and actual cost separately; unrun/ungraded cases remain unverified.

## Risks and mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Production deployment remains unapproved or unavailable | New FII/Focus cases cannot test live research value | Complete local checks and release package; do not claim live success until separately approved and verified |
| Agent tool schemas drift from OpenAPI/SDK | More malformed calls and misleading failures | Derive/validate tool arguments against the published contract and test parity |
| Benchmark questions are ambiguous | Agent clarification is mis-scored as failure | Clarify professional terms in the question without naming data sources or joins |
| Larger turn limits increase model cost | Budget overrun | Reserve worst-case cost before each case and stop before exceeding the total cap |
| “Completed” is mistaken for “passed” | Inflated product-value claim | Require independent rubric and deterministic numeric checks |

## Not in scope

- Production migration, deployment, schema-cache refresh, or historical backfill
  without separate release authorization.
- Relational-schema redesign without evidence from query correctness or measured
  performance.
- Steering the agent to a specific dataset, endpoint, join, or reference result.
- Paid data acquisition or a new chat application.
