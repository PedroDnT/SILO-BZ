"""HTML (and PDF) report in Portuguese from the engine JSON and the kept findings.

Every figure on the page is read from the engine JSON here: the tables walk
it directly and the findings' ``{{placeholders}}`` are replaced by
``values.format_value``. Engine strings are HTML-escaped. The page identifies
no client. Templates are plain files in ``templates/`` filled with
``{{name}}`` slots (no template engine dependency).
"""

from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.portfolio.report.redator import SECTION_TITLES, Finding
from src.portfolio.report.revisor import Removal
from src.portfolio.report.values import PLACEHOLDER_RE, format_value, resolve

TEMPLATES = Path(__file__).parent / "templates"
DEFAULT_SIGNATURE = "Pedro Todescan, pesquisador independente"
SIGNATURE_ENV = "SILO_REPORT_SIGNATURE"
_SLOT_RE = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")

DISCLAIMER_HTML = (
    "<ul>"
    "<li>Este relatório não é recomendação de investimento: não indica comprar, vender ou manter nenhum ativo.</li>"
    "<li>Não há previsão de retorno em nenhuma parte.</li>"
    "<li>Valores estimados aparecem sempre rotulados como estimativa.</li>"
    "<li>Grupo econômico não avaliado.</li>"
    "<li>Reapresentações aparecem como \"revisado, não avaliado\": os limiares de materialidade estão em definição.</li>"
    "</ul>"
)

SOURCE_LABELS = {
    "CVM": "CVM (dados.cvm.gov.br)",
    "BCB": "Banco Central do Brasil (SGS)",
    "B3": "B3",
    "FNET": "B3 Fundos.NET (FNET)",
    "ANBIMA": "ANBIMA",
    "IBGE": "IBGE",
    "ETFSBRASIL": "etfsbrasil.com.br (site de terceiros: taxa, cotistas e PL dos ETFs, não é documento da CVM)",
}

ASSET_LABELS = {
    "titulo_publico": "título público", "acao": "ação", "fundo": "fundo", "fidc": "FIDC",
    "fii": "FII", "etf": "ETF", "desconhecido": "não identificado", "caixa": "conta corrente",
    "cota_listada": "cota de fundo listada", "credito_privado": "crédito privado direto",
}
SECTION_STATUS_LABELS = {"complete": "avaliada", "partial": "avaliada em parte", "unknown": "não avaliada"}

STATUS_LABELS = {
    "identified": "identificada",
    "ambiguous": "ambígua, desempatada",
    "unknown": "não identificada",
    "complete": "completa",
    "partial": "parcial",
}


@dataclass
class Narrative:
    status: str  # "complete" | "unknown"
    kept: list[Finding] = field(default_factory=list)
    removed: list[Removal] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    reason: str | None = None
    provider: str = ""
    model: str = ""
    served_by: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    cost_cap_usd: float = 0.0


def signature(cli_value: str | None = None) -> str:
    return cli_value or os.environ.get(SIGNATURE_ENV) or DEFAULT_SIGNATURE


def fill(template: str, slots: dict[str, str]) -> str:
    """Replace ``{{name}}`` slots in one pass (inserted text is never rescanned)."""
    return _SLOT_RE.sub(lambda m: slots.get(m.group(1), m.group(0)), template)


def e(s: Any) -> str:
    return html.escape("" if s is None else str(s))


def v(engine: dict, path: str) -> str:
    """Escaped, formatted value at ``path``."""
    return e(format_value(engine, path))


def substitute(engine: dict, text: str) -> str:
    """Finding text to HTML: escape the prose, insert formatted placeholder values."""
    out, pos = [], 0
    for m in PLACEHOLDER_RE.finditer(text):
        out.append(e(text[pos:m.start()]))
        out.append(f'<span class="v">{v(engine, m.group(1).strip())}</span>')
        pos = m.end()
    out.append(e(text[pos:]))
    return "".join(out)


def _findings_html(engine: dict, narrative: Narrative, section: str) -> str:
    if narrative.status != "complete":
        return f'<p class="indisponivel">Texto interpretativo indisponível: {e(narrative.reason or "não gerado")}.</p>'
    items = [f for f in narrative.kept if f.section == section]
    if not items:
        return ""
    parts = []
    for f in items:
        cites = ", ".join(e(c) for c in f.citations)
        parts.append(
            f'<div class="achado"><strong>{substitute(engine, f.title)}</strong>'
            f'{substitute(engine, f.text)} <span class="cit">[{cites}]</span></div>'
        )
    return "\n".join(parts)


def _table(headers: list[tuple[str, bool]], rows: list[list[str]]) -> str:
    if not rows:
        return '<p class="indisponivel">Sem linhas.</p>'
    th = "".join(f'<th{" class=n" if num else ""}>{e(h)}</th>' for h, num in headers)
    body = []
    for r in rows:
        body.append("<tr>" + "".join(
            f'<td{" class=n" if headers[i][1] else ""}>{c}</td>' for i, c in enumerate(r)) + "</tr>")
    return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _ident_section(engine: dict) -> str:
    rows = []
    for i, ln in enumerate(engine.get("lines") or []):
        p = f"lines[{i}]"
        ident = ln.get("identification") or {}
        code = ln.get("cnpj") and v(engine, f"{p}.cnpj") or ln.get("ticker") and v(engine, f"{p}.ticker") or "—"
        status = ident.get("status") or "unknown"
        note = ""
        if ident.get("renamed_from"):
            note = f"<br><span class=cit>nome antigo: {v(engine, f'{p}.identification.renamed_from')}</span>"
        if status == "unknown" and ident.get("reason"):
            note = f"<br><span class=cit>{v(engine, f'{p}.identification.reason')}</span>"
        tag = "unk" if status != "identified" else ""
        rows.append([
            v(engine, f"{p}.line_id"),
            v(engine, f"{p}.instrument") + (f"<br><span class=cit>{v(engine, f'{p}.fund_name')}</span>" if ln.get("fund_name") else ""),
            e(ASSET_LABELS.get(ln.get("asset_type"), ln.get("asset_type") or "—")),
            code,
            v(engine, f"{p}.value_brl"),
            v(engine, f"{p}.weight_pct"),
            f'<span class="tag {tag}">{e(STATUS_LABELS.get(status, status))}</span>{note}',
        ])
    return _table(
        [("Linha", False), ("Ativo", False), ("Tipo", False), ("CNPJ / código", False),
         ("Valor", True), ("Peso", True), ("Identificação", False)],
        rows,
    )


def _fee_row(engine: dict, q: str, b: dict) -> list[str]:
    """One fee line: the disclosed fee first, where it comes from, the estimate apart, the declared expense ratio."""
    label = b.get("fee_status") or b.get("label") or ""
    if b.get("disclosed_pct_year") is not None:
        disclosed = f"<span class=v>{v(engine, f'{q}.disclosed_pct_year')}</span> a.a."
        if b.get("disclosed_brl_year") is not None:
            disclosed += f"<br><span class=cit>{v(engine, f'{q}.disclosed_brl_year')} por ano</span>"
        if b.get("disclosed_scope_label"):
            disclosed += f"<br><span class=cit>{v(engine, f'{q}.disclosed_scope_label')}</span>"
        if b.get("lamina_newer_label"):
            disclosed += f'<br><span class="tag unk">{v(engine, f"{q}.lamina_newer_label")}</span>'
        if b.get("sources_differ_label"):
            disclosed += f'<br><span class="tag unk">{v(engine, f"{q}.sources_differ_label")}</span>'
        if b.get("etf_site_label"):
            disclosed += f"<br><span class=cit>{v(engine, f'{q}.etf_site_label')}</span>"
    elif b.get("etf_site_check_label"):
        disclosed = f'<span class="tag unk">{v(engine, f"{q}.etf_site_check_label")}</span>'
        if b.get("etf_site_raw") is not None:
            disclosed += f"<br><span class=cit>valor informado pelo site: {v(engine, f'{q}.etf_site_raw')} a.a. (a conferir; pode estar correto)</span>"
        disclosed += f"<br><span class=cit>{v(engine, f'{q}.etf_site_label')}</span>"
    elif b.get("disclosed_min_pct_year") is not None:
        disclosed = (f"faixa divulgada: <span class=v>{v(engine, f'{q}.disclosed_min_pct_year')}</span> a "
                     f"<span class=v>{v(engine, f'{q}.disclosed_max_pct_year')}</span> a.a.")
    elif b.get("filed_zero_label"):
        disclosed = f'<span class="tag unk">{v(engine, f"{q}.filed_zero_label")}</span>'
        if b.get("filed_zero_pct") is not None:
            disclosed += f"<br><span class=cit>valor informado: {v(engine, f'{q}.filed_zero_pct')} a.a.</span>"
    elif b.get("implausible_label"):
        disclosed = f'<span class="tag unk">{v(engine, f"{q}.implausible_label")}</span>'
        if b.get("implausible_raw") is not None:
            disclosed += f"<br><span class=cit>valor informado: {v(engine, f'{q}.implausible_raw')} (a conferir; pode estar correto)</span>"
    else:
        disclosed = f'<span class="tag unk">{e(label)}</span>'
        if b.get("reason"):
            disclosed += f"<br><span class=cit>{v(engine, f'{q}.reason')}</span>"
    disclosed += _beside_html(engine, q, b)
    disclosed += _etf_facts_html(engine, q, b)
    origin = "—"
    if b.get("disclosed_origin"):
        origin = v(engine, f"{q}.disclosed_origin_label")
        if b.get("disclosed_as_of"):
            origin += f"<br><span class=cit>data: {v(engine, f'{q}.disclosed_as_of')}</span>"
        if b.get("disclosed_age_months") is not None:
            origin += f"<br><span class=cit>idade: {v(engine, f'{q}.disclosed_age_months')} meses</span>"
        if b.get("disclosed_stale"):
            origin += f' <span class="tag unk">{v(engine, f"{q}.disclosed_stale_label")}</span>'
    if b.get("estimated_pct_year") is not None:
        est = f"<span class=v>{v(engine, f'{q}.estimated_pct_year')}</span> a.a."
        if b.get("estimated_pct_year_high") is not None:
            est += f" a <span class=v>{v(engine, f'{q}.estimated_pct_year_high')}</span>"
        if b.get("estimated_brl_year") is not None:
            est += f"<br><span class=cit>{v(engine, f'{q}.estimated_brl_year')} por ano</span>"
        est += f'<br><span class="tag est">{v(engine, f"{q}.estimate_label") if b.get("estimate_label") else "estimativa"}</span>'
        if b.get("month"):
            est += f"<br><span class=cit>balancete de {v(engine, f'{q}.month')}</span>"
    elif b.get("estimate_available") is False:
        est = '<span class=cit>sem estimativa (mês do balancete sem base de cálculo)</span>'
    else:
        est = "—"
    expense = "—"
    if b.get("expense_ratio_pct") is not None:
        expense = f"<span class=v>{v(engine, f'{q}.expense_ratio_pct')}</span> a.a."
        if b.get("expense_ratio_period_from"):
            expense += (f"<br><span class=cit>{v(engine, f'{q}.expense_ratio_period_from')} a "
                        f"{v(engine, f'{q}.expense_ratio_period_to')}</span>")
    notes = []
    for j, fi in enumerate(b.get("findings") or []):
        notes.append(f"<span class=cit>{v(engine, f'{q}.findings[{j}].level')}: {v(engine, f'{q}.findings[{j}].text')}</span>")
    if b.get("perf_as_filed"):
        notes.append(f"<span class=cit>performance, como informado: {v(engine, f'{q}.perf_as_filed')}</span>")
    return [
        v(engine, f"{q}.line_id"), v(engine, f"{q}.cnpj"), disclosed, origin, est, expense, "<br>".join(notes) or "—",
    ]


def _beside_html(engine: dict, q: str, b: dict) -> str:
    """The other document's fee beside the headline (engine 1.4, #552): as filed, never summed, never the fee."""
    out = ""
    if b.get("lamina_beside_label"):
        if b.get("lamina_beside_pct_year") is not None:
            value = f"<span class=v>{v(engine, f'{q}.lamina_beside_pct_year')}</span> a.a."
        else:
            value = (f"<span class=v>{v(engine, f'{q}.lamina_beside_min_pct_year')}</span> a "
                     f"<span class=v>{v(engine, f'{q}.lamina_beside_max_pct_year')}</span> a.a.")
        out += (f"<br><span class=cit>{v(engine, f'{q}.lamina_beside_label')} {value}; "
                f"{v(engine, f'{q}.lamina_beside_check_label')}")
        if b.get("lamina_beside_as_of"):
            out += f" (lâmina de {v(engine, f'{q}.lamina_beside_as_of')})"
        out += "</span>"
        if b.get("lamina_beside_stale_label"):
            out += f' <span class="tag unk">{v(engine, f"{q}.lamina_beside_stale_label")}</span>'
    if b.get("extrato_beside_label"):
        when = f" de {v(engine, f'{q}.extrato_beside_as_of')}" if b.get("extrato_beside_as_of") else ""
        out += (f"<br><span class=cit>Extrato{when} informa <span class=v>{v(engine, f'{q}.extrato_beside_value')}</span> "
                "(como informado; não somado)</span>")
    if b.get("scale_flag_label"):
        out += f'<br><span class="tag unk">{v(engine, f"{q}.scale_flag_label")}</span>'
    return out


def _etf_facts_html(engine: dict, q: str, b: dict) -> str:
    """An ETF's cotistas and PL from etfsbrasil.com.br (engine 1.6), with the source and the snapshot date.

    Descriptive facts, never a fee and never summed; each part is printed only when the engine carries it.
    """
    parts = []
    if b.get("etf_site_nr_cotistas") is not None:
        parts.append(f"Cotistas: <span class=v>{v(engine, f'{q}.etf_site_nr_cotistas')}</span>")
    if b.get("etf_site_pl_brl") is not None:
        parts.append(f"PL: <span class=v>{v(engine, f'{q}.etf_site_pl_brl')}</span>")
    if not parts:
        return ""
    src = v(engine, f"{q}.etf_facts_label") if b.get("etf_facts_label") else "etfsbrasil.com.br, site de terceiro"
    if b.get("etf_site_as_of"):
        src += f", coleta de {v(engine, f'{q}.etf_site_as_of')}"
    return f"<br><span class=cit>{'; '.join(parts)} ({src})</span>"


_FEE_HEADERS = [("Linha", False), ("CNPJ", False), ("Taxa divulgada", False), ("Origem e data", False),
                ("Estimativa do balancete (à parte)", False), ("Despesa declarada (lâmina)", True), ("Observações", False)]


def _fees_section(engine: dict) -> str:
    fees = engine.get("fees") or {}
    by_line = fees.get("by_line") or []
    rows = [_fee_row(engine, f"fees.by_line[{i}]", b) for i, b in enumerate(by_line)]
    head = ""
    if fees:
        parts = []
        if fees.get("total_disclosed_brl_year") is not None:
            parts.append(f"Taxas divulgadas somadas (só valores fixos utilizáveis): <span class=v>{v(engine, 'fees.total_disclosed_brl_year')}</span> por ano.")
        else:
            parts.append("Nenhuma taxa divulgada fixa utilizável para somar.")
        if fees.get("total_etf_site_brl_year") is not None:
            parts.append("Taxas de ETF informadas pelo site etfsbrasil.com.br (fonte de terceiros, não documento da CVM), somadas à parte: "
                         f"<span class=v>{v(engine, 'fees.total_etf_site_brl_year')}</span> por ano.")
        if fees.get("total_fee_brl_year") is not None:
            parts.append(f"As duas juntas: <span class=v>{v(engine, 'fees.total_fee_brl_year')}</span> por ano.")
        if fees.get("total_estimated_brl_year") is not None:
            parts.append(f"Estimativa do balancete, à parte e nunca somada à divulgada: <span class=v>{v(engine, 'fees.total_estimated_brl_year')}</span> por ano "
                         f"(<span class=v>{v(engine, 'fees.weighted_estimated_pct_year')}</span> a.a. sobre a carteira).")
        head = f"<p>{' '.join(parts)} <span class=cit>Base: {v(engine, 'fees.basis')}</span></p>"
    out = head + _table(_FEE_HEADERS, rows)
    und = fees.get("underlying") or []
    if und:
        urows = []
        for i, u in enumerate(und):
            row = _fee_row(engine, f"fees.underlying[{i}]", u)
            urows.append([v(engine, f"fees.underlying[{i}].parent_line_id"), v(engine, f"fees.underlying[{i}].fund_name"), *row[2:6],
                          f'<span class="tag unk">{v(engine, f"fees.underlying[{i}].label_not_added")}</span>'])
        out += ("<h3>Fundos por baixo (taxa própria de cada um, não somada à do fundo de cima)</h3>"
                + _table([("Linha", False), ("Fundo investido", False), ("Taxa divulgada", False), ("Origem e data", False),
                          ("Estimativa do balancete (à parte)", False), ("Despesa declarada (lâmina)", True), ("Soma", False)], urows))
    return out


def _bucket_table(engine: dict, base: str, label_key: str, label: str) -> str:
    rows = []
    for i, _b in enumerate(resolve(engine, f"{base}.buckets") or []):
        q = f"{base}.buckets[{i}]"
        rows.append([v(engine, f"{q}.{label_key}"), v(engine, f"{q}.value_brl"), v(engine, f"{q}.weight_pct")])
    return _table([(label, False), ("Valor", True), ("Peso", True)], rows)


def _exposure_section(engine: dict) -> str:
    lt = engine.get("lookthrough") or {}
    out = []
    if lt.get("month"):
        out.append(f"<p class=cit>Carteiras dos fundos (CDA) de {v(engine, 'lookthrough.month')}; profundidade máxima {v(engine, 'lookthrough.max_depth')}.</p>")
    out.append("<h3>Sobreposição</h3>")
    rows = []
    for i, s in enumerate(lt.get("shared_exposure") or []):
        q = f"lookthrough.shared_exposure[{i}]"
        legs = "<br>".join(
            f"{v(engine, f'{q}.legs[{j}].line_id')}: {v(engine, f'{q}.legs[{j}].via')} — {v(engine, f'{q}.legs[{j}].value_brl')}"
            for j in range(len(s.get("legs") or []))
        )
        name = v(engine, f"{q}.name") if s.get("name") else v(engine, f"{q}.key")
        rows.append([name, v(engine, f"{q}.level"), legs, v(engine, f"{q}.total_brl"), v(engine, f"{q}.total_pct")])
    out.append(_table([("Exposição", False), ("Nível", False), ("Caminhos", False), ("Total", True), ("Peso", True)], rows))
    if lt.get("top_underlying"):
        out.append("<h3>O que está por baixo (maiores exposições)</h3>")
        rows = [[v(engine, f"lookthrough.top_underlying[{i}].name"), v(engine, f"lookthrough.top_underlying[{i}].value_brl"),
                 v(engine, f"lookthrough.top_underlying[{i}].weight_pct")] for i in range(len(lt["top_underlying"]))]
        out.append(_table([("Ativo subjacente", False), ("Valor", True), ("Peso", True)], rows))
    out.append("<h3>Indexador</h3>")
    out.append(_bucket_table(engine, "indexer", "indexer", "Indexador"))
    out.append("<h3>Setor</h3>")
    out.append(_bucket_table(engine, "sector", "sector", "Setor"))
    return "\n".join(out)


def _restatements_section(engine: dict) -> str:
    rows = []
    for i, _r in enumerate((engine.get("restatements") or {}).get("items") or []):
        q = f"restatements.items[{i}]"
        rows.append([
            v(engine, f"{q}.fund_name"), v(engine, f"{q}.document"), v(engine, f"{q}.competencia"),
            v(engine, f"{q}.delivered_at"), v(engine, f"{q}.modalidade"), v(engine, f"{q}.n_fields_changed"),
            f'<span class="tag unk">{v(engine, f"{q}.assessment")}</span>',
        ])
    return _table([("Fundo", False), ("Documento", False), ("Competência", False), ("Entregue em", False),
                   ("Modalidade", False), ("Campos alterados", True), ("Avaliação", False)], rows)


def _movement_section(engine: dict) -> str:
    """Movimento incomum: the table holds the funds at atenção or forte; the funds with no verdict say why."""
    mv = engine.get("movement") or {}
    out = [f"<p>Movimento incomum em <span class=v>{v(engine, 'movement.month')}</span>: retorno mensal da cota de cada fundo "
           "contra o dos fundos da mesma classe ANBIMA. "
           f"Em atenção: <span class=v>{v(engine, 'movement.counts.atencao')}</span>. "
           f"Forte: <span class=v>{v(engine, 'movement.counts.forte')}</span>. "
           f"Normal: <span class=v>{v(engine, 'movement.counts.normal')}</span>. "
           f'<span class="tag unk">não avaliado</span>: <span class=v>{v(engine, "movement.counts.nao_avaliado")}</span>.</p>',
           f"<p>{v(engine, 'movement.definition')} {v(engine, 'movement.class_note')}</p>",
           f"<p>{v(engine, 'movement.levels_note')} {v(engine, 'movement.note')}</p>"]
    rows = []
    for i, x in enumerate(mv.get("by_line") or []):
        if x.get("level") not in ("atencao", "forte"):
            continue
        q = f"movement.by_line[{i}]"
        rows.append([
            v(engine, f"{q}.fund_name"), v(engine, f"{q}.class_as_filed"), v(engine, f"{q}.n_peers"),
            v(engine, f"{q}.own_value_pct"), v(engine, f"{q}.class_mean_pct"), v(engine, f"{q}.class_sd_pct"),
            v(engine, f"{q}.z"), f'<span class="tag unk">{v(engine, f"{q}.level_label")}</span>',
        ])
    if rows:
        out.append(_table([("Fundo", False), ("Classe ANBIMA", False), ("Pares", True), ("Retorno do mês", True),
                           ("Média da classe", True), ("Desvio padrão da classe", True), ("z", True), ("Nível", False)], rows))
    elif mv.get("status") != "unknown":
        out.append("<p>Nenhum fundo da carteira ficou em atenção ou forte neste mês.</p>")
    ne = mv.get("not_evaluated") or []
    if ne:
        items = "".join(
            f"<li><strong>{v(engine, f'movement.not_evaluated[{i}].fund_name')}</strong> "
            f'(<span class="tag unk">não avaliado</span>): {v(engine, f"movement.not_evaluated[{i}].reason")}.</li>'
            for i in range(len(ne))
        )
        out.append(f"<ul>{items}</ul>")
    if mv.get("status") == "unknown":
        out.append(f'<p class="indisponivel">Não avaliado: {v(engine, "movement.reason")}.</p>')
    if mv.get("n_not_fund_lines"):
        out.append(f"<p>Linhas que não são fundos com CNPJ (sem classe para comparar): "
                   f"<span class=v>{v(engine, 'movement.n_not_fund_lines')}</span>.</p>")
    return "\n".join(out)


def _risk_section(engine: dict) -> str:
    rk = engine.get("risk_screens") or {}
    if engine.get("movement"):
        out = [_movement_section(engine)]
    else:
        out = ['<p>Movimento anormal de cota ou de patrimônio: <span class="tag unk">não avaliado</span> '
               "(a regra ainda não foi definida).</p>"]
    if rk.get("screens_run") is not None:
        out.append(f"<p>Telas executadas: <span class=v>{v(engine, 'risk_screens.screens_run')}</span>. "
                   f"Ocorrências na carteira: <span class=v>{e(len(rk.get('hits') or []))}</span>.</p>")
    hits = rk.get("hits") or []
    if hits:
        rows = [[v(engine, f"risk_screens.hits[{i}].screen"), v(engine, f"risk_screens.hits[{i}].line_id"),
                 v(engine, f"risk_screens.hits[{i}].cnpj")] for i in range(len(hits))]
        out.append(_table([("Tela", False), ("Linha", False), ("CNPJ", False)], rows))
    return "\n".join(out)


def _unknowns_section(engine: dict, narrative: Narrative) -> str:
    items = []
    for name, sec in sorted((engine.get("sections") or {}).items()):
        if isinstance(sec, dict) and sec.get("status") not in ("complete", None):
            affects = sec.get("affects") or []
            aff = f" Linhas afetadas: {e(', '.join(map(str, affects)))}." if affects else ""
            items.append(f"<li><strong>{e(name)}</strong> ({e(SECTION_STATUS_LABELS.get(sec['status'], sec['status']))}): "
                         f"{v(engine, f'sections.{name}.reason')}.{aff}</li>")
    for i, ln in enumerate(engine.get("lines") or []):
        ident = ln.get("identification") or {}
        if ident.get("status") == "unknown":
            items.append(f"<li><strong>Linha {v(engine, f'lines[{i}].line_id')}</strong> não identificada: "
                         f"{v(engine, f'lines[{i}].identification.reason')}. Valor: {v(engine, f'lines[{i}].value_brl')}.</li>")
    for i, b in enumerate((engine.get("fees") or {}).get("by_line") or []):
        if b.get("label") == "desconhecido" or (b.get("fee_status") and b.get("disclosed_pct_year") is None
                                                  and b.get("disclosed_min_pct_year") is None):
            items.append(f"<li><strong>Taxa da linha {v(engine, f'fees.by_line[{i}].line_id')}</strong> "
                         f"({v(engine, f'fees.by_line[{i}].fee_status') if b.get('fee_status') else 'desconhecida'}): "
                         f"{v(engine, f'fees.by_line[{i}].reason')}</li>")
    if "abnormal_movement" not in (engine.get("sections") or {}) and not engine.get("movement"):
        items.append("<li><strong>abnormal_movement</strong> (não avaliado): regra de movimento anormal ainda não definida.</li>")
    for i, _n in enumerate((engine.get("risk_screens") or {}).get("not_run") or []):
        items.append(f"<li><strong>Tela {v(engine, f'risk_screens.not_run[{i}].screen')}</strong>: "
                     f"{v(engine, f'risk_screens.not_run[{i}].reason')}.</li>")
    if narrative.status != "complete":
        items.append(f"<li><strong>Texto interpretativo</strong>: {e(narrative.reason)}.</li>")
    return "<ul>" + "".join(items) + "</ul>" if items else "<p>Nenhuma seção ficou sem avaliação.</p>"


def _method_section(engine: dict, narrative: Narrative) -> str:
    served = ", ".join(sorted(set(narrative.served_by)))
    model = e(narrative.model or "—") + (f" (respondido por {e(served)} via fallback do provedor)" if served else "")
    lines = [
        "Todo número deste relatório vem do JSON do motor do SILO. O texto foi escrito por um modelo de linguagem (Redator) "
        "que não digita algarismos: cada valor é um marcador ligado a um campo do JSON e é preenchido na montagem do relatório.",
        "Um Revisor independente confere cada frase: marcadores que não existem, algarismos fora de marcador, citações fora da "
        "proveniência e valores extremos sem confirmação removem a frase.",
        "A taxa de administração mostrada é a divulgada pelo fundo, na ordem Extrato CVM, lâmina, cadastro cad_fi; uma taxa 0 informada "
        "é mostrada como tal, \"a conferir\", e um valor acima de 5% a.a. também; nenhum dos dois é usado como custo, somado ou comparado, e nenhum é dado como errado. "
        "Quando a lâmina é mais recente que o Extrato e o Extrato informou 0 ou acima de 5% a.a., a taxa da lâmina é a mostrada e entra na soma, "
        "com a marca \"fontes divergem\" e o valor do Extrato ao lado, fora de qualquer conta. Para ETFs, que não têm taxa no Extrato, na lâmina "
        "nem no cad_fi, a taxa é a informada pelo site etfsbrasil.com.br (fonte de terceiros), com a data, somada à parte; o número de cotistas e o "
        "patrimônio líquido do ETF vêm da mesma coleta do mesmo site, como dado descritivo, nunca somados. A estimativa vem do balancete do "
        "fundo (contas COFI 8.1.7, acumuladas no exercício), fica em campo à parte, rotulada \"estimativa, não divulgada\", e nunca substitui "
        "nem se soma à taxa divulgada. A taxa de performance e os demais termos aparecem como o fundo os informou.",
        "Reapresentações são mostradas como \"revisado, não avaliado\": os limiares de materialidade ainda não foram definidos. Movimento anormal de cota e de patrimônio: não avaliado nesta versão.",
        "Grupo econômico não avaliado: não há fonte pública arquivada da estrutura de grupo, e o SILO não infere grupo por nome.",
        "Sem previsão de retorno e sem recomendação de compra, venda ou manutenção de qualquer ativo.",
        "Classificações por indexador e setor seguem regras versionadas; o que não tem regra aparece como \"sem classificação\".",
        f"Modelo: {model}. Provedor: {e(narrative.provider or '—')}. Custo do texto: US$ {narrative.cost_usd:.4f} "
        f"(teto de US$ {narrative.cost_cap_usd:.2f} por relatório).",
    ]
    out = "<ul>" + "".join(f"<li>{x}</li>" for x in lines) + "</ul>"
    if narrative.removed or narrative.notes:
        out += "<h3>Notas do Revisor</h3><ul>"
        for r in narrative.removed:
            scope = "achado removido" if r.whole_finding else "frase removida"
            out += f"<li>{e(r.finding_id)} ({e(scope)}): {e(r.reason.replace('{{', '').replace('}}', ''))}</li>"
        for n in narrative.notes:
            out += f"<li>{e(n)}</li>"
        out += "</ul>"
    return out


def _sources(engine: dict) -> str:
    dates: dict[str, str] = {}
    for k, d in (engine.get("data_dates") or {}).items():
        if d:
            dates[str(k).upper()] = str(d)
    for p in engine.get("provenance") or []:
        src = str(p.get("source") or "").upper()
        if src and p.get("data_date") and src not in dates:
            dates[src] = str(p["data_date"])
    used = {str(p.get("source") or "").upper() for p in engine.get("provenance") or []} | set(dates)
    used.discard("")
    items = []
    for src in sorted(used):
        key = next((k for k in (engine.get("data_dates") or {}) if str(k).upper() == src), None)
        when = v(engine, f"data_dates.{key}") if key else e(format_value({}, "d", dates.get(src))) if dates.get(src) else "data não informada"
        items.append(f"<li>{e(SOURCE_LABELS.get(src, src))}: dados até {when}</li>")
    endpoints = sorted({str(p.get("endpoint")) for p in engine.get("provenance") or [] if p.get("endpoint")})
    tail = f"<p class=nota>Consultas ao SILO: {e(', '.join(endpoints))}.</p>" if endpoints else ""
    return "<ul>" + "".join(items) + "</ul>" + tail


def render_html(engine: dict, narrative: Narrative, assinatura: str | None = None) -> str:
    template = (TEMPLATES / "report.html").read_text(encoding="utf-8")
    css = (TEMPLATES / "report.css").read_text(encoding="utf-8")

    def section(title: str, body: str) -> str:
        return f"<section><h2>{e(title)}</h2>\n{body}\n</section>"

    corpo = [
        section("Resumo", _findings_html(engine, narrative, "resumo")
                + (f"<h3>{e(SECTION_TITLES['achados'])}</h3>" + _findings_html(engine, narrative, "achados")
                   if narrative.status == "complete" and any(f.section == "achados" for f in narrative.kept) else "")),
        section("Identificação linha a linha", _ident_section(engine) + _findings_html(engine, narrative, "identificacao")),
        section("Custo em taxas", _fees_section(engine) + _findings_html(engine, narrative, "taxas")),
        section("Exposição", _exposure_section(engine) + _findings_html(engine, narrative, "exposicao")),
        section("Reapresentações", _restatements_section(engine) + _findings_html(engine, narrative, "reapresentacoes")),
        section("Sinais de risco", _risk_section(engine) + _findings_html(engine, narrative, "sinais_de_risco")),
        section("O que não foi possível avaliar", _unknowns_section(engine, narrative)),
        section("Metodologia e limitações", _method_section(engine, narrative)),
    ]
    meta = (f"Data de referência da carteira: {v(engine, 'valuation_date')} · "
            f"Diagnóstico gerado em {v(engine, 'generated_at')}")
    aviso = ""
    if engine.get("illustrative"):
        aviso = ('<p class="aviso">Exemplo com dados ilustrativos: este relatório foi montado a partir de um JSON de teste '
                 "e não é o diagnóstico de uma carteira real.</p>")
    return fill(template, {
        "titulo": "SILO · Diagnóstico de carteira",
        "css": css,
        "meta": meta,
        "aviso": aviso,
        "corpo": "\n".join(corpo),
        "fontes": _sources(engine),
        "assinatura": e(signature(assinatura)),
        "aviso_legal": DISCLAIMER_HTML,
    })


def html_to_pdf(html_text: str, out_path: str | Path) -> Path:
    """Render with WeasyPrint (imported here so HTML works where pango is absent)."""
    from weasyprint import HTML

    out = Path(out_path)
    HTML(string=html_text, base_url=str(TEMPLATES)).write_pdf(str(out))
    return out
