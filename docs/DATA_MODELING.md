# Data modeling principles (for *adding* data)

The existing schema is sound. This note exists so future additions — most likely
**market/price data for securities** — extend it the same way instead of growing a
parallel, wide, source-shaped table that downstream queries then have to special-case.
Read it before adding a new `(entity, doc_type)` or a new class of data; it sits on top
of the non-negotiable data-integrity rules in `.agents/rules/data-integrity.md`, it does
not replace them.

## The shape we already have

Ingestion is `FETCH → PARSE → STORE`, landing source rows in `cvm_<entity>_<doctype>` /
`bacen_<series>` tables, each with a **named UNIQUE constraint on its natural key** and
`ON CONFLICT DO UPDATE` upserts. The analytical layer (`src/store/analytical/`) then builds
a **star schema** on top: `dim_*` (fund, administrator, gestor, asset-class) and `fact_*`
matviews keyed by `(entity natural key, period)`. Keep new data inside this grain.

## How to decide the model for something new

1. **Reuse before inventing.** If a `dim_` already identifies the entity (a fund by CNPJ,
   a company by CNPJ, a security by its CVM/ISIN code), join to it — don't re-key.
2. **Model time series as a long fact, not a wide table.** One row per
   `(instrument natural key, date[, metric])` with a value column — never one column per
   source field or one table per provider. A long fact composes with the existing
   `fact_*_monthly` grain, indexes cleanly on `(instrument, date)`, and lets a new metric
   arrive as new rows rather than a schema migration.
3. **Preserve provenance.** Carry the source's own keys (instrument code, date, currency,
   source tag) straight through; never synthesize an identifier. One `cvm_ingest_log` row
   per ingest, as always.
4. **Idempotent by construction.** Named UNIQUE on the natural key
   (e.g. `(instrument_code, price_date, metric)`), upsert with `ON CONFLICT DO UPDATE`.
   Follow the 6-step "Adding a dataset" checklist in `CLAUDE.md`.
5. **A failed fetch raises.** No fabricated last-known-price fallbacks — that is precisely
   the `b3_calc_api` mistake. Validate every row through `DataValidator` before upsert.

## Worked example — daily security prices

A wide table `prices(instrument, date, open, high, low, close, volume, vwap, …)` per source
ages badly: each new field or provider is a migration, and the dashboards branch per column.

Prefer a **long fact**:

```sql
-- fact_security_price: one row per instrument/date/metric
CREATE TABLE IF NOT EXISTS fact_security_price (
    instrument_code TEXT NOT NULL,        -- natural key, joins dim_security
    price_date      DATE NOT NULL,
    metric          TEXT NOT NULL,        -- 'close' | 'volume' | 'vwap' | ...
    value           NUMERIC,
    currency        TEXT,
    source          TEXT NOT NULL,        -- provenance tag
    CONSTRAINT uq_fact_security_price UNIQUE (instrument_code, price_date, metric, source)
);
```

New metric → new rows. New source → new `source` value, not a new table. OHLC for a chart is
one pivoting view over this fact; it slots beside `fact_fund_monthly` / `fact_security_monthly`
in the same star schema and inherits the same idempotency and provenance guarantees.
