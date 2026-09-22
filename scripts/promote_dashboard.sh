#!/usr/bin/env bash
# Publish the dashboard build the deploy hook produced, then PROVE it published.
#
# WHY THIS EXISTS
# Between 2026-09-18 and 2026-09-22 the public site did not move while four
# production deployments went READY on top of it. Measured 2026-09-22:
#
#   GET silo-bz-deloslabs.vercel.app/macro       31,867 bytes, no "Inside the IPCA"
#   GET silo-bz-git-main-deloslabs.vercel.app/…  39,505 bytes, the section present
#   aliases on dpl_f9YsSJ… (newest production)   the branch alias, and nothing else
#   both vercel.app project domains              still bound to dpl_54vMGARv4w1DAhyx…
#                                                (6646c0c, PR #275), updatedAt
#                                                2026-09-18T00:17:56Z, never since
#
# So a production deployment stopped taking the project domains. Every build was
# correct; none of them was published. Nobody noticed for four days because the
# only things anyone checked were row counts in the build log and the
# deployment's READY state — both true, neither the site. CLAUDE.md already says
# row counts in a build log and pixels on the public URL are different
# observations. This script is that sentence made executable.
#
# WHY IT PROMOTES RATHER THAN FIXING AUTO-ASSIGNMENT
# Why auto-assignment stopped is NOT diagnosed (OPEN_ITEMS item 8). Build logs
# do not record aliasing and the API does not expose the decision, so there is
# nothing to read. Promoting explicitly makes the question moot instead of
# unanswered: an explicit promote of a deployment that already holds the domains
# is a no-op, so this is safe whether or not auto-assignment comes back.
#
# TIMING
# daily_ingest fires the deploy hook at the END of ingest (~06:56 UTC measured)
# and the Evidence build takes 17-45 min, so the workflow calling this runs at
# 08:00 UTC. If a long ingest pushes the build past that, this promotes the
# PREVIOUS deployment (harmless) and the verification below fails loudly rather
# than reporting a success it did not observe. A red run once is the correct
# outcome there; a silent freeze for four days is what we are replacing.
#
# EXIT CODES (the usual convention, unlike vercel_should_build.sh)
#   0 -> the public host serves the same build as the branch alias
#   1 -> it does not, and this script could not fix it
set -uo pipefail

PUBLIC_HOST=${PUBLIC_HOST:-silo-bz-deloslabs.vercel.app}
BRANCH_HOST=${BRANCH_HOST:-silo-bz-git-main-deloslabs.vercel.app}
VERCEL_PROJECT_ID=${VERCEL_PROJECT_ID:-prj_1zWxdkrKrs12Ss9TMPaepuaYgDpa}
VERCEL_TEAM_ID=${VERCEL_TEAM_ID:-team_7ysDZks5qlq6ycBQAioNZf7J}
API=${VERCEL_API:-https://api.vercel.com}
VERIFY_TRIES=${VERIFY_TRIES:-10}
VERIFY_DELAY=${VERIFY_DELAY:-15}

# The fingerprint. Evidence writes /data/manifest.json at build time and every
# source's parquet path carries a content hash, so the manifest digest changes
# whenever the data does. Comparing it across two hostnames answers the only
# question that matters — is the public host serving the build that was just
# made — without parsing HTML or trusting a deployment id we were told.
# -f so an HTTP error is a failure rather than a body, and an empty body is
# never a digest: sha256 of nothing is a perfectly good hash, so two dead
# fetches would otherwise "match" and report a broken site as published.
digest() {
    local body
    body=$(curl -fsS --max-time 30 "https://$1/data/manifest.json" 2>/dev/null) || return 1
    [ -n "$body" ] || return 1
    printf '%s' "$body" | sha256sum | cut -d' ' -f1
}

report() {
    local pub branch
    pub=$(digest "$PUBLIC_HOST")
    branch=$(digest "$BRANCH_HOST")
    echo "  $PUBLIC_HOST manifest ${pub:0:16}"
    echo "  $BRANCH_HOST manifest ${branch:0:16}"
    [ -n "$pub" ] && [ "$pub" = "$branch" ]
}

echo "promote_dashboard: publishing the build the deploy hook made"

if [ -z "${VERCEL_TOKEN:-}" ]; then
    echo "::warning::VERCEL_TOKEN unset — cannot promote. Create a token at"
    echo "  Vercel -> Account Settings -> Tokens (scope: team deloslabs)"
    echo "  and store it as the repository secret VERCEL_TOKEN."
    echo "Checking whether the site published on its own:"
    if report; then
        echo "Published: the public host matches the branch alias."
        exit 0
    fi
    echo "::warning::the public host is BEHIND the branch alias and no token is" \
         "available to promote. The dashboard is serving a stale build; see" \
         "docs/planning/OPEN_ITEMS.md item 8."
    exit 1
fi

auth=(-H "Authorization: Bearer $VERCEL_TOKEN")
q="teamId=$VERCEL_TEAM_ID"

newest=$(curl -sS --max-time 30 "${auth[@]}" \
    "$API/v6/deployments?projectId=$VERCEL_PROJECT_ID&target=production&state=READY&limit=1&$q" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin).get("deployments") or [{}]; print(d[0].get("uid") or d[0].get("id") or "")' 2>/dev/null)

if [ -z "$newest" ]; then
    echo "::warning::could not read the newest READY production deployment."
    report && { echo "Published anyway."; exit 0; }
    exit 1
fi
echo "  newest READY production deployment = $newest"

code=$(curl -sS --max-time 30 -o /tmp/promote.out -w '%{http_code}' -X POST \
    "${auth[@]}" "$API/v10/projects/$VERCEL_PROJECT_ID/promote/$newest?$q")
echo "  promote responded $code"
cat /tmp/promote.out 2>/dev/null || true

# The promote is asynchronous, so the answer is the site, not the status code.
for i in $(seq 1 "$VERIFY_TRIES"); do
    echo "verify $i/$VERIFY_TRIES:"
    if report; then
        echo "Published: the public host now serves the branch alias's build."
        exit 0
    fi
    sleep "$VERIFY_DELAY"
done

echo "::error::the public host still does not match the branch alias after" \
     "promoting $newest. The dashboard is serving a stale build; see" \
     "docs/planning/OPEN_ITEMS.md item 8."
exit 1
