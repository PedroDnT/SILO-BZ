"""ANBIMA class -> ETF index pairs (#609): the reviewed YAML, loaded and checked.

``rules/equivalents/class_index.yaml`` is the only place a fund class meets an
ETF index. The owner approves it; every pair carries ``status`` (``proposta``
until approved). Nothing here infers an index from a fund's name or a class
for an ETF: a pair exists because it is written in the file.

The same pairs reach SQL as a generated VALUES view
(``scripts/gen_class_index_sql.py`` writes the block in
``src/store/analytical/31_api_portfolio.sql``), read in reverse by
``api.portfolio_fee_peers``: an active ETF whose ``underlying_index`` is listed
under class C is a fee peer of C. ``tests/test_portfolio_equivalents.py`` pins
the SQL block to this file.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

RULES = Path(__file__).resolve().parent / "rules" / "equivalents" / "class_index.yaml"
STATUSES = ("proposta", "aprovada")
PAIR_KEYS = ("class", "index", "status", "rationale")

SQL_BEGIN = "-- BEGIN GENERATED class_index"
SQL_END = "-- END GENERATED class_index"


class EquivalentsError(ValueError):
    """The YAML is malformed, or a spelling is not one the warehouse files."""


@dataclass(frozen=True)
class Pair:
    classe_anbima: str
    underlying_index: str
    status: str
    rationale: str


def _text(entry: dict, key: str, where: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EquivalentsError(f"{where}: '{key}' must be a non-empty string")
    if value != value.strip() or "\n" in value:
        raise EquivalentsError(f"{where}: '{key}' must be one line with no outer spaces: {value!r}")
    return value


def parse_pairs(doc: object) -> list[Pair]:
    """Validate the YAML document's structure and return its pairs in file order."""
    if not isinstance(doc, dict) or not isinstance(doc.get("pairs"), list) or not doc["pairs"]:
        raise EquivalentsError("the file must hold a non-empty 'pairs' list")
    unknown_top = set(doc) - {"pairs", "unmapped"}
    if unknown_top:
        raise EquivalentsError(f"unknown top-level keys: {sorted(unknown_top)}")
    pairs: list[Pair] = []
    seen: set[tuple[str, str]] = set()
    for i, entry in enumerate(doc["pairs"]):
        where = f"pairs[{i}]"
        if not isinstance(entry, dict) or set(entry) != set(PAIR_KEYS):
            raise EquivalentsError(f"{where}: keys must be exactly {list(PAIR_KEYS)}")
        pair = Pair(_text(entry, "class", where), _text(entry, "index", where),
                    _text(entry, "status", where), _text(entry, "rationale", where))
        if pair.status not in STATUSES:
            raise EquivalentsError(f"{where}: status must be one of {STATUSES}, got {pair.status!r}")
        key = (pair.classe_anbima, pair.underlying_index)
        if key in seen:
            raise EquivalentsError(f"{where}: duplicate pair {key}")
        seen.add(key)
        pairs.append(pair)
    for i, entry in enumerate(doc.get("unmapped") or []):
        where = f"unmapped[{i}]"
        if not isinstance(entry, dict) or set(entry) != {"class", "reason"}:
            raise EquivalentsError(f"{where}: keys must be exactly ['class', 'reason']")
        cls = _text(entry, "class", where)
        _text(entry, "reason", where)
        if any(p.classe_anbima == cls for p in pairs):
            raise EquivalentsError(f"{where}: {cls!r} is both mapped and unmapped")
    return pairs


def load_pairs(path: Path | str = RULES) -> list[Pair]:
    with open(path, encoding="utf-8") as fh:
        return parse_pairs(yaml.safe_load(fh))


def check_spellings(pairs: Iterable[Pair], classes: Iterable[str], indices: Iterable[str]) -> None:
    """Raise unless every class is a filed ``classe_anbima`` and every index a filed
    ``underlying_index``. The caller passes the known spellings (a fixture in the tests,
    a bounded SELECT when the owner refreshes it); this module never queries."""
    known_classes, known_indices = set(classes), set(indices)
    missing = [f"class {p.classe_anbima!r}" for p in pairs if p.classe_anbima not in known_classes]
    missing += [f"index {p.underlying_index!r}" for p in pairs if p.underlying_index not in known_indices]
    if missing:
        raise EquivalentsError("spellings not filed: " + "; ".join(dict.fromkeys(missing)))


def indices_for_class(pairs: Iterable[Pair], classe_anbima: str) -> list[str]:
    return [p.underlying_index for p in pairs if p.classe_anbima == classe_anbima]


def classes_for_index(pairs: Iterable[Pair], underlying_index: str) -> list[str]:
    return [p.classe_anbima for p in pairs if p.underlying_index == underlying_index]


def _lit(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def sql_block(pairs: Iterable[Pair]) -> str:
    """The generated SQL block: a VALUES view the fee-peer function reads."""
    rows = ",\n".join(f"    ({_lit(p.classe_anbima)}, {_lit(p.underlying_index)}, {_lit(p.status)})"
                      for p in pairs)
    return (
        f"{SQL_BEGIN} (scripts/gen_class_index_sql.py from\n"
        "-- src/portfolio/rules/equivalents/class_index.yaml; do not edit by hand, regenerate).\n"
        "-- ANBIMA class (Extrato CLASSE_ANBIMA, as filed) -> the index an ETF tracks\n"
        "-- (cvm_etf_registry.underlying_index, as filed). status is the owner's review state.\n"
        "CREATE OR REPLACE VIEW public.portfolio_class_index AS\n"
        "SELECT v.classe_anbima, v.underlying_index, v.status\n"
        "FROM (VALUES\n"
        f"{rows}\n"
        ") AS v(classe_anbima, underlying_index, status);\n"
        "REVOKE ALL ON public.portfolio_class_index FROM PUBLIC, anon, authenticated;\n"
        "COMMENT ON VIEW public.portfolio_class_index IS\n"
        "    'Internal (31_api_portfolio.sql, #609). The reviewed ANBIMA class -> ETF index pairs of "
        "src/portfolio/rules/equivalents/class_index.yaml, generated by scripts/gen_class_index_sql.py. "
        "status proposta = not yet approved by the owner. Never inferred from a fund name.';\n"
        f"{SQL_END}"
    )


def replace_sql_block(sql: str, block: str) -> str:
    start, end = sql.find(SQL_BEGIN), sql.find(SQL_END)
    if start < 0 or end < start or sql.count(SQL_BEGIN) != 1:
        raise EquivalentsError("the SQL file must hold exactly one generated class_index block")
    return sql[:start] + block + sql[end + len(SQL_END):]
