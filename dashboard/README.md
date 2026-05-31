# iliquid dashboard

Evidence.dev analytics dashboard backed by the Supabase Postgres pipeline.

## Pages

| Page | Path | What it shows |
| ---- | ---- | ------------- |
| Overview | `/` | AUM by entity type (12mo), FIDC sector delinquency, live row counts |
| FIDC Credit Monitor | `/fidc` | Sector delinquency trend (24mo), aging buckets, top delinquent funds, red flags |
| FII Market | `/fii` | FII vs FIAGRO AUM, yield distribution (p10–p90), top funds by dividend yield |
| Suspicious Screens | `/suspicious` | Zombie growth, captive vehicles, evergreen aging, overdue securit series |

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

For deployment, point a static host at `build/` or use Netlify (config in the root `.netlify/`).
