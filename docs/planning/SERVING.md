# Serving data — user-driven requirements

The product is not “we ingested CVM and B3.” The product is: a researcher
(human or agent) can resolve an identifier, fetch an honest panel of mixed
market and fundamental series, and take that into a notebook without ever
being handed a fabricated price, fill, or ticker↔CNPJ match.

This file is the ordered requirements to get there. Do not skip a step: later
ones assume earlier ones hold. The HTTP surface is documented in
[docs/API.md](../API.md); this file is the *why / in what order / done when*.

## Outcome (definition of done)

A caller who only knows “PETR4 vs this FIDC’s delinquency since 2019” can:

1. Discover which metrics exist and at which grain (`GET /v1/catalog`).
2. Resolve names to ids without invented joins (`GET /v1/lookup`, `/v1/universe`).
3. Pull a `(id, date, metric, value)` panel, long or wide (`GET /v1/panel`).
4. See JSON `null` where the warehouse has no observation.
5. Trust `as_of` from `/v1/coverage` before claiming freshness.
6. Do the analysis (corr, OLS, event study) **in the notebook**.

Not done: a quote widget, a PostgREST dump of landing tables, or a
`POST /v1/query` that returns Pearson as if that were the product.

## Users (who drives each requirement)

| User | Job | Success looks like |
|---|---|---|
| **Researcher** | Mix B3 prints with CVM NAV/delinquency/flows | One panel, two grains aligned on `freq=month`, nulls stay null |
| **Agent** | Answer an analytical question from tools | Catalog once, then lookup, then panel — never invent a metric |
| **Chart / app** | Draw one ticker or one fund | `/v1/quotes/{ticker}?range=1y`, `/v1/funds/{cnpj}/nav` |
| **Operator** | Keep the warehouse true | Ingest + `cvm_ingest_log`; read API cannot write |

Integrity rules in `CLAUDE.md` apply to every step: never fabricate, preserve
provenance, validate before upsert, idempotent `ON CONFLICT`.

---

## Step 0 — Contract exists (done)

**User:** everyone downstream of ingest.

**Requirement.** Schema `api` is the only client surface. Landing tables stay
in `public`. HTTP (`serve/`) is an adapter: one `SELECT` / `api.*()` per
handler. Prices are unadjusted. Default cash board is `02`.

**Acceptance**

- [x] `src/store/analytical/19_api_contract.sql` defines `api.quotes`,
      `api.funds`, `api.panel`, `api.lookup`, `api.universe`, `api.coverage`.
- [x] `serve/app.py` exposes `/v1/quotes`, `/v1/funds`, `/v1/panel`,
      `/v1/lookup`, `/v1/universe`.
- [x] `docs/API.md` describes the researcher loop ending at the notebook.

**Do not reopen.** Do not GRANT `anon` on `b3_cotahist`. Do not add a second
fetch style (`POST /v1/query`) next to `/v1/panel`.

---

## Step 1 — Agents can discover the contract (this change)

**User:** an agent (or a new human) who does not know our column names.

**Requirement.** A static catalog names every metric, grain, constraint, and
HTTP route. Tool specs point at those routes. Analysis is described as a
notebook reduction of a panel, not as an API answer.

**Acceptance**

- [x] `GET /v1/catalog` returns `kind: catalog`, `primitive: panel`, the
      metric map, constraints, and examples that call `/v1/panel`.
- [x] `GET /v1/tools` returns OpenAI-style tools: `silo_catalog`,
      `silo_lookup`, `silo_universe`, `silo_panel`, `silo_coverage`.
- [x] No `/v1/query` route. Catalog text does not tell anyone to POST one.
- [x] `serve.app._PANEL_METRICS` is `tuple(METRICS)` so the allow-list cannot
      drift from the catalog.

**Why this step is first among remaining work.** Without it, agents invent
metrics and joins. Wiring this does not need a live database.

---

## Step 2 — The SQL actually runs

**User:** researcher hitting `/v1/panel` against Supabase, not a mock.

**Requirement.** `19_api_contract.sql` is applied and called. Substring tests
(`assert "api.panel" in sql`) are not proof.

**Acceptance**

- [x] `19_api_contract.sql` applied on Silo via `analytics-only` (2026-08-16).
- [x] Operator smokes: `quote_latest('PETR4')`, `panel(...)`, `coverage()` (SQL
      errors fail; 0 rows is coverage, not a broken function).
- [x] Phone path: **Actions → Tests → Run workflow** runs read-only `api.*`
      smokes (`test.yml` job `api-smoke`). Does not `apply_analytical.sh`.
- [ ] Ephemeral Postgres in CI that applies `schema.sql` + migrations +
      `apply_analytical.sh` still later — `01_dim_fund` `RAISE`s on an empty DB.
- [x] Full `apply_analytical.sh` (01 then 19) leaves `api.funds` intact when
      19 runs in the same pass.

**Blocks.** Compile on Silo is done. Remaining: a throwaway-Postgres job so a
PR cannot merge SQL that only substring-matches. Until then, dispatch
`api-smoke` after analytical changes.

---

## Step 3 — Serving cannot fall over a panel

**User:** researcher asking for 50 ids × 10 metrics × 20 years.

**Requirement.** Limits are enforced in SQL and connections are pooled. A 400
must happen *before* Postgres materializes and Python `fetchall()`s the body.

**Acceptance**

- [ ] `api.panel` takes a `LIMIT` (or the function itself caps rows). HTTP
      `_MAX_PANEL` / `_MAX_POINTS` are not checked only after `fetchall()`.
- [ ] `serve/` uses one pooled client (Supabase **transaction** pooler,
      port 6543) via `SILO_API_DATABASE_URL`. `get_pg_client()` is not called
      per request and connections are closed/returned.
- [ ] Runtime `statement_timeout` on the read role (the `SET` in 19 applies
      only to the DDL transaction that creates the objects).
- [ ] `os.environ["POSTGRES_URL"] = …` inside a request handler is gone.

**Blocks.** Step 0’s API is correct and still unsafe to put on the internet.

---

## Step 4 — Honest time and honest returns

**User:** researcher correlating month-end NAV with “month-end” equity close.

**Requirement.** Derived numbers are only computed where the warehouse has
adjacent observations. Stale last-prints are labeled.

**Acceptance**

- [ ] Daily `close_return` is null when the previous session is not the
      previous calendar day (or is documented as “previous *session*” in both
      catalog and SQL — pick one and test it). A three-month halt must not
      yield one print-to-print ratio labeled as a daily return.
- [ ] Monthly panel rows carry `obs_date` (the actual session) next to
      `period` (month truncated). A stock last printed on the 3rd is not
      silently a month-end close.
- [ ] Catalog `meaning` strings match the SQL after the change; bump
      `CATALOG_VERSION`.

**Blocks.** Factor work on the wide matrix will otherwise treat a halt as a
return and a mid-month last print as month-end.

---

## Step 5 — Lookup and universe are usable

**User:** agent resolving “Petrobras” or listing FIDC names.

**Requirement.** Discovery queries are bounded, deterministic, and indexed.

**Acceptance**

- [ ] `api.lookup` `ILIKE` patterns escape `%` / `_` in user input.
- [ ] `LIMIT 20` has `ORDER BY` (relevance or name) so the 20 rows are stable.
- [ ] Trigram (or equivalent) index on `dim_fund.fund_name` and
      `cia_company.denom_cia` if lookup stays `ILIKE '%q%'`.
- [ ] `api.universe` does not `GROUP BY ticker` over the full COTAHIST
      history to satisfy `LIMIT 50` — use a distinct-ticker side table or
      `DISTINCT ON` from a recent window.

**Blocks.** Agents timeout or get a random 20 names; researchers cannot
trust identifier search.

---

## Step 6 — Privilege boundary is real

**User:** anyone holding the publishable key.

**Requirement.** `anon` / `authenticated` can read `api.*` and nothing else
that matters. `SECURITY DEFINER` is not a substitute for grants.

**Acceptance**

- [ ] Decide explicitly: expose schema `api` on the Supabase Data API, **or**
      keep PostgREST off and serve only through `serve/`. Document the choice
      in `docs/API.md`.
- [ ] `SET search_path = ''` (or `pg_temp`) on every `SECURITY DEFINER`
      function; all names stay schema-qualified (they already are).
- [ ] `api.funds` / `api.quotes` views: either `security_invoker = true` plus
      grants on the underlying objects, or keep owner-privileged and **revoke**
      `anon` from `public` landing tables. Do not leave both doors open.
- [ ] Read role `silo_api`: `USAGE` on `api`, `SELECT` on api views, `EXECUTE`
      on api functions, no `INSERT`/`UPDATE`. `SILO_API_DATABASE_URL` uses it.

**Blocks.** Shipping HTTP in front of a role that can also `SELECT` ingest
logs and the options tape is not the serving outcome.

---

## Step 7 — Put it on a URL researchers will actually call

**User:** researcher outside this VM.

**Requirement.** HTTPS in front of `serve/`, read-only DB URL, cache headers
already on the handlers.

**Acceptance**

- [ ] Gateway (Vercel / any reverse proxy) terminates TLS and forwards to
      `python -m serve.app` (or a container of just `serve/`).
- [ ] Bind stays `127.0.0.1` on the origin; the gateway is the public socket.
- [ ] `GET /v1/health` is the uptime probe; `GET /v1/coverage` is the
      freshness probe. Both are in the catalog.
- [ ] Historical series (`to` in the past) cache `max-age=86400`; latest
      quote `max-age=300`; catalog `max-age=86400` (bump `version` on change).

Ingest remains GitHub Actions cron → Supabase (and the pipeline CLI). Serving
does not share an ingest HTTP server — that Flask app (`app.py` / `src/api/`)
was removed.

---

## Step 8 — Widen the panel, same grain (later)

**User:** researcher mixing CIA line items or BACEN macro with PETR4.

**Requirement.** New metrics join the catalog and `api.panel`. No new API
style. Ticker↔`cia_company` is still not invented — only add a match when it
exists as data.

**Acceptance**

- [ ] Each new metric has `id_type`, `grain`, `source`, `meaning` in
      `serve/catalog.py` `METRICS`.
- [ ] `api.panel` emits it as another `(id, date, metric, value)` union arm.
- [ ] Catalog `version` increments. Examples updated.
- [ ] Offline fixture test plus Step 2 smoke call.

---

## What we will not do

- Fabricate a last close, a filled month, or a ticker↔CNPJ join.
- Serve Pearson / rank / spread over HTTP so agents stop at those four answers.
- Expose `cvm_ingest_log`, `b3_cotahist` (options tape), or Portuguese landing
  columns as the user API.
- Mix ingest triggers with the read API (the old ingest Flask is deleted).
- Reintroduce a public FastAPI mesh, Docker-as-source-of-truth, or `b3_calc_api`.

## How to tell where we are

| Step | Status | Evidence |
|---|---|---|
| 0 Contract | done | `19_api_contract.sql`, `serve/app.py`, `docs/API.md` |
| 1 Catalog | done | `GET /v1/catalog`, `GET /v1/tools` |
| 2 SQL smoke | operator path | Silo apply + **Actions → Tests** `api-smoke`; ephemeral PG still later |
| 3 Limits / pool | open | `_MAX_PANEL` after `fetchall()`; new conn per request |
| 4 Honest time | open | daily `close_return` unguarded; no `obs_date` |
| 5 Lookup | open | `ILIKE %q%`, `LIMIT` without `ORDER BY` |
| 6 Privileges | open | `anon` grants vs Data API exposure undecided |
| 7 HTTPS | open | `serve/` binds 127.0.0.1 only |
| 8 More metrics | later | CIA / BACEN not in `METRICS` |
