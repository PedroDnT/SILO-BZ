"""CIA_ABERTA ingest module — thin wrappers around declarative field maps.

W6 scope:
    ingest_cia_company  — cad_cia_aberta.csv -> cia_company
    ingest_cia_event    — ipe_cia_aberta_{year}.csv -> cia_event

W7 scope (ITR/DFP financial statements):
    ingest_cia_filing   — itr/dfp summary header CSV -> cia_filing
    ingest_cia_account  — itr/dfp scoped statement members -> cia_account
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from src.parsers.mapping import apply_map
from src.parsers.field_maps import cia_company as _company
from src.parsers.field_maps import cia_event as _event
from src.parsers.field_maps import cia_account as _account
from src.parsers.field_maps import cia_filing as _filing
from src.parsers.field_maps import cia_fca_valor_mobiliario as _ticker
from src.store.pg_client import upsert_rows

logger = logging.getLogger(__name__)

# ESCALA_MOEDA -> multiplier to convert VL_CONTA into absolute reais.
# CVM statements are usually shipped in MIL (thousands); UNIDADE is as-is.
_MONEY_SCALE: Dict[str, float] = {
    "MIL": 1_000.0,
    "MILHAO": 1_000_000.0,
    "MILHÃO": 1_000_000.0,
    "UNIDADE": 1.0,
}


def _scale_factor(escala_moeda: Optional[str]) -> float:
    """Return the multiplier for an ESCALA_MOEDA token (default 1, with a warn)."""
    if not escala_moeda:
        return 1.0
    key = escala_moeda.strip().upper()
    factor = _MONEY_SCALE.get(key)
    if factor is None:
        logger.warning("cia_account: unknown ESCALA_MOEDA %r — treating as ×1", escala_moeda)
        return 1.0
    return factor


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


def ingest_cia_ticker(conn: Any, raw_rows: List[Dict[str, Any]]) -> int:
    """Parse and upsert FCA valores-mobiliários rows into cia_ticker.

    This is the published CNPJ↔ticker map. Natural key
    (cnpj_cia, data_refer, versao, valor_mobiliario, codneg, mercado) with
    NULLS NOT DISTINCT — codneg CAN be NULL (unlisted securities) and those
    rows are kept; the vw_company_ticker bridge skips them. Rows without a
    CNPJ or reference date cannot be keyed and are dropped (never coerced).

    Args:
        conn      -- _PgClient instance
        raw_rows  -- rows from CVMFetcher.fetch('cia_aberta',
                     'fca_valor_mobiliario', year=Y)

    Returns:
        number of rows upserted
    """
    records: List[Dict[str, Any]] = []
    for row in raw_rows:
        typed, residual = apply_map(row, _ticker.FIELD_MAP)
        if not typed.get("cnpj_cia") or typed.get("data_refer") is None:
            continue
        if typed.get("versao") is None:
            typed["versao"] = 1
        # Tickers are upper-case on the B3 tape; normalise the published code
        # the same way so vw_company_ticker joins b3_cotahist.codneg cleanly.
        if typed.get("codneg"):
            typed["codneg"] = typed["codneg"].strip().upper() or None
        typed["raw"] = residual
        records.append(typed)

    if not records:
        return 0

    return upsert_rows(
        conn,
        _ticker.TABLE,
        records,
        conflict_columns=",".join(_ticker.CONFLICT),
    )


def ingest_cia_filing(conn: Any, summary_rows: List[Dict[str, Any]], doc_type: str) -> int:
    """Parse and upsert ITR/DFP summary-header rows into cia_filing.

    The summary member (e.g. dfp_cia_aberta_2024.csv) carries one row per filing
    with the document id, receipt date and download link. ``doc_type`` (itr|dfp)
    is injected — it is not a CSV column.

    cia_filing has no ``raw`` column, so residual fields are discarded. Rows
    missing cd_cvm or dt_refer are dropped (cannot be upserted on the natural key).

    Args:
        conn         -- _PgClient instance
        summary_rows -- rows from the CIAMember whose grupo == "_summary"
        doc_type     -- "itr" or "dfp"

    Returns:
        number of rows upserted
    """
    records: List[Dict[str, Any]] = []

    for row in summary_rows:
        typed, _residual = apply_map(row, _filing.FIELD_MAP)
        typed["doc_type"] = doc_type

        if not typed.get("cd_cvm") or typed.get("dt_refer") is None:
            continue

        records.append(typed)

    if not records:
        return 0

    return upsert_rows(
        conn,
        _filing.TABLE,
        records,
        conflict_columns=",".join(_filing.CONFLICT),
    )


def ingest_cia_account(conn: Any, members: Sequence[Any], doc_type: str) -> int:
    """Parse and upsert ITR/DFP line-item rows into cia_account.

    Iterates the scoped statement members (BPA/BPP/DRE/DFC_*/DMPL/DRA/DVA × con/ind)
    of an ITR or DFP yearly ZIP. For each member, ``grupo`` and ``escopo`` come
    from the member name (CIAFetcher), ``doc_type`` from the call argument, and the
    remaining columns from the declarative field map. ``VL_CONTA`` is scaled to
    absolute reais via ESCALA_MOEDA (e.g. MIL → ×1000); the original escala_moeda
    string is preserved for audit. Unmapped CSV fields fall through to ``raw``.

    Non-account members (``_summary`` header, composicao_capital, parecer) are
    skipped — they have ``escopo is None`` (``is_account_data`` False) and are
    routed to cia_filing or ignored. Rows missing cd_cvm, cd_conta or dt_refer are
    dropped (cannot be upserted on the natural key / would violate NOT NULL).

    One upsert call per member keeps batches bounded and isolates a bad member.

    Args:
        conn     -- _PgClient instance
        members  -- CIAMember sequence from CIAFetcher.fetch_zip_members(doc_type, year)
        doc_type -- "itr" or "dfp"

    Returns:
        total number of rows upserted across all account members
    """
    total = 0

    for member in members:
        if not getattr(member, "is_account_data", False):
            continue

        records: List[Dict[str, Any]] = []
        for row in member.rows:
            typed, residual = apply_map(row, _account.FIELD_MAP)
            typed["grupo"] = member.grupo
            typed["escopo"] = member.escopo
            typed["doc_type"] = doc_type
            typed["raw"] = residual

            if (
                not typed.get("cd_cvm")
                or not typed.get("cd_conta")
                or typed.get("dt_refer") is None
            ):
                continue

            if typed.get("vl_conta") is not None:
                typed["vl_conta"] = typed["vl_conta"] * _scale_factor(typed.get("escala_moeda"))

            records.append(typed)

        if records:
            total += upsert_rows(
                conn,
                _account.TABLE,
                records,
                conflict_columns=",".join(_account.CONFLICT),
            )

    return total
