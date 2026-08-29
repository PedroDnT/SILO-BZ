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
# WHAT WE DIFF AGAINST, AND WHY IT IS NOT HEAD^
# Until 2026-08-29 this compared HEAD^..HEAD, which asks "did THIS COMMIT touch
# the dashboard". That is the wrong question and it silently drops work: land a
# dashboard change in commit A, push an unrelated commit B on top, and the gate
# evaluates B^..B, sees nothing under dashboard/, and skips — so A's change
# never reaches the site. Vercel exposes VERCEL_GIT_PREVIOUS_SHA (the SHA of
# the last successful deployment, populated only when an Ignored Build Step is
# configured), which answers the question we actually mean: "has the dashboard
# changed since what is currently deployed". We use it when the shallow clone
# actually contains that commit, and fall back to HEAD^ when it does not.
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

# Pick the diff base: the last successful deployment if we have it, else the
# parent commit. `git cat-file -e` is the check that matters — Vercel does a
# shallow clone, so the SHA can be set and still be absent from this checkout.
base=""
# Vercel clones shallow, so the previous SHA is essentially NEVER in the
# checkout — measured on deployment 5t9vBkhFVbezBGagY2KBE6ZciYov, where the
# variable was set to 1dac794 and `git cat-file -e` still missed. Without this
# fetch the branch below is dead code and the gate silently stays on HEAD^.
# GitHub allows fetching an arbitrary reachable SHA, and --depth=1 keeps it to
# the one commit whose tree the diff needs.
if [ -n "${VERCEL_GIT_PREVIOUS_SHA:-}" ] \
   && ! git cat-file -e "${VERCEL_GIT_PREVIOUS_SHA}^{commit}" 2>/dev/null; then
    if git fetch --quiet --depth=1 origin "$VERCEL_GIT_PREVIOUS_SHA" 2>/dev/null; then
        echo "  fetched previous SHA   = yes (--depth=1)"
    else
        echo "  fetched previous SHA   = no (fetch refused; falling back)"
    fi
fi

if [ -n "${VERCEL_GIT_PREVIOUS_SHA:-}" ] \
   && git cat-file -e "${VERCEL_GIT_PREVIOUS_SHA}^{commit}" 2>/dev/null; then
    base="$VERCEL_GIT_PREVIOUS_SHA"
    echo "  diff base               = VERCEL_GIT_PREVIOUS_SHA ($base)"
elif git rev-parse --verify HEAD^ >/dev/null 2>&1; then
    base="HEAD^"
    echo "  diff base               = HEAD^ (previous SHA unset, or unreachable even after fetch)"
else
    build "no diff base available (shallow clone, first commit, or unreachable previous SHA)"
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
