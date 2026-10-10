# Implementation plan: audit remediation

Approved by Pedro on 10/10/2026 (UTC-3). Tasks are tracked in GitHub parent
[#828](https://github.com/PedroDnT/SILO-BZ/issues/828); there is no duplicate todo file.
The existing `tasks/plan.md` belongs to debenture serving and remains separate.

## Goal and boundaries

Resolve secret protection, stale workflow skills, invisible trace-persistence
failures, and excessive always-loaded context. Execute sequentially on
`codex/audit-remediation`, with one reviewed commit per finding. Check live issue
ownership, PR file overlap and the primary checkout's Coordinator board before
writing. This chat owns goal coordination and the bounded paths.

Preserve integrity, approval and coordination rules, unrelated local changes,
the stateless diagnosis and private trace contract. Runtime LLM components stay
within the accepted product scope. Deployment and production credentials require
separate owner approval. Do not enable auto-merge on these gate-file changes.

## Ordered task index

1. [#829](https://github.com/PedroDnT/SILO-BZ/issues/829): sanitized secret guard
   shared by the pre-commit hook and PR CI, synthetic behavioral regressions,
   dotenv coverage and verified local hook activation. Estimate: 1–2 hours.
2. [#830](https://github.com/PedroDnT/SILO-BZ/issues/830): current serving rules,
   overlap checks, per-item commits and actual agent identity in skills.
   Estimate: 1 hour.
3. [#831](https://github.com/PedroDnT/SILO-BZ/issues/831): sanitized asynchronous
   persistence outcomes, complete artifact validation and response/cleanup
   preservation, proved with fake-container/bucket behavioral tests.
   Estimate: 1–2 hours.
4. [#832](https://github.com/PedroDnT/SILO-BZ/issues/832): reduce context with
   mandatory rules intact, explicit dataset-note entry points, rule inventory
   and byte-cap verification. Depends on #830. Estimate: 1–2 hours.

Each issue contains its exact acceptance criteria, verification and likely files.
Check the existing `claude/ai-firstify-audit` context hunks for compatible reuse;
its unrelated settings and MCP changes are outside this plan.

## Checkpoints

- [x] Owner approved this separate destination, plan and implementation.
- [x] After secret protection: rejection never echoes synthetic credentials,
  local hook is active, and the PR guard uses the same detector.
- [x] After skills and traces: changed references resolve; executable tests
  cover persistence success, validation failures, storage failures and cleanup.
- [ ] Complete: focused tests, required offline suite and CI pass; context is
  below 32 KiB with a target of 28 KiB; mandatory-rule inventory is reviewed;
  four focused commits and required docs are present in a ready-for-review PR.

## Risks and verification limits

| Risk | Mitigation |
| --- | --- |
| Credential printed by rejection or Git errors | Fixed safe diagnostics; synthetic output assertions |
| Working-file scan misses staged contents | Read staged blobs; test staged/worktree disagreement |
| Trace key mistaken for durable storage | Mark as intended/pending; explicit sanitized background outcome |
| Partial artifact writes called complete | Validate required artifacts first; publish trace last |
| Context move weakens a rule | Root safety rules retained; before/after inventory and entry-path review |
| Concurrent changes invalidate patches | Recheck claims/PRs and re-read files before applying |

Total estimate: 4–7 focused hours plus CI and review waits. Local checks, remote CI,
merge and deployment are distinct evidence. No deployment is part of this work.

## Current state

All four local fixes are implemented. Secret regressions: 21 passed. Worker
behavior/exposure/agent checks: 35 passed. The local hook is configured and
executable. Full suite, independent review and remote CI are the final gate;
production rollout remains separately gated.

## Mandatory-rule inventory for context reduction

| Original section | Current entry point | Preservation evidence |
| --- | --- | --- |
| Integrity, architecture, dataset/API additions | Root AGENTS.md | Entire sections unchanged |
| Database safety and approval boundaries | Root AGENTS.md | Entire sections unchanged |
| Claims, branch ownership and Coordinator | Root AGENTS.md | Entire sections unchanged |
| Time rules, environment and deployment | Root AGENTS.md | Entire sections unchanged |
| Graphify instructions added on current main | Root AGENTS.md | Entire managed block unchanged |
| Cursor VM/dependency and offline setup | docs/agents/cursor-cloud.md | Original section copied verbatim except heading level; root requires reading before first command |
| Consumer pages, build and accounting detail | docs/agents/consumers.md | Original section copied verbatim except heading level; root retains read-only, deployment and accounting boundaries |
| Dataset notes | Root plus SILO entry skill | Existing read-before-table-change instruction retained; unconditional Claude import removed |

Root instructions: 32,026 → 27,779 UTF-8 bytes; 4,989 bytes below the 32 KiB cap.
The earlier audit branch supplied the on-demand-loading approach; moved Cursor
content is copied from current main to preserve updated dependency facts. No
settings/MCP hunks from that branch are included.
