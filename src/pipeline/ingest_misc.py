"""Miscellaneous ingest functions — FIAGRO, FIP, and fund registry (FII).

These are smaller datasets with simpler structures that don't warrant their own
module but still need to go through the declarative field-map engine.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from src.parsers.mapping import (
    _norm, apply_map, assert_map_matches, derive_is_active, row_hash,
)
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
    undated = 0

    for row in raw_rows:
        typed, residual = apply_map(row, _fip.FIELD_MAP)
        typed["doc_type"] = doc_type
        typed["raw"] = residual

        # period is the row's OWN DT_COMPTC. A FIP yearly CSV holds every
        # filing of the year (4 quarters, or 3 quadrimestral periods), so
        # stamping the archive year on all of them collapsed 72-77% of every
        # file onto one row per fund. period_year stays as a stored column
        # because the coverage gate reads it, but it is not the key.
        period = typed.get("period")
        if period is None:
            undated += 1
            continue
        typed["period_year"] = period.year

        # Last element of the key, and only a tiebreaker: CVM restates the same
        # (fund, date, class) with different capital figures and publishes no
        # column that separates the two filings. Keeping both is honest;
        # picking one silently is not. See the field map for the audit.
        typed["row_hash"] = row_hash(row)

        if not typed.get("cnpj"):
            typed["cnpj"] = None  # table allows NULL

        records.append(typed)

    if undated:
        logger.warning(
            "cvm_fip_periodic: dropped %d of %d rows with no parseable DT_COMPTC",
            undated, len(raw_rows),
        )

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


def _columns_published_by(rows: List[Dict[str, Any]], field_map: Dict[str, Any]) -> set:
    """Which FIELD_MAP columns this source file actually publishes.

    A column whose candidate headers are absent from the file is not "empty", it
    is *not reported by this file* — and the two must not be written the same
    way. apply_map cannot tell them apart: it emits None either way.

    Judged on the union of keys across the rows, not the first row: a parser that
    omits absent keys per row would otherwise make the whole batch inherit
    whatever the first record happened to carry.
    """
    present = {_norm(k) for row in rows for k in row.keys()}
    return {
        col
        for col, (candidates, _type) in field_map.items()
        if any(_norm(c) in present for c in candidates)
    }


def ingest_fund_registry_cvm175(conn: Any, raw_rows: List[Dict[str, Any]]) -> int:
    """Parse and upsert CVM-175 registry rows (registro_fundo / registro_classe).

    entity_type and is_active are derived per row (the file mixes all fund
    families and both active and cancelled records).

    Both files land in cvm_fund_registry keyed on (cnpj, entity_type), and CVM
    reuses the fund's CNPJ for its classes: measured 2026-08-28, 36,492 of 36,606
    CNPJ_Classe values are also a CNPJ_Fundo. registro_classe.csv publishes no
    Administrador and no Gestor at all, so mapping it produced gestor_name=None
    and the upsert wrote that NULL over the fund row loaded moments earlier —
    erasing the manager for 36,343 funds, ETFs among them. That is why the ETF
    page showed an index publisher where a manager belongs.

    Columns this file does not publish are therefore dropped from the record
    entirely, so they appear in neither the INSERT list nor the ON CONFLICT SET
    and the fund's published value survives. Silence is not a value.

    Returns:
        number of rows upserted
    """
    records: List[Dict[str, Any]] = []
    published = _columns_published_by(raw_rows, _reg.FIELD_MAP)

    for row in raw_rows:
        typed, residual = apply_map(row, _reg.FIELD_MAP)
        if not typed.get("cnpj"):
            continue
        typed = {k: v for k, v in typed.items() if k in published}
        typed["entity_type"] = _entity_from_tipo(typed.get("tp_fundo"))
        typed["is_active"] = derive_is_active(typed.get("status"))
        typed["raw"] = residual
        records.append(typed)

    if not records:
        return 0

    missing = sorted(set(_reg.FIELD_MAP) - published)
    if missing:
        logger.info(
            "cvm175 registry: source does not publish %s — leaving those columns untouched",
            ", ".join(missing),
        )

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
    published = _columns_published_by(raw_rows, _reg.FIELD_MAP)

    for row in raw_rows:
        typed, residual = apply_map(row, _reg.FIELD_MAP)
        # Same rule as the CVM-175 path: this table is written by several source
        # files with different column sets, so a file may only assert the columns
        # it publishes. Otherwise whichever file loads last wins with NULLs.
        typed = {k: v for k, v in typed.items() if k in published}
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
