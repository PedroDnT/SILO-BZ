"""Declarative field-map engine.

Turns a raw CSV row + a dataset FIELD_MAP into (typed_columns, residual_raw),
so ingestion is map-driven and deterministic. See
docs/planning/02_ARCHITECTURE_AND_CONVENTIONS.md (sections 1-2).

A FIELD_MAP is::

    FIELD_MAP = { db_column: (["CSV_CANDIDATE", ...], coerce_type) }

The first non-empty candidate (case-insensitive) wins. `residual_raw` is the
original row minus every consumed source key, so `raw` only ever holds fields
we have not modeled yet.

coerce_type values: text, cnpj, int, numeric, pct, date, bool
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional, Sequence

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
