# `field_maps/` — the declarative ingestion standard

Each module here is the **single readable spec** for one CVM dataset: which DB column
comes from which CSV field, and how it's typed. Ingestion is driven by these maps via
`src.parsers.mapping.apply_map`, so the typed columns are deterministic and `raw` only
ever holds fields we haven't modeled yet. Full rationale:
`docs/planning/02_ARCHITECTURE_AND_CONVENTIONS.md`.

## Module contract
Every module exports:
- `TABLE` — target table name.
- `CONFLICT` — tuple of columns = the table's UNIQUE key (the `ON CONFLICT` target).
- `FIELD_MAP` — `{ db_column: (["CSV_CANDIDATE", ...], coerce_type) }`.
- `DOC_SUBTYPE` — only for subtype-multiplexed tables (e.g. FII geral/ativo_passivo/complemento).

`coerce_type ∈ {text, cnpj, int, numeric, pct, date, bool}` (see `mapping.coerce`).
Candidate lists exist because CVM renamed headers across years — first non-empty wins,
**no fuzzy matching**.

## Adding a dataset
1. Download a recent zip and read the real header (`unzip -p file.zip member.csv | head -1 | iconv -f latin1 -t utf-8`). Do **not** trust the post-strip samples in old transcripts.
2. Write `<dataset>.py` with `TABLE`, `CONFLICT`, `FIELD_MAP`.
3. The ingest path: `read CSV rows → apply_map(row, FIELD_MAP) → upsert_rows(TABLE, typed+raw, conflict=CONFLICT)`.
4. Verify per the Definition of Done in `docs/planning/02 §8`.

## Status
- ✅ `fii_geral`, `fii_ativo_passivo`, `fii_complemento` — reference implementation (W1).
- ⬜ All other datasets — port from the inline `_find_field` maps in `cvm_pipeline.py` (W1).
