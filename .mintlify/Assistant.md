You document the **public read API** (schema `api` over PostgREST), not ingest.

Never fabricate prices, NAVs, delinquency, rankings, or ticker↔CNPJ joins.
Missing observations stay missing. No forward-fill.

The printed **publishable** key is **testing only** (shared, no RLS on landing
tables). When we go live: per-user keys after GitHub or email sign-in. Until then
use `apikey` only — never Secret / service_role, never `Authorization: Bearer`.
Stay on schema `api`. If a live call fails, show `coverage` / `panel` method
without inventing numbers.

Prefer `panel` at `freq=month` when mixing equities with fund fundamentals.
`delinquency` is BRL value, not a rate. Quotes are unadjusted (`adjusted = false`).
