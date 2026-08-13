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

The build settings are pinned in the **repo-root** `vercel.json` rather than left to
Vercel's dashboard, deliberately:

```json
{
  "framework": null,
  "installCommand": "cd dashboard && npm install",
  "buildCommand": "cd dashboard && npm run preflight && npm run sources && npm run build",
  "outputDirectory": "dashboard/build"
}
```

It lives at the repo root (not in `dashboard/`) because the Vercel project's root
directory is the repository root — a `dashboard/vercel.json` is silently ignored there.
`"framework": null` (the "Other" preset) is the important part. With the root directory
unset, Vercel auto-detects the repo as a **Python** project (Flask `app.py` +
`requirements.txt`) and deploys the localhost-only control plane as a serverless
function, which crashes every request with `500 FUNCTION_INVOCATION_FAILED`. Pinning
framework to null and the build to the Evidence static output removes the functions
entirely.

Vercel **project settings must not override this** — leave Build & Output Settings
unoverridden so `vercel.json` wins. Keeping it in the repo also means the config is
reviewable and survives project re-creation; host config that lives only in a provider
dashboard leaves a failing build with nothing in the repo to fix.

**Required environment variables** (Vercel → Settings → Environment Variables). Evidence
reads datasource credentials from `EVIDENCE_SOURCE__<source>__<option>`; the source is named
`supabase` (`sources/supabase/connection.yaml`), so `npm run sources` needs:

```
EVIDENCE_SOURCE__supabase__host
EVIDENCE_SOURCE__supabase__port          # 5432
EVIDENCE_SOURCE__supabase__database      # postgres
EVIDENCE_SOURCE__supabase__user          # postgres.<project-ref> for the pooler
EVIDENCE_SOURCE__supabase__password
```

TLS is **not** an env var — it is pinned in `sources/supabase/connection.yaml`, because
Supabase rejects unencrypted connections (`connection is insecure — try using
sslmode=require`) and the setting is not a secret.

`npm run sources` queries Postgres at **build time** and bakes the results into the static
output, so a broken/expired database credential fails the build — the same credential
problem that has stalled the ingestion pipeline will also break dashboard deploys.

### Build preflight

`npm run preflight` (wired into the Vercel `buildCommand` ahead of `sources`)
connects with the same `EVIDENCE_SOURCE__supabase__*` variables Evidence uses
and asserts that a handful of expected tables exist.

It exists because the failure it replaces is close to undiagnosable.
`@evidence-dev/postgres` discards the underlying Postgres error:

```js
const lengthQuery = await connection.query(...).catch(() => undefined);
const rowCount = lengthQuery.rows[0].rows;   // TypeError on undefined
```

so pointing the dashboard at the wrong database makes every source fail with
`Cannot read properties of undefined (reading 'rows')` — the same message for a
missing table, a typo'd column, or a permissions problem — and the build then
hangs until the pooler drops the connection (~5 minutes) and reports
`Connection terminated unexpectedly`. The preflight turns that into one line
naming the host, the database, and the tables it could not find.

The most common cause is `EVIDENCE_SOURCE__supabase__host` pointing at a
Supabase **preview-branch** database (empty by design) rather than the project
`POSTGRES_URL` ingests into. Compare the two hosts first.
