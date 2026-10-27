"""ANBIMA's national holiday list (feriados_nacionais.xls), parsed as published (#1007).

The sheet has the header ``Data / Dia da Semana / Feriado``, one row per holiday,
then footnotes. A row whose first cell is not a date ends the list; a list with no
dates is an error, never a partial result. Two holidays on one date (2079-04-21) are
one row with both names joined by " / ".
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable

SOURCE_URL = "https://www.anbima.com.br/feriados/arqs/feriados_nacionais.xls"


class HolidayParseError(ValueError):
    pass


def parse_holidays(rows: Iterable[tuple[Any, Any, Any]]) -> list[dict]:
    out, seen = [], set()
    for i, (cell, _weekday, name) in enumerate(rows):
        if i == 0:
            if str(cell).strip().lower() != "data":
                raise HolidayParseError(f"unexpected header {cell!r}")
            continue
        if not isinstance(cell, (datetime, date)):
            break
        d = cell.date() if isinstance(cell, datetime) else cell
        label = str(name).strip()
        if not label or label.lower() == "nan":
            raise HolidayParseError(f"{d}: holiday without a name")
        if d in seen:
            prev = next(r for r in out if r["holiday_date"] == d)
            prev["name"] += " / " + label
            continue
        seen.add(d)
        out.append({"holiday_date": d, "name": label, "source_url": SOURCE_URL})
    if not out:
        raise HolidayParseError("no holiday dates found")
    return out
