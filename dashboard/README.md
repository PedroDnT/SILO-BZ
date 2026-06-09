# iliquid dashboard

Evidence.dev analytics dashboard backed by the Supabase Postgres pipeline.

## Pages

| Page | Path | What it shows |
| ---- | ---- | ------------- |
| Overview | `/` | AUM by entity type (12mo), FIDC sector delinquency, live row counts |
| FIDC Credit Monitor | `/fidc` | Sector delinquency trend (24mo), aging buckets, top delinquent funds, red flags |
| FII Market | `/fii` | FII vs FIAGRO AUM, yield distribution (p10–p90), top funds by dividend yield |
| Suspicious Screens | `/suspicious` | Zombie growth, captive vehicles, evergreen aging, overdue securit series |
| Performance | `/performance` | Per-asset-class fund performance ranking (who beat peers in a window) + methodology |
| ETF | `/etf` | ETF universe by provider / segment / index from `cvm_etf_registry` (price/NAV/return pending an ETF feed) |

## Data source

Connects to Supabase Postgres via `@evidence-dev/postgres`. The `supabase` source is configured in `sources/supabase/connection.yaml`. Credentials are injected at build time via environment variables or the Evidence settings UI.

```bash
npm install
npm run sources   # pull schema from Supabase
npm run dev       # http://localhost:3000
```

## Build

```bash
npm run build     # outputs to build/
```

Deployed to **Vercel** (project `iliquid-nightly`, primary live target). Can also be served as
a static build — point any static host at `build/`, or use Netlify (config in the root `.netlify/`).
