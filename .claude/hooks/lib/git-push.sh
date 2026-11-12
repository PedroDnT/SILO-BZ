# shellcheck shell=bash
# Sourced by the PreToolUse hooks on `git push` (no-push-merged-branch.sh,
# pre-push-docs.sh): which pushes a Bash command makes, from which directory,
# and of which branches (#904, #1109). Bash only; needs awk and git.
#
# Only a real push command counts: `git` (after any VAR=value) as the first
# word of a command segment, `push` its subcommand. The words inside a heredoc,
# a quoted string or a comment are not a push. The directory a push runs in is
# the payload `cwd`, moved by each `cd <dir>` segment before it and by
# `git -C <dir>`; an unknown one (`$VAR`, `$(...)`, a typo, or relative to an
# unknown one) is empty.

# Split the command (stdin) into segments, one per line, words joined by \037.
# Quotes are removed, heredoc bodies, comments and redirections dropped; ; & |
# && || ( ) and newlines end a segment. POSIX awk, no gawk extensions.
push_segments() {
  awk '
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
}'
}

# Resolve dir $2 against base $1. Empty means unknown: a directory that cannot
# be entered ($VAR, $(...), a typo), or a relative one from an unknown base.
resolve() {
  case "$2" in
  '') ;;
  /*) (cd "$2" 2>/dev/null && pwd) ;;
  *) [ -n "$1" ] && (cd "$1" 2>/dev/null && cd "$2" 2>/dev/null && pwd) ;;
  esac
}

# git_pushes <command> <cwd>: one line per push that publishes a branch, fields
# joined by \037:
#   1. the directory it runs in (empty: unknown)
#   2. that directory's current branch (empty: unknown or detached)
#   3. 1 when the push names a refspec, else 0 (it pushes the current branch)
#   4. 1 when it pushes tags only (--tags), else 0
#   5... the remote branches the refspecs name: the destination of src:dst,
#        `HEAD` read as the current branch, `refs/heads/` stripped. A `:branch`
#        refspec deletes it and is not listed.
# A push that deletes (--delete, -d, also bundled as -fd) prints no line.
git_pushes() {
  local cmd=$1 dir=$2 line k a target pdir current r b given tags out
  local -a t pos
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
    tags=0
    while [ "$k" -lt "${#t[@]}" ]; do
      a=${t[k]}
      case "$a" in
      --delete | -d) continue 2 ;; # deleting a remote branch publishes nothing
      -o | --push-option | --repo | --receive-pack | --exec) k=$((k + 1)) ;;
      --tags) tags=1 ;;
      --) ;;
      -[!-]*d*) continue 2 ;; # -d bundled with other short flags, e.g. -fd
      -*) ;;
      *) pos+=("$a") ;;
      esac
      k=$((k + 1))
    done
    current=
    [ -n "$pdir" ] && current=$(cd "$pdir" 2>/dev/null && git branch --show-current 2>/dev/null)
    given=0
    [ "${#pos[@]}" -gt 1 ] && given=1
    out="$pdir"$'\037'"$current"$'\037'"$given"$'\037'"$tags"
    for r in "${pos[@]:1}"; do
      r=${r#+}
      case "$r" in :*) continue ;; esac # :branch deletes it
      case "$r" in *:*) b=${r#*:} ;; *) b=$r ;; esac
      [ "$b" = HEAD ] && b=$current
      b=${b#refs/heads/}
      [ -n "$b" ] && out="$out"$'\037'"$b"
    done
    printf '%s\n' "$out"
  done < <(printf '%s\n' "$cmd" | push_segments)
}
