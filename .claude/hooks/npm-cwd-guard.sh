#!/usr/bin/env bash
# PreToolUse on Bash. Refuse `npm install|i|ci` when the directory it would run
# in is $HOME or has no package.json (the repo root has none; only dashboard/
# and webapp/ do). The effective directory is the hook payload's cwd, moved by
# any `cd` earlier in the same command, or `--prefix` / `-C` if given.
# `npm install -g` is allowed. Exit 2 blocks the call and shows stderr to Claude.
set -u
command -v python3 >/dev/null 2>&1 || exit 0
exec python3 -c '
import json, os, re, shlex, sys

p = json.load(sys.stdin)
cmd = (p.get("tool_input") or {}).get("command") or ""
if not re.search(r"\bnpm\s+(i|install|ci)\b", cmd):
    sys.exit(0)
home = os.path.expanduser("~")
cwd = p.get("cwd") or os.getcwd()

def resolve(base, d):
    return os.path.normpath(os.path.join(base, os.path.expanduser(d)))

# Walk the command segment by segment, tracking cd.
for seg in re.split(r"&&|\|\||;|\n", cmd):
    try:
        w = shlex.split(seg)
    except ValueError:
        w = seg.split()
    if not w:
        continue
    if w[0] == "cd":
        cwd = resolve(cwd, w[1] if len(w) > 1 else "~")
        continue
    if w[0] != "npm" or len(w) < 2 or w[1] not in ("i", "install", "ci"):
        continue
    if "-g" in w or "--global" in w:
        continue
    target = cwd
    for i, a in enumerate(w):
        if a in ("--prefix", "-C") and i + 1 < len(w):
            target = resolve(cwd, w[i + 1])
        elif a.startswith("--prefix="):
            target = resolve(cwd, a.split("=", 1)[1])
    if target == home:
        why = "it would run in $HOME"
    elif not os.path.isfile(os.path.join(target, "package.json")):
        why = f"{target} has no package.json"
    else:
        continue
    shown = " ".join(w)
    print(f"Refusing `{shown}`: {why}. cd into dashboard/ or webapp/ "
          "first and confirm that is the intended target (CLAUDE.md, Environment).",
          file=sys.stderr)
    sys.exit(2)
'
