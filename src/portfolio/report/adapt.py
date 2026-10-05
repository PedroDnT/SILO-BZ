"""The engine's JSON (schema 1.x) as the report's view.

The Redator, the Revisor and the renderer were written against a view of the engine's output
(``tests/fixtures/portfolio/report_provisional_engine_output.json``: ``lines``, ``fees.by_line``,
``lookthrough.shared_exposure``, ``indexer.buckets``...). The engine's own schema is richer and
named differently (``docs/reference/portfolio/engine-output.md``), so this module is the mapping
table of that page as code: it renames, selects and reshapes. It computes no figure: every number
is copied from the engine document (percentages the view needs are fields the engine writes,
``portfolio_pct`` and friends), and every label that says what a fee is comes from the engine.

The view holds no holder, account or statement-file identifier (the engine's ``statement.holder``
is not copied), so the Redator's ``assert_masked`` stays true.
"""

from __future__ import annotations

from typing import Any

from src.portfolio.common import REASON_TEXT

VIEW_VERSION = "report-view-1"
SHARED_GROUPS_SHOWN = 12

# The report names the source of each tool for its footer and the Revisor's citation rule.
SOURCE_BY_TOOL = {
    "lookup": "CVM", "company_financials": "CVM", "portfolio_resolve": "CVM", "portfolio_fees": "CVM",
    "portfolio_lookthrough": "CVM", "portfolio_movement": "CVM", "fidc_portfolio": "CVM", "quote_latest": "B3", "short_interest": "B3",
    "portfolio_instruments": "CVM", "portfolio_fund_terms": "CVM",
    "fund_restatements": "FNET", "fund_restatement_diff": "FNET", "screen_restatements": "FNET",
    "screen_late_filers": "FNET",
    # engine 1.10: the return block's series (fund quota from CVM, closes from B3, the CDI from BCB's SGS 12)
    "fund_nav": "CVM", "quote_history": "B3", "trade_consolidated_history": "B3", "macro_series": "BCB",
    # engine 1.12: the class distribution is CVM's quotas; the equivalents list is SILO's ETF registry (CVM) with the
    # etfsbrasil PL and fee, listed apart as ETFSBRASIL with the snapshot date (see _provenance_view)
    "class_return_distribution": "CVM", "portfolio_equivalents": "ETFSBRASIL",
}
LEVEL_BY_KIND = {
    "mesmo_ativo": "ativo",
    "mesmo_fundo_investido": "fundo",
    "mesmo_emissor_raiz_cnpj": "emissor (raiz de CNPJ)",
    "mesmo_codigo_emissor_b3": "emissor (código B3)",
}
FEES_BASIS = (
    "taxa de administração divulgada (Extrato CVM, lâmina, cad_fi, nessa ordem); a estimativa do balancete "
    "fica em campo à parte, rotulada 'estimativa, não divulgada', e nunca substitui a taxa divulgada"
)
TESOURO_NO_PRICE = "o SILO não tem série de preços do Tesouro Direto: o valor da linha é o do extrato"
# engine 1.7: what the report says about a gap is the fixed text of a code, never the engine's free text (which can
# name a tool or quote an error). A code this table does not know reads as the generic text.
GENERIC_GAP = "não foi possível avaliar esta parte nesta versão"
SECTION_STATUS_TEXT = {"partial": "avaliada em parte", "unknown": "não avaliada"}
SCREEN_FAILED = "a tela não rodou: a consulta ao SILO falhou ou foi recusada"
SECTION_TITLES_PT = {
    "identification": "Identificação", "fees": "Taxas", "lookthrough": "Look-through (carteira dos fundos)",
    "indexer": "Indexador", "sector": "Setor", "restatements": "Reapresentações", "risk_screens": "Telas de risco",
    "abnormal_movement": "Movimento incomum", "concentration": "Concentração", "allocation": "Alocação por classe",
    "risks": "Principais riscos", "liquidity": "Liquidez", "returns": "Retorno por posição",
    "tax": "Taxa e imposto por posição", "equivalents": "Equivalente de mercado",
}
# engine 1.9: what the identification table marks on a line, from the position's own flags and the credit match
BADGES = (
    ("ocr", "lido por OCR"),
    ("codigo_nao_conferido", "código não conferido"),
    ("taxa_nao_conferida", "taxa não conferida"),
    ("vencimento_diverge", "vencimento diverge do registro CVM"),
)
BADGE_LABEL = dict(BADGES)


def reason_text(code: str | None) -> str:
    return REASON_TEXT.get(code or "", GENERIC_GAP)


def _prov(*sources_lists: Any) -> list[str]:
    """Provenance ids (``p<call_id>``) of every non-statement source found in the given source lists."""
    out: list[str] = []
    for lst in sources_lists:
        for s in lst or []:
            if isinstance(s, dict) and s.get("tool") != "statement" and s.get("call_id") is not None:
                pid = f"p{s['call_id']}"
                if pid not in out:
                    out.append(pid)
    return out


def _asset_type(pos: dict, ident: dict) -> str:
    tipo = pos.get("tipo")
    identity = ident.get("identity") or {}
    asset_class = identity.get("asset_class")
    if tipo == "tesouro":
        return "titulo_publico"
    if tipo == "caixa":
        return "caixa"
    if tipo == "FIDC":
        return "fidc"
    if tipo in ("FII", "ETF", "FIP"):
        return tipo.lower()
    if tipo == "ação" or asset_class == "equity":
        return "acao"
    if asset_class == "fund_quota":
        return "cota_listada"
    if tipo == "fundo":
        return "fundo"
    if tipo in ("CRI", "CRA", "CDB", "LCI", "LCA", "debênture"):
        return "credito_privado"
    return "desconhecido"


def _line_view(pos: dict, ident: dict) -> dict:
    identity = ident.get("identity") or {}
    fm = ident.get("fund_match") or {}
    chosen = fm.get("chosen") or {}
    renamed = next((f for f in ident.get("findings") or [] if f.get("kind") == "renamed"), None)
    status = ident.get("status") or "unknown"
    cands = fm.get("candidates") or []
    tiebreak = bool(fm.get("tiebroken_by_quota"))
    view_status = "ambiguous" if (status == "ambiguous" or tiebreak) else status
    if identity.get("kind") == "tesouro":
        method = "titulo_e_vencimento"
    elif identity.get("kind") == "caixa":
        method = "linha_do_extrato"
    elif identity.get("kind") == "ticker":
        method = "ticker"
    elif identity.get("kind") == "credito":
        method = (ident.get("credit_match") or {}).get("match_kind") or "codigo_registro"
    else:
        method = chosen.get("match_kind") or ("nome_abreviado_desempate_por_cota" if tiebreak else None)
    code = ident.get("reason_code")
    if code == "cnpj_extrato":
        method = "cnpj_extrato"
    ident_view: dict[str, Any] = {
        "status": view_status,
        "method": method,
        # engine 1.7: a fixed text for a line not identified (or identified by the statement's CNPJ only)
        "reason": reason_text(code) if (status != "identified" or code == "cnpj_extrato") else None,
        "reason_code": code,
        "renamed_from": renamed.get("matched_name") if renamed else None,
        "renamed_at": renamed.get("matched_period") if renamed else None,
        "candidates": [],
    }
    if view_status == "ambiguous":
        ident_view["candidates"] = [
            {
                "cnpj": c.get("cnpj"),
                "fund_name": c.get("name"),
                "quota": c.get("quota_on_date"),
                "quota_date": pos.get("data_posicao"),
                "chosen": bool(chosen) and c.get("cnpj") == chosen.get("cnpj"),
            }
            for c in cands
        ]
    return {
        "line_id": f"L{pos['line_no']}",
        "asset_type": _asset_type(pos, ident),
        "instrument": pos.get("linha_extrato"),
        "cnpj": identity.get("cnpj"),
        "ticker": identity.get("ticker"),
        "fund_name": identity.get("name") if identity.get("kind") == "fund" else None,
        "value_brl": pos.get("valor_brl"),
        "weight_pct": pos.get("portfolio_pct"),
        "vencimento": pos.get("vencimento"),
        "taxa_texto": pos.get("taxa_texto"),
        "n_source_lines": len(pos.get("contas") or []) or 1,
        "badges": _badges(pos, ident),
        "identification": ident_view,
        "provenance": _prov(
            (ident.get("valuation") or {}).get("sources"),
            fm.get("sources"),
            ((ident.get("ticker_match") or {}).get("lookup") or {}).get("sources"),
            ((ident.get("ticker_match") or {}).get("reference_quote") or {}).get("sources"),
        ),
    }


def _badges(pos: dict, ident: dict) -> list[dict]:
    """Engine 1.9: the marks of the identification table, from flags the engine already carries (fixed labels)."""
    codes = []
    if pos.get("fonte_texto") == "ocr":
        codes.append("ocr")
    if pos.get("codigo_conferido") is False:
        codes.append("codigo_nao_conferido")
    if pos.get("taxa_conferida") is False:
        codes.append("taxa_nao_conferida")
    if any(f.get("code") == "vencimento_diverge" for f in (ident.get("credit_match") or {}).get("flags") or []):
        codes.append("vencimento_diverge")
    return [{"code": c, "label": BADGE_LABEL[c]} for c in codes]


def _credit_view(eng: dict) -> dict | None:
    """Engine 1.9: the CRA, CRI and debênture lines sent to the registry, with the statement's facts beside the
    registry's, copied (the price gap is the engine's ``price_gap_pct``). None for an older document."""
    positions = {p["line_no"]: p for p in eng["statement"]["positions"]}
    rows = []
    for ln in eng["identification"].get("lines") or []:
        cm = ln.get("credit_match")
        if not isinstance(cm, dict):
            continue
        st = cm.get("statement") or {}
        pos = positions.get(ln["line_no"]) or {}
        rows.append({
            "line_id": f"L{ln['line_no']}",
            "tipo": ln.get("tipo"),
            "input_code": cm.get("input_code"),
            "code": cm.get("code"),
            "matched": cm.get("matched"),
            "status_label": "encontrado" if cm.get("matched") else "não encontrado no SILO",
            "not_found_reason": None if cm.get("matched") else reason_text(cm.get("reason_code")),
            "issuer_as_printed": st.get("issuer_as_printed"),
            "cnpj_securit": cm.get("cnpj_securit"),
            "numero_serie": cm.get("numero_serie"),
            "classe": cm.get("classe"),
            "n_series": cm.get("n_series"),
            "statement_vencimento": st.get("vencimento"),
            "registry_vencimento": cm.get("data_vencimento"),
            "statement_taxa": st.get("taxa_texto"),
            "registry_taxa": cm.get("taxa_juros"),
            "situacao": cm.get("situacao"),
            "rating": cm.get("classificacao_risco_atual"),
            "registry_as_of": cm.get("data_referencia"),
            "statement_preco_brl": st.get("preco_brl"),
            "statement_date": st.get("data_posicao"),
            "fund_mark_brl": cm.get("preco_marcacao_fundos_brl"),
            "fund_mark_period": cm.get("cda_period"),
            "fund_mark_cda": {"month": cm.get("cda_period")},  # printed as the CDA's month (values.py: key "month")
            "n_fundos": cm.get("n_fundos"),
            "price_gap_pct": cm.get("price_gap_pct"),
            "price_gap_abs_pct": cm.get("price_gap_abs_pct"),
            "price_gap_label": cm.get("price_gap_label"),
            "value_brl": pos.get("valor_brl"),
            "weight_pct": pos.get("portfolio_pct"),
            "flags": [{"code": f.get("code"), "label": BADGE_LABEL.get(f.get("code"), reason_text(f.get("code")))}
                      for f in cm.get("flags") or []],
            "provenance": _prov(cm.get("sources")),
        })
    if not rows and not any("credit_match" in ln for ln in eng["identification"].get("lines") or []):
        return None
    return {
        "label": "emissor como impresso no extrato; registro da CVM (CRA, CRI) e marcação dos fundos (CDA bloco 4, debêntures)",
        "price_note": "preço do extrato e marcação média ponderada dos fundos em datas diferentes: informativo, não é veredito de preço",
        "rate_note": ("a taxa do extrato é a que a corretora imprime para a posição; a do registro é a remuneração da série "
                      "como arquivada na CVM: as duas podem diferir e nenhuma é corrigida"),
        "lines": rows,
    }


def _liquidity_view(eng: dict) -> dict | None:
    """Engine 1.9: the liquidity ladder, copied (every figure is the engine's), line numbers as ``L<n>``."""
    lq = eng.get("liquidity")
    if not isinstance(lq, dict):
        return None
    buckets = []
    for b in lq.get("buckets") or []:
        buckets.append({
            "bucket_id": b.get("bucket_id"), "bucket": b.get("bucket"), "value_brl": b.get("value_brl"),
            "weight_pct": b.get("portfolio_pct"), "line_ids": [f"L{n}" for n in b.get("line_nos") or []],
            "lines": [{"line_id": f"L{x['line_no']}", "tipo": x.get("tipo"), "value_brl": x.get("value_brl"),
                       "qt_dia_pagto_resgate": x.get("qt_dia_pagto_resgate"), "tp_dia_pagto_resgate": x.get("tp_dia_pagto_resgate"),
                       "qt_dia_conversao_cota": x.get("qt_dia_conversao_cota"), "qt_dia_resgate_cotas": x.get("qt_dia_resgate_cotas"),
                       "terms_source": x.get("terms_source"), "terms_dt_comptc": x.get("terms_dt_comptc"),
                       "estrategia_corretora": x.get("estrategia_corretora"), "vencimento": x.get("vencimento"),
                       "provenance": _prov(x.get("sources"))}
                      for x in b.get("lines") or []],
        })
    return {
        "status": lq.get("status"),
        "reason": _codes_text(lq.get("reason_codes")) if lq.get("status") in ("partial", "unknown") else None,
        "basis": lq.get("basis"),
        "days_note": lq.get("days_note"),
        "note": lq.get("note"),
        "evaluated": lq.get("evaluated"),
        "buckets": buckets,
        "above_d30_parts": lq.get("above_d30_parts"),
        "above_d30_total_brl": lq.get("above_d30_total_brl"),
        "above_d30_total_pct": lq.get("above_d30_total_pct"),
    }


def _fee_line_view(line_no: int, f: dict, names: dict[int, str]) -> dict:
    d = f.get("disclosed") or {}
    h = f.get("headline") or {}
    e = f.get("estimate") or {}
    x = f.get("expense_ratio") or {}
    lb = f.get("lamina_beside") or {}
    xb = f.get("extrato_beside") or {}
    sf = f.get("scale_flag") or {}
    etf = h if h.get("kind") == "etf_site" else {}
    # engine 1.6 (catalog v57): the ETF's cotistas and PL, read from etf_site (not the headline), so they show whatever the
    # fee's state: a fee to check, or a CVM source first. Descriptive: never a fee, never summed.
    es = f.get("etf_site") or {}
    has_facts = es.get("nr_cotistas") is not None or es.get("pl_brl") is not None
    out = {
        "line_id": f"L{line_no}",
        "cnpj": f.get("cnpj"),
        "fund_name": f.get("fund_name") or names.get(line_no),
        "fee_status": f.get("fee_status"),
        "label": f.get("fee_status"),
        "reason": reason_text(f.get("reason_code")) if f.get("reason_code") else f.get("reason"),
        # engine 1.5: a newer lâmina's fee is the headline and a cost (summed, still to check); an ETF's fee from
        # etfsbrasil.com.br is the headline when no CVM source has one, with its own origin label (never "CVM")
        "disclosed_pct_year": h.get("rate_pct_year") if h.get("kind") in ("fixa", "lamina_mais_recente", "etf_site") else None,
        "disclosed_min_pct_year": h.get("rate_min_pct_year"),
        "disclosed_max_pct_year": h.get("rate_max_pct_year"),
        "disclosed_brl_year": h.get("per_year_brl"),
        "disclosed_origin": d.get("origin") or etf.get("origin"),
        "disclosed_origin_label": d.get("origin_label") or etf.get("origin_label"),
        "disclosed_as_of": d.get("as_of") or etf.get("as_of"),
        "disclosed_age_months": d.get("age_months"),
        "disclosed_stale": d.get("stale"),
        "disclosed_stale_label": d.get("stale_label"),
        "disclosed_scope_label": d.get("scope_label"),
        "filed_zero_label": d.get("filed_zero_label"),
        "filed_zero_pct": h.get("filed_pct_year") if h.get("kind") == "zero_informado" else None,
        "needs_manual_check": f.get("needs_manual_check"),
        "implausible_label": d.get("implausible_label"),
        "implausible_raw": d.get("adm_filed_raw") if d.get("implausible_filed") else None,
        # engine 1.4 (catalog v55, #552): the other document's fee beside the headline, as filed, never summed
        "fee_resolution": f.get("fee_resolution"),
        "lamina_newer_label": h.get("basis") if h.get("kind") == "lamina_mais_recente" else None,
        "sources_differ_label": h.get("sources_differ_label"),
        "etf_ticker": etf.get("ticker"),
        "etf_site_label": etf.get("basis"),
        "etf_site_check_label": etf.get("check_label"),
        "etf_site_raw": etf.get("filed_pct_year") if etf.get("check_label") else None,
        "etf_site_nr_cotistas": es.get("nr_cotistas"),
        "etf_site_pl_brl": es.get("pl_brl"),
        "etf_site_as_of": es.get("as_of") if has_facts else None,
        "etf_facts_label": es.get("facts_label") if has_facts else None,
        "lamina_beside_label": lb.get("label"),
        "lamina_beside_check_label": lb.get("check_label"),
        "lamina_beside_pct_year": lb.get("lamina_pct_year"),
        "lamina_beside_min_pct_year": lb.get("lamina_min_pct_year"),
        "lamina_beside_max_pct_year": lb.get("lamina_max_pct_year"),
        "lamina_beside_as_of": lb.get("as_of"),
        "lamina_beside_age_months": lb.get("age_months"),
        "lamina_beside_stale_label": lb.get("stale_label"),
        "extrato_beside_label": xb.get("label"),
        "extrato_beside_value": xb.get("filed_value"),
        "extrato_beside_as_of": xb.get("as_of"),
        "scale_flag_label": sf.get("label"),
        "scale_factor": sf.get("factor"),
        "extrato_lamina_ratio": sf.get("extrato_lamina_ratio"),
        "perf_as_filed": d.get("perf_as_filed"),
        "terms_as_filed": d.get("terms_as_filed"),
        "estimate_label": e.get("label"),
        "estimated_pct_year": e.get("adm_pct_year"),
        "estimated_brl_year": e.get("adm_per_year_brl"),
        "estimate_available": e.get("available"),
        "month": e.get("month"),
        "expense_ratio_pct": x.get("declared_pct"),
        "expense_ratio_period_from": (x.get("period") or {}).get("from"),
        "expense_ratio_period_to": (x.get("period") or {}).get("to"),
        "expense_ratio_note": x.get("note"),
        "findings": [
            {k: fi.get(k) for k in ("kind", "level", "text", "disclosed_pct_year", "estimate_pct_year", "difference_pp", "age_months", "raw_value",
                                    "lamina_pct_year", "factor", "extrato_lamina_ratio")
             if fi.get(k) is not None}
            for fi in f.get("findings") or []
        ],
        "provenance": _prov(f.get("position_value_source") and [f["position_value_source"]], h.get("sources"), d.get("sources"), e.get("sources"),
                            lb.get("sources"), xb.get("sources"), sf.get("sources"), es.get("sources") if has_facts else None),
    }
    return out


def _fees_view(eng: dict, names: dict[int, str]) -> dict:
    fees = eng["fees"]
    t = fees.get("totals") or {}
    lines = fees.get("lines") or []
    by_line = [_fee_line_view(ln["line_no"], ln, names) for ln in lines]
    fixed_total = t.get("adm_disclosed_fixed_per_year_brl")
    has_fixed = any((ln.get("headline") or {}).get("kind") in ("fixa", "lamina_mais_recente") for ln in lines)
    has_etf = any((ln.get("headline") or {}).get("kind") == "etf_site" and (ln.get("headline") or {}).get("counted_as_cost") for ln in lines)
    findings = []
    for bl in by_line:
        for fi in bl["findings"]:
            findings.append({**fi, "line_id": bl["line_id"], "provenance": bl["provenance"]})
    underlying = []
    for u in fees.get("underlying") or []:
        v = _fee_line_view(u["line_no"], u, names)
        v.update(parent_line_id=f"L{u['line_no']}", fund_cnpj=u.get("fund_cnpj"), label_not_added=u.get("label"), value_brl=u.get("value_brl"))
        underlying.append(v)
    return {
        "status": fees.get("status"),
        "basis": FEES_BASIS,
        "source_order": fees.get("source_order"),
        "total_disclosed_brl_year": fixed_total if has_fixed else None,
        "total_disclosed_pct_year": t.get("adm_disclosed_fixed_portfolio_pct") if has_fixed else None,
        # engine 1.5: ETF fees from etfsbrasil.com.br, summed apart, and the total of both
        "total_etf_site_brl_year": t.get("adm_etf_site_per_year_brl") if has_etf else None,
        "total_etf_site_pct_year": t.get("adm_etf_site_portfolio_pct") if has_etf else None,
        "total_fee_brl_year": t.get("adm_fee_per_year_brl") if has_etf and has_fixed else None,
        "total_fee_pct_year": t.get("adm_fee_portfolio_pct") if has_etf and has_fixed else None,
        "total_estimated_brl_year": t.get("estimate_adm_per_year_brl"),
        "weighted_estimated_pct_year": t.get("estimate_adm_portfolio_pct"),
        "estimate_label": fees.get("estimate_label"),
        "not_found_label": fees.get("not_found_label"),
        "totals_note": t.get("total_note"),
        "by_line": by_line,
        "findings": findings,
        "underlying": underlying,
        "summary": _fee_summary_view(fees.get("summary")),
        "comparison": _fee_comparison_view(fees.get("comparison")),
    }


def _fee_comparison_view(sm: dict | None) -> dict | None:
    if not isinstance(sm, dict):
        return None
    out = {k: v for k, v in sm.items() if k not in ("lines", "errors", "reason_codes")}
    out["by_line"] = [{**{k: v for k, v in r.items() if k not in ("line_no", "sources")},
                       "line_id": f"L{r['line_no']}", "provenance": _prov(r.get("sources"))}
                      for r in sm.get("lines") or []]
    return out


def _fee_summary_view(sm: dict | None) -> dict | None:
    """Engine 1.8: "Quanto a carteira paga em taxas", copied (every figure is the engine's), line numbers as ``L<n>``."""
    if not isinstance(sm, dict):
        return None
    out = {k: v for k, v in sm.items() if k != "not_included"}
    out["not_included"] = [{"id": x.get("id"), "text": x.get("text"), "line_ids": [f"L{n}" for n in x.get("line_nos") or []],
                            "value_brl": x.get("value_brl")} for x in sm.get("not_included") or []]
    return out


def _lookthrough_view(eng: dict, names: dict[int, str]) -> dict:
    lt = eng["look_through"]
    groups = sorted(lt["shared_exposure"]["groups"], key=lambda g: -abs(g.get("total_exposure_brl") or 0))
    shown = groups[:SHARED_GROUPS_SHOWN]
    same = [set(g.get("line_nos") or []) for g in (eng["identification"].get("same_identity_line_groups") or [])]
    shared = []
    for g in shown:
        legs = [
            {
                "line_id": f"L{ln['line_no']}",
                "via": "direto" if ln.get("direct") else f"{ln.get('linha_extrato')} (CDA)",
                "value_brl": ln.get("exposure_brl"),
            }
            for ln in g.get("lines", [])
        ]
        shared.append(
            {
                "key": g.get("label"),
                "name": g.get("label"),
                "level": LEVEL_BY_KIND.get(g.get("kind"), g.get("kind")),
                "total_brl": g.get("total_exposure_brl"),
                "total_pct": g.get("total_exposure_portfolio_pct"),
                # engine 1.7: every leg is one fund or ticker held through several statement lines: the same
                # position, not two holdings that overlap (never a finding)
                "same_position": any({ln["line_no"] for ln in g.get("lines", [])} <= sg for sg in same),
                "legs": legs,
                "provenance": _prov(g.get("sources")),
            }
        )
    top = [
        {
            "name": t.get("asset_name") or t.get("asset_key"),
            "value_brl": t.get("exposure_brl"),
            "weight_pct": t.get("portfolio_pct"),
            "provenance": _prov(t.get("sources")),
        }
        for t in lt.get("top_exposures") or []
    ]
    return {
        "tree": _lookthrough_tree(eng, names),
        "status": lt.get("status"),
        "month": lt.get("cda_month"),
        "max_depth": lt.get("max_depth"),
        "n_shared_groups": len(groups),
        "n_shared_groups_shown": len(shown),
        "economic_group_note": lt["shared_exposure"].get("note"),
        "shared_exposure": shared,
        "top_underlying": top,
    }


TREE_FUNDS = 5
TREE_ASSETS = 3


def _lookthrough_tree(eng: dict, names: dict[int, str]) -> list[dict]:
    """Engine 1.8 report: portfolio -> fund -> its largest underlying assets, for the look-through diagram.

    A selection only: the funds with an opened portfolio (largest statement value first) and, under each, its largest
    exposures by ``exposure_brl``; every weight is the engine's ``portfolio_pct``. A fund not opened, a negative
    exposure (a liability or a short derivative) and a fund with no exposures are left out, so the diagram shows only
    paths the engine has.
    """
    values = {p["line_no"]: p for p in eng["statement"]["positions"]}
    funds = []
    for ln in eng["look_through"].get("lines") or []:
        exps = [x for x in ln.get("exposures") or []
                if not x.get("not_opened_fund") and (x.get("exposure_brl") or 0) > 0 and x.get("portfolio_pct") is not None]
        pos = values.get(ln["line_no"])
        if not exps or pos is None:
            continue
        exps.sort(key=lambda x: -(x.get("exposure_brl") or 0))
        funds.append({
            "line_id": f"L{ln['line_no']}",
            "name": names.get(ln["line_no"]),
            "value_brl": pos.get("valor_brl"),
            "weight_pct": pos.get("portfolio_pct"),
            "n_exposures": len(exps),
            "children": [{"name": x.get("asset_name") or x.get("asset_key"), "value_brl": x.get("exposure_brl"),
                          "weight_pct": x.get("portfolio_pct")} for x in exps[:TREE_ASSETS]],
        })
    funds.sort(key=lambda f: -(f.get("value_brl") or 0))
    return funds[:TREE_FUNDS]


def _allocation_view(eng: dict) -> dict | None:
    """Engine 1.8: the portfolio by asset class (the statement's type of each line), copied."""
    a = eng.get("allocation")
    if not isinstance(a, dict):
        return None
    return {
        "status": a.get("status"),
        "basis": a.get("basis"),
        "buckets": [{"asset_class": c.get("asset_class"), "value_brl": c.get("value_brl"), "weight_pct": c.get("portfolio_pct"),
                     "line_ids": [f"L{n}" for n in c.get("line_nos") or []]} for c in a.get("classes") or []],
    }


def _risks_view(eng: dict) -> dict | None:
    """Engine 1.8: "Principais riscos", copied. ``table_only`` (the attention-level movement count) stays in the view
    for the table and is dropped from what the Redator sees; ``text_allowed`` tells the Revisor which rows the text
    may cite."""
    r = eng.get("risks")
    if not isinstance(r, dict):
        return None
    rows = []
    for row in r.get("rows") or []:
        out = {k: v for k, v in row.items() if k not in ("sources", "line_nos", "reason")}
        out["line_ids"] = [f"L{n}" for n in row.get("line_nos") or []]
        # a not-evaluated or not-applicable row says why with the fixed text of its code, never free text
        out["reason"] = row.get("reason") if row.get("status") != "avaliado" else None
        out["provenance"] = _prov(row.get("sources"))
        rows.append(out)
    return {
        "status": r.get("status"),
        "title": r.get("title"),
        "note": r.get("note"),
        "severity_rule": r.get("severity_rule"),
        "thresholds": r.get("thresholds"),
        "counts": r.get("counts"),
        "rows": rows,
    }


def _buckets(section: dict, rows_key: str, label_key: str, out_label: str, value_key: str = "value_brl") -> dict:
    prov = []
    for it in section.get("items") or []:
        for pid in _prov(it.get("sources")):
            if pid not in prov:
                prov.append(pid)
    return {
        "status": section.get("status"),
        "rules_version": section.get("rules_version"),
        "buckets": [
            {out_label: r.get(label_key), "value_brl": r.get(value_key), "weight_pct": r.get("portfolio_pct")}
            for r in section.get(rows_key) or []
        ],
        "provenance": prov[:6],
    }


def _restatements_view(eng: dict, names: dict[int, str]) -> dict:
    items = []
    for ln in eng["restatements"].get("lines") or []:
        for r in ln.get("restatements") or []:
            inad = next((lf for lf in r.get("leaves") or [] if lf.get("leaf") == "VL_CRED_EXISTE_INAD"), None)
            items.append(
                {
                    "line_id": f"L{ln['line_no']}",
                    "cnpj": ln.get("cnpj"),
                    "fund_name": names.get(ln["line_no"]),
                    "document": r.get("tipo_documento") or "informe",
                    "competencia": r.get("reference_date"),
                    "fnet_id_original": str(r.get("previous_fnet_id")) if r.get("previous_fnet_id") is not None else None,
                    "fnet_id_restatement": str(r.get("fnet_id")) if r.get("fnet_id") is not None else None,
                    "modalidade": r.get("modalidade"),
                    "delivered_at": (r.get("delivered_at") or "")[:10] or None,
                    "n_fields_changed": r.get("n_fields_changed"),
                    "assessment": r.get("assessment"),
                    "delinquency_old_brl": inad.get("old_num") if inad else None,
                    "delinquency_new_brl": inad.get("new_num") if inad else None,
                    "delinquency_change_brl": inad.get("delta") if inad else None,
                    "diff": [
                        {"leaf": lf.get("leaf"), "old_num": lf.get("old_num"), "new_num": lf.get("new_num"),
                         "change_brl": lf.get("delta"), "match_basis": lf.get("match_basis")}
                        for lf in r.get("leaves") or []
                    ],
                    "provenance": _prov(r.get("sources")),
                }
            )
    return {"status": eng["restatements"].get("status"), "items": items}


def _risk_view(eng: dict) -> dict:
    rs = eng["risk_signals"]
    screens = rs.get("screens") or []
    hits, not_run = [], []
    for ln in rs.get("lines") or []:
        for s in ln.get("signals") or []:
            hits.append({"screen": s.get("screen"), "line_id": f"L{ln['line_no']}", "cnpj": ln.get("cnpj"),
                         "provenance": _prov(s.get("sources"))})
    for sc in screens:
        if sc.get("status") == "unknown":
            reason = SCREEN_FAILED
            if str(sc.get("screen", "")).startswith("screen_dormant"):
                reason += f" {rs.get('dormant_coverage_note') or ''}".rstrip()
            not_run.append({"screen": sc.get("screen"), "reason": reason})
    return {
        "status": rs.get("status"),
        "screens_run": sum(1 for sc in screens if sc.get("status") == "complete"),
        "hits": hits,
        "not_run": not_run,
        "coverage_note": rs.get("dormant_coverage_note"),
        "provenance": [],
    }


def _movement_line_view(ln: dict) -> dict:
    return {
        "line_id": f"L{ln['line_no']}",
        "cnpj": ln.get("cnpj"),
        "fund_name": ln.get("fund_name"),
        "month": ln.get("month"),
        "class": ln.get("class"),
        "subclass": ln.get("subclass"),
        "class_as_filed": ln.get("class_as_filed"),
        "class_as_of": ln.get("class_as_of"),
        "n_peers": ln.get("n_peers"),
        "min_peers": ln.get("min_peers"),
        "own_value_pct": ln.get("own_value_pct"),
        "class_mean_pct": ln.get("class_mean_pct"),
        "class_sd_pct": ln.get("class_sd_pct"),
        "z": ln.get("z"),
        "level": ln.get("level"),
        "level_label": ln.get("level_label"),
        "investigator_trigger": ln.get("investigator_trigger"),
        # a reason SILO returned with the class comparison is data; a failure is a code's fixed text (engine 1.7)
        "reason": reason_text(ln.get("reason_code")) if ln.get("reason_code") else ln.get("reason"),
        "provenance": _prov(ln.get("sources")),
    }


def _movement_view(eng: dict) -> dict | None:
    """Movimento incomum. ``by_line`` holds every fund; ``table`` the funds at atencao or forte (the only place
    atencao appears); ``strong`` the funds at forte (the only fund-level path the text may cite);
    ``not_evaluated`` the funds with no verdict and their reason. Engine documents before 1.3 have no section."""
    mv = eng.get("movement")
    if not isinstance(mv, dict):
        return None
    by_line = [_movement_line_view(ln) for ln in mv.get("lines") or []]
    return {
        "status": mv.get("status"),
        "reason": _codes_text(mv.get("reason_codes")) if mv.get("status") in ("partial", "unknown") else None,
        "month": mv.get("month"),
        "definition": mv.get("definition"),
        "class_note": mv.get("class_note"),
        "levels_note": mv.get("levels_note"),
        "note": mv.get("note"),
        "min_peers": (mv.get("thresholds") or {}).get("min_peers"),
        "thresholds": mv.get("thresholds"),
        "counts": mv.get("counts"),
        "n_not_fund_lines": len(mv.get("not_applicable_lines") or []),
        "by_line": by_line,
        "table": [x for x in by_line if x["level"] in ("atencao", "forte")],
        "strong": [x for x in by_line if x["level"] == "forte"],
        "not_evaluated": [
            {k: x[k] for k in ("line_id", "cnpj", "fund_name", "month", "class_as_filed", "n_peers", "min_peers", "reason", "provenance")}
            for x in by_line
            if x["level"] == "nao_avaliado"
        ],
    }


RETURN_WINDOW_DROP = ("sources", "reason", "cdi_reason_code", "fee_reason_code", "null_reasons")
EQUIVALENT_WINDOW_DROP = ("sources", "class_source_reason", "etf_reason", "class_reason")


def _returns_view(eng: dict) -> dict | None:
    """Engine 1.10: the return per position, copied (every figure is the engine's), line numbers as ``L<n>``.

    ``windows`` and ``coverage`` become lists in the engine's window order (``12m``, ``6m``): a placeholder key must
    start with a letter, so ``windows.12m`` could not be cited. Every reason is the fixed text of its code. There is
    no portfolio total, mean, median or ranking in the engine, and none is made here."""
    r = eng.get("returns")
    if not isinstance(r, dict):
        return None
    order = [w.get("id") for w in r.get("windows") or []]
    lines = []
    for ln in r.get("lines") or []:
        fee = ln.get("fee") or {}
        wins = []
        for wid in order:
            w = (ln.get("windows") or {}).get(wid)
            if not isinstance(w, dict):  # keep the position: windows[0] is always 12 months, windows[1] 6
                w = {"status": "nao_avaliado", "status_label": "não avaliado", "reason_code": None}
            out = {k: v for k, v in w.items() if k not in RETURN_WINDOW_DROP}
            out.update(
                id=wid,
                reason=reason_text(w.get("reason_code")) if w.get("reason_code") or w.get("status") != "avaliado" else None,
                cdi_reason=reason_text(w.get("cdi_reason_code")) if w.get("cdi_reason_code") else None,
                fee_reason=reason_text(w.get("fee_reason_code")) if w.get("fee_reason_code") else None,
                # engine 1.12: why there is no "% do CDI" (only the difference in p.p. is shown)
                pct_of_cdi_reason=(reason_text(w.get("pct_of_cdi_reason_code"))
                                   if w.get("pct_of_cdi_reason_code") else None),
                provenance=_prov(w.get("sources")),
            )
            wins.append(out)
        lines.append({
            "line_id": f"L{ln['line_no']}", "instrument": ln.get("linha_extrato"), "tipo": ln.get("tipo"),
            "cnpj": ln.get("cnpj"), "ticker": ln.get("ticker"), "name": ln.get("name"), "value_brl": ln.get("valor_brl"),
            "basis": ln.get("basis"), "basis_label": ln.get("basis_label"),
            "without_distributions": ln.get("without_distributions"),
            "status": ln.get("status"), "status_label": ln.get("status_label"), "reason_code": ln.get("reason_code"),
            "reason": reason_text(ln.get("reason_code")) if ln.get("reason_code") else None,
            "fee": {"status": fee.get("status"), "reason_code": fee.get("reason_code"),
                    "reason": reason_text(fee.get("reason_code")) if fee.get("reason_code") else None,
                    "rate_pct_year": fee.get("rate_pct_year"), "kind": fee.get("kind"), "fee_status": fee.get("fee_status"),
                    "origin": fee.get("origin"), "as_of": fee.get("as_of")},
            "performance_fee_filed": ln.get("performance_fee_filed"),
            # engine 1.12: the filed benchmark as filed, and whether it is CDI-like (the reason is a fixed text)
            "benchmark": _benchmark_view(ln.get("benchmark")),
            "notes": list(ln.get("notes") or []),
            "windows": wins,
            "provenance": _prov(ln.get("sources"), fee.get("sources"),
                                *[((ln.get("windows") or {}).get(w) or {}).get("sources") for w in order]),
        })
    cdi = r.get("cdi") or {}
    cov = r.get("coverage") or {}
    return {
        "status": r.get("status"),
        "reason": _codes_text(r.get("reason_codes")) if r.get("status") in ("partial", "unknown") else None,
        "position_date": r.get("position_date"), "end_month": r.get("end_month"),
        "windows": [{k: w.get(k) for k in ("id", "months", "base_month", "end_month", "annualized", "fee_share_of_annual",
                                           "volatility_note", "note")} for w in r.get("windows") or []],
        "definition": r.get("definition"), "gross_note": r.get("gross_note"), "sharpe_drag_note": r.get("sharpe_drag_note"),
        "drawdown_note": r.get("drawdown_note"), "performance_note": r.get("performance_note"), "note": r.get("note"),
        "pct_of_cdi_note": r.get("pct_of_cdi_note"),
        "cdi": {"series": cdi.get("series"), "sgs_code": cdi.get("sgs_code"), "unit": cdi.get("unit"),
                "convention": cdi.get("convention"), "n_rates": cdi.get("n_rates"), "first_date": cdi.get("first_date"),
                "last_date": cdi.get("last_date"), "status": cdi.get("status"), "reason_code": cdi.get("reason_code"),
                "reason": reason_text(cdi.get("reason_code")) if cdi.get("reason_code") else None,
                "provenance": _prov(cdi.get("sources"))},
        "n_lines": r.get("n_lines"), "n_evaluated": r.get("n_evaluated"), "n_not_evaluated": r.get("n_not_evaluated"),
        "coverage": [{"id": wid, **{k: (cov.get(wid) or {}).get(k) for k in ("evaluated_value_brl", "coverage_portfolio_value_pct",
                                                                              "n_evaluated")}} for wid in order if wid in cov],
        "lines": lines,
    }


def _benchmark_view(b: dict | None) -> dict | None:
    if not isinstance(b, dict):
        return None
    return {"cdi_like": b.get("cdi_like"), "reason_code": b.get("reason_code"),
            "reason": reason_text(b.get("reason_code")) if b.get("reason_code") else None,
            "extrato": b.get("extrato"), "extrato_as_of": b.get("extrato_as_of"), "lamina": b.get("lamina"),
            "lamina_n": b.get("lamina_n"), "lamina_as_of": b.get("lamina_as_of"),
            "provenance": _prov(b.get("sources"))}


def _equivalents_view(eng: dict) -> dict | None:
    """Engine 1.12: the market equivalent per fund line, copied (every figure is the engine's), lines as ``L<n>``.

    Every reason is the fixed text of its code; the SQL's own reason never reaches the view. Labelled "equivalente de
    mercado; não é recomendação"; the view ranks nothing and says nothing is better."""
    e = eng.get("equivalents")
    if not isinstance(e, dict):
        return None
    lines = []
    for ln in e.get("lines") or []:
        etf = ln.get("etf")
        etf_v = None
        if isinstance(etf, dict):
            etf_v = {k: v for k, v in etf.items() if k != "sources"}
            etf_v["fee_reason"] = reason_text(etf.get("fee_reason_code")) if etf.get("fee_reason_code") else None
            etf_v["provenance"] = _prov(etf.get("sources"))
        wins = []
        for w in ln.get("windows") or []:
            out = {k: v for k, v in w.items() if k not in EQUIVALENT_WINDOW_DROP}
            out.update(
                etf_reason=reason_text(w.get("etf_reason_code")) if w.get("etf_reason_code") else None,
                etf_series_reason=reason_text(w.get("etf_series_reason_code")) if w.get("etf_series_reason_code") else None,
                fund_reason=reason_text(w.get("fund_reason_code")) if w.get("fund_reason_code") else None,
                class_reason=reason_text(w.get("class_reason_code")) if w.get("class_reason_code") else None,
                provenance=_prov(w.get("sources")),
            )
            wins.append(out)
        lines.append({
            "line_id": f"L{ln['line_no']}", "instrument": ln.get("linha_extrato"), "fund_name": ln.get("fund_name"),
            "cnpj": ln.get("cnpj"), "value_brl": ln.get("valor_brl"), "classe_anbima": ln.get("classe_anbima"),
            "fundo_cotas": ln.get("fundo_cotas"), "class_indices": ln.get("class_indices"), "n_etfs": ln.get("n_etfs"),
            "status": ln.get("status"), "reason_code": ln.get("reason_code"),
            "reason": reason_text(ln.get("reason_code")) if ln.get("reason_code") else None,
            "label": ln.get("label"), "etf": etf_v, "windows": wins,
            "provenance": _prov(ln.get("sources"), (etf or {}).get("sources"), *[w.get("sources") for w in ln.get("windows") or []]),
        })
    return {
        "status": e.get("status"),
        "reason": _codes_text(e.get("reason_codes")) if e.get("status") in ("partial", "unknown") else None,
        "label": e.get("label"), "as_of": e.get("as_of"), "end_month": e.get("end_month"),
        "windows": [{k: w.get(k) for k in ("id", "months", "base_month", "end_month", "annualized")} for w in e.get("windows") or []],
        "choice_note": e.get("choice_note"), "class_note": e.get("class_note"), "band_note": e.get("band_note"),
        "pl_label": e.get("pl_label"), "fee_label": e.get("fee_label"),
        "n_fund_lines": e.get("n_fund_lines"), "n_found": e.get("n_found"), "n_without": e.get("n_without"),
        "found_value_brl": e.get("found_value_brl"), "coverage_portfolio_value_pct": e.get("coverage_portfolio_value_pct"),
        "lines": lines,
    }


def _no_rule_source(x: Any) -> Any:
    """A tax node without its ``rule_source`` dicts and ``sources`` (the URL, the quote and the call stay in the engine
    JSON; the article is kept)."""
    if isinstance(x, dict):
        return {k: _no_rule_source(v) for k, v in x.items() if not k.endswith("rule_source") and k != "sources"}
    if isinstance(x, list):
        return [_no_rule_source(v) for v in x]
    return x


def _tax_view(eng: dict) -> dict | None:
    """Engine 1.11: fee paid and tax per position, copied (every figure is the engine's), line numbers as ``L<n>``.

    Every reason is the fixed text of its code. The R$ tax is the engine's ``estimate.tax_brl`` or nothing; the view
    holds no portfolio total of tax and picks neither pension regime."""
    t = eng.get("tax")
    if not isinstance(t, dict):
        return None
    lines = []
    for ln in t.get("lines") or []:
        tax = ln.get("tax") or {}
        est = tax.get("estimate") or {}
        fee = ln.get("fee") or {}
        tax_v = _no_rule_source({k: v for k, v in tax.items() if k not in ("estimate", "reason")})
        tax_v["reason"] = reason_text(tax.get("reason_code")) if tax.get("reason_code") else None
        tax_v["act"] = (tax.get("rule_source") or {}).get("act")
        tax_v["estimate"] = {**_no_rule_source({k: v for k, v in est.items() if k != "reason"}),
                             "reason": reason_text(est.get("reason_code")) if est.get("reason_code") else None}
        lines.append({
            "line_id": f"L{ln['line_no']}", "instrument": ln.get("linha_extrato"), "tipo": ln.get("tipo"),
            "value_brl": ln.get("valor_brl"),
            "fee": _no_rule_source(fee),
            "holding": _no_rule_source(ln.get("holding") or {}),
            "tax": tax_v,
            "pension": _no_rule_source(ln.get("pension")) if ln.get("pension") else None,
            "optimization": _no_rule_source(ln.get("optimization") or []),
            "iof": _no_rule_source(ln.get("iof")) if ln.get("iof") else None,
            "a_conferir": [{k: a.get(k) for k in ("id", "text", "label", "decides_rate")} for a in ln.get("a_conferir") or []],
            "provenance": _prov(fee.get("sources"), est.get("sources")),
        })
    person = t.get("person") or {}
    labels = {k: v for k, v in (t.get("labels") or {}).items() if k != "date_missing"}  # a template with {lo}/{hi}
    return {
        "status": t.get("status"),
        "reason": _codes_text(t.get("reason_codes")) if t.get("status") in ("partial", "unknown") else None,
        "position_date": t.get("position_date"), "note": t.get("note"), "labels": labels,
        "rules_note": t.get("rules_note"),
        "rules_files": [{k: f.get(k) for k in ("file", "instrument", "version", "valid_from", "valid_to", "in_force", "not_verified")}
                        for f in t.get("rules_files") or []],
        "not_covered": [{"tipo": x.get("tipo"), "text": x.get("text")} for x in t.get("not_covered") or []],
        "person": {
            "flags": [{**{k: f.get(k) for k in ("id", "flagged", "rate_pct", "text", "article", "computed")},
                       "line_ids": [f"L{n}" for n in f.get("line_nos") or []]} for f in person.get("flags") or []],
            "minimum_tax": _no_rule_source(person.get("minimum_tax")) if person.get("minimum_tax") else None,
            "a_conferir": _no_rule_source(person.get("a_conferir") or []),
        },
        "n_lines": t.get("n_lines"), "n_with_rule": t.get("n_with_rule"), "n_without_rule": t.get("n_without_rule"),
        "n_tax_estimated": t.get("n_tax_estimated"), "n_fee_estimated": t.get("n_fee_estimated"),
        "lines": lines,
    }


def _codes_text(codes: list[str] | None) -> str:
    texts = list(dict.fromkeys(reason_text(c) for c in codes or []))
    return "; ".join(texts) if texts else GENERIC_GAP


def _section_entry(st: dict) -> dict:
    """A section's status with the fixed text of its reason codes (engine 1.7); never the engine's free text."""
    out = {"status": st["status"], "reason_codes": list(st.get("reason_codes") or [])}
    if st["status"] in ("partial", "unknown"):
        out["reason"] = _codes_text(out["reason_codes"])
    return out


def _sections_view(eng: dict, lines: list[dict]) -> dict:
    ss = eng["section_status"]
    mapping = {"identification": "identification", "fees": "fees", "lookthrough": "look_through", "indexer": "indexer",
               "sector": "sector", "restatements": "restatements", "risk_screens": "risk_signals"}
    for key in ("concentration", "allocation", "liquidity", "risks", "returns", "tax", "equivalents"):
        if key in ss:
            mapping[key] = key
    out: dict[str, Any] = {k: _section_entry(ss[v]) for k, v in mapping.items()}
    if isinstance(eng.get("movement"), dict):
        out["abnormal_movement"] = _section_entry(ss["movement"])
    else:
        out["abnormal_movement"] = {"status": "unknown", "reason": eng["risk_signals"].get("abnormal_movement")}
    out["material_restatement"] = {"status": "unknown", "reason": eng["restatements"].get("assessment")}
    out["economic_group"] = {"status": "unknown", "reason": eng["look_through"]["shared_exposure"].get("note")}
    out["benchmarks"] = {"status": "unknown", "reason": "fora do escopo desta versão (variância mínima e contribuição igual de risco ainda não calculadas)"}
    tes = [ln["line_id"] for ln in lines if ln["asset_type"] == "titulo_publico"]
    if tes:
        out["ntnb_price"] = {"status": "unknown", "reason": TESOURO_NO_PRICE, "affects": tes}
    unk = [ln["line_id"] for ln in lines if ln["identification"]["status"] == "unknown"]
    if unk and out["identification"]["status"] == "complete":
        out["identification"]["status"] = "partial"
        out["identification"]["reason"] = reason_text("linhas_nao_identificadas")
    return out


def _concentration_view(eng: dict) -> dict | None:
    """Engine 1.7: issuer as printed, maturity ladder and the FGC check, copied (every figure is the engine's)."""
    c = eng.get("concentration")
    if not isinstance(c, dict):
        return None
    iss, lad, fgc = c.get("issuer") or {}, c.get("maturity_ladder") or {}, c.get("fgc") or {}

    def ids(nos: list[int] | None) -> list[str]:
        return [f"L{n}" for n in nos or []]

    return {
        "status": c.get("status"),
        "issuer": {
            "status": iss.get("status"), "label": iss.get("label"), "basis": iss.get("basis"),
            "direct_credit_value_brl": iss.get("direct_credit_value_brl"),
            "direct_credit_weight_pct": iss.get("direct_credit_portfolio_pct"),
            "groups": [{"issuer": g.get("issuer_as_printed"), "line_ids": ids(g.get("line_nos")), "tipos": g.get("tipos"),
                        "value_brl": g.get("value_brl"), "weight_pct": g.get("portfolio_pct"),
                        "share_of_direct_credit_pct": g.get("direct_credit_pct")} for g in iss.get("groups") or []],
            "not_printed_line_ids": ids(iss.get("not_printed_line_nos")),
        },
        "maturity_ladder": {
            "status": lad.get("status"), "basis": lad.get("basis"),
            "buckets": [{"bucket": b.get("bucket"), "value_brl": b.get("value_brl"), "weight_pct": b.get("portfolio_pct"),
                         "line_ids": ids(b.get("line_nos"))} for b in lad.get("buckets") or []],
            "by_year": [{"year": y.get("year"), "value_brl": y.get("value_brl"), "weight_pct": y.get("portfolio_pct"),
                         "line_ids": ids(y.get("line_nos"))} for y in lad.get("by_year") or []],
            "no_maturity": {"bucket": (lad.get("no_maturity") or {}).get("bucket"),
                            "value_brl": (lad.get("no_maturity") or {}).get("value_brl"),
                            "weight_pct": (lad.get("no_maturity") or {}).get("portfolio_pct")},
        },
        "fgc": {
            "status": fgc.get("status"), "label": fgc.get("label"), "rule": fgc.get("rule"), "scope_note": fgc.get("scope_note"),
            "limit_brl": fgc.get("limit_brl"), "n_above_limit": fgc.get("n_above_limit"),
            "issuers": [{"issuer": g.get("issuer_as_printed"), "line_ids": ids(g.get("line_nos")), "tipos": g.get("tipos"),
                         "eligible_value_brl": g.get("eligible_value_brl"), "above_limit": g.get("above_limit"),
                         "excess_brl": g.get("excess_brl")} for g in fgc.get("issuers") or []],
        },
        "manager": _manager_view(c.get("manager") or {}),
        "fund_liquidity": {"status": (c.get("fund_liquidity") or {}).get("status"),
                           "reason": reason_text((c.get("fund_liquidity") or {}).get("reason_code"))},
    }


def _manager_view(m: dict) -> dict:
    """Engine 1.9: the fund value by manager (``gestor_id``, the filed value), copied; 1.8 had only a status."""
    out = {"status": m.get("status"), "reason": reason_text(m.get("reason_code")) if m.get("reason_code") else None}
    if "groups" not in m:
        out["reason"] = reason_text(m.get("reason_code"))
        return out
    out.update({
        "label": m.get("label"), "basis": m.get("basis"),
        "fund_value_brl": m.get("fund_value_brl"), "fund_value_weight_pct": m.get("fund_value_portfolio_pct"),
        "groups": [{"gestor_id": g.get("gestor_id"), "gestor_name": g.get("gestor_name"), "line_ids": [f"L{n}" for n in g.get("line_nos") or []],
                    "value_brl": g.get("value_brl"), "weight_pct": g.get("portfolio_pct"), "share_of_funds_pct": g.get("fund_value_pct"),
                    "provenance": _prov(g.get("sources"))} for g in m.get("groups") or []],
        "without_gestor_line_ids": [f"L{n}" for n in m.get("without_gestor_line_nos") or []],
        "without_gestor_value_brl": m.get("without_gestor_value_brl"),
    })
    return out


def _gaps_view(eng: dict, sections: dict, fees: dict, risk: dict, movement: dict | None) -> list[dict]:
    """"O que não foi possível avaliar" (engine 1.7): one short line per gap, written without the LLM.

    Fixed texts only; the unidentified lines are grouped by reason, with the group's value as the engine computed it.
    """
    gaps: list[dict] = []

    def add(title: str, text: str, line_ids: list[str] | None = None, value_brl: Any = None, weight_pct: Any = None) -> None:
        gaps.append({"title": title, "text": text.rstrip(". "), "line_ids": line_ids or [], "value_brl": value_brl,
                     "weight_pct": weight_pct})

    ident = eng.get("identification") or {}
    for g in ident.get("unknown_groups") or []:
        add("Linhas não identificadas", reason_text(g.get("reason_code")), [f"L{n}" for n in g.get("line_nos") or []],
            g.get("value_brl"), g.get("portfolio_pct"))
    ce = ident.get("cnpj_extrato_line_nos") or []
    if ce:
        add("Fundos pelo CNPJ do extrato", reason_text("cnpj_extrato"), [f"L{n}" for n in ce])
    by_status: dict[str, list[str]] = {}
    for b in fees.get("by_line") or []:
        if b.get("fee_status") and b.get("disclosed_pct_year") is None and b.get("disclosed_min_pct_year") is None:
            by_status.setdefault(str(b["fee_status"]), []).append(b["line_id"])
    for status, ids in by_status.items():
        add("Taxa", status, ids)
    failed_screens = [n["screen"] for n in risk.get("not_run") or []]
    if failed_screens:
        add("Telas de risco", SCREEN_FAILED + ": " + ", ".join(failed_screens))
    if any(str(sc.get("screen", "")).startswith("screen_dormant") for sc in (eng.get("risk_signals") or {}).get("screens") or []):
        # a permanent coverage limit of the dormant-funds screen, a fixed engine text (never an error)
        note = (eng.get("risk_signals") or {}).get("dormant_coverage_note")
        if note:
            add("Fundos dormentes", note)
    if movement and (movement.get("counts") or {}).get("nao_avaliado"):
        add("Movimento incomum", reason_text("fundos_nao_avaliados"),
            [x["line_id"] for x in movement.get("not_evaluated") or []])
    # engines 1.10 and 1.11: the lines without a return or without a tax rule, grouped by code (no value: the view sums
    # nothing the engine did not)
    for title, block, codes_of in ((SECTION_TITLES_PT["returns"], eng.get("returns"), _return_gap_codes),
                                   (SECTION_TITLES_PT["tax"], eng.get("tax"), _tax_gap_codes),
                                   (SECTION_TITLES_PT["equivalents"], eng.get("equivalents"), _equivalent_gap_codes)):
        groups: dict[str, list[str]] = {}
        for ln in (block.get("lines") or []) if isinstance(block, dict) else []:
            for code in codes_of(ln):
                if f"L{ln['line_no']}" not in groups.setdefault(code, []):
                    groups[code].append(f"L{ln['line_no']}")
        for code, ids in groups.items():
            add(title, reason_text(code), ids)
    for key in ("fees", "lookthrough", "restatements", "risk_screens", "abnormal_movement", "concentration", "liquidity",
                "returns", "tax", "equivalents"):
        sec = sections.get(key) or {}
        if key == "risk_screens" and failed_screens:
            continue  # the screens that did not run are a line above
        if sec.get("status") in ("partial", "unknown"):
            for code in sec.get("reason_codes") or [None]:
                if code in COVERED_ABOVE:
                    continue  # already a line above, with its lines
                add(SECTION_TITLES_PT.get(key, key), reason_text(code))
    for key in ("material_restatement", "economic_group", "benchmarks", "ntnb_price"):
        sec = sections.get(key)
        if sec:
            add(EXTRA_GAP_TITLES[key], sec.get("reason") or GENERIC_GAP, sec.get("affects"))
    return gaps


COVERED_ABOVE = ("sem_taxa_divulgada", "taxa_a_conferir", "fundos_nao_avaliados", "linhas_nao_identificadas",
                 "riscos_nao_avaliados", "linhas_sem_retorno", "imposto_linhas_sem_regra",
                 # engine 1.12: the equivalents block's line codes are grouped above with their lines
                 "equivalente_fora_escopo", "equivalente_sem_classe", "equivalente_sem_par", "equivalente_sem_etf",
                 "equivalente_sem_pl", "equivalente_sem_linha", "equivalente_sem_retorno", "distribuicao_classe_nao_avaliada")


def _return_gap_codes(ln: dict) -> list[str]:
    """A line not evaluated gives its code; an evaluated line gives the code of each window it could not evaluate."""
    if ln.get("status") != "avaliado":
        return [ln["reason_code"]] if ln.get("reason_code") else []
    return [w["reason_code"] for w in (ln.get("windows") or {}).values()
            if isinstance(w, dict) and w.get("status") != "avaliado" and w.get("reason_code")]


def _equivalent_gap_codes(ln: dict) -> list[str]:
    """A fund line with no equivalent gives its code; a found one gives the codes of the windows it could not compare."""
    if ln.get("status") != "encontrado":
        return [ln["reason_code"]] if ln.get("reason_code") else []
    return [c for w in ln.get("windows") or [] for c in (w.get("etf_reason_code"), w.get("class_reason_code")) if c]


def _tax_gap_codes(ln: dict) -> list[str]:
    t = ln.get("tax") or {}
    return [t["reason_code"]] if t.get("status") == "sem_regra" and t.get("reason_code") else []
FUND_ASSET_TYPES = ("fundo", "fidc", "fii", "fip", "etf", "cota_listada")


def _chart_and_risk_gaps(eng: dict, view: dict) -> list[dict]:
    """Engine 1.8: why a chart is not drawn, and every risk not evaluated, as fixed texts (never free text)."""
    out: list[dict] = []

    def add(title: str, text: str, line_ids: list[str] | None = None) -> None:
        out.append({"title": title, "text": text.rstrip(". "), "line_ids": line_ids or [], "value_brl": None, "weight_pct": None})

    already = set(((view.get("sections") or {}).get("concentration") or {}).get("reason_codes") or [])
    for row in (view.get("risks") or {}).get("rows") or []:
        if row.get("status") == "nao_avaliado" and row.get("reason_code") not in already:
            add(f"Principais riscos: {row.get('risk')}", row.get("reason") or GENERIC_GAP)
    c = view.get("concentration") or {}
    if c and (c.get("maturity_ladder") or {}).get("status") != "complete":
        add("Gráfico de vencimentos", reason_text("sem_vencimento"))
    if c and (c.get("issuer") or {}).get("status") != "complete":
        add("Gráfico de emissores", reason_text("sem_credito_direto"))
    fund_lines = [ln["line_id"] for ln in view.get("lines") or [] if ln.get("asset_type") in FUND_ASSET_TYPES]
    if fund_lines and not (view.get("lookthrough") or {}).get("tree"):
        add("Diagrama do look-through", reason_text("sem_carteira_dos_fundos"), fund_lines)
    by_line = (view.get("fees") or {}).get("by_line") or []
    if by_line and not any(b.get("disclosed_brl_year") is not None for b in by_line):
        add("Gráfico do custo em taxas", reason_text("sem_taxa_em_reais"))
    # engine 1.9: the manager chart and the liquidity ladder
    m = c.get("manager") or {}
    if fund_lines and "groups" in m and not m.get("groups"):
        add("Gráfico por gestora", reason_text("sem_gestor"), fund_lines)
    return out
EXTRA_GAP_TITLES = {
    "material_restatement": "Materialidade das reapresentações",
    "economic_group": "Grupo econômico",
    "benchmarks": "Comparação com carteiras de referência",
    "ntnb_price": "Preço do Tesouro Direto",
}


def _provenance_view(eng: dict) -> tuple[list[dict], dict[str, str]]:
    dates: dict[int, str] = {}

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            if x.get("tool") not in (None, "statement") and x.get("call_id") is not None and x.get("data_date"):
                dates.setdefault(x["call_id"], x["data_date"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    for key in ("identification", "fees", "look_through", "indexer", "sector", "restatements", "risk_signals", "movement",
                "returns", "tax", "equivalents"):
        walk(eng.get(key))
    prov = []
    by_source: dict[str, str] = {}
    for p in eng["provenance"]:
        src = SOURCE_BY_TOOL.get(p["tool"], "CVM")
        when = dates.get(p["call_id"])
        if when is None and p["tool"] != "portfolio_equivalents":  # its date is the ETF snapshot's or none, never the run's
            when = (p.get("requested_at_utc") or "")[:10] or None
        # engine 1.7: the request params and any error text stay in the engine JSON; the report's view has neither
        prov.append({"id": p.get("id") or f"p{p['call_id']}", "endpoint": f"api.{p['tool']}", "source": src,
                     "data_date": when, "failed": p.get("error") is not None})
        if when and (src not in by_source or when > by_source[src]):
            by_source[src] = when
    # engine 1.5: an ETF's fee comes through portfolio_fees but from etfsbrasil.com.br, a third-party site; it is
    # listed as its own source with the snapshot date, so the report never dates or credits it as CVM's
    fees = eng.get("fees") or {}
    fee_lines = [*(fees.get("lines") or []), *(fees.get("underlying") or [])]
    site_dates = [str(h["as_of"]) for h in ((ln.get("headline") or {}) for ln in fee_lines)
                  if h.get("kind") == "etf_site" and h.get("as_of")]
    # engine 1.6: the site's cotistas and PL date it too, whatever the fee's state
    site_dates += [str(es["as_of"]) for es in ((ln.get("etf_site") or {}) for ln in fee_lines)
                   if es.get("as_of") and (es.get("nr_cotistas") is not None or es.get("pl_brl") is not None)]
    # engine 1.12: the equivalent ETF's PL and fee are the same site's, dated by their snapshots
    for ln in (eng.get("equivalents") or {}).get("lines") or []:
        etf = ln.get("etf") or {}
        site_dates += [str(etf[k]) for k in ("pl_as_of", "fee_as_of") if etf.get(k)]
    if site_dates:
        by_source["ETFSBRASIL"] = max(site_dates)
    return prov, by_source


def is_engine_output(doc: dict) -> bool:
    return str(doc.get("schema_version", "")).startswith("1.") and "statement" in doc and "identification" in doc


def to_view(eng: dict) -> dict:
    """The report's view of an engine document (schema 1.x)."""
    positions = eng["statement"]["positions"]
    idents = {ln["line_no"]: ln for ln in eng["identification"]["lines"]}
    lines = [_line_view(p, idents.get(p["line_no"]) or {}) for p in positions]
    names = {p["line_no"]: (idents.get(p["line_no"], {}).get("identity") or {}).get("name") or p.get("linha_extrato") for p in positions}
    counts = eng["identification"]["counts"]
    provenance, data_dates = _provenance_view(eng)
    view = {
        "schema_version": VIEW_VERSION,
        "engine_schema_version": eng.get("schema_version"),
        "generated_at": eng.get("generated_at_utc"),
        "valuation_date": eng["statement"].get("position_date"),
        "masked": True,
        "illustrative": eng["engine"].get("client") == "fake",  # canned rows: the report says so on its cover
        "portfolio": {
            "total_brl": eng["statement"].get("sum_of_lines_brl"),
            "n_lines": eng["statement"].get("n_lines"),
            "n_identified": counts.get("identified"),
            "n_ambiguous": counts.get("ambiguous"),
            "n_unknown": counts.get("unknown"),
            "n_lines_read": eng["statement"].get("n_lines_read"),
            "n_positions_merged": eng["statement"].get("n_positions_merged"),
            "notes": eng["statement"].get("notes"),
        },
        "lines": lines,
        "fees": _fees_view(eng, names),
        "lookthrough": _lookthrough_view(eng, names),
        "indexer": _buckets(eng["indexer"], "classes", "indexer_class", "indexer"),
        "sector": _buckets(eng["sector"], "sectors", "sector", "sector"),
        "restatements": _restatements_view(eng, names),
        "risk_screens": _risk_view(eng),
        "sections": _sections_view(eng, lines),
        "provenance": provenance,
        "data_dates": data_dates,
    }
    movement = _movement_view(eng)
    if movement is not None:
        view["movement"] = movement
    concentration = _concentration_view(eng)
    if concentration is not None:
        view["concentration"] = concentration
    allocation = _allocation_view(eng)
    if allocation is not None:
        view["allocation"] = allocation
    risks = _risks_view(eng)
    if risks is not None:
        view["risks"] = risks
    credit = _credit_view(eng)
    if credit is not None:
        view["credit"] = credit
    liquidity = _liquidity_view(eng)
    if liquidity is not None:
        view["liquidity"] = liquidity
    returns = _returns_view(eng)
    if returns is not None:
        view["returns"] = returns
    tax = _tax_view(eng)
    if tax is not None:
        view["tax"] = tax
    equivalents = _equivalents_view(eng)
    if equivalents is not None:
        view["equivalents"] = equivalents
    view["gaps"] = _gaps_view(eng, view["sections"], view["fees"], view["risk_screens"], movement)
    view["gaps"] += _chart_and_risk_gaps(eng, view)
    return view
