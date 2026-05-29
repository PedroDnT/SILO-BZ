# 02 — ARCHITECTURE & CONVENTIONS (Shared Contract)

Every agent MUST follow these. They are what let parallel branches merge cleanly.

## 1. Storage philosophy: typed columns are the interface, `raw` is residual
- Each meaningful CSV field maps to an **explicit, named, typed column**. You should
  never need to read JSON to understand a row.
- `raw JSONB` is kept, but redefined: it holds **only the columns NOT mapped to a typed
  column** (the residual). When a dataset is fully mapped, `raw ≈ '{}'`. This makes
  `raw` a *signal* ("here are fields we haven't modeled yet"), not a parallel copy of
  typed data. This resolves the old "is it in raw or in the column?" confusion.
- Do NOT delete `raw` (it is near-free — verified it barely toasts — and it is the
  recovery path when CVM adds a field). Pedro may toggle it off later; default = keep.

## 2. The declarative field-map standard (W1 introduces this)
Replace scattered inline `_find_field(...)` calls with one declarative map per dataset,
living in `src/parsers/field_maps/`. One file per dataset, one dict:

```python
# src/parsers/field_maps/fi_diario.py
FIELD_MAP = {
    # db_column        (csv_source_candidates,           coerce_type)
    "cnpj":            (["CNPJ_FUNDO", "CNPJ_FUNDO_CLASSE"], "cnpj"),
    "tp_fundo":        (["TP_FUNDO_CLASSE", "TP_FUNDO"],     "text"),
    "dt_comptc":       (["DT_COMPTC"],                       "date"),
    "vl_total":        (["VL_TOTAL"],                        "numeric"),
    "vl_quota":        (["VL_QUOTA"],                        "numeric"),
    "vl_patrim_liq":   (["VL_PATRIM_LIQ"],                   "numeric"),
    "captc_dia":       (["CAPTC_DIA"],                       "numeric"),
    "resg_dia":        (["RESG_DIA"],                        "numeric"),
    "nr_cotst":        (["NR_COTST"],                        "int"),
}
CONFLICT = ("cnpj", "dt_comptc")     # ON CONFLICT target = the table's UNIQUE key
TABLE = "cvm_fi_diario"
```
- `coerce_type ∈ {cnpj, text, int, numeric, date, pct, bool}` → handled by
  `src/parsers/validation.py` (single place for parsing latin-1 numbers, BR/ISO dates,
  CNPJ normalization to 14 digits, etc.).
- A generic `apply_map(row, FIELD_MAP) -> (typed_dict, residual_raw)` builds the typed
  row and the residual `raw`. The parser becomes: read CSV → `apply_map` → `upsert_rows`.
- Candidate lists exist because CVM renamed fields across years (e.g. `CNPJ_FUNDO` →
  `CNPJ_FUNDO_CLASSE` in 2023+). First non-empty candidate wins. **No fuzzy matching.**

## 3. Numeric precision convention (stop reactive widening)
Set generous precision up front, by semantic class:
| Semantic | Type | Rationale |
|---|---|---|
| Monetary total / PL / asset value | `NUMERIC(28,2)` | trillions with margin |
| Unit/quota price | `NUMERIC(28,12)` | high fractional precision |
| Quantity (cotas emitidas) | `NUMERIC(28,6)` | values reach ~6e14 |
| Percentage | `NUMERIC(20,6)` | CVM ships outliers; keep wide |
| Count (cotistas) | `INTEGER` | small; `BIGINT` only if >2.1e9 |
| Date | `DATE` | — |
| Timestamp | `TIMESTAMPTZ` | — |
| Code / CNPJ | `TEXT` | CNPJ `CHECK (char_length = 14)` |
Audit existing columns against observed maxima once (W3) and migrate to these.

## 4. Keys, upserts, idempotency
- Every table has a **named UNIQUE constraint** = its natural key; upserts use it as the
  explicit `ON CONFLICT` target. Use `UNIQUE NULLS NOT DISTINCT (...)` when a key column
  is nullable (PG15+).
- Upserts must be **idempotent**: re-running a slice updates in place, never duplicates.
- Surrogate `id BIGSERIAL` is optional; do not reference it via FKs (relationships are by
  `cnpj`/`cd_cvm` + period).

## 5. Partitioning rule
- Partition by year (`RANGE` on the date column) **only** for tables expected > ~10M rows.
  Today that is `cvm_fi_diario` only; in Domain B it will be `cia_account`. Do NOT
  partition smaller tables.
- Use a **BRIN** index on the partition/time column (append-only, monotonic) plus a
  **composite btree `(entity_key, date DESC)`** for the "one entity over time" query.

## 6. Naming & layout conventions
- Tables: `cvm_<entity>_<grain>` (funds), `cia_<object>` (listed companies), `bacen_<series>`.
- Columns: snake_case, Portuguese source semantics preserved (`vl_`, `nr_`, `pct_`, `dt_`/`data_`).
- Migrations: append-only, idempotent, one file per domain in `src/store/migrations/`
  (W1 splits the monolithic tail of `schema.sql` into these). `apply_schema.py` runs them in order.
- The DB client module `src/store/supabase_client.py` is **renamed `src/store/pg_client.py`** in W0 (it's plain psycopg2 on Neon; the name misleads).

## 7. Collision-avoidance (critical for multi-agent work)
The two shared files that cause merge conflicts are `cvm_pipeline.py` and `schema.sql`.
W1 eliminates the contention by modularizing:
- **Parsing** moves from the monolithic `cvm_pipeline.py` into `src/parsers/field_maps/<dataset>.py`
  + thin per-entity ingest modules. After W1, each dataset's logic lives in its own file →
  agents edit disjoint files.
- **Schema** moves from one giant `schema.sql` tail into `src/store/migrations/<NN>_<domain>.sql`.
  Each workstream owns its own migration file(s); no two agents edit the same SQL file.
- `cvm_config.py` is append-only per dataset; adding an entity = adding a config block, not editing others.

After W0 + W1, the dependency graph in `04_WORKSTREAMS.md` has no shared-file conflicts.

## 8. Definition of Done (every ingestion task)
1. Declarative field map committed under `src/parsers/field_maps/`.
2. Idempotent migration committed under `src/store/migrations/`.
3. Backfill slice runs green; `cvm_ingest_log` shows `ok`.
4. Idempotency verified: re-run the same slice → row counts unchanged.
5. Null-rate check: each typed column's null rate is explained (genuine absence vs mapping miss).
6. No manual SQL `UPDATE`s; a from-empty reload reproduces identical typed data.
7. Reconciliation: `raw` contains only unmapped residual fields.
