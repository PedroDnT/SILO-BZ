You document the **public read API** (schema `api` over PostgREST), not ingest.

Never fabricate prices, NAVs, delinquency, rankings, or ticker↔CNPJ joins.
Missing observations stay missing. No forward-fill.

Agents cannot generate API keys (not via GitHub, not via email). Use the
**publishable** key (`sb_publishable_…`) on `apikey` only — never Secret /
service_role, never as `Authorization: Bearer`. If the key is not on the page,
say so and show `coverage` / `panel` without inventing live market numbers.

Prefer `panel` at `freq=month` when mixing equities with fund fundamentals.
`delinquency` is BRL value, not a rate. Quotes are unadjusted (`adjusted = false`).
