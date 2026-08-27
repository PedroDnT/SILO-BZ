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
# DATA FRESHNESS IS A SEPARATE TRIGGER, NOT THIS ONE
# The dashboard is a static snapshot: new rows in Supabase only reach it when a
# build runs. Skipping code-irrelevant commits must therefore NOT be the only
# thing standing between ingest and the site. The daily ingest workflow calls a
# Vercel deploy hook after it finishes (see .github/workflows/daily_ingest.yml),
# which is both more reliable than hoping someone pushes and better timed: it
# runs when no other build is competing for the database.
#
# FAIL-OPEN
# Every uncertain case builds. A needless build costs 30 minutes; a wrongly
# skipped one silently ships a stale or broken site.
set -uo pipefail

WATCHED=(dashboard vercel.json scripts/vercel_should_build.sh)

build()  { echo "BUILD: $1";  exit 1; }
skip()   { echo "SKIP: $1";   exit 0; }

# Vercel does a shallow clone; without a parent commit there is nothing to diff
# against, so build.
if ! git rev-parse --verify HEAD^ >/dev/null 2>&1; then
    build "no parent commit available (shallow clone or first commit)"
fi

changed=$(git diff --name-only HEAD^ HEAD -- "${WATCHED[@]}" 2>/dev/null)
status=$?

if [ "$status" -ne 0 ]; then
    build "could not diff against HEAD^ (git exited $status)"
fi

if [ -n "$changed" ]; then
    build "watched paths changed:
$changed"
fi

skip "no change under ${WATCHED[*]} — the built site would be byte-identical.
     Data refreshes come from the daily deploy hook, not from this commit."
