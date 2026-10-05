"""Is a fund CDI-like? Its own filed benchmark, read against the versioned spelling list (engine 1.12).

Owner's decision (#606, addendum Q36 of 2026-10-05): "% do CDI" is shown only for a fund whose own filed benchmark
is CDI or DI, as filed in the CVM Extrato (``PARAM_TAXA_PERFM``, the performance fee's index, its only benchmark
column) or the lâmina (``INDICE_REFER``). Never inferred from a name or an ANBIMA class. The accepted spellings are
the exact list in ``rules/benchmark_cdi.yaml``, matched after ``normalize``; nothing else is matched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

RULES = Path(__file__).resolve().parent / "rules" / "benchmark_cdi.yaml"

NOT_FILED = "referencia_nao_informada"
NOT_CDI = "referencia_nao_cdi"
DIVERGES = "referencia_diverge"


class BenchmarkRuleError(ValueError):
    """The rule file is malformed."""


@dataclass(frozen=True)
class Rules:
    version: int
    accepted: frozenset[str]
    rejected: frozenset[str]


def normalize(value: str | None) -> str | None:
    """Trim, collapse inner whitespace, upper-case. Blank is None. No other change (accents and punctuation stay)."""
    if value is None:
        return None
    out = re.sub(r"\s+", " ", str(value)).strip().upper()
    return out or None


def parse_rules(doc: Any) -> Rules:
    if not isinstance(doc, dict) or not isinstance(doc.get("version"), int):
        raise BenchmarkRuleError("the file needs an integer 'version'")
    lists = {}
    for key in ("accepted", "rejected"):
        entries = doc.get(key)
        if not isinstance(entries, list) or not entries:
            raise BenchmarkRuleError(f"'{key}' must be a non-empty list")
        spellings = []
        for i, e in enumerate(entries):
            sp = e.get("spelling") if isinstance(e, dict) else None
            if not isinstance(sp, str) or normalize(sp) != sp:
                raise BenchmarkRuleError(f"{key}[{i}]: 'spelling' must be written normalized: {sp!r}")
            spellings.append(sp)
        if len(set(spellings)) != len(spellings):
            raise BenchmarkRuleError(f"'{key}' repeats a spelling")
        lists[key] = frozenset(spellings)
    both = lists["accepted"] & lists["rejected"]
    if both:
        raise BenchmarkRuleError(f"spellings both accepted and rejected: {sorted(both)}")
    return Rules(doc["version"], lists["accepted"], lists["rejected"])


@lru_cache(maxsize=1)
def load_rules(path: str = str(RULES)) -> Rules:
    with open(path, encoding="utf-8") as fh:
        return parse_rules(yaml.safe_load(fh))


def classify(extrato: str | None, lamina: str | None, lamina_n: int | None, rules: Rules | None = None) -> dict[str, Any]:
    """CDI-like or not, with the reason code when not.

    ``extrato`` is ``benchmark_extrato``; ``lamina`` is ``benchmark_lamina`` (one value only when every class filed
    the same one) and ``lamina_n`` the count of distinct values the lâmina's classes filed.
    """
    rules = rules or load_rules()
    filed = {}
    if normalize(extrato):
        filed["extrato"] = normalize(extrato)
    if normalize(lamina):
        filed["lamina"] = normalize(lamina)
    out = {"cdi_like": False, "reason_code": None, "matched": [], "rule_version": rules.version,
           "normalized": dict(filed)}
    if isinstance(lamina_n, int) and (lamina_n > 1 or (lamina_n == 1 and not normalize(lamina))):
        # the lâmina's classes file different indices, or some filed one and some none: no single benchmark
        out["reason_code"] = DIVERGES
        return out
    if not filed:
        out["reason_code"] = NOT_FILED
        return out
    accepted = {k: v in rules.accepted for k, v in filed.items()}
    if all(accepted.values()):
        out.update(cdi_like=True, matched=sorted(f"{k}:{filed[k]}" for k in filed))
    elif any(accepted.values()):
        out["reason_code"] = DIVERGES
    else:
        out["reason_code"] = NOT_CDI
    return out
