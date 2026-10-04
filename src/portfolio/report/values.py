"""JSON paths into the engine output, and Brazilian formatting of their values.

A placeholder is ``{{path}}``: dot-separated keys with ``[i]`` list indexes,
for example ``{{fees.by_line[3].estimated_pct_year}}``. The renderer is the
only place a figure becomes text, and it formats by the path's last key:

| key                          | unit in the engine JSON | printed as            |
| ---------------------------- | ----------------------- | --------------------- |
| contains ``_brl``            | reais                   | ``R$ 1.234,56`` / ``R$ 187,3 milhões`` |
| contains ``_pct``            | percent (1.65 = 1,65%)  | ``1,65%``             |
| contains ``cnpj``            | 14 digits               | ``00.000.000/0000-00``|
| ``month`` / ``competencia``  | ISO date, first of month| ``08/2026``           |
| other ISO date               | ``YYYY-MM-DD``          | ``31/08/2026``        |
| ISO timestamp                | UTC                     | ``03/10/2026 13:00 (UTC-3) (16:00 UTC)`` |
| ``old_num`` / ``new_num`` / ``change_brl`` of a ``VL_*`` leaf | reais | as ``_brl`` |

This table is the report's one dependency on the engine's unit convention
(``docs/reference/portfolio/redator-revisor.md``); change it here when the engine's
schema doc says otherwise.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

PLACEHOLDER_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_TOKEN_RE = re.compile(r"([^.\[\]]+)|\[(\d+)\]")
_PATH_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[\d+\]|\.[A-Za-z_][A-Za-z0-9_]*)*$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")
_MONTH_KEYS = {"month", "competencia", "mes"}

# Brasília: UTC-3, no daylight saving since 2019 (owner's display rule).
BRT = timezone(timedelta(hours=-3), "UTC-3")

MISSING = object()


class PathError(KeyError):
    pass


def parse_path(path: str) -> list[str | int]:
    path = path.strip()
    if not _PATH_RE.match(path):
        raise PathError(f"malformed path {path!r}")
    out: list[str | int] = []
    for key, idx in _TOKEN_RE.findall(path):
        out.append(int(idx) if idx else key)
    return out


def resolve(doc: Any, path: str) -> Any:
    """The value at ``path``, or ``MISSING`` when any step does not exist."""
    try:
        tokens = parse_path(path)
    except PathError:
        return MISSING
    cur = doc
    for tok in tokens:
        if isinstance(tok, int):
            if not isinstance(cur, list) or tok >= len(cur):
                return MISSING
            cur = cur[tok]
        else:
            if not isinstance(cur, dict) or tok not in cur:
                return MISSING
            cur = cur[tok]
    return cur


def parent_path(path: str) -> str:
    tokens = parse_path(path)
    return join_path(tokens[:-1])


def last_key(path: str) -> str:
    """The last dict key of ``path`` (list indexes skipped)."""
    for tok in reversed(parse_path(path)):
        if isinstance(tok, str):
            return tok
    return ""


def join_path(tokens: list[str | int]) -> str:
    out = ""
    for tok in tokens:
        if isinstance(tok, int):
            out += f"[{tok}]"
        else:
            out += ("." if out else "") + tok
    return out


def iter_leaves(doc: Any, prefix: list[str | int] | None = None) -> Iterator[tuple[str, Any]]:
    """Every scalar leaf as ``(path, value)``."""
    prefix = prefix or []
    if isinstance(doc, dict):
        for k, v in doc.items():
            yield from iter_leaves(v, prefix + [k])
    elif isinstance(doc, list):
        for i, v in enumerate(doc):
            yield from iter_leaves(v, prefix + [i])
    else:
        yield join_path(prefix), doc


def is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _group(int_part: str) -> str:
    out = []
    while len(int_part) > 3:
        out.insert(0, int_part[-3:])
        int_part = int_part[:-3]
    out.insert(0, int_part)
    return ".".join(out)


def fmt_number(v: float, decimals: int) -> str:
    s = f"{abs(v):.{decimals}f}"
    if decimals:
        i, d = s.split(".")
        body = f"{_group(i)},{d}"
    else:
        body = _group(s)
    return ("-" if v < 0 and float(s) != 0 else "") + body


def fmt_brl(v: float) -> str:
    a = abs(v)
    sign = "-" if v < 0 else ""
    if a >= 1e9:
        n = a / 1e9
        return f"{sign}R$ {fmt_number(n, 2)} {'bilhão' if n < 2 else 'bilhões'}"
    if a >= 1e6:
        n = a / 1e6
        return f"{sign}R$ {fmt_number(n, 1)} {'milhão' if n < 2 else 'milhões'}"
    return f"{sign}R$ {fmt_number(a, 2)}"


def fmt_pct(v: float) -> str:
    return f"{fmt_number(v, 2)}%"


def fmt_cnpj(s: str) -> str:
    d = re.sub(r"\D", "", s)
    if len(d) != 14:
        return s
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def fmt_date(s: str, month_only: bool = False) -> str:
    y, m, d = s.split("-")
    return f"{m}/{y}" if month_only else f"{d}/{m}/{y}"


def fmt_timestamp(s: str) -> str:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    utc = dt.astimezone(timezone.utc)
    return dt.astimezone(BRT).strftime("%d/%m/%Y %H:%M") + f" (UTC-3) ({utc:%H:%M} UTC)"


def unit_of(doc: Any, path: str) -> str:
    """``brl`` | ``pct`` | ``cnpj`` | ``month`` | ``date`` | ``plain`` for the leaf at ``path``."""
    key = last_key(path).lower()
    if "_brl" in key or key == "brl":
        return "brl"
    if "_pct" in key or key == "pct":
        return "pct"
    if "cnpj" in key:
        return "cnpj"
    if key in ("old_num", "new_num", "change", "change_num"):
        parent = resolve(doc, parent_path(path))
        if isinstance(parent, dict) and str(parent.get("leaf", "")).upper().startswith("VL_"):
            return "brl"
    if key in _MONTH_KEYS:
        return "month"
    return "plain"


def format_value(doc: Any, path: str, value: Any = MISSING) -> str:
    """The Brazilian text for the leaf at ``path`` (``value`` overrides the lookup)."""
    v = resolve(doc, path) if value is MISSING else value
    unit = unit_of(doc, path)
    if v is None or v is MISSING:
        return "—"
    if isinstance(v, bool):
        return "sim" if v else "não"
    if is_number(v):
        if unit == "brl":
            return fmt_brl(float(v))
        if unit == "pct":
            return fmt_pct(float(v))
        if isinstance(v, int):
            return fmt_number(v, 0)
        decimals = min(6, max(2, len(repr(float(v)).split(".")[1].rstrip("0"))))
        return fmt_number(float(v), decimals)
    if isinstance(v, str):
        if unit == "cnpj":
            return fmt_cnpj(v)
        if _DATE_RE.match(v):
            return fmt_date(v, month_only=(unit == "month"))
        if _TS_RE.match(v):
            return fmt_timestamp(v)
        return v
    return str(v)


def is_date_string(v: Any) -> bool:
    return isinstance(v, str) and bool(_DATE_RE.match(v) or _TS_RE.match(v))
