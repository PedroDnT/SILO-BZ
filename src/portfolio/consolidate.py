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
    codigo_cnpj,
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


def _identity_key(p: Position) -> tuple | None:
    """The exact identity of a line from what the statement prints: the CNPJ (punctuation ignored) or the code with
    its maturity, at one position date. None when the line has no such key (it is never merged by name here)."""
    if p.tipo == "caixa":
        return ("caixa", p.data_posicao)
    cnpj = codigo_cnpj(p.codigo)
    if cnpj:
        return ("cnpj", cnpj, p.data_posicao)
    if p.codigo:
        if p.tipo == "tesouro" and not re.search(r"\d", p.codigo):
            return None  # a title with no maturity could be two different bonds
        return ("c", re.sub(r"\s+", " ", p.codigo.strip().upper()), p.vencimento, p.data_posicao)
    if p.tipo in FUND_TIPOS_BY_NAME:
        # a fund with no code: the same printed name, type, date and printed quota is the same fund (a fund has no
        # maturity or rate that could tell two lines apart); a different or missing quota keeps the lines apart
        if p.preco_unitario is None or p.preco_implicito:
            return None
        return ("n", _norm(p.linha_extrato), p.tipo, p.data_posicao, p.preco_unitario)
    return None


FUND_TIPOS_BY_NAME = ("fundo", "FIDC", "FII", "ETF")


def merge_same_identity(stmt: Statement) -> tuple[Statement, int]:
    """Engine 1.7: the lines of ONE statement with the same identity (same CNPJ, or same code and maturity, same
    date) become one position; the source lines stay under ``Position.contas`` (``conta_ref`` None: no account is
    invented). A consolidated statement that lists one asset per account is the case. A fund line with no code is
    merged only with the same printed name, type, date and printed quota; any other line with no CNPJ or code is
    never merged (two codeless CDBs of one bank may differ in maturity and rate). Returns the statement and the
    number of positions that merged two or more lines; the statement is returned unchanged when there are none."""
    groups: dict[tuple, list[Position]] = {}
    order: list[tuple] = []
    for i, p in enumerate(stmt.positions):
        k = _identity_key(p) or ("solo", i)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(p)
    merged = sum(1 for k in order if len(groups[k]) > 1)
    if not merged:
        return stmt, 0
    notes: list[str] = list(stmt.notes)
    positions: list[Position] = []
    for k in order:
        ps = groups[k]
        if len(ps) == 1:
            positions.append(replace(ps[0], line_no=len(positions) + 1))
            continue
        members = [(None, p) for p in ps]
        positions.append(_aggregate(len(positions) + 1, members, None, notes))
    if sum((p.valor for p in positions), Decimal("0")) != stmt.sum_of_lines:  # exact: merging only sums
        raise ConsolidationError("internal: merged total differs from the sum of the statement's lines")
    notes.append(
        f"{merged} ativo(s) presentes em mais de uma linha do extrato (mesmo CNPJ; mesmo código e vencimento; ou, num "
        "fundo sem código, mesmo nome, tipo e cota) "
        "foram agregados em uma posição; as linhas de origem ficam em 'contas'."
    )
    return replace(stmt, positions=tuple(positions), notes=tuple(dict.fromkeys(notes))), merged


def _agg_key(p: Position) -> tuple | None:
    if p.tipo == "caixa":
        return ("caixa", p.data_posicao)
    if codigo_cnpj(p.codigo):
        return _identity_key(p)
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


def _aggregate(line_no: int, members: list[tuple[int | None, Position]], titular_refs: list[str] | None,
               notes: list[str]) -> Position:
    """``members`` are (account index, position); index None (one statement, no accounts) keeps conta_ref as read."""
    ps = [p for _, p in members]
    first = ps[0]
    contas = tuple(
        ContaLine(
            conta_ref=p.conta_ref if i is None else (p.conta_ref or f"C{i + 1}"),
            titular_ref=None if i is None or titular_refs is None else titular_refs[i],
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
    elif first.preco_unitario is not None and not first.preco_implicito and _all_equal([(p.preco_unitario, p.preco_implicito) for p in ps]):
        preco, implicit = first.preco_unitario, False  # the same printed price on every line: kept as printed
    elif first.tipo in ("fundo", "FIDC") and qtd:
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
