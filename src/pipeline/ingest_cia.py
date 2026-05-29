"""CIA_ABERTA ingest module — thin wrappers around declarative field maps.

W6 scope:
    ingest_cia_company  — cad_cia_aberta.csv -> cia_company
    ingest_cia_event    — ipe_cia_aberta_{year}.csv -> cia_event

ITR/DFP financial-statement ingestion is owned by W7 and lives elsewhere.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from src.parsers.mapping import apply_map
from src.parsers.field_maps import cia_company as _company
from src.parsers.field_maps import cia_event as _event
from src.store.pg_client import upsert_rows

logger = logging.getLogger(__name__)


def ingest_cia_company(conn: Any, raw_rows: List[Dict[str, Any]]) -> int:
    """Parse and upsert CAD rows into cia_company.

    Rows missing the primary key (cd_cvm) are dropped silently — the source
    CSV is a flat registry and CVM occasionally publishes blank stubs.

    Args:
        conn      -- _PgClient instance
        raw_rows  -- rows from CVMFetcher.fetch('cia_aberta', 'cad')

    Returns:
        number of rows upserted
    """
    records: List[Dict[str, Any]] = []

    for row in raw_rows:
        typed, residual = apply_map(row, _company.FIELD_MAP)
        typed["raw"] = residual

        if not typed.get("cd_cvm"):
            continue

        records.append(typed)

    if not records:
        return 0

    return upsert_rows(
        conn,
        _company.TABLE,
        records,
        conflict_columns=",".join(_company.CONFLICT),
    )


def ingest_cia_event(conn: Any, raw_rows: List[Dict[str, Any]]) -> int:
    """Parse and upsert IPE rows into cia_event.

    cia_event NOT NULL columns: cd_cvm. The natural key is
    (protocolo, versao); rows missing either are dropped because they cannot
    be upserted idempotently.

    Note: cia_event does NOT have a ``raw`` JSONB column in the DDL, so we
    only emit typed columns here (no residual storage).

    Args:
        conn      -- _PgClient instance
        raw_rows  -- rows from CVMFetcher.fetch('cia_aberta', 'ipe', year=Y)

    Returns:
        number of rows upserted
    """
    records: List[Dict[str, Any]] = []

    for row in raw_rows:
        typed, _residual = apply_map(row, _event.FIELD_MAP)

        if not typed.get("cd_cvm"):
            continue
        if not typed.get("protocolo") or typed.get("versao") is None:
            continue

        records.append(typed)

    if not records:
        return 0

    return upsert_rows(
        conn,
        _event.TABLE,
        records,
        conflict_columns=",".join(_event.CONFLICT),
    )
