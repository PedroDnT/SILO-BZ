---
name: tech-debt
description: Audit SILO-BZ for technical debt, file one map issue plus phased child issues, then implement one phase as a PR
---
Score = (Impact + Risk) x (6 - Effort), each 1 to 5. Effort 1 is hours, 3 a day or two, 5 a week or more.

1. **Audit, read-only.** Fan out subagents by concern (code duplication and long functions, swallowed errors and raw DB access, test debt, docs and register staleness, workflows and dependencies, root clutter). Verify every surprising claim against the file before it goes in the report; drop what does not hold and say so. Check `docs/planning/OPEN_ITEMS.md` first: an item it already tracks is not a new finding.
2. **Report.** One table, scored, with a phase per item: A docs and deps (no behavior change), B one PR that needs an owner decision, C on touch, D housekeeping. A "Checked and dropped" section. Write it to the scratchpad and send it; the register and the issues are the durable record, not a new file under `docs/`.
3. **Labels first.** `gh api repos/PedroDnT/SILO-BZ/labels --paginate -q '.[].name'`. Needed: `tech-debt`, `phase:A` to `phase:D`, and one of `ready-for-agent` / `ready-for-human` / `needs-triage`. Create a missing one with `gh api -X POST .../labels` (`docs/agents/issue-tracker.md`).
4. **Issues.** One map issue (`tech-debt`, `epic`, `wayfinder:map`) with the phases and the dropped claims. Then one child per finding, created with `parent_issue_number`, title prefixed `[A]`..`[D]`, body with the score, the `path:line` facts and the fix; `ready-for-human` when an owner decision comes first. Create one child, check it, then the rest.
5. **Implement one phase** on `claude/tech-debt-<phase>`: the smallest change per item, the changelog fragment, the architecture page if the hook asks, the full suite green (`pip install -r requirements-dev.txt`), then a ready-for-review PR that says `Closes #n` per child. Items that need an owner decision are not in the PR; they wait on the issue.
6. **Discovery is not prioritization.** The audit reports; the owner picks the phase to start. Do not widen a phase PR with a new finding.
