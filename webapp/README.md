# iliquid webapp

Evidence.dev instance for CIA Aberta (publicly listed company) analytics — in progress.

Connects to the same Supabase Postgres database as `dashboard/` via `@evidence-dev/postgres`.

## Run locally

```bash
npm install
npm run sources   # pull schema from Supabase
npm run dev       # http://localhost:3000
```

## Status

CIA financial statement ingestion (`cia_filing`, `cia_account` tables) is being built on the `feat/cia-financials` branch. Dashboard pages will follow once the backfill is complete.
