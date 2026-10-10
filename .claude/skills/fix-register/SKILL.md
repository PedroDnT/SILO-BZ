---
name: fix-register
description: Work through open items in the SILO-BZ planning register (docs/planning/OPEN_ITEMS.md)
---
1. Read `docs/planning/OPEN_ITEMS.md` and list the open items, one line each, with a short plan.
2. Before fixing each item, fetch current main and search existing branches and open/recently merged PRs by ticket. Follow `AGENTS.md` ("Working beside other agents" and "Codex task-boundary board") for claims and open-PR file overlap. Reuse existing work; integrate only under the owner's Git/approval rules. Never switch branches or merge while shared-checkout writers are active.
3. Take one unclaimed, non-overlapping item. Explore only what it needs, make the focused fix, and verify it with the required checks.
4. Mark that item's status in the register, add its required branch docs, and commit only the reviewed paths: one fix per item. Follow the actual agent's branch prefix and ready-for-review PR rules in `AGENTS.md`.
5. If blocked or requiring an owner-only action, record the exact blocker/action and move to the next available item. Never silently mark blocked work done.
6. Repeat one item at a time. End with each item's status, verification and changed files; distinguish local, merged and deployed evidence.
