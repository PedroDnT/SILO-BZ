"""JSON paths into the engine output, and Brazilian formatting of their values.

A placeholder is ``{{path}}``: dot-separated keys with ``[i]`` list indexes,
for example ``{{fees.by_line[3].estimated_pct_year}}``. The renderer is the
only place a figure becomes text. ``unit_for`` decides a figure's unit from
the path's last key by the declared ``UNIT_RULES``, and ``format_as`` prints a
value in a unit; ``format_value`` reads a path and prints it:

| key                          | unit in the engine JSON | printed as            |
| ---------------------------- | ----------------------- | --------------------- |
| ``brl`` or a ``_brl`` word   | reais                   | ``R$ 1.234,56`` / ``R$ 187,3 milhões`` |
| ``pct`` or a ``_pct`` word   | percent (1.65 = 1,65%)  | ``1,65%``             |
| contains ``cnpj``            | 14 digits               | ``00.000.000/0000-00``|
| ``month`` / ``competencia`` / ends ``_month`` | ISO date, first of month | ``08/2026`` |
| ends ``_pp``                 | percentage points       | ``-0,43 p.p.``        |
| ``pct_of_cdi``               | percent of the CDI      | ``97,05% do CDI``     |
| other ISO date               | ``YYYY-MM-DD``          | ``31/08/2026``        |
| ISO timestamp                | UTC                     | ``03/10/2026 13:00 (UTC-3) (16:00 UTC)`` |
| ``old_num`` / ``new_num`` / ``change_brl`` of a ``VL_*`` leaf | reais | as ``_brl`` |

This table, written as ``UNIT_RULES`` and ``DIFF_NUMBER_KEYS``, is the report's one dependency on the engine's unit convention
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


# The units, decided once: every figure's unit comes from ``unit_for`` and every figure's text from ``format_as``.
BRL, PCT, PP, PCT_CDI, CNPJ, MONTH, PLAIN = "brl", "pct", "pp", "pct_cdi", "cnpj", "month", "plain"

# The engine's unit convention, declared (docs/reference/portfolio/redator-revisor.md, "The placeholder rule"): a
# figure's key names its unit, ``<what>_<unit>[_<qualifier>...]`` (``value_brl``, ``estimated_pct_year``,
# ``net_minus_cdi_pp``, ``end_month``). Each pattern is matched against the lowercased last key of a path and the first
# that matches decides. A key no rule matches is ``PLAIN``: printed by its type (number, ISO date, timestamp, text).
UNIT_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^pct_of_cdi$"), PCT_CDI),  # engine 1.13: the phrase "% do CDI" is the formatter's, never the writer's
    (re.compile(r"^brl$|_brl(?=_|$)"), BRL),
    (re.compile(r"^pct$|_pct(?=_|$)"), PCT),
    (re.compile(r"cnpj"), CNPJ),  # cnpj, fund_cnpj, cnpj_securit, p_cnpjs[i]
    (re.compile(r"_pp$"), PP),
    (re.compile(r"_month$|^(month|competencia|mes)$"), MONTH),  # engine 1.10: base_month, max_drawdown_peak_month
)

# The one unit the key cannot carry: a restatement diff row's numbers (``restatements.items[i].diff[j]``) are reais
# when the row's filed field (``leaf``) is a ``VL_*`` value, and plain otherwise.
DIFF_NUMBER_KEYS = frozenset({"old_num", "new_num", "change", "change_num"})


def unit_for(key: str, parent: Any = None) -> str:
    """The unit of the figure at ``key`` of the dict ``parent``: one of the constants above."""
    low = key.lower()
    for pattern, unit in UNIT_RULES:
        if pattern.search(low):
            return unit
    if low in DIFF_NUMBER_KEYS and isinstance(parent, dict) and str(parent.get("leaf", "")).upper().startswith("VL_"):
        return BRL
    return PLAIN


def unit_of(doc: Any, path: str) -> str:
    """``unit_for`` the leaf at ``path`` of ``doc``, which may be the view or any dict read from it."""
    key = last_key(path)
    if key.lower() not in DIFF_NUMBER_KEYS:
        return unit_for(key)
    tokens = parse_path(path)
    return unit_for(key, resolve(doc, join_path(tokens[:-1])) if len(tokens) > 1 else doc)


def format_as(v: Any, unit: str) -> str:
    """The Brazilian text for the value ``v`` in ``unit`` (a constant above)."""
    if v is None or v is MISSING:
        return "—"
    if isinstance(v, bool):
        return "sim" if v else "não"
    if is_number(v):
        if unit == BRL:
            return fmt_brl(float(v))
        if unit == PCT:
            return fmt_pct(float(v))
        if unit == PP:
            return f"{fmt_number(float(v), 2)} p.p."
        if unit == PCT_CDI:
            return f"{fmt_number(float(v), 2)}% do CDI"
        if isinstance(v, int):
            return fmt_number(v, 0)
        decimals = min(6, max(2, len(repr(float(v)).split(".")[1].rstrip("0"))))
        return fmt_number(float(v), decimals)
    if isinstance(v, str):
        if unit == CNPJ:
            return fmt_cnpj(v)
        if _DATE_RE.match(v):
            return fmt_date(v, month_only=(unit == MONTH))
        if _TS_RE.match(v):
            return fmt_timestamp(v)
        return v
    return str(v)


def format_value(doc: Any, path: str, value: Any = MISSING) -> str:
    """The Brazilian text for the leaf at ``path`` (``value`` overrides the lookup).

    ``doc`` is the view or any dict read from it, with ``path`` relative to it: a helper handed a fee line formats
    ``format_value(line, "estimated_pct_year")``, the same text as the full path from the view's root."""
    unit = unit_of(doc, path)
    return format_as(resolve(doc, path) if value is MISSING else value, unit)


def is_date_string(v: Any) -> bool:
    return isinstance(v, str) and bool(_DATE_RE.match(v) or _TS_RE.match(v))
