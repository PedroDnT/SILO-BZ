# iliquid webapp — CIA Aberta

Evidence.dev instance for **CIA Aberta** (listed-company) analytics, reading the
`cia_*` tables in the same Supabase Postgres as `dashboard/`. Read-only — never
writes.

| Page | Route | Data |
|------|-------|------|
| Overview | `/` | `cia_company` registry, top companies by revenue, latest Fatos Relevantes |
| Financials | `/financials` | Consolidated ITR/DFP from `cia_account` (DRE + BPA/BPP): revenue, net income, margins, ROE |
| Events | `/events` | `cia_event` IPE filings: volume, categories, Fato Relevante feed |

Conventions baked into the queries (see `docs/` and migration `04_cia.sql`):
`escopo = 'con'` (consolidated), `ordem_exerc = 'ÚLTIMO'` (accented), net income
= conta `3.11` falling back to `3.09` (banks), equity matched by
`ds_conta = 'Patrimônio Líquido Consolidado'` (its code varies 2.03/2.08).

## Run locally

```bash
npm install
export EVIDENCE_SOURCE__supabase__connectionString='postgresql://...'  # same var as dashboard/
npm run sources
npm run dev          # localhost:3000
npm run build        # static site → build/
```

Deploys like `dashboard/`: Vercel (primary) or any static host pointed at
`build/`.
