#!/usr/bin/env bash
# PreToolUse on Bash `git push` (.claude/settings.json). Every branch carries
# its own docs, so planning and the README are current the moment it merges:
#   1. one row in docs/planning/CHANGELOG.md, required on every push until the
#      branch has it (or a `No-changelog: <reason>` commit trailer);
#   2. no row that main already had goes missing from that file, on every push
#      (or a `Changelog-removes: <reason>` commit trailer);
#   3. a staleness check of README.md and the planning docs, asked once per
#      branch, unless the branch already edits README.md;
#   4. a change to the files one of the four docs/architecture/ pages describes
#      must edit that page in place (or carry a `No-architecture-change:
#      <reason>` trailer), and an edited page must stay under its size cap.
# A refusal is a PreToolUse deny: the push does not run and Claude reads why.
# Skips quietly when it cannot judge (no jq, another repo, detached HEAD).
set -u
payload=$(cat)
command -v jq >/dev/null 2>&1 || exit 0

cmd=$(printf '%s' "$payload" | jq -r '.tool_input.command // empty')
# The settings `if` filter is best-effort ($() and $VAR pass it), so re-check,
# looking only at the push itself, not the rest of a compound command.
push=$(printf '%s\n' "$cmd" | grep -oE '(^|[[:space:];&|(])git[[:space:]]+push([[:space:]][^;&|)]*)?' | head -n 1)
[ -n "$push" ] || exit 0
# Deleting a remote branch or pushing tags publishes no branch content.
printf '%s\n' "$push" | grep -qE '[[:space:]](--delete|-d|--tags)([[:space:]]|$)|[[:space:]]:[^[:space:]]' && exit 0

cwd=$(printf '%s' "$payload" | jq -r '.cwd // empty')
cd "${cwd:-.}" 2>/dev/null || exit 0
# Only this repository: the session may have cd'd into another clone.
here=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || exit 0
home=$(git -C "${CLAUDE_PROJECT_DIR:-.}" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || exit 0
[ "$here" = "$home" ] || exit 0
branch=$(git symbolic-ref --quiet --short HEAD) || exit 0
[ "$branch" != main ] || exit 0

skip() {
  jq -n --arg m "docs check skipped: $1" '{systemMessage: $m}'
  exit 0
}
git rev-parse --verify --quiet origin/main >/dev/null || skip "no origin/main in this clone"
base=$(git merge-base HEAD origin/main) || skip "$branch shares no history with origin/main"
changed=$(git diff --name-only "$base" HEAD)
[ -n "$changed" ] || exit 0

reason=""
add() {
  reason="${reason:+$reason

}$1"
}

# A trailer counts only on this branch's own commits, the ones origin/main does
# not have: in a criss-cross history `$base..HEAD` also holds main commits.
if ! grep -qx 'docs/planning/CHANGELOG.md' <<<"$changed" &&
  ! git log --format=%B origin/main..HEAD | grep -qiE '^No-changelog:[[:space:]]*[^[:space:]]'; then
  add "No CHANGELOG row. \`$branch\` changes $(grep -c . <<<"$changed") file(s) against origin/main, and every merged branch adds one row to docs/planning/CHANGELOG.md. Insert it as the first row under the table header (newest first):
| $(date -u +%Y-%m-%d) | $branch | **<what changed, in one bold sentence>.** <why, and what a reader needs to know> |
Escape any | inside the prose as \\|, and never run a formatter over that file (tests/test_changelog_integrity.py guards it). Commit, then push again. If your instructions forbid editing CHANGELOG.md (the Scout's do), put a \`No-changelog: <reason>\` trailer in one of this branch's commit messages instead."
fi

# A row main had at the merge base that HEAD no longer has, word for word, was
# dropped or rewritten. A merge that keeps one side of the CHANGELOG conflict
# does that silently: on 2026-09-26 the update of #322 from main kept its row,
# dropped #324's and #325's, and CI stayed green. Compared with the merge base,
# not origin/main's tip, so a branch that is merely behind main is not blamed
# for rows it never had. Every merge base: in a criss-cross history (main merged
# the branch while the branch merged an older main) there are two, and
# `git merge-base` names only one. .github/workflows/test.yml repeats this for
# pull requests, which also covers merges made outside Claude Code.
rows() { git show "$1:docs/planning/CHANGELOG.md" 2>/dev/null | grep '^| 20'; }
bases=$(git merge-base --all HEAD origin/main)
base_rows() { for b in $bases; do rows "$b"; done | awk '!seen[$0]++'; }
if ! git log --format=%B origin/main..HEAD | grep -qiE '^Changelog-removes:[[:space:]]*[^[:space:]]'; then
  dropped=$(grep -vxFf <(rows HEAD) <(base_rows))
  if [ -n "$dropped" ]; then
    n=$(grep -c . <<<"$dropped")
    at=$(git rev-parse --short $bases | paste -sd ' ' -)
    shown=$(head -n 5 <<<"$dropped" | jq -Rr 'if length > 200 then .[:200] + "…" else . end')
    [ "$n" -le 5 ] || shown="$shown
…and $((n - 5)) more"
    add "CHANGELOG rows dropped. docs/planning/CHANGELOG.md on \`$branch\` no longer has $n row(s) that main had at this branch's merge base with origin/main ($at), word for word:
$shown
A merge that keeps one side of the CHANGELOG conflict does this (on 2026-09-26 it took #324's and #325's rows out of main), and so does a formatter run over the file. Put each row back exactly as \`git show origin/main:docs/planning/CHANGELOG.md\` has it, newest first, commit, and push again. If this branch removes or rewrites them on purpose (as #318 removed a stale duplicate), put a \`Changelog-removes: <reason>\` trailer in one of this branch's commit messages instead."
  fi
fi

# 4. The four architecture pages describe structure, so a change to the files a
#    page owns must be reflected in that page, in place: no dated entry (that is
#    the CHANGELOG's job), and short. The map below is deliberately narrow, so a
#    new dataset or a workflow tweak does not trip it. One trailer excuses every
#    page: `No-architecture-change: <reason>`.
arch=docs/architecture
wf_structural() {
  git diff -U0 "$base" HEAD -- "$1" |
    grep -qE '^[+-]([^+-].*)?(cron:|concurrency:|group:|needs:|workflow_dispatch|if:[[:space:]]*(always|failure)\(\))'
}
workflows_added_or_removed=$(git diff --name-only --diff-filter=AD "$base" HEAD -- .github/workflows)
# A pure move (status R) changes where a file is, not what a page says about it.
edited_files=$(git diff --name-only --diff-filter=ACMD "$base" HEAD)
hits=""
while IFS= read -r f; do
  case "$f" in
    .github/workflows/*)
      if wf_structural "$f" || grep -qxF "$f" <<<"$workflows_added_or_removed"; then p=OPERATIONS; else continue; fi ;;
    vercel.json | scripts/promote_dashboard.sh | scripts/vercel_should_build.sh | scripts/verify_pipeline.py) p=OPERATIONS ;;
    src/pipeline/run_daily.py | src/pipeline/run_backfill.py | src/pipeline/ingest_log.py | scripts/apply_analytical.sh | src/store/analytical/08_cron_schedules.sql | serve/*) p=DATA_FLOW ;;
    src/store/pg_client.py | supabase/functions/* | docs/reference/security/* | src/store/analytical/12_grants_and_rls.sql) p=SYSTEM ;;
    docs/adr/*) p=DECISIONS ;;
    *) continue ;;
  esac
  hits="${hits:+$hits
}$p $f"
done <<<"$edited_files"
if git diff -U0 "$base" HEAD -- src/store | grep -qE '^\+([^+].*)?CREATE[[:space:]]+MATERIALIZED[[:space:]]+VIEW'; then
  hits="${hits:+$hits
}DATA_FLOW src/store (a new materialized view)"
fi
owns_SYSTEM="the infrastructure, the products and the boundaries"
owns_DATA_FLOW="the stages, the refresh windows, the matviews and the serving paths"
owns_OPERATIONS="the schedule, what a red day leaves, and how a change deploys"
owns_DECISIONS="the recorded decisions, one row each, linked to its source"
excused=0
git log --format=%B origin/main..HEAD | grep -qiE '^No-architecture-change:[[:space:]]*[^[:space:]]' && excused=1
for p in SYSTEM DATA_FLOW OPERATIONS DECISIONS; do
  page="$arch/$p.md"
  edited=0
  grep -qx "$page" <<<"$changed" && edited=1
  files=$(awk -v p="$p" '$1 == p { $1 = ""; print substr($0, 2) }' <<<"$hits" | head -n 5 | paste -sd ' ' -)
  if [ -n "$files" ] && [ "$edited" = 0 ] && [ "$excused" = 0 ]; then
    eval "owns=\$owns_$p"
    add "$page is not updated. This branch changes $files, which that page describes ($owns). Edit the page in place so it states how things are now: fix the lines that are no longer true, add only what a new reader needs, and put no dated entry in it. If the page is still right, put a \`No-architecture-change: <reason>\` trailer in one of this branch's commit messages."
  fi
  if [ "$edited" = 1 ]; then
    cap=4096
    [ "$p" = DECISIONS ] && cap=5120
    size=$(git cat-file -s "HEAD:$page" 2>/dev/null) || continue
    if [ "$size" -gt "$cap" ]; then
      add "$page is $size bytes; the cap is $cap. Keep it short: merge rows, drop detail the page's \"Deeper\" links already hold, and do not grow it with history."
    fi
  fi
done

asked=$(git rev-parse --git-path claude-docs-checked)
if ! grep -qx 'README.md' <<<"$changed" && ! grep -qxF "$branch" "$asked" 2>/dev/null; then
  printf '%s\n' "$branch" >>"$asked"
  check="README and planning check, asked once per branch. README.md is unchanged on \`$branch\`. Before publishing, check whether what this branch changes makes any of these stale, and fix them in this branch:
- README.md: the header facts and counts, and \"What's next\" (pending operator actions, known defects, deferred items)
- docs/planning/README.md: the \"Open\" cell of each Live doc
- docs/planning/OPEN_ITEMS.md: any item this branch finishes or changes"
  planning=$(grep -E '^docs/planning/[^/]+\.md$' <<<"$changed" | grep -vxE 'docs/planning/(CHANGELOG|README)\.md' | sed 's|^docs/planning/||' | paste -sd ' ' -)
  if [ -n "$planning" ] && ! grep -qx 'docs/planning/README.md' <<<"$changed"; then
    check="$check
This branch edits $planning in docs/planning/; the matching rows of docs/planning/README.md may need the same change."
  fi
  add "$check
If nothing is stale (or your instructions forbid editing these files), push again unchanged, and say in your reply what you checked."
fi

[ -n "$reason" ] || exit 0
jq -n --arg s "docs check held the push of $branch" --arg r "$reason" \
  '{systemMessage: $s, hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $r}}'
exit 0
