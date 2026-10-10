---
name: branch-audit
description: Read-only audit of git branches. Reports which local and remote branches are merged, squash-merged, unmerged, stale or safe to delete, and never deletes anything. Use whenever the user asks which branches are merged, what can be cleaned up, whether a branch is already in main, which branches are stale, or says "clean up my branches", "prune branches", "what is left to merge" or "is this branch merged", even if they do not say "audit".
---

# Branch audit

Answer "what is merged, what is not, and what is safe to delete" for a git repo. This skill only reads. The user decides every deletion, because a deleted branch can hold the only copy of someone's work, and a remote delete affects other people.

## Why not just `git branch --merged`

`--merged` only sees branches whose commits are ancestors of the default branch. GitHub squash and rebase merges rewrite the commits, so those branches look unmerged forever. The bundled script also detects them, so the report is not full of false "unmerged" rows. It errs the safe way: when unsure, it says `unmerged`.

## Steps

1. Run the script from the repo root. Add `--fetch` only if the user is fine with refreshing remote-tracking refs (it runs `git fetch --prune` and changes no branch). Without it, remote data may be old; say so.

   ```bash
   bash .claude/skills/branch-audit/scripts/branch_audit.sh [--fetch] [--stale-days 60]
   ```

   Output: a `# base=...` line, then tab-separated rows `verdict kind branch class ahead_of_base age_days note`.

2. Show the result grouped by verdict, as short tables. Order: `SAFE-TO-DELETE`, `REVIEW-STALE`, `REVIEW`, `KEEP`. Add the counts on top. Lead with the answer.

3. Explain only what the user needs:
   - `SAFE-TO-DELETE`: the work is in the default branch. A squash-merged row shows `ahead_of_base > 0`; that is expected, the commits were rewritten.
   - `REVIEW` / `REVIEW-STALE`: real work the default branch does not have. Never call these safe. For one that matters, show its unique commits with `git log --oneline base..branch`.
   - `KEEP`: the default branch, the current branch, or a branch checked out in another worktree. Git refuses to delete these anyway.
   - `upstream-gone` note: the remote branch was deleted (often right after a merge). Mention it, but trust `class`, not the note.

4. If the user wants to act, print the exact commands for the exact branch names, one list for local (`git branch -d`) and one for remote (`git push origin --delete`), and stop. Use `-d` for `merged` rows; it refuses unmerged work. For `squash-merged` rows `-d` will refuse too, because git cannot see the rewrite, so those need `-D`. Say that plainly and list them apart: `-D` is safe there only because the script found the same patch in the default branch, and the user should approve it knowingly. Never use `-D` on a `REVIEW` row. Do not build commands from a grep pattern: a pattern like `grep -v dev` also skips real branches that contain "dev" in the name. Run nothing that deletes unless the user approves that exact list in this conversation.

## Edge cases

- No `origin/HEAD` and no `main` or `master`: the script stops and says so. Ask which branch is the default.
- Several remotes: pass `--remote NAME`.
- A repo with a rule against pushing to a merged branch (or a hook for it): a remote branch for a merged PR is normally already deleted by the host. Do not recreate it.
- Shallow clones can misreport. If `git rev-parse --is-shallow-repository` prints `true`, say the result may be incomplete.
