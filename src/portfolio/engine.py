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

from src.portfolio.client import SiloClient, utc_now
from src.portfolio.common import add_months, brl, iso, month_start, statement_source
from src.portfolio.fees import compute_fees
from src.portfolio.identify import LineId, identify
from src.portfolio.indexer import compute_indexer
from src.portfolio.lookthrough import compute_lookthrough
from src.portfolio.restatements import compute_restatements
from src.portfolio.sector import compute_sector
from src.portfolio.signals import compute_signals
from src.portfolio.statement import Statement

log = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0"
ENGINE_VERSION = "0.1.0"
# Documented fixed lags until a coverage()-driven default exists (see engine-output.md).
CDA_LAG_MONTHS = 4
FEE_LAG_MONTHS = 1


@dataclass(frozen=True)
class EngineParams:
    cda_month: dt.date
    fee_month: dt.date
    max_depth: int = 5
    restatement_months: int = 12
    max_diff_docs: int = 5
    sector_top_tickers: int = 10

    def as_dict(self) -> dict[str, Any]:
        return {
            "cda_month": self.cda_month.isoformat(),
            "fee_month": self.fee_month.isoformat(),
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
        "id": "abnormal_movement",
        "text": "Movimento anormal e limiares de materialidade de reapresentação estão estacionados pelo dono.",
    },
]


def statement_section(stmt: Statement) -> dict[str, Any]:
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
        "positions": [
            {
                "line_no": p.line_no,
                "source_row": p.source_row,
                "linha_extrato": p.linha_extrato,
                "tipo": p.tipo,
                "codigo": p.codigo,
                "quantidade": float(p.quantidade) if p.quantidade is not None else None,
                "preco_unitario": float(p.preco_unitario) if p.preco_unitario is not None else None,
                "valor_brl": brl(p.valor),
                "pct_of_portfolio": float(round(p.valor / stmt.sum_of_lines * 100, 4)) if stmt.sum_of_lines else None,
                "data_posicao": iso(p.data_posicao),
                "source": statement_source(p.line_no, p.data_posicao),
            }
            for p in stmt.positions
        ],
    }


def run_engine(
    stmt: Statement,
    client: SiloClient,
    params: EngineParams | None = None,
    clock=utc_now,
) -> dict[str, Any]:
    params = params or default_params(stmt.position_date)
    log.info("engine start: %d lines, client=%s", len(stmt.positions), client.kind)

    ident, lines = identify(stmt, client)
    fees = compute_fees(lines, client, params.fee_month)
    look, exposures = compute_lookthrough(lines, client, params.cda_month, params.max_depth)
    unexplained = _unexplained_values(lines, look)
    indexer = compute_indexer(lines, exposures, unexplained)
    sector = compute_sector(
        lines, exposures, unexplained, client, stmt.position_date, top_tickers=params.sector_top_tickers
    )
    restatements = compute_restatements(
        lines, client, stmt.position_date, months=params.restatement_months, max_diff_docs=params.max_diff_docs
    )
    signals = compute_signals(lines, client)

    doc = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": clock().astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "engine": {"version": ENGINE_VERSION, "client": client.kind, "params": params.as_dict()},
        "statement": statement_section(stmt),
        "identification": ident,
        "fees": fees,
        "look_through": look,
        "indexer": indexer,
        "sector": sector,
        "restatements": restatements,
        "risk_signals": signals,
        "assumptions": ASSUMPTIONS,
        "section_status": {
            k: {"status": v["status"], "reason": v["reason"]}
            for k, v in (
                ("identification", ident),
                ("fees", fees),
                ("look_through", look),
                ("indexer", indexer),
                ("sector", sector),
                ("restatements", restatements),
                ("risk_signals", signals),
            )
        },
        "provenance": [e.as_dict() for e in client.provenance],
    }
    log.info("engine done: %d tool calls", len(client.provenance))
    return doc


def _unexplained_values(lines: list[LineId], look: dict[str, Any]) -> dict[int, Decimal]:
    out: dict[int, Decimal] = {}
    values = {li.line_no: li.position.valor for li in lines}
    for ln in look.get("lines", []):
        if ln.get("status") == "complete" and ln.get("unexplained_weight") is not None:
            out[ln["line_no"]] = values[ln["line_no"]] * Decimal(str(ln["unexplained_weight"]))
    return out


def dumps(doc: dict[str, Any]) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
