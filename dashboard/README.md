# iliquid dashboard

Evidence.dev analytics dashboard backed by the Supabase Postgres pipeline.

## Pages

| Page                | Path           | What it shows                                                                                             |
| ------------------- | -------------- | --------------------------------------------------------------------------------------------------------- |
| Overview            | `/`            | AUM by entity type (12mo), FIDC sector delinquency, live row counts                                       |
| FIDC Credit Monitor | `/fidc`        | Sector delinquency trend (24mo), aging buckets, top delinquent funds, red flags                           |
| FII Market          | `/fii`         | FII vs FIAGRO AUM, yield distribution (p10–p90), top funds by dividend yield                              |
| Suspicious Screens  | `/suspicious`  | Zombie growth, captive vehicles, evergreen aging, overdue securit series                                  |
| Performance         | `/performance` | Per-asset-class fund performance ranking (who beat peers in a window) + methodology                       |
| ETF                 | `/etf`         | ETF universe by provider / segment / index from `cvm_etf_registry` (price/NAV/return pending an ETF feed) |

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
a static build — point any static host at `build/`.

### Vercel configuration (`vercel.json`)

The build settings are pinned in `dashboard/vercel.json` rather than left to Vercel's
dashboard, deliberately:

```json
{
  "framework": null,
  "buildCommand": "npm run sources && npm run build",
  "outputDirectory": "build"
}
```

`"framework": null` (the "Other" preset) is the important part. Evidence is built on
SvelteKit, so Vercel's auto-detection identifies the project as SvelteKit and applies the
**serverless SSR** preset — but `evidence build` emits a purely **static** site into
`build/`. The mismatch deploys functions that have nothing valid to serve, and requests
fail with `500 FUNCTION_INVOCATION_FAILED`. Pinning the preset to static removes the
functions entirely.

Vercel **project settings must not override this** — leave Build & Output Settings
unoverridden so `vercel.json` wins. Keeping it in the repo also means the config is
reviewable and survives project re-creation; host config that lives only in a provider
dashboard is exactly what left the (now removed) Netlify site failing every build with
nothing in the repo to fix.

**Required environment variables** (Vercel → Settings → Environment Variables). Evidence
reads datasource credentials from `EVIDENCE_SOURCE__<source>__<option>`; the source is named
`supabase` (`sources/supabase/connection.yaml`), so `npm run sources` needs:

```
EVIDENCE_SOURCE__supabase__host
EVIDENCE_SOURCE__supabase__port          # 5432
EVIDENCE_SOURCE__supabase__database      # postgres
EVIDENCE_SOURCE__supabase__user          # postgres.<project-ref> for the pooler
EVIDENCE_SOURCE__supabase__password
EVIDENCE_SOURCE__supabase__ssl           # true
```

`npm run sources` queries Postgres at **build time** and bakes the results into the static
output, so a broken/expired database credential fails the build — the same credential
problem that has stalled the ingestion pipeline will also break dashboard deploys.
