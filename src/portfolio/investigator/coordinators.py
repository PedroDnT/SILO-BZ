"""The reviewed coordinator -> domain map (``src/portfolio/rules/investigator/coordinators.yaml``, #605).

Only ``aprovada`` entries are used. A coordinator is matched from an accepted "coordenador" fact of the
issue's own documents, never from the asset's name. Loading validates every entry and raises on a bad one:
a malformed reviewed file is a bug to fix, not a list to half-use.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from src.portfolio.investigator.text import normalize

PATH = Path(__file__).resolve().parents[1] / "rules" / "investigator" / "coordinators.yaml"
STATUSES = ("proposta", "aprovada")
_DOMAIN = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")


@dataclass(frozen=True)
class Coordinator:
    cnpj: str | None
    names: tuple[str, ...]
    domains: tuple[str, ...]
    status: str
    evidence: str

    def matches(self, value: str) -> bool:
        digits = re.findall(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}", value or "")
        if self.cnpj and any(re.sub(r"\D", "", d) == self.cnpj for d in digits):
            return True
        nv = normalize(value).replace(".", "").replace(",", "")
        return any(normalize(n).replace(".", "").replace(",", "") in nv for n in self.names)


def load(path: Path | str = PATH) -> list[Coordinator]:
    import yaml  # PyYAML is in the engine image (deploy/cloudflare/engine/requirements.txt, #642)

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    out: list[Coordinator] = []
    for i, e in enumerate(data.get("coordinators") or []):
        status = e.get("status")
        if status not in STATUSES:
            raise ValueError(f"coordinators.yaml entry {i}: status must be one of {STATUSES}, got {status!r}")
        cnpj = e.get("cnpj")
        if cnpj is not None and not re.fullmatch(r"\d{14}", str(cnpj)):
            raise ValueError(f"coordinators.yaml entry {i}: cnpj must be 14 digits or null")
        names = tuple(str(n) for n in e.get("names") or [] if str(n).strip())
        domains = tuple(str(d).strip().lower() for d in e.get("domains") or [])
        if not names or not domains or not all(_DOMAIN.match(d) for d in domains):
            raise ValueError(f"coordinators.yaml entry {i}: needs names and valid domains")
        if not str(e.get("evidence") or "").strip().startswith("http"):
            raise ValueError(f"coordinators.yaml entry {i}: evidence must start with the URL that was fetched")
        out.append(Coordinator(str(cnpj) if cnpj else None, names, domains, status, str(e.get("evidence"))))
    return out


def approved_domains(value: str, entries: list[Coordinator]) -> list[str]:
    """The domains of every APPROVED entry the coordinator fact's value matches (sorted, unique)."""
    return sorted({d for c in entries if c.status == "aprovada" and c.matches(value) for d in c.domains})


def proposed_match(value: str, entries: list[Coordinator]) -> bool:
    """True when only a ``proposta`` entry matches: said in the output, never used."""
    return any(c.status == "proposta" and c.matches(value) for c in entries)
