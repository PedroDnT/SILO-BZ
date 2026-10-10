#!/usr/bin/env bash
# Read-only audit of git branches against the remote default branch.
# Prints one tab-separated row per branch. It never deletes, resets or pushes.
# Usage: branch_audit.sh [--fetch] [--remote NAME] [--stale-days N]
#   --fetch   run `git fetch --prune` first (updates remote-tracking refs only)
set -euo pipefail

remote=origin
stale_days=60
do_fetch=0
while [ $# -gt 0 ]; do
  case "$1" in
    --fetch) do_fetch=1 ;;
    --remote) remote=$2; shift ;;
    --stale-days) stale_days=$2; shift ;;
    *) echo "usage: $0 [--fetch] [--remote NAME] [--stale-days N]" >&2; exit 2 ;;
  esac
  shift
done

git rev-parse --git-dir >/dev/null 2>&1 || { echo "not a git repository" >&2; exit 1; }
[ "$do_fetch" = 1 ] && git fetch --prune "$remote"

# Default branch: the remote's HEAD if known, else main, else master. Never assume a name.
base=$(git symbolic-ref --quiet --short "refs/remotes/$remote/HEAD" 2>/dev/null || true)
if [ -z "$base" ]; then
  for c in main master; do
    if git show-ref --verify --quiet "refs/remotes/$remote/$c"; then base="$remote/$c"; break; fi
  done
fi
[ -n "$base" ] || { echo "cannot find the default branch of '$remote'; run with --fetch" >&2; exit 1; }
base_short=${base#"$remote"/}

current=$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true)
now=$(date +%s)
worktrees=$(git worktree list --porcelain | sed -n 's|^branch refs/heads/||p')

# merged        : every commit is already in the default branch (ancestor)
# squash-merged : the branch's whole diff is in the default branch as one other commit
#                 (GitHub squash or rebase merge). `git branch --merged` misses these.
# unmerged      : real work that the default branch does not have
classify() {
  local ref=$1 mb tmp
  if git merge-base --is-ancestor "$ref" "$base"; then echo merged; return; fi
  mb=$(git merge-base "$base" "$ref" 2>/dev/null) || { echo unmerged; return; }
  # Rebuild the branch as ONE commit on its merge base, then ask git cherry whether the
  # default branch already holds an equal patch. A false "unmerged" is the safe error.
  tmp=$(GIT_AUTHOR_NAME=audit GIT_AUTHOR_EMAIL=audit@localhost \
        GIT_COMMITTER_NAME=audit GIT_COMMITTER_EMAIL=audit@localhost \
        git commit-tree "$ref^{tree}" -p "$mb" -m audit)
  if [ "$(git cherry "$base" "$tmp" | cut -c1)" = "-" ]; then echo squash-merged; else echo unmerged; fi
}

emit() { # kind ref short unix upstream_track
  local kind=$1 ref=$2 short=$3 unix=$4 track=$5 cls ahead age verdict note=""
  cls=$(classify "$ref")
  ahead=$(git rev-list --count "$base..$ref")
  age=$(( (now - unix) / 86400 ))
  if [ "$kind" = local ]; then
    [ "$short" = "$current" ] && note="current-branch"
    if [ "$short" != "$current" ] && printf '%s\n' "$worktrees" | grep -qxF -- "$short"; then
      note="${note:+$note,}checked-out-in-worktree"
    fi
    [ "$track" = "[gone]" ] && note="${note:+$note,}upstream-gone"
  fi
  if [ "$short" = "$base_short" ] || [ "$short" = "$base" ]; then verdict=KEEP; note="default-branch"
  elif [ -n "$note" ] && printf '%s' "$note" | grep -Eq 'current-branch|checked-out-in-worktree'; then verdict=KEEP
  elif [ "$cls" = merged ] || [ "$cls" = squash-merged ]; then verdict=SAFE-TO-DELETE
  elif [ "$age" -ge "$stale_days" ]; then verdict=REVIEW-STALE
  else verdict=REVIEW; fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$verdict" "$kind" "$short" "$cls" "$ahead" "$age" "$note"
}

echo "# base=$base stale_days=$stale_days"
printf 'verdict\tkind\tbranch\tclass\tahead_of_base\tage_days\tnote\n'
while IFS=$'\t' read -r short unix track; do
  [ -n "$short" ] && emit local "refs/heads/$short" "$short" "$unix" "$track"
done < <(git for-each-ref --format='%(refname:short)%09%(committerdate:unix)%09%(upstream:track)' refs/heads)
while IFS=$'\t' read -r short unix; do
  case "$short" in "$remote"|"$remote/HEAD") continue ;; esac
  emit remote "refs/remotes/$short" "$short" "$unix" ""
done < <(git for-each-ref --format='%(refname:short)%09%(committerdate:unix)' "refs/remotes/$remote")
