#!/usr/bin/env bash
# SessionStart: show where main is and which PRs are open, so a session sees
# parallel work before it starts its own (AGENTS.md, "Working beside other agents").
# Stdout lands in the session's context. Never blocks: every step may fail.
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

git fetch -q origin main 2>/dev/null
echo "origin/main (last 5):"
git log --oneline -5 origin/main 2>/dev/null || echo "  (unavailable)"

echo "Open PRs (REST; GraphQL is 403 here):"
gh api 'repos/PedroDnT/SILO-BZ/pulls?state=open&per_page=30' \
  --jq '.[] | "  #\(.number) \(.head.ref): \(.title)"' 2>/dev/null \
  || echo "  (gh unavailable)"
exit 0
