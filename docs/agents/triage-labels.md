# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning |
| --- | --- | --- |
| `needs-triage` | `needs-triage` | Maintainer needs to evaluate this issue |
| `needs-info` | `needs-info` | Waiting on reporter for more information |
| `ready-for-agent` | `ready-for-agent` | Fully specified, ready for an agent |
| `ready-for-human` | `ready-for-human` | Requires human implementation |
| `wontfix` | `wontfix` | Will not be actioned |

When a skill mentions a role, use the corresponding label string from this table.

## What a label does

No agent applies these labels on its own. One exception: `.github/workflows/conventions.yml` adds `needs-triage` to a new issue that has no triage label, by a fixed rule with no LLM. An agent acts on an issue only when the owner applies `ready-for-agent` (or starts `/orchestrate`), or when a user with write access writes `@claude` in an issue, a comment or a review. Only then does an agent read the issue's comments. The `@claude` agent pushes a `claude/` branch and posts a link; the owner opens the pull request. After you answer a `needs-info` issue, change its label by hand.

The workflow calls the shared workflows in `PedroDnT/agent-triage-conventions` at tag `v1`. The `@claude` agent needs the Claude GitHub app on this repo and the `CLAUDE_CODE_OAUTH_TOKEN` repo secret.

GitHub rejects a label that does not exist, so create a label before you use it. Check the list with `gh api repos/PedroDnT/SILO-BZ/labels`.
