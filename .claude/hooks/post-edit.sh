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
case "$f" in
  *.py) ;;
  *) exit 0 ;;
esac
[ -f "$f" ] || exit 0

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
