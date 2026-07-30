"""Declarative field-map engine.

Turns a raw CSV row + a dataset FIELD_MAP into (typed_columns, residual_raw),
so ingestion is map-driven and deterministic. See the "Adding a dataset" recipe
in CLAUDE.md.

A FIELD_MAP is::

    FIELD_MAP = { db_column: (["CSV_CANDIDATE", ...], coerce_type) }

The first non-empty candidate (case-insensitive) wins. `residual_raw` is the
original row minus every consumed source key, so `raw` only ever holds fields
we have not modeled yet.

coerce_type values: text, cnpj, cd_cvm, int, numeric, pct, date, bool
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

CoerceType = str  # one of: text, cnpj, int, numeric, pct, date, bool

_NULLISH = {"", "NULL", "NA", "N/A", "-", "NAO INFORMADO", "NÃO INFORMADO"}


def _norm(key: str) -> str:
    """Case/space-insensitive key for matching CVM header variants."""
    return key.strip().lower().replace(" ", "")


def coerce(value: Any, type_: CoerceType) -> Any:
    """Coerce a raw CSV string to the target Python type, or None on failure.

    Supported types:
        text    — strip whitespace; empty/nullish -> None
        cnpj    — strip non-digits, zero-pad to 14 chars
        cd_cvm  — strip non-digits and leading zeros to a canonical CVM code
                  (ITR/DFP pad CD_CVM to 6 digits, e.g. "001023"; CAD/IPE ship
                  it unpadded "1023" — normalise so the cia_* tables join)
        int     — parse integer (handles BR thousands separator)
        numeric — strip R$, normalise BR decimal comma (1.234,56 -> 1234.56)
        pct     — same as numeric (CVM ships raw fractions or percentages;
                  callers normalise downstream if needed)
        date    — try ISO then BR then YYYYMMDD then 2-digit-year BR
        bool    — S/SIM/TRUE/1/Y/YES -> True; everything else -> False
    """
    if value is None:
        return None
    s = str(value).strip()
    if s.upper() in _NULLISH:
        return None

    if type_ == "text":
        return s if s else None

    if type_ == "cnpj":
        digits = "".join(ch for ch in s if ch.isdigit())
        return digits.zfill(14) if digits else None

    if type_ == "cd_cvm":
        digits = "".join(ch for ch in s if ch.isdigit()).lstrip("0")
        return digits or None

    if type_ in ("numeric", "pct"):
        t = s.replace(" ", "").lstrip("R$").strip()
        # BR notation: 1.234.567,89 -> 1234567.89; 1234,89 -> 1234.89
        if "," in t and "." in t:
            t = t.replace(".", "").replace(",", ".")
        elif "," in t:
            t = t.replace(",", ".")
        try:
            return float(t)
        except ValueError:
            return None

    if type_ == "int":
        try:
            return int(float(s.replace(".", "").replace(",", ".")))
        except ValueError:
            return None

    if type_ == "date":
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y%m%d", "%d/%m/%y"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return None

    if type_ == "bool":
        return s.upper() in {"S", "SIM", "TRUE", "1", "Y", "YES"}

    raise ValueError(f"unknown coerce type: {type_!r}")


def apply_map(
    row: Mapping[str, Any],
    field_map: Mapping[str, tuple[Sequence[str], CoerceType]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply FIELD_MAP to a CSV row dict.

    Returns (typed_columns, residual_raw).
        typed_columns  — {db_col: coerced_value} for each mapped field.
                         Value is None when no candidate was found in the row.
        residual_raw   — {csv_key: raw_value} for all CSV keys NOT consumed
                         by any candidate list (the residual for the `raw`
                         JSONB column).
    """
    # Build a case-insensitive index once per row
    index = {_norm(k): k for k in row.keys()}
    typed: dict[str, Any] = {}
    consumed: set[str] = set()

    for col, (candidates, type_) in field_map.items():
        chosen_key = None
        for cand in candidates:
            real = index.get(_norm(cand))
            if real is not None and str(row.get(real, "")).strip() not in ("", "NULL", "NA"):
                chosen_key = real
                break
        if chosen_key is None:
            typed[col] = None
        else:
            typed[col] = coerce(row.get(chosen_key), type_)
            consumed.add(chosen_key)

    residual = {k: v for k, v in row.items() if k not in consumed}
    return typed, residual


# ---------------------------------------------------------------------------
# Field-map drift detection
#
# apply_map answers "what is this row?" but cannot report "this FIELD_MAP no
# longer fits the source". That blind spot is how the FIAGRO map went stale:
# CVM-175 renamed the headers (CNPJ_FUNDO -> CNPJ_Classe, DT_COMPTC ->
# Data_Referencia), zero candidates matched, every row parsed to all-None and
# was dropped for a missing natural key, and the ingest returned 0 rows without
# raising — 34 slices logged 'ok' behind an empty table.
#
# Drift shows up in the HEADER, not in the values, so these helpers compare the
# map's candidates against the CSV's keys and ignore values entirely. A column
# whose candidates are all absent from the header can never be populated.
# ---------------------------------------------------------------------------


class FieldMapMismatch(RuntimeError):
    """A FIELD_MAP no longer matches the source header (schema drift)."""


@dataclass(frozen=True)
class MapCoverage:
    matched: frozenset[str]      # db columns with a candidate present in the header
    unmatched: frozenset[str]    # db columns whose every candidate is absent

    @property
    def ratio(self) -> float:
        total = len(self.matched) + len(self.unmatched)
        return 1.0 if total == 0 else len(self.matched) / total


def map_coverage(
    header: Iterable[str],
    field_map: Mapping[str, tuple[Sequence[str], CoerceType]],
) -> MapCoverage:
    """Which FIELD_MAP columns could possibly be populated from `header`.

    Presence-only: a column counts as matched when any of its candidates appears
    in the header, regardless of whether that cell happens to be empty in a
    given row.
    """
    index = {_norm(k) for k in header}
    matched, unmatched = set(), set()
    for col, (candidates, _type) in field_map.items():
        if any(_norm(c) in index for c in candidates):
            matched.add(col)
        else:
            unmatched.add(col)
    return MapCoverage(frozenset(matched), frozenset(unmatched))


def assert_map_matches(
    rows: Sequence[Mapping[str, Any]],
    field_map: Mapping[str, tuple[Sequence[str], CoerceType]],
    *,
    dataset: str,
    required: Sequence[str] = (),
    warn_below: float = 0.5,
) -> MapCoverage:
    """Fail fast when a FIELD_MAP has drifted away from the source header.

    `required` names the columns the caller cannot ingest without — normally the
    natural key (e.g. ("cnpj", "period")). If any of them has no candidate in the
    header, raise: every row would be dropped and the slice would look like a
    successful no-op.

    A low overall match ratio only warns. Several maps in this repo legitimately
    list candidates for multiple tab/format variants and are sparse by design, so
    a hard threshold there would break working ingests.

    An empty `rows` is not drift (a genuinely empty slice) and returns silently.
    """
    if not rows:
        return MapCoverage(frozenset(), frozenset())

    # CSV batches are rectangular, but union a few rows in case a source ships
    # ragged dicts.
    header: set[str] = set()
    for row in rows[:10]:
        header.update(row.keys())

    cov = map_coverage(header, field_map)

    missing_required = [c for c in required if c in cov.unmatched]
    if missing_required:
        raise FieldMapMismatch(
            f"{dataset}: FIELD_MAP no longer matches the source header — required "
            f"column(s) {missing_required} have no candidate in the CSV. "
            f"Matched {sorted(cov.matched)}; unmatched {sorted(cov.unmatched)}. "
            f"Header sample: {sorted(header)[:12]}. "
            f"The source likely renamed its columns (e.g. a CVM-175 change); "
            f"update src/parsers/field_maps/."
        )

    if cov.ratio < warn_below:
        logger.warning(
            "%s: FIELD_MAP matched only %d/%d columns (%.0f%%) — possible source "
            "schema drift. Unmatched: %s",
            dataset, len(cov.matched), len(cov.matched) + len(cov.unmatched),
            cov.ratio * 100, sorted(cov.unmatched),
        )
    return cov


# ---------------------------------------------------------------------------
# Lifecycle helper
# ---------------------------------------------------------------------------

# Status tokens (matched case-insensitively, accent-insensitive enough for CVM)
# that indicate an instrument is currently operating. Everything else
# (CANCELADA, LIQUIDAÇÃO, INCORPORAÇÃO, ENCERRADA, pré-operacional, em análise…)
# is treated as not-active. Used to retain discontinued instruments with a clear
# is_active flag rather than dropping them.
_ACTIVE_STATUS_TOKENS = ("FUNCIONAMENTO NORMAL", "EM FUNCIONAMENTO", "ATIVO")


def derive_is_active(status: Any) -> Optional[bool]:
    """Map a CVM status/situacao string to a tri-state active flag.

    Returns True for operating instruments, False for discontinued ones, and
    None when status is missing (unknown), so callers can distinguish
    "known inactive" from "no status available".
    """
    if status is None:
        return None
    s = str(status).strip().upper()
    if not s:
        return None
    return any(token in s for token in _ACTIVE_STATUS_TOKENS)
