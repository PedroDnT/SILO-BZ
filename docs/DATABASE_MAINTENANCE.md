# Database maintenance

Operator runbook for keeping the Supabase Postgres database healthy: what runs on its
own, what to check and when, and what each failure signal means.

This is the **ongoing upkeep** doc. For first-time setup / moving to a new Supabase
project, see [`supabase_operations.md`](supabase_operations.md) instead.

Everything here needs `POSTGRES_URL` (Supabase connection string, `sslmode=require`) in
your environment or `.env`.

---

## 1. What runs automatically

`.github/workflows/daily_ingest.yml` — **06:00 UTC daily**:

1. bootstraps the schema (base + all migrations, idempotent)
2. `python -m src.pipeline.run_daily`
3. `ANALYZE`s the core tables (keeps planner estimates honest)
4. `bash scripts/apply_analytical.sh` — rebuilds the analytical layer, which doubles as
   the daily matview refresh

`.github/workflows/watchdog.yml` runs a couple of hours later, calls
`scripts/check_staleness.py`, and re-runs the daily ingest if a slice looks stale.

`.github/workflows/backfill.yml` is on-demand only (see §4).

> **A green run used to mean nothing.** In June 2026 a backfill spent 4h22m failing every
> download, printed `0 total rows`, exited 0, and left `cvm_fi_diario` 2024 **and** 2025
> completely empty behind a green check. `run_daily` now exits non-zero when any source
> fails, a backfill that lands zero rows exits 1, and a slice that fetched rows but wrote
> none is logged `error`. Trust green _more_ than before — but §2 still exists for a
> reason.

---

## 2. Checks and cadence

| When                 | Command                                      | Looking for                                                                    |
| -------------------- | -------------------------------------------- | ------------------------------------------------------------------------------ |
| After any run        | `python scripts/check_staleness.py`          | exit `0` fresh · `10` daily slice stale · `11` monthly (ANBIMA) stale          |
| Weekly               | `python scripts/verify_pipeline.py`          | presence, field-population rates, sample business metrics per entity           |
| Weekly               | the audit-log triage query (§3)              | `error` slices, slices stuck `running`, entities missing entirely              |
| Monthly              | `POSTGRES_URL=… python scripts/db_parity.py` | table/view inventory + row estimates and sizes (`--exact` for true `COUNT(*)`) |
| Monthly              | `SELECT * FROM data_coverage();`             | per-entity date coverage — the gap detector                                    |
| **Yearly (Nov–Dec)** | partition rollover (§6)                      | next year's partitions must exist before January                               |

`data_coverage(p_entity_type, start_date, end_date)` and
`ingest_log_summary(start_date, end_date)` (defaults: last 7 days) are analytical-layer
functions — they exist only after `apply_analytical.sh` has run.

---

## 3. Reading `cvm_ingest_log`

Exactly one row per ingest run, written by `_log_start` / `_log_finish` in
`src/pipeline/cvm_pipeline.py`.

| Status    | Meaning                                                                                                | Action                |
| --------- | ------------------------------------------------------------------------------------------------------ | --------------------- |
| `ok`      | Rows upserted (or the published file was genuinely empty)                                              | none                  |
| `skipped` | Source 404'd — a **not-yet-published** month. Normal on the trailing daily window; CVM lags 1–2 months | none                  |
| `error`   | Fetch/parse/write failed, **or** rows were fetched and none survived parsing                           | investigate — see §11 |
| `running` | Never finalized: the process died mid-slice                                                            | re-run that slice     |

Triage query:

```sql
SELECT entity, doc_type, status, count(*) AS n,
       min(period_year) AS yr_lo, max(period_year) AS yr_hi,
       sum(rows_upserted) AS rows
FROM cvm_ingest_log
GROUP BY entity, doc_type, status
ORDER BY entity, doc_type, status;
```

Two signals worth knowing, both learned from real outages:

- **Rows stuck `running`** mean the run died before finalizing. Historically this happened
  when the DB connection idled out during a long fetch, so the status update failed
  silently. `_log_finish` now reconnects and retries once, so fresh `running` rows point
  at a hard crash or a cancelled job rather than an idle connection.
- **No rows at all for an entity** is more severe than an `error` row, and means the
  ingest died _before_ any write. This is exactly how the ANBIMA ingest was found to have
  been failing on every single daily run for months — it wrote a non-existent audit-log
  column, and the exception was downgraded to a warning. If an entity you expect is simply
  absent from the query above, suspect its logging/startup path, not its parser.

Also note: **`ok` with `rows_upserted = 0` is no longer possible** when the source
returned rows. That combination was what let `cvm_fiagro_mensal` sit empty behind 34
`ok` slices; it is now an `error` naming the likely cause.

---

## 4. Healing gaps (backfill)

**Full / per-year backfill** — GitHub → Actions → **CVM Historical Backfill** → _Run
workflow_ (inputs: `start_year`, `end_year`). FI runs one job per year in parallel; other
entities, BACEN and the ETF registry run alongside. A _skip-if-complete_ guard makes
already-loaded years cheap, so re-dispatching the whole range is the normal move.

**One entity** — Actions → **Daily CVM Ingest** → _Run workflow_ with
`mode=backfill` and `entity=<fi|fidc|fii|fip|fiagro|securit|etf>`.

**Locally / one slice at a time** — the Flask control plane:

```bash
flask --app app run          # 127.0.0.1:5000, needs POSTGRES_URL
```

then `POST /api/ingest` per `(entity, doc_type, year, month)` and watch `/api/jobs`.
Useful when you want to fill a single month and inspect the result.

```bash
# or directly
python -m src.pipeline.run_backfill --start-year 2019 --cvm-only [--entity fidc]
```

### If CVM refuses connections

CVM blocks GitHub runner IPs from time to time. Retrying does not help: the TCP/TLS
handshake never completes. After `CVM_CONNECT_FAILURE_LIMIT` consecutive connect
failures (default **8**) the fetcher raises `CVMHostUnreachable` and aborts instead of
grinding through every remaining slice.

**Fix: re-dispatch the workflow** — a fresh runner usually gets an unblocked IP (in the
June 2026 incident FI 2022 and 2026 succeeded while 2024/2025 were blocked, in the same
run). Do **not** raise the limit to push through; that just restores the 4-hour grind.
The counter resets on any HTTP response, including a 404, so the daily window's routine
not-yet-published misses can never trip it.

---

## 5. Schema changes

- Edit `src/store/schema.sql` **and** add a new `src/store/migrations/NNN_*.sql`.
- **Never edit a historical migration** — they are append-only.
- Apply with `python scripts/apply_schema.py` (base schema + all migrations, idempotent).
  CI also bootstraps this on every run.
- CI applies with `psql -v ON_ERROR_STOP=1`, so migrations must be **psql-clean**
  (real SQL comments, no client-specific syntax).
- Keep everything idempotent: `CREATE TABLE IF NOT EXISTS`, named `UNIQUE` constraints,
  `ADD COLUMN IF NOT EXISTS`.

Adding a whole dataset is a different recipe — see "Adding a dataset" in `CLAUDE.md`.

---

## 6. Yearly partition rollover ⚠️

`cvm_fi_diario` and `cia_account` are **range-partitioned by year**. Partitions are
declared through **2026**, plus a `_future` catch-all.

This will not fail loudly. Once 2027 data arrives it lands in `cvm_fi_diario_future` /
`cia_account_future`, which silently forfeits partition pruning and grows without bound —
the same quiet-degradation shape as the bugs above.

Check (should be `0`):

```sql
SELECT 'fi_diario_future' AS t, count(*) FROM cvm_fi_diario_future
UNION ALL SELECT 'cia_account_future', count(*) FROM cia_account_future;
```

Each year, before January:

1. Add the next partition to `schema.sql` and a new migration, following the existing
   pattern:
   ```sql
   CREATE TABLE IF NOT EXISTS cvm_fi_diario_2027 PARTITION OF cvm_fi_diario
       FOR VALUES FROM ('2027-01-01') TO ('2028-01-01');
   ```
   (and the matching `cia_account_2027`, which partitions on `dt_refer`).
2. Apply it, then move any rows already parked in `_future` into the real partition
   (`INSERT … SELECT` + `DELETE`, inside a transaction).

---

## 7. Analytical layer

```bash
bash scripts/apply_analytical.sh     # run AFTER data exists
```

Applies `src/store/analytical/01…17` in order, re-creating dims, matviews
(`dim_fund`, `fact_fund_monthly`, `fact_security_monthly`), fraud screens and the
ranking/ETF functions. The re-create _is_ the daily refresh, so dashboards see fresh
aggregates without a separate cron.

- Several files carry **smoke guards that RAISE on an empty database** — never run this
  before ingesting.
- A missing `pg_cron` extension (`08_cron_schedules.sql`) is tolerated with a warning.
  **Any other failure is fatal** and the script exits non-zero.
- Consumers (`dashboard/`, `webapp/`) read these objects directly and are read-only.

---

## 8. Security / RLS

**52 of 59 public tables currently have RLS disabled**, so the anon/publishable key that
ships to browsers can read — and potentially write — almost everything.

Remediation is written but deliberately **not auto-applied**, and lives outside
`migrations/` so the CI bootstrap can't run it:

```bash
psql "$POSTGRES_URL" -v ON_ERROR_STOP=1 -f docs/security/enable_rls.sql
```

It enables RLS and adds a SELECT-only `anon_read` policy to every public base table
(including partitioned parents) in one transaction. Two things to understand before
running it:

- The read policy is **not optional**. `ENABLE ROW LEVEL SECURITY` without a SELECT
  policy returns zero rows to anon — the dashboards would go blank.
- It deliberately does **not** use `FORCE ROW LEVEL SECURITY`, so the owner/service role
  the pipeline connects as keeps bypassing RLS and ingestion is unaffected.

Verify afterwards with the query in the file's footer.

---

## 9. Storage, vacuum, `ANALYZE`

- Autovacuum is managed by Supabase; no manual `VACUUM` scheduling needed.
- CI `ANALYZE`s the core tables after every ingest. Row estimates from `db_parity.py`
  come from `pg_class.reltuples` and are only as fresh as the last `ANALYZE` — use
  `--exact` when a number needs to be authoritative.
- Largest objects to watch (July 2026): `cvm_fi_perfil` ≈ 2 GB, the `cvm_fi_diario`
  partitions ≈ 3.7 GB combined, `cia_account_2026` ≈ 0.7 GB. `db_parity.py` prints sizes.

---

## 10. Known gaps register

Live as of 2026-07-30. Keep this current — it exists so the next person doesn't have to
rediscover these by querying the warehouse from scratch.

| Gap                                                                  | Closes by                                                                        |
| -------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `cvm_fi_diario` 2024 + 2025 empty; 2026 starts Mar 2; 2019/2020 thin | Re-dispatch the backfill (§4)                                                    |
| `cvm_fiagro_mensal` empty                                            | Field map fixed in PR #72 — needs a backfill run                                 |
| `anbima_etf_class_monthly` empty                                     | Audit-log bug fixed in PR #72 — next daily run fills it                          |
| `etf_market_snapshot` empty                                          | Set the `APIFY_TOKEN` secret, then verify the scrape's selectors on one real run |
| SECURIT (all tables) 2026 only                                       | Undiagnosed — earlier years sit stuck `running`                                  |
| `cia_account` 2026 partition only                                    | Undiagnosed — pre-2026 ITR/DFP never backfilled                                  |
| `cvm_fii_mensal` starts 2021                                         | Undiagnosed — 2019–2020 never landed                                             |
| RLS off on 52 tables                                                 | Apply §8 when ready                                                              |

---

## 11. Troubleshooting

| Symptom                                                                  | Likely cause                                                         | Fix                                                                                                                                                |
| ------------------------------------------------------------------------ | -------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Green CI run, table still empty                                          | A source returned rows but all were dropped                          | Check `cvm_ingest_log` for `error` with "fetched N … upserted 0"; compare the field map to the current source header                               |
| `FieldMapMismatch: … no longer matches the source header`                | The source renamed its columns (e.g. a CVM-175 regime change)        | Update the map in `src/parsers/field_maps/`, putting the new name first and keeping the legacy name as a fallback. This is what happened to FIAGRO |
| Many slices `error` with "cannot connect to host" / `CVMHostUnreachable` | CVM is blocking this runner's IP                                     | Re-dispatch the workflow (§4). Don't raise the failure limit                                                                                       |
| Slices stuck `running`                                                   | Run died mid-slice (crash, cancelled job, timeout)                   | Re-run those slices; check the job log for the real cause                                                                                          |
| An entity has **no** `cvm_ingest_log` rows                               | It failed before any write — usually startup or logging, not parsing | Run its ingest directly and read the traceback; check every logged key is a real `cvm_ingest_log` column                                           |
| `run_daily` exits 1                                                      | One or more sources failed (others still ran)                        | Read the final "FAILED for N source(s)" line, which names each                                                                                     |
| `apply_analytical.sh` fails a smoke check                                | Ran against an empty/partial DB                                      | Ingest first, then re-run                                                                                                                          |
| Dashboard suddenly empty after a security change                         | RLS enabled without a SELECT policy                                  | Ensure the `anon_read` policy exists (§8)                                                                                                          |
| Rows appearing in `*_future` partitions                                  | Missing year partition                                               | §6 rollover                                                                                                                                        |

---

## Related

- [`supabase_operations.md`](supabase_operations.md) — one-time setup / project cutover
- [`DATA_MODELING.md`](DATA_MODELING.md) — star schema conventions for new data classes
- [`ETF_AND_PERFORMANCE.md`](ETF_AND_PERFORMANCE.md) — ETF carve-out and the CVM-175 CNPJ split
- `CLAUDE.md` — architecture, the "Adding a dataset" recipe, and the non-negotiable
  data-integrity rules
