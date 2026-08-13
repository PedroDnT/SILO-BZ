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

from src.parsers.mapping import apply_map, assert_map_matches, derive_is_active
from src.parsers.field_maps import fi_diario as _diario
from src.parsers.field_maps import fi_cda as _cda
from src.parsers.field_maps import fi_perfil as _perfil
from src.parsers.field_maps import fi_balancete as _balancete
from src.parsers.field_maps import fund_registry as _reg
from src.store.pg_client import upsert_rows

logger = logging.getLogger(__name__)


def ingest_fi_diario(conn: Any, raw_rows: List[Dict[str, Any]]) -> int:
    """Parse and upsert FI daily snapshot rows.

    Returns:
        number of rows upserted
    """
    records: List[Dict[str, Any]] = []

    assert_map_matches(
        raw_rows, _diario.FIELD_MAP, dataset="fi/inf_diario",
        required=("cnpj", "dt_comptc"),
    )
    for row in raw_rows:
        typed, residual = apply_map(row, _diario.FIELD_MAP)
        typed["raw"] = residual

        if not typed.get("cnpj") or not typed.get("dt_comptc"):
            continue

        # "text" coercion turns a blank ID_SUBCLASSE into None; the column is
        # NOT NULL DEFAULT '' precisely so the (cnpj, dt_comptc, id_subclasse)
        # UNIQUE constraint still catches duplicates for non-subclassed funds
        # (Postgres treats NULL as distinct from NULL in a UNIQUE constraint).
        typed["id_subclasse"] = typed.get("id_subclasse") or ""

        records.append(typed)

    if not records:
        return 0

    # Some CNPJs are filed twice on the same day under both the legacy
    # ("FI") and CVM-175 ("CLASSES - FIF") tp_fundo label, same (empty)
    # subclasse — a CVM-side transition artifact, not a distinct fund.
    # upsert_rows() dedupes same-key rows "last write wins", so sort the
    # CVM-175 label last to make the winner deterministic (current regime)
    # rather than dependent on the CSV's own row order.
    records.sort(key=lambda r: "CLASSE" in (r.get("tp_fundo") or ""))

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

    assert_map_matches(
        raw_rows, _perfil.FIELD_MAP, dataset="fi/perfil_mensal",
        required=("cnpj",),
    )
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


def ingest_fi_balancete(conn: Any, raw_rows: List[Dict[str, Any]]) -> int:
    """Parse and upsert FI monthly balance-sheet (BALANCETE) rows.

    Keyed on the source DT_COMPTC (no first-of-month override) — the natural
    key is (cnpj, dt_comptc, cd_conta_balcte).  Rows missing cnpj or dt_comptc
    are dropped (they can't satisfy the UNIQUE constraint).

    Returns:
        number of rows upserted
    """
    records: List[Dict[str, Any]] = []

    assert_map_matches(
        raw_rows, _balancete.FIELD_MAP, dataset="fi/balancete",
        required=("cnpj", "dt_comptc"),
    )
    for row in raw_rows:
        typed, residual = apply_map(row, _balancete.FIELD_MAP)
        typed["raw"] = residual

        if not typed.get("cnpj") or not typed.get("dt_comptc"):
            continue
        if not typed.get("cd_conta_balcte"):
            continue

        records.append(typed)

    if not records:
        return 0

    return upsert_rows(
        conn,
        _balancete.TABLE,
        records,
        conflict_columns=",".join(_balancete.CONFLICT),
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
