---
name: ship-api-change
description: Ship an api.* schema change end-to-end (claim, SQL, catalog, contracts, tests, PR)
---
The rules live in `AGENTS.md` ("Adding an API endpoint", "Working beside other agents"). This is the order to follow them in.

1. Claim the ticket: `git fetch`, then search open and merged PRs for the ticket number (`gh api "search/issues?q=repo:PedroDnT/SILO-BZ+is:pr+<n>"`). Compare your files with every open PR's files. Assign the issue and comment `Claimed by: claude · branch claude/<name>`.
2. Branch from `origin/main`. If main moves later, merge it before the catalog bump and renumber if needed.
3. Load the `silo` skill (`.claude/skills/silo/SKILL.md`), as `AGENTS.md` requires before a schema `api` change. Change the SQL. Escape single quotes in `COMMENT` literals (`''`). A new function refuses above 1,000 rows through `assert_row_cap`.
4. Bump the catalog version: the next free number after main.
5. Regenerate the contracts: `scripts/gen_openapi.py`, `scripts/gen_mcp_contract.py` (plus the `t()` line in `supabase/functions/silo-mcp/tools.ts`), and `scripts/gen_sdk_contract.py` for a new or changed signature.
6. Add or adjust tests. Run `pytest tests/ -q` (offline, DB mocked; there is no local Postgres step).
7. Add the changelog fragment `docs/planning/changelog.d/<date>_<branch>.md`. Edit the matching `docs/architecture/` page if the change touches what it describes.
8. Commit, push, and open the PR ready for review, not as a draft. Put the summary and the test result in the body.
9. After the merge, never push to that branch again. GitHub deleted it, and a push recreates it.
10. A merge deploys nothing to the database. Tell the owner to run `daily_ingest` with `mode=analytics-only`, then `deploy_mcp.yml`.
