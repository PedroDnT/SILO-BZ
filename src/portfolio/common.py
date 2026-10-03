"""Helpers shared by the blocks: sources, sections, number formatting.

Every number in the engine output carries a ``sources`` list. A source is
``{"tool", "call_id", "args", "data_date"}``; ``tool == "statement"`` means the
number came from the client's own statement (``args`` names the line).
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from src.portfolio.client import SiloClient, ToolError

STATUS_COMPLETE = "complete"
STATUS_PARTIAL = "partial"
STATUS_UNKNOWN = "unknown"
STATUS_NOT_APPLICABLE = "not_applicable"

UNCLASSIFIED = "sem classificação"


def dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return None
    try:
        out = Decimal(str(value))
    except ArithmeticError:  # decimal.InvalidOperation: not a number at source, reported as None
        return None
    return out if out.is_finite() else None


def brl(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def ratio(value: Decimal | None, places: int = 8) -> float | None:
    if value is None:
        return None
    return float(value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def pct(part: Decimal, whole: Decimal) -> float | None:
    if whole == 0:
        return None
    return float((part / whole * 100).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def iso(d: dt.date | None) -> str | None:
    return d.isoformat() if d else None


def as_date(value: Any) -> dt.date | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    s = str(value)[:10]
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        return None


def month_start(d: dt.date) -> dt.date:
    return d.replace(day=1)


def add_months(d: dt.date, n: int) -> dt.date:
    y, m = divmod(d.month - 1 + n, 12)
    return dt.date(d.year + y, m + 1, 1)


def source(tool: str, call_id: int | None, args: dict | None, data_date: Any) -> dict[str, Any]:
    dd = data_date.isoformat() if isinstance(data_date, dt.date) else (str(data_date)[:10] if data_date else None)
    return {"tool": tool, "call_id": call_id, "args": args or {}, "data_date": dd}


def statement_source(line_no: int, data_posicao: dt.date) -> dict[str, Any]:
    return source("statement", None, {"line_no": line_no}, data_posicao)


@dataclass
class Call:
    """One tool call's outcome as a block sees it."""

    tool: str
    args: dict
    call_id: int | None
    rows: list[dict] | None
    error: str | None

    @property
    def ok(self) -> bool:
        return self.rows is not None

    def src(self, data_date: Any = None) -> dict[str, Any]:
        return source(self.tool, self.call_id, self.args, data_date)


def call_tool(client: SiloClient, tool: str, args: dict, errors: list[dict]) -> Call:
    """Call a tool; a failure is appended to ``errors`` verbatim and returned as ``rows=None``."""
    try:
        rows = client.call(tool, args)
        return Call(tool, args, client.last_call_id, rows, None)
    except ToolError as exc:
        errors.append({"call_id": client.last_call_id, "tool": tool, "args": args, "error": exc.verbatim})
        return Call(tool, args, client.last_call_id, None, exc.verbatim)


@dataclass
class Section:
    """A report section: complete, partial, unknown (with reason) or not applicable."""

    status: str = STATUS_COMPLETE
    reason: str | None = None
    errors: list[dict] = field(default_factory=list)

    def head(self) -> dict[str, Any]:
        return {"status": self.status, "reason": self.reason, "errors": self.errors}

    def degrade(self, reason: str) -> None:
        """Mark partial (unless already unknown) and append the reason."""
        if self.status in (STATUS_COMPLETE, STATUS_NOT_APPLICABLE):
            self.status = STATUS_PARTIAL
        self.reason = reason if not self.reason else f"{self.reason} {reason}"

    def fail(self, reason: str) -> None:
        self.status = STATUS_UNKNOWN
        self.reason = reason


# B3's root is four letters OR digits (B3SA3, and ETFs such as B5P211, 5PRE11 and TD3511: 8 of the 187 tickers in
# the ETF registry on 2026-10-03), then 1 or 2 digits; at least one letter, so no number is read as a ticker.
_TICKER_RE = re.compile(r"^(?=[A-Z0-9]*[A-Z])[A-Z0-9]{4}\d{1,2}[A-Z]?$")


def is_ticker(code: str | None) -> bool:
    return bool(code) and bool(_TICKER_RE.match(code.strip().upper()))


def b3_issuer_code(isin: str | None) -> str | None:
    """ISIN characters 3 to 6 (1-based): B3's issuer code. Brazilian ISINs only."""
    if not isin or len(isin) != 12 or not isin.upper().startswith("BR"):
        return None
    return isin[2:6].upper()


def cnpj_root(cnpj: str | None) -> str | None:
    if not cnpj:
        return None
    d = re.sub(r"\D", "", str(cnpj))
    return d[:8] if len(d) == 14 else None
