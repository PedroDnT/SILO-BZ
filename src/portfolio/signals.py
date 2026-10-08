"""Block 14: fund risk signals from the ``screen_*`` tools.

The screens take no CNPJ: each is fetched once with its DEFAULT thresholds and
matched to the statement's funds client-side. A screen hit is a signal, not a
verdict (each row carries ``screen`` and ``params``).

* ``screen_dormant_funds`` refuses with defaults (8,218 rows on 2026-10-03), so
  it is called twice, pinned: ``p_dormancy='empty_shell'`` (every empty shell)
  and ``p_min_nav=1e9`` (parked funds above R$1bn only). A parked fund below
  R$1bn is NOT covered; the output says so.
* ``screen_delinquency_drivers`` refuses with defaults too (above 1000 rows on
  2026-10-05), so it is called once per worsening driver, pinned:
  ``consistent_worsening`` (304 rows) and ``value_up_rate_masked`` (78). The
  ``improvement``, ``stable`` and ``denominator_only`` drivers are not a risk
  signal and are not asked.
* ``screen_overdue_securit`` (rows keyed by securitizer) and
  ``screen_dormant_trend`` (an industry series) carry no fund CNPJ and are not
  matched.
* A refused screen makes that screen ``unknown`` with the verbatim error; the
  others still run.
* The abnormal-movement rule (movimento incomum, owner's decisions of 2026-10-03) lives in
  ``src/portfolio/movement.py``; this block only points at it.
"""

from __future__ import annotations

from typing import Any

from src.portfolio.client import SiloClient
from src.portfolio.common import STATUS_NOT_APPLICABLE, Section, call_tool
from src.portfolio.identify import LineId

DELINQUENCY_DRIVERS = ("consistent_worsening", "value_up_rate_masked")

CNPJ_SCREENS = (
    "screen_zombie_growth",
    "screen_captive_vehicles",
    "screen_evergreen_aging",
    "screen_restatements",
    "screen_late_filers",
    "screen_silent_filers",
)
NOT_MATCHABLE = {
    "screen_overdue_securit": "linhas por securitizadora (securitizer_cnpj), sem CNPJ de fundo",
    "screen_dormant_trend": "série do setor (um ponto por período), sem CNPJ de fundo",
}
DORMANT_CALLS = (
    ("empty_shell", {"p_dormancy": "empty_shell"}),
    ("parked_nav_ge_1bn", {"p_min_nav": 1000000000}),
)
DORMANT_COVERAGE_NOTE = (
    "Cobertura da tela de fundos dormentes: todas as cascas vazias e os fundos parados (sem atividade) com "
    "PL de última competência igual ou acima de R$ 1 bilhão. Um fundo parado abaixo disso NÃO foi avaliado "
    "(a chamada sem filtro é recusada pelo SILO por exceder uma página de 1.000 linhas)."
)
ABNORMAL_MOVEMENT_NOTE = (
    "Movimento incomum: avaliado na seção movement (retorno mensal da cota contra a classe ANBIMA do fundo), "
    "não neste bloco."
)
SIGNAL_NOTE = "Sinal, não veredito: o fundo cruzou um limiar declarado em informes públicos."


def compute_signals(lines: list[LineId], client: SiloClient) -> dict[str, Any]:
    sec = Section()
    funds = [li for li in lines if li.kind == "fund" and li.cnpj]
    if not funds:
        sec.status = STATUS_NOT_APPLICABLE
        sec.reason = "Nenhum fundo identificado."
        return {**sec.head(), "screens": [], "lines": [], "abnormal_movement": ABNORMAL_MOVEMENT_NOTE}
    cnpjs = {li.cnpj for li in funds}

    screens: list[dict[str, Any]] = []
    hits: dict[str, list[dict[str, Any]]] = {c: [] for c in cnpjs}
    failed: list[str] = []

    def run(label: str, tool: str, args: dict) -> None:
        r = call_tool(client, tool, args, sec.errors)
        entry: dict[str, Any] = {"screen": label, "tool": tool, "args": args}
        if not r.ok:
            entry.update(status="unknown", reason="screen recusado ou falhou (erro literal em errors)", reason_code="consulta_falhou",
                         n_rows=None)
            failed.append(label)
        else:
            entry.update(status="complete", reason=None, n_rows=len(r.rows or []))
            for row in r.rows or []:
                c = str(row.get("cnpj") or "")
                if c in hits:
                    hits[c].append(
                        {"screen": label, "tool": tool, "row": row, "note": SIGNAL_NOTE, "sources": [r.src()]}
                    )
        screens.append(entry)

    for tool in CNPJ_SCREENS:
        run(tool, tool, {})
    for driver in DELINQUENCY_DRIVERS:
        run(f"screen_delinquency_drivers[{driver}]", "screen_delinquency_drivers", {"p_driver": driver})
    for label, extra in DORMANT_CALLS:
        run(f"screen_dormant_funds[{label}]", "screen_dormant_funds", {"p_lookback_months": 3, **extra})
    for tool, why in NOT_MATCHABLE.items():
        screens.append({"screen": tool, "tool": tool, "args": None, "status": "not_applicable", "reason": why, "n_rows": None})

    if failed:
        sec.degrade(f"{len(failed)} screen(s) falharam e ficaram desconhecidos: {', '.join(failed)}.", code="consulta_falhou")
    out_lines = []
    for li in funds:
        h = hits[li.cnpj]
        out_lines.append(
            {
                "line_no": li.line_no,
                "cnpj": li.cnpj,
                "n_signals": len(h),
                "signals": h,
                "no_signal_note": None
                if h
                else "Nenhum dos screens avaliados trouxe este fundo (ausência de sinal não é atestado de saúde).",
                "unknown_screens": list(failed),
            }
        )
    return {
        **sec.head(),
        "screens": screens,
        "dormant_coverage_note": DORMANT_COVERAGE_NOTE,
        "abnormal_movement": ABNORMAL_MOVEMENT_NOTE,
        "lines": out_lines,
    }
