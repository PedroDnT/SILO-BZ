"""FIDC ingest module — thin wrapper around declarative field maps.

Handles:
  - fidc_mensal  (current 2025+ monthly snapshot via tab_IV, totals merged
                  from tab_VI and tab_II)
  - fidc_tranche (tabs X_2 + X_3 + X_6 joined)
  - fidc_tranche_flows (tab_X_4)
  - fidc_aging   (tab_VI)
  - fidc_setor   (tab_II, portfolio by sector — both eras)
  - fidc_scr     (tab_X, SCR grade ladder — both eras)
  - fidc_sacado  (tab_VIII, 25 largest sacados — both eras)
  - fidc_cedente (tab_I cedente slots, unpivoted — both eras)
  - fund_registry seed from HIST tab_II DENOM_SOCIAL
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from src.parsers.mapping import apply_map, assert_map_matches
from src.parsers.field_maps import fidc_mensal as _mensal
from src.parsers.field_maps import fidc_tranche as _tranche
from src.parsers.field_maps import fidc_tranche_flows as _flows
from src.parsers.field_maps import fidc_aging as _aging
from src.parsers.field_maps import fidc_setor as _setor
from src.parsers.field_maps import fidc_scr as _scr
from src.parsers.field_maps import fidc_sacado as _sacado
from src.parsers.field_maps import fidc_cedente as _cedente
from src.parsers.field_maps import fund_registry as _reg
from src.parsers.validation import DataValidator
from src.store.pg_client import upsert_rows

logger = logging.getLogger(__name__)

_validator = DataValidator()


def cedente_identifier(raw: Any) -> str | None:
    """The cedente's CPF/CNPJ from a tab_I slot, or None when it does not validate.

    The slot is free text and the published files carry three things besides
    real identifiers: blanks (the normal case), placeholders (all-zero and
    all-nine — 2,959 slots in 2024-12), and identifiers that lost leading
    zeros somewhere upstream (6084614000185 for 06084614000185; 37 such slots
    in 2026-07). A placeholder is not an identifier. A short one is kept
    only when zero-padding yields a CNPJ — or, when it could be one, a CPF —
    whose check digits verify: that is a recovered formatting loss, which the
    checksum makes verifiable, not a guess. Everything else is dropped.
    """
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if not digits:
        return None
    candidates = []
    if len(digits) == 14:
        candidates.append((digits, _validator._validate_cnpj))
    if len(digits) == 11:
        candidates.append((digits, _validator._validate_cpf))
    if len(digits) < 14:
        candidates.append((digits.zfill(14), _validator._validate_cnpj))
    if len(digits) < 11:
        candidates.append((digits.zfill(11), _validator._validate_cpf))
    for candidate, check in candidates:
        if check(candidate)[0]:
            return candidate
    return None


def ingest_fidc_mensal(
    conn: Any,
    raw_rows: List[Dict[str, Any]],
    rows_vi: List[Dict[str, Any]] | None = None,
    rows_ii: List[Dict[str, Any]] | None = None,
) -> int:
    """Parse and upsert FIDC monthly snapshot (2025+ tab_IV format).

    tab_IV carries only the PL figures. Two totals downstream reads live in
    sibling members of the same monthly ZIP and are merged in on (cnpj,
    period): `vl_inadimpl` from tab_VI (TAB_VI_B_VL_DIRCRED_INAD) and
    `vl_total` from tab_II (TAB_II_VL_CARTEIRA — the same column the HIST
    path reads for 2013-2024). When a sibling is unavailable its column stays
    NULL — never a guess.

    Args:
        raw_rows -- tab_IV rows
        rows_vi  -- tab_VI rows, or None to leave vl_inadimpl NULL
        rows_ii  -- tab_II rows, or None to leave vl_total NULL
    Returns:
        number of rows upserted
    """
    records: List[Dict[str, Any]] = []

    inadimpl_by_key: Dict[tuple, Any] = {}
    for row in rows_vi or []:
        typed_vi, _ = apply_map(row, _aging.FIELD_MAP)
        cnpj, period = typed_vi.get("cnpj"), typed_vi.get("period")
        if not cnpj or not period:
            continue
        total = typed_vi.get("vl_total_inad")
        if total is not None:
            inadimpl_by_key[(cnpj, period)] = total

    carteira_by_key: Dict[tuple, Any] = {}
    for row in rows_ii or []:
        typed_ii, _ = apply_map(row, _setor.FIELD_MAP)
        cnpj, period = typed_ii.get("cnpj"), typed_ii.get("period")
        if not cnpj or not period:
            continue
        carteira = typed_ii.get("vl_carteira")
        if carteira is not None:
            carteira_by_key[(cnpj, period)] = carteira

    assert_map_matches(
        raw_rows, _mensal.FIELD_MAP, dataset="fidc/mensal",
        required=("cnpj", "period"),
    )
    for row in raw_rows:
        typed, residual = apply_map(row, _mensal.FIELD_MAP)
        typed["raw"] = residual

        if not typed.get("cnpj") or not typed.get("period"):
            continue

        if typed.get("vl_inadimpl") is None:
            typed["vl_inadimpl"] = inadimpl_by_key.get(
                (typed["cnpj"], typed["period"])
            )
        if typed.get("vl_total") is None:
            typed["vl_total"] = carteira_by_key.get(
                (typed["cnpj"], typed["period"])
            )

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

    assert_map_matches(
        raw_rows, _aging.FIELD_MAP, dataset="fidc/aging",
        required=("cnpj", "period"),
    )
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


def _ingest_fidc_wide(
    conn: Any,
    raw_rows: List[Dict[str, Any]],
    fmap: Any,
    dataset: str,
    *,
    keep_raw: bool,
) -> int:
    """Shared body for the one-row-per-(fund, month) FIDC tabs.

    Same guard as ingest_fidc_aging: the map must still match the source
    header, a row missing either natural-key part is dropped (a NULL period
    would fail NOT NULL and roll back the month), and nothing is coerced.
    """
    assert_map_matches(
        raw_rows, fmap.FIELD_MAP, dataset=dataset, required=("cnpj", "period"),
    )
    records: List[Dict[str, Any]] = []
    for row in raw_rows:
        typed, residual = apply_map(row, fmap.FIELD_MAP)
        if keep_raw:
            typed["raw"] = residual
        if not typed.get("cnpj") or not typed.get("period"):
            continue
        records.append(typed)

    if not records:
        return 0

    return upsert_rows(
        conn, fmap.TABLE, records, conflict_columns=",".join(fmap.CONFLICT),
    )


def ingest_fidc_setor(conn: Any, raw_rows: List[Dict[str, Any]]) -> int:
    """Parse and upsert the receivables portfolio by sector (tab_II).

    Returns:
        number of rows upserted
    """
    return _ingest_fidc_wide(conn, raw_rows, _setor, "fidc/setor", keep_raw=True)


def ingest_fidc_scr(conn: Any, raw_rows: List[Dict[str, Any]]) -> int:
    """Parse and upsert the SCR risk-rating ladder (tab_X).

    Returns:
        number of rows upserted
    """
    return _ingest_fidc_wide(conn, raw_rows, _scr, "fidc/scr", keep_raw=True)


def ingest_fidc_sacado(conn: Any, raw_rows: List[Dict[str, Any]]) -> int:
    """Parse and upsert the 25 largest sacados (tab_VIII), one row per rank.

    `seq` is CVM's rank as filed and is part of the key; a row without it
    cannot be placed and is dropped. Nothing is re-ranked from `valor`.

    Returns:
        number of rows upserted
    """
    assert_map_matches(
        raw_rows, _sacado.FIELD_MAP, dataset="fidc/sacado",
        required=("cnpj", "period", "seq"),
    )
    records: List[Dict[str, Any]] = []
    for row in raw_rows:
        typed, _ = apply_map(row, _sacado.FIELD_MAP)
        if not typed.get("cnpj") or not typed.get("period") or typed.get("seq") is None:
            continue
        records.append(typed)

    if not records:
        return 0

    return upsert_rows(
        conn, _sacado.TABLE, records, conflict_columns=",".join(_sacado.CONFLICT),
    )


def ingest_fidc_cedente(conn: Any, raw_rows: List[Dict[str, Any]]) -> int:
    """Unpivot tab_I's cedente slots and upsert one row per (fund, month, block, slot).

    A slot is emitted only when its CPF/CNPJ validates (see
    cedente_identifier); a filled slot that does not is dropped and counted,
    never coerced. The share is kept as filed (NULL if the fund left it blank
    beside an identifier).

    Returns:
        number of rows upserted
    """
    assert_map_matches(
        raw_rows, _cedente.FIELD_MAP, dataset="fidc/cedente",
        required=("cnpj", "period", "cedente_a_1", "cedente_b_1"),
    )
    records: List[Dict[str, Any]] = []
    dropped = 0
    for row in raw_rows:
        typed, _ = apply_map(row, _cedente.FIELD_MAP)
        cnpj, period = typed.get("cnpj"), typed.get("period")
        if not cnpj or not period:
            continue
        for blk in _cedente.BLOCKS:
            for i in _cedente.SLOTS:
                filed = typed.get(f"cedente_{blk.lower()}_{i}")
                if filed is None:
                    continue
                ident = cedente_identifier(filed)
                if ident is None:
                    dropped += 1
                    continue
                records.append({
                    "cnpj":             cnpj,
                    "period":           period,
                    "bloco":            blk,
                    "seq":              i,
                    "cpf_cnpj_cedente": ident,
                    "pr_cedente":       typed.get(f"pr_{blk.lower()}_{i}"),
                })
    if dropped:
        logger.info("fidc/cedente: %d filled slot(s) dropped — identifier did not validate", dropped)

    if not records:
        return 0

    return upsert_rows(
        conn, _cedente.TABLE, records, conflict_columns=",".join(_cedente.CONFLICT),
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
