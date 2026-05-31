#!/usr/bin/env bash
# =============================================================================
# Finish Supabase setup. Run AFTER putting the Supabase DB password into
# .env (replacing [SUPABASE_DB_PASSWORD]).
#
#   bash scripts/finish_cutover.sh
#
# Steps:
#   1. Verify the Supabase connection + that the schema is present.
#   2. Update the GitHub Actions POSTGRES_URL secret (so the runner writes to Supabase).
#   3. Smoke ingest: a small BACEN refresh to prove rows land in Supabase.
#   4. Re-report row counts.
#
# The analytical layer is applied separately by scripts/apply_analytical.sh,
# which must run AFTER a full ingest (its smoke-check guards need real data).
# =============================================================================
set -uo pipefail
cd "$(dirname "$0")/.."

PY=.venv/bin/python

# --- load POSTGRES_URL from .env ---------------------------------------------
POSTGRES_URL="$(grep -E '^POSTGRES_URL=' .env | head -1 | cut -d= -f2-)"
export POSTGRES_URL
if [[ -z "$POSTGRES_URL" || "$POSTGRES_URL" == *"[SUPABASE_DB_PASSWORD]"* || "$POSTGRES_URL" == *"<password>"* ]]; then
  echo "ERROR: POSTGRES_URL in .env still has the database password placeholder."
  echo "       Paste the real Supabase database password into .env first."
  exit 1
fi

echo "==> [1/4] Verifying Supabase connection + schema"
$PY scripts/supabase_cutover.py || { echo "Connection/verify failed"; exit 1; }

echo
echo "==> [2/4] Updating GitHub Actions POSTGRES_URL secret"
# CI runs on IPv4-only GitHub runners; the direct db.<ref>.supabase.co host is
# IPv6-only, so the secret MUST use the IPv4-safe session pooler — never the
# local direct URL. Prefer SUPABASE_POOLER_URL (env or .env); refuse to set a
# direct URL as the secret.
ci_secret_ok=0
CI_URL="${SUPABASE_POOLER_URL:-$(grep -E '^SUPABASE_POOLER_URL=' .env 2>/dev/null | head -1 | cut -d= -f2-)}"
if [[ -z "$CI_URL" ]]; then
  if [[ "$POSTGRES_URL" == *"db."*".supabase.co"* ]]; then
    echo "  SKIPPED: POSTGRES_URL is the direct (IPv6-only) host — unsafe for CI."
    echo "  Set the session pooler URL and re-run, e.g.:"
    echo "    export SUPABASE_POOLER_URL='postgresql://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require'"
    echo "  (Supabase Dashboard -> Connect -> Session pooler). Secret left unchanged."
    CI_URL=""
  else
    CI_URL="$POSTGRES_URL"   # already a pooler/CI-safe URL
  fi
fi
if [[ -n "$CI_URL" ]]; then
  if command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
    if printf '%s' "$CI_URL" | gh secret set POSTGRES_URL; then
      echo "  GH secret POSTGRES_URL set to the pooler URL."
      ci_secret_ok=1
    else
      echo "ERROR: 'gh secret set POSTGRES_URL' failed — CI still points at the old DB. Aborting." >&2
      exit 1
    fi
  else
    echo "  SKIPPED: gh not authenticated. Run manually:"
    echo "    printf '%s' \"\$SUPABASE_POOLER_URL\" | gh secret set POSTGRES_URL"
  fi
fi

echo
echo "==> [3/4] Smoke ingest: BACEN last 7 days -> Supabase"
# Fail loudly if the smoke ingest errors — this step exists to PROVE rows land,
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
echo "==> [4/4] Final row counts"
$PY scripts/supabase_cutover.py

echo
if [ "$ci_secret_ok" -eq 0 ]; then
  echo "WARNING: GitHub Actions POSTGRES_URL secret was NOT updated (step 2 was skipped)."
  echo "         CI jobs will continue using the old database until you set the secret manually:"
  echo "           printf '%s' \"\$SUPABASE_POOLER_URL\" | gh secret set POSTGRES_URL"
  echo
fi
echo "Cutover complete. Next steps:"
echo "  1. Full ingest:        $PY -m src.pipeline.run_daily"
echo "  2. Analytical layer:   bash scripts/apply_analytical.sh   (after the full ingest)"
