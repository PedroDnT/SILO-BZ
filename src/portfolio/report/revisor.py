"""Revisor: an independent check of the Redator's findings against the engine JSON.

Deterministic first, sentence by sentence:

1. every ``{{placeholder}}`` resolves to an existing path with a non-null scalar;
2. a sentence with a literal digit outside a placeholder is removed;
3. every citation is an ``id`` in the engine's ``provenance``, and a source
   named in the text (CVM, BCB, B3, FNET, ...) is one the provenance carries;
4. an extreme value stays only when the engine JSON carries a second path
   confirming it (``EXTREME_RULES``), else the sentence is removed with a note.

A finding whose title fails, whose citations are invalid or empty, or that has
no sentence left is removed whole. Then, optionally, one LLM pass may delete or
reword findings; it may not add a placeholder, and every reword is re-checked
by the same deterministic rules (a failed reword is discarded, the original
kept).
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any

from src.portfolio.report.llm import LLMError, Provider
from src.portfolio.report.redator import Finding
from src.portfolio.report.values import (
    MISSING,
    PLACEHOLDER_RE,
    is_number,
    iter_leaves,
    last_key,
    parent_path,
    resolve,
)

# Extreme values (owner's brief). Units follow values.py: *_pct in percent.
FEE_PCT_YEAR_MAX = 5.0          # a fee above 5% a.a.
EXPOSURE_PCT_MAX = 50.0         # an exposure above 50% of the portfolio
DELINQUENCY_CHANGE_BRL_MAX = 100_000_000.0  # a delinquency change above R$100M

# Two values confirm each other when they agree to this relative tolerance.
CONFIRM_REL_TOL = 1e-6
CONFIRM_ABS_TOL = 0.005

SOURCE_NAMES = {
    "CVM": ("CVM",),
    "BCB": ("BCB", "BACEN", "Banco Central"),
    "B3": ("B3",),
    "FNET": ("FNET", "Fundos.NET"),
    "ANBIMA": ("ANBIMA",),
    "IBGE": ("IBGE",),
}

# Movimento incomum (owner, 2026-10-03): the text may cite the strong level, the funds with no verdict and the
# section's own constants. The attention level lives in the table (movement.table, movement.by_line) and nowhere else.
MOVEMENT_TEXT_PATHS = (
    "movement.strong[",
    "movement.not_evaluated[",
    "movement.counts.",
    "movement.month",
    "movement.min_peers",
    "movement.thresholds.",
    "movement.note",
    "movement.levels_note",
    "movement.definition",
    "movement.class_note",
    "movement.status",
    "movement.reason",
    "movement.n_not_fund_lines",
)
_ATENCAO_WORD_RE = re.compile(r"aten[cç][aã]o", re.IGNORECASE)
# A sentence about the movement that names the attention level without a movement placeholder (a fund named through
# lines[i].fund_name, say) is the same claim: the attention level is a table row, not a finding.
_MOVEMENT_WORD_RE = re.compile(r"movimento", re.IGNORECASE)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_DIGIT_RE = re.compile(r"\d")


@dataclass
class Removal:
    finding_id: str
    section: str
    title: str
    text: str
    reason: str
    whole_finding: bool


@dataclass
class RevisorResult:
    kept: list[Finding]
    removed: list[Removal] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def placeholders(text: str) -> list[str]:
    return [m.strip() for m in PLACEHOLDER_RE.findall(text)]


def split_sentences(text: str) -> list[str]:
    return [s for s in (p.strip() for p in _SENTENCE_SPLIT_RE.split(text.strip())) if s]


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=CONFIRM_REL_TOL, abs_tol=CONFIRM_ABS_TOL)


def _extreme(engine: dict, path: str, value: Any) -> tuple[str, float] | None:
    """``(kind, magnitude)`` when the value at ``path`` is extreme, else None."""
    if not is_number(value):
        return None
    key = last_key(path).lower()
    low_path = path.lower()
    if low_path.startswith("movement."):
        # A class-relative return, mean or sd is a sample statistic, not an exposure: it carries its own
        # n_peers, class and month, and the section's level rule decides where it may appear.
        return None
    parent = resolve(engine, parent_path(path))
    leaf = str(parent.get("leaf", "")).lower() if isinstance(parent, dict) else ""
    if "delinquency" in low_path or "inad" in leaf:
        if "change" in key:
            mag = abs(float(value))
        elif key in ("old_num", "new_num", "delinquency_old_brl", "delinquency_new_brl") and isinstance(parent, dict):
            pair = ("old_num", "new_num") if key in ("old_num", "new_num") else ("delinquency_old_brl", "delinquency_new_brl")
            old, new = parent.get(pair[0]), parent.get(pair[1])
            mag = abs(float(new) - float(old)) if is_number(old) and is_number(new) else abs(float(value))
        else:
            return None
        return ("delinquency_change", mag) if mag > DELINQUENCY_CHANGE_BRL_MAX else None
    if "_pct" in key:
        if low_path.startswith("fees") or "fee" in key or "taxa" in key:
            return ("fee", float(value)) if float(value) > FEE_PCT_YEAR_MAX else None
        return ("exposure", float(value)) if float(value) > EXPOSURE_PCT_MAX else None
    return None


def _confirmed(engine: dict, path: str, kind: str, magnitude: float, value: float) -> bool:
    """Is the extreme value carried by a second path outside its own object?"""
    parent = parent_path(path)
    pobj = resolve(engine, parent)
    if isinstance(pobj, dict):
        hint = pobj.get("confirmed_by") or pobj.get("second_path")
        for other in [hint] if isinstance(hint, str) else (hint or []):
            ov = resolve(engine, str(other))
            if is_number(ov) and (_close(float(ov), value) or _close(float(ov), magnitude)):
                return True
    targets = {value, magnitude}
    for other_path, ov in iter_leaves(engine):
        if not is_number(ov) or other_path == path:
            continue
        try:
            if parent_path(other_path) == parent:
                continue
        except KeyError:
            continue
        if any(_close(float(ov), t) for t in targets):
            return True
    return False


def _provenance(engine: dict) -> tuple[set[str], set[str]]:
    ids, sources = set(), set()
    for p in engine.get("provenance") or []:
        if isinstance(p, dict):
            if p.get("id") is not None:
                ids.add(str(p["id"]))
            if p.get("source"):
                sources.add(str(p["source"]).upper())
    sources |= {str(k).upper() for k in (engine.get("data_dates") or {})}
    return ids, sources


def check_sentence(engine: dict, sentence: str, sources: set[str]) -> str | None:
    """The reason to remove ``sentence``, or None when it passes."""
    bare = PLACEHOLDER_RE.sub("", sentence)
    if "{{" in bare or "}}" in bare:
        return "marcador malformado"
    if _DIGIT_RE.search(bare):
        return "algarismo fora de marcador"
    for name, aliases in SOURCE_NAMES.items():
        if name not in sources and any(re.search(rf"\b{re.escape(a)}\b", bare) for a in aliases):
            return f"fonte citada fora da proveniência: {name}"
    movement_phs = [ph for ph in placeholders(sentence) if ph.lower().startswith("movement.")]
    for ph in movement_phs:
        if not ph.lower().startswith(MOVEMENT_TEXT_PATHS):
            return f"movimento incomum: o nível atenção só aparece em tabela, não no texto: {{{{{ph}}}}}"
    if (movement_phs or _MOVEMENT_WORD_RE.search(bare)) and _ATENCAO_WORD_RE.search(bare):
        return "movimento incomum: o nível atenção só aparece em tabela, não no texto"
    for ph in placeholders(sentence):
        value = resolve(engine, ph)
        if value is MISSING:
            return f"marcador sem caminho no JSON: {{{{{ph}}}}}"
        if value is None:
            return f"marcador com valor nulo: {{{{{ph}}}}}"
        if isinstance(value, (dict, list)):
            return f"marcador não escalar: {{{{{ph}}}}}"
        ext = _extreme(engine, ph, value)
        if ext and not _confirmed(engine, ph, ext[0], ext[1], float(value)):
            return f"valor extremo ({ext[0]}) sem segundo caminho que o confirme: {{{{{ph}}}}}"
    return None


def check_finding(engine: dict, f: Finding) -> tuple[Finding | None, list[Removal]]:
    ids, sources = _provenance(engine)
    removals: list[Removal] = []

    def drop(reason: str) -> tuple[None, list[Removal]]:
        return None, removals + [Removal(f.id, f.section, f.title, f.text, reason, True)]

    if not f.citations:
        return drop("sem citação de proveniência")
    bad = [c for c in f.citations if c not in ids]
    if bad:
        return drop("citação inexistente na proveniência: " + ", ".join(bad))
    reason = check_sentence(engine, f.title, sources) if f.title else "sem título"
    if reason:
        return drop(f"título: {reason}")
    kept_sentences = []
    for s in split_sentences(f.text):
        reason = check_sentence(engine, s, sources)
        if reason:
            removals.append(Removal(f.id, f.section, f.title, s, reason, False))
        else:
            kept_sentences.append(s)
    if not kept_sentences:
        return None, removals + [Removal(f.id, f.section, f.title, f.text, "nenhuma frase restou", True)]
    return Finding(f.id, f.section, f.title, " ".join(kept_sentences), list(f.citations)), removals


def check(engine: dict, findings: list[Finding]) -> RevisorResult:
    result = RevisorResult(kept=[])
    for f in findings:
        kept, removals = check_finding(engine, f)
        result.removed.extend(removals)
        if kept is not None:
            result.kept.append(kept)
    return result


VERDICT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "action": {"type": "string", "enum": ["keep", "delete", "reword"]},
                    "text": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "action", "text", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """Você é o Revisor do SILO. Recebe achados em português já verificados mecanicamente contra o JSON do motor e revisa tom e coerência.

Você só pode manter (keep), apagar (delete) ou reescrever (reword) um achado. Nunca acrescente fatos nem números. Os números estão como marcadores {{caminho}}; ao reescrever, use somente marcadores que já estavam no texto original e nunca escreva algarismos. Apague um achado que recomende comprar, vender ou manter, que preveja retorno, que afirme algo sobre grupo econômico, que julgue a materialidade de uma reapresentação, ou que contradiga outro achado ou o JSON. Reescreva para tirar tom alarmista ou ambiguidade. Em reword, "text" é o novo texto; em keep e delete, "text" é vazio. "reason" explica a decisão em uma frase."""


def llm_review(engine: dict, result: RevisorResult, provider: Provider) -> RevisorResult:
    """Optional tone/consistency pass. Never adds a number; failures keep the deterministic result."""
    if not result.kept:
        return result
    payload = {
        "achados": [{"id": f.id, "section": f.section, "title": f.title, "text": f.text} for f in result.kept],
        "json_do_motor": engine,
    }
    try:
        if hasattr(provider, "role"):
            provider.role = "revisor"
        raw = provider.complete(SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False, sort_keys=True), VERDICT_SCHEMA)
    except LLMError as exc:
        result.notes.append(f"revisão por LLM não executada ({type(exc).__name__}: {exc}); valem as regras determinísticas")
        return result
    verdicts = {}
    for v in (raw.get("verdicts") if isinstance(raw, dict) else None) or []:
        if isinstance(v, dict) and v.get("id"):
            verdicts[str(v["id"])] = v
    out = RevisorResult(kept=[], removed=list(result.removed), notes=list(result.notes))
    for f in result.kept:
        v = verdicts.get(f.id)
        action = (v or {}).get("action", "keep")
        if action == "delete":
            out.removed.append(Removal(f.id, f.section, f.title, f.text, f"Revisor (LLM): {v.get('reason') or 'apagado'}", True))
            continue
        if action == "reword":
            new_text = str(v.get("text") or "")
            added = set(placeholders(new_text)) - set(placeholders(f.text))
            candidate = Finding(f.id, f.section, f.title, new_text, list(f.citations))
            rechecked, removals = check_finding(engine, candidate)
            if added:
                out.notes.append(f"{f.id}: reescrita descartada (acrescentou marcadores: {', '.join(sorted(added))})")
            elif rechecked is None or removals:
                out.notes.append(f"{f.id}: reescrita descartada (falhou na verificação determinística)")
            else:
                out.kept.append(rechecked)
                continue
        out.kept.append(f)
    return out
