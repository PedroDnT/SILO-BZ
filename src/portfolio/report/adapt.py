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

VIEW_VERSION = "report-view-1"
SHARED_GROUPS_SHOWN = 12

# The report names the source of each tool for its footer and the Revisor's citation rule.
SOURCE_BY_TOOL = {
    "lookup": "CVM", "company_financials": "CVM", "portfolio_resolve": "CVM", "portfolio_fees": "CVM",
    "portfolio_lookthrough": "CVM", "fidc_portfolio": "CVM", "quote_latest": "B3", "short_interest": "B3",
    "fund_restatements": "FNET", "fund_restatement_diff": "FNET", "screen_restatements": "FNET",
    "screen_late_filers": "FNET",
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
    if tipo in ("FII", "ETF"):
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
    else:
        method = chosen.get("match_kind") or ("nome_abreviado_desempate_por_cota" if tiebreak else None)
    ident_view: dict[str, Any] = {
        "status": view_status,
        "method": method,
        "reason": ident.get("reason"),
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
        "identification": ident_view,
        "provenance": _prov(
            (ident.get("valuation") or {}).get("sources"),
            fm.get("sources"),
            ((ident.get("ticker_match") or {}).get("lookup") or {}).get("sources"),
            ((ident.get("ticker_match") or {}).get("reference_quote") or {}).get("sources"),
        ),
    }


def _fee_line_view(line_no: int, f: dict, names: dict[int, str]) -> dict:
    d = f.get("disclosed") or {}
    h = f.get("headline") or {}
    e = f.get("estimate") or {}
    x = f.get("expense_ratio") or {}
    out = {
        "line_id": f"L{line_no}",
        "cnpj": f.get("cnpj"),
        "fund_name": f.get("fund_name") or names.get(line_no),
        "fee_status": f.get("fee_status"),
        "label": f.get("fee_status"),
        "reason": f.get("reason"),
        "disclosed_pct_year": h.get("rate_pct_year") if h.get("kind") == "fixa" else None,
        "disclosed_min_pct_year": h.get("rate_min_pct_year"),
        "disclosed_max_pct_year": h.get("rate_max_pct_year"),
        "disclosed_brl_year": h.get("per_year_brl"),
        "disclosed_origin": d.get("origin"),
        "disclosed_origin_label": d.get("origin_label"),
        "disclosed_as_of": d.get("as_of"),
        "disclosed_age_months": d.get("age_months"),
        "disclosed_stale": d.get("stale"),
        "disclosed_stale_label": d.get("stale_label"),
        "disclosed_scope_label": d.get("scope_label"),
        "filed_zero_label": d.get("filed_zero_label"),
        "filed_zero_pct": h.get("filed_pct_year") if h.get("kind") == "zero_informado" else None,
        "needs_manual_check": f.get("needs_manual_check"),
        "implausible_label": d.get("implausible_label"),
        "implausible_raw": d.get("adm_filed_raw") if d.get("implausible_filed") else None,
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
            {k: fi.get(k) for k in ("kind", "level", "text", "disclosed_pct_year", "estimate_pct_year", "difference_pp", "age_months", "raw_value")
             if fi.get(k) is not None}
            for fi in f.get("findings") or []
        ],
        "provenance": _prov(f.get("position_value_source") and [f["position_value_source"]], h.get("sources"), d.get("sources"), e.get("sources")),
    }
    return out


def _fees_view(eng: dict, names: dict[int, str]) -> dict:
    fees = eng["fees"]
    t = fees.get("totals") or {}
    lines = fees.get("lines") or []
    by_line = [_fee_line_view(ln["line_no"], ln, names) for ln in lines]
    fixed_total = t.get("adm_disclosed_fixed_per_year_brl")
    has_fixed = any((ln.get("headline") or {}).get("kind") == "fixa" for ln in lines)
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
        "total_estimated_brl_year": t.get("estimate_adm_per_year_brl"),
        "weighted_estimated_pct_year": t.get("estimate_adm_portfolio_pct"),
        "estimate_label": fees.get("estimate_label"),
        "not_found_label": fees.get("not_found_label"),
        "totals_note": t.get("total_note"),
        "by_line": by_line,
        "findings": findings,
        "underlying": underlying,
    }


def _lookthrough_view(eng: dict, names: dict[int, str]) -> dict:
    lt = eng["look_through"]
    groups = sorted(lt["shared_exposure"]["groups"], key=lambda g: -abs(g.get("total_exposure_brl") or 0))
    shown = groups[:SHARED_GROUPS_SHOWN]
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
        "status": lt.get("status"),
        "month": lt.get("cda_month"),
        "max_depth": lt.get("max_depth"),
        "n_shared_groups": len(groups),
        "n_shared_groups_shown": len(shown),
        "economic_group_note": lt["shared_exposure"].get("note"),
        "shared_exposure": shared,
        "top_underlying": top,
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
            reason = sc.get("reason") or "tela recusada"
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


def _sections_view(eng: dict, lines: list[dict]) -> dict:
    ss = eng["section_status"]
    mapping = {"identification": "identification", "fees": "fees", "lookthrough": "look_through", "indexer": "indexer",
               "sector": "sector", "restatements": "restatements", "risk_screens": "risk_signals"}
    out: dict[str, Any] = {k: {"status": ss[v]["status"], **({"reason": ss[v]["reason"]} if ss[v].get("reason") else {})}
                           for k, v in mapping.items()}
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
    return out


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

    for key in ("identification", "fees", "look_through", "indexer", "sector", "restatements", "risk_signals"):
        walk(eng.get(key))
    prov = []
    by_source: dict[str, str] = {}
    for p in eng["provenance"]:
        src = SOURCE_BY_TOOL.get(p["tool"], "CVM")
        when = dates.get(p["call_id"]) or (p.get("requested_at_utc") or "")[:10] or None
        prov.append({"id": p.get("id") or f"p{p['call_id']}", "endpoint": f"api.{p['tool']}", "params": p.get("args"),
                     "source": src, "data_date": when, "error": p.get("error")})
        if when and (src not in by_source or when > by_source[src]):
            by_source[src] = when
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
    return view
