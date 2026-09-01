#!/usr/bin/env bash
# =============================================================================
# Apply the analytical layer (src/store/analytical/01-19) to Supabase.
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

# TCP keepalives — same values as src/store/pg_client.py. CI talks to Supabase
# through the IPv4 session pooler (aws-*.pooler.supabase.com:5432). A CREATE
# MATERIALIZED VIEW sends nothing on the wire for minutes; without probes the
# pooler drops the client (~4m44s on Daily CVM Ingest #207) while the backend
# keeps AccessExclusiveLock from DROP ... CASCADE, and every later file that
# touches the same relation dies the same way. Do not print the URL: it holds
# the password.
_KEEPALIVE_QS="keepalives=1&keepalives_idle=30&keepalives_interval=10&keepalives_count=3"
_KEEPALIVE_KV="keepalives=1 keepalives_idle=30 keepalives_interval=10 keepalives_count=3"
if [[ "$POSTGRES_URL" != *"keepalives="* ]]; then
  case "$POSTGRES_URL" in
    postgres://*|postgresql://*)
      if [[ "$POSTGRES_URL" == *"?"* ]]; then
        POSTGRES_URL="${POSTGRES_URL}&${_KEEPALIVE_QS}"
      else
        POSTGRES_URL="${POSTGRES_URL}?${_KEEPALIVE_QS}"
      fi
      ;;
    *)
      POSTGRES_URL="${POSTGRES_URL} ${_KEEPALIVE_KV}"
      ;;
  esac
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
