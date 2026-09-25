#!/usr/bin/env bash
# Agent driver for SILO-BZ: boot an ephemeral Postgres, apply the full schema
# (base + migrations + analytical layer), launch the serve/ read API against
# it, and smoke the HTTP contract with curl.
#
# Usage (from the repo root):
#   bash .claude/skills/run-silo-bz/smoke.sh            # full run
#   KEEP_SERVER=1 bash .claude/skills/run-silo-bz/smoke.sh   # leave API running
#
# Env overrides:
#   SILO_PG_BIN   directory containing initdb, pg_ctl, psql, createdb
#   SILO_PG_DIR   socket+data parent dir  (default /var/tmp/silopg_run)
#   SILO_PG_PORT  postgres port           (default 55433)
#   SILO_API_PORT serve/ HTTP port        (default 8080)
#
# The Postgres instance is left running afterwards (cheap, reusable by the
# Evidence dashboard and by re-runs); only the Flask server is torn down
# unless KEEP_SERVER=1.
#
# Mirrors .github/workflows/test.yml `sql-compile`: roles anon/authenticated,
# schema.sql then migrations in lexical order (ON_ERROR_STOP), analytical
# layer under the silo.ci_smoke_bypass GUC (empty-DB smoke RAISEs downgrade
# to WARNINGs; production behavior unchanged).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PGBIN="${SILO_PG_BIN:-}"
if [ -z "$PGBIN" ]; then
  if command -v initdb >/dev/null 2>&1; then
    PGBIN="$(dirname "$(command -v initdb)")"
  elif [ -x /usr/lib/postgresql/16/bin/initdb ]; then
    PGBIN=/usr/lib/postgresql/16/bin
  elif command -v brew >/dev/null 2>&1; then
    BREW_PGBIN="$(brew --prefix postgresql@16 2>/dev/null || true)/bin"
    [ -x "$BREW_PGBIN/initdb" ] && PGBIN="$BREW_PGBIN"
  fi
fi
if [ -z "$PGBIN" ] || [ ! -x "$PGBIN/initdb" ]; then
  echo "PostgreSQL server binaries missing. Install PostgreSQL 16 or set SILO_PG_BIN." >&2
  exit 1
fi

# Linux CI uses the postgres OS account; Homebrew Postgres uses the current
# macOS account. initdb refuses to run as root.
if [ "$(uname -s)" = Darwin ]; then
  PGUSER="$(id -un)"
  pg_run() { "$@"; }
else
  PGUSER=postgres
  pg_run() { su postgres -c "$(printf '%q ' "$@")"; }
fi
PGDIR="${SILO_PG_DIR:-/var/tmp/silopg_run}"
PGPORT="${SILO_PG_PORT:-55433}"
APIPORT="${SILO_API_PORT:-8080}"
DB=silo_run
URL="postgresql://${PGUSER}@/${DB}?host=${PGDIR}&port=${PGPORT}"

say() { printf '\n== %s ==\n' "$*"; }

# --- 1. Postgres: init once, start if stopped -------------------------------
if [ ! -d "$PGDIR/data" ]; then
  say "initdb $PGDIR/data"
  mkdir -p "$PGDIR"
  if [ "$(uname -s)" != Darwin ]; then chown postgres "$PGDIR"; fi
  pg_run "$PGBIN/initdb" -D "$PGDIR/data" -A trust >/dev/null
fi
if ! pg_run "$PGBIN/pg_ctl" -D "$PGDIR/data" status >/dev/null 2>&1; then
  say "starting postgres on $PGDIR:$PGPORT"
  pg_run "$PGBIN/pg_ctl" -D "$PGDIR/data" -l "$PGDIR/log" \
    -o "-p $PGPORT -k $PGDIR -c listen_addresses=" start >/dev/null
fi

# --- 2. Database + roles + schema (idempotent) ------------------------------
pg_run "$PGBIN/psql" -d postgres -h "$PGDIR" -p "$PGPORT" -Atc "SELECT 1 FROM pg_database WHERE datname='$DB'" \
  | grep -q 1 || pg_run "$PGBIN/createdb" -h "$PGDIR" -p "$PGPORT" "$DB"
"$PGBIN/psql" "$URL" -Atc "SELECT 1 FROM pg_roles WHERE rolname='anon'" | grep -q 1 || \
  "$PGBIN/psql" "$URL" -v ON_ERROR_STOP=1 -q \
    -c "CREATE ROLE anon NOLOGIN;" -c "CREATE ROLE authenticated NOLOGIN;"

# The skip sentinel must be the LAST thing a full bootstrap creates, not the
# first. Gating on cvm_ingest_log (created at the top of schema.sql) meant a
# bootstrap that died in a later migration or in the analytical layer left a
# data dir that every re-run then skipped, so /v1/coverage kept failing until
# the directory was deleted by hand. api.catalog() is created by the last
# analytical file, so its absence means "not fully applied" and the whole
# idempotent bootstrap runs again.
#
# It must also match THIS checkout. The data dir outlives branches, so a DB
# bootstrapped on one branch kept serving that branch's api.* functions after
# a checkout that changed 19_api_contract.sql (observed: a v35 worktree
# smoked green against v32 functions). api.catalog()->>'version' is
# CATALOG_VERSION baked into the SQL, so a mismatch re-applies everything.
want_version=$(sed -n 's/^CATALOG_VERSION = \([0-9]*\).*/\1/p' "$REPO/serve/catalog.py")
have_version=$("$PGBIN/psql" "$URL" -Atc \
  "SELECT CASE WHEN to_regprocedure('api.catalog()') IS NOT NULL
               THEN api.catalog()->>'version' END" 2>/dev/null | tr -d '[:space:]')
if [ "$have_version" != "$want_version" ]; then
  say "applying schema.sql + migrations (db catalog '${have_version:-none}', repo v$want_version)"
  "$PGBIN/psql" "$URL" -v ON_ERROR_STOP=1 -q -f "$REPO/src/store/schema.sql"
  for f in "$REPO"/src/store/migrations/*.sql; do
    "$PGBIN/psql" "$URL" -v ON_ERROR_STOP=1 -q -f "$f" || { echo "FAIL $f"; exit 1; }
  done
  say "applying analytical layer (empty-DB bypass)"
  ( cd "$REPO" && PATH="$PGBIN:$PATH" POSTGRES_URL="$URL" PGOPTIONS="-c silo.ci_smoke_bypass=on" \
      bash scripts/apply_analytical.sh ) >/dev/null
  # Prove it: if the sentinel is still missing the bootstrap did not finish,
  # and failing here is far better than a green smoke over a half-built DB.
  have_version=$("$PGBIN/psql" "$URL" -Atc "SELECT api.catalog()->>'version'" 2>/dev/null | tr -d '[:space:]')
  [ "$have_version" = "$want_version" ] || {
    echo "bootstrap incomplete: db catalog '${have_version:-none}', repo v$want_version" >&2; exit 1; }
fi

# --- 3. Launch serve/ and wait for readiness --------------------------------
say "starting serve/ API on 127.0.0.1:$APIPORT"
SILO_API_DATABASE_URL="$URL" SILO_API_PORT="$APIPORT" \
  "$REPO/.venv/bin/python" -m serve.app >"$PGDIR/serve.log" 2>&1 &
SRV=$!
[ -n "${KEEP_SERVER:-}" ] || trap 'kill $SRV 2>/dev/null || true' EXIT

up=""
for _ in $(seq 1 20); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$APIPORT/v1/catalog")" = 200 ] \
    && { up=1; break; }
  kill -0 $SRV 2>/dev/null || { echo "server died:"; tail -5 "$PGDIR/serve.log"; exit 1; }
  sleep 1
done
[ -n "$up" ] || { echo "server never became ready"; tail -5 "$PGDIR/serve.log"; exit 1; }

# --- 4. Assert the HTTP contract --------------------------------------------
fail=0
check() { # check <expected-code> <path>
  local code; code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$APIPORT$2")
  if [ "$code" = "$1" ]; then echo "OK   $2 -> $code"; else echo "FAIL $2 -> $code (want $1)"; fail=1; fi
}
say "smoking the contract"
check 200 /v1/catalog
check 200 /v1/tools
check 200 /v1/coverage
check 404 /v1/quotes/NOPE9          # unknown ticker: honest 404, never a fabricated close
curl -s "http://127.0.0.1:$APIPORT/v1/catalog" | grep -q '"agent"' \
  && echo "OK   catalog carries the agent preamble" \
  || { echo "FAIL catalog missing agent preamble"; fail=1; }

if [ -n "${KEEP_SERVER:-}" ]; then
  echo; echo "server left running: pid $SRV, http://127.0.0.1:$APIPORT (log: $PGDIR/serve.log)"
fi
say "result"
[ "$fail" = 0 ] && echo "SMOKE PASS" || { echo "SMOKE FAIL"; exit 1; }
