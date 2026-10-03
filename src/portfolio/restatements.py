"""Block 4: restated filings of FIDC and FII positions.

Tools ``fund_restatements`` (one call per fund) and ``fund_restatement_diff``
(one call per restated document, because a single restatement can change over
a hundred leaves and the diff refuses above one 1,000-row page).

The materiality thresholds are PARKED by the owner: no judgement is made. Every
changed leaf is reported as ``reapresentado, não avaliado`` with the field, the
old and new values, both FNET ids and both delivery dates.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from src.portfolio.client import SiloClient
from src.portfolio.common import STATUS_NOT_APPLICABLE, Section, add_months, call_tool, dec, ratio
from src.portfolio.identify import LineId

NOT_ASSESSED = "reapresentado, não avaliado"
RESTATEMENT_TIPOS = ("FIDC", "FII")


def compute_restatements(
    lines: list[LineId], client: SiloClient, pos_date: dt.date, months: int = 12, max_diff_docs: int = 5
) -> dict[str, Any]:
    sec = Section()
    targets = [li for li in lines if li.kind == "fund" and li.cnpj and li.position.tipo in RESTATEMENT_TIPOS]
    if not targets:
        sec.status = STATUS_NOT_APPLICABLE
        sec.reason = "Nenhuma posição FIDC ou FII identificada."
        return {**sec.head(), "lines": [], "assessment": "thresholds parked by the owner"}

    p_from = add_months(pos_date.replace(day=1), -months).isoformat()
    p_to = pos_date.isoformat()
    out: list[dict[str, Any]] = []
    failed = 0
    for li in targets:
        args = {"p_cnpj": li.cnpj, "p_from": p_from, "p_to": p_to}
        rr = call_tool(client, "fund_restatements", args, sec.errors)
        if not rr.ok:
            failed += 1
            out.append(
                {
                    "line_no": li.line_no,
                    "cnpj": li.cnpj,
                    "status": "unknown",
                    "reason": "fund_restatements falhou (erro literal em errors da seção).",
                    "restatements": [],
                }
            )
            continue
        docs = sorted(rr.rows or [], key=lambda r: str(r.get("delivered_at") or ""), reverse=True)
        entries: list[dict[str, Any]] = []
        n_diff_calls = 0
        for d in docs:
            entry: dict[str, Any] = {
                "fnet_id": d.get("fnet_id"),
                "previous_fnet_id": d.get("previous_fnet_id"),
                "tipo_documento": d.get("tipo_documento"),
                "tipo_documento": d.get("tipo_documento"),
                "reference": d.get("reference_raw"),
                "reference_date": d.get("reference_date"),
                "reference_date": d.get("reference_date"),
                "versao": d.get("versao"),
                "modalidade": d.get("modalidade"),
                "delivered_at": d.get("delivered_at"),
                "previous_delivered_at": d.get("previous_delivered_at"),
                "lag_days": d.get("lag_days"),
                "n_fields_changed": d.get("n_fields_changed"),
                "diff_status": d.get("diff_status"),
                "assessment": NOT_ASSESSED,
                "leaves": [],
                "sources": [rr.src(d.get("reference_date"))],
            }
            if d.get("diff_status") != "compared":
                entry["diff_note"] = (
                    f"Diff indisponível (diff_status = {d.get('diff_status')!r}): o documento foi reapresentado, "
                    "mas o SILO não comparou os campos."
                )
            elif n_diff_calls >= max_diff_docs:
                entry["diff_note"] = (
                    f"Diff não buscado: limite de {max_diff_docs} documentos por fundo (os mais recentes foram buscados)."
                )
                sec.degrade(f"fundo da linha {li.line_no}: diff buscado só para {max_diff_docs} documentos.")
            else:
                n_diff_calls += 1
                dargs = {"p_cnpj": li.cnpj, "p_fnet_id": d.get("fnet_id")}
                dr = call_tool(client, "fund_restatement_diff", dargs, sec.errors)
                if not dr.ok:
                    entry["diff_note"] = "fund_restatement_diff falhou (erro literal em errors da seção)."
                    sec.degrade(f"diff do documento {d.get('fnet_id')} falhou.")
                else:
                    entry["leaves"] = [_leaf(x) for x in dr.rows or []]
                    entry["n_leaves"] = len(entry["leaves"])
                    entry["leaves_complete"] = entry["n_leaves"] == d.get("n_fields_changed")
                    entry["sources"].append(dr.src(d.get("reference_date")))
            entries.append(entry)
        out.append(
            {
                "line_no": li.line_no,
                "cnpj": li.cnpj,
                "status": "complete" if entries else "none_found",
                "reason": None if entries else f"Nenhuma reapresentação entre {p_from} e {p_to}.",
                "n_restatements": len(entries),
                "restatements": entries,
            }
        )
    if failed == len(targets):
        sec.fail("fund_restatements falhou para todos os fundos.")
    elif failed:
        sec.degrade(f"fund_restatements falhou para {failed} fundo(s).")
    return {
        **sec.head(),
        "window": {"from": p_from, "to": p_to},
        "assessment": "Limiares de materialidade estacionados pelo dono: nenhum julgamento; tudo é 'reapresentado, não avaliado'.",
        "max_diff_docs_per_fund": max_diff_docs,
        "lines": out,
    }


def _leaf(x: dict) -> dict[str, Any]:
    return {
        "field_path": x.get("field_path"),
        "block": x.get("block"),
        "leaf": x.get("leaf"),
        "change_kind": x.get("change_kind"),
        "old_value": x.get("old_value"),
        "new_value": x.get("new_value"),
        "old_num": ratio(dec(x.get("old_num")), 6),
        "new_num": ratio(dec(x.get("new_num")), 6),
        "delta": ratio(dec(x.get("delta")), 6),
        "match_basis": x.get("match_basis"),
        "fnet_id": x.get("fnet_id"),
        "previous_fnet_id": x.get("previous_fnet_id"),
        "delivered_at": x.get("delivered_at"),
        "previous_delivered_at": x.get("previous_delivered_at"),
        "source_url": x.get("source_url"),
        "assessment": NOT_ASSESSED,
    }
