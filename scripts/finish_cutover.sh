#!/usr/bin/env bash
# =============================================================================
# Finish Supabase setup. Run AFTER putting the Supabase DB password into
# .env (replacing [SUPABASE_DB_PASSWORD]).
#
#   bash scripts/finish_cutover.sh
#
# Steps:
#   1. Verify the Supabase connection + that the schema is present.
#   2. Apply the analytical layer (src/store/analytical/01-12) via psql.
#   3. Update the GitHub Actions POSTGRES_URL secret (so the runner writes to Supabase).
#   4. Smoke ingest: a small BACEN refresh to prove rows land in Supabase.
#   5. Re-report row counts.
# =============================================================================
set -uo pipefail
cd "$(dirname "$0")/.."

PY=.venv/bin/python
# Prefer psql on PATH (Linux, Intel Macs); fall back to the Homebrew libpq keg.
PSQL="psql"
if ! command -v psql >/dev/null 2>&1 && [ -x "/opt/homebrew/opt/libpq/bin/psql" ]; then
  PSQL="/opt/homebrew/opt/libpq/bin/psql"
fi

# --- load POSTGRES_URL from .env ---------------------------------------------
POSTGRES_URL="$(grep -E '^POSTGRES_URL=' .env | head -1 | cut -d= -f2-)"
export POSTGRES_URL
if [[ -z "$POSTGRES_URL" || "$POSTGRES_URL" == *"[SUPABASE_DB_PASSWORD]"* || "$POSTGRES_URL" == *"<password>"* ]]; then
  echo "ERROR: POSTGRES_URL in .env still has the database password placeholder."
  echo "       Paste the real Supabase database password into .env first."
  exit 1
fi

echo "==> [1/5] Verifying Supabase connection + schema"
$PY scripts/supabase_cutover.py || { echo "Connection/verify failed"; exit 1; }

echo
echo "==> [2/5] Applying analytical layer (continue-on-error; pg_cron may be skipped)"
for f in src/store/analytical/0[1-9]_*.sql \
         src/store/analytical/10_*.sql \
         src/store/analytical/11_indexes.sql \
         src/store/analytical/12_grants_and_rls.sql; do
  [ -f "$f" ] || continue
  echo "  -- $f"
  $PSQL "$POSTGRES_URL" -v ON_ERROR_STOP=0 -q -f "$f" 2>&1 | sed 's/^/     /' | tail -5
done

echo
echo "==> [3/5] Updating GitHub Actions POSTGRES_URL secret"
if command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
  printf '%s' "$POSTGRES_URL" | gh secret set POSTGRES_URL && echo "  GH secret POSTGRES_URL updated."
else
  echo "  SKIPPED: gh not authenticated. Run manually:"
  echo "    gh secret set POSTGRES_URL --body \"\$POSTGRES_URL\""
fi

echo
echo "==> [4/5] Smoke ingest: BACEN last 7 days -> Supabase"
# Fail loudly if the smoke ingest errors — step 4 exists to PROVE rows land,
# so a broken schema/credentials/network must not be reported as success.
$PY - <<'PYEOF'
import asyncio, datetime, os, sys
sys.path.insert(0, os.getcwd())
from src.pipeline.bacen_pipeline import BacenIngestor
async def main():
    ing = BacenIngestor()
    start = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    totals = await ing.backfill(start=start)
    print("  BACEN upserted:", totals)
    if sum(totals.values()) == 0:
        raise SystemExit("Smoke ingest upserted 0 rows — cutover NOT verified.")
asyncio.run(main())
PYEOF
if [ $? -ne 0 ]; then
  echo "ERROR: smoke ingest failed — cutover NOT verified. Aborting."
  exit 1
fi

echo
echo "==> [5/5] Final row counts"
$PY scripts/supabase_cutover.py

echo
echo "Cutover complete. Run a full daily ingest any time with:  $PY -m src.pipeline.run_daily"
