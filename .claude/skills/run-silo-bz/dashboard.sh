#!/usr/bin/env bash
# Agent driver for the Evidence dashboard against the ephemeral Postgres that
# smoke.sh boots. Run smoke.sh once first (it creates and schemas the DB).
#
#   bash .claude/skills/run-silo-bz/dashboard.sh up      # sources + dev server on :3000
#   bash .claude/skills/run-silo-bz/dashboard.sh shot /macro /tmp/macro.png [--click "Text"]
#   bash .claude/skills/run-silo-bz/dashboard.sh down
#
# Env: SILO_PG_DIR / SILO_PG_PORT as in smoke.sh, SILO_DASH_PORT (default 3000).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SKILL="$REPO/.claude/skills/run-silo-bz"
PGDIR="${SILO_PG_DIR:-/var/tmp/silopg_run}"
PGPORT="${SILO_PG_PORT:-55433}"
PORT="${SILO_DASH_PORT:-3000}"
if [ "$(uname -s)" = Darwin ]; then PGUSER="$(id -un)"; else PGUSER=postgres; fi
LOG="$PGDIR/evidence-dev.log"

stop_dev() {
  # A dev server left from an earlier `up` keeps the port, and the new one
  # dies behind it while curl still gets 200 from the old one.
  pkill -f "[e]vidence dev" 2>/dev/null || true
  pkill -f "$REPO/dashboard/node_modules/.*[v]ite" 2>/dev/null || true
  sleep 1
}

case "${1:-}" in
  up)
    cd "$REPO/dashboard"
    [ -d node_modules ] || npm ci --no-audit --no-fund
    stop_dev
    # sslmode=disable: Evidence's connector defaults to SSL and the local
    # socket server has none.
    EVIDENCE_SOURCE__supabase__connectionString="postgresql://${PGUSER}@/silo_run?host=${PGDIR}&port=${PGPORT}&sslmode=disable" \
      npm run sources >"$PGDIR/evidence-sources.log" 2>&1 \
      || { tail -20 "$PGDIR/evidence-sources.log"; exit 1; }
    echo "sources: $(grep -c 'Finished' "$PGDIR/evidence-sources.log") finished"
    # A 0-row source can leave a 0-byte parquet that the manifest still lists.
    # On the first page load DuckDB reads it ("too small to be a Parquet
    # file"), esbuild deadlocks and the dev server exits. Drop those entries
    # so the page reports a missing table instead of taking the server down.
    node -e '
      const fs=require("fs"),base=".evidence/template/",p=base+"static/data/manifest.json";
      const m=JSON.parse(fs.readFileSync(p)); let n=0;
      for (const [s,files] of Object.entries(m.renderedFiles)) {
        m.renderedFiles[s]=files.filter(f=>{const fp=base+f;
          const ok=fs.existsSync(fp)&&fs.statSync(fp).size>0;
          if(!ok){n++; if(fs.existsSync(fp)) fs.unlinkSync(fp);} return ok;});
      }
      fs.writeFileSync(p,JSON.stringify(m)); console.log("empty sources pruned:",n);'
    nohup npm run dev -- --port "$PORT" --host 127.0.0.1 >"$LOG" 2>&1 &
    for _ in $(seq 1 60); do
      [ "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/")" = 200 ] \
        && { echo "dashboard up: http://127.0.0.1:$PORT (log: $LOG)"; exit 0; }
      sleep 1
    done
    echo "dashboard never answered; tail of $LOG:"; tail -20 "$LOG"; exit 1
    ;;
  shot)
    path="${2:-/}"; out="${3:-/tmp/dash.png}"; shift $(( $# < 3 ? $# : 3 ))
    node "$SKILL/screenshot.mjs" "http://127.0.0.1:$PORT$path" "$out" "$@"
    if grep -qE "too small to be a Parquet|deadlock" "$LOG" 2>/dev/null; then
      echo "dev server crashed (see $LOG)"; exit 1
    fi
    ;;
  down)
    stop_dev; echo "dashboard stopped"
    ;;
  *)
    echo "usage: $0 up | shot <path> <out.png> [--click \"Link text\"] | down" >&2; exit 2
    ;;
esac
