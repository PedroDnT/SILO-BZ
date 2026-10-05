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

from src.portfolio.report import charts
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
    "cota_listada": "cota de fundo listada", "credito_privado": "crédito privado direto", "fip": "FIP",
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
    # Why the narrative is unknown, as a bare identifier (an LLMError class name or
    # "revisor_removed_all"), safe for a response header; ``reason`` may quote the model.
    reason_code: str | None = None
    # The CostMeter's calls (role, model, cost, token counts): numbers and fixed names only.
    calls: list[dict] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    served_by: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    cost_cap_usd: float = 0.0



# engine 1.9 liquidity table: where the filed terms came from, and the broker label kept only for a pension wrapper
TERMS_SOURCE_LABEL = {"extrato": "Extrato da CVM", "lamina": "lâmina"}
PREV_WRAPPER = re.compile(r"previd|pgbl|vgbl", re.I)
RATING_NOT_FILED = ("0", "-", "—")

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


NARRATIVE_UNAVAILABLE = ("Texto interpretativo indisponível neste relatório; as tabelas e a seção do que não foi possível "
                         "avaliar seguem completas.")


def _findings_html(engine: dict, narrative: Narrative, section: str) -> str:
    if narrative.status != "complete":
        # a fixed text: narrative.reason may quote the provider's error, and it never reaches the page (engine 1.7)
        return f'<p class="indisponivel">{e(NARRATIVE_UNAVAILABLE)}</p>' if section == "resumo" else ""
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
        if ident.get("method") == "cnpj_extrato" and ident.get("reason"):
            note += f'<br><span class="tag unk">{v(engine, f"{p}.identification.reason")}</span>'
        facts = []
        if ln.get("vencimento"):
            facts.append(f"vencimento {v(engine, f'{p}.vencimento')}")
        if ln.get("taxa_texto"):
            facts.append(f"taxa {v(engine, f'{p}.taxa_texto')}")
        if (ln.get("n_source_lines") or 1) > 1:
            facts.append(f"agrega {v(engine, f'{p}.n_source_lines')} linhas do extrato")
        if facts:
            note += f"<br><span class=cit>{' · '.join(facts)}</span>"
        tag = "unk" if status != "identified" else ""
        badges = "".join(f' <span class="tag unk">{v(engine, f"{p}.badges[{j}].label")}</span>'
                         for j in range(len(ln.get("badges") or [])))
        rows.append([
            v(engine, f"{p}.line_id"),
            v(engine, f"{p}.instrument") + (f"<br><span class=cit>{v(engine, f'{p}.fund_name')}</span>" if ln.get("fund_name") else ""),
            e(ASSET_LABELS.get(ln.get("asset_type"), ln.get("asset_type") or "—")),
            code,
            v(engine, f"{p}.value_brl"),
            v(engine, f"{p}.weight_pct"),
            f'<span class="tag {tag}">{e(STATUS_LABELS.get(status, status))}</span>{badges}{note}',
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
    out = head + _table(_FEE_HEADERS, rows) + charts.fee_chart(engine) + _fee_comparison_html(engine)
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


def _fee_comparison_html(engine: dict) -> str:
    comp = (engine.get("fees") or {}).get("comparison")
    if not comp:
        return ""
    base = "fees.comparison"
    out = ("<h3>Taxas versus fundos comparáveis</h3>"
           f"<p>{v(engine, base + '.basis')}</p>"
           f"<p>Comparação em {v(engine, base + '.as_of')}. Cobertura: "
           f"{v(engine, base + '.coverage_fund_value_pct')} do valor em fundos e "
           f"{v(engine, base + '.coverage_portfolio_value_pct')} da carteira.</p>")
    for i, row in enumerate(comp.get("by_line") or []):
        q = f"{base}.by_line[{i}]"
        out += "<h4>" + v(engine, q + '.fund_name') + "</h4>"
        if row.get("status") != "compared":
            out += "<p>não comparado: " + v(engine, q + '.reason') + "</p>"
            continue
        cohort = (v(engine, q + '.classe_anbima') + "; fundo de fundos: " + v(engine, q + '.fundo_cotas')
                  + "; " + v(engine, q + '.tp_fundo_classe'))
        out += "<p>Grupo comparável: " + cohort + ". Data da taxa: " + v(engine, q + '.fee_as_of') + ".</p>"
        out += _table([("Taxa a.a.", True), ("Mediana a.a.", True), ("p25 / p75 a.a.", True),
                       ("Diferença", True), ("Percentil", True)],
                      [[v(engine, q + '.own_fee_pct_year'), v(engine, q + '.median_pct_year'),
                        v(engine, q + '.p25_pct_year') + " / " + v(engine, q + '.p75_pct_year'),
                        v(engine, q + '.difference_pp'), v(engine, q + '.percentile_pct')]])
        out += ("<p>Pares utilizáveis: " + v(engine, q + '.n_peers') + "; excluídos: " + v(engine, q + '.n_excluded')
                + ". Datas dos pares: " + v(engine, q + '.peer_fee_oldest') + " a "
                + v(engine, q + '.peer_fee_newest') + ".</p>")
        out += _etf_peers_html(engine, q, row)
    return out


ETF_PEERS_LABEL = "informativo, não é recomendação"
ETF_PEERS_IN_STATS = ("a mediana, os quartis e o percentil acima incluem esses ETFs, com a taxa de um site de terceiros "
                      "(não é documento da CVM)")


def _etf_peers_html(engine: dict, q: str, row: dict) -> str:
    """Catalog v66 (#609): the peer group split into funds and ETFs, as the API serves it. Only when the engine carries
    the split; an ETF peer's fee is the third-party site's (``etf_peer_fee_source``), never a CVM-disclosed fee."""
    if row.get("n_etf_peers") is None:
        return ""
    out = (f"<p>Dos pares: <span class=v>{v(engine, q + '.n_fund_peers')}</span> fundos e "
           f"<span class=v>{v(engine, q + '.n_etf_peers')}</span> ETFs")
    if row.get("n_etf_excluded"):
        out += f" (ETFs sem taxa utilizável, fora: {v(engine, q + '.n_etf_excluded')})"
    out += f'. <span class="tag est">{e(ETF_PEERS_LABEL)}</span>'
    if row.get("n_etf_peers"):
        out += f'<br><span class="tag unk">{e(ETF_PEERS_IN_STATS)}</span>'
        if row.get("etf_peer_tickers"):
            out += f"<br><span class=cit>ETFs: {e(', '.join(str(t) for t in row['etf_peer_tickers']))}</span>"
        if row.get("etf_peer_fee_source"):
            out += f"<br><span class=cit>taxa dos ETFs: {v(engine, q + '.etf_peer_fee_source')}"
            if row.get("etf_peer_fee_oldest"):
                out += f", coletas de {v(engine, q + '.etf_peer_fee_oldest')} a {v(engine, q + '.etf_peer_fee_newest')}"
            out += "</span>"
    return out + "</p>"


WINDOW_LABEL = {"12m": "12 meses", "6m": "6 meses"}


def _equivalents_section(engine: dict) -> str:
    """Engine 1.13: the market equivalent of each fund line beside the class's return distribution. A fact beside the
    fund, labelled "equivalente de mercado; não é recomendação": no ranking, no "melhor", no instruction. A line with no
    equivalent says why with the fixed text of its code."""
    eq = engine.get("equivalents") or {}
    b = "equivalents"
    out = [f'<p><span class="tag unk">{v(engine, f"{b}.label")}</span></p>',
           f"<p class=cit>{v(engine, f'{b}.choice_note')}</p>",
           f"<p class=cit>{v(engine, f'{b}.class_note')}</p>"]
    rows = []
    none = []
    for i, ln in enumerate(eq.get("lines") or []):
        q = f"{b}.lines[{i}]"
        fund = f"{v(engine, f'{q}.line_id')} {v(engine, f'{q}.fund_name')}"
        if ln.get("status") != "encontrado" or not ln.get("etf"):
            none.append(f"<li>{fund}: {v(engine, f'{q}.reason')}.</li>")
            continue
        et = f"{q}.etf"
        fund += f"<br><span class=cit>classe {v(engine, f'{q}.classe_anbima')}</span>"
        etf = (f"<span class=v>{v(engine, f'{et}.ticker')}</span> {v(engine, f'{et}.name')}"
               f"<br><span class=cit>índice {v(engine, f'{et}.underlying_index')}</span>"
               f"<br>PL {v(engine, f'{et}.pl_brl')} em {v(engine, f'{et}.pl_as_of')}"
               f"<br><span class=cit>{v(engine, f'{et}.pl_label')}</span>")
        if ln["etf"].get("fee_pct_year") is not None:
            etf += (f"<br>taxa {v(engine, f'{et}.fee_pct_year')} a.a. em {v(engine, f'{et}.fee_as_of')}"
                    f"<br><span class=cit>{v(engine, f'{et}.fee_label')}</span>")
        else:
            etf += f"<br><span class=cit>{v(engine, f'{et}.fee_reason')}</span>"
        etf += f'<br><span class="tag unk">sem proventos</span><br><span class=cit>{v(engine, f"{et}.basis_label")}</span>'
        for j, w in enumerate(ln.get("windows") or []):
            wq = f"{q}.windows[{j}]"
            label = (e(WINDOW_LABEL.get(w.get("id"), w.get("id")))
                     + f"<br><span class=cit>{v(engine, f'{wq}.base_month')} a {v(engine, f'{wq}.end_month')}</span>")

            def ret(who: str) -> str:
                if w.get(f"{who}_net_return_pct") is None:
                    why = w.get(f"{who}_reason")
                    return f"<span class=cit>{v(engine, f'{wq}.{who}_reason')}</span>" if why else "—"
                cell = f"<span class=v>{v(engine, f'{wq}.{who}_net_return_pct')}</span>"
                if w.get(f"{who}_band_label"):
                    cell += f"<br><span class=cit>{v(engine, f'{wq}.{who}_band_label')}</span>"
                return cell

            if w.get("class_median_pct") is not None:
                cls = (f"p25 {v(engine, f'{wq}.class_p25_pct')}<br>mediana {v(engine, f'{wq}.class_median_pct')}"
                       f"<br>p75 {v(engine, f'{wq}.class_p75_pct')}<br><span class=cit>{v(engine, f'{wq}.class_n_funds')} fundos</span>")
            else:
                cls = f"<span class=cit>{v(engine, f'{wq}.class_reason')}</span>" if w.get("class_reason") else "—"
            rows.append([fund if j == 0 else "", etf if j == 0 else "", label, ret("fund"), ret("etf"), cls])
    if rows:
        out.append(_table([("Fundo", False), ("Equivalente de mercado (ETF)", False), ("Janela", False),
                           ("Retorno líquido do fundo", True), ("Retorno do ETF", True), ("Classe ANBIMA do fundo", True)], rows))
        out.append(f"<ul><li class=cit>{v(engine, f'{b}.band_note')}</li></ul>")
    if none:
        out.append("<p>Fundos sem equivalente de mercado:</p><ul>" + "".join(none) + "</ul>")
    if eq.get("status") in ("partial", "unknown") and eq.get("reason"):
        out.append(f'<p><span class="tag unk">{e(SECTION_STATUS_LABELS.get(eq["status"], eq["status"]))}</span> {v(engine, f"{b}.reason")}.</p>')
    return "\n".join(out)


def _returns_section(engine: dict) -> str:
    """Engine 1.10: the return per position over 12 and 6 months, beside the CDI of the same dates. One row per line
    and window; a line not evaluated says why with the fixed text of its code. No portfolio total, mean or ranking:
    a negative fee per point is shown as computed and marked as never aggregated."""
    r = engine.get("returns") or {}
    b = "returns"
    out = [f"<p class=cit>{v(engine, f'{b}.note')}</p>",
           f"<p class=cit>{v(engine, f'{b}.definition')}</p>"]
    cov = []
    for i, c in enumerate(r.get("coverage") or []):
        cov.append(f"{e(WINDOW_LABEL.get(c.get('id'), c.get('id')))}: {v(engine, f'{b}.coverage[{i}].n_evaluated')} linhas, "
                   f"{v(engine, f'{b}.coverage[{i}].evaluated_value_brl')} "
                   f"({v(engine, f'{b}.coverage[{i}].coverage_portfolio_value_pct')} da carteira)")
    if cov:
        out.append(f"<p>Linhas com retorno avaliado: {'; '.join(cov)}. A cobertura é parte do valor do extrato, não um retorno.</p>")
    cdi = r.get("cdi") or {}
    if cdi.get("status") == "ok":
        out.append(f"<p class=cit>CDI: série SGS {v(engine, f'{b}.cdi.sgs_code')} do Banco Central, "
                   f"{v(engine, f'{b}.cdi.first_date')} a {v(engine, f'{b}.cdi.last_date')}; {v(engine, f'{b}.cdi.convention')}.</p>")
    elif cdi.get("reason"):
        out.append(f'<p><span class="tag unk">CDI não disponível</span> {v(engine, f"{b}.cdi.reason")}.</p>')
    rows = []
    for i, ln in enumerate(r.get("lines") or []):
        q = f"{b}.lines[{i}]"
        asset = f"{v(engine, f'{q}.line_id')} {v(engine, f'{q}.instrument')}"
        if ln.get("status") != "avaliado":
            rows.append([asset, "—", f'<span class="tag unk">{v(engine, f"{q}.status_label")}</span><br>'
                                     f"<span class=cit>{v(engine, f'{q}.reason')}</span>", "—", "—", "—", "—", "—"])
            continue
        asset += f"<br><span class=cit>{v(engine, f'{q}.basis_label')}</span>"
        if ln.get("without_distributions"):
            asset += '<br><span class="tag unk">sem proventos</span>'
        for j, w in enumerate(ln.get("windows") or []):
            wq = f"{q}.windows[{j}]"
            label = e(WINDOW_LABEL.get(w.get("id"), w.get("id")))
            label += f"<br><span class=cit>{v(engine, f'{wq}.base_month')} a {v(engine, f'{wq}.end_month')}</span>"
            label += "".join(f"<br><span class=cit>{v(engine, f'{wq}.notes[{k}]')}</span>" for k in range(len(w.get("notes") or [])))
            if w.get("status") != "avaliado":
                rows.append([asset if j == 0 else "", label, f'<span class="tag unk">{v(engine, f"{wq}.status_label")}</span>'
                             f"<br><span class=cit>{v(engine, f'{wq}.reason')}</span>", "—", "—", "—", "—", "—"])
                continue
            net = f"<span class=v>{v(engine, f'{wq}.net_return_pct')}</span>"
            if w.get("gross_return_est_pct") is not None:
                net += (f"<br><span class=cit>bruto: {v(engine, f'{wq}.gross_return_est_pct')} "
                        f'</span><span class="tag est">{v(engine, f"{wq}.gross_label")}</span>')
            if w.get("cdi_pct") is not None:
                cdi_cell = (f"{v(engine, f'{wq}.cdi_pct')}<br><span class=cit>{v(engine, f'{wq}.cdi_base_date')} a "
                            f"{v(engine, f'{wq}.cdi_end_date')}</span>")
                vs = v(engine, f"{wq}.net_minus_cdi_pp")
                if w.get("pct_of_cdi") is not None:  # engine 1.13: only for a fund whose filed benchmark is CDI or DI
                    vs += f"<br><span class=v>{v(engine, f'{wq}.pct_of_cdi')}</span>"
                elif w.get("pct_of_cdi_reason") and w.get("pct_of_cdi_reason_code") != "pct_cdi_so_fundos":
                    vs += f"<br><span class=cit>{v(engine, f'{wq}.pct_of_cdi_reason')}</span>"
            else:
                cdi_cell = f"<span class=cit>{v(engine, f'{wq}.cdi_reason')}</span>" if w.get("cdi_reason") else "—"
                vs = "—"
            vol = "—"
            if w.get("volatility_annual_pct") is not None:
                vol = f"{v(engine, f'{wq}.volatility_annual_pct')}<br><span class=cit>{v(engine, f'{wq}.volatility_note')}</span>"
            dd = v(engine, f"{wq}.max_drawdown_pct")
            if w.get("max_drawdown_peak_month"):
                dd += (f"<br><span class=cit>{v(engine, f'{wq}.max_drawdown_peak_month')} a "
                       f"{v(engine, f'{wq}.max_drawdown_trough_month')}</span>")
            rows.append([asset if j == 0 else "", label, net, cdi_cell, vs, vol, dd, _fee_drag_html(engine, wq, w)])
    out.append(_table([("Linha e base", False), ("Janela", False), ("Retorno líquido", True), ("CDI nas mesmas datas", True),
                       ("Líquido menos CDI (e % do CDI)", True), ("Volatilidade anualizada", True), ("Queda máxima", True),
                       ("Taxa por ponto e perda de Sharpe", False)], rows))
    notes = [v(engine, f"{b}.gross_note"), v(engine, f"{b}.sharpe_drag_note"), v(engine, f"{b}.drawdown_note")]
    fpp = next((f"{b}.lines[{i}].windows[{j}].fee_per_point_note" for i, ln in enumerate(r.get("lines") or [])
                for j, w in enumerate(ln.get("windows") or []) if w.get("fee_per_point_note")), None)
    if fpp:
        notes.append("taxa por ponto: " + v(engine, fpp))
    line_notes = []
    for i, ln in enumerate(r.get("lines") or []):
        for k, n in enumerate(ln.get("notes") or []):
            if n not in [x[0] for x in line_notes]:
                line_notes.append((n, f"{b}.lines[{i}].notes[{k}]"))
    notes += [v(engine, path) for n, path in line_notes if n != r.get("performance_note")]
    if any(ln.get("performance_fee_filed") for ln in r.get("lines") or []):
        notes.append(v(engine, f"{b}.performance_note"))
    if r.get("pct_of_cdi_note") and any(w.get("pct_of_cdi") is not None for ln in r.get("lines") or []
                                        for w in ln.get("windows") or []):
        notes.append(v(engine, f"{b}.pct_of_cdi_note"))
    out.append("<ul>" + "".join(f"<li class=cit>{n}</li>" for n in notes if n and n != "—") + "</ul>")
    if r.get("status") in ("partial", "unknown") and r.get("reason"):
        out.append(f'<p><span class="tag unk">{e(SECTION_STATUS_LABELS.get(r["status"], r["status"]))}</span> {v(engine, f"{b}.reason")}.</p>')
    return "\n".join(out)


def _fee_drag_html(engine: dict, wq: str, w: dict) -> str:
    """The fee per point of gross return and the Sharpe the fee takes, each with the engine's own note; a value outside
    every aggregate (gross at or below zero) is marked so."""
    parts = []
    if w.get("fee_per_point") is not None:
        t = f"taxa por ponto: <span class=v>{v(engine, f'{wq}.fee_per_point')}</span>"
        if w.get("fee_pct_period") is not None:
            t += f" (taxa do período {v(engine, f'{wq}.fee_pct_period')})"
        if w.get("fee_per_point_excluded_from_aggregates"):
            t += ' <span class="tag unk">fora de qualquer média ou ranking</span>'
        parts.append(t)
    elif w.get("fee_reason"):
        parts.append(f"<span class=cit>{v(engine, f'{wq}.fee_reason')}</span>")
    if w.get("sharpe_drag") is not None:
        parts.append(f"perda de Sharpe: <span class=v>{v(engine, f'{wq}.sharpe_drag')}</span>")
    elif w.get("sharpe_drag_note") and w.get("fee_status") == "ok":
        parts.append(f"<span class=cit>perda de Sharpe: {v(engine, f'{wq}.sharpe_drag_note')}</span>")
    return "<br>".join(parts) or "—"


TAX_STATUS_PLAIN = ("isento", "aliquota_hoje")  # a rate in force without a condition: no "a conferir" tag


def _tax_fee_html(engine: dict, q: str, f: dict) -> str:
    """The fee paid in R$ a year, as the fee block's headline: an estimate, a range, or the fee block's own label."""
    st = f.get("status")
    if st == "estimada":
        out = (f"<span class=v>{v(engine, f'{q}.fee.per_year_brl')}</span> por ano<br>"
               f"<span class=cit>{v(engine, f'{q}.fee.rate_pct_year')} a.a.</span>")
    elif st == "faixa":
        out = (f"<span class=v>{v(engine, f'{q}.fee.per_year_min_brl')}</span> a "
               f"<span class=v>{v(engine, f'{q}.fee.per_year_max_brl')}</span> por ano<br>"
               f"<span class=cit>{v(engine, f'{q}.fee.rate_min_pct_year')} a {v(engine, f'{q}.fee.rate_max_pct_year')} a.a.</span>")
    else:
        return f"<span class=cit>{v(engine, f'{q}.fee.fee_status')}</span>" if f.get("fee_status") else "—"
    out += f' <span class="tag est">{v(engine, f"{q}.fee.label")}</span>'
    if f.get("third_party"):
        out += f"<br><span class=cit>{v(engine, f'{q}.fee.third_party_label')}</span>"
    if (f.get("loading") or {}).get("text"):
        out += f"<br><span class=cit>{v(engine, f'{q}.fee.loading.text')}</span>"
    return out


def _tax_rate_html(engine: dict, q: str, t: dict) -> str:
    """The rate in force with its article, "isento" with its article, the bracket, or why there is no rule."""
    st = t.get("status")
    tag = f'<span class="tag {"" if st in TAX_STATUS_PLAIN else "unk"}">{v(engine, f"{q}.tax.status_label")}</span>'
    if st == "sem_regra":
        return f"{tag}<br><span class=cit>{v(engine, f'{q}.tax.reason')}</span>"
    if st == "previdencia":
        return f"{tag}<br><span class=cit>dois regimes, ver Previdência abaixo</span>"
    out = ""
    if t.get("rate_text"):
        out = f"<span class=v>{v(engine, f'{q}.tax.rate_text')}</span>"
        if t.get("instrument_label"):
            out += f" <span class=cit>({v(engine, f'{q}.tax.instrument_label')})</span>"
        if t.get("article"):
            out += f"<br><span class=cit>{v(engine, f'{q}.tax.article')}</span>"
    if t.get("bracket"):
        out += ("<br>" if out else "") + f"<span class=cit>{v(engine, f'{q}.tax.bracket.text')}</span>"
        if not t.get("rate_text"):
            arts = [f"{v(engine, f'{q}.tax.candidates[{j}].label')}: {v(engine, f'{q}.tax.candidates[{j}].article')}"
                    for j, c in enumerate(t.get("candidates") or []) if c.get("article")]
            if arts:
                out += f"<br><span class=cit>{'; '.join(arts)}</span>"
    if st in TAX_STATUS_PLAIN:
        return out
    return f"{out}<br>{tag}" if out else tag


def _tax_brl_html(engine: dict, q: str, t: dict) -> str:
    """The tax in R$ only when the engine computed it (an estimate); otherwise the bracket or the fixed reason."""
    est = t.get("estimate") or {}
    if t.get("status") == "sem_regra":
        return "—"  # the rate column already says why
    if est.get("tax_brl") is not None:
        return (f"<span class=v>{v(engine, f'{q}.tax.estimate.tax_brl')}</span> "
                f'<span class="tag est">{v(engine, f"{q}.tax.estimate.label")}</span>'
                f"<br><span class=cit>{v(engine, f'{q}.tax.estimate.rate_pct')} sobre o ganho de 12 meses de "
                f"{v(engine, f'{q}.tax.estimate.gain_12m_brl')} (retorno de {v(engine, f'{q}.tax.estimate.net_return_12m_pct')})</span>")
    if t.get("bracket") and est.get("reason_code") != "isento_sem_imposto":
        return f"<span class=cit>sem valor em R$: {v(engine, f'{q}.tax.bracket.text')}</span>"
    if est.get("reason"):
        return f"<span class=cit>{v(engine, f'{q}.tax.estimate.reason')}</span>"
    return "—"


def _tax_section(engine: dict) -> str:
    """Engine 1.11: fee paid and tax per position. No portfolio total of tax; the pension regimes side by side, neither
    picked; the optimization facts labelled "informativo; não é recomendação"; IOF only when the engine has it."""
    tx = engine.get("tax") or {}
    b = "tax"
    out = [f"<p class=cit>{v(engine, f'{b}.note')}</p>"]
    rows = []
    for i, ln in enumerate(tx.get("lines") or []):
        q = f"{b}.lines[{i}]"
        h = ln.get("holding") or {}
        hold = (f"aplicação em {v(engine, f'{q}.holding.data_aplicacao')} ({v(engine, f'{q}.holding.days_held')} dias)"
                if h.get("data_aplicacao") else v(engine, f"{q}.holding.text"))
        check = "<br>".join(f"<span class=cit>{v(engine, f'{q}.a_conferir[{j}].text')}</span>"
                            for j in range(len(ln.get("a_conferir") or [])))
        if check:
            check = f'<span class="tag unk">{v(engine, f"{q}.a_conferir[0].label")}</span><br>{check}'
        rows.append([f"{v(engine, f'{q}.line_id')} {v(engine, f'{q}.instrument')}<br><span class=cit>{hold}</span>",
                     _tax_fee_html(engine, q, ln.get("fee") or {}), _tax_rate_html(engine, q, ln.get("tax") or {}),
                     _tax_brl_html(engine, q, ln.get("tax") or {}), check or "—"])
    out.append(_table([("Linha", False), ("Taxa paga", False), ("Imposto: alíquota em vigor", False),
                       ("Imposto em R$", False), ("A conferir", False)], rows))
    out.append(_pension_html(engine))
    out.append(_tax_info_html(engine))
    iof = [(i, ln) for i, ln in enumerate(tx.get("lines") or []) if ln.get("iof")]
    if iof:
        items = []
        for i, ln in iof:
            q = f"{b}.lines[{i}].iof"
            t = f"{v(engine, f'{b}.lines[{i}].line_id')}: {v(engine, f'{q}.text')}"
            if ln["iof"].get("rate_pct") is not None:
                t += f" (alíquota {v(engine, f'{q}.rate_pct')})"
            if ln["iof"].get("article"):
                t += f" <span class=cit>{v(engine, f'{q}.article')}</span>"
            items.append(f"<li>{t}</li>")
        out.append("<h3>IOF</h3><ul>" + "".join(items) + "</ul>")
    person = tx.get("person") or {}
    items = []
    for j, f in enumerate(person.get("flags") or []):
        if not f.get("flagged"):
            continue
        q = f"{b}.person.flags[{j}]"
        items.append(f"<li>{v(engine, f'{q}.text')}. Linhas: {e(', '.join(f.get('line_ids') or []))}. "
                     f"<span class=cit>{v(engine, f'{q}.article')}; não calculado</span></li>")
    if person.get("minimum_tax"):
        q = f"{b}.person.minimum_tax"
        items.append(f"<li>Tributação mínima: {v(engine, f'{q}.text')}. <span class=cit>{v(engine, f'{q}.article')}</span></li>")
    if items:
        out.append("<h3>Na pessoa física (sinalizado, sem valor)</h3><ul>" + "".join(items) + "</ul>")
    nc = tx.get("not_covered") or []
    if nc:
        out.append("<p class=cit>Sem regra de imposto: " + " ".join(v(engine, f"{b}.not_covered[{j}].text") for j in range(len(nc))) + "</p>")
    if tx.get("status") in ("partial", "unknown") and tx.get("reason"):
        out.append(f'<p><span class="tag unk">{e(SECTION_STATUS_LABELS.get(tx["status"], tx["status"]))}</span> {v(engine, f"{b}.reason")}.</p>')
    return "\n".join(out)


def _pension_html(engine: dict) -> str:
    """PGBL and VGBL lines: the regressive and the progressive regime in two columns, neither picked (#613)."""
    lines = [(i, ln) for i, ln in enumerate((engine.get("tax") or {}).get("lines") or []) if ln.get("pension")]
    if not lines:
        return ""
    out = ["<h3>Previdência (PGBL e VGBL): os dois regimes, nenhum indicado</h3>"]
    for i, ln in lines:
        q = f"tax.lines[{i}].pension"
        pe = ln["pension"]
        plan = v(engine, f"{q}.plan") if pe.get("plan") else "plano não impresso no extrato"
        head = f"<p>{v(engine, f'tax.lines[{i}].line_id')} {v(engine, f'tax.lines[{i}].instrument')}: {plan}"
        if pe.get("base"):
            head += f"; imposto sobre {v(engine, f'{q}.base')}"
        head += f". Regime: {v(engine, f'{q}.regime_label')}.</p>"
        reg = pe.get("regressive") or {}
        table = "<br>".join(_bracket_years(engine, f"{q}.regressive.table[{j}]", row)
                            for j, row in enumerate(reg.get("table") or []))
        left = f"{v(engine, f'{q}.regressive.text')}<br><span class=cit>{table}</span><br><span class=cit>{v(engine, f'{q}.regressive.article')}</span>"
        right = (f"{v(engine, f'{q}.progressive.text')}<br><span class=cit>{v(engine, f'{q}.progressive.article')}</span>")
        out.append(head + _table([("Regime regressivo", False), ("Regime progressivo", False)], [[left, right]]))
        out.append(f"<p class=cit>{v(engine, f'{q}.base_text')} {v(engine, f'{q}.irrevocable_text')}</p>")
    return "\n".join(out)


def _bracket_years(engine: dict, q: str, row: dict) -> str:
    """One row of the regressive table: "até 2 anos", "acima de 2 até 4 anos", "acima de 10 anos" (open ends as filed)."""
    lo, hi = row.get("over_years"), row.get("up_to_years")
    if not lo:
        span = f"até {v(engine, f'{q}.up_to_years')} anos"
    elif hi is None:
        span = f"acima de {v(engine, f'{q}.over_years')} anos"
    else:
        span = f"acima de {v(engine, f'{q}.over_years')} até {v(engine, f'{q}.up_to_years')} anos"
    return f"{span}: {v(engine, f'{q}.rate_pct')}"


def _tax_info_html(engine: dict) -> str:
    """The optimization facts of each line (next bracket, gross-up equivalence, come-cotas), each labelled
    "informativo; não é recomendação"."""
    items = []
    for i, ln in enumerate((engine.get("tax") or {}).get("lines") or []):
        for j, _o in enumerate(ln.get("optimization") or []):
            q = f"tax.lines[{i}].optimization[{j}]"
            items.append(f"<li>{v(engine, f'tax.lines[{i}].line_id')}: {v(engine, f'{q}.text')} "
                         f'<span class="tag est">{v(engine, f"{q}.label")}</span></li>')
    if not items:
        return ""
    return "<h3>Fatos de imposto por posição (informativo; não é recomendação)</h3><ul>" + "".join(items) + "</ul>"


def _bucket_table(engine: dict, base: str, label_key: str, label: str) -> str:
    rows = []
    for i, _b in enumerate(resolve(engine, f"{base}.buckets") or []):
        q = f"{base}.buckets[{i}]"
        rows.append([v(engine, f"{q}.{label_key}"), v(engine, f"{q}.value_brl"), v(engine, f"{q}.weight_pct")])
    return _table([(label, False), ("Valor", True), ("Peso", True)], rows)


def _exposure_section(engine: dict) -> str:
    lt = engine.get("lookthrough") or {}
    out = []
    if engine.get("allocation"):
        out.append("<h3>Por classe de ativo</h3>")
        out.append(f"<p class=cit>{v(engine, 'allocation.basis')}.</p>")
        out.append(_bucket_table(engine, "allocation", "asset_class", "Classe"))
        out.append(charts.allocation_chart(engine))
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
    origin = charts.exposure_origin_chart(engine)
    if origin:
        out.append("<h3>De onde vem a exposição ao mesmo ativo</h3>")
        out.append(origin)
    if lt.get("top_underlying"):
        out.append("<h3>O que está por baixo (maiores exposições)</h3>")
        rows = [[v(engine, f"lookthrough.top_underlying[{i}].name"), v(engine, f"lookthrough.top_underlying[{i}].value_brl"),
                 v(engine, f"lookthrough.top_underlying[{i}].weight_pct")] for i in range(len(lt["top_underlying"]))]
        out.append(_table([("Ativo subjacente", False), ("Valor", True), ("Peso", True)], rows))
    out.append(charts.lookthrough_chart(engine))
    out.append("<h3>Indexador</h3>")
    out.append(_bucket_table(engine, "indexer", "indexer", "Indexador"))
    out.append(charts.indexer_chart(engine))
    out.append("<h3>Setor</h3>")
    out.append(_bucket_table(engine, "sector", "sector", "Setor"))
    return "\n".join(out)


def _concentration_section(engine: dict) -> str:
    """Engine 1.7: issuer as printed (direct credit), maturity ladder, the FGC check; all from the statement."""
    c = engine.get("concentration") or {}
    out = []
    iss = c.get("issuer") or {}
    out.append("<h3>Emissores de crédito direto</h3>")
    if iss.get("groups"):
        out.append(f"<p class=cit>{v(engine, 'concentration.issuer.label')}. Base: {v(engine, 'concentration.issuer.basis')}. "
                   f"Crédito direto na carteira: {v(engine, 'concentration.issuer.direct_credit_value_brl')} "
                   f"({v(engine, 'concentration.issuer.direct_credit_weight_pct')}).</p>")
        rows = []
        for i, _g in enumerate(iss["groups"]):
            q = f"concentration.issuer.groups[{i}]"
            rows.append([v(engine, f"{q}.issuer"), e(", ".join(_g.get("tipos") or [])), e(", ".join(_g.get("line_ids") or [])),
                         v(engine, f"{q}.value_brl"), v(engine, f"{q}.weight_pct"), v(engine, f"{q}.share_of_direct_credit_pct")])
        out.append(_table([("Emissor (como impresso)", False), ("Tipos", False), ("Linhas", False), ("Valor", True),
                           ("Peso na carteira", True), ("Peso no crédito direto", True)], rows))
        out.append(charts.issuer_chart(engine))
    else:
        out.append("<p>Nenhum crédito direto na carteira.</p>")
    fidx = charts.fund_positions(engine)
    if fidx:
        out.append("<h3>Maiores posições em fundos</h3>")
        out.append(_table([("Linha", False), ("Fundo", False), ("Valor", True), ("Peso", True)],
                          [[v(engine, f"lines[{i}].line_id"),
                            v(engine, f"lines[{i}].fund_name") if engine["lines"][i].get("fund_name") else v(engine, f"lines[{i}].instrument"),
                            v(engine, f"lines[{i}].value_brl"), v(engine, f"lines[{i}].weight_pct")] for i in fidx]))
        out.append(charts.fund_chart(engine))
    lad = c.get("maturity_ladder") or {}
    out.append("<h3>Vencimentos</h3>")
    if lad.get("status") == "complete":
        out.append(f"<p class=cit>{v(engine, 'concentration.maturity_ladder.basis')}.</p>")
        rows = [[v(engine, f"concentration.maturity_ladder.buckets[{i}].bucket"),
                 e(", ".join(b.get("line_ids") or [])) or "—",
                 v(engine, f"concentration.maturity_ladder.buckets[{i}].value_brl"),
                 v(engine, f"concentration.maturity_ladder.buckets[{i}].weight_pct")]
                for i, b in enumerate(lad.get("buckets") or [])]
        rows.append([v(engine, "concentration.maturity_ladder.no_maturity.bucket"), "—",
                     v(engine, "concentration.maturity_ladder.no_maturity.value_brl"),
                     v(engine, "concentration.maturity_ladder.no_maturity.weight_pct")])
        out.append(_table([("Prazo até o vencimento", False), ("Linhas", False), ("Valor", True), ("Peso", True)], rows))
        years = lad.get("by_year") or []
        if years:
            yrows = [[v(engine, f"concentration.maturity_ladder.by_year[{i}].year"), e(", ".join(y.get("line_ids") or [])),
                      v(engine, f"concentration.maturity_ladder.by_year[{i}].value_brl"),
                      v(engine, f"concentration.maturity_ladder.by_year[{i}].weight_pct")] for i, y in enumerate(years)]
            out.append(_table([("Ano do vencimento", False), ("Linhas", False), ("Valor", True), ("Peso", True)], yrows))
            out.append(charts.maturity_chart(engine))
    else:
        out.append("<p>Nenhuma linha com vencimento impresso no extrato.</p>")
    fgc = c.get("fgc") or {}
    out.append("<h3>FGC por emissor</h3>")
    if fgc.get("status") == "complete":
        out.append(f"<p class=cit>{v(engine, 'concentration.fgc.rule')}. {v(engine, 'concentration.fgc.scope_note')}</p>")
        rows = []
        for i, g in enumerate(fgc.get("issuers") or []):
            q = f"concentration.fgc.issuers[{i}]"
            flag = (f'<span class="tag unk">acima de {v(engine, "concentration.fgc.limit_brl")} '
                    f'(excede {v(engine, f"{q}.excess_brl")}); {v(engine, "concentration.fgc.label")}</span>'
                    if g.get("above_limit") else "dentro do limite")
            rows.append([v(engine, f"{q}.issuer"), e(", ".join(g.get("tipos") or [])), e(", ".join(g.get("line_ids") or [])),
                         v(engine, f"{q}.eligible_value_brl"), flag])
        out.append(_table([("Emissor (como impresso)", False), ("Tipos", False), ("Linhas", False), ("Soma coberta", True),
                           ("Limite", False)], rows))
    else:
        out.append("<p>Nenhum CDB, LCI ou LCA na carteira.</p>")
    out.append(_manager_html(engine))
    if not engine.get("liquidity") and (c.get("fund_liquidity") or {}).get("status") not in (None, "complete"):
        out.append(f'<p><span class="tag unk">Liquidez dos fundos: não avaliada</span> {v(engine, "concentration.fund_liquidity.reason")}.</p>')
    return "\n".join(out)


def _manager_html(engine: dict) -> str:
    """Engine 1.9: fund value by manager (the filed gestor_id), with the chart; a 1.8 document says "não avaliada"."""
    m = (engine.get("concentration") or {}).get("manager") or {}
    if not m:
        return ""
    if "groups" not in m:
        if m.get("status") not in (None, "complete"):
            return f'<p><span class="tag unk">Concentração por gestor: não avaliada</span> {v(engine, "concentration.manager.reason")}.</p>'
        return ""
    out = ["<h3>Concentração por gestora</h3>"]
    if m.get("groups"):
        out.append(f"<p class=cit>{_cap(v(engine, 'concentration.manager.label'))}. Valor em fundos com CNPJ: "
                   f"{v(engine, 'concentration.manager.fund_value_brl')} ({v(engine, 'concentration.manager.fund_value_weight_pct')}).</p>")
        rows = []
        for i, g in enumerate(m["groups"]):
            q = f"concentration.manager.groups[{i}]"
            rows.append([v(engine, f"{q}.gestor_name"), v(engine, f"{q}.gestor_id"), e(", ".join(g.get("line_ids") or [])),
                         v(engine, f"{q}.value_brl"), v(engine, f"{q}.weight_pct"), v(engine, f"{q}.share_of_funds_pct")])
        out.append(_table([("Gestora (como arquivada)", False), ("Identificador arquivado", False), ("Linhas", False),
                           ("Valor", True), ("Peso na carteira", True), ("Peso nos fundos", True)], rows))
        out.append(charts.manager_chart(engine))
    if m.get("without_gestor_line_ids"):
        out.append(f'<p><span class="tag unk">sem gestor informado</span> Linhas: {e(", ".join(m["without_gestor_line_ids"]))}; '
                   f'valor {v(engine, "concentration.manager.without_gestor_value_brl")}.</p>')
    if m.get("status") in ("partial", "unknown") and m.get("reason"):
        out.append(f'<p><span class="tag unk">{e(SECTION_STATUS_LABELS.get(m["status"], m["status"]))}</span> '
                   f'{v(engine, "concentration.manager.reason")}.</p>')
    return "\n".join(out)


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _credit_section(engine: dict) -> str:
    """Engine 1.9: CRA, CRI and debêntures held directly, the statement beside the CVM registry and the funds' mark."""
    cr = engine.get("credit") or {}
    rows = []

    def pair(q: str, a: str, b: str, b_label: str = "registro") -> str:
        return (f"<span class=cit>extrato:</span> {v(engine, f'{q}.{a}')}<br>"
                f"<span class=cit>{b_label}:</span> {v(engine, f'{q}.{b}')}")

    for i, x in enumerate(cr.get("lines") or []):
        q = f"credit.lines[{i}]"
        code = v(engine, f"{q}.input_code")
        if not x.get("matched"):
            rows.append([v(engine, f"{q}.line_id"), code, v(engine, f"{q}.issuer_as_printed"),
                         f'<span class="tag unk">{v(engine, f"{q}.status_label")}</span><br><span class=cit>{v(engine, f"{q}.not_found_reason")}</span>',
                         "—", "—", f"<span class=cit>extrato:</span> {v(engine, f'{q}.statement_preco_brl')}"])
            continue
        code += f"<br><span class=cit>registro: {v(engine, f'{q}.code')}</span>"
        serie = " / ".join(t for t in (v(engine, f"{q}.numero_serie") if x.get("numero_serie") is not None else "",
                                        v(engine, f"{q}.classe") if x.get("classe") else "") if t)
        if serie:
            code += f"<br><span class=cit>série: {serie}</span>"
        if x.get("cnpj_securit"):
            code += f"<br><span class=cit>securitizadora: {v(engine, f'{q}.cnpj_securit')}</span>"
        code += "".join(f'<br><span class="tag unk">{v(engine, f"{q}.flags[{j}].label")}</span>' for j in range(len(x.get("flags") or [])))
        rating = v(engine, f'{q}.rating')
        if str(x.get("rating") or "").strip() in RATING_NOT_FILED:  # a filed "0" is no rating, shown as filed
            rating = f"não informado (arquivado: {rating})"
        situ = f"{v(engine, f'{q}.situacao')}<br><span class=cit>rating:</span> {rating}"
        price = (f"<span class=cit>extrato ({v(engine, f'{q}.statement_date')}):</span> {v(engine, f'{q}.statement_preco_brl')}<br>"
                 f"<span class=cit>fundos")
        if x.get("fund_mark_brl") is not None:
            price += (f" (CDA de {v(engine, f'{q}.fund_mark_cda.month')}"
                      f"{', ' + v(engine, f'{q}.n_fundos') + ' fundos' if x.get('n_fundos') is not None else ''}):</span> "
                      f"{v(engine, f'{q}.fund_mark_brl')}")
            if x.get("price_gap_pct") is not None:
                price += (f"<br><span class=cit>diferença {v(engine, f'{q}.price_gap_pct')}; "
                          f"{v(engine, f'{q}.price_gap_label')}</span>")
        else:
            price += ":</span> —"
        rows.append([v(engine, f"{q}.line_id"), code, v(engine, f"{q}.issuer_as_printed"),
                     pair(q, "statement_vencimento", "registry_vencimento"), pair(q, "statement_taxa", "registry_taxa"),
                     situ, price])
    head = (f"<p class=cit>{_cap(v(engine, 'credit.label'))}. Vencimento, taxa e preço como informados no extrato, no registro "
            f"da CVM e nas carteiras dos fundos. {_cap(v(engine, 'credit.price_note'))}. {_cap(v(engine, 'credit.rate_note'))}.</p>")
    return head + _table([("Linha", False), ("Código, série e securitizadora", False), ("Emissor (como impresso)", False),
                          ("Vencimento", False), ("Taxa", False), ("Situação e rating", False),
                          ("Preço (extrato | marcação dos fundos)", False)], rows)


def _liquidity_section(engine: dict) -> str:
    """Engine 1.9: the liquidity ladder, every line in one bucket, with the filed redemption terms of each fund."""
    lq = engine.get("liquidity") or {}
    out = [f"<p class=cit>Base: {v(engine, 'liquidity.basis')}; {v(engine, 'liquidity.days_note')}. {v(engine, 'liquidity.note')}</p>"]
    rows = []
    for i, b in enumerate(lq.get("buckets") or []):
        q = f"liquidity.buckets[{i}]"
        terms = []
        for j, x in enumerate(b.get("lines") or []):
            lq_ = f"{q}.lines[{j}]"
            if x.get("qt_dia_pagto_resgate") is None and x.get("qt_dia_resgate_cotas") is None:
                continue
            t = f"{v(engine, f'{lq_}.line_id')}: D+{v(engine, f'{lq_}.qt_dia_pagto_resgate')}"
            if x.get("tp_dia_pagto_resgate"):
                t += f" {v(engine, f'{lq_}.tp_dia_pagto_resgate').lower()}"
            if x.get("qt_dia_resgate_cotas"):
                t += f", carência {v(engine, f'{lq_}.qt_dia_resgate_cotas')} dias"
            if x.get("terms_source"):
                # "Extrato da CVM", never a bare "extrato": the reader holds the broker's extrato in the other hand
                t += f" ({e(TERMS_SOURCE_LABEL.get(x['terms_source'], x['terms_source']))}"
                t += f" de {v(engine, f'{lq_}.terms_dt_comptc')})" if x.get("terms_dt_comptc") else ")"
            if PREV_WRAPPER.search(x.get("estrategia_corretora") or ""):
                t += f" · {v(engine, f'{lq_}.estrategia_corretora')}"
            terms.append(t)
        rows.append([v(engine, f"{q}.bucket"), e(", ".join(b.get("line_ids") or [])) or "—",
                     "<br>".join(f"<span class=cit>{t}</span>" for t in terms) or "—",
                     v(engine, f"{q}.value_brl"), v(engine, f"{q}.weight_pct")])
    out.append(_table([("Faixa", False), ("Linhas", False), ("Prazo como arquivado", False), ("Valor", True), ("Peso", True)], rows))
    if lq.get("above_d30_total_pct") is not None:
        out.append(f"<p>Acima de D+30 (fundos acima de D+30, com carência, sem prazo informado e crédito direto): "
                   f"<span class=v>{v(engine, 'liquidity.above_d30_total_brl')}</span> "
                   f"(<span class=v>{v(engine, 'liquidity.above_d30_total_pct')}</span> da carteira).</p>")
    if lq.get("status") in ("partial", "unknown") and lq.get("reason"):
        out.append(f'<p><span class="tag unk">{e(SECTION_STATUS_LABELS.get(lq["status"], lq["status"]))}</span> {v(engine, "liquidity.reason")}.</p>')
    out.append(charts.liquidity_chart(engine))
    return "\n".join(out)


SEVERITY_CLASS = {"atencao": "sev-a", "moderado": "sev-m", "baixo": "sev-b"}


def _threshold_text(engine: dict, q: str, th: dict) -> str:
    parts = []
    for level, word in (("atencao", "atenção"), ("moderado", "moderado")):
        for unit in ("pct", "count"):
            key = f"{level}_above_{unit}"
            if th.get(key) is not None:
                parts.append(f"{word} &gt; {v(engine, f'{q}.{key}')}")
    return "<br>".join(parts) or "—"


def _risks_section(engine: dict) -> str:
    """Engine 1.8: "Principais riscos", one row per risk, the semáforo from fixed thresholds; every value a path."""
    rk = engine.get("risks") or {}
    out = [f"<p class=cit>{v(engine, 'risks.note')} Critério: {v(engine, 'risks.severity_rule')}.</p>"]
    rows = []
    for i, r in enumerate(rk.get("rows") or []):
        q = f"risks.rows[{i}]"
        if r.get("status") == "avaliado":
            unit = r.get("unit")
            value = f"<span class=v>{v(engine, f'{q}.value_{unit}')}</span>"
            if r.get("subject"):
                value += f"<br><span class=cit>{v(engine, f'{q}.subject')}</span>"
            if r.get("value_brl_detail") is not None:
                lab = f"{v(engine, f'{q}.value_brl_detail_label')}: " if r.get("value_brl_detail_label") else ""
                value += f"<br><span class=cit>{lab}{v(engine, f'{q}.value_brl_detail')}</span>"
            if r.get("id") == "credito_preco_marcacao" and r.get("statement_preco_brl") is not None:
                value += (f"<br><span class=cit>extrato {v(engine, f'{q}.statement_preco_brl')} ({v(engine, f'{q}.statement_date')}) | "
                          f"fundos {v(engine, f'{q}.preco_marcacao_fundos_brl')} (CDA de {e(format_value({'month': resolve(engine, f'{q}.cda_period')}, 'month'))})</span>")
            if r.get("id") == "credito_vencimento_diverge" and r.get("registry_vencimento"):
                value += (f"<br><span class=cit>extrato {v(engine, f'{q}.statement_vencimento')} | "
                          f"registro {v(engine, f'{q}.registry_vencimento')}</span>")
            if r.get("id") in ("indexador", "liquidez"):
                value += "<br><span class=cit>" + " · ".join(
                    f"{v(engine, f'{q}.parts[{j}].group')} {v(engine, f'{q}.parts[{j}].portfolio_pct')}"
                    for j, p in enumerate(r.get("parts") or [])
                    if (p.get("value_brl") or 0) > 0 or p.get("group") == "sem classificação") + "</span>"
            if (r.get("table_only") or {}).get("n_atencao"):
                value += (f"<br><span class=cit>fundos em atenção (só nesta tabela): "
                          f"{v(engine, f'{q}.table_only.n_atencao')}</span>")
            sev = (f'<span class="sev {SEVERITY_CLASS.get(r.get("severity"), "")}"></span>'
                   f"{v(engine, f'{q}.severity_label')}")
            if r.get("check_label"):
                sev += f'<br><span class="tag unk">{v(engine, f"{q}.check_label")}</span>'
        else:
            value = "—"
            sev = f'<span class="tag unk">{v(engine, f"{q}.status_label")}</span><br><span class=cit>{v(engine, f"{q}.reason")}</span>'
        rows.append([v(engine, f"{q}.risk"), value, sev, v(engine, f"{q}.explanation"),
                     _threshold_text(engine, f"{q}.thresholds", r.get("thresholds") or {})])
    out.append(_table([("Risco", False), ("Valor", False), ("Semáforo", False), ("O que mede", False), ("Limites", False)], rows)
               .replace("<table>", '<table class="riscos">', 1))
    return "\n".join(out)


def _fee_headline_section(engine: dict) -> str:
    """Engine 1.8: "Quanto a carteira paga em taxas": the disclosed total, the ETF site's apart, the coverage, and
    what is not included. The balancete estimate is shown apart and never added."""
    sm = (engine.get("fees") or {}).get("summary") or {}
    b = "fees.summary"
    out = []
    if sm.get("adm_disclosed_fixed_per_year_brl") is not None:
        out.append(f'<div class="destaque"><span class="numero">{v(engine, f"{b}.adm_disclosed_fixed_per_year_brl")}</span> por ano '
                   f'<span class="numero-2">{v(engine, f"{b}.adm_disclosed_fixed_portfolio_pct")} da carteira ao ano</span>'
                   "<br><span class=cit>taxa de administração divulgada, somada nos fundos com taxa fixa</span></div>")
    else:
        out.append('<div class="destaque"><span class="numero-2">Nenhuma taxa de administração fixa divulgada para somar.</span></div>')
    items = []
    if sm.get("adm_disclosed_range_low_per_year_brl") is not None:
        items.append(f"Fundos com classes de taxas diferentes (faixa divulgada), à parte: <span class=v>{v(engine, f'{b}.adm_disclosed_range_low_per_year_brl')}</span> "
                     f"a <span class=v>{v(engine, f'{b}.adm_disclosed_range_high_per_year_brl')}</span> por ano "
                     f"({v(engine, f'{b}.adm_disclosed_range_low_portfolio_pct')} a {v(engine, f'{b}.adm_disclosed_range_high_portfolio_pct')} da carteira).")
    if sm.get("adm_etf_site_per_year_brl") is not None:
        items.append(f"ETFs, à parte: <span class=v>{v(engine, f'{b}.adm_etf_site_per_year_brl')}</span> por ano "
                     f"({v(engine, f'{b}.adm_etf_site_portfolio_pct')} da carteira): {v(engine, f'{b}.etf_site_label')}.")
    if sm.get("fund_value_brl") is not None:
        items.append(f"Cobertura: dos <span class=v>{v(engine, f'{b}.fund_value_brl')}</span> em fundos "
                     f"({v(engine, f'{b}.fund_value_portfolio_pct')} da carteira), têm taxa fixa divulgada "
                     f"<span class=v>{v(engine, f'{b}.coverage_fixed_fund_value_pct')}</span>, faixa divulgada "
                     f"{v(engine, f'{b}.coverage_range_fund_value_pct')}, taxa de ETF do site {v(engine, f'{b}.coverage_etf_site_fund_value_pct')} "
                     f"e nenhuma taxa utilizável <span class=v>{v(engine, f'{b}.coverage_without_fee_fund_value_pct')}</span>.")
    if sm.get("estimate_adm_per_year_brl") is not None:
        items.append(f"Estimativa do balancete ({v(engine, f'{b}.estimate_label')}), à parte e nunca somada: "
                     f"{v(engine, f'{b}.estimate_adm_per_year_brl')} por ano ({v(engine, f'{b}.estimate_adm_portfolio_pct')} da carteira).")
    if items:
        out.append("<ul>" + "".join(f"<li>{x}</li>" for x in items) + "</ul>")
    ni = []
    for i, x in enumerate(sm.get("not_included") or []):
        q = f"{b}.not_included[{i}]"
        tail = f" Linhas: {e(', '.join(x.get('line_ids') or []))}." if x.get("line_ids") else ""
        if x.get("value_brl") is not None:
            tail += f" Valor: {v(engine, f'{q}.value_brl')}."
        ni.append(f"<li>{v(engine, f'{q}.text')}.{tail}</li>")
    if ni:
        out.append("<h3>Não incluído no total</h3><ul>" + "".join(ni) + "</ul>")
    out.append(f"<p class=cit>Base: {v(engine, f'{b}.basis')}. O detalhe por fundo está em Custo em taxas.</p>")
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
    """"O que não foi possível avaliar": deterministic, one short line per gap, from the view's ``gaps`` (engine 1.7).

    Fixed texts only (never an engine reason, an error or a request param); the unidentified lines come grouped
    by reason, with the group's value. Written without the LLM.
    """
    items = []
    for i, g in enumerate(engine.get("gaps") or []):
        q = f"gaps[{i}]"
        tail = ""
        if g.get("line_ids"):
            tail += f" Linhas: {e(', '.join(map(str, g['line_ids'])))}."
        if g.get("value_brl") is not None:
            tail += f" Valor: {v(engine, f'{q}.value_brl')}"
            if g.get("weight_pct") is not None:
                tail += f" ({v(engine, f'{q}.weight_pct')} da carteira)"
            tail += "."
        items.append(f"<li><strong>{v(engine, f'{q}.title')}</strong>: {v(engine, f'{q}.text')}.{tail}</li>")
    if "gaps" not in engine:  # a view built before engine 1.7: the section statuses, as fixed labels only
        for name, sec in sorted((engine.get("sections") or {}).items()):
            if isinstance(sec, dict) and sec.get("status") in ("partial", "unknown"):
                items.append(f"<li><strong>{e(name)}</strong>: {e(SECTION_STATUS_LABELS.get(sec['status'], sec['status']))}.</li>")
    if narrative.status != "complete":
        items.append(f"<li><strong>Texto interpretativo</strong>: {e(NARRATIVE_UNAVAILABLE)}</li>")
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
        *_v19_method(engine),
        *_risk_method(engine),
        *_returns_tax_method(engine),
        "Os gráficos são desenhados a partir dos mesmos campos das tabelas ao lado, que continuam sendo o registro preciso; "
        "um gráfico sem dado não é desenhado, e a seção do que não foi possível avaliar diz por quê.",
        f"Modelo: {model}. Provedor: {e(narrative.provider or '—')}. Custo do texto: US$ {narrative.cost_usd:.4f} "
        f"(teto de US$ {narrative.cost_cap_usd:.2f} por relatório).",
    ]
    # The Revisor's notes (what it removed and why) stay in the Narrative for the logs and the JSON; the client's
    # PDF does not carry them (engine 1.7).
    return "<ul>" + "".join(f"<li>{x}</li>" for x in lines) + "</ul>"


def _v19_method(engine: dict) -> list[str]:
    """Engine 1.9: how direct credit, the managers and the liquidity ladder are read (fixed texts)."""
    out = []
    if engine.get("credit"):
        out.append("Crédito direto: CRA e CRI são procurados pelo código exato no registro da CVM; a série é a de vencimento "
                   "igual ao do extrato, senão a única, senão a de menor número, marcada \"vencimento diverge do registro CVM\" "
                   "(a conferir). Debêntures são procuradas pelo código nas carteiras dos fundos (CDA bloco 4); a marcação é a "
                   "média ponderada dos fundos, em outra data, e a diferença para o preço do extrato é informativa, não um "
                   "veredito de preço. Nada é procurado por semelhança de nome, e o emissor fica como impresso no extrato. "
                   "Situação e rating aparecem como arquivados.")
    if engine.get("liquidity"):
        out.append("Gestora e liquidez: a gestora e os prazos de resgate são os arquivados no Extrato da CVM ou na lâmina. "
                   "A concentração agrupa pelo identificador da gestora, nunca pelo nome. O prazo de pagamento do resgate é "
                   "lido como arquivado (D+N), sem converter dias úteis e corridos; carência acima de zero é lock-up; um "
                   "prazo não informado é \"fundo sem prazo de resgate informado\", nunca zero.")
    return out


def _returns_tax_method(engine: dict) -> list[str]:
    """Engines 1.10 and 1.11: how the returns and the tax are read (the engine's own texts, and the rule files)."""
    out = []
    if engine.get("returns"):
        out.append(f"Retorno por posição: {v(engine, 'returns.definition')} Sem retorno da carteira inteira, sem média e sem "
                   "ranking. \"% do CDI\" (retorno líquido dividido pelo CDI das mesmas datas) só aparece para fundo cujo índice "
                   "de referência arquivado, no Extrato (índice da taxa de performance) ou na lâmina, é CDI ou DI, por uma lista "
                   "fixa de grafias, e só com CDI do período acima de zero; nas demais linhas, a diferença em pontos percentuais.")
    if engine.get("equivalents"):
        out.append(f"Equivalente de mercado: {v(engine, 'equivalents.choice_note')} {v(engine, 'equivalents.class_note')} "
                   f"O patrimônio líquido e a taxa do ETF são do site etfsbrasil.com.br (fonte de terceiros), com a data.")
    tx = engine.get("tax") or {}
    if tx:
        files = "; ".join(
            f"{v(engine, f'tax.rules_files[{i}].instrument')} versão {v(engine, f'tax.rules_files[{i}].version')}"
            + (" (não verificado em parte)" if f.get("not_verified") else "")
            for i, f in enumerate(tx.get("rules_files") or []))
        out.append(f"Imposto: regras versionadas por tipo de instrumento, transcritas de {v(engine, 'tax.rules_note')}"
                   + (f" ({files})" if files else "") + ". O valor em R$ só aparece quando o motor o calculou, rotulado "
                   "estimativa; sem data de aplicação no extrato fica a faixa de alíquotas. Nenhum total de imposto da carteira.")
    return out


def _risk_method(engine: dict) -> list[str]:
    rk = engine.get("risks") or {}
    if not rk:
        return []
    th = []
    for i, r in enumerate(rk.get("rows") or []):
        if r.get("thresholds"):
            th.append(f"{v(engine, f'risks.rows[{i}].risk')}: "
                      + _threshold_text(engine, f"risks.rows[{i}].thresholds", r["thresholds"]).replace("<br>", ", "))
    return [f"Principais riscos: {v(engine, 'risks.severity_rule')}. Limites: {'; '.join(th)}. {v(engine, 'risks.note')}"]


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
        *([section("Principais riscos", _risks_section(engine) + _findings_html(engine, narrative, "riscos"))]
          if engine.get("risks") else []),
        *([section("Quanto a carteira paga em taxas", _fee_headline_section(engine))]
          if (engine.get("fees") or {}).get("summary") else []),
        section("Identificação linha a linha", _ident_section(engine) + _findings_html(engine, narrative, "identificacao")),
        *([section("Crédito direto no registro da CVM", _credit_section(engine))]
          if (engine.get("credit") or {}).get("lines") else []),
        section("Custo em taxas", _fees_section(engine) + _findings_html(engine, narrative, "taxas")),
        section("Exposição", _exposure_section(engine) + _findings_html(engine, narrative, "exposicao")),
        *([section("Concentração e vencimentos", _concentration_section(engine))] if engine.get("concentration") else []),
        *([section("Liquidez", _liquidity_section(engine))] if engine.get("liquidity") else []),
        *([section("Retorno por posição", _returns_section(engine) + _findings_html(engine, narrative, "retornos"))]
          if engine.get("returns") else []),
        *([section("Taxa e imposto por posição", _tax_section(engine) + _findings_html(engine, narrative, "impostos"))]
          if engine.get("tax") else []),
        *([section("Equivalente de mercado", _equivalents_section(engine) + _findings_html(engine, narrative, "equivalentes"))]
          if engine.get("equivalents") else []),
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
