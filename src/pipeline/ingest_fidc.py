"""FIDC ingest module — thin wrapper around declarative field maps.

Handles:
  - fidc_mensal  (current 2025+ monthly snapshot via tab_IV)
  - fidc_tranche (tabs X_2 + X_3 + X_6 joined)
  - fidc_tranche_flows (tab_X_4)
  - fidc_aging   (tab_VI)
  - fund_registry seed from HIST tab_II DENOM_SOCIAL
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from src.parsers.mapping import apply_map
from src.parsers.field_maps import fidc_mensal as _mensal
from src.parsers.field_maps import fidc_tranche as _tranche
from src.parsers.field_maps import fidc_tranche_flows as _flows
from src.parsers.field_maps import fidc_aging as _aging
from src.parsers.field_maps import fund_registry as _reg
from src.store.pg_client import upsert_rows

logger = logging.getLogger(__name__)


def ingest_fidc_mensal(conn: Any, raw_rows: List[Dict[str, Any]]) -> int:
    """Parse and upsert FIDC monthly snapshot (2025+ tab_IV format).

    Returns:
        number of rows upserted
    """
    records: List[Dict[str, Any]] = []

    for row in raw_rows:
        typed, residual = apply_map(row, _mensal.FIELD_MAP)
        typed["raw"] = residual

        if not typed.get("cnpj") or not typed.get("period"):
            continue

        records.append(typed)

    if not records:
        return 0

    return upsert_rows(
        conn,
        _mensal.TABLE,
        records,
        conflict_columns=",".join(_mensal.CONFLICT),
    )


def ingest_fidc_tranche(
    conn: Any,
    rows_x2: List[Dict[str, Any]],
    rows_x3: List[Dict[str, Any]],
    rows_x6: List[Dict[str, Any]],
    year: int,
    month: int,
) -> int:
    """Join tab_X_2 + X_3 + X_6 and upsert tranche-level characteristics.

    The join key is (cnpj, period, classe_serie).  apply_map is called on the
    merged row so all candidates are checked in one pass.

    Returns:
        number of rows upserted
    """
    from src.parsers.mapping import _norm

    def _key(row: Dict[str, Any]) -> tuple:
        # Build key directly from raw row using apply_map on the key columns only
        typed, _ = apply_map(row, _tranche.FIELD_MAP)
        return (typed.get("cnpj") or "", typed.get("period"), typed.get("classe_serie") or "")

    x3_index = {_key(r): r for r in rows_x3}
    x6_index = {_key(r): r for r in rows_x6}

    records: List[Dict[str, Any]] = []
    for row in rows_x2:
        k = _key(row)
        merged = {**x6_index.get(k, {}), **x3_index.get(k, {}), **row}
        typed, residual = apply_map(merged, _tranche.FIELD_MAP)
        typed["raw"] = residual

        if not typed.get("cnpj"):
            continue

        records.append(typed)

    if not records:
        return 0

    return upsert_rows(
        conn,
        _tranche.TABLE,
        records,
        conflict_columns=",".join(_tranche.CONFLICT),
    )


def ingest_fidc_tranche_flows(conn: Any, raw_rows: List[Dict[str, Any]]) -> int:
    """Parse and upsert per-tranche flows (tab_X_4).

    Returns:
        number of rows upserted
    """
    records: List[Dict[str, Any]] = []

    for row in raw_rows:
        typed, residual = apply_map(row, _flows.FIELD_MAP)
        # flows table has no raw column per schema — omit residual
        # (schema has no `raw` JSONB column on cvm_fidc_tranche_flows)

        if not typed.get("cnpj"):
            continue

        # Ensure non-null key parts per CONFLICT
        if not typed.get("classe_serie"):
            typed["classe_serie"] = ""
        if not typed.get("tp_oper"):
            typed["tp_oper"] = ""

        records.append(typed)

    if not records:
        return 0

    return upsert_rows(
        conn,
        _flows.TABLE,
        records,
        conflict_columns=",".join(_flows.CONFLICT),
    )


def ingest_fidc_aging(conn: Any, raw_rows: List[Dict[str, Any]]) -> int:
    """Parse and upsert FIDC delinquency aging buckets (tab_VI).

    Returns:
        number of rows upserted
    """
    records: List[Dict[str, Any]] = []

    for row in raw_rows:
        typed, residual = apply_map(row, _aging.FIELD_MAP)
        typed["raw"] = residual

        if not typed.get("cnpj") or not typed.get("period"):
            continue

        records.append(typed)

    if not records:
        return 0

    return upsert_rows(
        conn,
        _aging.TABLE,
        records,
        conflict_columns=",".join(_aging.CONFLICT),
    )


def seed_fund_registry_from_hist(conn: Any, rows_ii: List[Dict[str, Any]]) -> int:
    """Seed cvm_fund_registry with FIDC fund names from HIST tab_II rows.

    tab_II carries DENOM_SOCIAL — use it to populate the registry without a
    dedicated cadastral fetch.

    Returns:
        number of rows upserted
    """
    seen: set = set()
    records: List[Dict[str, Any]] = []

    for row in rows_ii:
        typed, _ = apply_map(row, _reg.FIELD_MAP)
        cnpj = typed.get("cnpj")
        if not cnpj or cnpj in seen:
            continue
        seen.add(cnpj)
        name = typed.get("fund_name") or row.get("DENOM_SOCIAL")
        if name:
            records.append({
                "cnpj":        cnpj,
                "entity_type": "fidc",
                "fund_name":   name,
                "raw":         {},
            })

    if not records:
        return 0

    return upsert_rows(
        conn,
        _reg.TABLE,
        records,
        conflict_columns=",".join(_reg.CONFLICT),
    )
