"""Block 1: identify every statement line.

Input: a masked ``Statement`` and a ``SiloClient``. Output: the
``identification`` section and one ``LineId`` per line for the other blocks.

* Funds (``fundo``, ``FIDC``, ``FII``, ``ETF``): one batched ``portfolio_resolve``
  call (name history + CNPJ + quota tie-break). The quota is sent only for
  ``fundo`` and ``FIDC``: a listed FII/ETF's market price is not its NAV quota.
* Tickers (``ação``, and ``FII``/``ETF`` whose ``codigo`` is a ticker): ``lookup``
  (exact id match only) and ``quote_latest`` (a reference quote, never used to
  revalue the line). For ``ação`` lines ``company_financials`` gives the
  issuer's CNPJ and CVM setor (``lookup`` returns ``cnpj = null`` for tickers).
* ETFs by ticker (engine 1.5): a ticker line typed ``ETF``, or ``outro`` and not a share, with no
  fund CNPJ yet, is sent to ``portfolio_resolve`` by its ticker; only a ``match_kind = "etf_ticker"``
  row (the ticker in SILO's curated ETF registry) is accepted. It gives the ETF's CNPJ for the fee
  block only (``etf_cnpj``): the line stays a ticker for look-through, movement and sector.
* Tesouro: title and maturity parsed from ``codigo``; SILO has no price series,
  so the value is the statement's, labelled.
* Everything else: unknown, with the reason.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from src.portfolio.client import SiloClient
from src.portfolio.common import (
    STATUS_COMPLETE,
    STATUS_NOT_APPLICABLE,
    Section,
    as_date,
    brl,
    call_tool,
    dec,
    is_ticker,
    iso,
    ratio,
    statement_source,
)
from src.portfolio.statement import Position, Statement, codigo_cnpj

FUND_TIPOS = ("fundo", "FIDC", "FII", "ETF")
TICKER_TIPOS = ("ação", "FII", "ETF")
QUOTA_TIPOS = ("fundo", "FIDC")

# Tesouro title as printed (accent-free, upper) -> title family.
TESOURO_TITLES = {
    "LFT": "LFT",
    "TESOURO SELIC": "LFT",
    "LTN": "LTN",
    "TESOURO PREFIXADO": "LTN",
    "NTN-F": "NTN-F",
    "NTNF": "NTN-F",
    "TESOURO PREFIXADO COM JUROS SEMESTRAIS": "NTN-F",
    "NTN-B": "NTN-B",
    "NTNB": "NTN-B",
    "TESOURO IPCA+ COM JUROS SEMESTRAIS": "NTN-B",
    "NTN-B PRINCIPAL": "NTN-B PRINCIPAL",
    "NTNB PRINCIPAL": "NTN-B PRINCIPAL",
    "TESOURO IPCA+": "NTN-B PRINCIPAL",
    "NTN-B1": "NTN-B1",
    "TESOURO RENDA+": "NTN-B1",
    "TESOURO EDUCA+": "NTN-B1",
    "NTN-C": "NTN-C",
    "TESOURO IGPM+ COM JUROS SEMESTRAIS": "NTN-C",
    "NTN-I": "NTN-I",
}
# Title family -> CDA block 1 tp_titpub (as filed; measured 2026-10-03 on 2026-05).
TESOURO_TP_TITPUB = {
    "LFT": "LETRAS FINANCEIRAS DO TESOURO",
    "LTN": "LETRAS DO TESOURO NACIONAL",
    "NTN-F": "NOTAS DO TESOURO NACIONAL - SERIE F",
    "NTN-B": "NOTAS DO TESOURO NACIONAL SERIE B",
    "NTN-B PRINCIPAL": "NOTAS DO TESOURO NACIONAL SERIE B",
    "NTN-B1": "NOTAS DO TESOURO NACIONAL SERIE B",
    "NTN-C": "NOTAS DO TESOURO NACIONAL SERIE C",
    "NTN-I": "NOTAS DO TESOURO NACIONAL SERIE I",
}
_TESOURO_RE = re.compile(r"^(?P<title>.+?)\s+(?P<mat>\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|\d{4})$")

UNSUPPORTED_REASON = {
    "CDB": "O SILO não tem fonte para CDB (bloco 5 da CDA e registros de emissão bancária não ingeridos).",
    "LCI": "O SILO não tem fonte para LCI.",
    "LCA": "O SILO não tem fonte para LCA.",
    "debênture": "Debênture detida diretamente: o SILO não tem cadastro nem preço de debêntures.",
    "CRI": "CRI detido diretamente: identificação por código ainda não implementada nesta versão.",
    "CRA": "CRA detido diretamente: identificação por código ainda não implementada nesta versão.",
    "outro": "Tipo 'outro' sem ticker: o SILO não identifica pelo nome nem pelo código do registro.",
}
CREDIT_TIPOS = ("CRI", "CRA", "CDB", "LCI", "LCA", "debênture", "outro")


@dataclass
class LineId:
    """What block 1 established about one line; read by the other blocks."""

    position: Position
    status: str = "unknown"  # identified | ambiguous | unknown
    reason: str | None = None
    kind: str | None = None  # fund | ticker | tesouro
    cnpj: str | None = None
    name: str | None = None
    entity_type: str | None = None
    ticker: str | None = None
    isin: str | None = None
    asset_class: str | None = None
    issuer_cnpj: str | None = None
    issuer_setor: str | None = None
    issuer_source: dict | None = None
    tesouro_title: str | None = None
    tesouro_maturity: str | None = None
    tesouro_tp_titpub: str | None = None
    etf_cnpj: str | None = None  # engine 1.5: the ETF's CNPJ from the ETF registry, read by the fee block only
    statement_facts: dict[str, Any] = field(default_factory=dict)
    findings: list[dict] = field(default_factory=list)

    @property
    def line_no(self) -> int:
        return self.position.line_no


def _norm(s: str | None) -> str:
    s = s or ""
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().upper()


def parse_tesouro(codigo: str | None) -> tuple[str, str] | None:
    """(title family, maturity ISO date or year) from a ``codigo`` like ``NTN-B 2035-05-15``."""
    if not codigo:
        return None
    m = _TESOURO_RE.match(codigo.strip())
    if not m:
        return None
    family = TESOURO_TITLES.get(_norm(m.group("title")))
    if not family:
        return None
    mat = m.group("mat")
    if "/" in mat:
        d, mo, y = mat.split("/")
        mat = f"{y}-{mo}-{d}"
    return family, mat


def identify(stmt: Statement, client: SiloClient) -> tuple[dict[str, Any], list[LineId]]:
    sec = Section()
    lines = [LineId(position=p) for p in stmt.positions]
    by_no = {li.line_no: li for li in lines}
    resolve_out: dict[int, dict[str, Any]] = {}
    ticker_out: dict[int, dict[str, Any]] = {}

    # --- Funds: one batched portfolio_resolve call. -------------------------------
    fund_lines = [li for li in lines if li.position.tipo in FUND_TIPOS]
    if fund_lines:
        args = {
            "p_names": [li.position.linha_extrato for li in fund_lines],
            "p_cnpjs": [codigo_cnpj(li.position.codigo) for li in fund_lines],
            "p_quotas": [
                float(li.position.preco_unitario)
                if li.position.tipo in QUOTA_TIPOS and li.position.preco_unitario is not None
                else None
                for li in fund_lines
            ],
            "p_quota_dates": [li.position.data_posicao.isoformat() for li in fund_lines],
        }
        res = call_tool(client, "portfolio_resolve", args, sec.errors)
        if not res.ok:
            for li in fund_lines:
                li.reason = "Resolução de fundos indisponível: portfolio_resolve falhou (erro literal em errors)."
            sec.degrade("portfolio_resolve falhou; as linhas de fundo ficaram desconhecidas.")
        else:
            grouped: dict[int, list[dict]] = {}
            for row in res.rows or []:
                try:
                    k = int(row.get("line_no"))
                except (TypeError, ValueError):
                    continue
                grouped.setdefault(k, []).append(row)
            for idx, li in enumerate(fund_lines, start=1):
                cands = sorted(grouped.get(idx, []), key=lambda r: (r.get("rank") is None, r.get("rank") or 0))
                resolve_out[li.line_no] = _apply_resolve(li, cands, res.src(li.position.data_posicao))

    # --- Tickers: lookup + quote_latest (+ company_financials for shares). ---------
    for li in lines:
        p = li.position
        code = (p.codigo or "").strip().upper()
        if p.tipo == "outro" and is_ticker(code):
            pass  # the statement gave a ticker and no type: the lookup says what it is
        elif p.tipo not in TICKER_TIPOS:
            continue
        if not is_ticker(code):
            if p.tipo == "ação":
                li.status, li.reason = "unknown", "Ação sem ticker no campo código: o SILO não identifica ações pelo nome."
            continue
        ticker_out[li.line_no] = _identify_ticker(li, code, client, sec, stmt.position_date)

    # --- ETFs by ticker: the CNPJ for the fee block (engine 1.5). -------------------
    etf_out = _identify_etfs(lines, client, sec, stmt.position_date)

    # --- Tesouro and unsupported types. ---------------------------------------------
    for li in lines:
        p = li.position
        li.statement_facts = _statement_facts(p)
        if p.tipo == "caixa":
            li.status, li.kind, li.name = "identified", "caixa", "Conta corrente"
            li.reason = "Saldo em conta corrente lido do extrato; sem identificação a fazer."
            continue
        if p.tipo == "tesouro":
            parsed = parse_tesouro(p.codigo)
            if not parsed:
                title = TESOURO_TITLES.get(_norm(p.codigo or ""))
                if title:
                    # the statement prints the title but not the maturity: exposure by title, line stays unidentified
                    li.kind, li.tesouro_title = "tesouro", title
                    li.tesouro_tp_titpub = TESOURO_TP_TITPUB.get(title)
                li.status = "unknown"
                li.reason = (
                    "Título do Tesouro sem título e vencimento reconhecíveis no campo código "
                    "(formato: 'NTN-B 2035-05-15')."
                )
                continue
            fam, mat = parsed
            li.status, li.kind = "identified", "tesouro"
            li.tesouro_title, li.tesouro_maturity = fam, mat
            li.tesouro_tp_titpub = TESOURO_TP_TITPUB.get(fam)
            li.name = f"{fam} {mat}"
            li.reason = "Identificado por título e vencimento; o SILO não tem série de preços do Tesouro."
        elif p.tipo in UNSUPPORTED_REASON and li.status != "identified":
            li.status, li.reason = "unknown", UNSUPPORTED_REASON[p.tipo]
            if p.tipo in CREDIT_TIPOS and p.codigo:
                li.reason += f" Código do registro lido do extrato: {p.codigo}."

    out_lines = []
    for li in lines:
        p = li.position
        if li.status == "unknown" and not li.reason:
            li.reason = "Sem identificação."
        out_lines.append(
            {
                "line_no": li.line_no,
                "linha_extrato": p.linha_extrato,
                "tipo": p.tipo,
                "codigo": p.codigo,
                "status": li.status,
                "reason": li.reason,
                "identity": {
                    "kind": li.kind,
                    "cnpj": li.cnpj,
                    "name": li.name,
                    "entity_type": li.entity_type,
                    "ticker": li.ticker,
                    "isin": li.isin,
                    "asset_class": li.asset_class,
                    "issuer_cnpj": li.issuer_cnpj,
                    "tesouro_title": li.tesouro_title,
                    "tesouro_maturity": li.tesouro_maturity,
                    "etf_cnpj": li.etf_cnpj,
                },
                "statement_facts": li.statement_facts,
                "fund_match": resolve_out.get(li.line_no),
                "ticker_match": ticker_out.get(li.line_no),
                "etf_match": etf_out.get(li.line_no),
                "valuation": {
                    "value_brl": brl(p.valor),
                    "basis": "statement",
                    "note": "Valor do extrato; o SILO não reavalia a posição.",
                    "sources": [statement_source(p.line_no, p.data_posicao)],
                },
                "findings": li.findings,
            }
        )
    counts = {s: sum(1 for li in lines if li.status == s) for s in ("identified", "ambiguous", "unknown")}
    if sec.status == STATUS_COMPLETE and counts["identified"] < len(lines):
        sec.status = "partial"
        sec.reason = f"{counts['ambiguous']} linha(s) ambígua(s) e {counts['unknown']} desconhecida(s)."
    if not lines:
        sec.status = STATUS_NOT_APPLICABLE
    return {**sec.head(), "counts": counts, "lines": out_lines}, lines


def _apply_resolve(li: LineId, cands: list[dict], src: dict) -> dict[str, Any]:
    def cand(r: dict) -> dict[str, Any]:
        return {
            "rank": r.get("rank"),
            "cnpj": r.get("candidate_cnpj"),
            "name": r.get("candidate_name"),
            "matched_name": r.get("matched_name"),
            "matched_period": r.get("matched_period"),
            "entity_type": r.get("entity_type"),
            "match_kind": r.get("match_kind"),
            "similarity": ratio(dec(r.get("similarity")), 4),
            "quota_on_date": ratio(dec(r.get("quota_on_date"))),
            "quota_rel_diff": ratio(dec(r.get("quota_rel_diff"))),
            "ambiguous": r.get("ambiguous"),
            "reason": r.get("reason"),
        }

    out: dict[str, Any] = {
        "candidates": [cand(r) for r in cands],
        "quota_basis": "implícita (valor / quantidade do extrato)" if li.position.preco_implicito else "impressa no extrato",
        "sources": [src],
    }
    if not cands:
        li.status = "unknown"
        li.reason = "portfolio_resolve não encontrou candidato pelo nome (histórico) nem pelo CNPJ."
        return out
    top = cands[0]
    out["tiebroken_by_quota"] = bool(
        len(cands) > 1
        and not top.get("ambiguous")
        and "quota" in str(top.get("reason") or "").lower()
        and (cands[1].get("quota_rel_diff") is None or (dec(cands[1].get("quota_rel_diff")) or 0) > (dec(top.get("quota_rel_diff")) or 0))
    )
    if top.get("ambiguous"):
        li.status = "ambiguous"
        li.reason = top.get("reason") or "Mais de um fundo plausível; a cota não desempata."
        return out
    li.status, li.kind = "identified", "fund"
    li.cnpj = top.get("candidate_cnpj")
    li.name = top.get("candidate_name")
    li.entity_type = top.get("entity_type")
    li.reason = top.get("reason")
    out["chosen"] = cand(top)
    matched = top.get("matched_name")
    if matched and li.name and _norm(matched) != _norm(li.name):
        li.findings.append(
            {
                "kind": "renamed",
                "text": (
                    f"O nome no extrato corresponde a um nome antigo do fundo (registrado em "
                    f"{top.get('matched_period')}); o nome atual é '{li.name}'."
                ),
                "matched_name": matched,
                "matched_period": top.get("matched_period"),
                "current_name": li.name,
                "sources": [src],
            }
        )
    given = codigo_cnpj(li.position.codigo)
    if given and li.cnpj and given != li.cnpj:
        li.findings.append(
            {
                "kind": "cnpj_conflict",
                "text": f"O CNPJ do extrato ({given}) difere do fundo resolvido ({li.cnpj}).",
                "sources": [src],
            }
        )
    return out


def _identify_etfs(lines: list[LineId], client: SiloClient, sec: Section, pos_date: dt.date) -> dict[int, dict[str, Any]]:
    """Ticker lines that may be ETFs: their CNPJ from SILO's ETF registry through portfolio_resolve (engine 1.5)."""
    probe = []
    for li in lines:
        code = (li.position.codigo or "").strip().upper()
        if li.cnpj or not is_ticker(code):
            continue
        if li.position.tipo == "ETF" or (li.position.tipo == "outro" and li.asset_class != "equity"):
            probe.append((li, code))
    if not probe:
        return {}
    res = call_tool(client, "portfolio_resolve", {"p_names": [code for _, code in probe]}, sec.errors)
    if not res.ok:
        sec.degrade("portfolio_resolve falhou para os tickers que podem ser ETF; a taxa desses ETFs ficou desconhecida.")
        return {}
    by_line: dict[int, dict] = {}
    for row in res.rows or []:
        if row.get("match_kind") != "etf_ticker" or not row.get("candidate_cnpj"):
            continue  # only the ETF registry's exact ticker counts; a name match on a ticker is never used
        try:
            by_line.setdefault(int(row.get("line_no")), row)
        except (TypeError, ValueError):
            continue
    out: dict[int, dict[str, Any]] = {}
    for idx, (li, code) in enumerate(probe, start=1):
        row = by_line.get(idx)
        if row is None:
            continue
        li.etf_cnpj = str(row["candidate_cnpj"])
        out[li.line_no] = {
            "ticker": code,
            "cnpj": li.etf_cnpj,
            "name": row.get("candidate_name"),
            "match_kind": "etf_ticker",
            "reason": row.get("reason"),
            "use": "CNPJ do ETF usado só para a taxa; a linha continua identificada pelo ticker.",
            "sources": [res.src(pos_date)],
        }
        if li.status != "identified":
            # a fixed income ETF is not in COTAHIST, so lookup does not find its ticker; the ETF registry does
            li.status, li.kind, li.ticker = "identified", "ticker", code
            li.name = li.name or row.get("candidate_name")
            li.reason = (f"ETF {code} identificado pelo ticker no registro de ETFs do SILO (cvm_etf_registry); "
                         "lookup não o encontrou (ETFs de renda fixa não estão no COTAHIST).")
    return out


def _identify_ticker(li: LineId, code: str, client: SiloClient, sec: Section, pos_date: dt.date) -> dict[str, Any]:
    out: dict[str, Any] = {"ticker": code}
    lk = call_tool(client, "lookup", {"p_query": code}, sec.errors)
    if not lk.ok:
        sec.degrade(f"lookup falhou para {code}.")
        if li.status != "identified":
            li.status, li.reason = "unknown", "lookup falhou (erro literal em errors)."
        return out
    exact = [r for r in lk.rows or [] if str(r.get("id", "")).upper() == code]
    out["lookup"] = {"rows": exact, "sources": [lk.src()]}
    if not exact:
        if li.status != "identified":
            li.status, li.reason = "unknown", f"Ticker {code} não encontrado no SILO (lookup sem correspondência exata)."
        return out
    row = exact[0]
    li.ticker = code
    li.isin = row.get("isin")
    li.asset_class = row.get("asset_class")
    if li.status != "identified" or li.kind is None:
        li.status, li.kind = "identified", "ticker"
        li.name = li.name or row.get("name")
        li.reason = None
    elif li.kind == "fund":
        li.reason = (li.reason + " " if li.reason else "") + f"Ticker {code} confirmado por lookup."

    q = call_tool(client, "quote_latest", {"p_ticker": code}, sec.errors)
    if q.ok and q.rows:
        qr = q.rows[0]
        out["reference_quote"] = {
            "close": ratio(dec(qr.get("close")), 6),
            "trade_date": qr.get("trade_date"),
            "label": "Cotação de referência; o valor da posição continua sendo o do extrato.",
            "sources": [q.src(qr.get("trade_date"))],
        }
    elif q.ok:
        out["reference_quote"] = None
    else:
        sec.degrade(f"quote_latest falhou para {code}.")

    if li.position.tipo == "ação" or li.asset_class == "equity":
        args = {"p_id": code, "p_from": (pos_date - dt.timedelta(days=548)).isoformat(), "p_to": pos_date.isoformat()}
        cf = call_tool(client, "company_financials", args, sec.errors)
        if cf.ok and cf.rows:
            latest = max(cf.rows, key=lambda r: str(r.get("ref_date") or ""))
            li.issuer_cnpj = latest.get("cnpj")
            li.issuer_setor = latest.get("setor")
            li.issuer_source = cf.src(latest.get("ref_date"))
            out["issuer"] = {
                "cnpj": li.issuer_cnpj,
                "company": latest.get("company"),
                "setor_cvm": li.issuer_setor,
                "sources": [li.issuer_source],
            }
        elif cf.ok:
            out["issuer"] = None
        else:
            sec.degrade(f"company_financials falhou para {code}; emissor e setor desconhecidos.")
    return out


def _statement_facts(p: Position) -> dict[str, Any]:
    """What the statement itself prints about the line, beyond name and value (all null for a spreadsheet)."""
    return {
        "vencimento": iso(p.vencimento),
        "taxa_texto": p.taxa_texto,
        "estrategia_corretora": p.estrategia_corretora,
        "classe_corretora": p.classe_corretora,
        "conta_ref": p.conta_ref,
        "preco_implicito": p.preco_implicito,
    }
