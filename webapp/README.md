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
= conta `3.11` falling back to `3.09`, equity matched by
`ds_conta = 'Patrimônio Líquido Consolidado'` (its code varies 2.03/2.08).

The `3.09` fallback is **not** because banks omit `3.11` — Banco do Brasil
(`cd_cvm` 1023, FY2024, `con`) files `3.11` as `Lucro ou Prejuízo Líquido
Consolidado do Período`. `3.09` is profit *before* the statutory profit-sharing
on `3.10`, so it equals net income only where `3.10` is zero. Banks do use a
different chart, but the difference is in what the codes *mean* (`3.01` is
interest income, `3.05` is pre-tax profit) — so never compare a bank's `3.01`
or `3.03` with an industrial company's.

## Run locally

```bash
npm install
export EVIDENCE_SOURCE__supabase__connectionString='postgresql://...'  # same var as dashboard/
npm run sources
npm run dev          # localhost:3000
npm run build        # static site → build/
```

**Not currently deployed.** `vercel.json` hardcodes `cd dashboard` for install/build/output and `scripts/vercel_should_build.sh` only triggers on `dashboard/`, so a change here can never reach Vercel. Run it locally (`npm install && npm run dev`), or add a second Vercel project pointed at this directory or any static host pointed at
`build/`.
