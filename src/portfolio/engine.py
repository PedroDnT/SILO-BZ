"""The diagnosis engine: masked statement + one SiloClient -> one JSON document.

Every number comes from this code and the SILO tools, never from an LLM. The
document schema is ``docs/reference/portfolio/engine-output.md`` and is
append-only within a ``schema_version``: keys are added, never renamed or
removed, so the report writer can build against the fixture
``tests/fixtures/portfolio/demo_engine_output.json``.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.portfolio.allocation import compute_allocation
from src.portfolio.client import SiloClient, utc_now
from src.portfolio.common import add_months, brl, iso, month_start, statement_source
from src.portfolio.concentration import compute_concentration
from src.portfolio.consolidate import merge_same_identity
from src.portfolio.fees import compute_fees, summarize
from src.portfolio.identify import LineId, identify
from src.portfolio.indexer import compute_indexer
from src.portfolio.liquidity import compute_liquidity
from src.portfolio.lookthrough import add_portfolio_shares, compute_lookthrough
from src.portfolio.movement import compute_movement, default_movement_month
from src.portfolio.restatements import compute_restatements
from src.portfolio.risks import compute_risks
from src.portfolio.sector import compute_sector
from src.portfolio.signals import compute_signals
from src.portfolio.statement import Position, Statement
from src.portfolio.terms import attach_to_identification, fetch_fund_terms

log = logging.getLogger(__name__)

SCHEMA_VERSION = "1.9"
ENGINE_VERSION = "0.1.0"
# Documented fixed lags until a coverage()-driven default exists (see engine-output.md).
CDA_LAG_MONTHS = 4
FEE_LAG_MONTHS = 1


@dataclass(frozen=True)
class EngineParams:
    cda_month: dt.date
    fee_month: dt.date
    movement_month: dt.date
    max_depth: int = 4
    restatement_months: int = 12
    max_diff_docs: int = 5
    sector_top_tickers: int = 10

    def as_dict(self) -> dict[str, Any]:
        return {
            "cda_month": self.cda_month.isoformat(),
            "fee_month": self.fee_month.isoformat(),
            "movement_month": self.movement_month.isoformat(),
            "max_depth": self.max_depth,
            "restatement_months": self.restatement_months,
            "max_diff_docs_per_fund": self.max_diff_docs,
            "sector_lookthrough_top_tickers": self.sector_top_tickers,
            "cda_lag_months_default": CDA_LAG_MONTHS,
            "fee_lag_months_default": FEE_LAG_MONTHS,
        }


def default_params(position_date: dt.date, **overrides: Any) -> EngineParams:
    base = month_start(position_date)
    p = {
        "cda_month": add_months(base, -CDA_LAG_MONTHS),
        "fee_month": add_months(base, -FEE_LAG_MONTHS),
        "movement_month": default_movement_month(position_date),
    }
    p.update({k: v for k, v in overrides.items() if v is not None})
    return EngineParams(**p)


ASSUMPTIONS = [
    {
        "id": "fee_units",
        "text": (
            "disclosed_taxa_adm e adm_fee_pct_annual_est são lidos como percentual ao ano. A CVM não declara "
            "unidade para TAXA_ADM (migration 64); a leitura como % a.a. não foi verificada contra a lâmina."
        ),
    },
    {
        "id": "weight_in_root",
        "text": (
            "weight_in_root de portfolio_lookthrough é lido como fração (0 a 1) do valor do fundo raiz, já "
            "composta ao longo do caminho; exposição em R$ = valor da posição x weight_in_root."
        ),
    },
    {
        "id": "position_date",
        "text": (
            "A data de referência é a mais recente das linhas; a cota enviada ao resolvedor usa a data de cada "
            "linha. A CDA e o balancete usam o mês de defasagem fixa de EngineParams, não o mês da posição."
        ),
    },
    {
        "id": "valuation",
        "text": "O valor de cada posição é o do extrato; cotações do SILO são de referência e nunca reavaliam a linha.",
    },
    {
        "id": "direct_tesouro",
        "text": "O SILO não tem série de preços do Tesouro: a posição em título direto vale o que o extrato diz.",
    },
    {
        "id": "economic_group",
        "text": "Grupo econômico não é avaliado; a sobreposição de emissor usa raiz de CNPJ e código de emissor da B3.",
    },
    {
        "id": "concentration",
        "text": (
            "Concentração e vencimentos (esquema 1.7) somam só valores do extrato. O emissor é o nome impresso na linha, "
            "sem o tipo e o código do registro; não é grupo econômico. O teste do FGC soma CDB, LCI e LCA por emissor "
            "impresso e fica a conferir: o limite é por CPF e instituição, e o extrato pode ter mais de um titular."
        ),
    },
    {
        "id": "risks",
        "text": (
            "Principais riscos (esquema 1.8): cada linha lê um campo de outra seção, ou uma soma de valores do extrato, "
            "contra limites fixos do código (src/portfolio/risks.py); o semáforo é atenção, moderado ou baixo. O crédito "
            "sem cobertura do FGC supõe um só titular e trata o emissor impresso como a instituição: fica a conferir."
        ),
    },
    {
        "id": "credit_registry",
        "text": (
            "Crédito direto (esquema 1.9): CRA e CRI são procurados pelo código exato no registro da CVM, e a série é a "
            "de vencimento igual ao do extrato (senão a única, senão a de menor número, marcada 'vencimento diverge'); "
            "debêntures, pelo código nas carteiras dos fundos (CDA bloco 4). O emissor continua o impresso no extrato. "
            "A marcação dos fundos é a média ponderada da CDA, em outra data: a diferença para o preço do extrato é "
            "informativa, não um veredito de preço."
        ),
    },
    {
        "id": "fund_terms",
        "text": (
            "Gestora e prazos de resgate (esquema 1.9): como arquivados no Extrato da CVM ou na lâmina. A concentração por "
            "gestora agrupa pelo identificador arquivado, nunca pelo nome. O prazo de pagamento do resgate é lido como "
            "arquivado, sem converter dias úteis e corridos; carência acima de zero é lock-up; um prazo não informado "
            "nunca é lido como zero."
        ),
    },
    {
        "id": "abnormal_movement",
        "text": (
            "Movimento incomum (esquema 1.3): o retorno mensal da cota do fundo é comparado com o da sua classe ANBIMA "
            "conforme arquivada no Extrato da CVM, nos limiares do dono (atenção acima de 2 desvios padrão, só em tabela; "
            "forte acima de 3, no texto). Os limiares de materialidade de reapresentação seguem estacionados pelo dono."
        ),
    },
    {
        "id": "movement_class",
        "text": (
            "A classe do movimento é a do arquivo mais recente do Extrato da CVM, não a classe vigente na data do mês; o "
            "Extrato cobre cerca de 84% dos fundos FI ativos, e fundo fora dele ou sem classe informada é 'não avaliado'. "
            "Sem classe mais ampla de reserva: classe com menos de 30 fundos com retorno no mês também é 'não avaliado'."
        ),
    },
]


def _position_dict(p: Position, total: Decimal) -> dict[str, Any]:
    return {
        "line_no": p.line_no,
        "source_row": p.source_row,
        "linha_extrato": p.linha_extrato,
        "tipo": p.tipo,
        "codigo": p.codigo,
        "quantidade": float(p.quantidade) if p.quantidade is not None else None,
        "preco_unitario": float(p.preco_unitario) if p.preco_unitario is not None else None,
        "preco_implicito": p.preco_implicito,
        "valor_brl": brl(p.valor),
        "portfolio_pct": float(round(p.valor / total * 100, 4)) if total else None,
        "data_posicao": iso(p.data_posicao),
        "vencimento": iso(p.vencimento),
        "taxa_texto": p.taxa_texto,
        "estrategia_corretora": p.estrategia_corretora,
        "classe_corretora": p.classe_corretora,
        "conta_ref": p.conta_ref,
        "contas": [
            {
                "conta_ref": c.conta_ref,
                "titular_ref": c.titular_ref,
                "source_row": c.source_row,
                "linha_extrato": c.linha_extrato,
                "quantidade": float(c.quantidade) if c.quantidade is not None else None,
                "preco_unitario": float(c.preco_unitario) if c.preco_unitario is not None else None,
                "valor_brl": brl(c.valor),
                "data_posicao": iso(c.data_posicao),
            }
            for c in p.contas
        ],
        "source": statement_source(p.line_no, p.data_posicao),
        "fonte_texto": p.fonte_texto,
        "codigo_conferido": p.codigo_conferido,
        "taxa_conferida": p.taxa_conferida,
        "ajustes_ocr": list(p.ajustes_ocr),
    }


def statement_section(stmt: Statement) -> dict[str, Any]:
    total = stmt.sum_of_lines
    return {
        "holder": stmt.holder.as_dict(),
        "corretora": stmt.corretora,
        "source_format": stmt.source_format,
        "stated_total_brl": brl(stmt.stated_total),
        "sum_of_lines_brl": brl(stmt.sum_of_lines),
        "difference_brl": brl(stmt.sum_of_lines - stmt.stated_total),
        "tolerance_brl": brl(stmt.tolerance),
        "reconciled": True,
        "n_lines": len(stmt.positions),
        "position_date": iso(stmt.position_date),
        "position_dates": [iso(d) for d in stmt.position_dates],
        "notes": list(stmt.notes),
        "positions": [_position_dict(p, total) for p in stmt.positions],
        "consolidated": bool(stmt.accounts),
        "accounts": [
            {
                "conta_ref": a.conta_ref,
                "titular_ref": a.titular_ref,
                "n_lines": a.n_lines,
                "stated_total_brl": brl(a.stated_total),
                "sum_of_lines_brl": brl(a.sum_of_lines),
                "position_date": iso(a.position_date),
                "source_format": a.source_format,
                "positions": [_position_dict(p, a.sum_of_lines) for p in a.positions],
            }
            for a in stmt.accounts
        ],
    }


def run_engine(
    stmt: Statement,
    client: SiloClient,
    params: EngineParams | None = None,
    clock=utc_now,
) -> dict[str, Any]:
    params = params or default_params(stmt.position_date)
    n_read = len(stmt.positions)
    stmt, n_merged = merge_same_identity(stmt)  # engine 1.7: one asset listed on several lines is one position
    log.info("engine start: %d lines (%d read), client=%s", len(stmt.positions), n_read, client.kind)

    ident, lines = identify(stmt, client)
    terms = fetch_fund_terms(lines, client)  # engine 1.9: managers and redemption terms, one batch
    attach_to_identification(ident, terms)
    look, exposures = compute_lookthrough(lines, client, params.cda_month, params.max_depth)
    add_portfolio_shares(look, exposures, stmt.sum_of_lines)
    fund_nodes = {ln["line_no"]: ln.get("fund_nodes", []) for ln in look["lines"]}
    fees = compute_fees(lines, client, params.fee_month, fund_nodes)
    _fee_totals_as_portfolio_pct(fees, stmt.sum_of_lines)
    unexplained = _unexplained_values(lines, look)
    indexer = compute_indexer(lines, exposures, unexplained)
    sector = compute_sector(
        lines, exposures, unexplained, client, stmt.position_date, top_tickers=params.sector_top_tickers
    )
    restatements = compute_restatements(
        lines, client, stmt.position_date, months=params.restatement_months, max_diff_docs=params.max_diff_docs
    )
    signals = compute_signals(lines, client)
    movement = compute_movement(lines, client, params.movement_month)
    liquidity = compute_liquidity(lines, terms)  # engine 1.9
    concentration = compute_concentration(lines, stmt.position_date, terms, liquidity)
    allocation = compute_allocation(lines)  # engine 1.8
    fees["summary"] = summarize(fees, stmt.sum_of_lines, concentration.get("issuer"))  # engine 1.8

    doc = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": clock().astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "engine": {"version": ENGINE_VERSION, "client": client.kind, "params": params.as_dict()},
        "statement": {**statement_section(stmt), "n_lines_read": n_read, "n_positions_merged": n_merged},
        "identification": ident,
        "fees": fees,
        "look_through": look,
        "indexer": indexer,
        "sector": sector,
        "restatements": restatements,
        "risk_signals": signals,
        "movement": movement,
        "concentration": concentration,
        "allocation": allocation,
        "liquidity": liquidity,
        "assumptions": ASSUMPTIONS,
        "section_status": {
            k: {"status": v["status"], "reason": v["reason"], "reason_codes": list(v.get("reason_codes") or [])}
            for k, v in (
                ("identification", ident),
                ("fees", fees),
                ("look_through", look),
                ("indexer", indexer),
                ("sector", sector),
                ("restatements", restatements),
                ("risk_signals", signals),
                ("movement", movement),
                ("concentration", concentration),
                ("allocation", allocation),
                ("liquidity", liquidity),
            )
        },
        "provenance": [{**e.as_dict(), "id": f"p{e.call_id}"} for e in client.provenance],
    }
    # engine 1.8: the main risks read the sections above, so they are built last and placed after them
    risks = compute_risks(doc)
    doc = _insert_after(doc, "liquidity", "risks", risks)
    doc["section_status"]["risks"] = {"status": risks["status"], "reason": risks["reason"],
                                      "reason_codes": list(risks.get("reason_codes") or [])}
    log.info("engine done: %d tool calls", len(client.provenance))
    return doc


def _fee_totals_as_portfolio_pct(fees: dict[str, Any], total: Decimal) -> None:
    """Totals as a percent of the whole portfolio (kept apart: disclosed and estimate are never combined)."""
    t = fees["totals"]
    for src, dst in (("adm_disclosed_fixed_per_year_brl", "adm_disclosed_fixed_portfolio_pct"),
                     ("adm_etf_site_per_year_brl", "adm_etf_site_portfolio_pct"),
                     ("adm_fee_per_year_brl", "adm_fee_portfolio_pct"),
                     ("adm_disclosed_range_low_per_year_brl", "adm_disclosed_range_low_portfolio_pct"),  # engine 1.8
                     ("adm_disclosed_range_high_per_year_brl", "adm_disclosed_range_high_portfolio_pct"),
                     ("estimate_adm_per_year_brl", "estimate_adm_portfolio_pct")):
        t[dst] = float((Decimal(str(t[src])) / total * 100).quantize(Decimal("0.0001"))) if total else None


def _insert_after(doc: dict[str, Any], after: str, key: str, value: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in doc.items():
        out[k] = v
        if k == after:
            out[key] = value
    return out


def _unexplained_values(lines: list[LineId], look: dict[str, Any]) -> dict[int, Decimal]:
    out: dict[int, Decimal] = {}
    values = {li.line_no: li.position.valor for li in lines}
    for ln in look.get("lines", []):
        if ln.get("status") == "complete" and ln.get("unexplained_weight") is not None:
            out[ln["line_no"]] = values[ln["line_no"]] * Decimal(str(ln["unexplained_weight"]))
    return out


def dumps(doc: dict[str, Any]) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
