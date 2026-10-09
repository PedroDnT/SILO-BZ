#!/usr/bin/env bash
# PreToolUse on `git push`. Refuse a push from a branch whose PR is already
# merged: GitHub deleted the remote branch, so a push recreates it (AGENTS.md,
# "Working beside other agents", rule 6). A push that deletes a remote branch is
# allowed. Fails open when jq or gh is missing or offline: a missing check must
# not stop work. Exit 2 blocks the call and shows stderr to Claude.
set -u
command -v jq >/dev/null 2>&1 || exit 0
command -v gh >/dev/null 2>&1 || exit 0
payload=$(cat)
cmd=$(printf '%s' "$payload" | jq -r '.tool_input.command // empty')
case "$cmd" in
*'git push'*) ;;
*) exit 0 ;;
esac
case "$cmd" in
*' --delete'* | *' -d '*) exit 0 ;;
esac
cwd=$(printf '%s' "$payload" | jq -r '.cwd // empty')
[ -n "$cwd" ] && cd "$cwd" 2>/dev/null
b=$(git branch --show-current 2>/dev/null)
[ -n "$b" ] || exit 0
n=$(gh pr list --state merged --head "$b" --json number -q '.[0].number' 2>/dev/null)
if [ -n "$n" ]; then
  echo "Branch $b already merged (PR #$n). Do not push: GitHub deleted it and a push recreates it. Branch from main instead." >&2
  exit 2
fi
exit 0
