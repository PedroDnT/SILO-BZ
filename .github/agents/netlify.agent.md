# ProjThis repo, `PedroDnT/iliquid_nightly`, is a Python data-ingestion and analytics project for Brazilian financial datasets, mainly CVM and BACEN. It is not primarily a static frontend app.

Key commands:

- Install: `pip install -r requirements.txt`
- Test: `pytest`
- Daily ingestion: `python -m src.pipeline.run_daily`
- Backfill: `python -m src.pipeline.run_backfill`
- Local API: `flask --app app run`

Database is Neon Serverless Postgres via `POSTGRES_URL`. Prefer pooled `-pooler` Neon URLs for CI/serverless ingestion and direct URLs for schema/admin work. Never commit secrets.

Daily ingestion should usually use `CVM_DAILY_SCOPE=core`, prioritizing FI/FIDC/FIAGRO monthly datasets. Long historical backfills should stay in GitHub Actions or another batch runtime, not Netlify Functions.

Before creating Netlify config, inspect the repo and identify the intended deploy target: static dashboard/docs, lightweight functions, or something else. Do not assume Vite/Next/npm build defaults. Do not deploy long-running ingestion as Netlify Functions unless explicitly redesigned for Netlify limits.

When editing, make small focused changes, preserve existing Python structure, keep CLI/API compatibility, use env vars for runtime tuning, and add/update tests.
