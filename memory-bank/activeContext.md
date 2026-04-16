# Active Context

## Current Goals

- Delos Oracle M1: deploy Anchor program to Solana devnet, run relayer against live BCB data
  - `delos-oracle/` is fully scaffolded; needs `anchor build && anchor deploy --provider.cluster devnet`
  - After deploy: replace placeholder `DeLoSXXX…` program ID in `Anchor.toml` + `relayer/config.py`
  - Copy `target/idl/delos_oracle.json` → `app/public/idl/` for the React dashboard

- Supabase backfill: run `python -m src.ingestor.run_backfill --start-year 2019` once
  with `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` set to populate the fraud-detection DB

- GitHub secrets to configure: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`,
  `ORACLE_KEYPAIR_JSON`, `SOLANA_RPC_URL`, `ANCHOR_PROGRAM_ID`

## Current Blockers

- Anchor CLI + Rust toolchain needed locally for M1 deploy (not available in CI sandbox)
- Real Supabase project needed to test ingestor end-to-end