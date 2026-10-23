"""Parse one page of ANBIMA's public search list (/busca/debentures,
/busca/certificado-de-recebiveis) into codes (#1006, #1014).

Each card names its code just above "Calcular ativo", and shows "PU Indicativo"
with a value or '-'. A code with a value is one that ANBIMA prices today. The
page footer says "Exibindo a - b de N resultados"; the fetcher checks that the
pages together hold exactly N distinct codes.

A layout this parser does not know raises ``AnbimaParseError``.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from src.parsers.anbima_debenture import AnbimaParseError, _missing

# One debenture code has a space, as ANBIMA publishes and links it: "SNB 11".
_CODE = re.compile(r"[A-Z0-9][A-Z0-9 ]{4,10}[A-Z0-9]")
_SHOWN = re.compile(r"Exibindo\s+([\d.]+)\s*-\s*([\d.]+)\s+de\s+([\d.]+)\s+resultados")
# Lines a card may show between its code and "Calcular ativo".
_TAGS = {"LEI 12.431", "CRI", "CRA"}


class Listed(NamedTuple):
    codigo: str
    priced: bool  # "PU Indicativo" shows a value, not '-'


class ListingPage(NamedTuple):
    items: list[Listed]
    first: int
    last: int
    total: int


def _int(s: str) -> int:
    return int(s.replace(".", ""))


def parse_listing(text: str) -> ListingPage:
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    starts = [i for i, x in enumerate(lines) if x == "Calcular ativo"]
    items: list[Listed] = []
    for n, i in enumerate(starts):
        j = i - 1
        while j >= 0 and lines[j] in _TAGS:
            j -= 1
        if j >= 2 and lines[j - 1] == "•":  # "CODE • Name" on a CRI/CRA card
            j -= 2
        if j < 0 or not _CODE.fullmatch(lines[j]):
            raise AnbimaParseError(f"listing card without a code before line {i}: {lines[max(j, 0)]!r}")
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        try:
            k = lines.index("PU Indicativo", i, end)
        except ValueError as exc:
            raise AnbimaParseError(f"{lines[j]}: listing card without 'PU Indicativo'") from exc
        if k + 1 >= end:
            raise AnbimaParseError(f"{lines[j]}: 'PU Indicativo' without a value")
        items.append(Listed(lines[j], not _missing(lines[k + 1])))
    shown = _SHOWN.search(text)
    if shown is None:
        raise AnbimaParseError("listing page without its 'Exibindo a - b de N resultados' counter")
    first, last, total = (_int(g) for g in shown.groups())
    if len(items) != last - first + 1:
        raise AnbimaParseError(f"listing page shows {first}-{last} but {len(items)} cards were read")
    return ListingPage(items, first, last, total)
