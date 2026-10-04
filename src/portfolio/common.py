"""Helpers shared by the blocks: sources, sections, number formatting.

Every number in the engine output carries a ``sources`` list. A source is
``{"tool", "call_id", "args", "data_date"}``; ``tool == "statement"`` means the
number came from the client's own statement (``args`` names the line).
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from src.portfolio.client import SiloClient, ToolError

STATUS_COMPLETE = "complete"
STATUS_PARTIAL = "partial"
STATUS_UNKNOWN = "unknown"
STATUS_NOT_APPLICABLE = "not_applicable"

UNCLASSIFIED = "sem classificação"

# Reason codes (engine 1.7). A section or a line that could not be evaluated carries one of these codes beside its
# free-text reason; the report prints only the fixed Portuguese text of the code (``REASON_TEXT``), never the engine's
# reason, which may name a tool or quote an error.
R_TOOL_FAILED = "consulta_falhou"
REASON_TEXT = {
    R_TOOL_FAILED: "uma consulta ao SILO falhou ou foi recusada; a parte afetada ficou sem avaliação",
    "linhas_nao_identificadas": "há linhas do extrato não identificadas (lista abaixo)",
    "sem_fundos": "nenhum fundo identificado na carteira",
    "sem_taxa_divulgada": "fundo(s) sem taxa de administração divulgada encontrada",
    "taxa_a_conferir": "taxa informada a conferir (0 ou acima de 5% a.a.), fora das somas",
    "fontes_divergem": "lâmina mais recente que o Extrato: fontes divergem, a conferir",
    "sem_carteira_cda": "fundo(s) sem carteira na CDA do mês",
    "linhas_sem_peso": "fundo(s) com linhas da CDA sem peso",
    "resposta_inconsistente": "resposta do SILO inconsistente para alguma linha; a linha não foi avaliada",
    "fundos_nao_avaliados": "fundo(s) não avaliados contra a classe",
    "limite_diffs": "diferenças de reapresentação buscadas só para os documentos mais recentes",
    "limite_tickers": "setor consultado só para os maiores tickers dentro dos fundos",
    "sem_credito_direto": "nenhum crédito direto na carteira",
    "sem_vencimento": "nenhuma linha com vencimento impresso no extrato",
    "sem_fonte_api": "o SILO ainda não serve esse dado por uma API pública",
    "gestor_sem_api": "concentração por gestor não avaliada: o SILO ainda não serve o CNPJ do gestor por uma API pública",
    "liquidez_sem_api": "liquidez dos fundos (prazo de resgate da lâmina) não avaliada: o SILO ainda não a serve por uma API pública",
    "sem_linha_taxa": "o SILO não devolveu linha de taxa para este fundo",
    "sem_linha_movimento": "o SILO não devolveu comparação com a classe para este fundo",
    # engine 1.8: the main risks and the report's charts
    "sem_emissor_impresso": "crédito direto sem nome de emissor impresso no extrato",
    "riscos_nao_avaliados": "há riscos não avaliados por falta de dado (lista em Principais riscos)",
    "sem_carteira_dos_fundos": "nenhum fundo da carteira tem carteira aberta na CDA: o diagrama do look-through não é desenhado",
    "sem_taxa_em_reais": "nenhum fundo tem taxa fixa em R$ por ano: o gráfico do custo em taxas não é desenhado",
    # identification, per line
    "cnpj_extrato": "CNPJ do extrato; nome não conferido",
    "sem_candidato": "nome e CNPJ sem correspondência nos dados do SILO",
    "ambiguo": "mais de um fundo plausível; a cota não desempatou",
    "credito_sem_fonte": "crédito direto (CRA, CRI, debênture): identificação por código ainda não implementada",
    "bancario_sem_fonte": "CDB, LCI ou LCA: o SILO não tem fonte para títulos de emissão bancária",
    "outro_sem_ticker": "tipo 'outro' sem ticker: o SILO não identifica pelo nome",
    "acao_sem_ticker": "ação sem ticker no campo código",
    "ticker_nao_encontrado": "ticker não encontrado nos dados do SILO",
    "tesouro_sem_vencimento": "título do Tesouro sem título e vencimento reconhecíveis",
    "sem_identificacao": "sem identificação",
}


class SiloUnavailable(Exception):
    """SILO did not answer (timeout, 5xx, network) even after the retry: a retryable failure, not a data gap.

    Carries no request text: the server answers 503 with a fixed code and the CLI exits non-zero.
    """

    code = "silo_unavailable"


def dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return None
    try:
        out = Decimal(str(value))
    except ArithmeticError:  # decimal.InvalidOperation: not a number at source, reported as None
        return None
    return out if out.is_finite() else None


def brl(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def ratio(value: Decimal | None, places: int = 8) -> float | None:
    if value is None:
        return None
    return float(value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def pct(part: Decimal, whole: Decimal) -> float | None:
    if whole == 0:
        return None
    return float((part / whole * 100).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def iso(d: dt.date | None) -> str | None:
    return d.isoformat() if d else None


def as_date(value: Any) -> dt.date | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    s = str(value)[:10]
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        return None


def month_start(d: dt.date) -> dt.date:
    return d.replace(day=1)


def add_months(d: dt.date, n: int) -> dt.date:
    y, m = divmod(d.month - 1 + n, 12)
    return dt.date(d.year + y, m + 1, 1)


def source(tool: str, call_id: int | None, args: dict | None, data_date: Any) -> dict[str, Any]:
    dd = data_date.isoformat() if isinstance(data_date, dt.date) else (str(data_date)[:10] if data_date else None)
    return {"tool": tool, "call_id": call_id, "args": args or {}, "data_date": dd}


def statement_source(line_no: int, data_posicao: dt.date) -> dict[str, Any]:
    return source("statement", None, {"line_no": line_no}, data_posicao)


@dataclass
class Call:
    """One tool call's outcome as a block sees it."""

    tool: str
    args: dict
    call_id: int | None
    rows: list[dict] | None
    error: str | None
    transient: bool = False  # the failure was the infrastructure's (timeout, 5xx, network): a retry may answer

    @property
    def ok(self) -> bool:
        return self.rows is not None

    def src(self, data_date: Any = None) -> dict[str, Any]:
        return source(self.tool, self.call_id, self.args, data_date)


def call_tool(client: SiloClient, tool: str, args: dict, errors: list[dict]) -> Call:
    """Call a tool; a failure is appended to ``errors`` verbatim and returned as ``rows=None``."""
    try:
        rows = client.call(tool, args)
        return Call(tool, args, client.last_call_id, rows, None)
    except ToolError as exc:
        errors.append({"call_id": client.last_call_id, "tool": tool, "args": args, "error": exc.verbatim,
                       "transient": exc.transient})
        return Call(tool, args, client.last_call_id, None, exc.verbatim, exc.transient)


@dataclass
class Section:
    """A report section: complete, partial, unknown (with reason) or not applicable."""

    status: str = STATUS_COMPLETE
    reason: str | None = None
    errors: list[dict] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)

    def head(self) -> dict[str, Any]:
        return {"status": self.status, "reason": self.reason, "errors": self.errors, "reason_codes": self.reason_codes}

    def code(self, code: str | None) -> None:
        if code and code not in self.reason_codes:
            self.reason_codes.append(code)

    def degrade(self, reason: str, code: str | None = None) -> None:
        """Mark partial (unless already unknown) and append the reason (and its code, engine 1.7)."""
        if self.status in (STATUS_COMPLETE, STATUS_NOT_APPLICABLE):
            self.status = STATUS_PARTIAL
        self.reason = reason if not self.reason else f"{self.reason} {reason}"
        self.code(code)

    def fail(self, reason: str, code: str | None = None) -> None:
        self.status = STATUS_UNKNOWN
        self.reason = reason
        self.code(code)


# B3's root is four letters OR digits (B3SA3, and ETFs such as B5P211, 5PRE11 and TD3511: 8 of the 187 tickers in
# the ETF registry on 2026-10-03), then 1 or 2 digits; at least one letter, so no number is read as a ticker.
_TICKER_RE = re.compile(r"^(?=[A-Z0-9]*[A-Z])[A-Z0-9]{4}\d{1,2}[A-Z]?$")


def is_ticker(code: str | None) -> bool:
    return bool(code) and bool(_TICKER_RE.match(code.strip().upper()))


def b3_issuer_code(isin: str | None) -> str | None:
    """ISIN characters 3 to 6 (1-based): B3's issuer code. Brazilian ISINs only."""
    if not isin or len(isin) != 12 or not isin.upper().startswith("BR"):
        return None
    return isin[2:6].upper()


def cnpj_root(cnpj: str | None) -> str | None:
    if not cnpj:
        return None
    d = re.sub(r"\D", "", str(cnpj))
    return d[:8] if len(d) == 14 else None
