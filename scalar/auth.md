# Authentication

SILO's API surface is schema `api` exposed through Supabase PostgREST. All calls need an API key in the `apikey` header (or as a query parameter — but prefer the header).

## Two tiers

| Tier              | Key                        | Statement timeout | Who uses it         |
| ----------------- | -------------------------- | ----------------- | ------------------- |
| **anon**          | Supabase anon (public) key | 3 seconds         | Everyone by default |
| **authenticated** | Supabase JWT               | 8 seconds         | Signed-in users     |

The anon key is published in the Supabase project settings. It is safe to embed in client code — it gives read-only access to schema `api` only. Landing tables, ingest tables, and `cvm_ingest_log` are not accessible to either client role.

## Getting the anon key

Supabase dashboard → **Settings → API → Project API keys → anon (public)**.

The URL is fixed: `https://zcjbtpxuhdekpwcxmepn.supabase.co/rest/v1`.

## When to use a JWT

The authenticated tier raises the statement timeout from 3s to 8s. That is its only advantage — it unlocks no additional data. Most research calls return well under 3s when the database is warm. The practical difference is:

- **Cold calls** (first call after idle) can take 16–43s on a warehouse this size and will cancel at the ceiling regardless of tier. Warm, the same calls return in 0.3–1.9s.
- **Long date windows** on fundamentals (e.g., PETR4 six years of consolidated lines) take ~450ms warm — within the anon budget.

If you are building an application that makes calls after long idle periods, consider adding a warmup call before the user-facing request.

## Making authenticated calls

```bash
curl -X POST \
  'https://zcjbtpxuhdekpwcxmepn.supabase.co/rest/v1/rpc/quote_history' \
  -H 'apikey: YOUR_ANON_KEY' \
  -H 'Authorization: Bearer YOUR_JWT' \
  -H 'Content-Type: application/json' \
  -d '{"p_ticker": "PETR4", "p_from": "2019-01-02", "p_to": "2026-09-30"}'
```

The `apikey` header is always required even when sending a JWT.

## What is not exposed

- Schema `public` — landing tables, ingest audit log, analytical matviews
- `api.screen_*` functions — forensic screens; no grant to `anon` or `authenticated`
- `silo_api` role — internal role for the local Flask adapter (`serve/`), not a PostgREST credential

The MCP server (`https://zcjbtpxuhdekpwcxmepn.supabase.co/functions/v1/silo-mcp`) uses the same anon key automatically.
