"""Block 17 (engine 1.8): "Principais riscos", one row per risk, read from the sections the engine already built.

Deterministic: every value is a field of another section (its path in ``source_path``) or a sum of statement values
(credit not covered by the FGC, the indexer groups), every severity comes from the fixed thresholds below (strictly
above the threshold), and every explanation is a fixed text. A risk whose input is missing is a row with
``status = "nao_avaliado"`` and a fixed reason; a risk that does not apply to this portfolio (no direct credit, no FIDC
or FII) is ``nao_se_aplica``. None is omitted. No row is a forecast or a recommendation.

The movement row keeps the owner's rule: a fund at the attention level is a table row, never text. Its count of such
funds sits under ``table_only`` (a key the Redator never sees) and the row has ``text_allowed = false`` when that is
what sets its severity, so the Revisor removes any sentence that cites it.

Engine 1.9 adds the direct credit identified by its registry code (CRA/CRI outside "Adimplente", a maturity that
differs from the CVM registry, the statement's price against the funds' mark for debêntures), the largest fund manager
and the liquidity above D+30, which replaces the "não avaliado" liquidity row when the funds' terms came back.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from src.portfolio.common import (
    REASON_TEXT,
    STATUS_COMPLETE,
    STATUS_NOT_APPLICABLE as STATUS_NOT_APPLICABLE_SECTION,
    STATUS_UNKNOWN,
    UNCLASSIFIED,
    Section,
    brl,
    dec,
    pct,
)

TITLE = "Principais riscos"
EVALUATED, NOT_EVALUATED, NOT_APPLICABLE = "avaliado", "nao_avaliado", "nao_se_aplica"
STATUS_LABEL = {EVALUATED: "avaliado", NOT_EVALUATED: "não avaliado", NOT_APPLICABLE: "não se aplica"}
SEVERITY_LABEL = {"atencao": "atenção", "moderado": "moderado", "baixo": "baixo"}
SEVERITY_RANK = {"atencao": 0, "moderado": 1, "baixo": 2}
SEVERITY_RULE = (
    "semáforo fixo: atenção quando o valor é estritamente maior que o limite de atenção; moderado quando é estritamente "
    "maior que o limite moderado; baixo nos demais casos. Os limites são fixos no motor do SILO "
    "e são os mesmos para toda carteira"
)
NOTE = "Fatos da carteira com um limite fixo; não é previsão de mercado nem recomendação de compra, venda ou manutenção."

# Fixed thresholds (owner's brief, 2026-10-04). Units: _pct in percent of the portfolio, _count a count.
THRESHOLDS: dict[str, dict[str, float | int | None]] = {
    "concentracao_emissor": {"atencao_above_pct": 10.0, "moderado_above_pct": 5.0},
    "concentracao_fundo": {"atencao_above_pct": 25.0, "moderado_above_pct": 15.0},
    "credito_privado": {"atencao_above_pct": 30.0, "moderado_above_pct": 15.0},
    "credito_sem_fgc": {"atencao_above_pct": 20.0, "moderado_above_pct": 10.0},
    "fgc_acima_limite": {"atencao_above_count": 0, "moderado_above_count": None},
    "vencimentos": {"atencao_above_pct": 40.0, "moderado_above_pct": 20.0},
    "indexador": {"atencao_above_pct": 80.0, "moderado_above_pct": 60.0},
    "reapresentacoes": {"atencao_above_count": None, "moderado_above_count": 0},
    "movimento_anormal": {"atencao_above_count": 0, "moderado_above_count": None},
    # engine 1.9
    "credito_situacao": {"atencao_above_count": 0, "moderado_above_count": None},
    "credito_vencimento_diverge": {"atencao_above_count": None, "moderado_above_count": 0},
    "credito_preco_marcacao": {"atencao_above_pct": None, "moderado_above_pct": 5.0},
    "concentracao_gestor": {"atencao_above_pct": 40.0, "moderado_above_pct": 25.0},
    "liquidez": {"atencao_above_pct": 50.0, "moderado_above_pct": 30.0},
}
RISK_NAMES = {
    "concentracao_emissor": "Concentração: maior emissor de crédito direto",
    "concentracao_fundo": "Concentração: maior fundo",
    "credito_privado": "Crédito privado direto",
    "credito_sem_fgc": "Crédito direto sem cobertura do FGC",
    "fgc_acima_limite": "FGC: emissores acima de R$ 250 mil",
    "vencimentos": "Vencimentos: maior ano",
    "indexador": "Indexador",
    "reapresentacoes": "Reapresentações (FIDC e FII)",
    "movimento_anormal": "Movimento anormal de cota",
    "credito_situacao": "CRA/CRI fora de 'Adimplente'",
    "credito_vencimento_diverge": "Vencimento diverge do registro CVM",
    "credito_preco_marcacao": "Preço do extrato vs marcação dos fundos (debêntures)",
    "concentracao_gestor": "Maior gestora",
    "liquidez": "Liquidez acima de D+30",
}
EXPLANATION = {
    "concentracao_emissor": (
        "parte da carteira no maior emissor de crédito direto, pelo nome impresso no extrato; grupo econômico não avaliado"
    ),
    "concentracao_fundo": "parte da carteira na maior posição em um único fundo",
    "credito_privado": "parte da carteira em crédito direto (CDB, LCI, LCA, CRI, CRA, debêntures, CDCA)",
    "credito_sem_fgc": (
        "crédito direto que o FGC não cobre: CRI, CRA, debêntures, CDCA e o que passa de R$ 250 mil por emissor impresso; "
        "a conferir, porque o limite é por CPF e por conglomerado, e o emissor impresso não é o conglomerado"
    ),
    "fgc_acima_limite": (
        "emissores impressos cujos CDB, LCI e LCA somam mais que o limite do FGC; a conferir: limite por CPF e instituição"
    ),
    "vencimentos": "parte da carteira que vence no ano com mais vencimentos impressos no extrato",
    "indexador": (
        "parte da carteira no maior grupo de indexador (inflação, pré-fixado, pós-fixado, renda variável, câmbio); "
        "um fato da carteira, sem previsão de juros ou de inflação"
    ),
    "reapresentacoes": "documentos reapresentados pelos FIDC e FII da carteira na janela; reapresentado, não avaliado",
    "movimento_anormal": (
        "fundos com retorno de cota a mais de 3 desvios padrão da média da sua classe ANBIMA no mês (nível forte); "
        "um sinal sobre um mês passado"
    ),
    "credito_situacao": (
        "CRA e CRI da carteira cuja situação no registro da CVM não é 'Adimplente', como arquivada; uma situação não "
        "informada não conta"
    ),
    "credito_vencimento_diverge": (
        "CRA e CRI cujo vencimento impresso no extrato difere do vencimento da série no registro da CVM; a conferir"
    ),
    "credito_preco_marcacao": (
        "maior diferença entre o preço unitário do extrato e a marcação média ponderada dos fundos que têm a debênture "
        "(CDA bloco 4), em datas diferentes; informativo, não é veredito de preço"
    ),
    "concentracao_gestor": (
        "parte da carteira nos fundos da maior gestora, agrupados pelo identificador da gestora arquivado na CVM, "
        "nunca pelo nome"
    ),
    "liquidez": (
        "parte da carteira que não se resgata em até D+30: fundos com prazo de pagamento acima de D+30, com carência "
        "(lock-up), sem prazo de resgate informado e o crédito direto, que não tem liquidez antes do vencimento; prazos "
        "como arquivados, dias úteis e corridos sem conversão"
    ),
}
NOT_EVALUATED_TEXT = {
    "sem_vencimento": REASON_TEXT["sem_vencimento"],
    "consulta_falhou": REASON_TEXT["consulta_falhou"],
    "fundos_nao_avaliados": "nenhum fundo da carteira pôde ser comparado com a sua classe",
    "liquidez_sem_api": (
        "o SILO ainda não serve o prazo de resgate da lâmina por uma API pública, e a coluna de liquidez do extrato "
        "para o crédito direto ainda não é lida"
    ),
    "sem_indexador": "nenhuma parte da carteira tem indexador classificado",
    "cra_cri_sem_registro": REASON_TEXT["cra_cri_sem_registro"],
    "sem_marcacao_fundos": REASON_TEXT["sem_marcacao_fundos"],
    "sem_gestor": REASON_TEXT["sem_gestor"],
    "gestor_sem_api": REASON_TEXT["gestor_sem_api"],
}
NOT_APPLICABLE_TEXT = {
    "sem_credito_direto": REASON_TEXT["sem_credito_direto"],
    "sem_fundos": REASON_TEXT["sem_fundos"],
    "sem_fidc_fii": "nenhum FIDC ou FII identificado na carteira",
    "sem_cdb_lci_lca": "nenhum CDB, LCI ou LCA na carteira",
    "sem_cra_cri": REASON_TEXT["sem_cra_cri"],
    "sem_debenture": REASON_TEXT["sem_debenture"],
}
DETAIL_LABEL = {"credito_sem_fgc": "valor sem cobertura", "fgc_acima_limite": "excedente somado",
                "credito_situacao": "valor desses títulos", "credito_vencimento_diverge": "valor desses títulos",
                "concentracao_gestor": "valor nos fundos da gestora", "liquidez": "valor acima de D+30"}
CHECK_LABEL = {"credito_vencimento_diverge": "a conferir", "credito_preco_marcacao": "informativo, não é veredito de preço",
               "indexador": "leitura parcial: mais de 25% da carteira sem indexador classificado (partes ao lado)"}
# Above this share of the portfolio without an indexer, the indexer row's largest group may not be the largest one:
# the row keeps its value and severity and carries CHECK_LABEL["indexador"] (real statement, 2026-10-05, replayed with
# a sample of each fund's look-through: a large unclassified share, the funds' part the ingested CDA blocks do not
# explain, printed beside "baixo").
INDEXER_UNCLASSIFIED_CHECK_PCT = 25.0
FUND_TIPOS = ("fundo", "FIDC", "FII", "ETF", "FIP")
INDEXER_GROUPS = (
    ("inflação", lambda c: c.startswith("inflação")),
    ("pré-fixado", lambda c: c == "pré-fixado"),
    ("pós-fixado", lambda c: c.startswith("pós-fixado")),
    ("renda variável", lambda c: c == "renda variável"),
    ("câmbio", lambda c: c == "câmbio"),
    ("caixa", lambda c: c.startswith("caixa")),
)
FACTOR_GROUPS = ("inflação", "pré-fixado", "pós-fixado", "renda variável", "câmbio")


def severity(risk_id: str, value: float | int | None) -> str | None:
    if value is None:
        return None
    th = THRESHOLDS[risk_id]
    unit = "pct" if any(k.endswith("_pct") for k in th) else "count"
    att, mod = th.get(f"atencao_above_{unit}"), th.get(f"moderado_above_{unit}")
    if att is not None and value > att:
        return "atencao"
    if mod is not None and value > mod:
        return "moderado"
    return "baixo"


def _statement_sources(doc: dict, line_nos: list[int]) -> list[dict]:
    by_no = {p["line_no"]: p for p in doc["statement"]["positions"]}
    return [by_no[n]["source"] for n in line_nos if n in by_no and by_no[n].get("source")]


def _row(risk_id: str, *, status: str, unit: str, value: Any = None, subject: str | None = None,
         source_path: str | None = None, line_nos: list[int] | None = None, sources: list[dict] | None = None,
         code: str | None = None, extra: dict | None = None, sev: str | None = None) -> dict[str, Any]:
    sev = sev if sev is not None else (severity(risk_id, value) if status == EVALUATED else None)
    if status == NOT_EVALUATED:
        reason = NOT_EVALUATED_TEXT.get(code or "", REASON_TEXT.get(code or "", "não avaliado"))
    elif status == NOT_APPLICABLE:
        reason = NOT_APPLICABLE_TEXT.get(code or "", REASON_TEXT.get(code or "", "não se aplica"))
    else:
        reason = None
    row = {
        "id": risk_id,
        "risk": RISK_NAMES[risk_id],
        "status": status,
        "status_label": STATUS_LABEL[status],
        "unit": unit,
        "value_pct": value if unit == "pct" and status == EVALUATED else None,
        "value_brl": value if unit == "brl" and status == EVALUATED else None,
        "value_count": value if unit == "count" and status == EVALUATED else None,
        "subject": subject,
        "source_path": source_path,
        "severity": sev,
        "severity_label": SEVERITY_LABEL.get(sev or ""),
        "thresholds": dict(THRESHOLDS[risk_id]),
        "explanation": EXPLANATION[risk_id],
        "reason_code": code,
        "reason": reason,
        "line_nos": line_nos or [],
        "text_allowed": True,
        "sources": sources or [],
    }
    row.update(extra or {})
    if row.get("value_brl_detail") is not None:
        row["value_brl_detail_label"] = DETAIL_LABEL.get(risk_id, "valor")
    return row


def _issuer_rows(doc: dict) -> list[dict]:
    c = doc.get("concentration") or {}
    iss, fgc = c.get("issuer") or {}, c.get("fgc") or {}
    rows: list[dict] = []
    groups = iss.get("groups") or []
    if iss.get("status") != STATUS_COMPLETE:
        code = iss.get("reason_code") or "sem_credito_direto"
        for rid in ("concentracao_emissor", "credito_privado", "credito_sem_fgc"):
            rows.append(_row(rid, status=NOT_APPLICABLE, unit="pct", code=code))
    else:
        all_nos = sorted({n for g in groups for n in g.get("line_nos") or []} | set(iss.get("not_printed_line_nos") or []))
        if groups:
            g0 = groups[0]
            rows.append(_row("concentracao_emissor", status=EVALUATED, unit="pct", value=g0.get("portfolio_pct"),
                             subject=g0.get("issuer_as_printed"), source_path="concentration.issuer.groups[0].portfolio_pct",
                             line_nos=g0.get("line_nos"), sources=_statement_sources(doc, g0.get("line_nos") or []),
                             extra={"value_brl_detail": g0.get("value_brl")}))
        else:
            rows.append(_row("concentracao_emissor", status=NOT_EVALUATED, unit="pct", code="sem_emissor_impresso"))
        rows.append(_row("credito_privado", status=EVALUATED, unit="pct", value=iss.get("direct_credit_portfolio_pct"),
                         source_path="concentration.issuer.direct_credit_portfolio_pct", line_nos=all_nos,
                         sources=_statement_sources(doc, all_nos), extra={"value_brl_detail": iss.get("direct_credit_value_brl")}))
        # what the FGC does not cover: every direct-credit line, less each printed issuer's CDB/LCI/LCA up to the limit
        total = dec(doc["statement"].get("sum_of_lines_brl")) or Decimal("0")
        credit = dec(iss.get("direct_credit_value_brl")) or Decimal("0")
        limit = dec(fgc.get("limit_brl")) or Decimal("250000")
        covered = sum((min(dec(g.get("eligible_value_brl")) or Decimal("0"), limit) for g in fgc.get("issuers") or []),
                      Decimal("0"))
        uncovered = credit - covered
        rows.append(_row("credito_sem_fgc", status=EVALUATED, unit="pct", value=pct(uncovered, total) if total else None,
                         source_path="concentration.issuer.direct_credit_value_brl - concentration.fgc.issuers[].eligible_value_brl (até concentration.fgc.limit_brl)",
                         line_nos=all_nos, sources=_statement_sources(doc, all_nos),
                         extra={"value_brl_detail": brl(uncovered), "check_label": fgc.get("label")}))
    if fgc.get("status") == STATUS_COMPLETE:
        above = [g for g in fgc.get("issuers") or [] if g.get("above_limit")]
        nos = [n for g in above for n in g.get("line_nos") or []]
        excess = sum((dec(g.get("excess_brl")) or Decimal("0") for g in above), Decimal("0"))
        rows.append(_row("fgc_acima_limite", status=EVALUATED, unit="count", value=fgc.get("n_above_limit"),
                         subject=above[0].get("issuer_as_printed") if above else None,
                         source_path="concentration.fgc.n_above_limit", line_nos=nos, sources=_statement_sources(doc, nos),
                         extra={"value_brl_detail": brl(excess), "check_label": fgc.get("label")}))
    else:
        rows.append(_row("fgc_acima_limite", status=NOT_APPLICABLE, unit="count", code="sem_cdb_lci_lca"))
    return rows


def _fund_row(doc: dict) -> dict:
    """The largest fund, summed over every line that identifies as it (same CNPJ, else same code): a fund held in
    two accounts is one exposure (real statement, 2026-10-05: one fund in two accounts, 3.65% + 6.10%)."""
    idents = {ln["line_no"]: ln for ln in doc["identification"]["lines"]}
    groups: dict[str, dict] = {}
    for i, p in enumerate(doc["statement"]["positions"]):
        ident = idents.get(p["line_no"]) or {}
        identity = ident.get("identity") or {}
        is_fund = p.get("tipo") in FUND_TIPOS or identity.get("kind") == "fund" or identity.get("asset_class") == "fund_quota"
        if not is_fund:
            continue
        key = identity.get("cnpj") or p.get("codigo") or f"L{p['line_no']}"
        g = groups.setdefault(key, {"value": Decimal("0"), "pct": Decimal("0"), "line_nos": [], "idx": [], "sources": [],
                                    "subject": identity.get("name") or p.get("linha_extrato")})
        g["value"] += dec(p.get("valor_brl")) or Decimal("0")
        g["pct"] += dec(p.get("portfolio_pct")) or Decimal("0")
        g["line_nos"].append(p["line_no"])
        g["idx"].append(i)
        if p.get("source"):
            g["sources"].append(p["source"])
    if not groups:
        return _row("concentracao_fundo", status=NOT_APPLICABLE, unit="pct", code="sem_fundos")
    g = max(groups.values(), key=lambda x: (x["value"], -x["line_nos"][0]))
    if len(g["idx"]) == 1:
        path, value = f"statement.positions[{g['idx'][0]}].portfolio_pct", doc["statement"]["positions"][g["idx"][0]].get("portfolio_pct")
    else:
        total = dec(doc["statement"].get("sum_of_lines_brl")) or Decimal("0")
        path = "statement.positions[" + ", ".join(str(i) for i in g["idx"]) + "].valor_brl, somados (mesmo fundo), sobre statement.sum_of_lines_brl"
        value = pct(g["value"], total)
    return _row("concentracao_fundo", status=EVALUATED, unit="pct", value=value,
                subject=g["subject"], source_path=path, line_nos=g["line_nos"], sources=g["sources"],
                extra={"value_brl_detail": brl(g["value"])})


def _maturity_row(doc: dict) -> dict:
    lad = (doc.get("concentration") or {}).get("maturity_ladder") or {}
    years = lad.get("by_year") or []
    if lad.get("status") != STATUS_COMPLETE or not years:
        return _row("vencimentos", status=NOT_EVALUATED, unit="pct", code="sem_vencimento")
    k = max(range(len(years)), key=lambda j: (years[j].get("value_brl") or 0, -j))
    y = years[k]
    return _row("vencimentos", status=EVALUATED, unit="pct", value=y.get("portfolio_pct"), subject=y.get("year"),
                source_path=f"concentration.maturity_ladder.by_year[{k}].portfolio_pct", line_nos=y.get("line_nos"),
                sources=_statement_sources(doc, y.get("line_nos") or []), extra={"value_brl_detail": y.get("value_brl")})


def _indexer_row(doc: dict) -> dict:
    ix = doc.get("indexer") or {}
    total = dec(ix.get("portfolio_value_brl")) or Decimal("0")
    if ix.get("status") == STATUS_UNKNOWN or not total:
        return _row("indexador", status=NOT_EVALUATED, unit="pct", code=(ix.get("reason_codes") or ["consulta_falhou"])[0])
    sums: dict[str, Decimal] = {}
    for c in ix.get("classes") or []:
        name = c.get("indexer_class") or UNCLASSIFIED
        group = next((g for g, test in INDEXER_GROUPS if test(name)), UNCLASSIFIED)
        sums[group] = sums.get(group, Decimal("0")) + (dec(c.get("value_brl")) or Decimal("0"))
    parts = [{"group": g, "value_brl": brl(sums.get(g, Decimal("0"))), "portfolio_pct": pct(sums.get(g, Decimal("0")), total)}
             for g in [*(g for g, _ in INDEXER_GROUPS), UNCLASSIFIED]]
    factors = [p for p in parts if p["group"] in FACTOR_GROUPS and (p["value_brl"] or 0) > 0]
    if not factors:
        return _row("indexador", status=NOT_EVALUATED, unit="pct", code="sem_indexador", extra={"parts": parts})
    top = max(factors, key=lambda p: p["value_brl"])
    extra: dict = {"parts": parts}
    unclassified = next(p for p in parts if p["group"] == UNCLASSIFIED)["portfolio_pct"] or 0
    if unclassified > INDEXER_UNCLASSIFIED_CHECK_PCT:
        extra["check_label"] = CHECK_LABEL["indexador"]
    return _row("indexador", status=EVALUATED, unit="pct", value=top["portfolio_pct"], subject=top["group"],
                source_path="indexer.classes[].value_brl, somados por grupo sobre indexer.portfolio_value_brl",
                extra=extra)


def _restatement_row(doc: dict) -> dict:
    rs = doc.get("restatements") or {}
    lines = rs.get("lines") or []
    if rs.get("status") == STATUS_UNKNOWN:
        return _row("reapresentacoes", status=NOT_EVALUATED, unit="count", code="consulta_falhou")
    if not lines:
        return _row("reapresentacoes", status=NOT_APPLICABLE, unit="count", code="sem_fidc_fii")
    n = sum(len(ln.get("restatements") or []) for ln in lines)
    srcs = [s for ln in lines for r in ln.get("restatements") or [] for s in r.get("sources") or []]
    nos = [ln["line_no"] for ln in lines if ln.get("restatements")]
    return _row("reapresentacoes", status=EVALUATED, unit="count", value=n, source_path="restatements.lines[].restatements",
                line_nos=nos, sources=srcs[:6], extra={"assessment": rs.get("assessment")})


def _movement_row(doc: dict) -> dict:
    mv = doc.get("movement")
    if not isinstance(mv, dict) or mv.get("status") == STATUS_UNKNOWN:
        return _row("movimento_anormal", status=NOT_EVALUATED, unit="count", code="consulta_falhou")
    counts = mv.get("counts") or {}
    if not counts.get("funds"):
        return _row("movimento_anormal", status=NOT_APPLICABLE, unit="count", code="sem_fundos")
    forte, atencao = counts.get("forte") or 0, counts.get("atencao") or 0
    if forte + atencao + (counts.get("normal") or 0) == 0:
        return _row("movimento_anormal", status=NOT_EVALUATED, unit="count", code="fundos_nao_avaliados")
    lines = mv.get("lines") or []
    strong = [ln for ln in lines if ln.get("level") == "forte"]
    srcs = [s for ln in lines if ln.get("level") in ("forte", "atencao", "normal") for s in ln.get("sources") or []]
    # the attention level is a table row (owner, 2026-10-03): when it alone sets the severity, the row is table-only
    sev = "atencao" if forte else ("moderado" if atencao else "baixo")
    row = _row("movimento_anormal", status=EVALUATED, unit="count", value=forte, sev=sev,
               subject=strong[0].get("fund_name") if strong else None, source_path="movement.counts.forte",
               line_nos=[ln["line_no"] for ln in strong], sources=srcs[:6],
               extra={"table_only": {"n_atencao": atencao, "atencao_line_nos": [ln["line_no"] for ln in lines if ln.get("level") == "atencao"]}})
    row["text_allowed"] = not (atencao and not forte)
    return row


def _liquidity_row(doc: dict) -> dict:
    lq = doc.get("liquidity")
    if not isinstance(lq, dict):  # an engine document before 1.9: the redemption terms were not served
        liq = (doc.get("concentration") or {}).get("fund_liquidity") or {}
        return _row("liquidez", status=NOT_EVALUATED, unit="pct", code=liq.get("reason_code") or "liquidez_sem_api")
    if not lq.get("evaluated"):
        # the terms call did not answer for some fund: never computed with those funds put in "sem prazo"
        return _row("liquidez", status=NOT_EVALUATED, unit="pct", code="consulta_falhou")
    by_id = {b.get("bucket_id"): (k, b) for k, b in enumerate(lq.get("buckets") or [])}
    parts = []
    nos: list[int] = []
    for bid in lq.get("above_d30_parts") or []:
        k, b = by_id.get(bid, (None, {}))
        parts.append({"group": b.get("bucket"), "bucket_id": bid, "value_brl": b.get("value_brl"),
                      "portfolio_pct": b.get("portfolio_pct")})
        nos += b.get("line_nos") or []
    return _row("liquidez", status=EVALUATED, unit="pct", value=lq.get("above_d30_total_pct"),
                source_path="liquidity.above_d30_total_pct", line_nos=sorted(nos), sources=_statement_sources(doc, sorted(nos)),
                extra={"value_brl_detail": lq.get("above_d30_total_brl"), "parts": parts})


def _ident_lines(doc: dict) -> list[tuple[int, dict, dict]]:
    """(index in identification.lines, the line, its statement position)."""
    by_no = {p["line_no"]: p for p in doc["statement"]["positions"]}
    return [(i, ln, by_no.get(ln["line_no"]) or {}) for i, ln in enumerate((doc.get("identification") or {}).get("lines") or [])]


def _credit_rows(doc: dict) -> list[dict]:
    """Engine 1.9: CRA/CRI outside "Adimplente", maturities that differ from the registry, debênture price vs mark."""
    lines = _ident_lines(doc)
    rows: list[dict] = []
    cra = [(i, ln, p) for i, ln, p in lines if ln.get("tipo") in ("CRA", "CRI")]
    matched = [(i, ln, p) for i, ln, p in cra if (ln.get("credit_match") or {}).get("matched")]
    if not cra:
        rows += [_row(rid, status=NOT_APPLICABLE, unit="count", code="sem_cra_cri")
                 for rid in ("credito_situacao", "credito_vencimento_diverge")]
    elif not matched:
        failed = any((ln.get("credit_match") or {}).get("reason_code") == "consulta_falhou" or ln.get("reason_code") == "consulta_falhou"
                     for _, ln, _ in cra)
        code = "consulta_falhou" if failed else "cra_cri_sem_registro"
        rows += [_row(rid, status=NOT_EVALUATED, unit="count", code=code)
                 for rid in ("credito_situacao", "credito_vencimento_diverge")]
    else:
        for rid, flag in (("credito_situacao", "situacao_fora_adimplente"), ("credito_vencimento_diverge", "vencimento_diverge")):
            hit = [(i, ln, p) for i, ln, p in matched if any(f.get("code") == flag for f in ln["credit_match"].get("flags") or [])]
            nos = [ln["line_no"] for _, ln, _ in hit]
            value = sum((dec(p.get("valor_brl")) or Decimal("0") for _, _, p in hit), Decimal("0"))
            subject = hit[0][1]["credit_match"].get("code") if hit else None
            extra: dict[str, Any] = {"value_brl_detail": brl(value) if hit else None,
                                     "n_evaluated": len(matched), "n_not_found": len(cra) - len(matched)}
            if rid in CHECK_LABEL:
                extra["check_label"] = CHECK_LABEL[rid]
            if rid == "credito_situacao" and hit:
                extra["situacao"] = hit[0][1]["credit_match"].get("situacao")
            if rid == "credito_vencimento_diverge" and hit:
                f0 = next(f for f in hit[0][1]["credit_match"]["flags"] if f.get("code") == flag)
                extra["statement_vencimento"] = f0.get("statement_vencimento")
                extra["registry_vencimento"] = f0.get("registry_vencimento")
            srcs = [s for _, ln, _ in hit for s in ln["credit_match"].get("sources") or []]
            rows.append(_row(rid, status=EVALUATED, unit="count", value=len(hit), subject=subject,
                             source_path=f"identification.lines[].credit_match.flags[code={flag}]", line_nos=nos,
                             sources=srcs[:6] or _statement_sources(doc, nos), extra=extra))
    deb = [(i, ln, p) for i, ln, p in lines if ln.get("tipo") == "debênture"]
    priced = [(i, ln, p) for i, ln, p in deb if (ln.get("credit_match") or {}).get("price_gap_abs_pct") is not None]
    if not deb:
        rows.append(_row("credito_preco_marcacao", status=NOT_APPLICABLE, unit="pct", code="sem_debenture"))
    elif not priced:
        failed = any((ln.get("credit_match") or {}).get("reason_code") == "consulta_falhou" for _, ln, _ in deb)
        rows.append(_row("credito_preco_marcacao", status=NOT_EVALUATED, unit="pct",
                         code="consulta_falhou" if failed else "sem_marcacao_fundos"))
    else:
        i, ln, p = max(priced, key=lambda t: (t[1]["credit_match"]["price_gap_abs_pct"], -t[1]["line_no"]))
        cm = ln["credit_match"]
        st = cm.get("statement") or {}
        rows.append(_row("credito_preco_marcacao", status=EVALUATED, unit="pct", value=cm["price_gap_abs_pct"],
                         subject=cm.get("code") or cm.get("input_code"),
                         source_path=f"identification.lines[{i}].credit_match.price_gap_abs_pct", line_nos=[ln["line_no"]],
                         sources=(cm.get("sources") or [])[:2] + _statement_sources(doc, [ln["line_no"]]),
                         extra={"check_label": CHECK_LABEL["credito_preco_marcacao"], "price_gap_pct": cm.get("price_gap_pct"),
                                "statement_preco_brl": st.get("preco_brl"), "statement_date": st.get("data_posicao"),
                                "preco_marcacao_fundos_brl": cm.get("preco_marcacao_fundos_brl"),
                                "cda_period": cm.get("cda_period"), "n_evaluated": len(priced)}))
    return rows


def _manager_row(doc: dict) -> dict:
    m = (doc.get("concentration") or {}).get("manager") or {}
    st = m.get("status")
    if st == STATUS_NOT_APPLICABLE_SECTION:
        return _row("concentracao_gestor", status=NOT_APPLICABLE, unit="pct", code="sem_fundos")
    groups = m.get("groups") or []
    if st == STATUS_UNKNOWN or m.get("unanswered_line_nos"):
        return _row("concentracao_gestor", status=NOT_EVALUATED, unit="pct", code=m.get("reason_code") or "gestor_sem_api")
    if not groups:
        return _row("concentracao_gestor", status=NOT_EVALUATED, unit="pct", code="sem_gestor")
    g = groups[0]
    return _row("concentracao_gestor", status=EVALUATED, unit="pct", value=g.get("portfolio_pct"), subject=g.get("gestor_name"),
                source_path="concentration.manager.groups[0].portfolio_pct", line_nos=g.get("line_nos"),
                sources=(g.get("sources") or [])[:4] + _statement_sources(doc, g.get("line_nos") or []),
                extra={"value_brl_detail": g.get("value_brl"), "gestor_id": g.get("gestor_id"),
                       "fund_value_pct": g.get("fund_value_pct"),
                       "without_gestor_line_nos": m.get("without_gestor_line_nos") or []})


def compute_risks(doc: dict[str, Any]) -> dict[str, Any]:
    """The ``risks`` section from an engine document whose other sections are built."""
    sec = Section()
    rows = [*_issuer_rows(doc), _fund_row(doc), _maturity_row(doc), _indexer_row(doc), _restatement_row(doc),
            _movement_row(doc), *_credit_rows(doc), _manager_row(doc), _liquidity_row(doc)]
    order = {rid: k for k, rid in enumerate(THRESHOLDS)}
    status_rank = {EVALUATED: 0, NOT_EVALUATED: 1, NOT_APPLICABLE: 2}
    rows.sort(key=lambda r: (status_rank[r["status"]], SEVERITY_RANK.get(r["severity"] or "", 3), order[r["id"]]))
    n_not = sum(1 for r in rows if r["status"] == NOT_EVALUATED)
    if n_not:
        sec.degrade("Há riscos não avaliados por falta de dado.", code="riscos_nao_avaliados")
    return {
        **sec.head(),
        "title": TITLE,
        "note": NOTE,
        "severity_rule": SEVERITY_RULE,
        "thresholds": {k: dict(v) for k, v in THRESHOLDS.items()},
        "counts": {
            "atencao": sum(1 for r in rows if r["severity"] == "atencao"),
            "moderado": sum(1 for r in rows if r["severity"] == "moderado"),
            "baixo": sum(1 for r in rows if r["severity"] == "baixo"),
            "nao_avaliado": n_not,
            "nao_se_aplica": sum(1 for r in rows if r["status"] == NOT_APPLICABLE),
        },
        "rows": rows,
    }
