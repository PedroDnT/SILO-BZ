"""Block 3: fees.

Tool ``portfolio_fees(p_cnpjs, p_month)``, one batched call (one row per fund).

The rule, from the owner: the fee must be CORRECT.

* A disclosed fee (CVM registry, later the lâmina) wins. R$ per year = position
  value x rate.
* A balancete estimate is shown only as ``estimativa a partir do balancete``,
  never as the disclosed fee, and never when ``fiscal_reset_suspect`` is true
  (the month's flow crosses the fund's fiscal-year reset and reads wrong).
* The performance fee is a share of the EXCESS return over a benchmark, so
  position x rate is wrong for it: no R$ figure comes from the disclosed
  performance rate. A R$ figure for performance exists only from the balancete
  estimate, labelled.
* A fund with neither is ``taxa desconhecida``, with the reason.

Assumption (recorded in the output): ``disclosed_taxa_adm`` and
``adm_fee_pct_annual_est`` are read as percent per year. CVM's metadata states
no unit for TAXA_ADM (migration 64).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from src.portfolio.client import SiloClient
from src.portfolio.common import (
    STATUS_NOT_APPLICABLE,
    Section,
    brl,
    call_tool,
    dec,
    pct,
    ratio,
    source,
    statement_source,
)
from src.portfolio.identify import LineId

ESTIMATE_LABEL = "estimativa a partir do balancete"
UNKNOWN_FEE = "taxa desconhecida"
FEE_TIPOS = ("fundo", "FIDC", "FII", "ETF")


def compute_fees(lines: list[LineId], client: SiloClient, fee_month: dt.date) -> dict[str, Any]:
    sec = Section()
    fund_lines = [li for li in lines if li.kind == "fund" and li.cnpj and li.position.tipo in FEE_TIPOS]
    out_lines: list[dict[str, Any]] = []
    if not fund_lines:
        sec.status = STATUS_NOT_APPLICABLE
        sec.reason = "Nenhuma linha de fundo identificada."
        return {**sec.head(), "month": fee_month.isoformat(), "lines": [], "totals": _totals([], Decimal("0"))}

    cnpjs = sorted({li.cnpj for li in fund_lines if li.cnpj})
    args = {"p_cnpjs": cnpjs, "p_month": fee_month.isoformat()}
    res = call_tool(client, "portfolio_fees", args, sec.errors)
    rows_by_cnpj: dict[str, dict] = {}
    if res.ok:
        rows_by_cnpj = {str(r.get("cnpj")): r for r in res.rows or []}
    else:
        sec.fail("portfolio_fees falhou (erro literal em errors); nenhuma taxa pôde ser calculada.")

    for li in fund_lines:
        out_lines.append(_line_fee(li, rows_by_cnpj.get(li.cnpj or ""), res, fee_month))

    total_value = sum((li.position.valor for li in fund_lines), Decimal("0"))
    if sec.status != "unknown":
        unknown = [o for o in out_lines if o["fee_status"] == UNKNOWN_FEE]
        if unknown:
            sec.degrade(f"{len(unknown)} fundo(s) com taxa desconhecida.")
    return {
        **sec.head(),
        "month": fee_month.isoformat(),
        "estimate_label": ESTIMATE_LABEL,
        "lines": out_lines,
        "totals": _totals(out_lines, total_value),
    }


def _line_fee(li: LineId, row: dict | None, res, fee_month: dt.date) -> dict[str, Any]:
    p = li.position
    base: dict[str, Any] = {
        "line_no": li.line_no,
        "cnpj": li.cnpj,
        "fund_name": li.name,
        "position_value_brl": brl(p.valor),
        "position_value_source": statement_source(p.line_no, p.data_posicao),
    }
    if not res.ok:
        return {
            **base,
            "fee_status": UNKNOWN_FEE,
            "reason": "portfolio_fees falhou; erro literal em errors da seção.",
            "adm": None,
            "perf": None,
            "total_per_year_brl": None,
        }
    if row is None:
        return {
            **base,
            "fee_status": UNKNOWN_FEE,
            "reason": (
                "portfolio_fees não devolveu linha para este CNPJ no mês: sem balancete resumido (FIDC, FII e "
                "ETF não o entregam) e sem taxa divulgada no cadastro."
            ),
            "adm": None,
            "perf": None,
            "total_per_year_brl": None,
        }

    src = source("portfolio_fees", res.call_id, res.args, row.get("month") or fee_month)
    disclosed_adm = dec(row.get("disclosed_taxa_adm"))
    disclosed_perf = dec(row.get("disclosed_taxa_perfm"))
    est_adm = dec(row.get("adm_fee_pct_annual_est"))
    est_perf = dec(row.get("perf_fee_pct_annual_est"))
    suspect = bool(row.get("fiscal_reset_suspect"))
    nav = dec(row.get("nav"))
    estimate_ok = not suspect

    adm: dict[str, Any]
    if disclosed_adm is not None:
        adm = {
            "basis": "divulgada",
            "rate_pct_per_year": ratio(disclosed_adm, 4),
            "per_year_brl": brl(p.valor * disclosed_adm / 100),
            "disclosed_source": row.get("disclosed_source"),
            "disclosed_as_of": row.get("disclosed_as_of"),
            "sources": [src],
        }
    elif est_adm is not None and estimate_ok:
        adm = {
            "basis": ESTIMATE_LABEL,
            "rate_pct_per_year": ratio(est_adm, 4),
            "per_year_brl": brl(p.valor * est_adm / 100),
            "label": row.get("estimate_label") or ESTIMATE_LABEL,
            "sources": [src],
        }
    else:
        adm = {
            "basis": UNKNOWN_FEE,
            "reason": _unknown_reason(est_adm, suspect, "administração"),
            "rate_pct_per_year": None,
            "per_year_brl": None,
            "sources": [src],
        }

    perf: dict[str, Any] = {"disclosed": None, "estimate": None}
    if disclosed_perf is not None:
        perf["disclosed"] = {
            "basis": "divulgada",
            "rate_as_filed": ratio(disclosed_perf, 4),
            "meaning": (
                "Taxa de performance divulgada: percentual sobre o excedente da rentabilidade acima do "
                "referencial do regulamento. Não é percentual do patrimônio; o SILO não converte em R$."
            ),
            "per_year_brl": None,
            "disclosed_source": row.get("disclosed_source"),
            "disclosed_as_of": row.get("disclosed_as_of"),
            "sources": [src],
        }
    if est_perf is not None and estimate_ok:
        perf["estimate"] = {
            "basis": ESTIMATE_LABEL,
            "rate_pct_per_year": ratio(est_perf, 4),
            "per_year_brl": brl(p.valor * est_perf / 100),
            "label": row.get("estimate_label") or ESTIMATE_LABEL,
            "sources": [src],
        }
    elif est_perf is not None:
        perf["estimate"] = {
            "basis": UNKNOWN_FEE,
            "reason": _unknown_reason(est_perf, suspect, "performance"),
            "sources": [src],
        }

    per_year = [
        v
        for v in (
            adm.get("per_year_brl"),
            (perf.get("estimate") or {}).get("per_year_brl"),
        )
        if v is not None
    ]
    status = adm["basis"] if adm["basis"] != UNKNOWN_FEE else UNKNOWN_FEE
    out = {
        **base,
        "fee_status": status,
        "reason": adm.get("reason"),
        "fund_nav_brl": brl(nav),
        "fiscal_reset_suspect": suspect,
        "adm": adm,
        "perf": perf,
        "total_per_year_brl": round(sum(per_year), 2) if per_year else None,
        "total_per_year_note": (
            "Soma da taxa de administração e da estimativa de performance, quando existem; "
            "a taxa de performance divulgada não entra (não é % do patrimônio)."
        ),
    }
    return out


def _unknown_reason(est: Decimal | None, suspect: bool, which: str) -> str:
    if suspect:
        return (
            f"Sem taxa de {which} divulgada; a estimativa do balancete foi descartada porque o mês cruza o "
            "reinício do exercício fiscal do fundo (fiscal_reset_suspect)."
        )
    if est is None:
        return f"Sem taxa de {which} divulgada e sem estimativa do balancete para o mês."
    return f"Sem taxa de {which} utilizável."


def _totals(lines: list[dict], covered_value: Decimal) -> dict[str, Any]:
    disclosed = Decimal("0")
    estimated = Decimal("0")
    perf_est = Decimal("0")
    value_known = Decimal("0")
    unknown_value = Decimal("0")
    for o in lines:
        v = dec(o["position_value_brl"]) or Decimal("0")
        adm = o.get("adm") or {}
        if adm.get("basis") == "divulgada":
            disclosed += dec(adm.get("per_year_brl")) or Decimal("0")
            value_known += v
        elif adm.get("basis") == ESTIMATE_LABEL:
            estimated += dec(adm.get("per_year_brl")) or Decimal("0")
            value_known += v
        else:
            unknown_value += v
        pe = (o.get("perf") or {}).get("estimate") or {}
        if pe.get("basis") == ESTIMATE_LABEL:
            perf_est += dec(pe.get("per_year_brl")) or Decimal("0")
    total = disclosed + estimated + perf_est
    return {
        "adm_disclosed_per_year_brl": brl(disclosed),
        "adm_estimated_per_year_brl": brl(estimated),
        "perf_estimated_per_year_brl": brl(perf_est),
        "total_per_year_brl": brl(total),
        "total_note": (
            f"Soma só dos fundos com taxa conhecida; a parte divulgada e a parte {ESTIMATE_LABEL} "
            "ficam separadas."
        ),
        "fund_value_brl": brl(covered_value),
        "fund_value_with_known_fee_brl": brl(value_known),
        "fund_value_with_unknown_fee_brl": brl(unknown_value),
        "pct_of_fund_value_with_known_fee": pct(value_known, covered_value) if covered_value else None,
    }
