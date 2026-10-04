"""Block 16 (engine 1.8): the portfolio by asset class, from the statement's own type of each line.

Sums of statement values only (``source = "statement"``). The class of a line is the type the statement prints
(``tipo``: fundo, FIDC, FII, ETF, ação, tesouro, CDB, ...), grouped into report classes; a ticker the statement types
``outro`` takes the class SILO's ``lookup`` gave it (share or listed fund quota), never one inferred from the name.
What is left (an ``outro`` line with no class) is ``sem classificação``, always the last entry, even at zero, as in
the indexer and sector blocks.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from src.portfolio.common import STATUS_COMPLETE, UNCLASSIFIED, Section, brl, pct
from src.portfolio.concentration import is_direct_credit
from src.portfolio.identify import LineId

BASIS = (
    "tipo impresso no extrato para cada linha (para um ticker do tipo 'outro', a classe que o lookup do SILO informa); "
    "somas de valores do extrato"
)
CLASS_BY_TIPO = {
    "tesouro": "título público",
    "ação": "ação",
    "fundo": "fundo",
    "FIDC": "FIDC",
    "FII": "FII",
    "ETF": "ETF",
    "caixa": "conta corrente",
}
CREDIT_CLASS = "crédito privado direto"
LISTED_QUOTA_CLASS = "cota de fundo listada"


def class_of(li: LineId) -> str:
    p = li.position
    if is_direct_credit(li):
        return CREDIT_CLASS
    if p.tipo in CLASS_BY_TIPO:
        return CLASS_BY_TIPO[p.tipo]
    if li.asset_class == "equity":
        return "ação"
    if li.asset_class == "fund_quota":
        return LISTED_QUOTA_CLASS
    return UNCLASSIFIED


def compute_allocation(lines: list[LineId]) -> dict[str, Any]:
    sec = Section()
    total = sum((li.position.valor for li in lines), Decimal("0"))
    acc: dict[str, list[LineId]] = {}
    for li in lines:
        acc.setdefault(class_of(li), []).append(li)
    unclassified = acc.pop(UNCLASSIFIED, [])

    def row(label: str, lis: list[LineId]) -> dict[str, Any]:
        v = sum((li.position.valor for li in lis), Decimal("0"))
        return {"asset_class": label, "value_brl": brl(v), "portfolio_pct": pct(v, total) if total else None,
                "n_lines": len(lis), "line_nos": [li.line_no for li in lis]}

    classes = sorted((row(k, v) for k, v in acc.items()), key=lambda r: (-(r["value_brl"] or 0), r["asset_class"]))
    classes.append(row(UNCLASSIFIED, unclassified))
    check = sum((Decimal(str(r["value_brl"])) for r in classes), Decimal("0")) - total
    return {
        **sec.head(),
        "status": STATUS_COMPLETE,
        "source": "statement",
        "basis": BASIS,
        "portfolio_value_brl": brl(total),
        "classes": classes,
        "sum_check_brl": brl(check),
    }
