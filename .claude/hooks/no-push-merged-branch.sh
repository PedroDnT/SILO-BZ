#!/usr/bin/env bash
# PreToolUse on `git push`. Refuse a push of a branch whose PR is already
# merged: GitHub deleted the remote branch, so a push recreates it (AGENTS.md,
# "Working beside other agents", rule 6). A push that deletes a remote branch is
# allowed. Fails open when jq or gh is missing or offline: a missing check must
# not stop work. Exit 2 blocks the call and shows stderr to Claude.
#
# The branch comes from the command, not from the session (#904): an explicit
# refspec (`git push -u origin <branch>`), else the current branch of the
# directory the push runs in, which a leading `cd <dir> &&` or `git -C <dir>`
# names. The payload `cwd` is only the starting directory. Only a real push
# command counts: `git` (after any VAR=value) as the first word of a command
# segment, `push` its subcommand. The words inside a heredoc, a quoted string
# or a comment are not a push.
set -u
command -v jq >/dev/null 2>&1 || exit 0
command -v gh >/dev/null 2>&1 || exit 0
payload=$(cat)
cmd=$(printf '%s' "$payload" | jq -r '.tool_input.command // empty')
case "$cmd" in
*push*) ;;
*) exit 0 ;;
esac
cwd=$(printf '%s' "$payload" | jq -r '.cwd // empty')
[ -n "$cwd" ] || cwd=$PWD
# The command parsing is shared with pre-push-docs.sh (#1109).
# shellcheck source=lib/git-push.sh
. "${BASH_SOURCE[0]%/*}/lib/git-push.sh" || exit 0

# Print the number of a merged PR whose head is $2, asked from directory $1
# (the payload cwd when $1 is unknown: gh only needs the repository).
merged_pr() {
  # REST, not `gh pr list`: GraphQL is 403 from these sessions (AGENTS.md).
  (cd "${1:-$cwd}" 2>/dev/null && gh api "repos/{owner}/{repo}/pulls?state=closed&head={owner}:$2" \
    -q '[.[] | select(.merged_at != null)][0].number // empty' 2>/dev/null)
}

check() { # dir branch
  local b=${2#refs/heads/} n
  [ -n "$b" ] || return 0
  n=$(merged_pr "$1" "$b")
  if [ -n "$n" ]; then
    echo "Branch $b already merged (PR #$n). Do not push: GitHub deleted it and a push recreates it. Branch from main instead." >&2
    exit 2
  fi
}

# A push from a directory it cannot enter has no known current branch: one
# that relies on it fails open, an explicit refspec is still checked.
while IFS=$'\037' read -r -a f; do
  [ "${#f[@]}" -ge 4 ] || continue
  if [ "${f[2]}" = 0 ]; then
    check "${f[0]}" "${f[1]}" # no refspec: the current branch is pushed
    continue
  fi
  for b in "${f[@]:4}"; do check "${f[0]}" "$b"; done
done < <(git_pushes "$cmd" "$cwd")
exit 0
