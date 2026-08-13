"""FII ingest module — thin wrapper around declarative field maps.

Handles three subtypes that all target cvm_fii_mensal (discriminated by
doc_subtype), the periodic reports (cvm_fii_periodic), and the INF_TRIMESTRAL
property register (cvm_fii_imovel, its own grain).

Each public function is called by CVMIngestor and returns the number of rows
upserted.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Mapping

from src.parsers.mapping import apply_map, assert_map_matches
from src.parsers.field_maps import fii_geral as _geral
from src.parsers.field_maps import fii_ativo_passivo as _ap
from src.parsers.field_maps import fii_complemento as _comp
from src.parsers.field_maps import fii_periodic as _periodic
from src.parsers.field_maps import fii_trimestral_geral as _tri_geral
from src.parsers.field_maps import fii_trimestral_complemento as _tri_comp
from src.parsers.field_maps import fii_imovel as _imovel
from src.store.pg_client import upsert_rows

logger = logging.getLogger(__name__)


def _row_hash(row: Mapping[str, Any]) -> str:
    """Stable sha256 over a source row's own fields.

    Used only where CVM publishes no usable identifier (the FII property
    register — see src/parsers/field_maps/fii_imovel.py). Deterministic for a
    given row, so re-ingesting an unchanged file is an exact no-op, and it never
    maps one source row onto another's. Nothing here is invented: the digest is
    a function of the published values alone.
    """
    payload = "\x1f".join(
        f"{k}={'' if row.get(k) is None else row.get(k)}" for k in sorted(row)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

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


# doc_type -> field map for the periodic reports. Each INF_TRIMESTRAL member is
# a different table in the source archive with its own header, so each gets its
# own map; `anual` and `dfin` still share the generic minimal map.
_PERIODIC_MAP = {
    "trimestral_geral":       _tri_geral.FIELD_MAP,
    "trimestral_complemento": _tri_comp.FIELD_MAP,
}


def ingest_fii_periodic(conn: Any, raw_rows: List[Dict[str, Any]], doc_type: str, year: int) -> int:
    """Parse and upsert FII periodic report rows.

    Args:
        conn      -- _PgClient instance
        raw_rows  -- rows from CVMFetcher
        doc_type  -- trimestral_geral | trimestral_complemento | anual | dfin
        year      -- period year (injected, not from CSV)
    Returns:
        number of rows upserted
    """
    field_map = _PERIODIC_MAP.get(doc_type, _periodic.FIELD_MAP)
    if doc_type in _PERIODIC_MAP:
        # These members always carry the key; a header that no longer does is
        # drift and must fail loudly rather than upsert a table full of NULLs.
        assert_map_matches(
            raw_rows, field_map, dataset=f"fii/{doc_type}",
            required=("cnpj", "data_referencia"),
        )

    records: List[Dict[str, Any]] = []

    for row in raw_rows:
        typed, residual = apply_map(row, field_map)
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


def ingest_fii_imovel(conn: Any, raw_rows: List[Dict[str, Any]], year: int) -> int:
    """Parse and upsert the FII property register (INF_TRIMESTRAL _imovel_ member).

    Separate from ingest_fii_periodic because the grain differs: many properties
    per fund per quarter, so it targets cvm_fii_imovel keyed
    (cnpj, data_referencia, row_hash).

    Rows missing cnpj or data_referencia are dropped and counted — the key
    cannot be guessed.

    Args:
        conn      -- _PgClient instance
        raw_rows  -- rows from CVMFetcher
        year      -- archive year (injected, not from CSV)
    Returns:
        number of rows upserted
    """
    assert_map_matches(
        raw_rows, _imovel.FIELD_MAP, dataset="fii/trimestral_imovel",
        required=("cnpj", "data_referencia"),
    )

    records: List[Dict[str, Any]] = []
    dropped = 0

    for row in raw_rows:
        typed, residual = apply_map(row, _imovel.FIELD_MAP)
        if not typed.get("cnpj") or not typed.get("data_referencia"):
            dropped += 1
            continue
        typed["row_hash"] = _row_hash(row)
        typed["period_year"] = year
        typed["raw"] = residual
        records.append(typed)

    if dropped:
        logger.warning(
            "fii/trimestral_imovel %d: dropped %d row(s) with no cnpj/data_referencia",
            year, dropped,
        )

    if not records:
        return 0

    return upsert_rows(
        conn,
        _imovel.TABLE,
        records,
        conflict_columns=",".join(_imovel.CONFLICT),
    )
