---
name: run-silo-bz
description: Build, run, and drive SILO-BZ locally. Use when asked to start, run or smoke the serve/ read API, exercise an api.* SQL function, launch, click through or screenshot the Evidence dashboard, or run the test suite.
---

SILO-BZ is an ingest pipeline plus two read surfaces: the `serve/` Flask API
over schema `api`, and the Evidence dashboard in `dashboard/`. Nothing runs
without a database, so every driver here uses an **ephemeral local Postgres**
that `smoke.sh` creates. It **never touches production Supabase**.

| Driver | Does |
|---|---|
| `.claude/skills/run-silo-bz/smoke.sh` | boots Postgres, applies schema + migrations + analytical layer, launches `serve/`, asserts the HTTP contract with curl |
| `.claude/skills/run-silo-bz/dashboard.sh` | `up` / `shot` / `down` for the Evidence dev server against that DB |
| `.claude/skills/run-silo-bz/screenshot.mjs` | Playwright page load, optional `--click`, prints `TITLE:` / `H1:`, saves a PNG |

All paths are relative to the repo root. Verified 2026-09-25 on macOS
(Apple Silicon, Homebrew `postgresql@16`, Node 26, Python 3.12 `.venv`). The
scripts also carry the Linux-container branches (`su postgres`,
`/opt/node22`, `/opt/pw-browsers/chromium`) from the 2026-09-23 run there;
those were not re-run this time.

## Prerequisites (macOS)

`initdb`/`pg_ctl`/`psql` on `PATH` (Homebrew `postgresql@16`), `.venv/` with
`requirements.txt` installed. Playwright is **not** a repo dependency;
install it once into its own folder:

```bash
mkdir -p ~/.cache/silo-pw && cd ~/.cache/silo-pw && printf '{"private":true}\n' > package.json
npm install --no-audit --no-fund playwright
npx playwright install chromium
```

The `package.json` line is not optional; see Gotchas.

## Run (agent path): API

```bash
bash .claude/skills/run-silo-bz/smoke.sh
```

Ends in `SMOKE PASS` after asserting `/v1/catalog` 200 (with the agent
preamble), `/v1/tools` 200, `/v1/coverage` 200 and `/v1/quotes/NOPE9` 404.
It takes seconds: the data dir in `/var/tmp/silopg_run` persists, and the
schema is re-applied only when `api.catalog()`'s version differs from
`CATALOG_VERSION` in this checkout. Keep the API up for manual curls with
`KEEP_SERVER=1`. Overrides: `SILO_PG_DIR`, `SILO_PG_PORT` (55433),
`SILO_API_PORT` (8080).

## Run (agent path): SQL functions directly

Most PRs change `src/store/analytical/19_api_contract.sql`, not HTTP. After
`smoke.sh`, call the function as PostgREST would:

```bash
psql "postgresql://$(id -un)@/silo_run?host=/var/tmp/silopg_run&port=55433" -c "select count(*) as rows from api.balance_sheets('PETR4')" -c "select api.catalog()->>'version' as catalog"
```

On an empty DB that returns 0 rows and the repo's catalog version. To check
the logic, insert a few rows into `cia_company` / `cia_account` (natural
keys only) and call the function. To iterate on one file, re-apply it with
`psql "$URL" -v ON_ERROR_STOP=1 -f src/store/analytical/19_api_contract.sql`.

## Run (agent path): dashboard

```bash
bash .claude/skills/run-silo-bz/dashboard.sh up
bash .claude/skills/run-silo-bz/dashboard.sh shot / /tmp/dash_click.png --click "FIDC Credit Monitor"
bash .claude/skills/run-silo-bz/dashboard.sh shot /markets /tmp/dash_markets.png
bash .claude/skills/run-silo-bz/dashboard.sh down
```

`up` runs `npm ci` if needed, `npm run sources` against the local DB (129
sources, ~3 s), prunes empty sources, and starts `npm run dev` on
127.0.0.1:3000. `shot` prints `CLICKED: … -> /fidc/`, `TITLE:` and `H1:` to
assert on, and exits 1 if the dev server crashed. **Open the PNG.** On an
empty DB, pages render their headings and query panels. Sources that
returned 0 rows show `Catalog Error: Table with name … does not exist`,
which is expected locally.

## Run (human path)

`python -m serve.app` with `SILO_API_DATABASE_URL` exported, or
`cd dashboard && npm run dev`. Both need a database, so use the drivers above.

## Test

```bash
.venv/bin/pytest tests/ -q
```

~1,866 tests, ~20 s, all offline. **On macOS, 2 fail and that is expected:**
`test_vercel_build_gate.py::test_fnet_input_validation[2025-01-01-…]` runs
the `backfill.yml` date check, which uses GNU `date -d`. BSD `date` rejects
it. They pass on Linux CI.

## Gotchas

- **`npm run dev` dies on a 0-byte parquet.** A 0-row source can leave an
  empty `aum_by_entity.parquet` that `manifest.json` still lists. The first
  page load makes DuckDB fail with `too small to be a Parquet file`, esbuild
  deadlocks, and the server exits. Deleting the file is not enough: the dev
  server recreates it from the manifest. `dashboard.sh up` removes both the
  file and the manifest entry. The older note that only `npm run build`
  fails is out of date.
- **A dead dev server can look alive.** A previous server still holding
  :3000 answers curl with 200 while the new one has already died, and the
  browser then gets `ERR_CONNECTION_REFUSED`. `dashboard.sh` kills old
  servers first.
- **`npm install` in a folder with no `package.json` walks up.** On this
  Mac it installed Playwright into `~/package.json` / `~/node_modules`,
  editing an unrelated project. Always create the `package.json` first.
- **Playwright version and browser build must match.** Playwright 1.63
  wants `chromium-1243`; an older cached `chromium-1234` isn't picked up,
  so run `npx playwright install chromium`.
- **The data dir outlives branches.** Before the version check,
  `smoke.sh` served the api functions from whatever branch first
  bootstrapped `/var/tmp/silopg_run`: a v35 checkout passed smoke against
  v32 SQL.
- **Unix socket paths are capped at 103 bytes on macOS.** A long
  `SILO_PG_DIR` (for example under the Claude scratchpad) fails with `could
  not create any Unix-domain sockets`. Keep it short, like the default.
- **Evidence needs `sslmode=disable`** for the local socket server;
  `dashboard.sh` sets it.
- **The analytical layer RAISEs on an empty DB by design**; `smoke.sh`
  applies it with `PGOPTIONS="-c silo.ci_smoke_bypass=on"`. Never set that
  against production.
- **`pkill -f serve.app` kills your own shell** (it matches its own command
  line). Use `pkill -f "serve[.]app"`.

## Troubleshooting

- **`su: Authentication failed` from smoke.sh on macOS**: you have the
  pre-macOS `smoke.sh`. This version runs `pg_ctl` as the current user on
  Darwin.
- **`page.goto: net::ERR_CONNECTION_REFUSED`**: the dev server crashed.
  Check `/var/tmp/silopg_run/evidence-dev.log` for `too small to be a
  Parquet file`, then `dashboard.sh down && dashboard.sh up`.
- **`playwright not found in: …`**: run the Prerequisites install, or point
  `SILO_PLAYWRIGHT` at a `node_modules` dir that contains `playwright/`.
- **`bootstrap incomplete: db catalog '…', repo vN`**: a migration or
  analytical file failed partway through. Re-run `smoke.sh` to see the
  error; it re-applies idempotently.
