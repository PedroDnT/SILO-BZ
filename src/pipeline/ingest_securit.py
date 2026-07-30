"""SECURIT ingest module — thin wrapper around declarative field maps.

Handles:
  - securit_mensal  (monthly emissions: cra_mensal, cri_mensal, ots_mensal)
  - securit_serie   (per-series: cra_classe, cri_classe, ots_classe)
  - securit_fluxo   (cash flows: cra_fluxo, cri_fluxo, ots_fluxo)
  - securit_dfin    (financial statements: dfin_cra, dfin_cri)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from src.parsers.mapping import apply_map, assert_map_matches
from src.parsers.field_maps import securit_mensal as _mensal
from src.parsers.field_maps import securit_serie as _serie
from src.parsers.field_maps import securit_fluxo as _fluxo
from src.parsers.field_maps import securit_dfin as _dfin
from src.store.pg_client import upsert_rows

logger = logging.getLogger(__name__)

# Maps doc_type suffix -> instrument_type label for _mensal table
_DOC_TO_INSTRUMENT = {
    "cra_classe": "cra_mensal",
    "cri_classe": "cri_mensal",
    "ots_classe": "ots_mensal",
    "cra_fluxo":  "cra_mensal",
    "cri_fluxo":  "cri_mensal",
    "ots_fluxo":  "ots_mensal",
}


def _resolve_instrument_type(doc_type: str) -> str:
    return _DOC_TO_INSTRUMENT.get(doc_type, doc_type.rsplit("_", 1)[0] + "_mensal")


def ingest_securit_mensal(
    conn: Any,
    raw_rows: List[Dict[str, Any]],
    instrument_type: str,
    year: int,
) -> int:
    """Parse and upsert SECURIT monthly emissions.

    Args:
        conn            -- _PgClient instance
        raw_rows        -- rows from CVMFetcher
        instrument_type -- cra_mensal | cri_mensal | ots_mensal
        year            -- period year (injected)
    Returns:
        number of rows upserted
    """
    records: List[Dict[str, Any]] = []

    for row in raw_rows:
        typed, residual = apply_map(row, _mensal.FIELD_MAP)
        typed["instrument_type"] = instrument_type
        typed["period_year"] = year
        typed["raw"] = residual
        records.append(typed)

    if not records:
        return 0

    return upsert_rows(
        conn,
        _mensal.TABLE,
        records,
        conflict_columns=",".join(_mensal.CONFLICT),
    )


def ingest_securit_serie(
    conn: Any,
    raw_rows: List[Dict[str, Any]],
    doc_type: str,
    year: int,
) -> int:
    """Parse and upsert SECURIT per-series data (classe CSV).

    Args:
        doc_type -- cra_classe | cri_classe | ots_classe
    Returns:
        number of rows upserted
    """
    instrument_type = _resolve_instrument_type(doc_type)
    records: List[Dict[str, Any]] = []

    assert_map_matches(
        raw_rows, _serie.FIELD_MAP, dataset="securit/serie",
        required=("codigo_identificacao",),
    )
    for row in raw_rows:
        typed, residual = apply_map(row, _serie.FIELD_MAP)
        typed["instrument_type"] = instrument_type
        typed["raw"] = residual

        # Ensure non-null key parts per CONFLICT
        if not typed.get("codigo_identificacao"):
            typed["codigo_identificacao"] = ""
        if typed.get("data_referencia") is None:
            continue  # date is required in conflict key

        records.append(typed)

    if not records:
        return 0

    return upsert_rows(
        conn,
        _serie.TABLE,
        records,
        conflict_columns=",".join(_serie.CONFLICT),
    )


def ingest_securit_fluxo(
    conn: Any,
    raw_rows: List[Dict[str, Any]],
    doc_type: str,
    year: int,
) -> int:
    """Parse and upsert SECURIT per-tranche cash flows (fluxo_caixa CSV).

    Args:
        doc_type -- cra_fluxo | cri_fluxo | ots_fluxo
    Returns:
        number of rows upserted
    """
    instrument_type = _resolve_instrument_type(doc_type)
    records: List[Dict[str, Any]] = []

    assert_map_matches(
        raw_rows, _fluxo.FIELD_MAP, dataset="securit/fluxo",
        required=("codigo_identificacao",),
    )
    for row in raw_rows:
        typed, residual = apply_map(row, _fluxo.FIELD_MAP)
        typed["instrument_type"] = instrument_type
        typed["raw"] = residual

        if not typed.get("codigo_identificacao"):
            typed["codigo_identificacao"] = ""
        if typed.get("data_referencia") is None:
            continue

        records.append(typed)

    if not records:
        return 0

    return upsert_rows(
        conn,
        _fluxo.TABLE,
        records,
        conflict_columns=",".join(_fluxo.CONFLICT),
    )


def ingest_securit_dfin(
    conn: Any,
    raw_rows: List[Dict[str, Any]],
    instrument_type: str,
    year: int,
) -> int:
    """Parse and upsert SECURIT financial statements.

    Args:
        instrument_type -- dfin_cra | dfin_cri
    Returns:
        number of rows upserted
    """
    records: List[Dict[str, Any]] = []

    for row in raw_rows:
        typed, residual = apply_map(row, _dfin.FIELD_MAP)
        typed["instrument_type"] = instrument_type
        typed["period_year"] = year
        typed["raw"] = residual
        records.append(typed)

    if not records:
        return 0

    return upsert_rows(
        conn,
        _dfin.TABLE,
        records,
        conflict_columns=",".join(_dfin.CONFLICT),
    )
