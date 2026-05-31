"""FI ingest module — thin wrapper around declarative field maps.

Handles inf_diario (daily snapshot), cda (portfolio composition), and
perfil_mensal (investor profile).

Each public function is called by CVMIngestor and returns the number of rows
upserted.  The historical variants (hist_inf_diario, hist_cda) use the same
field maps — the only difference is in how the fetcher constructs the URL.
"""
from __future__ import annotations

import logging
from datetime import date as _date
from typing import Any, Dict, List, Optional

from src.parsers.mapping import apply_map, derive_is_active
from src.parsers.field_maps import fi_diario as _diario
from src.parsers.field_maps import fi_cda as _cda
from src.parsers.field_maps import fi_perfil as _perfil
from src.parsers.field_maps import fund_registry as _reg
from src.store.pg_client import upsert_rows

logger = logging.getLogger(__name__)


def ingest_fi_diario(conn: Any, raw_rows: List[Dict[str, Any]]) -> int:
    """Parse and upsert FI daily snapshot rows.

    Returns:
        number of rows upserted
    """
    records: List[Dict[str, Any]] = []

    for row in raw_rows:
        typed, residual = apply_map(row, _diario.FIELD_MAP)
        typed["raw"] = residual

        if not typed.get("cnpj") or not typed.get("dt_comptc"):
            continue

        records.append(typed)

    if not records:
        return 0

    return upsert_rows(
        conn,
        _diario.TABLE,
        records,
        conflict_columns=",".join(_diario.CONFLICT),
    )


def ingest_fi_cda(conn: Any, raw_rows: List[Dict[str, Any]], year: int, month: int) -> int:
    """Parse and upsert FI portfolio composition rows.

    period is normalised to first-of-month (YYYY-MM-01).

    Returns:
        number of rows upserted
    """
    first_of_month = _date(year, month, 1)
    records: List[Dict[str, Any]] = []

    for row in raw_rows:
        typed, residual = apply_map(row, _cda.FIELD_MAP)
        typed["raw"] = residual
        # Override period to first-of-month regardless of DT_COMPTC precision
        typed["period"] = first_of_month

        if not typed.get("cnpj"):
            continue

        records.append(typed)

    if not records:
        return 0

    return upsert_rows(
        conn,
        _cda.TABLE,
        records,
        conflict_columns=",".join(_cda.CONFLICT),
    )


def ingest_fi_perfil(conn: Any, raw_rows: List[Dict[str, Any]], year: int, month: int) -> int:
    """Parse and upsert FI monthly investor profile rows.

    Returns:
        number of rows upserted
    """
    first_of_month = _date(year, month, 1)
    records: List[Dict[str, Any]] = []

    for row in raw_rows:
        typed, residual = apply_map(row, _perfil.FIELD_MAP)
        typed["raw"] = residual
        # Ensure period is always first-of-month
        if typed.get("period") is None:
            typed["period"] = first_of_month

        if not typed.get("cnpj"):
            continue

        records.append(typed)

    if not records:
        return 0

    return upsert_rows(
        conn,
        _perfil.TABLE,
        records,
        conflict_columns=",".join(_perfil.CONFLICT),
    )


def ingest_fund_registry_fi(conn: Any, raw_rows: List[Dict[str, Any]]) -> int:
    """Parse and upsert FI fund registry (cadastral) rows.

    Returns:
        number of rows upserted
    """
    records: List[Dict[str, Any]] = []

    for row in raw_rows:
        typed, residual = apply_map(row, _reg.FIELD_MAP)
        typed["entity_type"] = "fi"
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
