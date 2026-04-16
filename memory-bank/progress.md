# Progress

## Done

- [x] Refactor: Pydantic v2 patterns, datetime timezone, .gitignore
- [x] Mintlify docs site (10 MDX pages + docs.json)
- [x] CVM API: all doc types (FIDC/FIP/FIAGRO/SECURIT), LCA/LCI aliases, validation config
- [x] CVM API: CNPJ cross-entity registry endpoint (`/api/v1/cnpj/{cnpj}`) — 3 data planes
- [x] Part 1 — Supabase Ingestor (`src/ingestor/`)
  - schema.sql: 6 tables with raw JSONB + fraud-query indexes
  - CVMIngestor + BacenIngestor; run_backfill.py + run_daily.py
  - `.github/workflows/daily_ingest.yml` (06:00 UTC cron)
- [x] Part 2 — Delos Oracle / Solana (`delos-oracle/`)
  - Anchor program: MacroState PDA (SELIC/CDI/IPCA/IGP-M/USDBRL as scaled integers)
  - Python relayer: BacenClient → anchorpy → Solana devnet
  - React + Vite dashboard: reads PDA, Tailwind dark theme
  - `.github/workflows/oracle_crank.yml` (hourly cron)
- [x] Test suite: 63 tests, 100% passing

## Doing

- [ ] Delos Oracle M1: anchor build + deploy to devnet (needs local Anchor CLI)
- [ ] Supabase initial backfill (needs live SUPABASE_URL + SERVICE_KEY)

## Next

- [ ] Delos Oracle M2: React dashboard live at Vercel URL (after M1 deploy)
- [ ] Delos Oracle M3: TimeFM SELIC/IPCA forecasts posted on-chain alongside actuals
- [ ] Delos Oracle M4: Pyth PTAX cross-reference discrepancy signal
- [ ] Delos Oracle M5: COPOM LLM hawkish/dovish score on-chain
- [ ] Wire rate limiting via slowapi (env vars already defined in .env.example)
- [ ] Tests for src/ingestor/ (mock Supabase client)