"""Declarative field maps for every CVM dataset.

Each submodule exposes:
    TABLE    — target Postgres table name
    CONFLICT — tuple of column names for ON CONFLICT
    FIELD_MAP — {db_col: ([csv_candidates], coerce_type)}

Usage::

    from src.parsers.field_maps import fi_diario as m
    from src.parsers.mapping import apply_map

    typed, raw = apply_map(csv_row, m.FIELD_MAP)
    typed["raw"] = raw
    upsert_rows(conn, m.TABLE, [typed], ",".join(m.CONFLICT))
"""
