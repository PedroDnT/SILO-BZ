"""Dated administration-fee peers, never a saving estimate or recommendation."""
from __future__ import annotations

import calendar
import datetime as dt
from decimal import Decimal
from typing import Any

from src.portfolio.client import SiloClient
from src.portfolio.common import Section, as_date, brl, call_tool, dec, pct, ratio, statement_source
from src.portfolio.fees import FEE_TIPOS
from src.portfolio.identify import LineId

REASONS = {
    "sem_identificacao": "fundo sem identificação suficiente para comparação",
    "tipo_fora_comparacao": "ETF, FIDC, FII ou FIP: fora da comparação de taxas de fundos FI",
    "sem_extrato_comparavel": "sem Extrato CVM para comparar",
    "sem_classe_comparavel": "classe ANBIMA não informada no Extrato",
    "sem_tipo_comparavel": "indicador de fundo de fundos não informado como S ou N",
    "sem_escopo_comparavel": "escopo do documento não informado como fundo FI ou classe FIF",
    "taxa_nao_utilizavel": "taxa ausente, zero, negativa ou acima de cinco por cento ao ano; a conferir",
    "taxa_defasada_comparacao": "taxa do Extrato com mais de trinta e seis meses; fora da comparação",
    "taxa_data_futura": "documento posterior à data da comparação",
    "pares_insuficientes": "menos de trinta pares com taxa utilizável; sem comparação mais ampla",
    "fonte_taxa_diverge": "taxa exibida vem de outra fonte ou versão; fora da comparação do Extrato",
    "consulta_falhou": "consulta de comparação de taxas falhou ou foi recusada",
    "sem_linha_comparacao": "o SILO não devolveu comparação para este fundo",
    "resposta_inconsistente": "resposta de comparação inconsistente; fundo não comparado",
}
BASIS = (
    "Taxa de administração do Extrato CVM versus fundos FI ativos da mesma classe ANBIMA, indicador de fundo de "
    "fundos e escopo do documento (fundo FI ou classe FIF). Ao menos trinta taxas utilizáveis, positivas e até cinco "
    "por cento ao ano, com documento de até trinta e seis meses. Universo ativo: cota em um dos três meses de "
    "referência. Inclui o próprio fundo quando elegível. Documentos mais recentes disponíveis, não um histórico. "
    "Performance e despesa total não entram. ETFs de índice ligado à classe na lista revisada entram como pares e nas "
    "estatísticas, com a taxa do site etfsbrasil.com.br (fonte de terceiros), e são contados à parte. Percentil por posição média dos empates; diferença em pontos "
    "percentuais para a mediana. Não mede qualidade, economia realizável ou recomendação de troca."
)
# catalog v66 (#609): the peer group split by kind, copied as served. An ETF peer's fee is the third-party site's
# (etf_peer_fee_source), never a CVM-disclosed fee; n_peers = n_fund_peers + n_etf_peers.
ETF_PEER_KEYS = ("n_fund_peers", "n_etf_peers", "n_etf_excluded", "etf_peer_tickers", "etf_peer_fee_oldest",
                 "etf_peer_fee_newest", "etf_peer_fee_source")
STATS = ("p25_pct_year", "median_pct_year", "p75_pct_year", "percentile_pct", "difference_pp")


def compute_fee_peers(lines: list[LineId], fees: dict, client: SiloClient, as_of: dt.date,
                      portfolio_total: Decimal) -> dict[str, Any]:
    sec = Section()
    oldest_year = as_of.year - 3
    oldest_fee_date = dt.date(oldest_year, as_of.month,
                              min(as_of.day, calendar.monthrange(oldest_year, as_of.month)[1]))
    funds = [li for li in lines if li.position.tipo in FEE_TIPOS]
    eligible = [li for li in funds if li.position.tipo == "fundo" and li.status == "identified" and li.cnpj
                and li.entity_type in (None, "fi")]
    ids = sorted({li.cnpj for li in eligible})
    found = {}
    failed = set()
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        call = call_tool(client, "portfolio_fee_peers", {"p_cnpjs": chunk, "p_as_of": as_of.isoformat()}, sec.errors)
        if not call.ok:
            failed.update(chunk)
        else:
            for row in call.rows:
                if row.get("cnpj") in chunk:
                    found[row["cnpj"]] = (row, call)
    fee_by = {f["line_no"]: f for f in fees.get("lines", [])}
    out = []
    covered = Decimal("0")
    fund_value = sum((li.position.valor for li in funds), Decimal("0"))
    eligible_nos = {li.line_no for li in eligible}
    for li in funds:
        rec = {"line_no": li.line_no, "cnpj": li.cnpj, "fund_name": li.name or li.position.linha_extrato,
               "position_value_brl": brl(li.position.valor), "status": "not_compared", "reason_code": None,
               "reason": None, "sources": [statement_source(li.line_no, li.position.data_posicao)],
               **{k: None for k in STATS}, "own_fee_pct_year": None}
        why = None
        if li.line_no not in eligible_nos:
            why = "tipo_fora_comparacao" if li.position.tipo != "fundo" or li.entity_type not in (None, "fi") else "sem_identificacao"
        elif li.cnpj in failed:
            why = "consulta_falhou"
        elif li.cnpj not in found:
            why = "sem_linha_comparacao"
        else:
            row, call = found[li.cnpj]
            rec.update({k: row.get(k) for k in ("classe_anbima", "fundo_cotas", "tp_fundo_classe", "fee_as_of",
                                              "comparison_as_of", "activity_from", "activity_to", "n_peers", "n_excluded",
                                              "peer_fee_oldest", "peer_fee_newest", *ETF_PEER_KEYS)})
            rec["sources"].append(call.src(row.get("fee_as_of")))
            h = (fee_by.get(li.line_no) or {}).get("headline") or {}
            own = dec(row.get("taxa_adm"))
            values = [dec(row.get(k)) for k in STATS[:4]]
            n = dec(row.get("n_peers"))
            fee_date = as_date(row.get("fee_as_of"))
            if row.get("status") != "compared":
                why = row.get("reason_code") if row.get("reason_code") in REASONS else "resposta_inconsistente"
            elif (n is None or n < 30 or n != n.to_integral_value() or own is None or not 0 < own <= 5
                  or any(x is None for x in values) or not 0 < values[0] <= values[1] <= values[2] <= 5
                  or not 0 <= values[3] <= 100 or row.get("comparison_as_of") != as_of.isoformat()
                  or not row.get("classe_anbima") or row.get("fundo_cotas") not in ("S", "N")
                  or row.get("tp_fundo_classe") not in ("FI", "CLASSES - FIF")
                  or fee_date is None or not oldest_fee_date <= fee_date <= as_of):
                why = "resposta_inconsistente"
            elif (h.get("origin") != "extrato" or h.get("kind") != "fixa" or h.get("stale")
                  or h.get("as_of") != row.get("fee_as_of") or dec(h.get("rate_pct_year")) != own):
                why = "fonte_taxa_diverge"
            else:
                rec.update(status="compared", own_fee_pct_year=ratio(own, 6),
                           **{k: ratio(dec(row[k]), 6) for k in STATS[:4]},
                           difference_pp=ratio(own - values[1], 6))
                covered += li.position.valor
        if why:
            rec.update(reason_code=why, reason=REASONS[why])
            sec.degrade("Há fundos não comparados; cada linha informa o motivo.", code=why)
        out.append(rec)
    if not funds:
        sec.status, sec.reason = "not_applicable", "Nenhuma linha de fundo na carteira."
    elif ids and set(ids) <= failed:
        sec.fail("Consulta de comparação de taxas falhou.", code="consulta_falhou")
    # Keep section text short regardless of the number of missing lines.
    if sec.status == "partial":
        sec.reason = "Há fundos não comparados; cada linha informa o motivo."
    return {**sec.head(), "as_of": as_of.isoformat(), "basis": BASIS, "lines": out,
            "n_compared": sum(r["status"] == "compared" for r in out),
            "n_not_compared": sum(r["status"] != "compared" for r in out),
            "compared_value_brl": brl(covered), "fund_value_brl": brl(fund_value),
            "coverage_fund_value_pct": pct(covered, fund_value),
            "coverage_portfolio_value_pct": pct(covered, portfolio_total)}
