#!/usr/bin/env bash
# Copy the database credentials in POSTGRES_URL into the 5 Vercel variables
# the dashboard build reads (EVIDENCE_SOURCE__supabase__*), for Production and
# Preview. Run from your SILO-BZ clone, after `vercel login`.
#
#   bash scripts/set_vercel_db_env.sh
#
# It asks for the URL (postgresql://<user>:<password>@<host>:<port>/<db>?sslmode=require)
# with the typing hidden, so the password never lands in your shell history.
# Use the URL that works today: the one in the GitHub POSTGRES_URL secret
# (GitHub cannot show it back), or a fresh one from Supabase > Connect >
# Session pooler. Nothing is printed except the variable names.
set -euo pipefail
if [ -z "${POSTGRES_URL:-}" ]; then read -rsp 'POSTGRES_URL: ' POSTGRES_URL; echo; fi
: "${POSTGRES_URL:?POSTGRES_URL is empty}"
export POSTGRES_URL

if [ "$(python3 -c 'import os,urllib.parse as u;print(u.urlsplit(os.environ["POSTGRES_URL"]).port or 5432)')" = "6543" ]; then
  echo "port 6543 is the transaction pooler; use the session pooler (5432) URL for the dashboard build" >&2; exit 1
fi

vercel link --yes --project silo-bz --scope deloslabs >/dev/null

parse() {  # $1 = user|password|host|port|database
  python3 - "$1" <<'PY'
import os, sys, urllib.parse as u
p = u.urlsplit(os.environ["POSTGRES_URL"])
v = {"user": p.username, "password": p.password, "host": p.hostname,
     "port": str(p.port or 5432), "database": p.path.lstrip("/") or "postgres"}[sys.argv[1]]
sys.stdout.write(u.unquote(v or ""))
PY
}

for part in host port database user password; do
  name="EVIDENCE_SOURCE__supabase__${part}"
  value="$(parse "$part")"
  [ -n "$value" ] || { echo "empty $part in POSTGRES_URL" >&2; exit 1; }
  for target in production preview; do
    # Update in place so a failed call never leaves the variable deleted;
    # add only when it does not exist yet (first run).
    printf '%s' "$value" | vercel env update "$name" "$target" --sensitive --yes --scope deloslabs >/dev/null 2>&1 ||
      printf '%s' "$value" | vercel env add "$name" "$target" --sensitive --scope deloslabs >/dev/null
  done
  echo "set $name (production, preview)"
done
