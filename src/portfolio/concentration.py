"""Block 15 (engine 1.7): concentration and maturity, from the statement's own facts.

Every number here is a sum of statement values (``valor``, ``vencimento``), never a SILO figure and never
an estimate:

* ``issuer``: direct credit (CRA, CRI, debênture, CDB, CDCA, LCI, LCA) grouped by the issuer AS PRINTED: the
  line's name with the instrument type and the registry code taken out, compared as accent-free upper text.
  It is not an economic group: SILO never infers a group by name, and two names of one issuer stay apart.
* ``maturity_ladder``: the lines with a printed maturity (``vencimento``, or the Tesouro maturity in
  ``codigo``) by time to maturity from the position date; the rest is ``sem vencimento``.
* ``fgc``: the FGC-covered types the statement can name (CDB, LCI, LCA) summed per issuer as printed, flagged
  above R$ 250 mil. LF, CRA, CRI, debêntures and fund quotas are not covered. A check to make by hand: the
  limit is per CPF and institution (conglomerate), and a consolidated statement may hold more than one holder.
* ``manager`` (concentration by fund manager) and ``fund_liquidity`` (lâmina redemption terms): not evaluated.
  No ``api`` function or view serves the manager's CNPJ or ``qt_dia_pagto_resgate`` (checked 2026-10-04), and
  this engine reads SILO only through the public API.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from decimal import Decimal
from typing import Any

from src.portfolio.common import STATUS_COMPLETE, STATUS_NOT_APPLICABLE, STATUS_UNKNOWN, Section, brl, pct
from src.portfolio.identify import LineId, parse_tesouro

DIRECT_CREDIT_TIPOS = ("CRA", "CRI", "debênture", "CDB", "LCI", "LCA")
FGC_TIPOS = ("CDB", "LCI", "LCA")
FGC_LIMIT_BRL = Decimal("250000")
ISSUER_LABEL = "emissor como impresso no extrato; grupo econômico não avaliado"
ISSUER_BASIS = (
    "nome da linha sem o tipo do instrumento e sem o código do registro, comparado como texto sem acento e em "
    "maiúsculas; dois nomes diferentes do mesmo emissor ficam separados"
)
FGC_LABEL = "a conferir: limite por CPF e instituição; o extrato consolidado pode ter mais de um titular"
FGC_RULE = (
    "Regulamento do FGC (Anexo II da Resolução CMN nº 4.222/2013), art. 2º: a garantia ordinária cobre, entre outros, "
    "CDB, RDB, LC, LCI, LCA e LCD, até R$ 250 mil por CPF ou CNPJ e por instituição ou conglomerado financeiro; "
    "letra financeira (LF), CRA, CRI, debêntures e cotas de fundos não são cobertos"
)
FGC_SCOPE_NOTE = (
    "Somados só CDB, LCI e LCA, os tipos do extrato que o FGC cobre; uma LC ou LF lançada como 'outro' não é "
    "reconhecida pelo nome."
)
MANAGER_REASON = (
    "Concentração por gestor não avaliada: nenhuma função ou visão pública do SILO (schema api) serve o CNPJ do "
    "gestor arquivado na CVM."
)
LIQUIDITY_REASON = (
    "Liquidez dos fundos não avaliada: nenhuma função ou visão pública do SILO (schema api) serve o prazo de "
    "pagamento do resgate da lâmina (qt_dia_pagto_resgate)."
)
LADDER = (
    ("vencido ou vence na data", 0),
    ("até 1 ano", 365),
    ("de 1 a 2 anos", 730),
    ("de 2 a 5 anos", 1826),
    ("de 5 a 10 anos", 3652),
    ("acima de 10 anos", None),
)
NO_MATURITY = "sem vencimento no extrato"

_TYPE_WORDS = r"(CRA|CRI|CDB|CDCA|LCI|LCA|LC|LF|DEB|DEBENTURE|DEBENTURES|RDB)"
_REGISTRY_SUFFIX = re.compile(rf"\s*-?\s*\b{_TYPE_WORDS}-\S+\s*$")
_LEADING_TYPE = re.compile(rf"^(\b{_TYPE_WORDS}\b[\s\-:]*)+")


def _norm(s: str | None) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().upper()


def is_direct_credit(li: LineId) -> bool:
    p = li.position
    if p.tipo in DIRECT_CREDIT_TIPOS:
        return True
    # a CDCA is typed 'outro' by both readers; its registry code (CDCA-...) is printed in the name
    return p.tipo == "outro" and bool(re.search(r"\bCDCA\b", _norm(p.linha_extrato)))


def issuer_as_printed(li: LineId) -> str | None:
    """The line's name without the instrument type and the registry code; None when nothing is left."""
    p = li.position
    name = _norm(p.linha_extrato)
    code = _norm(p.codigo)
    if code:
        name = name.replace(code, " ")
    name = _REGISTRY_SUFFIX.sub("", name)
    name = _LEADING_TYPE.sub("", name.strip())
    name = re.sub(r"\s+", " ", name).strip(" -:/")
    return name or None


def _maturity(li: LineId) -> dt.date | None:
    p = li.position
    if p.vencimento:
        return p.vencimento
    if p.tipo == "tesouro":
        parsed = parse_tesouro(p.codigo)
        if parsed and len(parsed[1]) == 10:
            return dt.date.fromisoformat(parsed[1])
    return None


def _bucket(days: int) -> str:
    for label, limit in LADDER:
        if limit is None or days <= limit:
            return label
    return LADDER[-1][0]


def compute_concentration(lines: list[LineId], position_date: dt.date) -> dict[str, Any]:
    sec = Section()
    total = sum((li.position.valor for li in lines), Decimal("0"))
    issuer = _issuer(lines, total)
    ladder = _ladder(lines, total, position_date)
    fgc = _fgc(lines)
    manager = {"status": STATUS_UNKNOWN, "reason_code": "gestor_sem_api", "reason": MANAGER_REASON}
    liquidity = {"status": STATUS_UNKNOWN, "reason_code": "liquidez_sem_api", "reason": LIQUIDITY_REASON}
    sec.degrade(MANAGER_REASON, code="gestor_sem_api")
    sec.degrade(LIQUIDITY_REASON, code="liquidez_sem_api")
    return {
        **sec.head(),
        "source": "statement",
        "issuer": issuer,
        "maturity_ladder": ladder,
        "fgc": fgc,
        "manager": manager,
        "fund_liquidity": liquidity,
    }


def _issuer(lines: list[LineId], total: Decimal) -> dict[str, Any]:
    credit = [li for li in lines if is_direct_credit(li)]
    base = {"label": ISSUER_LABEL, "basis": ISSUER_BASIS, "tipos": list(DIRECT_CREDIT_TIPOS) + ["CDCA"]}
    if not credit:
        return {**base, "status": STATUS_NOT_APPLICABLE, "reason_code": "sem_credito_direto", "groups": [],
                "direct_credit_value_brl": 0.0, "direct_credit_portfolio_pct": pct(Decimal("0"), total) if total else None,
                "not_printed_line_nos": []}
    credit_total = sum((li.position.valor for li in credit), Decimal("0"))
    groups: dict[str, list[LineId]] = {}
    not_printed: list[int] = []
    for li in credit:
        name = issuer_as_printed(li)
        if name is None:
            not_printed.append(li.line_no)
            continue
        groups.setdefault(name, []).append(li)
    out = []
    for name, lis in groups.items():
        v = sum((li.position.valor for li in lis), Decimal("0"))
        out.append({
            "issuer_as_printed": name,
            "line_nos": [li.line_no for li in lis],
            "n_lines": len(lis),
            "tipos": sorted({li.position.tipo for li in lis}),
            "value_brl": brl(v),
            "portfolio_pct": pct(v, total),
            "direct_credit_pct": pct(v, credit_total),
        })
    out.sort(key=lambda g: -(g["value_brl"] or 0))
    return {**base, "status": STATUS_COMPLETE, "reason_code": None, "groups": out,
            "direct_credit_value_brl": brl(credit_total), "direct_credit_portfolio_pct": pct(credit_total, total),
            "not_printed_line_nos": not_printed}


def _ladder(lines: list[LineId], total: Decimal, position_date: dt.date) -> dict[str, Any]:
    acc: dict[str, list[LineId]] = {label: [] for label, _ in LADDER}
    by_year: dict[int, list[LineId]] = {}
    none: list[LineId] = []
    for li in lines:
        m = _maturity(li)
        if m is None:
            none.append(li)
        else:
            acc[_bucket((m - position_date).days)].append(li)
            by_year.setdefault(m.year, []).append(li)

    def row(label: str, lis: list[LineId]) -> dict[str, Any]:
        v = sum((li.position.valor for li in lis), Decimal("0"))
        return {"bucket": label, "value_brl": brl(v), "portfolio_pct": pct(v, total), "n_lines": len(lis),
                "line_nos": [li.line_no for li in lis]}

    buckets = [row(label, acc[label]) for label, _ in LADDER]
    n_with = sum(len(v) for v in acc.values())
    check = sum((li.position.valor for lis in acc.values() for li in lis), Decimal("0")) + sum(
        (li.position.valor for li in none), Decimal("0")) - total
    return {
        "status": STATUS_COMPLETE if n_with else STATUS_NOT_APPLICABLE,
        "reason_code": None if n_with else "sem_vencimento",
        "basis": "vencimento impresso no extrato (ou o do título do Tesouro no código), contado da data da posição",
        "position_date": position_date.isoformat(),
        "buckets": buckets,
        "no_maturity": row(NO_MATURITY, none),
        # engine 1.8: the same lines by calendar year of maturity; the year is a string so it never prints as a number
        "by_year": [{"year": str(y), **{k: v for k, v in row(str(y), by_year[y]).items() if k != "bucket"}}
                    for y in sorted(by_year)],
        "sum_check_brl": brl(check),
    }


def _fgc(lines: list[LineId]) -> dict[str, Any]:
    eligible = [li for li in lines if li.position.tipo in FGC_TIPOS]
    base = {"label": FGC_LABEL, "rule": FGC_RULE, "scope_note": FGC_SCOPE_NOTE, "limit_brl": brl(FGC_LIMIT_BRL),
            "eligible_tipos": list(FGC_TIPOS)}
    if not eligible:
        return {**base, "status": STATUS_NOT_APPLICABLE, "reason_code": "sem_credito_direto", "issuers": [],
                "n_above_limit": 0, "not_printed_line_nos": []}
    groups: dict[str, list[LineId]] = {}
    not_printed: list[int] = []
    for li in eligible:
        name = issuer_as_printed(li)
        if name is None:
            not_printed.append(li.line_no)
            continue
        groups.setdefault(name, []).append(li)
    issuers = []
    for name, lis in groups.items():
        v = sum((li.position.valor for li in lis), Decimal("0"))
        above = v > FGC_LIMIT_BRL
        issuers.append({
            "issuer_as_printed": name,
            "line_nos": [li.line_no for li in lis],
            "tipos": sorted({li.position.tipo for li in lis}),
            "eligible_value_brl": brl(v),
            "above_limit": above,
            "excess_brl": brl(v - FGC_LIMIT_BRL) if above else None,
        })
    issuers.sort(key=lambda g: -(g["eligible_value_brl"] or 0))
    return {**base, "status": STATUS_COMPLETE, "reason_code": None, "issuers": issuers,
            "n_above_limit": sum(1 for g in issuers if g["above_limit"]), "not_printed_line_nos": not_printed}
