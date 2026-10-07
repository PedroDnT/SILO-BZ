# System

SILO pulls Brazilian public financial data, keeps it in one Postgres and serves
it read-only. Four infrastructures, four products.

```
        SOURCES   CVM · B3 · BACEN · IBGE · ANBIMA · FNET · market hosts
                                   │  HTTP pull, never push
                  GitHub Actions   (the ingest compute)
                  fetch → parse → upsert, one audit row per slice
                                   │
                  Supabase Postgres (the only state)
      public   landing tables → normalizing views → dim_/fact_ matviews
      api      views + functions: the contract
           ┌──────────────┬───────────┴──────┬──────────────┬──────────────┐
           ▼              ▼                  ▼              ▼              ▼
   PostgREST · SDK    silo-mcp          dashboard/      research job   diagnosis
   serve/ (local)     Edge Function     Vercel build    read-only      Cloudflare
   └──────── read api.* ───────┘        └── read public directly ──┘   Worker+Container
```

| Part                   | Owns                                                                                                          |
| ---------------------- | ------------------------------------------------------------------------------------------------------------- |
| `src/fetchers`         | Talking to sources. A 404 means "not published yet".                                                          |
| `src/parsers`          | Bytes to typed rows. Invalid rows are dropped.                                                                |
| `src/pipeline`         | Slices, the `cvm_ingest_log` audit, the entrypoints.                                                          |
| `src/store`            | The one writer (`pg_client`), schema, migrations.                                                             |
| `src/store/analytical` | Views, matviews and schema `api`.                                                                             |
| `src/portfolio`        | The diagnosis: statement readers, engine, report, investigator. |
| `deploy/cloudflare`    | The Worker, the engine Container and private R2 for traces.                                                   |
| `sdk/`                 | `silo_client`, the typed Python caller of `api.*`.                                                            |
| `.github/workflows`    | Schedules, recovery and checks.                                                                               |

## Boundaries that matter

1. **`api` vs `public`.** Clients get `api` only; landing tables are revoked
   from `anon`. The dashboard and the research job connect with privileged
   credentials and read `public` directly, so they are not bound by `api`.
2. **Landed vs complete.** `landed_at` is our health; `complete_through` is
   the source's filing calendar.
3. **View vs matview.** A plain view is live; a matview is only as fresh as the
   last analytical apply (see [DATA_FLOW](DATA_FLOW.md#analytical)).
4. **The BDI ratchet.** B3 keeps about 21 business days of lending and flow
   data and publishes no archive. A missed session is lost.
5. **Shared database.** Another application's tables (`messages`, `profiles`,
   `threads`) live in `public`. RLS protects them; this repo does not own them.
6. **Upsert vs replace.** Writes upsert on the natural key and never delete,
   except a re-read CDA month: each fund in the file replaces its rows for that
   month in one transaction. A fund missing from the file keeps its rows.
7. **Stateless diagnosis.** The engine keeps no user portfolio in Supabase;
   masked traces go to R2 only ([DECISIONS](DECISIONS.md)).

`webapp/` exists but is not deployed.

Deeper: [README](../../README.md), [API](../reference/API.md),
[data modeling](../reference/DATA_MODELING.md).
