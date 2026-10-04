"""Block 14b: movimento incomum, a fund's month against its own ANBIMA class.

One tool, ``portfolio_movement`` (catalog v54), called once per 200 funds for ONE month.
The SQL owns the statistics (docs: ``31_api_portfolio.sql``, section "portfolio_movement"):
the fund's monthly quota return against the same return over the FI funds of its ANBIMA
class as filed in the CVM Extrato, mean and sample standard deviation taken on values
winsorized at the class's 1st and 99th percentile, ``z = (own - mean) / sd``. This module
does not recompute a number. It carries the served rows, applies the owner's decisions of
2026-10-03 about WHERE a level may appear, and checks the server's level against its own z.

Owner decisions (map #510, 2026-10-03):

* ``atencao`` (strictly beyond 2 class standard deviations) is for the TABLE only: it
  flags about 5% of fund-months on production, and the owner judged a 10% flag too many
  for the text.
* ``forte`` (strictly beyond 3) may go in the TEXT and sets ``investigator_trigger`` for
  the later Investigator agent.
* a fund with fewer than 30 class peers, no class, no return or a month that is not
  complete is ``nao_avaliado`` with the reason, never skipped and never zero.
* nothing here is a forecast or a recommendation: the block states the number, the class,
  the sample size and the month.
"""

from __future__ import annotations

import calendar
import datetime as dt
from decimal import Decimal
from typing import Any

from src.portfolio.client import SiloClient
from src.portfolio.common import STATUS_NOT_APPLICABLE, Section, call_tool, dec, iso, ratio, statement_source
from src.portfolio.identify import LineId

TOOL = "portfolio_movement"
CHUNK = 200
# The owner's thresholds, strictly greater (exactly 2 is normal, exactly 3 is atencao).
ATENCAO_Z = Decimal(2)
FORTE_Z = Decimal(3)
MIN_PEERS = 30
# The SQL decides the level on the unrounded z and serves z at 4 decimals, so a z within half a
# unit of the last place of a threshold may legitimately sit on either side of it.
Z_ROUNDING_TOLERANCE = Decimal("0.0001")

NORMAL = "normal"
ATENCAO = "atencao"
FORTE = "forte"
NOT_EVALUATED = "nao_avaliado"
LEVEL_LABELS = {NORMAL: "normal", ATENCAO: "atenção", FORTE: "forte", NOT_EVALUATED: "não avaliado"}

DEFINITION = (
    "Retorno mensal da cota do fundo (cota de fim de mês sobre a do mês anterior, de fact_fund_monthly) comparado com o "
    "mesmo retorno dos fundos FI da sua classe ANBIMA conforme arquivada no Extrato da CVM; média e desvio padrão da "
    "classe calculados sobre valores winsorizados no 1º e no 99º percentil da classe no mês (o valor do próprio fundo "
    "não é winsorizado); z = (retorno do fundo menos média da classe) dividido pelo desvio padrão da classe."
)
CLASS_NOTE = (
    "A classe é a do arquivo mais recente do Extrato da CVM, não a da data do mês; fundos fora do Extrato ou sem "
    "classe ANBIMA informada não são avaliados."
)
LEVELS_NOTE = (
    "Atenção: |z| acima de 2, só em tabela. Forte: |z| acima de 3, pode entrar no texto e aciona o Investigador. "
    "Estritamente acima: exatamente 2 é normal e exatamente 3 é atenção."
)
NOT_FORECAST = "Sinal estatístico sobre um mês passado: não é previsão de retorno, veredito nem recomendação."
NOT_APPLICABLE_REASONS = {
    "ticker": "ação, ETF ou cota listada identificada por ticker: sem CNPJ de fundo para comparar com a classe",
    "tesouro": "título público direto: não é fundo",
    "caixa": "conta corrente: não é fundo",
}


def default_movement_month(position_date: dt.date) -> dt.date:
    """The month of the position date when it is a month-end, else the month before it.

    A position dated mid-month sits inside a month that is not complete, and the SQL would
    answer ``nao_avaliado`` for every fund; the previous month is the latest one that can be judged.
    """
    first = position_date.replace(day=1)
    last_day = calendar.monthrange(position_date.year, position_date.month)[1]
    if position_date.day == last_day:
        return first
    y, m = divmod(first.month - 2, 12)
    return dt.date(first.year + y, m + 1, 1)


def classify_z(z: Decimal | None) -> str | None:
    """The level a z implies under the owner's thresholds: strictly greater, either sign."""
    if z is None:
        return None
    if abs(z) > FORTE_Z:
        return FORTE
    if abs(z) > ATENCAO_Z:
        return ATENCAO
    return NORMAL


def _implied_levels(z: Decimal) -> set[str]:
    """Levels consistent with a served (4-decimal) z: its own, and those of z moved by the rounding tolerance."""
    out = {classify_z(z), classify_z(z + Z_ROUNDING_TOLERANCE), classify_z(z - Z_ROUNDING_TOLERANCE)}
    return {x for x in out if x}


def _month_end(month: dt.date) -> dt.date:
    return month.replace(day=calendar.monthrange(month.year, month.month)[1])


def _not_applicable(lines: list[LineId], fund_ids: set[int]) -> list[dict[str, Any]]:
    out = []
    for li in lines:
        if li.line_no in fund_ids:
            continue
        reason = NOT_APPLICABLE_REASONS.get(li.kind or "")
        if reason is None:
            reason = (
                "linha não identificada: sem CNPJ de fundo para comparar com a classe"
                if li.status == "unknown"
                else "linha ambígua: sem CNPJ de fundo escolhido para comparar com a classe"
                if li.status == "ambiguous"
                else "sem CNPJ de fundo para comparar com a classe"
            )
        out.append({"line_no": li.line_no, "linha_extrato": li.position.linha_extrato, "level": NOT_EVALUATED,
                    "level_label": LEVEL_LABELS[NOT_EVALUATED], "reason": reason})
    return out


def _unknown_line(li: LineId, month: dt.date, reason: str, code: str) -> dict[str, Any]:
    return {
        "line_no": li.line_no,
        "cnpj": li.cnpj,
        "fund_name": li.name,
        "position_value_source": statement_source(li.position.line_no, li.position.data_posicao),
        "month": iso(month),
        "class": None,
        "subclass": None,
        "class_as_filed": None,
        "class_as_of": None,
        "n_peers": None,
        "min_peers": MIN_PEERS,
        "own_value_pct": None,
        "class_mean_pct": None,
        "class_sd_pct": None,
        "class_p01_pct": None,
        "class_p99_pct": None,
        "z": None,
        "level": NOT_EVALUATED,
        "level_label": LEVEL_LABELS[NOT_EVALUATED],
        "investigator_trigger": False,
        "in_table": False,
        "in_text": False,
        "reason": reason,
        "reason_code": code,  # engine 1.7: the report prints the code's fixed text, never this reason
        "sources": [],
    }


def _line(li: LineId, row: dict[str, Any], call: Any, month: dt.date, sec: Section) -> dict[str, Any]:
    z = dec(row.get("z"))
    level = str(row.get("level") or NOT_EVALUATED)
    reason = row.get("reason")
    code = None  # a reason SILO returned with a verdict is data (the class and its peers), shown as served
    if level not in LEVEL_LABELS:
        code = "resposta_inconsistente"
        level, reason = NOT_EVALUATED, f"nível desconhecido devolvido pelo SILO ({row.get('level')!r}); não usado."
        z = None
        sec.degrade(f"linha {li.line_no}: nível desconhecido devolvido por portfolio_movement.", code="resposta_inconsistente")
    elif level != NOT_EVALUATED:
        # The server decided the level on the unrounded z. A level its own z contradicts is not shown as a finding.
        if z is None or level not in _implied_levels(z):
            reason = (
                f"o SILO devolveu o nível {level!r} com z {None if z is None else str(z)}, que a regra de 2 e 3 desvios "
                "não confirma; linha não avaliada."
            )
            code = "resposta_inconsistente"
            level, z = NOT_EVALUATED, None
            sec.degrade(f"linha {li.line_no}: nível devolvido por portfolio_movement contradiz o seu z.", code="resposta_inconsistente")
    return {
        "line_no": li.line_no,
        "cnpj": li.cnpj,
        "fund_name": li.name,
        "position_value_source": statement_source(li.position.line_no, li.position.data_posicao),
        "month": row.get("month") or iso(month),
        "class": row.get("class"),
        "subclass": row.get("subclass"),
        "class_as_filed": row.get("class_as_filed"),
        "class_as_of": row.get("class_as_of"),
        "n_peers": row.get("n_peers"),
        "min_peers": row.get("min_peers") if row.get("min_peers") is not None else MIN_PEERS,
        "own_value_pct": ratio(dec(row.get("own_value_pct")), 6),
        "class_mean_pct": ratio(dec(row.get("class_mean_pct")), 6),
        "class_sd_pct": ratio(dec(row.get("class_sd_pct")), 6),
        "class_p01_pct": ratio(dec(row.get("class_p01_pct")), 6),
        "class_p99_pct": ratio(dec(row.get("class_p99_pct")), 6),
        "z": ratio(z, 4),
        "level": level,
        "level_label": LEVEL_LABELS[level],
        # The engine owns the flag: forte and only forte, whatever the served column says.
        "investigator_trigger": level == FORTE,
        "in_table": level in (ATENCAO, FORTE),
        "in_text": level == FORTE,
        "reason": reason,
        "reason_code": code,
        "sources": [call.src(_month_end(month))],
    }


def compute_movement(lines: list[LineId], client: SiloClient, month: dt.date) -> dict[str, Any]:
    sec = Section()
    funds = [li for li in lines if li.kind == "fund" and li.cnpj]
    base = {
        "month": iso(month),
        "definition": DEFINITION,
        "class_note": CLASS_NOTE,
        "levels_note": LEVELS_NOTE,
        "note": NOT_FORECAST,
        "thresholds": {
            "atencao_abs_z": float(ATENCAO_Z),
            "forte_abs_z": float(FORTE_Z),
            "strictly_greater": True,
            "min_peers": MIN_PEERS,
            "winsorized_percentiles": [1, 99],
        },
    }
    na = _not_applicable(lines, {li.line_no for li in funds})
    if not funds:
        sec.status = STATUS_NOT_APPLICABLE
        sec.reason = "Nenhum fundo identificado para comparar com a classe."
        return {**sec.head(), **base, "counts": _counts([]), "investigator_trigger_line_nos": [], "lines": [],
                "not_applicable_lines": na}

    cnpjs = sorted({li.cnpj for li in funds if li.cnpj})
    found: dict[str, tuple[dict, Any]] = {}
    calls = []
    for i in range(0, len(cnpjs), CHUNK):
        res = call_tool(client, TOOL, {"p_cnpjs": cnpjs[i : i + CHUNK], "p_month": month.isoformat()}, sec.errors)
        calls.append(res)
        if res.ok:
            for r in res.rows or []:
                found[str(r.get("cnpj"))] = (r, res)
    failed = [c for c in calls if not c.ok]
    if failed and len(failed) == len(calls):
        sec.fail("portfolio_movement falhou (erro literal em errors); nenhum fundo pôde ser comparado com a classe.", code="consulta_falhou")
    elif failed:
        sec.degrade("portfolio_movement falhou para parte dos fundos (erro literal em errors).", code="consulta_falhou")

    out_lines: list[dict[str, Any]] = []
    for li in funds:
        hit = found.get(li.cnpj or "")
        if hit is None:
            reason, code = (
                ("consulta ao SILO falhou para este fundo.", "consulta_falhou")
                if failed
                else ("portfolio_movement não devolveu linha para este CNPJ.", "sem_linha_movimento")
            )
            out_lines.append(_unknown_line(li, month, reason, code))
            continue
        out_lines.append(_line(li, hit[0], hit[1], month, sec))

    counts = _counts(out_lines)
    if sec.status != "unknown" and counts[NOT_EVALUATED]:
        sec.degrade(
            f"{counts[NOT_EVALUATED]} de {len(out_lines)} fundo(s) não avaliados contra a classe (o motivo de cada um está na seção de sinais de risco).",
            code="fundos_nao_avaliados",
        )
    return {
        **sec.head(),
        **base,
        "counts": counts,
        "investigator_trigger_line_nos": [ln["line_no"] for ln in out_lines if ln["investigator_trigger"]],
        "lines": out_lines,
        "not_applicable_lines": na,
    }


def _counts(lines: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "funds": len(lines),
        NORMAL: sum(1 for ln in lines if ln["level"] == NORMAL),
        ATENCAO: sum(1 for ln in lines if ln["level"] == ATENCAO),
        FORTE: sum(1 for ln in lines if ln["level"] == FORTE),
        NOT_EVALUATED: sum(1 for ln in lines if ln["level"] == NOT_EVALUATED),
    }
