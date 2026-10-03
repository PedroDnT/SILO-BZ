"""Block 3: fees.

Tool ``portfolio_fees(p_cnpjs, p_month)``: one batched call for the statement's funds and
one for the funds they hold (the look-through's fund nodes). The owner insists the fee
be CORRECT, so the rules are these:

1. The headline is the DISCLOSED administration fee as filed, % a year. The tool picks ONE
   source per fund, in this order, and names it in ``disclosed_origin``: the CVM Extrato
   (``extrato``, ``cvm_fi_extrato``), the lâmina (``lamina``, newest reference month),
   CVM's cad_fi (``cad_fi``). When nothing is disclosed the line says ``taxa divulgada
   não encontrada`` and the estimate is NEVER substituted for it. The provenance sentence
   follows ``disclosed_origin`` (an Extrato fee is not a cad_fi fee).
   A filed 0 is ``valor 0 informado (provavelmente não preenchido)``: shown, never counted
   as a zero cost and never summed. A filed value above 5 % a.a. (or below 0) is ``valor
   implausível descartado``: not the fee, the raw value kept in its own field.
2. The balancete estimate is its own field, always labelled ``estimativa, não
   divulgada``, with its method, beside the disclosed fee or alone. It is never averaged
   with the disclosed fee and never presented as the fee. In the fiscal-year reset month
   the tool returns no estimate; none is made up here.
3. ``PR_PL_DESPESA`` (the declared total expense ratio) is a separate field with its
   period, never added to the fee. ``portfolio_fees`` does not return it yet, so the field
   is present, empty, and says why.
4. The filing date and age are always output; ``defasada`` when older than 36 months for
   the Extrato (age does not predict error there) and 24 for the lâmina. For cad_fi the date
   is the day SILO read the row, not a filing date, and no age is claimed. An Extrato row is
   a class fee for a CVM 175 class (``taxa da classe``): no subclass fee is assumed.
5. A disclosed 0 is a disclosed 0 (never a missing fee), plus a finding when the
   balancete shows a clear expense. When there is no single value but a min and max, the
   range is output as filed. A finding (attention level) is raised when the estimate
   differs from a fixed disclosed fee by more than max(0.25 p.p. a.a., 25 % of it).
6. The performance fee is text in the source: passed through verbatim, never parsed, and
   never converted to R$ (it is a share of the excess return, not of the NAV). The Extrato's
   other terms (performance parameters and method, entry and exit fees, custody fee) are
   output as filed, with no reading.
7. A feeder's fee is never added to its master's: every fund keeps its own. The funds a
   fund holds appear under ``underlying`` with their own fees, labelled ``não somada``.

Assumption, recorded in the output: ``disclosed_taxa_adm`` and the estimate are read as
percent per year. CVM's metadata states no unit for TAXA_ADM (migration 64).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from src.portfolio.client import SiloClient
from src.portfolio.common import (
    STATUS_NOT_APPLICABLE,
    Call,
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

ESTIMATE_LABEL = "estimativa, não divulgada"
NOT_FOUND = "taxa divulgada não encontrada"
NOT_ADDED = "não somada"
FEE_TIPOS = ("fundo", "FIDC", "FII", "ETF")
STALE_MONTHS = 24  # lâmina; the schema's historical top-level key
STALE_MONTHS_BY_ORIGIN = {"extrato": 36, "lamina": 24, "cad_fi": None}
ORIGIN_FROM_SOURCE = {"cvm_fi_extrato": "extrato", "cvm_fi_lamina": "lamina", "cvm_fund_registry (cad_fi)": "cad_fi"}
ORIGIN_LABEL = {"extrato": "Extrato CVM", "lamina": "lâmina CVM", "cad_fi": "cadastro cad_fi da CVM"}
ZERO_LABEL = "valor 0 informado (provavelmente não preenchido)"
IMPLAUSIBLE_LABEL = "valor implausível descartado"
IMPLAUSIBLE_ABOVE_PCT = Decimal("5")
EXPENSE_RATIO_NOTE = (
    "Total de despesas declarado na lâmina (PR_PL_DESPESA, % do patrimônio médio no período indicado): "
    "campo à parte, nunca somado à taxa de administração."
)
EXPENSE_RATIO_MISSING = "Sem total de despesas declarado na lâmina para este fundo."
# 'clearly above zero' for the finding on a disclosed zero (percent a year of the estimate)
CLEARLY_ABOVE_ZERO_PCT = Decimal("0.05")
DIFF_ABS_PCT = Decimal("0.25")
DIFF_REL = Decimal("0.25")
CHUNK = 200


def _fetch(client: SiloClient, cnpjs: list[str], month: dt.date, errors: list[dict]) -> tuple[dict[str, dict], list[Call]]:
    rows: dict[str, dict] = {}
    calls: list[Call] = []
    for i in range(0, len(cnpjs), CHUNK):
        chunk = cnpjs[i : i + CHUNK]
        res = call_tool(client, "portfolio_fees", {"p_cnpjs": chunk, "p_month": month.isoformat()}, errors)
        calls.append(res)
        if res.ok:
            for r in res.rows or []:
                rows[str(r.get("cnpj"))] = {"row": r, "call": res}
    return rows, calls


def compute_fees(
    lines: list[LineId],
    client: SiloClient,
    fee_month: dt.date,
    fund_nodes: dict[int, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    sec = Section()
    fund_lines = [li for li in lines if li.kind == "fund" and li.cnpj and li.position.tipo in FEE_TIPOS]
    if not fund_lines:
        sec.status = STATUS_NOT_APPLICABLE
        sec.reason = "Nenhuma linha de fundo identificada."
        return {**sec.head(), "month": fee_month.isoformat(), "lines": [], "underlying": [], "totals": _totals([])}

    cnpjs = sorted({li.cnpj for li in fund_lines if li.cnpj})
    found, calls = _fetch(client, cnpjs, fee_month, sec.errors)
    failed_calls = [c for c in calls if not c.ok]
    if failed_calls and len(failed_calls) == len(calls):
        sec.fail("portfolio_fees falhou (erro literal em errors); nenhuma taxa pôde ser calculada.")
    elif failed_calls:
        sec.degrade("portfolio_fees falhou para parte dos fundos (erro literal em errors).")

    out_lines = []
    for li in fund_lines:
        entry = found.get(li.cnpj or "")
        base = {
            "line_no": li.line_no,
            "cnpj": li.cnpj,
            "fund_name": li.name,
            "position_value_brl": brl(li.position.valor),
            "position_value_source": statement_source(li.position.line_no, li.position.data_posicao),
        }
        if entry is None:
            reason = (
                "portfolio_fees falhou para este fundo (erro literal em errors da seção)."
                if failed_calls
                else "portfolio_fees não devolveu linha para este CNPJ."
            )
            out_lines.append({**base, "fee_status": NOT_FOUND, "reason": reason, **_empty_fee()})
            continue
        out_lines.append({**base, **_fee_record(entry["row"], li.position.valor, entry["call"], fee_month)})

    underlying = _underlying(fund_nodes or {}, client, fee_month, sec)
    unknown = [o for o in out_lines if o["fee_status"] == NOT_FOUND]
    unusable = [o for o in out_lines if o["fee_status"] in (ZERO_LABEL, IMPLAUSIBLE_LABEL)]
    if unknown and sec.status != "unknown":
        sec.degrade(f"{len(unknown)} fundo(s) sem taxa divulgada encontrada.")
    if unusable and sec.status != "unknown":
        sec.degrade(f"{len(unusable)} fundo(s) com taxa informada que não é usada (valor 0 ou implausível).")
    return {
        **sec.head(),
        "month": fee_month.isoformat(),
        "estimate_label": ESTIMATE_LABEL,
        "not_found_label": NOT_FOUND,
        "stale_after_months": STALE_MONTHS,
        "stale_after_months_by_origin": STALE_MONTHS_BY_ORIGIN,
        "zero_label": ZERO_LABEL,
        "implausible_label": IMPLAUSIBLE_LABEL,
        "source_order": ["extrato", "lamina", "cad_fi"],
        "lines": out_lines,
        "underlying": underlying,
        "totals": _totals(out_lines),
    }


def _empty_fee() -> dict[str, Any]:
    return {
        "disclosed": None,
        "headline": None,
        "estimate": None,
        "expense_ratio": _expense_ratio(),
        "findings": [],
    }


def _expense_ratio(row: dict | None = None, src: dict | None = None) -> dict[str, Any]:
    """The lâmina's declared total expense ratio, its own field with its period; never added to a fee."""
    if row is None or row.get("lamina_pr_pl_despesa") is None:
        return {"declared_pct": None, "period": None, "as_of": (row or {}).get("lamina_as_of"), "source": None,
                "note": EXPENSE_RATIO_MISSING, "tool_note": (row or {}).get("lamina_expense_note")}
    return {
        "declared_pct": ratio(dec(row.get("lamina_pr_pl_despesa")), 4),
        "period": {"from": row.get("lamina_dt_ini_despesa"), "to": row.get("lamina_dt_fim_despesa")},
        "as_of": row.get("lamina_as_of"),
        "source": "cvm_fi_lamina",
        "note": EXPENSE_RATIO_NOTE,
        "sources": [src] if src else [],
    }


def _fee_record(row: dict, value: Decimal, call: Call, fee_month: dt.date) -> dict[str, Any]:
    """One fund's fees: disclosed, headline, estimate, findings. ``value`` is what the client holds in the fund."""
    src = source("portfolio_fees", call.call_id, call.args, row.get("month") or fee_month)
    d_adm = dec(row.get("disclosed_taxa_adm"))
    d_min = dec(row.get("disclosed_taxa_adm_min"))
    d_max = dec(row.get("disclosed_taxa_adm_max"))
    d_src = row.get("disclosed_source")
    as_of = row.get("disclosed_as_of")
    age = row.get("disclosed_age_months")
    # The provenance follows disclosed_origin (catalog v52); a v51 row has only disclosed_source.
    origin = row.get("disclosed_origin") or ORIGIN_FROM_SOURCE.get(d_src)
    has_disclosed = d_src is not None or origin is not None
    filed_zero = bool(row.get("filed_zero"))
    implausible = bool(row.get("implausible_filed"))
    raw_filed = dec(row.get("taxa_adm_filed_raw"))
    limit = STALE_MONTHS_BY_ORIGIN.get(origin)
    if isinstance(age, int) and limit is not None:
        stale = age > limit
    elif origin == "extrato" and isinstance(row.get("disclosed_age_days"), int):
        stale = row["disclosed_age_days"] / 30.4375 > limit
    else:
        stale = False
    tp = row.get("extrato_tp_fundo_classe")
    scope_label = "taxa da classe" if tp == "CLASSES - FIF" else ("taxa do fundo" if origin == "extrato" and tp else None)

    disclosed: dict[str, Any] | None = None
    headline: dict[str, Any] | None = None
    if has_disclosed:
        disclosed = {
            "origin": origin,
            "origin_label": ORIGIN_LABEL.get(origin),
            "source": d_src,
            "as_of": as_of,
            "as_of_meaning": {
                "extrato": "data de competência (DT_COMPTC) da versão mais recente do Extrato das Informações",
                "lamina": "mês de referência da lâmina (dt_comptc)",
                "cad_fi": "dia em que o SILO leu o cad_fi, não data de entrega do fundo",
            }.get(origin),
            "age_months": age,
            "age_days": row.get("disclosed_age_days"),
            "stale": stale,
            "stale_label": "defasada" if stale else None,
            "stale_after_months": limit,
            "n_classes": row.get("disclosed_n_classes"),
            "note": row.get("disclosed_note"),
            "filed_zero": filed_zero,
            "filed_zero_label": ZERO_LABEL if filed_zero else None,
            "implausible_filed": implausible,
            "implausible_label": IMPLAUSIBLE_LABEL if implausible else None,
            "adm_filed_raw": ratio(raw_filed, 6),  # as filed, unit read as % a year, plain number: never printed as a rate
            "adm_rate_pct_year": ratio(d_adm, 4),
            "adm_min_pct_year": ratio(d_min, 4),
            "adm_max_pct_year": ratio(d_max, 4),
            "adm_info_text": row.get("disclosed_taxa_adm_info"),
            "perf_as_filed": row.get("disclosed_taxa_perfm"),  # verbatim text, never parsed
            "perf_info_text": row.get("disclosed_taxa_perfm_info"),
            "perf_meaning": (
                "Taxa de performance divulgada, em texto, como no documento de origem: percentual sobre o excedente "
                "acima do referencial do regulamento. Não é % do patrimônio e o SILO não converte em R$."
            ),
            "scope_label": scope_label,
            "class_note": row.get("extrato_class_note"),
            "terms_as_filed": _extrato_terms(row) if origin == "extrato" else None,
            "sources": [src],
        }
        if implausible:
            disclosed["rejected"] = {
                "label": IMPLAUSIBLE_LABEL,
                "raw_value": ratio(raw_filed, 6),
                "rule": f"acima de {IMPLAUSIBLE_ABOVE_PCT}% a.a. (ou abaixo de 0): tratado como erro de escala e não usado",
            }
        if filed_zero:
            headline = {
                "kind": "zero_informado",
                "basis": ZERO_LABEL,
                "rate_pct_year": None,
                "filed_pct_year": 0.0,
                "per_year_brl": None,
                "counted_as_cost": False,
                "source": d_src,
                "origin": origin,
                "scope_label": scope_label,
                "as_of": as_of,
                "age_months": age,
                "stale": stale,
                "sources": [src],
            }
        elif d_adm is not None:
            headline = {
                "kind": "fixa",
                "basis": "taxa de administração divulgada",
                "rate_pct_year": ratio(d_adm, 4),
                "per_year_brl": brl(value * d_adm / 100),
                "source": d_src,
                "origin": origin,
                "scope_label": scope_label,
                "as_of": as_of,
                "age_months": age,
                "stale": stale,
                "sources": [src],
            }
        elif d_min is not None and d_max is not None and not implausible:
            headline = {
                "kind": "faixa",
                "basis": "faixa de taxa de administração divulgada (classes com taxas diferentes)",
                "rate_min_pct_year": ratio(d_min, 4),
                "rate_max_pct_year": ratio(d_max, 4),
                "per_year_min_brl": brl(value * d_min / 100),
                "per_year_max_brl": brl(value * d_max / 100),
                "source": d_src,
                "origin": origin,
                "as_of": as_of,
                "age_months": age,
                "stale": stale,
                "sources": [src],
            }

    est_adm = dec(row.get("adm_fee_pct_annual_est"))
    est_perf = dec(row.get("perf_fee_pct_annual_est"))
    suspect = bool(row.get("fiscal_reset_suspect"))
    estimate = {
        "label": ESTIMATE_LABEL,
        "method": row.get("estimate_label"),
        "month": row.get("month"),
        "nav_brl": brl(dec(row.get("nav"))),
        "available": est_adm is not None,
        "fiscal_reset_suspect": suspect,
        "adm_pct_year": ratio(est_adm, 4),
        "adm_per_year_brl": brl(value * est_adm / 100) if est_adm is not None else None,
        "perf_pct_year": ratio(est_perf, 4),
        "perf_per_year_brl": brl(value * est_perf / 100) if est_perf is not None else None,
        "note": "Nunca somada, nem comparada como se fosse a taxa divulgada: é o que o balancete do mês sugere.",
        "sources": [src],
    }

    findings: list[dict[str, Any]] = []
    if d_adm is not None and est_adm is not None:
        if d_adm == 0 and est_adm > CLEARLY_ABOVE_ZERO_PCT:
            findings.append(
                {
                    "kind": "divulgado_zero_balancete_registra_despesa",
                    "level": "atenção",
                    "text": "Divulgado 0, balancete registra despesa.",
                    "disclosed_pct_year": 0.0,
                    "estimate_pct_year": ratio(est_adm, 4),
                    "sources": [src],
                }
            )
        elif d_adm > 0 and abs(est_adm - d_adm) > max(DIFF_ABS_PCT, DIFF_REL * d_adm):
            findings.append(
                {
                    "kind": "estimativa_difere_da_divulgada",
                    "level": "atenção",
                    "text": (
                        "Estimativa e divulgada divergem por mais de max(0,25 p.p. a.a.; 25% do valor divulgado); "
                        "isso não diz qual das duas está errada."
                    ),
                    "disclosed_pct_year": ratio(d_adm, 4),
                    "estimate_pct_year": ratio(est_adm, 4),
                    "difference_pp": ratio(est_adm - d_adm, 4),
                    "sources": [src],
                }
            )
    if stale:
        findings.append(
            {
                "kind": "lamina_defasada" if origin == "lamina" else "taxa_defasada",
                "level": "informação",
                "text": (
                    f"A taxa divulgada ({ORIGIN_LABEL.get(origin, origin)}) tem {age if age is not None else '?'} meses "
                    f"de defasagem (mais de {limit})."
                ),
                "origin": origin,
                "age_months": age,
                "sources": [src],
            }
        )
    if implausible:
        findings.append(
            {
                "kind": "valor_implausivel_descartado",
                "level": "informação",
                "text": f"{IMPLAUSIBLE_LABEL.capitalize()}: a fonte informou uma taxa fora de 0 a {IMPLAUSIBLE_ABOVE_PCT}% a.a.",
                "origin": origin,
                "raw_value": ratio(raw_filed, 6),
                "sources": [src],
            }
        )

    # The reasons are the engine's own Portuguese; the tool's note (English, verbatim) stays in disclosed.note.
    if headline is not None and headline["kind"] == "zero_informado":
        status = ZERO_LABEL
        reason = "A fonte informou taxa de administração igual a 0: lida como não informada, nunca como custo zero, e não somada."
    elif headline is not None:
        status = "divulgada" if headline["kind"] == "fixa" else "faixa divulgada"
        reason = None
    elif implausible:
        status = IMPLAUSIBLE_LABEL
        reason = (f"A fonte informou {ratio(raw_filed, 6)}: fora de 0 a {IMPLAUSIBLE_ABOVE_PCT}% a.a., tratado como erro de "
                  "escala e não usado; o valor informado fica em campo à parte.")
    else:
        status = NOT_FOUND
        reason = (
            "Nenhuma taxa de administração única divulgada: as classes do fundo informam taxas diferentes ou nenhuma."
            if has_disclosed
            else "Nenhuma taxa de administração divulgada no Extrato, na lâmina nem no cad_fi."
        )
    return {
        "fee_status": status,
        "reason": reason,
        "fund_nav_brl": brl(dec(row.get("nav"))),
        "disclosed": disclosed,
        "headline": headline,
        "estimate": estimate,
        "expense_ratio": _expense_ratio(row, src),
        "findings": findings,
    }


def _extrato_terms(row: dict) -> dict[str, Any]:
    """The Extrato's other terms exactly as filed: no reading, no conversion."""
    return {
        "tp_fundo_classe": row.get("extrato_tp_fundo_classe"),
        "classe_anbima": row.get("extrato_classe_anbima"),
        "performance": {
            "exists": row.get("extrato_existe_taxa_perfm"),
            "taxa_perfm_as_filed": ratio(dec(row.get("extrato_taxa_perfm")), 6),
            "param_as_filed": row.get("extrato_param_taxa_perfm"),
            "calc_as_filed": row.get("extrato_calc_taxa_perfm"),
            "info_as_filed": row.get("extrato_inf_taxa_perfm"),
        },
        "entry": {
            "exists": row.get("extrato_existe_taxa_ingresso"),
            "pct_as_filed": ratio(dec(row.get("extrato_taxa_ingresso_pr")), 6),
            "real_brl_as_filed": brl(dec(row.get("extrato_taxa_ingresso_real"))),
        },
        "exit": {
            "exists": row.get("extrato_existe_taxa_saida"),
            "pct_as_filed": ratio(dec(row.get("extrato_taxa_saida_pr")), 6),
            "real_brl_as_filed": brl(dec(row.get("extrato_taxa_saida_real"))),
        },
        "custody_max_as_filed": ratio(dec(row.get("extrato_taxa_custodia_max")), 6),
    }


def _underlying(fund_nodes: dict[int, list[dict[str, Any]]], client: SiloClient, fee_month: dt.date, sec: Section) -> list[dict[str, Any]]:
    nodes: list[tuple[int, dict[str, Any]]] = [(ln, n) for ln, ns in fund_nodes.items() for n in ns if n.get("fund_cnpj")]
    if not nodes:
        return []
    cnpjs = sorted({str(n["fund_cnpj"]) for _, n in nodes})
    found, calls = _fetch(client, cnpjs, fee_month, sec.errors)
    if any(not c.ok for c in calls):
        sec.degrade("portfolio_fees falhou para os fundos investidos (taxa dos fundos de baixo desconhecida).")
    out = []
    for ln, n in nodes:
        entry = found.get(str(n["fund_cnpj"]))
        value = dec(n.get("value_brl")) or Decimal("0")
        rec: dict[str, Any] = {
            "line_no": ln,
            "fund_cnpj": n["fund_cnpj"],
            "fund_name": n.get("fund_name"),
            "path": n.get("path"),
            "depth": n.get("depth"),
            "value_brl": brl(value),
            "added_to_totals": False,
            "label": NOT_ADDED,
            "label_note": "Taxa do fundo investido, mostrada à parte: nunca somada à taxa do fundo de cima nem ao total.",
        }
        if entry is None:
            rec.update(fee_status=NOT_FOUND, reason="sem linha de taxa para o fundo investido", **_empty_fee())
        else:
            rec.update(_fee_record(entry["row"], value, entry["call"], fee_month))
        out.append(rec)
    return out


def _totals(lines: list[dict]) -> dict[str, Any]:
    fixed = Decimal("0")
    range_lo = Decimal("0")
    range_hi = Decimal("0")
    est_adm = Decimal("0")
    est_perf = Decimal("0")
    v_fixed = v_range = v_none = v_zero = v_implausible = Decimal("0")
    for o in lines:
        v = dec(o["position_value_brl"]) or Decimal("0")
        h = o.get("headline")
        if h and h["kind"] == "zero_informado":
            v_zero += v  # a filed 0 is not a fee: never counted as a zero cost, never summed
        elif o.get("fee_status") == IMPLAUSIBLE_LABEL:
            v_implausible += v
        elif h and h["kind"] == "fixa":
            fixed += dec(h["per_year_brl"]) or Decimal("0")
            v_fixed += v
        elif h and h["kind"] == "faixa":
            range_lo += dec(h["per_year_min_brl"]) or Decimal("0")
            range_hi += dec(h["per_year_max_brl"]) or Decimal("0")
            v_range += v
        else:
            v_none += v
        e = o.get("estimate") or {}
        est_adm += dec(e.get("adm_per_year_brl")) or Decimal("0")
        est_perf += dec(e.get("perf_per_year_brl")) or Decimal("0")
    total_value = v_fixed + v_range + v_none + v_zero + v_implausible
    return {
        "adm_disclosed_fixed_per_year_brl": brl(fixed),
        "adm_disclosed_range_low_per_year_brl": brl(range_lo),
        "adm_disclosed_range_high_per_year_brl": brl(range_hi),
        "total_note": (
            "Só taxas divulgadas entram aqui: a soma das fixas e, à parte, a faixa das linhas com taxas diferentes entre "
            "classes. A estimativa do balancete fica no campo próprio, nunca somada à divulgada. Taxas de fundos "
            "investidos não entram (não somada)."
        ),
        "estimate_adm_per_year_brl": brl(est_adm),
        "estimate_perf_per_year_brl": brl(est_perf),
        "estimate_label": ESTIMATE_LABEL,
        "fund_value_brl": brl(total_value),
        "fund_value_with_fixed_fee_brl": brl(v_fixed),
        "fund_value_with_fee_range_brl": brl(v_range),
        "fund_value_without_disclosed_fee_brl": brl(v_none + v_zero + v_implausible),
        "fund_value_with_filed_zero_brl": brl(v_zero),
        "fund_value_with_implausible_fee_brl": brl(v_implausible),
        "known_fee_fund_value_pct": pct(v_fixed + v_range, total_value) if total_value else None,
    }
