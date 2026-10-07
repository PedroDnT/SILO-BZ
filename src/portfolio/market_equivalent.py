"""Block 17 (engine 1.13): the market equivalent per fund line (#609, owner's resolution of 2026-10-05).

For a fund line whose ANBIMA class (as filed in the Extrato, read by the fee comparison) is mapped to an index in the
reviewed YAML (``rules/equivalents/class_index.yaml``, approved pairs, read in reverse: class -> index), the
equivalent is the largest active ETF by third-party PL tracking one of those indices (``api.portfolio_equivalents``).
The ETF and the fund are set beside the class's net quota return distribution (``api.class_return_distribution``:
p25, median, p75, at least 30 funds) over the return block's 12- and 6-month windows. The ETF's return comes from the
return block's own machinery: the cash-tape ``close`` ("sem proventos") or, for a fixed-income ETF,
``trade_consolidated_history``'s ``last_price``; never ``ref_price`` or ``close_adj``. The ETF's PL and fee are the
etfsbrasil.com.br values (third party, dated). A fact beside the fund, not a recommendation: no ranking, no
"melhor", no instruction. Every line without an equivalent carries a fixed reason code (``common.REASON_TEXT``).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from src.portfolio import returns as _ret
from src.portfolio.client import SiloClient
from src.portfolio.common import (
    REASON_TEXT,
    STATUS_NOT_APPLICABLE,
    Section,
    add_months,
    as_date,
    brl,
    call_tool,
    dec,
    iso,
    pct,
    ratio,
    statement_source,
)
from src.portfolio.equivalents import Pair, load_pairs
from src.portfolio.identify import LineId

EQ_LABEL = "equivalente de mercado; não é recomendação"
EQ_FOUND = "encontrado"
EQ_NONE = "sem_equivalente"
CHOICE_NOTE = ("O ETF é o maior por patrimônio líquido (site de terceiros, na data indicada) entre os ETFs ativos que "
               "acompanham um índice ligado à classe ANBIMA do fundo na lista de classes revisada pelo dono "
               "do SILO. Mesmo objetivo; não é recomendação de troca.")
BAND_NOTE = "posição do retorno na distribuição da classe (p25, mediana, p75), não um ranking"
CLASS_NOTE = ("Distribuição do retorno líquido de cota dos fundos FI ativos da mesma classe ANBIMA e do mesmo indicador "
              "de fundo de cotas (mínimo de 30 fundos), nas mesmas janelas do bloco de retorno.")
# The PL and fee labels and the band text are the report's (src/portfolio/report/labels.py, engine 2.0).
CLASS_CALL_LIMIT = 50
# fee-comparison codes that mean it read no class it accepted (the class comes only from an accepted served row)
NO_CLASS_READ = ("sem_linha_comparacao", "sem_identificacao", "tipo_fora_comparacao", "resposta_inconsistente")
STATUS_TO_CODE = {"sem_par": "equivalente_sem_par", "sem_etf": "equivalente_sem_etf", "sem_pl": "equivalente_sem_pl"}


def compute_equivalents(lines: list[LineId], fees: dict[str, Any], returns: dict[str, Any], client: SiloClient,
                        position_date: dt.date, as_of: dt.date, portfolio_total: Decimal,
                        pairs: list[Pair] | None = None) -> dict[str, Any]:
    sec = Section()
    pairs = load_pairs() if pairs is None else pairs
    approved: dict[str, list[str]] = {}
    for p in pairs:
        if p.status == "aprovada":
            approved.setdefault(p.classe_anbima, []).append(p.underlying_index)
    end_month = as_date(returns.get("end_month")) or _ret.default_movement_month(position_date)
    months = [add_months(end_month, -12 + i) for i in range(13)]
    cmp_by = {c["line_no"]: c for c in (fees.get("comparison") or {}).get("lines", [])}
    ret_by = {r["line_no"]: r for r in returns.get("lines", [])}
    funds = [li for li in lines if li.position.tipo == "fundo"]

    # 1. the class of each fund line, from the fee comparison (the Extrato's CLASSE_ANBIMA and FUNDO_COTAS, as filed)
    out: list[dict[str, Any]] = []
    todo: list[tuple[dict[str, Any], str, str | None]] = []
    for li in funds:
        rec = _empty_line(li, ret_by.get(li.line_no))
        c = cmp_by.get(li.line_no) or {}
        cls = c.get("classe_anbima")
        if li.status != "identified" or li.entity_type not in (None, "fi") or not li.cnpj:
            _why(rec, "equivalente_fora_escopo")
        elif c.get("reason_code") == "consulta_falhou":
            _why(rec, "consulta_falhou")
        elif not c or c.get("reason_code") in NO_CLASS_READ:
            _why(rec, "equivalente_sem_comparacao")  # the fee comparison read no row, or one it rejected
        elif not cls:
            _why(rec, "equivalente_sem_classe")
        else:
            rec.update(classe_anbima=cls, fundo_cotas=c.get("fundo_cotas"))
            todo.append((rec, cls, c.get("fundo_cotas")))
        out.append(rec)

    # 2. one call for the classes: the ETFs on their mapped indices, the largest by PL flagged
    classes = sorted({cls for _, cls, _ in todo})
    by_class: dict[str, list[dict]] = {}
    eq_calls: dict[str, Any] = {}
    failed: set[str] = set()
    for i in range(0, len(classes), CLASS_CALL_LIMIT):
        chunk = classes[i:i + CLASS_CALL_LIMIT]
        call = call_tool(client, "portfolio_equivalents", {"p_classes": chunk, "p_as_of": as_of.isoformat()}, sec.errors)
        if not call.ok:
            failed.update(chunk)
            continue
        for row in call.rows or []:
            if row.get("classe_anbima") in chunk:
                by_class.setdefault(row["classe_anbima"], []).append(row)
                eq_calls[row["classe_anbima"]] = call

    dist_cache: dict[tuple[str, str], tuple[dict[int, dict] | None, Any, str | None]] = {}
    etf_cache: dict[str, dict[str, Any]] = {}
    series_cache: dict = {}
    no_cdi = _ret._Cdi([], None, "nao_usado")  # the ETF's own return; the CDI comparison is the return block's
    for rec, cls, fc in todo:
        if cls in failed:
            _why(rec, "consulta_falhou")
            continue
        rows = by_class.get(cls)
        pick, code = _pick(rows, approved.get(cls, []))
        if rows:
            rec.update(class_indices=list(rows[0].get("class_indices") or []) or None, n_etfs=rows[0].get("n_etfs"),
                       class_indices_rules=sorted(set(approved.get(cls, []))) or None)
            rec["pairs_match_rules"] = sorted(rec["class_indices"] or []) == (rec["class_indices_rules"] or [])
        if cls in eq_calls:
            rec["sources"].append(eq_calls[cls].src(pick.get("pl_as_of") if pick else None))
        if code:
            _why(rec, code)
            continue
        if pick.get("ticker") not in etf_cache:
            etf_cache[pick["ticker"]] = _etf_series(pick, client, months, position_date, series_cache, no_cdi, sec)
        etf = _etf_record(pick, etf_cache[pick["ticker"]], cmp_by.get(rec["line_no"]) or {},
                          eq_calls[cls].src(pick.get("pl_as_of")))
        dist = _distribution(client, cls, fc, end_month, dist_cache, sec)
        rec.update(status=EQ_FOUND, etf=etf, windows=_windows(rec, etf_cache[pick["ticker"]], dist, ret_by.get(rec["line_no"]),
                                                       end_month))
        rec["label"] = EQ_LABEL

    for rec in out:
        if rec["reason_code"]:
            sec.degrade("Há fundos sem equivalente de mercado; cada linha informa o motivo.", code=rec["reason_code"])
        for w in rec["windows"]:
            for k in ("etf_reason_code", "class_reason_code"):
                if w.get(k):
                    sec.degrade("Há equivalentes sem comparação de retorno; cada janela informa o motivo.", code=w[k])
    if not funds:
        sec.status, sec.reason = STATUS_NOT_APPLICABLE, "Nenhuma linha de fundo na carteira."
    elif classes and set(classes) <= failed:
        sec.fail("Consulta de equivalente de mercado falhou.", code="consulta_falhou")
    if sec.status == "partial":
        sec.reason = "Há fundos sem equivalente de mercado ou sem comparação de retorno; cada linha informa o motivo."
    found = [r for r in out if r["status"] == EQ_FOUND]
    covered = sum((Decimal(str(r["valor_brl"])) for r in found), Decimal("0"))
    return {
        **sec.head(),
        "label": EQ_LABEL,
        "as_of": as_of.isoformat(),
        "end_month": iso(end_month),
        "windows": [{"id": wid, "months": n, "base_month": iso(add_months(end_month, -n)), "end_month": iso(end_month),
                     "annualized": False} for wid, n, *_ in _ret.WINDOWS],
        "choice_note": CHOICE_NOTE,
        "class_note": CLASS_NOTE,
        "band_note": BAND_NOTE,
        "lines": out,
        "n_fund_lines": len(out),
        "n_found": len(found),
        "n_without": len(out) - len(found),
        "found_value_brl": brl(covered),
        "coverage_portfolio_value_pct": pct(covered, portfolio_total),
    }


def _empty_line(li: LineId, ret_line: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "line_no": li.line_no,
        "linha_extrato": li.position.linha_extrato,
        "fund_name": li.name or li.position.linha_extrato,
        "cnpj": li.cnpj,
        "valor_brl": brl(li.position.valor),
        "classe_anbima": None,
        "fundo_cotas": None,
        "class_indices": None,
        "n_etfs": None,
        "status": EQ_NONE,
        "reason_code": None,
        "reason": None,
        "label": EQ_LABEL,
        "etf": None,
        "windows": [],
        "fund_return_status": (ret_line or {}).get("status"),
        "class_indices_rules": None,  # the YAML's approved indices for the class, as this engine read them
        "pairs_match_rules": None,  # false while the database serves another version of the reviewed list
        "sources": [statement_source(li.line_no, li.position.data_posicao)],
    }


def _why(rec: dict[str, Any], code: str) -> None:
    rec.update(status=EQ_NONE, reason_code=code, reason=REASON_TEXT[code])


def _pick(rows: list[dict] | None, yaml_indices: list[str]) -> tuple[dict | None, str | None]:
    """The equivalent row, or a reason code. The served pairs decide (the SQL reads only approved ones); a list that
    differs from the YAML on disk is a deploy lag, flagged on the line (``pairs_match_rules``), not a failure."""
    if not rows:
        return None, "equivalente_sem_linha"
    statuses = {r.get("status") for r in rows}
    if len(statuses) != 1:
        return None, "resposta_inconsistente"
    status = statuses.pop()
    if status in STATUS_TO_CODE:
        return None, STATUS_TO_CODE[status]
    picks = [r for r in rows if r.get("is_equivalent") is True]
    if status != "found" or len(picks) != 1 or not picks[0].get("ticker") or dec(picks[0].get("pl_brl")) is None:
        return None, "resposta_inconsistente"
    best = picks[0]
    if any((dec(r.get("pl_brl")) or Decimal(0)) > dec(best["pl_brl"]) for r in rows):
        return None, "resposta_inconsistente"  # the flagged ETF must be the largest by PL
    return best, None


def _etf_series(pick: dict, client: SiloClient, months: list[dt.date], position_date: dt.date, cache: dict,
                no_cdi: Any, sec: Section) -> dict[str, Any]:
    """The ETF's 12- and 6-month return, by the return block's own series and window code."""
    basis = _ret.FIXED_INCOME_ETF if pick.get("segment") == "fixed_income_br" else _ret.CLOSE
    points, call, err = _ret._series(None, pick["ticker"], None, basis, client, months, position_date, cache, sec)
    out: dict[str, Any] = {"basis": basis, "points_error": None, "windows": {}, "call": call}
    if points is None:
        if basis == _ret.FIXED_INCOME_ETF and err == "consulta_falhou" and not (call is not None and call.transient):
            err = "etf_rf_sem_api"  # the tool is not served yet (catalog v65 not deployed) or refused
        out["points_error"] = err
        return out
    fee = {"status": "nao_se_aplica", "reason_code": None, "rate_pct_year": None, "sources": []}
    for wid, n, frac, vol_note in _ret.WINDOWS:
        out["windows"][wid] = _ret._window(months[-(n + 1):], n, frac, vol_note, points, basis, fee, no_cdi, call)
    return out


def _etf_record(pick: dict, series: dict, comparison: dict, src: dict) -> dict[str, Any]:
    basis = series["basis"]
    peers = comparison.get("etf_peer_tickers") or []
    return {
        "ticker": pick.get("ticker"),
        "cnpj": pick.get("etf_cnpj"),
        "name": pick.get("etf_name"),
        "underlying_index": pick.get("underlying_index"),
        "segment": pick.get("segment"),
        "pl_brl": brl(dec(pick.get("pl_brl"))),
        "pl_as_of": pick.get("pl_as_of"),
        "fee_pct_year": ratio(dec(pick.get("fee_pct_year")), 4),
        "fee_as_of": pick.get("fee_as_of"),
        "fee_reason_code": None if pick.get("fee_pct_year") is not None else "equivalente_sem_taxa",
        "in_fee_peers": pick.get("ticker") in peers,
        "snapshot_source": pick.get("snapshot_source"),
        "basis": basis,
        "without_distributions": True,
        "note": _ret.NOTE_ETF,
        "pl_rank": pick.get("pl_rank"),
        "sources": [src],
    }


def _distribution(client: SiloClient, cls: str, fc: str | None, end_month: dt.date, cache: dict, sec: Section):
    key = (cls, fc or "")
    if key in cache:
        return cache[key]
    if fc not in ("S", "N"):
        cache[key] = (None, None, "distribuicao_classe_nao_avaliada")
        return cache[key]
    args = {"p_classe_anbima": cls, "p_fundo_cotas": fc, "p_month": end_month.isoformat()}
    call = call_tool(client, "class_return_distribution", args, sec.errors)
    if not call.ok:
        cache[key] = (None, call, "consulta_falhou")
        return cache[key]
    rows = {}
    for r in call.rows or []:
        n = r.get("window_months")
        if n not in (12, 6) or n in rows or as_date(r.get("end_month")) != end_month \
                or as_date(r.get("start_month")) != add_months(end_month, -n):
            cache[key] = (None, call, "resposta_inconsistente")
            return cache[key]
        rows[n] = r
    cache[key] = (rows, call, None) if set(rows) == {12, 6} else (None, call, "resposta_inconsistente")
    return cache[key]


def _band(v: Decimal | None, p25: Decimal, med: Decimal, p75: Decimal) -> str | None:
    if v is None:
        return None
    if v < p25:
        return "abaixo_p25"
    if v < med:
        return "p25_mediana"
    if v <= p75:
        return "mediana_p75"
    return "acima_p75"


def _windows(rec: dict, series: dict, dist: tuple, ret_line: dict | None, end_month: dt.date) -> list[dict[str, Any]]:
    rows, dcall, derr = dist
    out = []
    for wid, n, *_ in _ret.WINDOWS:
        w: dict[str, Any] = {
            "id": wid, "months": n, "base_month": iso(add_months(end_month, -n)), "end_month": iso(end_month),
            "etf_net_return_pct": None, "etf_status": _ret.NOT_EVALUATED, "etf_reason_code": None, "etf_reason": None,
            "fund_net_return_pct": None, "fund_status": _ret.NOT_EVALUATED, "fund_reason_code": None,
            "class_status": _ret.NOT_EVALUATED, "class_reason_code": None, "class_reason": None, "class_n_funds": None,
            "class_p25_pct": None, "class_median_pct": None, "class_p75_pct": None,
            "etf_minus_median_pp": None, "fund_minus_median_pp": None,
            "etf_band": None, "fund_band": None,
            "band_note": BAND_NOTE, "etf_series_reason_code": None, "etf_base_date": None, "etf_end_date": None,
            "class_start_month": None, "class_end_month": None, "class_source_reason": None, "sources": [],
        }
        ew = series["windows"].get(wid)
        if series["points_error"] or ew is None or ew["status"] != _ret.EVALUATED:
            code = series["points_error"] or (ew or {}).get("reason_code") or "serie_incompleta"
            w.update(etf_reason_code="equivalente_sem_retorno", etf_reason=REASON_TEXT["equivalente_sem_retorno"],
                     etf_series_reason_code=code)
        else:
            w.update(etf_net_return_pct=ew["net_return_pct"], etf_status=_ret.EVALUATED,
                     etf_base_date=ew["base_date"], etf_end_date=ew["end_date"])
            w["sources"].extend(ew["sources"][:1])
        fw = ((ret_line or {}).get("windows") or {}).get(wid) or {}
        if fw.get("status") == _ret.EVALUATED:
            w.update(fund_net_return_pct=fw["net_return_pct"], fund_status=_ret.EVALUATED)
        else:
            w["fund_reason_code"] = fw.get("reason_code") or (ret_line or {}).get("reason_code") or "linhas_sem_retorno"
        r = (rows or {}).get(n)
        if derr or r is None:
            code = derr or "resposta_inconsistente"
            w.update(class_reason_code=code, class_reason=REASON_TEXT[code])
        elif r.get("status") != "evaluated" or any(dec(r.get(k)) is None for k in ("p25_pct", "median_pct", "p75_pct")):
            w.update(class_reason_code="distribuicao_classe_nao_avaliada",
                     class_reason=REASON_TEXT["distribuicao_classe_nao_avaliada"], class_n_funds=r.get("n_funds"),
                     class_source_reason=r.get("reason"))
        else:
            p25, med, p75 = (dec(r[k]) for k in ("p25_pct", "median_pct", "p75_pct"))
            if not p25 <= med <= p75 or not isinstance(r.get("n_funds"), int) or r["n_funds"] < 30:
                w.update(class_reason_code="resposta_inconsistente", class_reason=REASON_TEXT["resposta_inconsistente"])
            else:
                w.update(class_status=_ret.EVALUATED, class_n_funds=r["n_funds"], class_p25_pct=ratio(p25, 6),
                         class_median_pct=ratio(med, 6), class_p75_pct=ratio(p75, 6),
                         class_start_month=r.get("start_month"), class_end_month=r.get("end_month"))
                if dcall is not None:
                    w["sources"].append(dcall.src(r.get("end_month")))
                for who in ("etf", "fund"):
                    v = dec(w[f"{who}_net_return_pct"])
                    if v is not None:
                        b = _band(v, p25, med, p75)
                        w.update({f"{who}_minus_median_pp": ratio(v - med, 6), f"{who}_band": b})
        out.append(w)
    return out
