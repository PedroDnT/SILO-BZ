#!/usr/bin/env bash
# Vercel `ignoreCommand`: decide whether this commit needs a dashboard build.
#
# EXIT CODES ARE INVERTED FROM THE USUAL CONVENTION (Vercel's contract):
#   exit 0 -> SKIP the build
#   exit 1 -> BUILD
#
# WHY THIS EXISTS
# A dashboard build runs `evidence sources`, which fires ~90 SQL queries at the
# production Supabase and takes 25-45 minutes. Vercel builds every commit on
# every branch, so a commit that touches only tests/ or .github/ paid that full
# price for an identical output.
#
# That waste is not free, it is actively harmful. On 2026-08-26 four builds
# overlapped: shared queries slowed 5x (aging_buckets 12s -> 103s), two builds
# hit BUILD_EXCEEDED_MAXIMUM_TIME, and — worst — the concurrent scans of
# cvm_fi_perfil blocked `ALTER TABLE cvm_fi_perfil ADD COLUMN` in the schema
# apply until the server killed it, so migration 14 and every later migration
# never ran. Three of those four builds were for commits that did not touch the
# dashboard at all.
#
# WHAT STILL TRIGGERS A BUILD
#   - anything under dashboard/   (the site itself)
#   - vercel.json                 (build config)
#   - this script                 (so a change to the rule is always exercised)
#
# WHAT WE DIFF AGAINST: HEAD^, AND WHY THAT IS RIGHT HERE
# main only ever advances by MERGE commits (git log --format=%p shows two
# parents on each). For a merge commit, HEAD^ is the first parent — the tip of
# main before the PR — so `git diff HEAD^ HEAD` is the ENTIRE pull request, not
# one commit of it. That is exactly the question a production build should ask.
#
# An earlier version of this file tried VERCEL_GIT_PREVIOUS_SHA (the SHA of the
# last successful deployment) on the theory that HEAD^ misses a dashboard change
# buried under a later commit. That failure needs several NON-merge commits
# pushed straight to main, which this repo's PR workflow does not produce, and
# the variable turned out to be unusable anyway: Vercel clones shallow, so the
# commit is absent, and fetching it is REFUSED on the build runner —
#     fetched previous SHA = no (fetch refused; falling back)
# on deployment 528UqNVSMVnfCcQqtL4LmkgtHHWB. Both attempts were dead code that
# still looked like a fix. Removed rather than left in as decoration.
#
# The residual gap is real but small: on a multi-commit FEATURE BRANCH, a
# preview build can skip when an earlier commit touched the dashboard and the
# tip did not. Preview builds are not the published site, and the merge commit
# rebuilds it correctly.
#
# DATA FRESHNESS IS A SEPARATE TRIGGER — AND THIS SCRIPT USED TO BLOCK IT
# The dashboard is a static snapshot: new rows in Supabase only reach it when a
# build runs. The daily ingest workflow therefore POSTs a Vercel deploy hook
# after it finishes (.github/workflows/daily_ingest.yml), which is better timed
# than a human push: it runs when no other build is competing for the database.
#
# But a deploy hook fires on a COMMIT THAT DID NOT CHANGE — that is the entire
# point of it — so every path-diff rule, this one included, skips it. Measured
# on 2026-08-29 01:40 UTC: run 191 POSTed the hook, Vercel returned 201 and
# created deployment dpl_DosS5xPKtYoroMGREr6XyaV4yYPq on main@9664535, this
# script found no dashboard change, and the deployment went straight to
# CANCELED. The hook has never been able to refresh data, and the comment here
# previously claimed it could.
#
# Vercel's documented system environment variables carry no deploy-hook flag we
# can branch on, so the DECISION LOG below prints what is actually set on every
# run. A hook-triggered deployment's log is the evidence needed to write that
# rule — do not guess it.
#
# FAIL-OPEN
# Every uncertain case builds. A needless build costs 30 minutes; a wrongly
# skipped one silently ships a stale or broken site.
set -uo pipefail

WATCHED=(dashboard vercel.json scripts/vercel_should_build.sh)

build()  { echo "BUILD: $1";  exit 1; }
skip()   { echo "SKIP: $1";   exit 0; }

# Decision log. Printed before any exit so a skipped build still records why,
# and so a deploy-hook deployment reveals which variables distinguish it.
echo "vercel_should_build: deciding"
echo "  VERCEL_GIT_COMMIT_SHA   = ${VERCEL_GIT_COMMIT_SHA:-<unset>}"
echo "  VERCEL_GIT_PREVIOUS_SHA = ${VERCEL_GIT_PREVIOUS_SHA:-<unset>}"
echo "  VERCEL_GIT_COMMIT_REF   = ${VERCEL_GIT_COMMIT_REF:-<unset>}"
echo "  VERCEL_ENV              = ${VERCEL_ENV:-<unset>}"
echo "  HEAD                    = $(git rev-parse --short HEAD 2>/dev/null || echo '<no HEAD>')"

# Diff base. On a merge commit HEAD^ is the first parent — main before the PR —
# so this covers the whole pull request. See the header for why the last
# successful deployment's SHA is not used instead.
base=""
if git rev-parse --verify HEAD^ >/dev/null 2>&1; then
    base="HEAD^"
    echo "  diff base               = HEAD^ (previous main for a merge commit)"
else
    build "no parent commit available (shallow clone or first commit)"
fi

changed=$(git diff --name-only "$base" HEAD -- "${WATCHED[@]}" 2>/dev/null)
status=$?

if [ "$status" -ne 0 ]; then
    build "could not diff $base..HEAD (git exited $status)"
fi

if [ -n "$changed" ]; then
    build "watched paths changed since $base:
$changed"
fi

skip "no change under ${WATCHED[*]} since $base — the built site would be
     byte-identical. NOTE: a deploy hook fired for a data refresh also lands
     here, because the commit itself is unchanged. If this run WAS a deploy
     hook, the variables logged above are the evidence for a rule that lets it
     through; see the header."
