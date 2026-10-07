#!/usr/bin/env bash
# PostToolUse after Write|Edit. py_compile every edited .py; pytest when
# src/ serve/ tests/ scripts/ change. Failures emit Claude hook JSON.
# Do not swallow (no `|| true`). Skip quietly when tools are missing.
set -u
payload=$(cat)
command -v jq >/dev/null 2>&1 || exit 0

f=$(printf '%s' "$payload" | jq -r '.tool_input.file_path // .tool_response.filePath // empty')
[ -n "$f" ] || exit 0
f="${f#./}"
# Claude Code sends an absolute path. The directory match below is relative,
# so until 2026-10-06 the pytest branch never ran (#708). Make the path
# relative to the checkout the hook runs in: the repo root, or a worktree.
# Prefix strip, not `realpath --relative-to`, so it works on BSD too.
root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
case "$f" in
  "$root"/*) f="${f#"$root"/}" ;;
  "$PWD"/*) f="${f#"$PWD"/}" ;;
  /*) exit 0 ;;  # outside this checkout: nothing to compile or test here
esac
case "$f" in
  *.py) ;;
  *) exit 0 ;;
esac
[ -f "$f" ] || exit 0
# POST_EDIT_DRY_RUN=1 prints the decision and stops, so a test can pin the
# path handling without running py_compile or the suite.
if [ "${POST_EDIT_DRY_RUN:-}" = 1 ]; then
  case "$f" in
    src/*|serve/*|tests/*|scripts/*) echo "pytest $f" ;;
    *) echo "compile-only $f" ;;
  esac
  exit 0
fi

emit() {
  local title="$1" body="$2"
  jq -n --arg t "$title" --arg b "$body" \
    '{systemMessage:$t, hookSpecificOutput:{hookEventName:"PostToolUse", additionalContext:$b}}'
}

PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python

compile_out=$("$PY" -m py_compile "$f" 2>&1) || {
  emit "py_compile failed: $f" "py_compile:
$compile_out"
  exit 2
}

case "$f" in
  src/*|serve/*|tests/*|scripts/*) ;;
  *) exit 0 ;;
esac
[ -x .venv/bin/pytest ] || exit 0

set +e
pytest_out=$(.venv/bin/pytest tests/ -q --tb=line 2>&1)
rc=$?
set -e
if [ "$rc" -ne 0 ]; then
  emit "pytest failed after editing $f" "pytest tail:
$(printf '%s' "$pytest_out" | tail -n 20)"
  exit 2
fi
exit 0
