"""Block 18 (engine 1.9): each fund's manager and redemption terms, from ``portfolio_fund_terms``.

One batch for every fund line with a CNPJ (identified by ``portfolio_resolve`` or by the statement's own CNPJ), on the
retry path of identification (``identify.call_halving``: a transient failure is retried once with the batch halved).
A final failure is not raised: identification already stands, so the manager concentration and the liquidity ladder
say "não avaliado" for the lines the call did not answer, with the verbatim error in their sections.

The values are as filed (the CVM Extrato or the lâmina, ``terms_source``): a NULL is "not filed", never zero, and a
day count is never converted between business days and calendar days.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from src.portfolio.client import SiloClient
from src.portfolio.identify import LineId, call_halving, rows_by_input

TOOL = "portfolio_fund_terms"
MAX_CNPJS = 200
TERM_FIELDS = (
    "gestor_id", "gestor_name", "admin_cnpj", "admin_name", "terms_source", "terms_dt_comptc",
    "qt_dia_conversao_cota", "qt_dia_pagto_resgate", "tp_dia_pagto_resgate", "qt_dia_resgate_cotas",
)


@dataclass
class FundTerms:
    """What ``portfolio_fund_terms`` said, per statement line."""

    requested: list[int] = field(default_factory=list)  # line numbers sent
    rows: dict[int, dict[str, Any]] = field(default_factory=dict)  # line_no -> the line's ``fund_terms`` block
    failed: dict[int, str] = field(default_factory=dict)  # line_no -> reason code (consulta_falhou, resposta_inconsistente)
    errors: list[dict] = field(default_factory=list)  # the verbatim error of each refused call

    @property
    def called(self) -> bool:
        return bool(self.requested)


def _digits(s: Any) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _args(group: list[LineId]) -> dict[str, Any]:
    return {"p_cnpjs": [li.cnpj for li in group]}


def fund_lines(lines: list[LineId]) -> list[LineId]:
    """The lines whose fund is known by CNPJ (``cnpj_extrato`` included): the ones the terms are asked for."""
    return [li for li in lines if li.kind == "fund" and li.cnpj]


def fetch_fund_terms(lines: list[LineId], client: SiloClient) -> FundTerms:
    out = FundTerms()
    group = fund_lines(lines)
    if not group:
        return out
    out.requested = [li.line_no for li in group]
    answered: list = []
    failed: list = []
    for i in range(0, len(group), MAX_CNPJS):  # the API refuses more than 200 CNPJs per call (22023)
        a, f = call_halving(client, TOOL, group[i : i + MAX_CNPJS], _args, out.errors)
        answered += a
        failed += f
    for grp, _res in failed:
        for li in grp:
            out.failed[li.line_no] = "consulta_falhou"
    for grp, res in answered:
        sent = _args(grp)["p_cnpjs"]
        # the echoed CNPJ is compared as digits: the API may print it with or without punctuation
        grouped, _ = rows_by_input(res, sent, "__none__")
        for idx, li in enumerate(grp, start=1):
            rows = grouped.get(idx) or []
            row = rows[0] if rows else None
            # the API returns one row per input CNPJ, so a missing row is an inconsistent answer, never "not filed"
            if row is None or (row.get("input_cnpj") is not None and _digits(row.get("input_cnpj")) != _digits(sent[idx - 1])):
                out.failed[li.line_no] = "resposta_inconsistente"
                continue
            out.rows[li.line_no] = terms_block(row, [res.src(li.position.data_posicao)])
    return out


def terms_block(row: dict | None, sources: list[dict]) -> dict[str, Any]:
    """A line's ``fund_terms``: the API's fields as served, ``answered`` false when no row came back for the CNPJ."""
    r = row or {}
    out: dict[str, Any] = {"answered": row is not None}
    for k in TERM_FIELDS:
        v = r.get(k)
        out[k] = str(v)[:10] if k == "terms_dt_comptc" and v else v
    out["tool_note"] = r.get("reason")
    out["sources"] = sources
    return out


def attach_to_identification(ident: dict[str, Any], terms: FundTerms) -> None:
    """``identification.lines[].fund_terms`` (engine 1.9): the block for a fund line asked for, else null."""
    for ln in ident.get("lines") or []:
        n = ln["line_no"]
        if n in terms.rows:
            ln["fund_terms"] = terms.rows[n]
        elif n in terms.failed:
            ln["fund_terms"] = {"answered": False, "reason_code": terms.failed[n], "sources": []}
        else:
            ln["fund_terms"] = None
