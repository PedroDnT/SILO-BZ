#!/usr/bin/env bash
# =============================================================================
# Apply the analytical layer (src/store/analytical/01-12) to Supabase.
#
#   bash scripts/apply_analytical.sh
#
# Run this AFTER a full ingest has populated the base tables. Several files have
# smoke-check guards (e.g. 01_dim_fund) that RAISE on an empty database, so the
# analytical layer cannot be built until fund/securit/cia data exists.
#
# Failure handling (addresses PR review — no masked failures):
#   - Each file runs with ON_ERROR_STOP=1 so psql returns a real exit code.
#   - pg_cron being unavailable (08_cron_schedules) is tolerated with a warning.
#   - ANY other failure is reported in full and makes this script exit non-zero,
#     so a bad view/function/grant can never be silently skipped.
# =============================================================================
set -uo pipefail
cd "$(dirname "$0")/.."

# Prefer psql on PATH (Linux, Intel Macs, CI); fall back to the Homebrew libpq keg.
PSQL="psql"
if ! command -v psql >/dev/null 2>&1 && [ -x "/opt/homebrew/opt/libpq/bin/psql" ]; then
  PSQL="/opt/homebrew/opt/libpq/bin/psql"
fi

POSTGRES_URL="${POSTGRES_URL:-$(grep -E '^POSTGRES_URL=' .env 2>/dev/null | head -1 | cut -d= -f2-)}"
if [[ -z "$POSTGRES_URL" || "$POSTGRES_URL" == *"[SUPABASE_DB_PASSWORD]"* || "$POSTGRES_URL" == *"<password>"* ]]; then
  echo "ERROR: POSTGRES_URL is unset or still has the password placeholder." >&2
  exit 1
fi

failed=()
warned=()
applied=0

for f in src/store/analytical/[0-9][0-9]_*.sql; do
  [ -f "$f" ] || continue
  base="$(basename "$f")"
  out="$("$PSQL" "$POSTGRES_URL" -v ON_ERROR_STOP=1 -q -f "$f" 2>&1)"
  rc=$?
  if [ $rc -eq 0 ]; then
    applied=$((applied + 1))
    echo "  ok   $base"
  elif [ "$base" = "08_cron_schedules.sql" ] && grep -qi "pg_cron" <<<"$out"; then
    warned+=("$base")
    echo "  warn $base — pg_cron not enabled (Dashboard → Database → Extensions); skipped"
  else
    failed+=("$base")
    echo "  FAIL $base"
    sed 's/^/         /' <<<"$out" | tail -6
  fi
done

echo
echo "Applied: $applied   Warnings: ${#warned[@]}   Failures: ${#failed[@]}"
if [ ${#failed[@]} -gt 0 ]; then
  echo "Analytical layer apply FAILED for: ${failed[*]}" >&2
  echo "(If these are 'smoke check ... no rows' errors, ingest data first, then re-run.)" >&2
  exit 1
fi
echo "Analytical layer applied successfully."
