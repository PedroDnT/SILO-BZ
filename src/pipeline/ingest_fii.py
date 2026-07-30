"""FII ingest module — thin wrapper around declarative field maps.

Handles three subtypes that all target cvm_fii_mensal (discriminated by
doc_subtype), plus the periodic reports (cvm_fii_periodic).

Each public function is called by CVMIngestor and returns the number of rows
upserted.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from src.parsers.mapping import apply_map, assert_map_matches
from src.parsers.field_maps import fii_geral as _geral
from src.parsers.field_maps import fii_ativo_passivo as _ap
from src.parsers.field_maps import fii_complemento as _comp
from src.parsers.field_maps import fii_periodic as _periodic
from src.store.pg_client import upsert_rows

logger = logging.getLogger(__name__)

# Map doc_type string -> (subtype label, field_map module)
_SUBTYPE_MAP = {
    "mensal_geral":         (_geral.DOC_SUBTYPE,    _geral.FIELD_MAP),
    "mensal_ativo_passivo": (_ap.DOC_SUBTYPE,       _ap.FIELD_MAP),
    "mensal_complemento":   (_comp.DOC_SUBTYPE,     _comp.FIELD_MAP),
}


def ingest_fii_mensal(conn: Any, raw_rows: List[Dict[str, Any]], doc_type: str) -> int:
    """Parse and upsert FII monthly rows for a given doc_type/subtype.

    Args:
        conn      -- _PgClient instance
        raw_rows  -- rows from CVMFetcher (list of dicts from CSV)
        doc_type  -- one of: mensal_geral | mensal_ativo_passivo | mensal_complemento
    Returns:
        number of rows upserted
    """
    if doc_type not in _SUBTYPE_MAP:
        logger.error("ingest_fii_mensal: unknown doc_type %r", doc_type)
        return 0

    subtype, field_map = _SUBTYPE_MAP[doc_type]
    assert_map_matches(
        raw_rows, field_map, dataset=f"fii/{doc_type}",
        required=("cnpj",),
    )
    records: List[Dict[str, Any]] = []

    for row in raw_rows:
        typed, residual = apply_map(row, field_map)
        typed["doc_subtype"] = subtype
        typed["raw"] = residual

        # cnpj must be non-empty
        if not typed.get("cnpj"):
            continue

        # period: apply_map coerces to date object; if None fall back gracefully
        # (the ingest module is called with year context so the caller can patch)
        records.append(typed)

    if not records:
        return 0

    return upsert_rows(
        conn,
        _geral.TABLE,  # same table for all three subtypes
        records,
        conflict_columns=",".join(_geral.CONFLICT),
    )


def ingest_fii_periodic(conn: Any, raw_rows: List[Dict[str, Any]], doc_type: str, year: int) -> int:
    """Parse and upsert FII periodic report rows.

    Args:
        conn      -- _PgClient instance
        raw_rows  -- rows from CVMFetcher
        doc_type  -- one of: trimestral | anual | dfin
        year      -- period year (injected, not from CSV)
    Returns:
        number of rows upserted
    """
    records: List[Dict[str, Any]] = []

    for row in raw_rows:
        typed, residual = apply_map(row, _periodic.FIELD_MAP)
        typed["doc_type"] = doc_type
        typed["period_year"] = year
        typed["raw"] = residual

        if not typed.get("cnpj"):
            typed["cnpj"] = None  # allow NULL per table constraint

        records.append(typed)

    if not records:
        return 0

    return upsert_rows(
        conn,
        _periodic.TABLE,
        records,
        conflict_columns=",".join(_periodic.CONFLICT),
    )
