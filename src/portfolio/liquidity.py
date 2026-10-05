"""Block 19 (engine 1.9): the liquidity ladder, "Liquidez".

Every line of the statement in one bucket, valued at the statement's value (``source = "statement"``). A fund's bucket
is its redemption terms as filed (``portfolio_fund_terms``: the CVM Extrato or the lâmina):

* ``qt_dia_resgate_cotas`` above 0 is a lock-up, whatever the payment days say;
* else ``qt_dia_pagto_resgate`` alone is the D+N, read as filed: business days ("dias úteis") and calendar days
  ("dias corridos") are never converted, each line carries ``tp_dia_pagto_resgate`` as filed;
* a NULL from a call that answered is "not filed" (a closed-end FIDC, FII or FIP, or a term not filed), its own bucket;
* a fund the call did not answer, and a fund line that is not identified, are ``sem classificação``: no term is
  assumed for them, and the section says why.

Direct credit (CRA, CRI, debênture, CDB, CDCA, LCI, LCA) has no redemption before maturity; Tesouro, shares and ETFs,
and the current account are their own buckets. No price, haircut or market depth is assessed.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from src.portfolio.common import STATUS_COMPLETE, STATUS_NOT_APPLICABLE, STATUS_UNKNOWN, Section, brl, dec, pct
from src.portfolio.concentration import is_direct_credit
from src.portfolio.identify import LineId
from src.portfolio.terms import FundTerms

TITLE = "Liquidez"
D5, D30 = 5, 30
BUCKETS = (
    ("d0_d5", "D+0 a D+5"),
    ("d6_d30", "D+6 a D+30"),
    ("acima_d30", "acima de D+30"),
    ("lockup", "lock-up"),
    ("fundo_sem_prazo", "fundo sem prazo de resgate informado"),
    ("credito_direto", "crédito direto sem liquidez antes do vencimento"),
    ("titulos_publicos", "títulos públicos (Tesouro)"),
    ("bolsa", "ETF/ações (negociados em bolsa)"),
    ("caixa", "caixa"),
    ("sem_classificacao", "sem classificação"),
)
# What "Liquidez acima de D+30" sums (risks.py): the funds above D+30, the lock-ups, the funds with no term filed and
# the direct credit.
ABOVE_D30_PARTS = ("acima_d30", "lockup", "fundo_sem_prazo", "credito_direto")
BASIS = (
    "prazo de pagamento do resgate (qt_dia_pagto_resgate) como arquivado no Extrato da CVM ou na lâmina, contado do "
    "pedido; carência (qt_dia_resgate_cotas) maior que zero é lock-up; valores do extrato"
)
DAYS_NOTE = (
    "prazos como arquivados: dias úteis e dias corridos não são convertidos; um D+N em dias corridos fica na faixa do "
    "seu N"
)
NOTE = "Prazo de resgate como arquivado; não avalia preço de venda, deságio nem profundidade de mercado."


def _bucket_of(li: LineId, terms: FundTerms | None) -> tuple[str, str | None]:
    """(bucket id, reason code for a line that is not placed by its own terms)."""
    p = li.position
    if p.tipo == "caixa":
        return "caixa", None
    if p.tipo == "tesouro":
        return "titulos_publicos", None
    if is_direct_credit(li):
        return "credito_direto", None
    if p.tipo in ("ação", "ETF") or li.kind == "ticker":
        return "bolsa", None
    if li.kind == "fund" and li.cnpj:
        if terms is None or li.line_no in terms.failed or li.line_no not in terms.rows:
            code = (terms.failed.get(li.line_no) if terms else None) or "consulta_falhou"
            return "sem_classificacao", code
        t = terms.rows[li.line_no]
        lock = dec(t.get("qt_dia_resgate_cotas"))
        if lock is not None and lock > 0:
            return "lockup", None
        n = dec(t.get("qt_dia_pagto_resgate"))
        if n is None:
            return "fundo_sem_prazo", "prazo_nao_informado"
        return ("d0_d5" if n <= D5 else "d6_d30" if n <= D30 else "acima_d30"), None
    return "sem_classificacao", "liquidez_sem_identificacao"


def compute_liquidity(lines: list[LineId], terms: FundTerms | None) -> dict[str, Any]:
    sec = Section()
    total = sum((li.position.valor for li in lines), Decimal("0"))
    acc: dict[str, list[tuple[LineId, str | None]]] = {b: [] for b, _ in BUCKETS}
    for li in lines:
        b, code = _bucket_of(li, terms)
        acc[b].append((li, code))

    def line_row(li: LineId, code: str | None) -> dict[str, Any]:
        t = (terms.rows.get(li.line_no) if terms else None) or {}
        return {
            "line_no": li.line_no,
            "tipo": li.position.tipo,
            "value_brl": brl(li.position.valor),
            "portfolio_pct": pct(li.position.valor, total) if total else None,
            "qt_dia_pagto_resgate": t.get("qt_dia_pagto_resgate"),
            "tp_dia_pagto_resgate": t.get("tp_dia_pagto_resgate"),
            "qt_dia_conversao_cota": t.get("qt_dia_conversao_cota"),
            "qt_dia_resgate_cotas": t.get("qt_dia_resgate_cotas"),
            "terms_source": t.get("terms_source"),
            "terms_dt_comptc": t.get("terms_dt_comptc"),
            "estrategia_corretora": li.position.estrategia_corretora,
            "vencimento": li.position.vencimento.isoformat() if li.position.vencimento else None,
            "reason_code": code,
            "sources": t.get("sources") or [],
        }

    buckets = []
    for b, label in BUCKETS:
        lis = acc[b]
        v = sum((li.position.valor for li, _ in lis), Decimal("0"))
        buckets.append({
            "bucket_id": b,
            "bucket": label,
            "value_brl": brl(v),
            "portfolio_pct": pct(v, total) if total else None,
            "n_lines": len(lis),
            "line_nos": [li.line_no for li, _ in lis],
            "lines": [line_row(li, code) for li, code in lis],
        })
    above = sum((li.position.valor for b in ABOVE_D30_PARTS for li, _ in acc[b]), Decimal("0"))
    check = sum((Decimal(str(x["value_brl"])) for x in buckets), Decimal("0")) - total
    unanswered = [li.line_no for li, code in acc["sem_classificacao"] if code in ("consulta_falhou", "resposta_inconsistente")]
    if terms is not None:
        sec.errors.extend(terms.errors)
    if not lines:
        sec.status = STATUS_NOT_APPLICABLE
    elif unanswered:
        asked = len(terms.requested) if terms else 0
        if asked and len(unanswered) >= asked:
            sec.fail("portfolio_fund_terms falhou: prazos de resgate dos fundos não avaliados (erro literal em errors).",
                     code="consulta_falhou")
        else:
            sec.degrade(f"{len(unanswered)} fundo(s) sem resposta de portfolio_fund_terms: em sem classificação.",
                        code="consulta_falhou")
    if any(code == "liquidez_sem_identificacao" for _, code in acc["sem_classificacao"]):
        sec.degrade("Linha(s) não identificada(s): sem prazo de resgate a consultar.", code="liquidez_sem_identificacao")
    return {
        **sec.head(),
        "title": TITLE,
        "source": "statement",
        "basis": BASIS,
        "days_note": DAYS_NOTE,
        "note": NOTE,
        "thresholds_days": {"d5": D5, "d30": D30},
        "portfolio_value_brl": brl(total),
        "buckets": buckets,
        "above_d30_parts": list(ABOVE_D30_PARTS),
        "above_d30_total_brl": brl(above),
        "above_d30_total_pct": pct(above, total) if total else None,
        "evaluated": bool(lines) and not unanswered and sec.status != STATUS_UNKNOWN,
        "unanswered_line_nos": unanswered,
        "sum_check_brl": brl(check),
    }


def liquidity_complete(section: dict[str, Any] | None) -> bool:
    return isinstance(section, dict) and section.get("status") in (STATUS_COMPLETE, "partial") and bool(section.get("evaluated"))
