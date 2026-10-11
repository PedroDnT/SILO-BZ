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

No agent reads issue comments or applies these labels on its own. An agent acts on an issue only when the owner applies `ready-for-agent` (or starts `/orchestrate`). After you answer a `needs-info` issue, change its label by hand.

GitHub rejects a label that does not exist, so create a label before you use it. Check the list with `gh api repos/PedroDnT/SILO-BZ/labels`.
