# Consumers (read-only, query Supabase directly)

Both are **Evidence.dev** projects (Node-based: `npm install && npm run sources && npm run dev`
→ localhost:3000; `npm run build` → `build/`). They connect to the same Supabase Postgres via
`@evidence-dev/postgres` and only read — never write.

- **`dashboard/`** — fund **and market** analytics at
  [https://silo-bz-deloslabs.vercel.app/](https://silo-bz-deloslabs.vercel.app/), 20
  pages. Industry and backdrop: Overview (`/`), Industry Structure (`/industry`),
  Macro Context (`/macro`), Rates and Curves (`/rates`), B3 Markets (`/markets`),
  Short Monitor (`/short`), Follow the Money (`/flows`). By asset class: FI (`/fi`), FIDC Credit Monitor
  (`/fidc`), FII Market (`/fii`), Securitization (`/securit`), ETF (`/etf`).
  Granular: Managers (`/managers`), Fund Explorer (`/fund`), Fund Holdings
  (`/holdings`), Performance (`/performance`), Suspicious Screens (`/suspicious`), Dormant Funds (`/dormant`),
  Filing Behaviour (`/filings`).
  Plus Pipeline Ops (`/ops`).
  Evidence static snapshot (parquet at build). The Vercel project in team
  `deloslabs` is named `silo-bz` (renamed from `silo` on 2026-09-17, so older
  planning docs and changelog rows still say `silo`); that is the
  GitHub/deploy-hook name, not the public URL. Also buildable as a static site
  for any static host.
- **`webapp/`** — Evidence.dev instance for CIA Aberta (listed-company) analytics over the
  `cia_*` tables: Overview (`/`), Financials (`/financials`, consolidated ITR/DFP with
  margins/ROE), Events (`/events`, IPE + Fato Relevante feed). Mind the data conventions
  in `webapp/README.md` (accented `ÚLTIMO`, net income conta 3.11 **only** — no 3.09
  fallback anywhere, because 3.09 is pre-statutory-participations profit, not net
  income, and banks do generally file 3.11; equity by name). `setor` is the partition
  key for peer comparisons — `/growth` ranks within sector for that reason.
