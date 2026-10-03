"""Block 2: look-through and shared exposure.

Tool ``portfolio_lookthrough(p_cnpjs, p_month, p_max_depth)``, called once per
root fund so that one refusal makes one line unknown, not the section.

Each returned row is a node of the holding tree under a root: ``depth`` 1 is
what the root holds, ``path`` how we got there, ``weight_in_root`` the node's
share of the ROOT's value (assumed a fraction, 0..1; recorded as an
assumption). Exposure in R$ = position value x ``weight_in_root``.

* A leaf is a node nothing else is expanded under: any non-fund row, and a fund
  quota row (block 2) with no children (its own holdings are not in the CDA,
  or the depth cap stopped there; reported as ``fundo_sem_look_through``).
* Intermediate fund nodes are kept in ``fund_nodes`` (the master of a FIC,
  say) so two lines that hold the same fund can be seen.
* Cycle rows (``is_cycle``) are not followed and not counted.
* The part of the root's value that no ingested CDA block explains is shown
  as ``unexplained_weight`` (blocks 3, 5, 7 and 8 are not ingested; cash and
  liabilities live there). Nothing fills it.

Shared exposure, across all lines (direct positions included): the same asset
(asset key or ISIN), the same issuer by 8-digit CNPJ root, the same B3 issuer
code (ISIN characters 3 to 6), and the same fund held by two lines. Economic
group is NOT assessed.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from src.portfolio.client import SiloClient
from src.portfolio.common import (
    STATUS_NOT_APPLICABLE,
    Section,
    as_date,
    b3_issuer_code,
    brl,
    call_tool,
    cnpj_root,
    dec,
    ratio,
    source,
    statement_source,
)
from src.portfolio.identify import LineId

LOOKTHROUGH_TIPOS = ("fundo", "FIDC", "FII", "ETF")
ECONOMIC_GROUP_NOTE = (
    "Grupo econômico NÃO avaliado: o SILO compara emissor por raiz de CNPJ (8 dígitos) e por código de "
    "emissor da B3, não por controle societário."
)


@dataclass
class Exposure:
    """One economic exposure of one statement line (direct or through funds)."""

    line_no: int
    via: str  # "direto" or the path through funds
    depth: int
    block: str | None
    asset_kind: str | None
    asset_key: str | None
    asset_name: str | None
    isin: str | None
    issuer_cnpj: str | None
    issuer_code: str | None
    tp_aplic: str | None
    tp_ativo: str | None
    tp_titpub: str | None
    indexer_code: str | None
    maturity: str | None
    weight: Decimal  # share of the line's value (1 for a direct position)
    value_brl: Decimal  # line value x weight
    period: str | None
    opaque_fund: bool = False  # a fund quota with no holdings expanded
    sources: list[dict] = field(default_factory=list)
    ticker: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "line_no": self.line_no,
            "via": self.via,
            "depth": self.depth,
            "block": self.block,
            "asset_kind": "fundo_sem_look_through" if self.opaque_fund else self.asset_kind,
            "asset_key": self.asset_key,
            "asset_name": self.asset_name,
            "isin": self.isin,
            "issuer_cnpj": self.issuer_cnpj,
            "issuer_code": self.issuer_code,
            "tp_aplic": self.tp_aplic,
            "tp_ativo": self.tp_ativo,
            "tp_titpub": self.tp_titpub,
            "indexer_code": self.indexer_code,
            "maturity": self.maturity,
            "weight_in_line": ratio(self.weight),
            "exposure_brl": brl(self.value_brl),
            "period": self.period,
            "sources": self.sources,
        }


def block_number(value: Any) -> str | None:
    """Normalise ``block`` ('BLC_4', 4, '4', 'block 4') to the digit string."""
    if value is None:
        return None
    m = re.search(r"\d+", str(value))
    return m.group(0) if m else str(value)


def compute_lookthrough(
    lines: list[LineId], client: SiloClient, cda_month: dt.date, max_depth: int
) -> tuple[dict[str, Any], dict[int, list[Exposure]]]:
    sec = Section()
    exposures: dict[int, list[Exposure]] = {}
    out_lines: list[dict[str, Any]] = []
    fund_nodes: dict[int, list[dict[str, Any]]] = {}

    roots = [li for li in lines if li.kind == "fund" and li.cnpj and li.position.tipo in LOOKTHROUGH_TIPOS]
    refused = 0

    for li in lines:
        exposures[li.line_no] = _direct_exposures(li)

    for li in roots:
        args = {"p_cnpjs": [li.cnpj], "p_month": cda_month.isoformat(), "p_max_depth": max_depth}
        res = call_tool(client, "portfolio_lookthrough", args, sec.errors)
        if not res.ok:
            refused += 1
            out_lines.append(
                {
                    "line_no": li.line_no,
                    "cnpj": li.cnpj,
                    "status": "unknown",
                    "reason": "portfolio_lookthrough falhou para este fundo (erro literal em errors da seção).",
                    "n_rows": None,
                    "exposures": [],
                }
            )
            exposures[li.line_no] = []
            continue
        rows = [r for r in res.rows or [] if not r.get("is_cycle")]
        cycles = [r for r in res.rows or [] if r.get("is_cycle")]
        if not rows:
            out_lines.append(
                {
                    "line_no": li.line_no,
                    "cnpj": li.cnpj,
                    "status": "no_holdings",
                    "reason": (
                        f"A CDA de {cda_month.strftime('%Y-%m')} não traz carteira para este fundo "
                        "(ou o fundo não entrega CDA, como FIDC e FII)."
                    ),
                    "n_rows": 0,
                    "exposures": [],
                    "sources": [res.src(cda_month)],
                }
            )
            exposures[li.line_no] = []
            continue
        exp, nodes, weight_sum = _expand(li, rows, res)
        exposures[li.line_no] = exp
        fund_nodes[li.line_no] = nodes
        out_lines.append(
            {
                "line_no": li.line_no,
                "cnpj": li.cnpj,
                "status": "complete",
                "reason": None,
                "n_rows": len(res.rows or []),
                "n_cycle_rows_skipped": len(cycles),
                "max_depth_seen": max((int(r.get("depth") or 0) for r in rows), default=0),
                "explained_weight": ratio(weight_sum),
                "unexplained_weight": ratio(Decimal(1) - weight_sum),
                "unexplained_note": (
                    "Parte do valor do fundo que nenhum bloco da CDA ingerido explica (caixa, derivativos, "
                    "blocos 3, 5, 7 e 8 não ingeridos; negativo = passivos e derivativos somados). Não preenchida."
                ),
                "exposures": [e.as_dict() for e in exp],
                "fund_nodes": nodes,
                "sources": [res.src(cda_month)],
            }
        )

    if not roots:
        sec.status = STATUS_NOT_APPLICABLE
        sec.reason = "Nenhum fundo identificado para abrir."
    elif refused == len(roots):
        sec.fail("portfolio_lookthrough falhou para todos os fundos (erros literais em errors).")
    elif refused:
        sec.degrade(f"portfolio_lookthrough falhou para {refused} de {len(roots)} fundos; essas linhas ficaram sem look-through.")
    empty = [o for o in out_lines if o["status"] == "no_holdings"]
    if empty and sec.status == "complete":
        sec.degrade(f"{len(empty)} fundo(s) sem carteira na CDA do mês.")

    shared = shared_exposure(lines, exposures, fund_nodes)
    section = {
        **sec.head(),
        "cda_month": cda_month.isoformat(),
        "max_depth": max_depth,
        "lines": out_lines,
        "shared_exposure": shared,
    }
    return section, exposures


def _direct_exposures(li: LineId) -> list[Exposure]:
    """The line itself as an exposure, for the lines that are not opened as funds."""
    p = li.position
    src = [statement_source(p.line_no, p.data_posicao)]
    if li.kind == "ticker":
        return [
            Exposure(
                line_no=li.line_no,
                via="direto",
                depth=0,
                block=None,
                asset_kind="acao_direta" if p.tipo == "ação" else "cota_listada",
                asset_key=li.ticker,
                asset_name=li.name,
                isin=li.isin,
                issuer_cnpj=li.issuer_cnpj,
                issuer_code=b3_issuer_code(li.isin),
                tp_aplic=None,
                tp_ativo=None,
                tp_titpub=None,
                indexer_code=None,
                maturity=None,
                weight=Decimal(1),
                value_brl=p.valor,
                period=p.data_posicao.isoformat(),
                sources=src + ([li.issuer_source] if li.issuer_source else []),
                ticker=li.ticker,
            )
        ]
    if li.kind == "tesouro":
        return [
            Exposure(
                line_no=li.line_no,
                via="direto",
                depth=0,
                block=None,
                asset_kind="titulo_publico_direto",
                asset_key=f"{li.tesouro_title} {li.tesouro_maturity}",
                asset_name=li.name,
                isin=None,
                issuer_cnpj=None,
                issuer_code=None,
                tp_aplic=None,
                tp_ativo=None,
                tp_titpub=li.tesouro_tp_titpub,
                indexer_code=None,
                maturity=li.tesouro_maturity,
                weight=Decimal(1),
                value_brl=p.valor,
                period=p.data_posicao.isoformat(),
                sources=src,
            )
        ]
    return []


def _expand(li: LineId, rows: list[dict], res) -> tuple[list[Exposure], list[dict], Decimal]:
    p = li.position
    holders = {str(r.get("holder_cnpj")) for r in rows if r.get("holder_cnpj")}
    exposures: list[Exposure] = []
    nodes: list[dict[str, Any]] = []
    weight_sum = Decimal("0")
    for r in rows:
        block = block_number(r.get("block"))
        key = r.get("asset_key")
        w = dec(r.get("weight_in_root")) or Decimal("0")
        is_fund_row = block == "2"
        has_children = is_fund_row and key is not None and str(key) in holders
        src = [res.src(r.get("period"))]
        if is_fund_row:
            nodes.append(
                {
                    "fund_cnpj": key,
                    "fund_name": r.get("asset_name"),
                    "depth": r.get("depth"),
                    "path": r.get("path"),
                    "weight_in_line": ratio(w),
                    "value_brl": brl(p.valor * w),
                    "expanded": has_children,
                    "period": r.get("period"),
                    "sources": src,
                }
            )
        if has_children:
            continue
        weight_sum += w
        exposures.append(
            Exposure(
                line_no=li.line_no,
                via=_via(r.get("path")),
                depth=int(r.get("depth") or 0),
                block=block,
                asset_kind=r.get("asset_kind"),
                asset_key=str(key) if key is not None else None,
                asset_name=r.get("asset_name"),
                isin=r.get("isin"),
                issuer_cnpj=r.get("issuer_cnpj"),
                issuer_code=r.get("issuer_code") or b3_issuer_code(r.get("isin")),
                tp_aplic=r.get("tp_aplic"),
                tp_ativo=r.get("tp_ativo"),
                tp_titpub=r.get("tp_titpub"),
                indexer_code=r.get("indexer_code"),
                maturity=str(r.get("maturity"))[:10] if r.get("maturity") else None,
                weight=w,
                value_brl=p.valor * w,
                period=str(r.get("period"))[:10] if r.get("period") else None,
                opaque_fund=is_fund_row,
                sources=src,
            )
        )
    return exposures, nodes, weight_sum


def _via(path: Any) -> str:
    if isinstance(path, (list, tuple)):
        return " > ".join(str(x) for x in path)
    return str(path) if path is not None else "fundo"


# ---------------------------------------------------------------------------
# Shared exposure.
# ---------------------------------------------------------------------------


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        self.parent[self.find(a)] = self.find(b)


def _tokens(e: Exposure) -> list[str]:
    toks = []
    if e.asset_key and not e.opaque_fund:
        toks.append("k:" + e.asset_key.strip().upper())
    if e.isin:
        toks.append("i:" + e.isin.strip().upper())
    return toks


def shared_exposure(
    lines: list[LineId], exposures: dict[int, list[Exposure]], fund_nodes: dict[int, list[dict[str, Any]]]
) -> dict[str, Any]:
    names = {li.line_no: li.position.linha_extrato for li in lines}
    all_exp = [e for es in exposures.values() for e in es]
    groups: list[dict[str, Any]] = []

    # (a) same asset: asset key or ISIN, joined transitively.
    uf = _UnionFind()
    for e in all_exp:
        toks = _tokens(e)
        for t in toks:
            uf.find(t)
        for a, b in zip(toks, toks[1:]):
            uf.union(a, b)
    by_asset: dict[str, list[Exposure]] = defaultdict(list)
    for e in all_exp:
        toks = _tokens(e)
        if toks and not e.opaque_fund:
            by_asset[uf.find(toks[0])].append(e)
    for members in by_asset.values():
        g = _group("mesmo_ativo", members, names, label=_label(members))
        if g:
            groups.append(g)

    # (b) same issuer, 8-digit CNPJ root.
    by_root: dict[str, list[Exposure]] = defaultdict(list)
    for e in all_exp:
        root = cnpj_root(e.issuer_cnpj)
        if root and not e.opaque_fund:
            by_root[root].append(e)
    for root, members in sorted(by_root.items()):
        g = _group("mesmo_emissor_raiz_cnpj", members, names, label=f"raiz CNPJ {root}")
        if g:
            g["issuer_cnpj_root"] = root
            groups.append(g)

    # (c) same B3 issuer code (ISIN characters 3 to 6).
    by_code: dict[str, list[Exposure]] = defaultdict(list)
    for e in all_exp:
        if e.issuer_code and not e.opaque_fund and (e.asset_kind != "titulo_publico_direto"):
            by_code[e.issuer_code.upper()].append(e)
    for code, members in sorted(by_code.items()):
        g = _group("mesmo_codigo_emissor_b3", members, names, label=f"código de emissor B3 {code}")
        if g:
            g["issuer_code"] = code
            groups.append(g)

    # (d) the same fund held by two lines (the overlap of two feeder funds).
    by_fund: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    for ln, nodes in fund_nodes.items():
        for n in nodes:
            if n.get("fund_cnpj"):
                by_fund[str(n["fund_cnpj"])].append((ln, n))
    for cnpj, members in sorted(by_fund.items()):
        line_nos = sorted({ln for ln, _ in members})
        if len(line_nos) < 2:
            continue
        per_line: dict[int, Decimal] = defaultdict(Decimal)
        for ln, n in members:
            per_line[ln] += dec(n.get("value_brl")) or Decimal("0")
        groups.append(
            {
                "kind": "mesmo_fundo_investido",
                "label": f"fundo {cnpj} ({members[0][1].get('fund_name')})",
                "fund_cnpj": cnpj,
                "line_nos": line_nos,
                "lines": [
                    {"line_no": ln, "linha_extrato": names[ln], "exposure_brl": brl(v)}
                    for ln, v in sorted(per_line.items())
                ],
                "total_exposure_brl": brl(sum(per_line.values(), Decimal("0"))),
                "sources": [s for _, n in members for s in n.get("sources", [])][:4],
            }
        )

    return {
        "economic_group_assessed": False,
        "note": ECONOMIC_GROUP_NOTE,
        "kinds_note": (
            "Os totais de tipos diferentes descrevem as mesmas posições por ângulos diferentes: não somar "
            "entre tipos."
        ),
        "groups": groups,
    }


def _label(members: list[Exposure]) -> str:
    e = members[0]
    return f"{e.asset_key}" + (f" ({e.isin})" if e.isin else "")


def _group(kind: str, members: list[Exposure], names: dict[int, str], label: str) -> dict[str, Any] | None:
    line_nos = sorted({e.line_no for e in members})
    if len(line_nos) < 2:
        return None
    per_line: dict[int, Decimal] = defaultdict(Decimal)
    for e in members:
        per_line[e.line_no] += e.value_brl
    return {
        "kind": kind,
        "label": label,
        "line_nos": line_nos,
        "lines": [
            {
                "line_no": ln,
                "linha_extrato": names[ln],
                "exposure_brl": brl(v),
                "direct": any(e.line_no == ln and e.via == "direto" for e in members),
            }
            for ln, v in sorted(per_line.items())
        ],
        "total_exposure_brl": brl(sum(per_line.values(), Decimal("0"))),
        "sources": [s for e in members for s in e.sources][:6],
    }
