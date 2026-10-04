"""Consolidation of several statements into one portfolio for the diagnosis.

``consolidate(statements)`` takes already read, masked and reconciled
``Statement`` objects (one per account) and returns a ``ConsolidatedPortfolio``:

* accounts get ordinal tokens ``C1..Cn`` (by order) and holders ``T1..Tn`` (by a salted
  in-process fingerprint, since the masked token ``[TITULAR]`` is the same for everyone);
  the real account number and name are never kept;
* the same asset in two accounts is aggregated for diagnosis when it has the same ``codigo``
  (and maturity) or, with no code, the same normalised name and type, AND the same position
  date; the per-account lines stay under ``Position.contas``;
* the total is the sum of the statements' own totals, each already reconciled;
* statements with different position dates are NOT mixed silently: the dates and the gap are a
  note, and no asset is aggregated across dates;
* more than one holder is flagged ``multi-titular``; the same account twice at the same date is
  refused (it would double-count).
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Sequence

from src.portfolio.mask import MaskedHolder
from src.portfolio.statement import (
    AccountSummary,
    ContaLine,
    Position,
    Statement,
    StatementError,
)


class ConsolidationError(StatementError):
    """The statements cannot be consolidated without double counting or mixing what must not be mixed."""


@dataclass(frozen=True)
class ConsolidatedPortfolio:
    statement: Statement  # the aggregated portfolio, what the engine diagnoses
    accounts: tuple[AccountSummary, ...]  # the per-account view
    notes: tuple[str, ...]
    n_lines_before: int  # lines across accounts before aggregation
    n_assets_in_several_accounts: int


def _norm(name: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c))
    return re.sub(r"[\s*]+", " ", s).strip().upper()


def _agg_key(p: Position) -> tuple | None:
    if p.tipo == "caixa":
        return ("caixa", p.data_posicao)
    if p.codigo:
        if p.tipo == "tesouro" and not re.search(r"\d", p.codigo):
            # a title with no maturity could be two different bonds: never aggregated
            return None
        return ("c", p.codigo.upper(), p.vencimento, p.data_posicao)
    if p.tipo == "tesouro":
        return None
    return ("n", _norm(p.linha_extrato), p.tipo, p.data_posicao)


def consolidate(statements: Sequence[Statement]) -> ConsolidatedPortfolio:
    if not statements:
        raise ValueError("consolidate() needs at least one statement")
    notes: list[str] = []

    # holders and accounts
    titular_ord: dict[str, str] = {}
    titular_refs: list[str] = []
    for i, st in enumerate(statements):
        fp = st.holder.titular_fp
        if fp is None:
            ref = f"T{len(titular_ord) + 1}"
            titular_ord[f"_unknown{i}"] = ref
            notes.append(f"Titular da conta C{i + 1} não identificado no arquivo: contado como titular distinto ({ref}).")
        else:
            ref = titular_ord.setdefault(fp, f"T{len(titular_ord) + 1}")
        titular_refs.append(ref)
    n_titulares = len(set(titular_refs))
    if n_titulares > 1:
        notes.append(f"multi-titular: {n_titulares} titulares ({', '.join(sorted(set(titular_refs)))}); as contas são somadas, não são uma pessoa só.")

    seen_conta: dict[str, int] = {}
    for i, st in enumerate(statements):
        fp = st.holder.conta_fp
        if fp is None:
            continue
        if fp in seen_conta:
            j = seen_conta[fp]
            if statements[j].position_date == st.position_date:
                raise ConsolidationError(
                    f"as contas C{j + 1} e C{i + 1} são a mesma conta na mesma data ({st.position_date.isoformat()}): "
                    "somar as duas duplicaria o patrimônio; consolidação interrompida"
                )
            notes.append(
                f"As contas C{j + 1} e C{i + 1} são a mesma conta em datas diferentes "
                f"({statements[j].position_date.isoformat()} e {st.position_date.isoformat()}): ambas foram somadas."
            )
        else:
            seen_conta[fp] = i

    # dates
    dates = sorted({d for st in statements for d in st.position_dates})
    if len(dates) > 1:
        gap = (dates[-1] - dates[0]).days
        notes.append(
            f"Datas de posição diferentes entre as contas: {', '.join(d.isoformat() for d in dates)} "
            f"(intervalo de {gap} dias). A data de referência é a mais recente; nenhum ativo foi agregado entre datas."
        )

    # per-account positions with the ordinal token
    accounts: list[AccountSummary] = []
    per_account_positions: list[list[Position]] = []
    for i, st in enumerate(statements):
        ref = f"C{i + 1}"
        pos = [replace(p, conta_ref=ref) for p in st.positions]
        per_account_positions.append(pos)
        accounts.append(
            AccountSummary(
                conta_ref=ref,
                titular_ref=titular_refs[i],
                n_lines=len(pos),
                stated_total=st.stated_total,
                sum_of_lines=st.sum_of_lines,
                position_date=st.position_date,
                source_format=st.source_format,
                positions=tuple(pos),
            )
        )
        for n in st.notes:
            notes.append(f"{ref}: {n}")

    # aggregation
    groups: dict[tuple, list[tuple[int, Position]]] = {}
    order: list[tuple | int] = []
    solo = 0
    for i, pos in enumerate(per_account_positions):
        for p in pos:
            k = _agg_key(p)
            if k is None:
                k = ("solo", solo)
                solo += 1
            if k not in groups:
                groups[k] = []
                order.append(k)
            groups[k].append((i, p))

    aggregated: list[Position] = []
    several = 0
    for k in order:
        members = groups[k]
        accounts_in = {i for i, _ in members}
        if len(accounts_in) > 1:
            several += 1
        aggregated.append(_aggregate(len(aggregated) + 1, members, titular_refs, notes))

    sum_agg = sum((p.valor for p in aggregated), Decimal("0"))
    sum_lines = sum((st.sum_of_lines for st in statements), Decimal("0"))
    if sum_agg != sum_lines:  # exact: aggregation only sums
        raise ConsolidationError(f"internal: aggregated total R$ {sum_agg} differs from the sum of the statements R$ {sum_lines}")
    stated = sum((st.stated_total for st in statements), Decimal("0"))
    tol = sum((st.tolerance for st in statements), Decimal("0"))
    formats = {st.source_format for st in statements}
    brokers = sorted({st.corretora for st in statements if st.corretora})
    if several:
        notes.append(f"{several} ativo(s) presentes em mais de uma conta foram agregados para o diagnóstico; as linhas por conta ficam em 'contas'.")
    stmt = Statement(
        holder=MaskedHolder(
            titular="[TITULAR]" if any(st.holder.titular for st in statements) else None,
            cpf=None,
            conta="[CONTA]" if any(st.holder.conta for st in statements) else None,
        ),
        corretora=", ".join(brokers) or None,
        stated_total=stated,
        sum_of_lines=sum_lines,
        tolerance=tol,
        positions=tuple(aggregated),
        position_date=dates[-1],
        position_dates=tuple(dates),
        source_format=formats.pop() if len(formats) == 1 else "mixed",
        notes=tuple(dict.fromkeys(notes)),
        accounts=tuple(accounts),
    )
    return ConsolidatedPortfolio(
        statement=stmt,
        accounts=tuple(accounts),
        notes=stmt.notes,
        n_lines_before=sum(len(p) for p in per_account_positions),
        n_assets_in_several_accounts=several,
    )


def _all_equal(values: list) -> bool:
    return all(v == values[0] for v in values)


def _aggregate(line_no: int, members: list[tuple[int, Position]], titular_refs: list[str], notes: list[str]) -> Position:
    ps = [p for _, p in members]
    first = ps[0]
    contas = tuple(
        ContaLine(
            conta_ref=p.conta_ref or f"C{i + 1}",
            titular_ref=titular_refs[i],
            source_row=p.source_row,
            linha_extrato=p.linha_extrato,
            quantidade=p.quantidade,
            preco_unitario=p.preco_unitario,
            valor=p.valor,
            data_posicao=p.data_posicao,
        )
        for i, p in members
    )
    valor = sum((p.valor for p in ps), Decimal("0"))
    qtys = [p.quantidade for p in ps]
    qtd = sum(qtys, Decimal("0")) if all(q is not None for q in qtys) else None
    if len(ps) == 1:
        preco, implicit = first.preco_unitario, first.preco_implicito
    elif first.tipo == "fundo" and qtd:
        preco, implicit = (valor / qtd).quantize(Decimal("0.00000001")), True
    else:
        preco, implicit = None, False
    taxa = first.taxa_texto if _all_equal([p.taxa_texto for p in ps]) else None
    if len(ps) > 1 and not _all_equal([p.taxa_texto for p in ps]):
        notes.append(f"Taxas impressas diferentes para o mesmo ativo em contas diferentes (linha consolidada {line_no}): a taxa ficou sem valor.")
    return Position(
        line_no=line_no,
        source_row=first.source_row,
        linha_extrato=first.linha_extrato,
        tipo=first.tipo,
        codigo=next((p.codigo for p in ps if p.codigo), None),
        quantidade=qtd,
        preco_unitario=preco,
        valor=valor,
        data_posicao=first.data_posicao,
        vencimento=first.vencimento if _all_equal([p.vencimento for p in ps]) else None,
        taxa_texto=taxa,
        estrategia_corretora=first.estrategia_corretora if _all_equal([p.estrategia_corretora for p in ps]) else None,
        classe_corretora=first.classe_corretora if _all_equal([p.classe_corretora for p in ps]) else None,
        conta_ref=first.conta_ref if len(ps) == 1 else None,
        preco_implicito=implicit,
        contas=contas,
        emissor=first.emissor if _all_equal([p.emissor for p in ps]) else None,
    )


def describe_consolidated(c: ConsolidatedPortfolio) -> list[str]:
    """Aggregate, masked lines only (no name, account, CPF or asset name)."""
    st = c.statement
    n_t = len({a.titular_ref for a in c.accounts})
    out = [
        f"contas: {len(c.accounts)}; titulares: {n_t}" + (" (multi-titular)" if n_t > 1 else ""),
        f"datas de posição: {', '.join(d.isoformat() for d in st.position_dates)}",
        f"linhas antes da agregação: {c.n_lines_before}; depois: {len(st.positions)}; ativos em mais de uma conta: {c.n_assets_in_several_accounts}",
        f"total consolidado R$ {st.sum_of_lines:,.2f} (soma dos totais declarados R$ {st.stated_total:,.2f})",
    ]
    for a in c.accounts:
        out.append(f"  {a.conta_ref} ({a.titular_ref}): {a.n_lines} linhas, R$ {a.sum_of_lines:,.2f}, {a.position_date.isoformat()}")
    out += [f"nota: {n}" for n in c.notes if not re.search(r"\bC\d+: ", n)]
    return out
