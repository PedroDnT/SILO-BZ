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
   A filed 0 is ``0 informado; a conferir`` and a filed value above 5 % a.a. is ``valor
   informado acima de 5% a.a.; a conferir``: either may be correct, so the engine never says
   it is wrong. Neither is used as a cost, summed or compared; the filed value is shown, the
   balancete estimate stays beside it, and ``needs_manual_check`` is true.
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
8. The Extrato and the lâmina disagree (catalog v55, issue #552). ``fee_resolution`` says which
   rule the tool applied. When the Extrato filed 0 or above 5 % a.a. and the lâmina is older, has
   no single fee or none in (0, 5] (``extrato_lamina_beside``), the Extrato stays the fee as filed
   and the lâmina's own fee is shown beside it: ``lâmina informa X; a conferir``. When the lâmina's
   single fee is in (0, 5] and NEWER than the Extrato (``lamina_newer``), the lâmina is the
   headline (``headline.kind = "lamina_mais_recente"``) and the Extrato's value is shown beside it
   as filed: ``Extrato de <data> informa X``. Owner's decision of 2026-10-03 (engine 1.5): the
   newer lâmina's fee is a disclosed fee like any other, so it is a cost (``per_year_brl``), enters
   the fixed sum and is compared with the balancete estimate; the line stays flagged
   (``needs_manual_check``, "fontes divergem") and the Extrato's value beside it is never summed.
   In ``extrato_lamina_beside`` and ``extrato_to_check`` neither value is a cost, summed or
   compared. Nothing is rescaled. When the Extrato above 5 is exactly 10 or 100 times the lâmina
   (``extrato_scale_factor``), ``scale_flag`` says ``possível erro de escala no Extrato``: a flag
   only.
9. ETFs (engine 1.5). An ETF line reaches this block with its CNPJ from ``portfolio_resolve``
   (``match_kind = "etf_ticker"``: the ticker in SILO's curated ETF registry). CVM's Extrato,
   lâmina and cad_fi carry no fee for an ETF (measured 2026-10-03: 0 of the 178 active ETFs), so
   when no CVM source discloses one the fee is ``portfolio_fees``' ``etf_site_*``: the "Taxa de
   administração total" printed on etfsbrasil.com.br, a third-party site, with its snapshot date.
   It is labelled as such (``headline.kind = "etf_site"``, never "divulgada" by the CVM), applies
   the same reading rules (a 0 or above 5 % a.a. is shown, to check, never a cost), and enters
   its own sum (``totals.adm_etf_site_per_year_brl``) and the total of both
   (``totals.adm_fee_per_year_brl``). A CVM source, when one exists, always comes first.

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
ZERO_LABEL = "0 informado; a conferir"
IMPLAUSIBLE_LABEL = "valor informado acima de 5% a.a.; a conferir"
NEGATIVE_LABEL = "valor informado negativo; a conferir"
# catalog v55, issue #552: the lâmina beside the Extrato, or the newer lâmina as the source
LAMINA_BESIDE_LABEL = "lâmina informa"
CHECK_LABEL = "a conferir"
EXTRATO_BESIDE_LABEL = "Extrato informa"
LAMINA_NEWER_LABEL = "lâmina mais recente que o Extrato; a conferir"
SOURCES_DIFFER_LABEL = "fontes divergem"
SCALE_FLAG_LABEL = "possível erro de escala no Extrato"
LAMINA_BESIDE_NOTE = (
    "Taxa da lâmina mostrada ao lado da do Extrato, nunca no lugar dela: o Extrato informou 0 ou valor acima de 5% a.a. "
    "e a lâmina é mais antiga ou não traz uma taxa única entre 0 e 5% a.a. Nenhum dos dois valores entra em soma ou comparação."
)
EXTRATO_BESIDE_NOTE = (
    "Valor do Extrato como informado, mostrado ao lado da taxa da lâmina, que é mais recente: o Extrato informou 0 ou valor "
    "acima de 5% a.a. A taxa da lâmina entra na soma e na comparação com o balancete; o valor do Extrato não entra em "
    "nenhuma conta. Fontes divergem: a conferir. Nada é corrigido."
)
# engine 1.5: an ETF's fee from etfsbrasil.com.br when no CVM source discloses one (portfolio_fees etf_site_*, catalog v56)
ETF_SITE_LABEL = "taxa informada pelo site etfsbrasil.com.br (fonte de terceiros, não é documento da CVM)"
ETF_SITE_ORIGIN_LABEL = "site etfsbrasil.com.br (terceiros)"
ETF_SITE_NOTE = (
    "Taxa de administração total impressa na página do ETF em etfsbrasil.com.br, lida na data indicada. O Extrato, a lâmina "
    "e o cad_fi da CVM não trazem taxa para ETFs; quando trazem, a fonte da CVM vem primeiro. Somada à parte das taxas "
    "divulgadas em documento da CVM."
)
SCALE_FLAG_NOTE = (
    "Sinal apenas: o valor do Extrato é exatamente 10 ou 100 vezes a taxa da lâmina. Nenhum valor é corrigido nem reescalado."
)
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
    fund_lines = [li for li in lines if _fee_cnpj(li)]
    if not fund_lines:
        sec.status = STATUS_NOT_APPLICABLE
        sec.reason = "Nenhuma linha de fundo identificada."
        return {**sec.head(), "month": fee_month.isoformat(), "lines": [], "underlying": [], "totals": _totals([])}

    cnpjs = sorted({c for c in (_fee_cnpj(li) for li in fund_lines) if c})
    found, calls = _fetch(client, cnpjs, fee_month, sec.errors)
    failed_calls = [c for c in calls if not c.ok]
    if failed_calls and len(failed_calls) == len(calls):
        sec.fail("portfolio_fees falhou (erro literal em errors); nenhuma taxa pôde ser calculada.")
    elif failed_calls:
        sec.degrade("portfolio_fees falhou para parte dos fundos (erro literal em errors).")

    out_lines = []
    for li in fund_lines:
        cnpj = _fee_cnpj(li)
        entry = found.get(cnpj or "")
        base = {
            "line_no": li.line_no,
            "cnpj": cnpj,
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
    unusable = [o for o in out_lines if o.get("needs_manual_check") and not (o.get("headline") or {}).get("counted_as_cost")]
    differ = [o for o in out_lines if o.get("needs_manual_check") and (o.get("headline") or {}).get("counted_as_cost")]
    if unknown and sec.status != "unknown":
        sec.degrade(f"{len(unknown)} fundo(s) sem taxa divulgada encontrada.")
    if unusable and sec.status != "unknown":
        sec.degrade(f"{len(unusable)} fundo(s) com taxa informada a conferir (0 ou acima de 5% a.a.), que não entra em nenhuma conta.")
    if differ and sec.status != "unknown":
        sec.degrade(f"{len(differ)} fundo(s) com a lâmina mais recente que o Extrato como fonte: fontes divergem, a conferir; a taxa da lâmina entra na soma.")
    return {
        **sec.head(),
        "month": fee_month.isoformat(),
        "estimate_label": ESTIMATE_LABEL,
        "not_found_label": NOT_FOUND,
        "stale_after_months": STALE_MONTHS,
        "stale_after_months_by_origin": STALE_MONTHS_BY_ORIGIN,
        "zero_label": ZERO_LABEL,
        "implausible_label": IMPLAUSIBLE_LABEL,
        "negative_label": NEGATIVE_LABEL,
        "lamina_beside_label": LAMINA_BESIDE_LABEL,
        "extrato_beside_label": EXTRATO_BESIDE_LABEL,
        "lamina_newer_label": LAMINA_NEWER_LABEL,
        "sources_differ_label": SOURCES_DIFFER_LABEL,
        "etf_site_label": ETF_SITE_LABEL,
        "scale_flag_label": SCALE_FLAG_LABEL,
        "check_label": CHECK_LABEL,
        "source_order": ["extrato", "lamina", "cad_fi"],
        "lines": out_lines,
        "underlying": underlying,
        "totals": _totals(out_lines),
    }


def _empty_fee() -> dict[str, Any]:
    return {
        "needs_manual_check": False,
        "disclosed": None,
        "headline": None,
        "estimate": None,
        "expense_ratio": _expense_ratio(),
        "fee_resolution": None,
        "lamina_beside": None,
        "extrato_beside": None,
        "scale_flag": None,
        "etf_site": None,
        "findings": [],
    }


def _fee_cnpj(li: LineId) -> str | None:
    """The CNPJ whose fee the line carries: a fund's own, or an ETF's from the ETF registry (engine 1.5)."""
    if li.kind == "fund" and li.cnpj and li.position.tipo in FEE_TIPOS:
        return li.cnpj
    return li.etf_cnpj


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
    resolution = row.get("fee_resolution")  # catalog v55; NULL on an older row
    lamina_newer = resolution == "lamina_newer"
    needs_check = filed_zero or implausible or lamina_newer
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
            "implausible_label": (NEGATIVE_LABEL if raw_filed is not None and raw_filed < 0 else IMPLAUSIBLE_LABEL) if implausible else None,
            "needs_manual_check": needs_check,
            "fee_resolution": resolution,
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
                "label": disclosed["implausible_label"],
                "raw_value": ratio(raw_filed, 6),
                "rule": f"fora de 0 a {IMPLAUSIBLE_ABOVE_PCT}% a.a.: não usado como custo, não somado nem comparado, a conferir; pode estar correto",
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
        elif lamina_newer and d_adm is not None:
            # The newer of two filed, dated documents: the lâmina's fee is the headline and, by the owner's decision of
            # 2026-10-03 (engine 1.5), a cost like any disclosed fee: summed and compared. The line stays to check.
            headline = {
                "kind": "lamina_mais_recente",
                "basis": LAMINA_NEWER_LABEL,
                "sources_differ_label": SOURCES_DIFFER_LABEL,
                "rate_pct_year": ratio(d_adm, 4),
                "per_year_brl": brl(value * d_adm / 100),
                "counted_as_cost": True,
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

    lamina_beside, extrato_beside, scale_flag = _beside(row, resolution, src)

    # engine 1.5: an ETF's fee from etfsbrasil.com.br, only when no CVM source discloses anything for the fund.
    etf_site = _etf_site(row, src)
    etf_fee = dec(row.get("etf_site_taxa_adm"))
    if etf_site is not None and not has_disclosed and headline is None and etf_fee is not None:
        usable = Decimal("0") < etf_fee <= IMPLAUSIBLE_ABOVE_PCT
        needs_check = not usable
        headline = {
            "kind": "etf_site",
            "basis": ETF_SITE_LABEL,
            "rate_pct_year": ratio(etf_fee, 4) if usable else None,
            "filed_pct_year": ratio(etf_fee, 4),  # as published by the site, never rescaled
            "per_year_brl": brl(value * etf_fee / 100) if usable else None,
            "counted_as_cost": usable,
            "check_label": None if usable else (ZERO_LABEL if etf_fee == 0 else (NEGATIVE_LABEL if etf_fee < 0 else IMPLAUSIBLE_LABEL)),
            "source": "etf_market_snapshot",
            "origin": "etf_site",
            "origin_label": ETF_SITE_ORIGIN_LABEL,
            "ticker": row.get("etf_ticker"),
            "as_of": row.get("etf_site_as_of"),
            "sources": [src],
        }
        etf_site["used_as_fee"] = usable

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
                "text": f"{disclosed['implausible_label'].capitalize()}: a fonte informou um valor fora do intervalo usual; pode estar correto e não entra em nenhuma conta.",
                "origin": origin,
                "raw_value": ratio(raw_filed, 6),
                "sources": [src],
            }
        )

    if lamina_beside is not None:
        findings.append(
            {
                "kind": "lamina_ao_lado_do_extrato",
                "level": "informação",
                "text": "A lâmina informa outra taxa, mostrada ao lado da do Extrato; a conferir. Nenhuma das duas entra em soma.",
                "lamina_pct_year": lamina_beside["lamina_pct_year"],
                "sources": [src],
            }
        )
    if extrato_beside is not None:
        findings.append(
            {
                "kind": "lamina_mais_recente_que_extrato",
                "level": "informação",
                "text": ("Fontes divergem: a lâmina, mais recente que o Extrato, é a fonte da taxa e entra na soma e na comparação "
                         "com o balancete; o Extrato informou 0 ou valor acima de 5% a.a. e fica ao lado, como informado, fora de "
                         "qualquer conta; a conferir."),
                "raw_value": extrato_beside["filed_value"],
                "sources": [src],
            }
        )
    if scale_flag is not None:
        findings.append(
            {
                "kind": "possivel_erro_de_escala_no_extrato",
                "level": "atenção",
                "text": "Possível erro de escala no Extrato: o valor do Extrato é exatamente 10 ou 100 vezes a taxa da lâmina; nada foi corrigido.",
                "factor": scale_flag["factor"],
                "extrato_lamina_ratio": scale_flag["extrato_lamina_ratio"],
                "sources": [src],
            }
        )

    # The reasons are the engine's own Portuguese; the tool's note (English, verbatim) stays in disclosed.note.
    if headline is not None and headline["kind"] == "lamina_mais_recente":
        status = LAMINA_NEWER_LABEL
        reason = ("O Extrato informou 0 ou valor acima de 5% a.a.; a lâmina, mais recente, informa outra taxa e é a fonte. "
                  "Fontes divergem: a taxa da lâmina é usada como custo, somada e comparada com o balancete, e a linha fica a "
                  "conferir; o valor do Extrato fica ao lado, como informado, fora de qualquer conta.")
    elif headline is not None and headline["kind"] == "etf_site":
        status = ETF_SITE_LABEL if headline["counted_as_cost"] else headline["check_label"]
        reason = ("ETF: o Extrato, a lâmina e o cad_fi da CVM não trazem taxa para este fundo; a taxa é a informada pelo site "
                  "etfsbrasil.com.br, fonte de terceiros, na data indicada"
                  + (", somada à parte das taxas divulgadas em documento da CVM." if headline["counted_as_cost"]
                     else ". O valor fica a conferir (pode estar correto): não é usado como custo, nem somado."))
    elif headline is not None and headline["kind"] == "zero_informado":
        status = ZERO_LABEL
        reason = "A fonte informou taxa de administração igual a 0. O valor fica a conferir (pode estar correto): não é usado como custo, nem somado, nem comparado."
    elif headline is not None:
        status = "divulgada" if headline["kind"] == "fixa" else "faixa divulgada"
        reason = None
    elif implausible:
        status = disclosed["implausible_label"]
        reason = (f"A fonte informou {ratio(raw_filed, 6)}, fora do intervalo usual de 0 a {IMPLAUSIBLE_ABOVE_PCT}% a.a. O valor fica a conferir "
                  "(pode estar correto): não é usado como custo, nem somado, nem comparado; o valor informado está em campo à parte.")
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
        "needs_manual_check": needs_check,
        "fund_nav_brl": brl(dec(row.get("nav"))),
        "disclosed": disclosed,
        "headline": headline,
        "estimate": estimate,
        "expense_ratio": _expense_ratio(row, src),
        "fee_resolution": resolution,
        "lamina_beside": lamina_beside,
        "extrato_beside": extrato_beside,
        "scale_flag": scale_flag,
        "etf_site": etf_site,
        "findings": findings,
    }


def _etf_site(row: dict, src: dict) -> dict[str, Any] | None:
    """An ETF's fee as etfsbrasil.com.br prints it (portfolio_fees etf_*, catalog v56); None when the CNPJ is no ETF."""
    if not row.get("etf_ticker"):
        return None
    return {
        "label": ETF_SITE_LABEL,
        "origin_label": ETF_SITE_ORIGIN_LABEL,
        "ticker": row.get("etf_ticker"),
        "rate_as_published": ratio(dec(row.get("etf_site_taxa_adm")), 4),  # as the site prints it, never rescaled
        "as_of": row.get("etf_site_as_of"),
        "source": row.get("etf_site_source"),
        "tool_note": row.get("etf_site_note"),
        "note": ETF_SITE_NOTE,
        "used_as_fee": False,  # set below when it is the headline
        "sources": [src],
    }


def _beside(row: dict, resolution: str | None, src: dict) -> tuple[dict | None, dict | None, dict | None]:
    """The other document's fee, shown beside the headline as filed (catalog v55, #552). Never a cost, never summed."""
    lamina_beside = extrato_beside = scale_flag = None
    lam = dec(row.get("lamina_taxa_adm"))
    lam_min = dec(row.get("lamina_taxa_adm_min"))
    lam_max = dec(row.get("lamina_taxa_adm_max"))
    if resolution == "extrato_lamina_beside" and (lam is not None or lam_min is not None):
        lam_age = row.get("lamina_age_months")
        limit = STALE_MONTHS_BY_ORIGIN["lamina"]
        lam_stale = isinstance(lam_age, int) and lam_age > limit
        lamina_beside = {
            "label": LAMINA_BESIDE_LABEL,
            "check_label": CHECK_LABEL,
            "lamina_pct_year": ratio(lam, 4),
            "lamina_min_pct_year": ratio(lam_min, 4) if lam is None else None,
            "lamina_max_pct_year": ratio(lam_max, 4) if lam is None else None,
            "n_classes": row.get("lamina_n_classes"),
            "as_of": row.get("lamina_as_of"),
            "age_months": lam_age,
            "stale": lam_stale,
            "stale_label": "defasada" if lam_stale else None,
            "stale_after_months": limit,
            "source": "cvm_fi_lamina",
            "origin_label": ORIGIN_LABEL["lamina"],
            "counted_as_cost": False,
            "note": LAMINA_BESIDE_NOTE,
            "sources": [src],
        }
    if resolution == "lamina_newer" and row.get("extrato_taxa_adm_filed") is not None:
        extrato_beside = {
            "label": EXTRATO_BESIDE_LABEL,
            "filed_value": ratio(dec(row.get("extrato_taxa_adm_filed")), 6),  # as filed, plain number: never printed as a rate
            "as_of": row.get("extrato_as_of"),
            "source": "cvm_fi_extrato",
            "origin_label": ORIGIN_LABEL["extrato"],
            "counted_as_cost": False,
            "note": EXTRATO_BESIDE_NOTE,
            "sources": [src],
        }
    factor = row.get("extrato_scale_factor")
    if factor in (10, 100):
        scale_flag = {
            "label": SCALE_FLAG_LABEL,
            "factor": int(factor),
            "extrato_lamina_ratio": ratio(dec(row.get("extrato_lamina_ratio")), 4),
            "note": SCALE_FLAG_NOTE,
            "sources": [src],
        }
    return lamina_beside, extrato_beside, scale_flag


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
    etf = Decimal("0")
    range_lo = Decimal("0")
    range_hi = Decimal("0")
    est_adm = Decimal("0")
    est_perf = Decimal("0")
    v_fixed = v_range = v_none = v_zero = v_implausible = v_lamina_newer = v_etf = v_etf_check = Decimal("0")
    for o in lines:
        v = dec(o["position_value_brl"]) or Decimal("0")
        h = o.get("headline")
        if h and h["kind"] == "zero_informado":
            v_zero += v  # a filed 0 is not a fee: never counted as a zero cost, never summed
        elif (o.get("disclosed") or {}).get("implausible_filed"):
            v_implausible += v  # the flag lives in disclosed (engine 1.3 read a top-level key the record never had, so this bucket stayed 0)
        elif h and h["kind"] in ("fixa", "lamina_mais_recente"):
            # engine 1.5 (owner, 2026-10-03): the newer lâmina's fee is summed like any disclosed fee; the line stays to check
            fixed += dec(h["per_year_brl"]) or Decimal("0")
            v_fixed += v
            if h["kind"] == "lamina_mais_recente":
                v_lamina_newer += v  # a subset of fund_value_with_fixed_fee_brl since 1.5
        elif h and h["kind"] == "etf_site" and h.get("counted_as_cost"):
            etf += dec(h["per_year_brl"]) or Decimal("0")  # a third-party site's fee: its own sum, never under "divulgada"
            v_etf += v
        elif h and h["kind"] == "etf_site":
            v_etf_check += v  # the site printed 0 or above 5: shown, to check, never summed
        elif h and h["kind"] == "faixa":
            range_lo += dec(h["per_year_min_brl"]) or Decimal("0")
            range_hi += dec(h["per_year_max_brl"]) or Decimal("0")
            v_range += v
        else:
            v_none += v
        e = o.get("estimate") or {}
        est_adm += dec(e.get("adm_per_year_brl")) or Decimal("0")
        est_perf += dec(e.get("perf_per_year_brl")) or Decimal("0")
    total_value = v_fixed + v_range + v_none + v_zero + v_implausible + v_etf + v_etf_check
    return {
        "adm_disclosed_fixed_per_year_brl": brl(fixed),
        "adm_disclosed_range_low_per_year_brl": brl(range_lo),
        "adm_disclosed_range_high_per_year_brl": brl(range_hi),
        "total_note": (
            "Só taxas divulgadas entram aqui: a soma das fixas (inclusive a da lâmina mais recente que o Extrato, a conferir "
            "porque as fontes divergem; o valor do Extrato ao lado nunca entra) e, à parte, a faixa das linhas com taxas "
            "diferentes entre classes. A taxa de ETF informada pelo site etfsbrasil.com.br (fonte de terceiros) é somada à "
            "parte, em adm_etf_site_per_year_brl, e as duas juntas estão em adm_fee_per_year_brl. A estimativa do balancete "
            "fica no campo próprio, nunca somada à divulgada. Taxas de fundos investidos não entram (não somada)."
        ),
        "adm_etf_site_per_year_brl": brl(etf),
        "adm_fee_per_year_brl": brl(fixed + etf),
        "estimate_adm_per_year_brl": brl(est_adm),
        "estimate_perf_per_year_brl": brl(est_perf),
        "estimate_label": ESTIMATE_LABEL,
        "fund_value_brl": brl(total_value),
        "fund_value_with_fixed_fee_brl": brl(v_fixed),
        "fund_value_with_fee_range_brl": brl(v_range),
        "fund_value_without_disclosed_fee_brl": brl(v_none + v_zero + v_implausible + v_etf_check),
        "fund_value_with_filed_zero_brl": brl(v_zero),
        "fund_value_with_implausible_fee_brl": brl(v_implausible),
        "fund_value_with_lamina_newer_fee_brl": brl(v_lamina_newer),
        "fund_value_with_etf_site_fee_brl": brl(v_etf),
        "fund_value_with_etf_site_fee_to_check_brl": brl(v_etf_check),
        "known_fee_fund_value_pct": pct(v_fixed + v_range, total_value) if total_value else None,
        "known_fee_incl_etf_site_fund_value_pct": pct(v_fixed + v_range + v_etf, total_value) if total_value else None,
    }
