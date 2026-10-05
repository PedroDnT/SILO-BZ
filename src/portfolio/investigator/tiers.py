"""The three acceptance tiers of a fact (owner's resolution of #605, Q31 revised).

* **A, "verificado na fonte"**: the quote is in the document text after normalization (``text.normalize``),
  the value is in the quote, and every number of the value is a number of the quote.
* **B, "conferido por modelo; a conferir"**: the quote is not found verbatim (a table, an OCR'd page, a
  paraphrase), but a passage of the document is located that resembles it, every number of the value and
  of the quote is a number of that passage, and a judge model DIFFERENT from the extractor confirms that
  the passage supports the fact.
* **C, "descartado"**: everything else. Counted, never shown as a fact.

The number rule is enforced here, in code, in every tier: no model's number reaches the output unless
the document's own passage carries it. The judge only answers yes or no; it never supplies a value.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from src.portfolio.investigator.text import best_passage, normalize, numbers_within, quote_found

TIER_A, TIER_B, TIER_C = "A", "B", "C"
TIER_LABEL = {TIER_A: "verificado na fonte", TIER_B: "conferido por modelo; a conferir", TIER_C: "descartado"}

# Why a fact was discarded (tier C), fixed codes; the report prints only their text.
DISCARD_TEXT = {
    "sem_valor_ou_citacao": "fato sem valor ou sem citação",
    "valor_fora_da_citacao": "valor não está na citação e não há juiz para conferir",
    "numero_fora_do_trecho": "um número do fato não aparece no trecho do documento",
    "trecho_nao_localizado": "citação não localizada no documento",
    "juiz_indisponivel": "citação não exata e sem modelo juiz diferente do extrator",
    "juiz_rejeitou": "o modelo juiz não confirmou que o trecho sustenta o fato",
    "juiz_falhou": "o modelo juiz não respondeu",
    "campo_desconhecido": "campo fora da lista do investigador",
    "documento_sem_identificador": "a página da web não cita o código, o ISIN, o CNPJ nem o nome do ativo",
}

# (field, value, passage) -> supported?  Raises on a failed call (counted as juiz_falhou).
Judge = Callable[[str, str, str], bool]


@dataclass(frozen=True)
class Verdict:
    tier: str
    reason_code: str | None = None
    passage: str | None = None
    passage_ratio: float | None = None

    @property
    def label(self) -> str:
        return TIER_LABEL[self.tier]


def assess(field: str, value: str | None, quote: str | None, doc_text: str, judge: Judge | None,
           normalized_text: str | None = None) -> Verdict:
    """The tier of one extracted fact against the full text of the document it cites."""
    if not (value or "").strip() or not (quote or "").strip():
        return Verdict(TIER_C, "sem_valor_ou_citacao")
    nt = normalized_text if normalized_text is not None else normalize(doc_text)
    nv = normalize(value)
    if quote_found(quote, doc_text, nt):
        nq = normalize(quote)
        if not numbers_within(value, quote):
            return Verdict(TIER_C, "numero_fora_do_trecho")
        # on word boundaries: a value "AA" is not in "AAA(bra)", "Banco X" is not in "Banco XP"
        if re.search(rf"(?<![0-9a-z]){re.escape(nv)}(?![0-9a-z])", nq):
            return Verdict(TIER_A, None, nq, 1.0)
        # the quote is the document's, but the value restates it: only a judge can say it is the same fact
        return _judged(field, value, nq, 1.0, judge, missing_code="valor_fora_da_citacao")
    passage, ratio = best_passage(quote, doc_text, nt)
    if passage is None:
        return Verdict(TIER_C, "trecho_nao_localizado", None, round(ratio, 4))
    if not numbers_within(value, passage) or not numbers_within(quote, passage):
        return Verdict(TIER_C, "numero_fora_do_trecho", passage, round(ratio, 4))
    return _judged(field, value, passage, round(ratio, 4), judge, missing_code="juiz_indisponivel")


def _judged(field: str, value: str, passage: str, ratio: float, judge: Judge | None, missing_code: str) -> Verdict:
    if judge is None:
        return Verdict(TIER_C, missing_code, passage, ratio)
    try:
        ok = bool(judge(field, value, passage))
    except Exception as exc:  # noqa: BLE001 - a judge that fails confirms nothing; the fact is discarded and counted
        if getattr(exc, "stop", False):  # the cost share is spent: the investigator stops, not this fact alone
            raise
        return Verdict(TIER_C, "juiz_falhou", passage, ratio)
    return Verdict(TIER_B, None, passage, ratio) if ok else Verdict(TIER_C, "juiz_rejeitou", passage, ratio)
