"""Miscellaneous ingest functions — FIAGRO, FIP, and fund registry (FII).

These are smaller datasets with simpler structures that don't warrant their own
module but still need to go through the declarative field-map engine.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from src.parsers.mapping import apply_map, assert_map_matches, derive_is_active
from src.parsers.field_maps import fiagro_mensal as _fiagro
from src.parsers.field_maps import fip_periodic as _fip
from src.parsers.field_maps import fund_registry as _reg
from src.store.pg_client import upsert_rows

logger = logging.getLogger(__name__)


def ingest_fiagro_mensal(conn: Any, raw_rows: List[Dict[str, Any]]) -> int:
    """Parse and upsert FIAGRO monthly snapshot rows.

    Returns:
        number of rows upserted
    """
    assert_map_matches(
        raw_rows, _fiagro.FIELD_MAP, dataset="fiagro/mensal",
        required=("cnpj", "period"),
    )
    records: List[Dict[str, Any]] = []

    for row in raw_rows:
        typed, residual = apply_map(row, _fiagro.FIELD_MAP)
        typed["raw"] = residual

        if not typed.get("cnpj") or not typed.get("period"):
            continue

        records.append(typed)

    if not records:
        return 0

    return upsert_rows(
        conn,
        _fiagro.TABLE,
        records,
        conflict_columns=",".join(_fiagro.CONFLICT),
    )


def ingest_fip_periodic(
    conn: Any,
    raw_rows: List[Dict[str, Any]],
    doc_type: str,
    year: int,
) -> int:
    """Parse and upsert FIP periodic report rows.

    Args:
        doc_type -- inf_trimestral | inf_quadrimestral
        year     -- period year (injected, not from CSV)
    Returns:
        number of rows upserted
    """
    records: List[Dict[str, Any]] = []

    for row in raw_rows:
        typed, residual = apply_map(row, _fip.FIELD_MAP)
        typed["doc_type"] = doc_type
        typed["period_year"] = year
        typed["raw"] = residual

        if not typed.get("cnpj"):
            typed["cnpj"] = None  # table allows NULL

        records.append(typed)

    if not records:
        return 0

    return upsert_rows(
        conn,
        _fip.TABLE,
        records,
        conflict_columns=",".join(_fip.CONFLICT),
    )


def _entity_from_tipo(tipo: Any) -> str:
    """Derive cvm_fund_registry.entity_type from a CVM Tipo_Fundo/Tipo_Classe.

    Handles both the short codes in registro_fundo (FI, FIDC, FII, FIP, …) and
    the verbose registro_classe labels ("Classes de Cotas de Fundos FIF").
    """
    s = str(tipo or "").upper()
    if "FIDC" in s:
        return "fidc"
    if "FIAGRO" in s:
        return "fiagro"
    if "FII" in s:          # FII, FIIM
        return "fii"
    if any(k in s for k in ("FIP", "FMIEE", "FMIA", "FMAI")):
        return "fip"
    if any(k in s for k in ("FUNCINE", "FICART", "FMP", "FGTS")):
        return "other"
    return "fi"             # FI, FIF, FACFIF, FAPI, FITVM, "... Fundos FIF"


def ingest_fund_registry_cvm175(conn: Any, raw_rows: List[Dict[str, Any]]) -> int:
    """Parse and upsert CVM-175 registry rows (registro_fundo / registro_classe).

    entity_type and is_active are derived per row (the file mixes all fund
    families and both active and cancelled records).

    Returns:
        number of rows upserted
    """
    records: List[Dict[str, Any]] = []

    for row in raw_rows:
        typed, residual = apply_map(row, _reg.FIELD_MAP)
        if not typed.get("cnpj"):
            continue
        typed["entity_type"] = _entity_from_tipo(typed.get("tp_fundo"))
        typed["is_active"] = derive_is_active(typed.get("status"))
        typed["raw"] = residual
        records.append(typed)

    if not records:
        return 0

    return upsert_rows(
        conn,
        _reg.TABLE,
        records,
        conflict_columns=",".join(_reg.CONFLICT),
    )


def ingest_fund_registry(conn: Any, raw_rows: List[Dict[str, Any]], entity_type: str) -> int:
    """Parse and upsert fund registry rows for a given entity type.

    Args:
        entity_type -- 'fi' | 'fii' (injected by caller)
    Returns:
        number of rows upserted
    """
    records: List[Dict[str, Any]] = []

    for row in raw_rows:
        typed, residual = apply_map(row, _reg.FIELD_MAP)
        typed["entity_type"] = entity_type
        typed["is_active"] = derive_is_active(typed.get("status"))
        typed["raw"] = residual

        if not typed.get("cnpj"):
            continue

        records.append(typed)

    if not records:
        return 0

    return upsert_rows(
        conn,
        _reg.TABLE,
        records,
        conflict_columns=",".join(_reg.CONFLICT),
    )
