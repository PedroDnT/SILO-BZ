"""Engine 2.1 (#766, method C): the contracted return of a bank or similar credit line (CDB, LCI, LCA, CDCA).

The statement prints the rate and the start date ("Data Inicial"); the return is the rate accrued over the window on
the CDI or the IPCA of the same dates. It is what the contract pays, labelled "retorno contratado": no credit risk, no
mark, never a market return. It sits apart from ``returns.lines`` (the owner's decision: annex only), so it enters no
coverage, contribution or body table.

A rate is read only when it is one of five plain shapes: "p% do CDI", "CDI", "CDI + s%", "IPCA + s%", "r% a.a.".
Anything else is not read. A paper that started after the window's base date, has no start date or matured inside the
window is not evaluated: a 12-month accrual on a younger paper would be invented.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import ROUND_DOWN, Decimal
from typing import Any

from src.portfolio.client import SiloClient
from src.portfolio.common import Section, as_date, call_tool, dec, iso, ratio, statement_source
from src.portfolio.identify import LineId

CONTRACTED_TIPOS = ("CDB", "LCI", "LCA")
LABEL = "retorno contratado"
NOTE = (
    "Retorno contratado: a taxa impressa no extrato acumulada sobre o CDI ou o IPCA das mesmas datas, desde a data base "
    "da janela. É o que o contrato paga, sem risco de crédito nem marcação; não é retorno de mercado. O IPCA entra pelo "
    "mês cheio, sem pró-rata nem defasagem; o prefixado e o spread contam dias úteis do CDI."
)
FACTOR_PLACES = Decimal(1).scaleb(-16)

_PCT_CDI = re.compile(r"^(\d+(?:,\d+)?)\s*%\s*(?:DO\s+)?CDI$")
_CDI_SPREAD = re.compile(r"^CDI\s*\+\s*(\d+(?:,\d+)?)\s*%(?:\s*A\.?A\.?)?$")
_IPCA_SPREAD = re.compile(r"^IPCA\s*\+\s*(\d+(?:,\d+)?)\s*%(?:\s*A\.?A\.?)?$")
_PREFIXED = re.compile(r"^(\d+(?:,\d+)?)\s*%\s*A\.?A\.?$")

REASONS = {
    "contratado_sem_taxa": "o extrato não imprime a taxa",
    "contratado_taxa_ilegivel": "taxa impressa fora das formas lidas (p% do CDI, CDI, CDI + s%, IPCA + s%, r% a.a.)",
    "contratado_sem_data_inicial": "o extrato não imprime a data inicial",
    "contratado_papel_mais_novo": "o papel começou depois da data base da janela",
    "contratado_vencido": "o papel venceu antes do fim da janela",
    "cdi_indisponivel": "CDI do período indisponível",
    "contratado_ipca_indisponivel": "IPCA de algum mês da janela indisponível no SILO",
}


def parse_rate(text: str | None) -> dict[str, Any] | None:
    """{kind, value_pct} for the five plain shapes; None for anything else."""
    t = re.sub(r"\s+", " ", (text or "").strip().upper())
    if t == "CDI":
        return {"kind": "pct_cdi", "value_pct": 100.0}
    for kind, rx in (("pct_cdi", _PCT_CDI), ("cdi_spread", _CDI_SPREAD), ("ipca_spread", _IPCA_SPREAD), ("prefixado", _PREFIXED)):
        m = rx.match(t)
        if m:
            return {"kind": kind, "value_pct": float(m.group(1).replace(",", "."))}
    return None


def _trunc(x: Decimal) -> Decimal:
    return x.quantize(FACTOR_PLACES, rounding=ROUND_DOWN)


def compute_contracted(lines: list[LineId], cdi: Any, client: SiloClient, windows: list[tuple[str, list[dt.date]]],
                       sec: Section) -> dict[str, Any]:
    """``windows``: (id, months) with the base month first. ``cdi`` is the returns block's own series."""
    targets = [li for li in lines if li.position.tipo in CONTRACTED_TIPOS
               or (li.position.tipo == "outro" and li.kind == "credito")]
    rates = {li.line_no: parse_rate(li.position.taxa_texto) for li in targets}
    ipca, ipca_call = _ipca(client, windows, sec) if any((r or {}).get("kind") == "ipca_spread" for r in rates.values()) else ({}, None)
    out = []
    for li in targets:
        p = li.position
        rec = {
            "line_no": li.line_no, "linha_extrato": p.linha_extrato, "tipo": p.tipo, "valor_brl": ratio(dec(p.valor), 2),
            "taxa_texto": p.taxa_texto, "rate": rates[li.line_no], "data_inicial": iso(p.data_inicial or p.data_aplicacao),  # the PDF's 'Data Inicial', else the sheet's data_aplicacao
            "vencimento": iso(p.vencimento), "status": "nao_avaliado", "windows": {},
            "sources": [statement_source(li.line_no, p.data_posicao)],
        }
        for wid, months in windows:
            rec["windows"][wid] = _window(rec, months, cdi, ipca, ipca_call)
        if any(w["status"] == "avaliado" for w in rec["windows"].values()):
            rec["status"] = "avaliado"
        out.append(rec)
    return {"label": LABEL, "note": NOTE, "lines": out, "n_lines": len(out),
            "n_evaluated": sum(r["status"] == "avaliado" for r in out)}


def _ipca(client: SiloClient, windows: list[tuple[str, list[dt.date]]], sec: Section) -> tuple[dict[dt.date, Decimal], Any]:
    first = min(ms[0] for _, ms in windows)
    last = max(ms[-1] for _, ms in windows)
    call = call_tool(client, "inflation", {"p_series": "IPCA", "p_from": first.isoformat(), "p_to": last.isoformat()}, sec.errors)
    if not call.ok:
        return {}, call
    out: dict[dt.date, Decimal] = {}
    for r in call.rows or []:
        d, v = as_date(r.get("reference_date")), dec(r.get("value"))
        if d is not None and v is not None and r.get("series") in (None, "IPCA"):
            out[d.replace(day=1)] = v
    return out, call


def _empty(code: str, months: list[dt.date]) -> dict[str, Any]:
    return {"status": "nao_avaliado", "reason_code": code, "reason": REASONS[code], "base_month": iso(months[0]),
            "end_month": iso(months[-1]), "base_date": None, "end_date": None, "n_business_days": None,
            "contracted_return_pct": None, "cdi_pct": None, "net_minus_cdi_pp": None, "pct_of_cdi": None,
            "pct_of_cdi_reason_code": None, "sources": []}


def _window(rec: dict, months: list[dt.date], cdi: Any, ipca: dict[dt.date, Decimal], ipca_call: Any) -> dict[str, Any]:
    rate = rec["rate"]
    if not rec["taxa_texto"]:
        return _empty("contratado_sem_taxa", months)
    if rate is None:
        return _empty("contratado_taxa_ilegivel", months)
    start, end = (cdi.month_end(months[0]), cdi.month_end(months[-1])) if not cdi.error_code else (None, None)
    if start is None or end is None:
        return _empty("cdi_indisponivel", months)
    inicio, venc = as_date(rec["data_inicial"]), as_date(rec["vencimento"])
    if inicio is None:
        return _empty("contratado_sem_data_inicial", months)
    if inicio > start:
        return _empty("contratado_papel_mais_novo", months)
    if venc is not None and venc < end:
        return _empty("contratado_vencido", months)
    days = [v for d, v in cdi.rates if start <= d < end]
    c, _ = cdi.compound(start, end)
    if c is None or not days:
        return _empty("cdi_indisponivel", months)
    n = len(days)
    v = Decimal(str(rate["value_pct"])) / 100
    kind = rate["kind"]
    sources = [cdi.call.src(end)] if cdi.call else []
    if kind == "pct_cdi":
        f = Decimal(1)
        for d in days:
            f = _trunc(f * (1 + d / 100 * v))
    elif kind == "cdi_spread":
        f = (1 + c) * (1 + v) ** (Decimal(n) / 252)
    elif kind == "prefixado":
        f = (1 + v) ** (Decimal(n) / 252)
    else:  # ipca_spread: the IPCA of every month after the base month through the end month
        need = months[1:]
        if any(m not in ipca for m in need):
            return _empty("contratado_ipca_indisponivel", months)
        f = Decimal(1)
        for m in need:
            f *= 1 + ipca[m] / 100
        f *= (1 + v) ** (Decimal(n) / 252)
        if ipca_call is not None:
            sources.append(ipca_call.src(months[-1]))
    r = f - 1
    w = _empty("contratado_sem_taxa", months)
    w.update(status="avaliado", reason_code=None, reason=None, base_date=iso(start), end_date=iso(end), n_business_days=n,
             contracted_return_pct=ratio(r * 100, 6), cdi_pct=ratio(c * 100, 6), net_minus_cdi_pp=ratio((r - c) * 100, 6),
             sources=sources)
    if kind in ("pct_cdi", "cdi_spread") and c > 0:
        w["pct_of_cdi"] = ratio(r / c * 100, 4)
    else:
        w["pct_of_cdi_reason_code"] = "taxa_nao_cdi" if c > 0 else "cdi_nao_positivo"
    return w
