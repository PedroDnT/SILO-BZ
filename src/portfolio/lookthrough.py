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
    Call,
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

LOOKTHROUGH_TIPOS = ("fundo", "FIDC", "FII", "ETF", "FIP")
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
    taxa_texto: str | None = None  # the rate as the statement prints it (direct credit lines)
    tesouro_title: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "line_no": self.line_no,
            "via": self.via,
            "depth": self.depth,
            "block": self.block,
            "asset_kind": self.asset_kind,
            "not_opened_fund": self.opaque_fund,
            "asset_key": self.asset_key,
            "asset_name": self.asset_name,
            "isin": self.isin,
            "issuer_cnpj": self.issuer_cnpj,
            "issuer_code": self.issuer_code,
            "tp_aplic": self.tp_aplic,
            "tp_ativo": self.tp_ativo,
            "tp_titpub": self.tp_titpub,
            "indexer_code": self.indexer_code,
            "taxa_texto": self.taxa_texto,
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
    depth_reduced: list[int] = []

    for li in lines:
        exposures[li.line_no] = _direct_exposures(li)

    for li in roots:
        res, depth_used = _lookthrough_call(client, li.cnpj, cda_month, max_depth, sec.errors)
        if depth_used < max_depth:
            depth_reduced.append(li.line_no)
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
        all_rows = res.rows or []
        cycles = [r for r in all_rows if r.get("is_cycle") or r.get("asset_kind") == "fund_quota_cycle"]
        no_cda = [r for r in all_rows if r.get("asset_kind") == "no_cda_filing"]
        rows = [r for r in all_rows if r not in cycles and r not in no_cda]
        if no_cda and not rows:
            out_lines.append(
                {
                    "line_no": li.line_no,
                    "cnpj": li.cnpj,
                    "status": "no_holdings",
                    "reason": (
                        f"O fundo não entregou CDA em {cda_month.strftime('%Y-%m')} (no_cda_filing): "
                        "sem carteira para abrir (FIDC e FII não entregam CDA)."
                    ),
                    "n_rows": len(all_rows),
                    "exposures": [],
                    "sources": [res.src(cda_month)],
                }
            )
            exposures[li.line_no] = []
            continue
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
        exp, nodes, weight_sum, no_weight = _expand(li, rows, res)
        exposures[li.line_no] = exp
        fund_nodes[li.line_no] = nodes
        out_lines.append(
            {
                "line_no": li.line_no,
                "cnpj": li.cnpj,
                "status": "partial" if no_weight else "complete",
                "reason": (
                    f"{len(no_weight)} linha(s) sem peso (patrimônio de um fundo no caminho desconhecido): "
                    "fora das exposições e da soma, valores em rows_without_weight."
                    if no_weight
                    else None
                ),
                "rows_without_weight": no_weight,
                "n_rows": len(all_rows),
                "n_cycle_rows_skipped": len(cycles),
                "max_depth_seen": max((int(r.get("depth") or 0) for r in rows), default=0),
                "max_depth_used": depth_used,
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
        sec.fail("portfolio_lookthrough falhou para todos os fundos (erros literais em errors).", code="consulta_falhou")
    elif refused:
        sec.degrade(f"portfolio_lookthrough falhou para {refused} de {len(roots)} fundos; essas linhas ficaram sem look-through.", code="consulta_falhou")
    if depth_reduced:
        sec.degrade(
            f"{len(depth_reduced)} fundo(s) aberto(s) com profundidade menor que {max_depth}: a resposta passava de "
            "1000 linhas (22023); os fundos abaixo do limite ficam como limite de profundidade.",
            code="profundidade_reduzida",
        )
    empty = [o for o in out_lines if o["status"] == "no_holdings"]
    if empty:
        sec.degrade(f"{len(empty)} fundo(s) sem carteira na CDA do mês.", code="sem_carteira_cda")
    partial_lines = [o for o in out_lines if o["status"] == "partial"]
    if partial_lines:
        sec.degrade(f"{len(partial_lines)} fundo(s) com linhas sem peso.", code="linhas_sem_peso")

    shared = shared_exposure(lines, exposures, fund_nodes)
    section = {
        **sec.head(),
        "cda_month": cda_month.isoformat(),
        "max_depth": max_depth,
        "lines": out_lines,
        "shared_exposure": shared,
    }
    return section, exposures


_ROW_CAP = re.compile(r"more than 1000 rows")  # 22023 alone is also a bad argument: only the page cap steps down


def _lookthrough_call(client: SiloClient, cnpj: str, cda_month: dt.date, max_depth: int, errors: list[dict]) -> tuple[Call, int]:
    """One fund's look-through. A fund of funds can pass the API's one-page cap (22023, more than 1000 rows) at the
    requested depth: retry one level shallower, down to 1, and say which depth answered. A refusal followed by an
    answer is not an error of the section; when no depth answers, every refusal goes to ``errors``."""
    depth = max_depth
    tried: list[dict] = []
    while True:
        args = {"p_cnpjs": [cnpj], "p_month": cda_month.isoformat(), "p_max_depth": depth}
        res = call_tool(client, "portfolio_lookthrough", args, tried)
        if res.ok or depth <= 1 or res.transient or not _ROW_CAP.search(res.error or ""):
            break
        depth -= 1
    if not res.ok:
        errors.extend(tried)
    return res, depth


def add_portfolio_shares(section: dict[str, Any], exposures: dict[int, list[Exposure]], total: Decimal, top_n: int = 10) -> None:
    """Percent of the WHOLE portfolio for every exposure and group, and the largest exposures across lines.

    ``top_exposures`` sums the same asset (asset key, else ISIN) across lines, direct positions
    included; funds that were not opened, and the current account, are left out.
    """
    if not total:
        section["top_exposures"] = []
        return

    def share(v: Decimal) -> float:
        return float((v / total * 100).quantize(Decimal("0.0001")))

    for ln in section["lines"]:
        for e in ln.get("exposures", []):
            e["portfolio_pct"] = share(dec(e["exposure_brl"]) or Decimal("0"))
    for g in section["shared_exposure"]["groups"]:
        g["total_exposure_portfolio_pct"] = share(dec(g["total_exposure_brl"]) or Decimal("0"))
    agg: dict[str, dict[str, Any]] = {}
    for line_no, exps in exposures.items():
        for e in exps:
            if e.opaque_fund or e.asset_kind == "caixa" or not (e.asset_key or e.isin):
                continue
            k = (e.asset_key or e.isin or "").upper()
            row = agg.setdefault(k, {"asset_key": e.asset_key, "asset_name": e.asset_name, "isin": e.isin, "value": Decimal("0"), "line_nos": set(), "sources": []})
            row["value"] += e.value_brl
            row["line_nos"].add(line_no)
            row["sources"].extend(e.sources[:2])
            row["asset_name"] = row["asset_name"] or e.asset_name
    top = sorted(agg.values(), key=lambda r: -abs(r["value"]))[:top_n]
    section["top_exposures"] = [
        {
            "asset_key": r["asset_key"],
            "asset_name": r["asset_name"],
            "isin": r["isin"],
            "exposure_brl": brl(r["value"]),
            "portfolio_pct": share(r["value"]),
            "line_nos": sorted(r["line_nos"]),
            "sources": r["sources"][:4],
        }
        for r in top
    ]


def _direct_exposures(li: LineId) -> list[Exposure]:
    """The line itself as an exposure, for the lines that are not opened as funds."""
    p = li.position
    src = [statement_source(p.line_no, p.data_posicao)]
    if li.kind == "ticker":
        equity = p.tipo == "ação" or li.asset_class == "equity"
        return [
            Exposure(
                line_no=li.line_no,
                via="direto",
                depth=0,
                block=None,
                asset_kind="acao_direta" if equity else "cota_listada",
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
                asset_key=f"{li.tesouro_title} {li.tesouro_maturity}" if li.tesouro_maturity else li.tesouro_title,
                asset_name=li.name or li.tesouro_title,
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
                tesouro_title=li.tesouro_title,
            )
        ]
    if p.tipo == "caixa":
        return [
            Exposure(
                line_no=li.line_no, via="direto", depth=0, block=None, asset_kind="caixa", asset_key="conta corrente",
                asset_name="Conta corrente", isin=None, issuer_cnpj=None, issuer_code=None, tp_aplic=None, tp_ativo=None,
                tp_titpub=None, indexer_code=None, maturity=None, weight=Decimal(1), value_brl=p.valor,
                period=p.data_posicao.isoformat(), sources=src,
            )
        ]
    credit_tipo = p.tipo in ("CRI", "CRA", "CDB", "LCI", "LCA", "debênture", "outro")
    if credit_tipo and (li.kind == "credito" or (li.kind is None and p.taxa_texto)):
        # a direct credit line: identified by its registry code (engine 1.9) or not, the statement prints its rate and
        # maturity. An identified debênture carries its ISIN and B3 issuer code, so the issuer-code overlap check finds
        # the same issuer held inside the funds; a CRA or CRI keeps none (its ISIN code is the securitizadora's).
        deb = li.kind == "credito" and p.tipo == "debênture"
        return [
            Exposure(
                line_no=li.line_no, via="direto", depth=0, block=None, asset_kind="credito_direto", asset_key=p.codigo,
                asset_name=p.linha_extrato, isin=li.isin if deb else None, issuer_cnpj=None,
                issuer_code=(li.issuer_code or b3_issuer_code(li.isin)) if deb else None, tp_aplic=None, tp_ativo=None,
                tp_titpub=None, indexer_code=None, maturity=p.vencimento.isoformat() if p.vencimento else None,
                weight=Decimal(1), value_brl=p.valor, period=p.data_posicao.isoformat(), sources=src, taxa_texto=p.taxa_texto,
            )
        ]
    return []


def _expand(li: LineId, rows: list[dict], res) -> tuple[list[Exposure], list[dict], Decimal, list[dict]]:
    """Leaves, fund nodes, the leaves' weight sum and the rows with no weight.

    The tool's rule: sum ``weight_in_root`` over every row but ``fund_quota`` (a fund looked
    through, whose own holdings are the rows below it). ``fund_quota_unfiled`` and
    ``fund_quota_depth_cap`` are funds that could not be opened: leaves, with the reason.
    """
    p = li.position
    exposures: list[Exposure] = []
    nodes: list[dict[str, Any]] = []
    no_weight: list[dict] = []
    weight_sum = Decimal("0")
    for r in rows:
        kind = r.get("asset_kind")
        block = block_number(r.get("block"))
        key = r.get("asset_key")
        w = dec(r.get("weight_in_root"))
        src = [res.src(r.get("period"))]
        is_quota = kind in ("fund_quota", "fund_quota_unfiled", "fund_quota_depth_cap")
        if is_quota:
            nodes.append(
                {
                    "fund_cnpj": key,
                    "fund_name": r.get("asset_name"),
                    "depth": r.get("depth"),
                    "path": r.get("path"),
                    "weight_in_line": ratio(w) if w is not None else None,
                    "value_brl": brl(p.valor * w) if w is not None else None,
                    "expanded": kind == "fund_quota",
                    "not_expanded_reason": {
                        "fund_quota_unfiled": "o fundo investido não entregou CDA no mês",
                        "fund_quota_depth_cap": "limite de profundidade do look-through",
                    }.get(kind),
                    "period": r.get("period"),
                    "sources": src,
                }
            )
        if kind == "fund_quota":
            continue
        if w is None:
            no_weight.append({"asset_kind": kind, "asset_key": key, "value_brl_as_filed": brl(dec(r.get("value_brl"))), "path": r.get("path")})
            continue
        weight_sum += w
        exposures.append(
            Exposure(
                line_no=li.line_no,
                via=_via(r.get("path")),
                depth=int(r.get("depth") or 0),
                block=block,
                asset_kind=kind,
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
                opaque_fund=is_quota,
                sources=src,
            )
        )
    return exposures, nodes, weight_sum, no_weight


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
        # the sovereign (Tesouro) is not an issuer concentration: its ISIN code is left out
        if e.issuer_code and not e.opaque_fund and e.asset_kind not in ("titulo_publico_direto", "government_bond", "repo", "other_block1"):
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
    # A fund or ETF held directly is the same fund when another line holds it underneath (real statement,
    # 2026-10-05: an ETF bought directly and also inside a credit fund's master). Only with at least one
    # look-through leg: two direct lines of one fund are one position in two accounts, not an overlap.
    for li in lines:
        c = li.cnpj if li.kind == "fund" else li.etf_cnpj
        if c and str(c) in by_fund:
            by_fund[str(c)].append((li.line_no, {"fund_cnpj": c, "fund_name": li.name or li.position.linha_extrato,
                                                 "value_brl": float(li.position.valor), "direct": True, "sources": []}))
    for cnpj, members in sorted(by_fund.items()):
        line_nos = sorted({ln for ln, _ in members})
        if len(line_nos) < 2 or all(n.get("direct") for _, n in members):
            continue
        direct = sorted({ln for ln, n in members if n.get("direct")})
        per_line: dict[int, Decimal] = defaultdict(Decimal)
        for ln, n in members:
            per_line[ln] += dec(n.get("value_brl")) or Decimal("0")
        groups.append(
            {
                "kind": "mesmo_fundo_investido",
                "label": f"fundo {cnpj} ({members[0][1].get('fund_name')})",
                "fund_cnpj": cnpj,
                "line_nos": line_nos,
                "direct_line_nos": direct,
                "lines": [
                    {"line_no": ln, "linha_extrato": names[ln], "exposure_brl": brl(v), "direct": ln in direct}
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
