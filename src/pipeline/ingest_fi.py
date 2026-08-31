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

from src.parsers.mapping import apply_map, assert_map_matches, derive_is_active, row_hash
from src.parsers.field_maps import fi_diario as _diario
from src.parsers.field_maps import fi_cda as _cda
from src.parsers.field_maps import fi_cda_acoes as _cda_acoes
from src.parsers.field_maps import fi_cda_cotas as _cda_cotas
from src.parsers.field_maps import fi_cda_debentures as _cda_deb
from src.parsers.field_maps import fi_perfil as _perfil
from src.parsers.field_maps import fi_balancete as _balancete
from src.parsers.field_maps import fund_registry as _reg
from src.store.pg_client import upsert_rows

logger = logging.getLogger(__name__)


def _period_for(row: Dict[str, Any], typed: Dict[str, Any], fallback: Optional[_date]) -> Optional[_date]:
    """First-of-month for a CDA row, from the row itself when the caller cannot say.

    The monthly archives are one competency month per file, so the caller knows
    the period and passes it as `fallback`. The yearly HIST archives are twelve
    months in one file, and there the period has to come from each row's own
    DT_COMPTC — passing a single month for the whole file stamps every row with
    it, and the unique key then collapses December onto January.

    That is not hypothetical: ingest_fi_hist_cda called ingest_fi_cda(rows,
    year, 1) and cvm_fi_cda's key is (cnpj, period, tp_aplic, tp_ativo), so
    every pre-2023 year held one month instead of twelve.

    A row whose date will not parse returns None and is dropped by the caller.
    Guessing a month here would be inventing the one column that says when the
    position was held.
    """
    if fallback is not None:
        return fallback
    value = typed.get("period") or row.get("DT_COMPTC")
    if isinstance(value, _date):
        return value.replace(day=1)
    if not value:
        return None
    try:
        parsed = _date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
    return parsed.replace(day=1)


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
    # Diario-only: a June-2026 header+row audit of cda BLC_1, perfil_mensal
    # and balancete found no ID_SUBCLASSE column and zero same-key dual
    # labels, so those ingests do not apply this sort.
    records.sort(key=lambda r: "CLASSE" in (r.get("tp_fundo") or ""))

    return upsert_rows(
        conn,
        _diario.TABLE,
        records,
        conflict_columns=",".join(_diario.CONFLICT),
    )


def ingest_fi_cda(
    conn: Any, raw_rows: List[Dict[str, Any]], year: int, month: Optional[int]
) -> int:
    """Parse and upsert FI portfolio composition rows.

    period is normalised to first-of-month (YYYY-MM-01). Pass month=None for a
    yearly HIST archive, where each row carries its own competency month and a
    single value for the file would collapse the year — see _period_for.

    Returns:
        number of rows upserted
    """
    first_of_month = _date(year, month, 1) if month is not None else None
    records: List[Dict[str, Any]] = []
    undated = 0

    for row in raw_rows:
        typed, residual = apply_map(row, _cda.FIELD_MAP)
        typed["raw"] = residual
        period = _period_for(row, typed, first_of_month)
        if period is None:
            undated += 1
            continue
        typed["period"] = period

        if not typed.get("cnpj"):
            continue

        records.append(typed)

    if undated:
        logger.warning(
            "%s: dropped %d of %d rows with no parseable DT_COMPTC",
            _cda.TABLE, undated, len(raw_rows),
        )

    if not records:
        return 0

    return upsert_rows(
        conn,
        _cda.TABLE,
        records,
        conflict_columns=",".join(_cda.CONFLICT),
    )


def _ingest_cda_holdings(
    conn: Any,
    raw_rows: List[Dict[str, Any]],
    year: int,
    month: Optional[int],
    field_map_module: Any,
    required: str,
) -> int:
    """Shared body for the CDA holdings blocks (4 and 2).

    They differ only in their field map and in which column must be present for
    a row to be worth keeping, so the parse/upsert shape is factored out rather
    than duplicated.

    `required` is the identifier that makes the row joinable — the ticker for
    equities, the held fund's CNPJ for fund quotas. A row missing it is dropped
    and counted, never written with a synthesised value: an equity holding with
    no ticker cannot be joined to the tape, and inventing one would be exactly
    the fabrication the ingest rules forbid.

    period is normalised to first-of-month, matching every other monthly table.
    Pass month=None for a yearly HIST archive so each row keeps its own
    competency month; see _period_for for what a single value costs there.
    """
    first_of_month = _date(year, month, 1) if month is not None else None
    records: List[Dict[str, Any]] = []
    dropped = 0
    undated = 0

    for row in raw_rows:
        typed, residual = apply_map(row, field_map_module.FIELD_MAP)
        typed["raw"] = residual

        period = _period_for(row, typed, first_of_month)
        if period is None:
            undated += 1
            continue
        typed["period"] = period

        if not typed.get("cnpj") or not typed.get(required):
            dropped += 1
            continue

        records.append(typed)

    if dropped or undated:
        logger.info(
            "%s: dropped %d of %d rows with no %s, %d with no parseable DT_COMPTC",
            field_map_module.TABLE, dropped, len(raw_rows), required, undated,
        )

    if not records:
        return 0

    return upsert_rows(
        conn,
        field_map_module.TABLE,
        records,
        conflict_columns=",".join(field_map_module.CONFLICT),
    )


def ingest_fi_cda_acoes(
    conn: Any, raw_rows: List[Dict[str, Any]], year: int, month: Optional[int]
) -> int:
    """Parse and upsert FI equity holdings (CDA block 4).

    cd_ativo is the published B3 ticker; it is what joins these rows to
    b3_cotahist, so a row without one is dropped rather than stored unjoinable.
    """
    return _ingest_cda_holdings(conn, raw_rows, year, month, _cda_acoes, "cd_ativo")


def ingest_fi_cda_cotas(
    conn: Any, raw_rows: List[Dict[str, Any]], year: int, month: Optional[int]
) -> int:
    """Parse and upsert FI fund-of-fund holdings (CDA block 2).

    cnpj_cota identifies the held fund and is NOT NULL in the target table, so a
    row without it cannot be written at all.
    """
    return _ingest_cda_holdings(conn, raw_rows, year, month, _cda_cotas, "cnpj_cota")


def ingest_fi_cda_debentures(
    conn: Any, raw_rows: List[Dict[str, Any]], year: int, month: Optional[int]
) -> int:
    """Parse and upsert FI debenture holdings (CDA block 6).

    Unlike blocks 4 and 2 this one has no single published column naming the
    instrument — a debenture has no CD_ATIVO — so the key ends in row_hash and
    the shared _ingest_cda_holdings body does not fit. See the field map for the
    audit that produced the key.

    cpf_cnpj_emissor is what makes the row joinable to the issuer universe, so a
    row without one is dropped and counted rather than stored unjoinable. It is
    NOT validated as a CNPJ: PF_PJ_EMISSOR says the same column may hold a CPF,
    and rejecting those would discard real filings.
    """
    first_of_month = _date(year, month, 1) if month is not None else None
    records: List[Dict[str, Any]] = []
    dropped = 0
    undated = 0

    for row in raw_rows:
        typed, residual = apply_map(row, _cda_deb.FIELD_MAP)
        typed["raw"] = residual

        period = _period_for(row, typed, first_of_month)
        if period is None:
            undated += 1
            continue
        typed["period"] = period

        if not typed.get("cnpj") or not typed.get("cpf_cnpj_emissor"):
            dropped += 1
            continue

        # Over the SOURCE row, not the typed one: the digest must be a function
        # of what CVM published, so re-reading an unchanged file is an exact
        # no-op regardless of how the field map later evolves.
        typed["row_hash"] = row_hash(row)

        records.append(typed)

    if dropped or undated:
        logger.info(
            "%s: dropped %d of %d rows with no issuer CPF/CNPJ, %d with no "
            "parseable DT_COMPTC",
            _cda_deb.TABLE, dropped, len(raw_rows), undated,
        )

    if not records:
        return 0

    return upsert_rows(
        conn,
        _cda_deb.TABLE,
        records,
        conflict_columns=",".join(_cda_deb.CONFLICT),
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
