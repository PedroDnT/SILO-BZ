---
name: run-silo-bz
description: Build, run, and drive SILO-BZ locally. Use when asked to start or smoke the serve/ read API, run the pipeline verification, launch or screenshot the Evidence dashboard, or run the test suite.
---

SILO-BZ is a headless ingestion pipeline plus a read-only Flask API
(`serve/`) and an Evidence.dev dashboard (`dashboard/`). There is no
runnable "app" without a database, so the driver is
`.claude/skills/run-silo-bz/smoke.sh`: it boots an **ephemeral local
Postgres** (Unix socket, no TCP), applies the full schema + analytical
layer, launches `serve/` against it, and asserts the HTTP contract with
curl. The dashboard is driven with `npm run dev` +
`.claude/skills/run-silo-bz/screenshot.mjs` (pre-installed Chromium).

All paths are relative to the repo root. Never point any of this at
production Supabase — the ephemeral instance is the point.

## Prerequisites

Already present in the standard container: Python 3.12 venv at `.venv/`
(else `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`),
PostgreSQL 16 server binaries at `/usr/lib/postgresql/16/bin` with a
`postgres` system user, Node 22 at `/opt/node22/bin`, global
`playwright@1.56` under `/opt/node22/lib/node_modules`, and Chromium at
`/opt/pw-browsers/chromium`. Nothing needed `apt-get` in this container.

## Run (agent path): API smoke

```bash
bash .claude/skills/run-silo-bz/smoke.sh
```

First run takes ~2 min (initdb + schema + 25 migrations + analytical
layer); re-runs skip all of that and finish in seconds. Ends with
`SMOKE PASS` after asserting: `/v1/catalog` 200 (with the agent
preamble), `/v1/tools` 200, `/v1/coverage` 200, `/v1/quotes/NOPE9` 404
(unknown ticker is an honest 404, never a fabricated close).

To keep the API up for manual curls:

```bash
KEEP_SERVER=1 bash .claude/skills/run-silo-bz/smoke.sh
curl -s http://127.0.0.1:8080/v1/lookup?q=petro   # 404 on an empty DB — correct
```

Defaults: Postgres data+socket in `/var/tmp/silopg_run` port 55433, API
on 8080. Override with `SILO_PG_DIR` / `SILO_PG_PORT` / `SILO_API_PORT`.
The Postgres stays running between invocations (server log:
`$SILO_PG_DIR/serve.log`). Connection string for direct psql:

```bash
psql "postgresql://postgres@/silo_run?host=/var/tmp/silopg_run&port=55433"
```

## Run (agent path): Evidence dashboard

Uses the same ephemeral Postgres (run smoke.sh once first). `sslmode=disable`
is mandatory — Evidence's postgres connector defaults to SSL and the
socket server has none.

```bash
cd dashboard   # node_modules already present; else: npm install --no-audit --no-fund
EVIDENCE_SOURCE__supabase__connectionString="postgresql://postgres@/silo_run?host=/var/tmp/silopg_run&port=55433&sslmode=disable" npm run sources
npm run dev -- --port 3000 --host 127.0.0.1 &   # ready in ~10 s (curl / until 200)
node ../.claude/skills/run-silo-bz/screenshot.mjs http://127.0.0.1:3000/ /tmp/dash_home.png
node ../.claude/skills/run-silo-bz/screenshot.mjs http://127.0.0.1:3000/markets /tmp/dash_markets.png
```

`screenshot.mjs` prints the page `<title>` and first `<h1>` (assert on
those) and saves a PNG. **On an empty DB the pages render structure but
chart queries error** ("null function or function signature mismatch") —
sources with a zero-row spine guard write ≥1 row, but genuinely empty
sources write 0-row parquets whose columns degrade to null-typed. That is
expected locally; real rendering needs real data. `npm run build` will
_fail outright_ on 0-byte parquets — only run a production build against
a populated database.

## Run (human path)

`python -m serve.app` with `POSTGRES_URL` (or `SILO_API_DATABASE_URL`)
exported → Flask dev server on 127.0.0.1:8080, Ctrl-C to stop.
`cd dashboard && npm run dev` → localhost:3000. Useless headless without
the ephemeral DB above or Supabase credentials.

## Test

```bash
.venv/bin/pytest tests/ -v    # all offline (DB + HTTP mocked); 629 pass, ~2 min
```

Offline pipeline verification (DuckDB at `.local_db/`, separate from the
Postgres above) is `scripts/seed_local_db.py --skip-fi` followed by
`scripts/run_analysis_local.py`. **Warning, measured in this container:**
the seed downloads real CVM fixtures and through the egress proxy it was
still downloading after 20+ minutes (silent — it prints nothing until a
dataset finishes; progress is visible as `.local_db/*.duckdb.wal`
growing). Budget accordingly or prefer the pytest suite; the README's
"~2min" assumes fast egress.

## Gotchas

- **Postgres refuses to run as root** — every `initdb`/`pg_ctl` goes
  through `su postgres -c '…'`, and the data dir parent must be
  `chown postgres` first. smoke.sh does both.
- **The analytical layer RAISEs on an empty DB by design** — apply it
  with `PGOPTIONS="-c silo.ci_smoke_bypass=on"` (smoke.sh does). That
  GUC only downgrades the empty-DB smoke checks to WARNINGs; never set
  it against production.
- **ESM ignores `NODE_PATH`** — `import 'playwright'` fails even though
  it is globally installed. `screenshot.mjs` imports
  `/opt/node22/lib/node_modules/playwright/index.mjs` by absolute path.
- **Flask exits 1 instantly if the port is taken** ("Port 8080 is in
  use…"). A previous `serve.app` may still be running; kill it with
  `pkill -f "serve[.]app"` — the brackets matter, a plain
  `pkill -f serve.app` matches _your own shell's command line_ and kills
  it (observed: exit code 144, no output).
- **Evidence + local socket Postgres needs `sslmode=disable`** in the
  connection string or sources fail with "The server does not support
  SSL connections".
- **Order matters for the dashboard**: `npm run sources` before
  `npm run dev`; dev serves whatever parquet snapshot sources last wrote.

## Troubleshooting

- **`connection to server on socket … failed: Connection refused`** —
  the ephemeral Postgres died (container restarts don't preserve
  processes, only `/var/tmp`). Re-run smoke.sh; it restarts the existing
  data dir without re-applying schema.
- **`null function or function signature mismatch` on dashboard pages** —
  empty-DB artifact (see Gotchas), not a bug in the page. Populate the
  DB or point sources at real data to see charts.
- **`server never became ready` from smoke.sh** — read
  `$SILO_PG_DIR/serve.log`; the usual cause is a stale process on the
  API port (see the pkill gotcha).
