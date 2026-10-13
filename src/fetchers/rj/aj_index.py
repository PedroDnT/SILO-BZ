"""Which inventoried administrador judicial (AJ) a text names (#846, the resolver's first step).

A DJEN act often names the case's AJ, by its website or by its name. This module
recognises only AJs already in the #844 inventory (``aj_sites.csv``), so it never
records a new name, and it never guesses:

* a text that cites an inventoried AJ's domain (``www.vonsaltiel.com.br``) names that AJ;
* otherwise a text that contains one of the AJ's inventoried names, folded, does;
  names that are too short or made only of generic words ("Administração Judicial
  Ltda") are not used, and neither is a name two inventory rows share;
* when the text names two different AJs, the answer is None.

The answer is the inventory row's domain and its first listed name, as printed there.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.fetchers.rj.parse import fold

INVENTORY = Path(__file__).with_name("aj_sites.csv")
MIN_NAME_CHARS = 12
_GENERIC = {
    "administracao", "administracoes", "administradora", "administrador", "administradores",
    "judicial", "judiciais", "ltda", "ss", "s/s", "sociedade", "advogados", "advocacia",
    "consultoria", "consultores", "empresarial", "empresariais", "empresas", "assessoria", "me", "eireli",
    "de", "e", "do", "da", "dos", "das", "unipessoal", "individual", "simples", "epp",
}


@dataclass(frozen=True)
class AJ:
    domain: str
    name: str      # the first name the inventory lists for the domain


def _names(cell: str) -> List[str]:
    return [n.strip() for n in re.split(r"\s*[|/]\s*", cell or "") if n.strip()]


def _specific(folded: str) -> bool:
    words = [w for w in re.findall(r"[a-z0-9/]+", folded) if w not in _GENERIC]
    return len(folded) >= MIN_NAME_CHARS and len("".join(words)) >= 5


@lru_cache(maxsize=1)
def _index() -> Tuple[Dict[str, AJ], Dict[str, AJ]]:
    by_domain: Dict[str, AJ] = {}
    by_name: Dict[str, Optional[AJ]] = {}
    with open(INVENTORY, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            names = _names(row["aj_names"])
            if not names:
                continue
            aj = AJ(domain=row["domain"].lower(), name=names[0])
            by_domain[aj.domain] = aj
            for n in names:
                key = fold(n).rstrip(" .,;")  # "Ltda." matches a text that prints "Ltda"
                if _specific(key):
                    # A name two rows share names neither of them.
                    by_name[key] = None if key in by_name and by_name[key] != aj else aj
    return by_domain, {k: v for k, v in by_name.items() if v is not None}


def aj_named_in(text: str) -> Optional[AJ]:
    """The one inventoried AJ the text names, or None (none named, or more than one)."""
    folded = fold(text)
    if not folded:
        return None
    by_domain, by_name = _index()
    found = {aj for d, aj in by_domain.items()
             if re.search(r"(?<![a-z0-9.-])(?:www\.)?" + re.escape(d) + r"(?![a-z0-9-])", folded)}
    if not found:
        found = {aj for n, aj in by_name.items() if re.search(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])", folded)}
    return found.pop() if len(found) == 1 else None
