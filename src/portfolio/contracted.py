"""Schema 2.2 (#766, method C): the contracted return of a bank credit line (CDB, LCI, LCA, CDCA).

SILO has no price series for these papers. What the statement prints is a rate ("110,00% do CDI", "CDI + 1,50%",
"IPCA + 6,20%", "13,84% a.a."). Applied to the CDI or the IPCA of the window, it gives what the contract pays over the
window: a "retorno contratado", with no credit risk and no mark to market, gross of income tax. It is never a measured
return: it lives in the line's separate ``contracted`` block, never in measured ``windows``, the measured share of
``coverage`` or the contribution. The owner chose to show its 12-month figure in the same report table as methods A
and B on 2026-10-09; it remains clearly labelled contracted and is not added to their coverage or totals.

Rules, fixed (never tuned per paper):

* the rate is read only when it matches one of four shapes exactly (``RATE_SHAPES``); any other text, or a rate the
  OCR did not check, is ``contratado_taxa_ilegivel``. Nothing is inferred from a bare "CDI";
* the paper must exist for the whole window: its initial date (the BTG performance report's 'Data inicial', else the
  spreadsheet's 'data_aplicacao') on or before the base date, and its maturity, when printed, on or after the end date;
* dates are the CDI calendar's month-ends of the base and end months (as a fund's); the business days are the CDI
  rates from the base date inclusive to the end date exclusive (B3's DI-factor convention);
* % do CDI: product of ``1 + rate/100 x p/100``, each factor truncated at 16 places, product rounded to 8 (B3, Caderno
  de Fórmulas CDB, 6.1.2). CDI + s: the DI factor times ``(1 + s/100) ^ (du/252)``. Prefixado x: ``(1 + x/100) ^
  (du/252)``. IPCA + s: the product of the IPCA monthly changes of the window's months (``inflation('IPCA')``) times
  ``(1 + s/100) ^ (du/252)``: an approximation, with no lag or anniversary pro rata, said so on the window;
* "% do CDI" only for a rate on the CDI; otherwise n/a and the difference in p.p.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Any

from src.portfolio.client import SiloClient
from src.portfolio.common import Call, Section, add_months, as_date, call_tool, dec, iso, ratio, statement_source
from src.portfolio.identify import LineId
from src.portfolio.statement import Position

EVALUATED = "avaliado"
NOT_EVALUATED = "nao_avaliado"
LABEL = "retorno contratado"
NOTE = (
    "Retorno contratado: a taxa impressa no extrato aplicada ao CDI ou ao IPCA da janela, condicionado a o papel existir "
    "durante toda a janela. A taxa não incorpora risco de crédito nem marcação a mercado e é bruta de IR; aparece "
    "identificada como contratada e permanece fora da cobertura medida e das contribuições."
)
NOTE_IPCA = (
    "aproximação: IPCA dos meses da janela, sem defasagem nem pró-rata da data de aniversário do papel"
)
BANK_TIPOS = ("CDB", "LCI", "LCA")
_CDCA = re.compile(r"(?<![A-Z0-9])CDCA-")
_NUM = r"(\d{1,3}(?:,\d+)?)"
# (indexer, pattern) on the trimmed, upper-cased text; the number is Brazilian (comma decimal)
RATE_SHAPES = (
    ("pct_cdi", re.compile(rf"^{_NUM}\s*%\s*(?:DO\s+)?CDI$")),
    ("cdi_spread", re.compile(rf"^CDI\s*\+\s*{_NUM}\s*%(?:\s*A\.?\s*A\.?)?$")),
    ("ipca_spread", re.compile(rf"^IPCA\s*\+\s*{_NUM}\s*%(?:\s*A\.?\s*A\.?)?$")),
    ("prefixado", re.compile(rf"^{_NUM}\s*%\s*A\.?\s*A\.?$")),
)
CDI_INDEXERS = ("pct_cdi", "cdi_spread")
FACTOR_PLACES = Decimal(1).scaleb(-16)
PRODUCT_PLACES = Decimal(1).scaleb(-8)
DAYS_YEAR = Decimal(252)
WINDOWS = (("12m", 12), ("6m", 6))


def is_bank_credit(p: Position) -> bool:
    """A CDB, LCI or LCA by type, or a CDCA the statement prints as such (its 'CDCA-' code)."""
    return p.tipo in BANK_TIPOS or (p.tipo == "outro" and bool(_CDCA.search(str(p.linha_extrato or "").upper())))


def parse_rate(text: str | None) -> dict[str, Any] | None:
    """The rate's indexer and number, or None when the text matches none of the four shapes."""
    if not text:
        return None
    t = re.sub(r"\s+", " ", str(text).strip().upper())
    for indexer, rx in RATE_SHAPES:
        m = rx.match(t)
        if m:
            return {"indexer": indexer, "value": float(Decimal(m.group(1).replace(",", ".")))}
    return None


class Ipca:
    """The IPCA monthly changes of the window's months, fetched once and only when a contracted rate is on IPCA."""

    def __init__(self, by_month: dict[dt.date, Decimal], call: Call | None, error: str | None):
        self.by_month = by_month
        self.call = call
        self.error = error

    @classmethod
    def fetch(cls, lines: list[LineId], client: SiloClient, months: list[dt.date], sec: Section) -> "Ipca":
        need = any(is_bank_credit(li.position) and (parse_rate(li.position.taxa_texto) or {}).get("indexer") == "ipca_spread"
                   for li in lines)
        if not need:
            return cls({}, None, None)
        args = {"p_series": "IPCA", "p_from": months[1].isoformat(), "p_to": add_months(months[-1], 1).isoformat()}
        call = call_tool(client, "inflation", args, sec.errors)
        if not call.ok:
            sec.degrade("inflation falhou: o retorno contratado atrelado ao IPCA não foi calculado (erro literal em errors).",
                        code="consulta_falhou")
            return cls({}, call, "consulta_falhou")
        out: dict[dt.date, Decimal] = {}
        for r in call.rows or []:
            d, v = as_date(r.get("reference_date")), dec(r.get("value"))
            if r.get("series") not in (None, "IPCA") or d is None or v is None or d.replace(day=1) in out:
                return cls({}, call, "resposta_inconsistente")
            out[d.replace(day=1)] = v
        return cls(out, call, None)


def compute(li: LineId, months: list[dt.date], cdi: Any, ipca: Ipca) -> dict[str, Any] | None:
    """The ``contracted`` block of one line; None for a line that is not bank credit."""
    p = li.position
    if not is_bank_credit(p):
        return None
    rate = parse_rate(p.taxa_texto) if p.taxa_conferida is not False else None
    start = p.data_inicial or p.data_aplicacao
    out: dict[str, Any] = {
        "label": LABEL,
        "basis": "retorno_contratado",
        "taxa_texto": p.taxa_texto,  # as printed
        "rate": rate,
        "data_inicial": iso(start),
        "data_inicial_source": ("data_inicial" if p.data_inicial else "data_aplicacao") if start else None,
        "vencimento": iso(p.vencimento),
        "status": NOT_EVALUATED,
        "reason_code": None,
        "notes": [NOTE],
        "windows": {},
        "sources": [statement_source(li.line_no, p.data_posicao)],
    }
    for wid, n in WINDOWS:
        out["windows"][wid] = _window(months[-(n + 1):], rate, start, p.vencimento, cdi, ipca)
    if any(w["status"] == EVALUATED for w in out["windows"].values()):
        out["status"] = EVALUATED
    else:
        out["reason_code"] = out["windows"]["12m"]["reason_code"]
    if rate and rate["indexer"] == "ipca_spread":
        out["notes"].append(NOTE_IPCA)
    return out


def _empty(code: str | None, wm: list[dt.date]) -> dict[str, Any]:
    return {"status": NOT_EVALUATED, "reason_code": code, "base_month": iso(wm[0]), "end_month": iso(wm[-1]),
            "base_date": None, "end_date": None, "n_business_days": None, "accrual_pct": None, "index_pct": None,
            "rate_factor_pct": None, "cdi_pct": None, "net_minus_cdi_pp": None, "pct_of_cdi": None,
            "pct_of_cdi_reason_code": None, "approximation": None, "sources": []}


def _window(wm: list[dt.date], rate: dict | None, start: dt.date | None, maturity: dt.date | None, cdi: Any,
            ipca: Ipca) -> dict[str, Any]:
    if rate is None:
        return _empty("contratado_taxa_ilegivel", wm)
    if start is None:
        return _empty("contratado_sem_data_inicial", wm)
    if cdi.error_code:
        return _empty("cdi_indisponivel", wm)
    d0, d1 = cdi.month_end(wm[0]), cdi.month_end(wm[-1])
    if d0 is None or d1 is None:
        return _empty("cdi_indisponivel", wm)
    if start > d0:
        return _empty("contratado_papel_mais_novo", wm)
    if maturity is not None and maturity < d1:
        return _empty("contratado_vence_na_janela", wm)
    cdi_ret, du = cdi.compound(d0, d1)
    if cdi_ret is None:
        return _empty("cdi_indisponivel", wm)
    value = Decimal(str(rate["value"]))
    years = Decimal(du) / DAYS_YEAR
    srcs = [cdi.call.src(d1)] if cdi.call else []
    index_ret = rate_factor = None
    approx = None
    if rate["indexer"] == "pct_cdi":
        f = Decimal(1)
        for d, v in cdi.rates:
            if d0 <= d < d1:
                f *= (1 + v / 100 * value / 100).quantize(FACTOR_PLACES, rounding=ROUND_DOWN)
        accrual = f.quantize(PRODUCT_PLACES, rounding=ROUND_HALF_UP) - 1
        index_ret = cdi_ret
    elif rate["indexer"] == "cdi_spread":
        rate_factor = (1 + value / 100) ** years
        accrual = (1 + cdi_ret) * rate_factor - 1
        index_ret = cdi_ret
    elif rate["indexer"] == "prefixado":
        rate_factor = (1 + value / 100) ** years
        accrual = rate_factor - 1
    else:  # ipca_spread
        if ipca.error or any(m not in ipca.by_month for m in wm[1:]):
            return _empty("contratado_ipca_indisponivel", wm)
        idx = Decimal(1)
        for m in wm[1:]:
            idx *= 1 + ipca.by_month[m] / 100
        index_ret = idx - 1
        rate_factor = (1 + value / 100) ** years
        accrual = idx * rate_factor - 1
        approx = NOTE_IPCA
        if ipca.call:
            srcs.append(ipca.call.src(wm[-1]))
    w = _empty(None, wm)
    w.update(
        status=EVALUATED,
        base_date=iso(d0),
        end_date=iso(d1),
        n_business_days=du,
        accrual_pct=ratio(accrual * 100, 6),
        index_pct=ratio(index_ret * 100, 6) if index_ret is not None else None,
        rate_factor_pct=ratio((rate_factor - 1) * 100, 6) if rate_factor is not None else None,
        cdi_pct=ratio(cdi_ret * 100, 6),
        net_minus_cdi_pp=ratio((accrual - cdi_ret) * 100, 6),
        approximation=approx,
        sources=srcs,
    )
    if rate["indexer"] not in CDI_INDEXERS:
        w["pct_of_cdi_reason_code"] = "credito_nao_cdi"
    elif cdi_ret <= 0:
        w["pct_of_cdi_reason_code"] = "cdi_nao_positivo"
    else:
        w["pct_of_cdi"] = ratio(accrual / cdi_ret * 100, 4)
    return w
