"""Per-dataset typed column → CSV header field maps.

Each module exposes:
  TABLE       — target table name (str)
  CONFLICT    — ON CONFLICT column list (tuple of str)
  FIELD_MAP   — dict mapping db_column → (csv_candidates, coerce_type)

coerce_type values: cnpj | text | int | numeric | date | pct | bool
"""
