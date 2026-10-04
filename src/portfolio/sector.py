"""Block 11: exposure by sector.

Only published fields, never a name:

* listed shares (direct and inside funds): CVM's ``cia_company.setor`` through
  ``company_financials(p_id=ticker).setor``; when that is empty, B3's own
  sector from the ``short_interest`` view (``sector``), labelled as B3's.
* FIDC: ``cvm_fidc_setor`` through ``fidc_portfolio(kind='sector')``: lettered
  codes are sectors, ``TOTAL`` the book, digit codes members of their parent
  (summing parents only).
* FII ``segmento_atuacao`` and ETF ``segment`` have no tool in the public
  contract, so they are ``sem classificação`` with that reason.
* everything else: ``sem classificação``, with the reason.

Look-through share exposures are resolved for the ``top_tickers`` largest
tickers by exposure (one ``company_financials`` call each); the rest is
``sem classificação`` with the reason, so the call count is bounded and said.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from decimal import Decimal
from typing import Any

from src.portfolio.client import SiloClient
from src.portfolio.common import (
    UNCLASSIFIED,
    Section,
    brl,
    call_tool,
    dec,
    is_ticker,
    pct,
    ratio,
)
from src.portfolio.identify import LineId
from src.portfolio.lookthrough import Exposure

STOCK_TP_APLIC = ("Ações", "Ações e outros TVM cedidos em empréstimo")
FII_ETF_REASON = (
    "Nenhuma ferramenta do contrato público do SILO expõe cvm_fii_periodic.segmento_atuacao nem "
    "cvm_etf_registry.segment; o setor não é inferido pelo nome."
)


def compute_sector(
    lines: list[LineId],
    exposures: dict[int, list[Exposure]],
    unexplained: dict[int, Decimal],
    client: SiloClient,
    pos_date: dt.date,
    top_tickers: int = 10,
) -> dict[str, Any]:
    sec = Section()
    total = sum((li.position.valor for li in lines), Decimal("0"))
    items: list[dict[str, Any]] = []
    by_sector: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    unclassified_reasons: dict[str, Decimal] = defaultdict(Decimal)

    def add(line_no, via, key, sector, taxonomy, value, reason, sources):
        if sector is None:
            sector, taxonomy = UNCLASSIFIED, "-"
            unclassified_reasons[reason or "sem setor publicado"] += value
        by_sector[(sector, taxonomy)] += value
        items.append(
            {
                "line_no": line_no,
                "via": via,
                "asset_key": key,
                "sector": sector,
                "taxonomy": taxonomy,
                "reason_unclassified": reason if sector == UNCLASSIFIED else None,
                "exposure_brl": brl(value),
                "sources": sources,
            }
        )

    # Sector per ticker, cached: direct share lines first, then the biggest inside funds.
    ticker_sector: dict[str, dict[str, Any]] = {}
    for li in lines:
        if li.kind == "ticker" and (li.position.tipo == "ação" or li.asset_class == "equity") and li.ticker:
            ticker_sector[li.ticker] = {
                "sector": li.issuer_setor,
                "taxonomy": "CVM (cia_company.setor)",
                "sources": [li.issuer_source] if li.issuer_source else [],
            }
    inside: dict[str, Decimal] = defaultdict(Decimal)
    for ln, exps in exposures.items():
        for e in exps:
            if e.via != "direto" and e.block == "4" and e.tp_aplic in STOCK_TP_APLIC and is_ticker(e.asset_key):
                inside[e.asset_key.upper()] += abs(e.value_brl)
    to_query = [t for t, _ in sorted(inside.items(), key=lambda kv: -kv[1]) if t not in ticker_sector][:top_tickers]
    skipped = {t for t in inside if t not in ticker_sector and t not in to_query}
    for t in to_query:
        ticker_sector[t] = _query_ticker_sector(client, t, pos_date, sec)
    # B3 fallback where CVM gave nothing.
    for t, d in list(ticker_sector.items()):
        if d["sector"] is None and not d.get("failed"):
            fb = _b3_sector(client, t, sec)
            if fb:
                ticker_sector[t] = fb

    for li in lines:
        p = li.position
        exps = exposures.get(li.line_no, [])
        if li.kind == "fund" and p.tipo == "FIDC" and li.cnpj:
            _fidc_sector(li, client, pos_date, sec, add)
            continue
        if li.kind == "fund" and p.tipo in ("FII", "ETF"):
            add(li.line_no, "direto", li.ticker or li.cnpj, None, None, p.valor, FII_ETF_REASON, [])
            continue
        if not exps:
            reason = li.reason if li.status != "identified" else "sem exposição aberta para esta linha"
            add(li.line_no, "direto", None, None, None, p.valor, f"linha {li.line_no}: {reason}", [])
            continue
        for e in exps:
            if e.asset_kind == "acao_direta":
                d = ticker_sector.get(e.asset_key or "", {})
                add(e.line_no, e.via, e.asset_key, d.get("sector"), d.get("taxonomy"), e.value_brl,
                    "ticker sem setor publicado (CVM nem B3)", d.get("sources", e.sources))
            elif e.block == "4" and e.tp_aplic in STOCK_TP_APLIC and is_ticker(e.asset_key):
                t = e.asset_key.upper()
                if t in skipped:
                    add(e.line_no, e.via, e.asset_key, None, None, e.value_brl,
                        f"setor não consultado: fora dos {top_tickers} maiores tickers do look-through", e.sources)
                else:
                    d = ticker_sector.get(t, {})
                    add(e.line_no, e.via, e.asset_key, d.get("sector"), d.get("taxonomy"), e.value_brl,
                        d.get("reason") or "ticker sem setor publicado (CVM nem B3)", e.sources + d.get("sources", []))
            else:
                add(e.line_no, e.via, e.asset_key, None, None, e.value_brl,
                    _non_equity_reason(e), e.sources)
        resid = unexplained.get(li.line_no)
        if resid:
            add(li.line_no, "fundo", None, None, None, resid,
                "parte do fundo que a CDA ingerida não explica", [])

    if skipped:
        sec.degrade(f"{len(skipped)} ticker(s) dentro de fundos não tiveram o setor consultado (limite de {top_tickers}).", code="limite_tickers")
    by_sector.setdefault((UNCLASSIFIED, "-"), Decimal("0"))
    ordered = sorted(by_sector.items(), key=lambda kv: (kv[0][0] == UNCLASSIFIED, -kv[1]))
    return {
        **sec.head(),
        "never_inferred_from_name": True,
        "lookthrough_ticker_limit": top_tickers,
        "portfolio_value_brl": brl(total),
        "sectors": [
            {"sector": k[0], "taxonomy": k[1], "value_brl": brl(v), "portfolio_pct": pct(v, total)}
            for k, v in ordered
        ],
        "sum_check_brl": brl(sum(by_sector.values(), Decimal("0")) - total),
        "unclassified_breakdown": [
            {"reason": k, "value_brl": brl(v), "portfolio_pct": pct(v, total)}
            for k, v in sorted(unclassified_reasons.items(), key=lambda kv: -kv[1])
        ],
        "items": items,
    }


def _non_equity_reason(e: Exposure) -> str:
    if e.asset_kind == "caixa":
        return "conta corrente: sem setor"
    if e.asset_kind == "credito_direto":
        return "crédito privado direto: o extrato não traz o setor do emissor"
    if e.asset_kind == "cota_listada":
        return FII_ETF_REASON
    if e.opaque_fund:
        return "fundo investido sem carteira disponível na CDA"
    if e.block == "1" or e.asset_kind == "titulo_publico_direto":
        return "título público federal: sem setor publicado"
    if e.block == "6" or (e.tp_aplic or "").startswith("Deb"):
        return "crédito privado: o SILO não publica setor do emissor para debêntures sem cadastro"
    return f"ativo sem setor publicado (bloco {e.block}, {e.tp_aplic})"


def _query_ticker_sector(client: SiloClient, ticker: str, pos_date: dt.date, sec: Section) -> dict[str, Any]:
    args = {"p_id": ticker, "p_from": (pos_date - dt.timedelta(days=548)).isoformat(), "p_to": pos_date.isoformat()}
    cf = call_tool(client, "company_financials", args, sec.errors)
    if not cf.ok:
        sec.degrade(f"company_financials falhou para {ticker}.", code="consulta_falhou")
        return {"sector": None, "taxonomy": None, "failed": True, "reason": "company_financials falhou", "sources": []}
    if not cf.rows:
        return {"sector": None, "taxonomy": None, "reason": f"{ticker} sem demonstrações na CVM", "sources": [cf.src()]}
    latest = max(cf.rows, key=lambda r: str(r.get("ref_date") or ""))
    return {
        "sector": latest.get("setor"),
        "taxonomy": "CVM (cia_company.setor)",
        "sources": [cf.src(latest.get("ref_date"))],
    }


def _b3_sector(client: SiloClient, ticker: str, sec: Section) -> dict[str, Any] | None:
    args = {"filters": {"ticker": f"eq.{ticker}"}, "select": "ticker,trade_date,sector", "order": "trade_date.desc", "limit": 1}
    r = call_tool(client, "short_interest", args, sec.errors)
    if not r.ok:
        sec.degrade(f"short_interest (setor B3) falhou para {ticker}.", code="consulta_falhou")
        return None
    if r.rows and r.rows[0].get("sector"):
        return {"sector": r.rows[0]["sector"], "taxonomy": "B3 (short_interest.sector)", "sources": [r.src(r.rows[0].get("trade_date"))]}
    return None


def _fidc_sector(li: LineId, client: SiloClient, pos_date: dt.date, sec: Section, add) -> None:
    p = li.position
    args = {
        "p_cnpj": li.cnpj,
        "p_kind": "sector",
        "p_from": (pos_date.replace(day=1) - dt.timedelta(days=100)).isoformat(),
        "p_to": pos_date.isoformat(),
    }
    r = call_tool(client, "fidc_portfolio", args, sec.errors)
    if not r.ok:
        sec.degrade(f"fidc_portfolio falhou para a linha {li.line_no}.", code="consulta_falhou")
        add(li.line_no, "direto", li.cnpj, None, None, p.valor, "fidc_portfolio falhou (erro literal em errors)", [])
        return
    if not r.rows:
        add(li.line_no, "direto", li.cnpj, None, None, p.valor, "FIDC sem carteira por setor (tab II) no período", [r.src()])
        return
    period = max(str(x.get("period")) for x in r.rows)
    month = [x for x in r.rows if str(x.get("period")) == period]
    total = next((dec(x.get("value")) for x in month if x.get("code") == "TOTAL"), None)
    sectors = [x for x in month if re.fullmatch(r"[A-Z]", str(x.get("code") or "")) and dec(x.get("value"))]
    src = [r.src(period)]
    if not total or total <= 0 or not sectors:
        add(li.line_no, "direto", li.cnpj, None, None, p.valor, "FIDC sem total de carteira por setor no período", src)
        return
    allocated = Decimal("0")
    for x in sorted(sectors, key=lambda x: -(dec(x.get("value")) or 0)):
        w = (dec(x.get("value")) or Decimal("0")) / total
        allocated += w
        add(li.line_no, f"direto (tab II {period})", x.get("code"), x.get("item"), "CVM (cvm_fidc_setor)", p.valor * w, None, src)
    if allocated < 1:
        add(li.line_no, f"direto (tab II {period})", li.cnpj, None, None, p.valor * (1 - allocated),
            "parte da carteira de direitos creditórios sem setor informado (tab II)", src)
