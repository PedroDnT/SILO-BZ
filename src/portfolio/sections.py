"""The sections of a portfolio diagnosis, declared once, and what the report says when one is not complete.

CONTEXT.md's "Unknown section": a part of the diagnosis that could not be computed is reported, never omitted or
estimated. This module is where each section is declared (its engine key, its key in the report's view, its title in
the "O que não foi possível avaliar" list) and where that rule is applied:

- the engine records a section's status with ``status_of`` and ``attach`` (never by writing ``section_status`` itself);
- the report's view reads the statuses with ``sections_view`` and turns them, with the line-level codes of the
  blocks, into the gap lines with ``report_gaps``.

The texts are fixed: a code becomes ``REASON_TEXT``'s text, and the engine's free ``reason`` (which can name a tool or
quote an error) never reaches the report (engine 1.7). ``REPORT_SLOTS`` are the Redator's finding slots.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from src.portfolio.common import REASON_TEXT

# engine 1.7: a code this table does not know reads as the generic text
GENERIC_GAP = "não foi possível avaliar esta parte nesta versão"
SCREEN_FAILED = "a tela não rodou: a consulta ao SILO falhou ou foi recusada"
TESOURO_NO_PRICE = "o SILO não tem série de preços do Tesouro Direto: o valor da linha é o do extrato"
FUND_ASSET_TYPES = ("fundo", "fidc", "fii", "fip", "etf", "cota_listada")


def reason_text(code: str | None) -> str:
    return REASON_TEXT.get(code or "", GENERIC_GAP)


def codes_text(codes: list[str] | None) -> str:
    texts = list(dict.fromkeys(reason_text(c) for c in codes or []))
    return "; ".join(texts) if texts else GENERIC_GAP


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


@dataclass(frozen=True)
class SectionSpec:
    """One diagnosis section. The declaration order is the engine's order (its keys and ``section_status``)."""

    key: str                      # the engine document's key and its ``section_status`` key
    view_key: str | None = None   # the key in the report view's ``sections`` (None: not in the view)
    title: str | None = None      # the title of its lines in "O que não foi possível avaliar"
    in_every_view: bool = False   # an engine 1.0 section: the view requires it; a later one is listed when present
    gap_from_status: bool = False  # a partial or unknown status gives one gap line per reason code
    covered_codes: tuple[str, ...] = ()  # codes another gap line already says, with its lines
    line_gap_codes: Callable[[dict], list[str]] | None = None  # the codes of one of its lines, grouped into gap lines
    dated: bool = False           # the report reads the data date of its tool calls from it


SECTIONS: tuple[SectionSpec, ...] = (
    SectionSpec("identification", "identification", "Identificação", in_every_view=True,
                covered_codes=("linhas_nao_identificadas",), dated=True),
    SectionSpec("fees", "fees", "Taxas", in_every_view=True, gap_from_status=True,
                covered_codes=("sem_taxa_divulgada", "taxa_a_conferir"), dated=True),
    SectionSpec("look_through", "lookthrough", "Look-through (carteira dos fundos)", in_every_view=True,
                gap_from_status=True, dated=True),
    SectionSpec("indexer", "indexer", "Indexador", in_every_view=True, dated=True),
    SectionSpec("sector", "sector", "Setor", in_every_view=True, dated=True),
    SectionSpec("restatements", "restatements", "Reapresentações", in_every_view=True, gap_from_status=True, dated=True),
    SectionSpec("risk_signals", "risk_screens", "Telas de risco", in_every_view=True, gap_from_status=True, dated=True),
    # engine 1.5; an engine document without the block reads as unknown in the view (see sections_view)
    SectionSpec("movement", "abnormal_movement", "Movimento incomum", gap_from_status=True,
                covered_codes=("fundos_nao_avaliados",), dated=True),
    SectionSpec("concentration", "concentration", "Concentração", gap_from_status=True),
    SectionSpec("allocation", "allocation", "Alocação por classe"),
    SectionSpec("liquidity", "liquidity", "Liquidez", gap_from_status=True),
    # engine 1.8 onward: blocks that read the sections above, built last and attached after them
    SectionSpec("risks", "risks", "Principais riscos", covered_codes=("riscos_nao_avaliados",)),
    SectionSpec("returns", "returns", "Retorno por posição", gap_from_status=True,
                covered_codes=("linhas_sem_retorno",), line_gap_codes=_return_gap_codes, dated=True),
    SectionSpec("tax", "tax", "Taxa e imposto por posição", gap_from_status=True,
                covered_codes=("imposto_linhas_sem_regra",), line_gap_codes=_tax_gap_codes, dated=True),
    # engine 1.13: the equivalents block's line codes are grouped with their lines
    SectionSpec("equivalents", "equivalents", "Equivalente de mercado", gap_from_status=True,
                covered_codes=("equivalente_fora_escopo", "equivalente_sem_classe", "equivalente_sem_par",
                               "equivalente_sem_etf", "equivalente_sem_pl", "equivalente_sem_linha",
                               "equivalente_sem_retorno", "distribuicao_classe_nao_avaliada"),
                line_gap_codes=_equivalent_gap_codes, dated=True),
    SectionSpec("investigation"),
)
BY_KEY = {s.key: s for s in SECTIONS}
# a section-level code one of these covers is not repeated as a section line: it is already a line, with its lines
COVERED_CODES = frozenset(c for s in SECTIONS for c in s.covered_codes)

# What this version never assesses: always unknown in the view, each with its gap title (never an engine section)
NOT_ASSESSED_TITLES = {
    "material_restatement": "Materialidade das reapresentações",
    "economic_group": "Grupo econômico",
    "benchmarks": "Comparação com carteiras de referência",
    "ntnb_price": "Preço do Tesouro Direto",
}
BENCHMARKS_OUT_OF_SCOPE = ("fora do escopo desta versão (variância mínima e contribuição igual de risco ainda não "
                           "calculadas)")

# The Redator's finding slots, in its order, with their titles (the slot is the ``section`` of a finding)
REPORT_SLOTS = (
    ("resumo", "Resumo"),
    ("achados", "Achados que ninguém pegaria à mão"),
    ("riscos", "Principais riscos"),
    ("identificacao", "Identificação linha a linha"),
    ("taxas", "Custo em taxas"),
    ("exposicao", "Exposição"),
    ("reapresentacoes", "Reapresentações"),
    ("sinais_de_risco", "Sinais de risco"),
    ("retornos", "Retorno por posição"),
    ("impostos", "Taxa e imposto por posição"),
    ("equivalentes", "Equivalente de mercado"),
)


# --- the engine side ------------------------------------------------------------------------------------------------


def status_entry(block: dict[str, Any]) -> dict[str, Any]:
    """A section block's ``section_status`` entry: its status, free reason and reason codes."""
    return {"status": block["status"], "reason": block["reason"], "reason_codes": list(block.get("reason_codes") or [])}


def status_of(doc: dict[str, Any]) -> dict[str, Any]:
    """``section_status`` for the sections already in ``doc``, in the declared order."""
    return {s.key: status_entry(doc[s.key]) for s in SECTIONS if s.key in doc}


def attach(doc: dict[str, Any], key: str, block: dict[str, Any]) -> dict[str, Any]:
    """A copy of ``doc`` with ``block`` placed right after the section declared before it, and its status recorded.

    For the blocks the engine builds last because they read the others (risks, returns, tax, equivalents and the
    investigation): the document keeps the declared order whatever order the blocks were computed in.
    """
    at = [s.key for s in SECTIONS].index(key)
    after = next(s.key for s in reversed(SECTIONS[:at]) if s.key in doc)
    out: dict[str, Any] = {}
    for k, v in doc.items():
        out[k] = v
        if k == after:
            out[key] = block
    out["section_status"][key] = status_entry(block)
    return out


# --- the report side ------------------------------------------------------------------------------------------------


def section_entry(st: dict) -> dict:
    """A section's status with the fixed text of its reason codes (engine 1.7); never the engine's free text."""
    out = {"status": st["status"], "reason_codes": list(st.get("reason_codes") or [])}
    if st["status"] in ("partial", "unknown"):
        out["reason"] = codes_text(out["reason_codes"])
    return out


def sections_view(eng: dict, lines: list[dict]) -> dict:
    """The view's ``sections``: every declared section the engine wrote, then what this version never assesses."""
    ss = eng["section_status"]
    out: dict[str, Any] = {}
    for s in SECTIONS:
        if s.view_key is None or s.key == "movement":
            continue
        if s.in_every_view or s.key in ss:
            out[s.view_key] = section_entry(ss[s.key])
    if isinstance(eng.get("movement"), dict):
        out["abnormal_movement"] = section_entry(ss["movement"])
    else:  # an engine before 1.5: the risk screens say why the movement was not assessed
        out["abnormal_movement"] = {"status": "unknown", "reason": eng["risk_signals"].get("abnormal_movement")}
    out["material_restatement"] = {"status": "unknown", "reason": eng["restatements"].get("assessment")}
    out["economic_group"] = {"status": "unknown", "reason": eng["look_through"]["shared_exposure"].get("note")}
    out["benchmarks"] = {"status": "unknown", "reason": BENCHMARKS_OUT_OF_SCOPE}
    tes = [ln["line_id"] for ln in lines if ln["asset_type"] == "titulo_publico"]
    if tes:
        out["ntnb_price"] = {"status": "unknown", "reason": TESOURO_NO_PRICE, "affects": tes}
    unk = [ln["line_id"] for ln in lines if ln["identification"]["status"] == "unknown"]
    if unk and out["identification"]["status"] == "complete":
        out["identification"]["status"] = "partial"
        out["identification"]["reason"] = reason_text("linhas_nao_identificadas")
    return out


def dated_keys() -> list[str]:
    """The engine keys whose tool calls carry the data date the report's sources list shows, in the declared order."""
    return [s.key for s in SECTIONS if s.dated]


def report_gaps(eng: dict, view: dict) -> list[dict]:
    """"O que não foi possível avaliar" (engine 1.7): one short line per gap, written without the LLM.

    Fixed texts only; the unidentified lines are grouped by reason, with the group's value as the engine computed
    it. Then why a chart is not drawn and every risk not evaluated (engine 1.8).
    """
    return _status_gaps(eng, view) + _chart_and_risk_gaps(eng, view)


def _gap(title: str, text: str, line_ids: list[str] | None = None, value_brl: Any = None, weight_pct: Any = None) -> dict:
    return {"title": title, "text": text.rstrip(". "), "line_ids": line_ids or [], "value_brl": value_brl,
            "weight_pct": weight_pct}


def _status_gaps(eng: dict, view: dict) -> list[dict]:
    sections, fees, risk, movement = view["sections"], view["fees"], view["risk_screens"], view.get("movement")
    gaps: list[dict] = []

    def add(*args: Any) -> None:
        gaps.append(_gap(*args))

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
        add(BY_KEY["risk_signals"].title, SCREEN_FAILED + ": " + ", ".join(failed_screens))
    if any(str(sc.get("screen", "")).startswith("screen_dormant") for sc in (eng.get("risk_signals") or {}).get("screens") or []):
        # a permanent coverage limit of the dormant-funds screen, a fixed engine text (never an error)
        note = (eng.get("risk_signals") or {}).get("dormant_coverage_note")
        if note:
            add("Fundos dormentes", note)
    if movement and (movement.get("counts") or {}).get("nao_avaliado"):
        add(BY_KEY["movement"].title, reason_text("fundos_nao_avaliados"),
            [x["line_id"] for x in movement.get("not_evaluated") or []])
    # engines 1.10, 1.11 and 1.13: the lines without a return, a tax rule or an equivalent, grouped by code (no value:
    # the view sums nothing the engine did not)
    for s in SECTIONS:
        if s.line_gap_codes is None:
            continue
        block = eng.get(s.key)
        groups: dict[str, list[str]] = {}
        for ln in (block.get("lines") or []) if isinstance(block, dict) else []:
            for code in s.line_gap_codes(ln):
                if f"L{ln['line_no']}" not in groups.setdefault(code, []):
                    groups[code].append(f"L{ln['line_no']}")
        for code, ids in groups.items():
            add(s.title, reason_text(code), ids)
    for s in SECTIONS:
        if not s.gap_from_status:
            continue
        sec = sections.get(s.view_key) or {}
        if s.key == "risk_signals" and failed_screens:
            continue  # the screens that did not run are a line above
        if sec.get("status") in ("partial", "unknown"):
            for code in sec.get("reason_codes") or [None]:
                if code in COVERED_CODES:
                    continue  # already a line above, with its lines
                add(s.title, reason_text(code))
    for key, title in NOT_ASSESSED_TITLES.items():
        sec = sections.get(key)
        if sec:
            add(title, sec.get("reason") or GENERIC_GAP, sec.get("affects"))
    return gaps


def _chart_and_risk_gaps(eng: dict, view: dict) -> list[dict]:
    """Engine 1.8: why a chart is not drawn, and every risk not evaluated, as fixed texts (never free text)."""
    out: list[dict] = []

    def add(title: str, text: str, line_ids: list[str] | None = None) -> None:
        out.append(_gap(title, text, line_ids))

    already = set(((view.get("sections") or {}).get("concentration") or {}).get("reason_codes") or [])
    for row in (view.get("risks") or {}).get("rows") or []:
        if row.get("status") == "nao_avaliado" and row.get("reason_code") not in already:
            add(f"{BY_KEY['risks'].title}: {row.get('risk')}", row.get("reason") or GENERIC_GAP)
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
    # engine 1.9: the manager chart
    m = c.get("manager") or {}
    if fund_lines and "groups" in m and not m.get("groups"):
        add("Gráfico por gestora", reason_text("sem_gestor"), fund_lines)
    return out
