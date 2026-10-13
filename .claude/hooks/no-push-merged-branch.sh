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

# Split the command into segments, one per line, words joined by \037. Quotes
# are removed, heredoc bodies, comments and redirections dropped; ; & | && ||
# ( ) and newlines end a segment. POSIX awk, no gawk extensions.
segments=$(printf '%s\n' "$cmd" | awk '
function flush_word() { if (inword) { seg = seg (nw ? "\037" : "") word; nw++ } word = ""; inword = 0 }
function flush_seg() { flush_word(); if (nw) print seg; seg = ""; nw = 0 }
{ text = text $0 "\n" }
END {
  n = length(text); i = 1; seg = ""; nw = 0; word = ""; inword = 0; nh = 0; drop = 0
  while (i <= n) {
    c = substr(text, i, 1)
    if (c == "\\") {
      d = substr(text, i + 1, 1)
      if (d != "\n") { word = word d; inword = 1 }
      i += 2; continue
    }
    if (c == "\047") {
      j = index(substr(text, i + 1), "\047"); if (!j) j = n - i + 1
      w = substr(text, i + 1, j - 1); gsub(/\n/, " ", w)
      word = word w; inword = 1; i += j + 1; continue
    }
    if (c == "\"") {
      i++
      while (i <= n && substr(text, i, 1) != "\"") {
        if (substr(text, i, 1) == "\\" && i < n) i++
        d = substr(text, i, 1); if (d == "\n") d = " "
        word = word d; i++
      }
      inword = 1; i++; continue
    }
    if (c == "#" && !inword) { while (i <= n && substr(text, i, 1) != "\n") i++; continue }
    if (c == "<" || c == ">") {
      if (inword && word ~ /^[0-9]+$/) { word = ""; inword = 0 }
      flush_word()
      if (substr(text, i, 3) == "<<<") { i += 3; drop = 1; continue }
      if (substr(text, i, 2) == "<<") {
        i += 2; strip = 0
        if (substr(text, i, 1) == "-") { strip = 1; i++ }
        while (substr(text, i, 1) == " " || substr(text, i, 1) == "\t") i++
        delim = ""
        while (i <= n) {
          d = substr(text, i, 1)
          if (d ~ /[ \t\n;&|()<>]/) break
          if (d != "\047" && d != "\"" && d != "\\") delim = delim d
          i++
        }
        nh++; hd[nh] = delim; hs[nh] = strip; continue
      }
      while (substr(text, i, 1) ~ /[<>&|]/) i++
      drop = 1; continue
    }
    if (c == " " || c == "\t") {
      if (drop && inword) { word = ""; inword = 0; drop = 0 } else flush_word()
      i++; continue
    }
    if (c ~ /[;&|()\n]/) {
      if (drop && inword) { word = ""; inword = 0 }
      drop = 0; flush_seg(); i++
      if (c == "\n") {
        for (h = 1; h <= nh; h++) {
          while (i <= n) {
            e = index(substr(text, i), "\n"); if (!e) e = n - i + 2
            line = substr(text, i, e - 1); i += e
            if (hs[h]) sub(/^\t+/, "", line)
            if (line == hd[h]) break
          }
        }
        nh = 0
      }
      continue
    }
    word = word c; inword = 1; i++
  }
  if (drop && inword) { word = ""; inword = 0 }
  flush_seg()
}')

# Resolve dir $2 against base $1. Empty means unknown: a directory that cannot
# be entered ($VAR, $(...), a typo), or a relative one from an unknown base.
resolve() {
  case "$2" in
  '') ;;
  /*) (cd "$2" 2>/dev/null && pwd) ;;
  *) [ -n "$1" ] && (cd "$1" 2>/dev/null && cd "$2" 2>/dev/null && pwd) ;;
  esac
}

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

dir=$cwd
while IFS= read -r line; do
  [ -n "$line" ] || continue
  IFS=$'\037' read -r -a t <<<"$line"
  k=0
  while [ "$k" -lt "${#t[@]}" ] && [[ ${t[k]} =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; do k=$((k + 1)); done
  [ "$k" -lt "${#t[@]}" ] || continue
  if [ "${t[k]}" = cd ]; then
    target=${t[k + 1]:-}
    case "$target" in '' | -) continue ;; esac
    dir=$(resolve "$dir" "$target")
    continue
  fi
  [ "${t[k]}" = git ] || continue
  k=$((k + 1))
  pdir=$dir
  # git's global options, up to the subcommand.
  while [ "$k" -lt "${#t[@]}" ]; do
    case "${t[k]}" in
    -C)
      pdir=$(resolve "$pdir" "${t[k + 1]:-}")
      k=$((k + 2))
      ;;
    -c | --git-dir | --work-tree | --namespace | --exec-path) k=$((k + 2)) ;;
    -*) k=$((k + 1)) ;;
    *) break ;;
    esac
  done
  [ "${t[k]:-}" = push ] || continue
  k=$((k + 1))
  pos=()
  while [ "$k" -lt "${#t[@]}" ]; do
    a=${t[k]}
    case "$a" in
    --delete | -d) continue 2 ;; # deleting a remote branch is allowed
    -o | --push-option | --repo | --receive-pack | --exec) k=$((k + 1)) ;;
    --) ;;
    -[!-]*d*) continue 2 ;; # -d bundled with other short flags, e.g. -fd
    -*) ;;
    *) pos+=("$a") ;;
    esac
    k=$((k + 1))
  done
  # An unknown directory has no known current branch: a push that relies on it
  # fails open, an explicit refspec is still checked.
  current=
  [ -n "$pdir" ] && current=$(cd "$pdir" 2>/dev/null && git branch --show-current 2>/dev/null)
  if [ "${#pos[@]}" -le 1 ]; then
    check "$pdir" "$current" # no refspec: the current branch is pushed
    continue
  fi
  for r in "${pos[@]:1}"; do
    r=${r#+}
    case "$r" in :*) continue ;; esac # :branch deletes it
    case "$r" in *:*) b=${r#*:} ;; *) b=$r ;; esac
    [ "$b" = HEAD ] && b=$current
    check "$pdir" "$b"
  done
done <<<"$segments"
exit 0
