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
from src.parsers.field_maps import fi_lamina as _lamina
from src.parsers.field_maps import fi_extrato as _extrato
from src.parsers.field_maps import fi_balancete as _balancete
from src.parsers.field_maps import fund_registry as _reg
from src.store.pg_client import replace_scoped_rows, upsert_rows
from src.parsers.validation import DataValidator

logger = logging.getLogger(__name__)

_validator = DataValidator()


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
    conn: Any,
    raw_rows: List[Dict[str, Any]],
    year: int,
    month: Optional[int],
    stats: Optional[Dict[str, int]] = None,
) -> int:
    """Parse and upsert FI portfolio composition rows.

    period is normalised to first-of-month (YYYY-MM-01). Pass month=None for a
    yearly HIST archive, where each row carries its own competency month and a
    single value for the file would collapse the year — see _period_for.

    For a month, each fund in the file replaces its stored rows of that month
    (_store_cda_block); `stats["rows_deleted"]` counts what that removed.

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

    records = _drop_relabelled_twins(records)
    # The names go first: if the holdings upsert then fails, no row has lost
    # its name without it being stored (the strip script's order too).
    _upsert_fund_names(conn, take_fund_names(records))
    return _store_cda_block(conn, _cda, records, month, stats)


FUND_NAME_TABLE = "cvm_fi_cda_fund_name"
FUND_NAME_CONFLICT = "cnpj,period,denom_social"


def take_fund_names(records: List[Dict[str, Any]]) -> set:
    """Pop DENOM_SOCIAL out of each record's raw; return {(cnpj, period, name)}.

    CVM repeats the filing fund's name on every CDA row. It is kept once per
    fund, month and name in cvm_fi_cda_fund_name (migration 60) instead of on
    every holding row.
    """
    names = set()
    for r in records:
        raw = r.get("raw")
        if isinstance(raw, dict):
            name = raw.pop("DENOM_SOCIAL", None)
            if name:
                names.add((r["cnpj"], r["period"], name))
    return names


def _upsert_fund_names(conn: Any, names: set) -> None:
    if names:
        upsert_rows(
            conn,
            FUND_NAME_TABLE,
            [{"cnpj": c, "period": p, "denom_social": d} for c, p, d in sorted(names)],
            conflict_columns=FUND_NAME_CONFLICT,
        )


def _store_cda_block(
    conn: Any,
    field_map_module: Any,
    records: List[Dict[str, Any]],
    month: Optional[int],
    stats: Optional[Dict[str, int]],
) -> int:
    """Write one parsed CDA block: per-fund replace for a month, upsert for a year.

    A monthly archive is re-read until month M+5 ends (#551), and a fund may
    re-file in that time: drop a position, or change a block-6 row (whose key
    ends in row_hash, so the changed row would land beside the old one). So for
    a month, every fund present in the new file ends up holding exactly the
    rows the file carries for it (pg_client.replace_scoped_rows). A fund absent
    from the file keeps every stored row: a partial or truncated file must
    never erase data. Called only after the whole file has parsed and
    validated, so a parse failure deletes nothing.

    A yearly HIST archive (month None) is final and is only upserted.
    """
    conflict = ",".join(field_map_module.CONFLICT)
    if month is None:
        return upsert_rows(conn, field_map_module.TABLE, records, conflict_columns=conflict)
    return replace_scoped_rows(
        conn,
        field_map_module.TABLE,
        records,
        conflict_columns=conflict,
        nulls_distinct=field_map_module.NULLS_DISTINCT,
        stats=stats,
    )


# The same position filed twice in one month, once per fund-type label.
# Measured on block 1: HIST 2005 has 144 groups under two labels (FI/FIF,
# FI/FITVM), 128 with identical quantity and value; 202503 has 34 (FI and
# CLASSES - FIF across the CVM-175 transition), 33 identical. tp_fundo is in
# the key so the few twins with DIFFERENT positions both survive, but an
# identical twin is one holding reported twice, and keeping both would double
# it in every sum.
_POSITION_COLS = ("qt_pos_final", "vl_merc_pos_final", "cd_selic", "tp_titpub", "dt_venc")


def _label_rank(tp_fundo: Optional[str]) -> tuple:
    # The CVM-175 label ("CLASSES - ...") is the current regime and wins; any
    # other tie breaks on the label text, so the survivor never depends on the
    # CSV's row order.
    return (not (tp_fundo or "").startswith("CLASSES"), tp_fundo or "")


def _drop_relabelled_twins(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    key_wo_label = [c for c in _cda.CONFLICT if c != "tp_fundo"]
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for r in records:
        groups.setdefault(tuple(r.get(c) for c in key_wo_label), []).append(r)

    kept: List[Dict[str, Any]] = []
    dropped = 0
    for group in groups.values():
        label_of: Dict[tuple, Optional[str]] = {}   # position -> label kept
        for r in sorted(group, key=lambda r: _label_rank(r.get("tp_fundo"))):
            position = tuple(r.get(c) for c in _POSITION_COLS)
            label = r.get("tp_fundo")
            if position in label_of and label_of[position] != label:
                dropped += 1
                continue
            label_of.setdefault(position, label)
            kept.append(r)

    if dropped:
        logger.info(
            "%s: kept once %d position(s) filed under two fund-type labels",
            _cda.TABLE, dropped,
        )
    return kept


def _ingest_cda_holdings(
    conn: Any,
    raw_rows: List[Dict[str, Any]],
    year: int,
    month: Optional[int],
    field_map_module: Any,
    required: str,
    stats: Optional[Dict[str, int]] = None,
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

    _upsert_fund_names(conn, take_fund_names(records))   # names first, see ingest_fi_cda
    return _store_cda_block(conn, field_map_module, records, month, stats)


def ingest_fi_cda_acoes(
    conn: Any,
    raw_rows: List[Dict[str, Any]],
    year: int,
    month: Optional[int],
    stats: Optional[Dict[str, int]] = None,
) -> int:
    """Parse and upsert FI equity holdings (CDA block 4).

    cd_ativo is the published B3 ticker; it is what joins these rows to
    b3_cotahist, so a row without one is dropped rather than stored unjoinable.
    """
    return _ingest_cda_holdings(conn, raw_rows, year, month, _cda_acoes, "cd_ativo", stats)


def ingest_fi_cda_cotas(
    conn: Any,
    raw_rows: List[Dict[str, Any]],
    year: int,
    month: Optional[int],
    stats: Optional[Dict[str, int]] = None,
) -> int:
    """Parse and upsert FI fund-of-fund holdings (CDA block 2).

    cnpj_cota identifies the held fund and is NOT NULL in the target table, so a
    row without it cannot be written at all.
    """
    return _ingest_cda_holdings(conn, raw_rows, year, month, _cda_cotas, "cnpj_cota", stats)


def ingest_fi_cda_debentures(
    conn: Any,
    raw_rows: List[Dict[str, Any]],
    year: int,
    month: Optional[int],
    stats: Optional[Dict[str, int]] = None,
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

    return _store_cda_block(conn, _cda_deb, records, month, stats)


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


def _unparsed_cells(row: Dict[str, Any], field_map: Dict[str, Any], typed: Dict[str, Any]) -> Dict[str, str]:
    """Source cells a typed numeric or date column could not parse.

    apply_map consumes a mapped header out of the residual `raw` whether or not
    the value coerced, so a malformed number would vanish without trace. They are
    returned here to be kept in `raw` under `_unparsed`, never guessed.
    """
    index = {k.strip().upper(): k for k in row}
    out: Dict[str, str] = {}
    for col, (candidates, type_) in field_map.items():
        if type_ not in ("numeric", "int", "date") or typed.get(col) is not None:
            continue
        for cand in candidates:
            real = index.get(cand.strip().upper())
            if real is None:
                continue
            value = str(row.get(real) or "").strip()
            if value and value.upper() not in ("NULL", "NA", "N/A", "-"):
                out[real] = value
            break
    return out


def ingest_fi_lamina(conn: Any, raw_rows: List[Dict[str, Any]]) -> int:
    """Parse and upsert the main member of one monthly lamina zip.

    Keyed on the source's own (CNPJ_FUNDO_CLASSE, DT_COMPTC, ID_SUBCLASSE); the
    month comes from each row's DT_COMPTC, not from the file name. A row whose CNPJ
    fails DataValidator or whose DT_COMPTC does not parse is dropped and counted.
    Fee text is kept as filed: TAXA_PERFM is text, and a numeric cell that does
    not parse lands in `raw["_unparsed"]` instead of being guessed.

    Returns:
        number of rows upserted
    """
    assert_map_matches(
        raw_rows, _lamina.FIELD_MAP, dataset="fi/lamina",
        required=("cnpj", "dt_comptc"),
    )
    records: List[Dict[str, Any]] = []
    bad_cnpj = bad_date = n_unparsed = 0

    for row in raw_rows:
        typed, residual = apply_map(row, _lamina.FIELD_MAP)
        if not typed.get("cnpj") or not _validator._validate_cnpj(typed["cnpj"])[0]:
            bad_cnpj += 1
            continue
        if typed.get("dt_comptc") is None:
            bad_date += 1
            continue
        unparsed = _unparsed_cells(row, _lamina.FIELD_MAP, typed)
        if unparsed:
            n_unparsed += 1
            residual = {**residual, "_unparsed": unparsed}
        typed["raw"] = residual
        records.append(typed)

    if bad_cnpj or bad_date:
        logger.warning(
            "cvm_fi_lamina: dropped %d row(s) with an invalid CNPJ and %d with no parseable "
            "DT_COMPTC, of %d", bad_cnpj, bad_date, len(raw_rows),
        )
    if n_unparsed:
        logger.warning(
            "cvm_fi_lamina: %d row(s) have a numeric or date cell that did not parse; "
            "kept as text in raw['_unparsed']", n_unparsed,
        )
    if not records:
        return 0

    keys = {(r["cnpj"], r["dt_comptc"], r["id_subclasse"]) for r in records}
    if len(keys) < len(records):
        logger.warning(
            "cvm_fi_lamina: %d source row(s) share a (cnpj, dt_comptc, id_subclasse) key; "
            "the last one in the file is kept", len(records) - len(keys),
        )

    return upsert_rows(
        conn,
        _lamina.TABLE,
        records,
        conflict_columns=",".join(_lamina.CONFLICT),
    )


def ingest_fi_extrato(conn: Any, raw_rows: List[Dict[str, Any]], source_file: str) -> int:
    """Parse and upsert one Extrato das Informacoes CSV (current file or one year).

    Keyed on the source's own (CNPJ_FUNDO_CLASSE, DT_COMPTC). A row whose CNPJ
    fails DataValidator or whose DT_COMPTC does not parse is dropped and counted.
    TAXA_ADM is stored exactly as filed: a 0 and a value above 5 are kept (the API
    reads them, this never rewrites them), and a cell that is not a number lands in
    `raw["_unparsed"]` instead of being guessed. A repeated (cnpj, dt_comptc) keeps
    the last row in the file and says so: whether a yearly file repeats the pair
    was not measured.

    Args:
        source_file: the CSV name (extrato_fi.csv or extrato_fi_YYYY.csv), stored
            on every row as its provenance.

    Returns:
        number of rows upserted
    """
    assert_map_matches(
        raw_rows, _extrato.FIELD_MAP, dataset="fi/extrato",
        required=("cnpj", "dt_comptc"),
    )
    records: List[Dict[str, Any]] = []
    bad_cnpj = bad_date = n_unparsed = 0

    for row in raw_rows:
        typed, residual = apply_map(row, _extrato.FIELD_MAP)
        if not typed.get("cnpj") or not _validator._validate_cnpj(typed["cnpj"])[0]:
            bad_cnpj += 1
            continue
        if typed.get("dt_comptc") is None:
            bad_date += 1
            continue
        unparsed = _unparsed_cells(row, _extrato.FIELD_MAP, typed)
        if unparsed:
            n_unparsed += 1
            residual = {**residual, "_unparsed": unparsed}
        typed["source_file"] = source_file
        typed["raw"] = residual
        records.append(typed)

    if bad_cnpj or bad_date:
        logger.warning(
            "cvm_fi_extrato %s: dropped %d row(s) with an invalid CNPJ and %d with no "
            "parseable DT_COMPTC, of %d", source_file, bad_cnpj, bad_date, len(raw_rows),
        )
    if n_unparsed:
        logger.warning(
            "cvm_fi_extrato %s: %d row(s) have a numeric or date cell that did not parse; "
            "kept as text in raw['_unparsed']", source_file, n_unparsed,
        )
    if not records:
        return 0

    keys = {(r["cnpj"], r["dt_comptc"]) for r in records}
    if len(keys) < len(records):
        logger.warning(
            "cvm_fi_extrato %s: %d source row(s) repeat a (cnpj, dt_comptc) key; "
            "the last one in the file is kept", source_file, len(records) - len(keys),
        )

    return upsert_rows(
        conn,
        _extrato.TABLE,
        records,
        conflict_columns=",".join(_extrato.CONFLICT),
    )


def ingest_fi_balancete(conn: Any, raw_rows: List[Dict[str, Any]]) -> int:
    """Parse FI monthly balance-sheet (BALANCETE) rows and upsert their summary.

    Keyed on the source DT_COMPTC (no first-of-month override) — the natural
    key is (cnpj, dt_comptc, cd_conta_balcte).  Rows missing cnpj or dt_comptc
    are dropped (they can't satisfy the UNIQUE constraint).

    Only cvm_fi_balancete_resumo is written: the account-level table was
    retired (migration 62) once the summary covered every stored month.

    Returns:
        number of summary rows (fund-months) upserted
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
        _balancete.RESUMO_TABLE,
        balancete_resumo(records),
        conflict_columns=",".join(_balancete.RESUMO_CONFLICT),
    )


def balancete_resumo(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One cvm_fi_balancete_resumo row per (cnpj, dt_comptc) of typed balancete rows.

    Each COFI account in RESUMO_ACCOUNTS lands in its column as filed; an account
    the fund did not file stays NULL. n_contas counts distinct account codes, and
    a code repeated in the file counts once with its last value, as the
    account table's key kept it.
    """
    accounts: Dict[tuple, Dict[str, Any]] = {}
    meta: Dict[tuple, Dict[str, Any]] = {}
    for rec in records:
        key = (rec["cnpj"], rec["dt_comptc"])
        accounts.setdefault(key, {})[rec["cd_conta_balcte"]] = rec.get("vl_saldo_balcte")
        meta[key] = rec

    out: List[Dict[str, Any]] = []
    for key, by_code in accounts.items():
        last = meta[key]
        row: Dict[str, Any] = {
            "cnpj": key[0],
            "dt_comptc": key[1],
            "tp_fundo_classe": last.get("tp_fundo_classe"),
            "plano_conta_balcte": last.get("plano_conta_balcte"),
            "n_contas": len(by_code),
        }
        for code, column in _balancete.RESUMO_ACCOUNTS.items():
            row[column] = by_code.get(code)
        out.append(row)
    return out


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
