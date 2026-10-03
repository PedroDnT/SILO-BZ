"""Block 10: exposure by indexer class.

Classes come from the versioned rules table ``rules/indexer_rules.csv``
(columns: source, field, value, indexer_class, note) applied to PUBLISHED
fields only: CDA block 1 ``tp_aplic`` / ``tp_titpub``, block 6
``cd_indexador_posfx``, block 4 ``tp_aplic``, and for direct positions the
Tesouro title or the statement type. Nothing is inferred from a name. A value
with no rule is ``sem classificação`` and the value is named in the output.

``sem classificação`` is always shown, and it also holds what the CDA does not
explain (unexplained weight of a fund) and lines the engine could not identify,
so the classes add up to the whole portfolio.
"""

from __future__ import annotations

import csv
import hashlib
import re
import unicodedata
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.portfolio.common import UNCLASSIFIED, brl, pct, ratio
from src.portfolio.identify import LineId
from src.portfolio.lookthrough import Exposure

RULES_PATH = Path(__file__).parent / "rules" / "indexer_rules.csv"
INDEXER_RULES_VERSION = "2026-10-03.1"
NULL_TOKEN = "NULL"


def load_rules(path: Path = RULES_PATH) -> dict[tuple[str, str, str], dict[str, str]]:
    rules: dict[tuple[str, str, str], dict[str, str]] = {}
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            key = (row["source"], row["field"], row["value"])
            if key in rules:
                raise ValueError(f"duplicate indexer rule {key}")
            rules[key] = row
    return rules


def rules_sha256(path: Path = RULES_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _norm_taxa(text: str | None) -> str:
    """The rate text as printed, accent-stripped, lowercase, one space between words."""
    if not text:
        return ""
    t = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip().lower()


def classify(e: Exposure, rules: dict) -> tuple[str, str, str | None]:
    """(indexer class, rule that decided it, reason when unclassified)."""

    def hit(source: str, field: str, value: str | None):
        r = rules.get((source, field, value if value is not None else NULL_TOKEN))
        return r

    if e.asset_kind == "caixa":
        r = hit("direct", "tipo", "caixa")
        if r:
            return r["indexer_class"], "direct/tipo=caixa", r["note"] or None
    if e.asset_kind == "credito_direto":
        taxa = _norm_taxa(e.taxa_texto)
        if not taxa:
            return UNCLASSIFIED, "", "crédito direto sem taxa impressa no extrato"
        for (src, fld, pattern), r in rules.items():
            if src == "statement_taxa" and re.search(pattern, taxa):
                return r["indexer_class"], f"statement_taxa/regex={pattern}", None
        return UNCLASSIFIED, "", "taxa impressa no extrato sem regra (o texto da taxa só é lido pela tabela de regras)"
    if e.asset_kind == "titulo_publico_direto":
        title = e.tesouro_title or (e.asset_key or "").rsplit(" ", 1)[0]
        r = hit("direct_tesouro", "title", title)
        if r:
            return r["indexer_class"], f"direct_tesouro/title={title}", None
        return UNCLASSIFIED, "", f"sem regra para o título direto '{title}'"
    if e.depth == 0 and e.asset_kind in ("acao_direta", "cota_listada"):
        tipo = "ação" if e.asset_kind == "acao_direta" else "FII"
        r = hit("direct", "tipo", tipo)
        if r:
            return r["indexer_class"], f"direct/tipo={tipo}", None
    if e.opaque_fund:
        return UNCLASSIFIED, "", "fundo investido sem carteira disponível na CDA"
    if e.block == "1":
        r = hit("block1", "tp_aplic", e.tp_aplic)
        if r:
            return r["indexer_class"], f"block1/tp_aplic={e.tp_aplic}", r["note"] or None
        r = hit("block1", "tp_titpub", e.tp_titpub)
        if r:
            return r["indexer_class"], f"block1/tp_titpub={e.tp_titpub}", None
        return UNCLASSIFIED, "", f"sem regra para tp_titpub={e.tp_titpub!r} (bloco 1)"
    if e.block == "6":
        code = e.indexer_code if e.indexer_code not in (None, "") else NULL_TOKEN
        r = hit("block6", "cd_indexador_posfx", code)
        if r:
            return r["indexer_class"], f"block6/cd_indexador_posfx={code}", r["note"] or None
        return UNCLASSIFIED, "", f"sem regra para cd_indexador_posfx={code!r} (bloco 6)"
    if e.block == "4":
        r = hit("block4", "tp_aplic", e.tp_aplic)
        if r:
            return r["indexer_class"], f"block4/tp_aplic={e.tp_aplic}", r["note"] or None
        return UNCLASSIFIED, "", f"sem regra para tp_aplic={e.tp_aplic!r} (bloco 4)"
    return UNCLASSIFIED, "", f"sem regra para o bloco {e.block!r}"


def compute_indexer(
    lines: list[LineId],
    exposures: dict[int, list[Exposure]],
    unexplained: dict[int, Decimal],
) -> dict[str, Any]:
    rules = load_rules()
    total = sum((li.position.valor for li in lines), Decimal("0"))
    by_class: dict[str, Decimal] = defaultdict(Decimal)
    n_items: dict[str, int] = defaultdict(int)
    unclassified_reasons: dict[str, Decimal] = defaultdict(Decimal)
    by_position: dict[int, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    items: list[dict[str, Any]] = []
    line_value = {li.line_no: li.position.valor for li in lines}

    for li in lines:
        exps = exposures.get(li.line_no, [])
        if not exps:
            reason = (
                li.reason
                if li.status != "identified"
                else "sem exposição aberta (look-through indisponível ou fundo sem carteira na CDA)"
            )
            v = li.position.valor
            by_class[UNCLASSIFIED] += v
            n_items[UNCLASSIFIED] += 1
            by_position[li.line_no][UNCLASSIFIED] += v
            unclassified_reasons[f"linha {li.line_no}: {reason}"] += v
            continue
        for e in exps:
            cls, rule, why = classify(e, rules)
            if cls == UNCLASSIFIED:
                unclassified_reasons[why or f"regra {rule} classifica como sem classificação"] += e.value_brl
            by_class[cls] += e.value_brl
            n_items[cls] += 1
            by_position[li.line_no][cls] += e.value_brl
            items.append(
                {
                    "line_no": li.line_no,
                    "via": e.via,
                    "asset_key": e.asset_key,
                    "indexer_class": cls,
                    "rule": rule or None,
                    "reason_unclassified": why,
                    "exposure_brl": brl(e.value_brl),
                    "sources": e.sources,
                }
            )
        resid = unexplained.get(li.line_no)
        if resid is not None and resid != 0:
            by_class[UNCLASSIFIED] += resid
            n_items[UNCLASSIFIED] += 1
            by_position[li.line_no][UNCLASSIFIED] += resid
            unclassified_reasons["parte do fundo que a CDA ingerida não explica (caixa, derivativos, blocos 3, 5, 7, 8)"] += resid

    by_class.setdefault(UNCLASSIFIED, Decimal("0"))
    ordered = sorted(by_class.items(), key=lambda kv: (kv[0] == UNCLASSIFIED, -kv[1]))
    classes = [
        {
            "indexer_class": k,
            "value_brl": brl(v),
            "pct_of_portfolio": pct(v, total),
            "n_items": n_items.get(k, 0),
        }
        for k, v in ordered
    ]
    check = sum(by_class.values(), Decimal("0")) - total
    return {
        "status": "complete",
        "reason": None,
        "errors": [],
        "rules_version": INDEXER_RULES_VERSION,
        "rules_sha256": rules_sha256(),
        "rules_file": "src/portfolio/rules/indexer_rules.csv",
        "never_inferred_from_name": True,
        "portfolio_value_brl": brl(total),
        "classes": classes,
        "sum_check_brl": brl(check),
        "unclassified_breakdown": [
            {"reason": k, "value_brl": brl(v), "pct_of_portfolio": pct(v, total)}
            for k, v in sorted(unclassified_reasons.items(), key=lambda kv: -kv[1])
        ],
        "by_position": [
            {
                "line_no": ln,
                "classes": [
                    {"indexer_class": k, "value_brl": brl(v), "weight_in_line": ratio(v / line_value[ln])}
                    for k, v in sorted(d.items(), key=lambda kv: (kv[0] == UNCLASSIFIED, -kv[1]))
                ],
            }
            for ln, d in sorted(by_position.items())
        ],
        "items": items,
    }
