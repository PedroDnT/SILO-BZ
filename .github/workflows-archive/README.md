# Archived GitHub Actions

Workflows in this folder are **not** registered by GitHub (only
`.github/workflows/*.yml` are). They stay in git so the YAML is recoverable.

| File | Why it left the dispatch list |
|---|---|
| `audit_coverage.yml` | Never run. Same job: `python scripts/audit_coverage.py` with `POSTGRES_URL`. |
| `audit_matview_dependents.yml` | One-off during CASCADE work. Same job: `python scripts/audit_matview_dependents.py`. |

Live Actions (keep these):

- `daily_ingest.yml` — cron + `daily` / `analytics-only` / `b3-backfill`
- `backfill.yml` — full CVM historical (parallel FI years)
- `watchdog.yml` — 08:00 UTC staleness re-run

To run an archived audit locally:

```bash
POSTGRES_URL=… python scripts/audit_coverage.py
POSTGRES_URL=… python scripts/audit_matview_dependents.py
```
