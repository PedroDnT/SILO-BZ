"""Block 1: identify every statement line.

Input: a masked ``Statement`` and a ``SiloClient``. Output: the
``identification`` section and one ``LineId`` per line for the other blocks.

* Funds (``fundo``, ``FIDC``, ``FII``, ``ETF``): ``portfolio_resolve`` (name history + CNPJ + quota
  tie-break), split (engine 1.7): the lines with a CNPJ on the statement in one call, the others in
  chunks of ``RESOLVE_CHUNK``; a transient failure (timeout, 5xx, network) is retried once with the
  chunk halved, and a failure costs only its own lines. A line with a CNPJ on the statement that
  resolve does not return (error or no candidate) is identified by that CNPJ, ``match_kind =
  "cnpj_extrato"``, name not checked. A line without one that still fails for an infrastructure
  reason raises ``SiloUnavailable``: no document. An ETF line whose ``codigo`` is a ticker skips
  resolve and goes the ticker way. The quota is sent only for
  ``fundo`` and ``FIDC``: a listed FII/ETF's market price is not its NAV quota.
* Tickers (``ação``, and ``FII``/``ETF`` whose ``codigo`` is a ticker): ``lookup``
  (exact id match only) and ``quote_latest`` (a reference quote, never used to
  revalue the line). For ``ação`` lines ``company_financials`` gives the
  issuer's CNPJ and CVM setor (``lookup`` returns ``cnpj = null`` for tickers).
* ETFs by ticker (engine 1.5): a ticker line typed ``ETF``, or ``outro`` and not a share, with no
  fund CNPJ yet, is sent to ``portfolio_resolve`` by its ticker; only a ``match_kind = "etf_ticker"``
  row (the ticker in SILO's curated ETF registry) is accepted. It gives the ETF's CNPJ for the fee
  block only (``etf_cnpj``): the line stays a ticker for look-through, movement and sector.
* Tesouro: title and maturity parsed from ``codigo``; SILO has no price series,
  so the value is the statement's, labelled.
* Direct credit by its registry code (engine 1.9): the CRA, CRI and debênture lines that print a ``codigo`` go in
  one ``portfolio_instruments`` call (the code as read, no prefix added: the API normalises it), on the same
  retry path as ``portfolio_resolve``. A CRA or CRI is the ``securit_cetip`` row of that exact code, and of its series
  the one whose ``data_vencimento`` equals the statement's maturity; else the only series, else the lowest
  ``numero_serie``, flagged ``vencimento_diverge`` with both dates. A debênture is the ``cda_ticker`` row (CDA block 4).
  Never a fuzzy match; an OCR code not checked (``codigo_conferido`` false) is sent as read. The printed issuer
  stays as printed. A code SILO does not know stays unknown (``credito_sem_registro``).
* Everything else: unknown, with the reason.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from src.portfolio.client import SiloClient
from src.portfolio.common import (
    R_TOOL_FAILED,
    REASON_TEXT,
    STATUS_COMPLETE,
    STATUS_NOT_APPLICABLE,
    Call,
    Section,
    SiloUnavailable,
    as_date,
    b3_issuer_code,
    brl,
    call_tool,
    dec,
    is_ticker,
    iso,
    ratio,
    statement_source,
)
from src.portfolio.statement import Position, Statement, codigo_cnpj

FUND_TIPOS = ("fundo", "FIDC", "FII", "ETF", "FIP")
RESOLVE_CHUNK = 3  # lines without a CNPJ per portfolio_resolve call: the fuzzy name path is the slow one (57014, 2026-10-04)
CNPJ_EXTRATO_REASON = "CNPJ do extrato; nome não conferido."
TICKER_TIPOS = ("ação", "FII", "ETF")
QUOTA_TIPOS = ("fundo", "FIDC")

# Tesouro title as printed (accent-free, upper) -> title family.
TESOURO_TITLES = {
    "LFT": "LFT",
    "TESOURO SELIC": "LFT",
    "LTN": "LTN",
    "TESOURO PREFIXADO": "LTN",
    "NTN-F": "NTN-F",
    "NTNF": "NTN-F",
    "TESOURO PREFIXADO COM JUROS SEMESTRAIS": "NTN-F",
    "NTN-B": "NTN-B",
    "NTNB": "NTN-B",
    "TESOURO IPCA+ COM JUROS SEMESTRAIS": "NTN-B",
    "NTN-B PRINCIPAL": "NTN-B PRINCIPAL",
    "NTNB PRINCIPAL": "NTN-B PRINCIPAL",
    "TESOURO IPCA+": "NTN-B PRINCIPAL",
    "NTN-B1": "NTN-B1",
    "TESOURO RENDA+": "NTN-B1",
    "TESOURO EDUCA+": "NTN-B1",
    "NTN-C": "NTN-C",
    "TESOURO IGPM+ COM JUROS SEMESTRAIS": "NTN-C",
    "NTN-I": "NTN-I",
}
# Title family -> CDA block 1 tp_titpub (as filed; measured 2026-10-03 on 2026-05).
TESOURO_TP_TITPUB = {
    "LFT": "LETRAS FINANCEIRAS DO TESOURO",
    "LTN": "LETRAS DO TESOURO NACIONAL",
    "NTN-F": "NOTAS DO TESOURO NACIONAL - SERIE F",
    "NTN-B": "NOTAS DO TESOURO NACIONAL SERIE B",
    "NTN-B PRINCIPAL": "NOTAS DO TESOURO NACIONAL SERIE B",
    "NTN-B1": "NOTAS DO TESOURO NACIONAL SERIE B",
    "NTN-C": "NOTAS DO TESOURO NACIONAL SERIE C",
    "NTN-I": "NOTAS DO TESOURO NACIONAL SERIE I",
}
_TESOURO_RE = re.compile(r"^(?P<title>.+?)\s+(?P<mat>\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|\d{4})$")

UNSUPPORTED_REASON = {
    "CDB": "O SILO não tem fonte para CDB (bloco 5 da CDA e registros de emissão bancária não ingeridos).",
    "LCI": "O SILO não tem fonte para LCI.",
    "LCA": "O SILO não tem fonte para LCA.",
    "debênture": "Debênture detida diretamente sem código de registro no extrato: o SILO identifica debêntures só pelo código.",
    "CRI": "CRI detido diretamente sem código de registro no extrato: o SILO identifica CRI só pelo código.",
    "CRA": "CRA detido diretamente sem código de registro no extrato: o SILO identifica CRA só pelo código.",
    "outro": "Tipo 'outro' sem ticker: o SILO não identifica pelo nome nem pelo código do registro.",
}
UNSUPPORTED_CODE = {
    "CDB": "bancario_sem_fonte", "LCI": "bancario_sem_fonte", "LCA": "bancario_sem_fonte",
    "debênture": "credito_sem_codigo", "CRI": "credito_sem_codigo", "CRA": "credito_sem_codigo", "outro": "outro_sem_ticker",
}
# engine 1.9: the direct credit SILO identifies by its registry code (portfolio_instruments), and the match each accepts
INSTRUMENT_TIPOS = ("CRA", "CRI", "debênture")
INSTRUMENT_MATCH_KIND = {"CRA": "securit_cetip", "CRI": "securit_cetip", "debênture": "cda_ticker"}
ADIMPLENTE = "adimplente"
CREDIT_TIPOS = ("CRI", "CRA", "CDB", "LCI", "LCA", "debênture", "outro")


@dataclass
class LineId:
    """What block 1 established about one line; read by the other blocks."""

    position: Position
    status: str = "unknown"  # identified | ambiguous | unknown
    reason: str | None = None
    reason_code: str | None = None  # engine 1.7: the fixed code of an unidentified line (common.REASON_TEXT)
    kind: str | None = None  # fund | ticker | tesouro
    cnpj: str | None = None
    name: str | None = None
    entity_type: str | None = None
    ticker: str | None = None
    isin: str | None = None
    asset_class: str | None = None
    issuer_cnpj: str | None = None
    issuer_setor: str | None = None
    issuer_source: dict | None = None
    tesouro_title: str | None = None
    tesouro_maturity: str | None = None
    tesouro_tp_titpub: str | None = None
    etf_cnpj: str | None = None  # engine 1.5: the ETF's CNPJ from the ETF registry, read by the fee block only
    issuer_code: str | None = None  # engine 1.9: a debênture's B3 issuer code (ISIN characters 3 to 6), from the API
    credit: dict[str, Any] | None = None  # engine 1.9: the credit_match block of a CRA, CRI or debênture line
    statement_facts: dict[str, Any] = field(default_factory=dict)
    findings: list[dict] = field(default_factory=list)

    @property
    def line_no(self) -> int:
        return self.position.line_no


def _norm(s: str | None) -> str:
    s = s or ""
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().upper()


def parse_tesouro(codigo: str | None) -> tuple[str, str] | None:
    """(title family, maturity ISO date or year) from a ``codigo`` like ``NTN-B 2035-05-15``."""
    if not codigo:
        return None
    m = _TESOURO_RE.match(codigo.strip())
    if not m:
        return None
    family = TESOURO_TITLES.get(_norm(m.group("title")))
    if not family:
        return None
    mat = m.group("mat")
    if "/" in mat:
        d, mo, y = mat.split("/")
        mat = f"{y}-{mo}-{d}"
    return family, mat


def identify(stmt: Statement, client: SiloClient) -> tuple[dict[str, Any], list[LineId]]:
    sec = Section()
    lines = [LineId(position=p) for p in stmt.positions]
    by_no = {li.line_no: li for li in lines}
    resolve_out: dict[int, dict[str, Any]] = {}
    ticker_out: dict[int, dict[str, Any]] = {}

    # --- Funds: portfolio_resolve, split (engine 1.7). ------------------------------
    # The lines with a CNPJ on the statement go in one call (an exact key, fast); the others, which take the fuzzy
    # name path, in chunks of RESOLVE_CHUNK, so a slow or failed call costs only its own lines. An ETF line whose
    # codigo is a ticker skips this call: the ticker path below (lookup, then the ETF registry) identifies it.
    fund_lines = [li for li in lines if li.position.tipo in FUND_TIPOS and not _etf_by_ticker(li.position)]
    with_cnpj = [li for li in fund_lines if codigo_cnpj(li.position.codigo)]
    without = [li for li in fund_lines if not codigo_cnpj(li.position.codigo)]
    groups = ([with_cnpj] if with_cnpj else []) + [without[i : i + RESOLVE_CHUNK] for i in range(0, len(without), RESOLVE_CHUNK)]
    infra_failed: list[LineId] = []
    for group in groups:
        answered, failed = _resolve(client, sec, group)
        for grp, res in answered:
            grouped: dict[int, list[dict]] = {}
            for row in res.rows or []:
                try:
                    k = int(row.get("line_no"))
                except (TypeError, ValueError):
                    continue
                grouped.setdefault(k, []).append(row)
            # line_no in the answer is the 1-based index into THIS call's p_names
            for idx, li in enumerate(grp, start=1):
                cands = sorted(grouped.get(idx, []), key=lambda r: (r.get("rank") is None, r.get("rank") or 0))
                resolve_out[li.line_no] = _apply_resolve(li, cands, res.src(li.position.data_posicao))
        for grp, res in failed:
            unresolved = 0
            for li in grp:
                if codigo_cnpj(li.position.codigo):
                    resolve_out[li.line_no] = _from_statement_cnpj(li, {"candidates": [], "sources": []})
                    continue
                unresolved += 1
                li.reason = "Resolução de fundos indisponível: portfolio_resolve falhou (erro literal em errors)."
                li.reason_code = R_TOOL_FAILED
                if res.transient:
                    infra_failed.append(li)
            if unresolved:
                sec.degrade("portfolio_resolve falhou para parte das linhas de fundo; elas ficaram desconhecidas.", code=R_TOOL_FAILED)
    if infra_failed:
        # SILO did not answer even after the retry: a retryable failure, not a data gap. No document is produced.
        raise SiloUnavailable()

    # --- Tickers: lookup + quote_latest (+ company_financials for shares). ---------
    for li in lines:
        p = li.position
        code = (p.codigo or "").strip().upper()
        if p.tipo == "outro" and is_ticker(code):
            pass  # the statement gave a ticker and no type: the lookup says what it is
        elif p.tipo not in TICKER_TIPOS:
            continue
        if not is_ticker(code):
            if p.tipo == "ação":
                li.status, li.reason = "unknown", "Ação sem ticker no campo código: o SILO não identifica ações pelo nome."
                li.reason_code = "acao_sem_ticker"
            continue
        ticker_out[li.line_no] = _identify_ticker(li, code, client, sec, stmt.position_date)

    # --- ETFs by ticker: the CNPJ for the fee block (engine 1.5). -------------------
    etf_out = _identify_etfs(lines, client, sec, stmt.position_date, resolve_out)

    # --- Direct credit by registry code: portfolio_instruments (engine 1.9). --------
    credit_out = _identify_credit(lines, client, sec)

    # --- Tesouro and unsupported types. ---------------------------------------------
    for li in lines:
        p = li.position
        li.statement_facts = _statement_facts(p)
        if p.tipo == "caixa":
            li.status, li.kind, li.name = "identified", "caixa", "Conta corrente"
            li.reason = "Saldo em conta corrente lido do extrato; sem identificação a fazer."
            continue
        if p.tipo == "tesouro":
            parsed = parse_tesouro(p.codigo)
            if not parsed:
                title = TESOURO_TITLES.get(_norm(p.codigo or ""))
                if title:
                    # the statement prints the title but not the maturity: exposure by title, line stays unidentified
                    li.kind, li.tesouro_title = "tesouro", title
                    li.tesouro_tp_titpub = TESOURO_TP_TITPUB.get(title)
                li.status = "unknown"
                li.reason = (
                    "Título do Tesouro sem título e vencimento reconhecíveis no campo código "
                    "(formato: 'NTN-B 2035-05-15')."
                )
                li.reason_code = "tesouro_sem_vencimento"
                continue
            fam, mat = parsed
            li.status, li.kind = "identified", "tesouro"
            li.tesouro_title, li.tesouro_maturity = fam, mat
            li.tesouro_tp_titpub = TESOURO_TP_TITPUB.get(fam)
            li.name = f"{fam} {mat}"
            li.reason = "Identificado por título e vencimento; o SILO não tem série de preços do Tesouro."
        elif p.tipo in UNSUPPORTED_REASON and li.status != "identified" and li.line_no not in credit_out:
            li.status, li.reason = "unknown", UNSUPPORTED_REASON[p.tipo]
            li.reason_code = UNSUPPORTED_CODE[p.tipo]
            if p.tipo in CREDIT_TIPOS and p.codigo:
                li.reason += f" Código do registro lido do extrato: {p.codigo}."

    out_lines = []
    for li in lines:
        p = li.position
        if li.status == "unknown" and not li.reason:
            li.reason = "Sem identificação."
        if li.status == "identified" and li.reason_code != "cnpj_extrato":
            li.reason_code = None
        elif li.status != "identified" and not li.reason_code:
            li.reason_code = "sem_identificacao"
        out_lines.append(
            {
                "line_no": li.line_no,
                "linha_extrato": p.linha_extrato,
                "tipo": p.tipo,
                "codigo": p.codigo,
                "status": li.status,
                "reason": li.reason,
                "reason_code": li.reason_code,
                "identity": {
                    "kind": li.kind,
                    "cnpj": li.cnpj,
                    "name": li.name,
                    "entity_type": li.entity_type,
                    "ticker": li.ticker,
                    "isin": li.isin,
                    "asset_class": li.asset_class,
                    "issuer_cnpj": li.issuer_cnpj,
                    "tesouro_title": li.tesouro_title,
                    "tesouro_maturity": li.tesouro_maturity,
                    "etf_cnpj": li.etf_cnpj,
                    "issuer_code": li.issuer_code,
                },
                "statement_facts": li.statement_facts,
                "fund_match": resolve_out.get(li.line_no),
                "ticker_match": ticker_out.get(li.line_no),
                "etf_match": etf_out.get(li.line_no),
                "credit_match": credit_out.get(li.line_no),
                "valuation": {
                    "value_brl": brl(p.valor),
                    "basis": "statement",
                    "note": "Valor do extrato; o SILO não reavalia a posição.",
                    "sources": [statement_source(p.line_no, p.data_posicao)],
                },
                "findings": li.findings,
            }
        )
    counts = {s: sum(1 for li in lines if li.status == s) for s in ("identified", "ambiguous", "unknown")}
    if counts["identified"] < len(lines):
        if sec.status == STATUS_COMPLETE:
            sec.status = "partial"
            sec.reason = f"{counts['ambiguous']} linha(s) ambígua(s) e {counts['unknown']} desconhecida(s)."
        sec.code("linhas_nao_identificadas")
    if not lines:
        sec.status = STATUS_NOT_APPLICABLE
    return {**sec.head(), "counts": counts, "lines": out_lines, "unknown_groups": _unknown_groups(lines),
            "cnpj_extrato_line_nos": [li.line_no for li in lines if li.reason_code == "cnpj_extrato"],
            "same_identity_line_groups": _same_identity(lines)}, lines


def _same_identity(lines: list[LineId]) -> list[dict[str, Any]]:
    """Engine 1.7: lines the statement printed apart (different names, no common code) that identify as the same
    fund or ticker. They are one position held through two lines, not two holdings: the report never calls their
    overlap diversification or a finding."""
    by: dict[tuple[str, str], list[int]] = {}
    for li in lines:
        if li.status != "identified":
            continue
        if li.kind == "fund" and li.cnpj:
            by.setdefault(("cnpj", li.cnpj), []).append(li.line_no)
        elif li.kind == "ticker" and li.ticker:
            by.setdefault(("ticker", li.ticker), []).append(li.line_no)
    return [{"kind": k[0], "key": k[1], "line_nos": v} for k, v in by.items() if len(v) > 1]


def _unknown_groups(lines: list[LineId]) -> list[dict[str, Any]]:
    """Engine 1.7: the lines that are not identified, grouped by reason code, with their statement value."""
    total = sum((li.position.valor for li in lines), Decimal("0"))
    groups: dict[str, list[LineId]] = {}
    for li in lines:
        if li.status != "identified":
            groups.setdefault(li.reason_code or "sem_identificacao", []).append(li)
    out = []
    for code, lis in groups.items():
        v = sum((li.position.valor for li in lis), Decimal("0"))
        out.append({
            "reason_code": code,
            "line_nos": [li.line_no for li in lis],
            "n_lines": len(lis),
            "value_brl": brl(v),
            "portfolio_pct": float(round(v / total * 100, 4)) if total else None,
        })
    return sorted(out, key=lambda g: -(g["value_brl"] or 0))


def _etf_by_ticker(p: Position) -> bool:
    return p.tipo == "ETF" and is_ticker((p.codigo or "").strip().upper())


def _resolve_args(group: list[LineId]) -> dict[str, Any]:
    return {
        "p_names": [li.position.linha_extrato for li in group],
        "p_cnpjs": [codigo_cnpj(li.position.codigo) for li in group],
        "p_quotas": [
            float(li.position.preco_unitario)
            if li.position.tipo in QUOTA_TIPOS and li.position.preco_unitario is not None
            else None
            for li in group
        ],
        "p_quota_dates": [li.position.data_posicao.isoformat() for li in group],
    }


def _resolve(client: SiloClient, sec: Section, group: list[LineId]) -> tuple[list[tuple[list[LineId], Call]], list[tuple[list[LineId], Call]]]:
    """One portfolio_resolve call for ``group``: ``(answered, failed)`` as (lines, call) pairs."""
    return call_halving(client, "portfolio_resolve", group, _resolve_args, sec.errors)


def call_halving(client: SiloClient, tool: str, group: list[Any], args_of, errors: list[dict]) -> tuple[list[tuple[list[Any], Call]], list[tuple[list[Any], Call]]]:
    """One ``tool`` call for ``group`` (args from ``args_of(group)``): ``(answered, failed)`` as (items, call) pairs.

    A transient failure (timeout, 5xx, network) is retried once with the chunk halved (a single item is retried as
    is); a refusal or any other error is not retried. A failure costs only the items of the call that failed.
    """
    res = call_tool(client, tool, args_of(group), errors)
    if res.ok:
        return [(group, res)], []
    if not res.transient:
        return [], [(group, res)]
    half = len(group) // 2
    parts = [group[:half], group[half:]] if half else [group]
    answered: list[tuple[list[Any], Call]] = []
    failed: list[tuple[list[Any], Call]] = []
    for part in parts:
        r = call_tool(client, tool, args_of(part), errors)
        (answered if r.ok else failed).append((part, r))
    return answered, failed


def rows_by_input(res: Call, sent: list[str], code_key: str) -> tuple[dict[int, list[dict]], set[int]]:
    """The rows of one call grouped by the 1-based index of the input they answer (``line_no`` is the index into the
    call's own input array), and the indexes whose echoed input (``code_key``) is not what was sent there."""
    grouped: dict[int, list[dict]] = {}
    inconsistent: set[int] = set()
    for row in res.rows or []:
        try:
            k = int(row.get("line_no"))
        except (TypeError, ValueError):
            continue
        if not 1 <= k <= len(sent):
            continue
        echoed = row.get(code_key)
        if echoed is not None and str(echoed).strip() != str(sent[k - 1]).strip():
            inconsistent.add(k)
            continue
        grouped.setdefault(k, []).append(row)
    return grouped, inconsistent


def _serie_key(r: dict) -> tuple:
    n = str(r.get("numero_serie") if r.get("numero_serie") is not None else "")
    return (0, int(n), n) if n.strip().isdigit() else (1, 0, n)


def _credit_args(group: list[LineId]) -> dict[str, Any]:
    return {"p_codes": [str(li.position.codigo).strip() for li in group]}


def _identify_credit(lines: list[LineId], client: SiloClient, sec: Section) -> dict[int, dict[str, Any]]:
    """Engine 1.9: CRA, CRI and debênture lines by their registry code, one ``portfolio_instruments`` batch."""
    out: dict[int, dict[str, Any]] = {}
    group = [li for li in lines if li.position.tipo in INSTRUMENT_TIPOS and str(li.position.codigo or "").strip()]
    if not group:
        return out
    answered, failed = call_halving(client, "portfolio_instruments", group, _credit_args, sec.errors)
    if any(res.transient for _, res in failed):
        # SILO did not answer even after the retry: a retryable failure, not a data gap. No document is produced.
        raise SiloUnavailable()
    for grp, res in failed:
        for li in grp:
            li.status, li.reason_code = "unknown", R_TOOL_FAILED
            li.reason = ("Identificação do crédito indisponível: portfolio_instruments falhou (erro literal em errors). "
                         f"Código do registro lido do extrato: {str(li.position.codigo).strip()}.")
            out[li.line_no] = _credit_block(li, None, [], [res.src(li.position.data_posicao)], R_TOOL_FAILED)
        sec.degrade("portfolio_instruments falhou para as linhas de crédito direto; elas ficaram desconhecidas.",
                    code=R_TOOL_FAILED)
    for grp, res in answered:
        sent = _credit_args(grp)["p_codes"]
        grouped, inconsistent = rows_by_input(res, sent, "input_code")
        for idx, li in enumerate(grp, start=1):
            src = [res.src(li.position.data_posicao)]
            if idx in inconsistent:
                li.status, li.reason_code = "unknown", "resposta_inconsistente"
                li.reason = "portfolio_instruments devolveu outro código para esta linha; a linha não foi avaliada."
                out[li.line_no] = _credit_block(li, None, [], src, "resposta_inconsistente")
                sec.degrade("Resposta inconsistente de portfolio_instruments para uma linha de crédito.", code="resposta_inconsistente")
                continue
            kind = INSTRUMENT_MATCH_KIND[li.position.tipo]
            cands = [r for r in grouped.get(idx, []) if r.get("match_kind") == kind]
            if not cands:
                # an OCR code that did not pass its check and matches nothing is a reading problem first, not a gap in
                # SILO (real statement, 2026-10-05: a debenture ticker read as a word): say so, never "sem registro"
                unchecked = li.position.codigo_conferido is False
                code = "codigo_nao_conferido" if unchecked else "credito_sem_registro"
                li.status, li.reason_code = "unknown", code
                li.reason = (f"{li.position.tipo} com código {sent[idx - 1]}: o código não foi encontrado nos dados do SILO "
                             f"({'registro de CRA e CRI da CVM' if kind == 'securit_cetip' else 'carteiras dos fundos, CDA bloco 4'})"
                             + ("; o código foi lido por OCR e não conferido." if unchecked else "."))
                flags = [{"code": "codigo_nao_conferido", "text": REASON_TEXT["codigo_nao_conferido"]}] if unchecked else None
                out[li.line_no] = _credit_block(li, None, [], src, code, flags)
                continue
            out[li.line_no] = _apply_credit(li, cands, src)
    return out


def _apply_credit(li: LineId, cands: list[dict], src: list[dict]) -> dict[str, Any]:
    p = li.position
    flags: list[dict[str, Any]] = []
    stmt_mat = iso(p.vencimento)
    if p.tipo in ("CRA", "CRI"):
        ordered = sorted(cands, key=_serie_key)
        same = [r for r in ordered if stmt_mat and str(r.get("data_vencimento") or "")[:10] == stmt_mat]
        chosen = same[0] if same else ordered[0]
        reg_mat = str(chosen.get("data_vencimento") or "")[:10] or None
        if not same and stmt_mat and reg_mat and reg_mat != stmt_mat:
            flags.append({"code": "vencimento_diverge", "text": REASON_TEXT["vencimento_diverge"],
                          "statement_vencimento": stmt_mat, "registry_vencimento": reg_mat})
        if not stmt_mat and len(ordered) > 1:
            flags.append({"code": "serie_sem_vencimento", "text": REASON_TEXT["serie_sem_vencimento"]})
        situacao = chosen.get("situacao")
        # a NULL situação is "not filed": it is never read as outside Adimplente
        if situacao is not None and str(situacao).strip().lower() != ADIMPLENTE:
            flags.append({"code": "situacao_fora_adimplente", "text": REASON_TEXT["situacao_fora_adimplente"],
                          "situacao": situacao})
    else:
        ordered = list(cands)
        chosen = ordered[0]
    if p.codigo_conferido is False:
        flags.append({"code": "codigo_nao_conferido", "text": REASON_TEXT["codigo_nao_conferido"]})
    li.status, li.kind, li.reason_code = "identified", "credito", None
    li.isin = chosen.get("cd_isin")
    if p.tipo == "debênture":
        # the B3 issuer code joins a debênture held directly to the same issuer inside the funds (look-through)
        li.issuer_code = chosen.get("issuer_code") or b3_issuer_code(li.isin)
        li.reason = f"Debênture identificada pelo código {chosen.get('code') or p.codigo} nas carteiras dos fundos (CDA bloco 4)."
    else:
        li.reason = (f"{p.tipo} identificado pelo código {chosen.get('code') or p.codigo} no registro da CVM"
                     + (f" (série {chosen.get('numero_serie')})." if chosen.get("numero_serie") is not None else "."))
    block = _credit_block(li, chosen, ordered, src, None, flags)
    li.credit = block
    return block


def _credit_block(li: LineId, row: dict | None, series: list[dict], src: list[dict], code: str | None,
                  flags: list[dict] | None = None) -> dict[str, Any]:
    """The ``credit_match`` block of one line: the API's fields as served (money with ``_brl``), the statement's own
    maturity, rate and price beside them, and the flags. Nothing is converted or corrected."""
    from src.portfolio.concentration import issuer_as_printed  # concentration imports this module

    p = li.position
    r = row or {}
    price = dec(p.preco_unitario) if p.preco_unitario is not None else None
    mark = dec(r.get("preco_marcacao_fundos"))
    gap = (price / mark - 1) * 100 if price is not None and mark else None
    return {
        "matched": row is not None,
        "reason_code": code,
        "reason": REASON_TEXT.get(code or "") if code else li.reason,
        "input_code": str(p.codigo or "").strip() or None,
        "code": r.get("code"),
        "match_kind": r.get("match_kind"),
        "instrument_type": r.get("instrument_type"),
        "cnpj_securit": r.get("cnpj_securit"),
        "numero_serie": r.get("numero_serie"),
        "classe": r.get("classe"),
        "data_vencimento": str(r["data_vencimento"])[:10] if r.get("data_vencimento") else None,
        "situacao": r.get("situacao"),
        "taxa_juros": r.get("taxa_juros"),
        "classificacao_risco_atual": r.get("classificacao_risco_atual"),
        "valor_total_integralizado_brl": brl(dec(r.get("valor_total_integralizado"))),
        "data_referencia": str(r["data_referencia"])[:10] if r.get("data_referencia") else None,
        "cd_isin": r.get("cd_isin"),
        "issuer_code": r.get("issuer_code"),
        "n_fundos": r.get("n_fundos"),
        "preco_marcacao_fundos_brl": ratio(mark, 6) if mark is not None else None,
        "cda_period": str(r["cda_period"])[:10] if r.get("cda_period") else None,
        "tool_note": r.get("reason"),
        "n_series": len(series),
        "series": [{"numero_serie": s.get("numero_serie"), "data_vencimento": str(s.get("data_vencimento") or "")[:10] or None}
                   for s in series] if len(series) > 1 else [],
        "statement": {
            "issuer_as_printed": issuer_as_printed(li),
            "vencimento": iso(p.vencimento),
            "taxa_texto": p.taxa_texto,
            "preco_brl": ratio(price, 6) if price is not None else None,
            "preco_implicito": p.preco_implicito,
            "data_posicao": iso(p.data_posicao),
        },
        # the statement's price against the funds' weighted mark: informative, different dates, never a price verdict
        "price_gap_pct": float(round(gap, 4)) if gap is not None else None,
        "price_gap_abs_pct": float(round(abs(gap), 4)) if gap is not None else None,
        "price_gap_label": "informativo, não é veredito de preço" if gap is not None else None,
        "flags": list(flags or []),
        "sources": src,
    }


def _from_statement_cnpj(li: LineId, out: dict[str, Any]) -> dict[str, Any]:
    """Engine 1.7: the CNPJ printed on the statement is an exact key, so it identifies the fund when
    portfolio_resolve did not (an error, or no candidate). The name is not checked and not filled in."""
    given = codigo_cnpj(li.position.codigo)
    li.status, li.kind, li.cnpj = "identified", "fund", given
    li.entity_type = {"FIDC": "fidc", "FII": "fii", "FIP": "fip"}.get(li.position.tipo)
    li.reason, li.reason_code = CNPJ_EXTRATO_REASON, "cnpj_extrato"
    out["chosen"] = {
        "rank": None, "cnpj": given, "name": None, "matched_name": None, "matched_period": None,
        "entity_type": li.entity_type, "match_kind": "cnpj_extrato", "similarity": None, "quota_on_date": None,
        "quota_rel_diff": None, "ambiguous": False, "reason": CNPJ_EXTRATO_REASON,
    }
    out["sources"] = [statement_source(li.line_no, li.position.data_posicao)]
    return out


def _apply_resolve(li: LineId, cands: list[dict], src: dict) -> dict[str, Any]:
    def cand(r: dict) -> dict[str, Any]:
        return {
            "rank": r.get("rank"),
            "cnpj": r.get("candidate_cnpj"),
            "name": r.get("candidate_name"),
            "matched_name": r.get("matched_name"),
            "matched_period": r.get("matched_period"),
            "entity_type": r.get("entity_type"),
            "match_kind": r.get("match_kind"),
            "similarity": ratio(dec(r.get("similarity")), 4),
            "quota_on_date": ratio(dec(r.get("quota_on_date"))),
            "quota_rel_diff": ratio(dec(r.get("quota_rel_diff"))),
            "ambiguous": r.get("ambiguous"),
            "reason": r.get("reason"),
        }

    out: dict[str, Any] = {
        "candidates": [cand(r) for r in cands],
        "quota_basis": "implícita (valor / quantidade do extrato)" if li.position.preco_implicito else "impressa no extrato",
        "sources": [src],
    }
    if not cands:
        if codigo_cnpj(li.position.codigo):
            return _from_statement_cnpj(li, out)
        li.status = "unknown"
        li.reason = "portfolio_resolve não encontrou candidato pelo nome (histórico) nem pelo CNPJ."
        li.reason_code = "sem_candidato"
        return out
    top = cands[0]
    out["tiebroken_by_quota"] = bool(
        len(cands) > 1
        and not top.get("ambiguous")
        and "quota" in str(top.get("reason") or "").lower()
        and (cands[1].get("quota_rel_diff") is None or (dec(cands[1].get("quota_rel_diff")) or 0) > (dec(top.get("quota_rel_diff")) or 0))
    )
    if top.get("ambiguous"):
        li.status = "ambiguous"
        li.reason = top.get("reason") or "Mais de um fundo plausível; a cota não desempata."
        li.reason_code = "ambiguo"
        return out
    if top.get("match_kind") == "etf_ticker":
        # engine 1.5: a line named by an ETF's bare ticker. The ETF's CNPJ is for the fee block only: an ETF files no
        # CDA (none of the registry's CNPJs in 2026, measured 2026-10-03), so the line stays a ticker, never a fund.
        code = str(li.position.linha_extrato or "").strip().upper()
        li.etf_cnpj = top.get("candidate_cnpj")
        li.status, li.kind, li.ticker = "identified", "ticker", code
        li.name = top.get("candidate_name")
        li.reason = f"ETF {code} identificado pelo ticker no registro de ETFs do SILO (cvm_etf_registry)."
        out["chosen"] = cand(top)
        return out
    li.status, li.kind = "identified", "fund"
    li.cnpj = top.get("candidate_cnpj")
    li.name = top.get("candidate_name")
    li.entity_type = top.get("entity_type")
    li.reason = top.get("reason")
    out["chosen"] = cand(top)
    matched = top.get("matched_name")
    # A rename is a finding only when the name led the identification: a line resolved by the CNPJ the statement
    # prints never depended on any name, and CVM 175 renamed almost every fund (FI to FIF, "RESPONSABILIDADE
    # LIMITADA"), so flagging it there is noise (real statement, 2026-10-05: five such findings, none useful).
    if matched and li.name and _norm(matched) != _norm(li.name) and top.get("match_kind") != "cnpj":
        li.findings.append(
            {
                "kind": "renamed",
                "text": (
                    f"O nome no extrato corresponde a um nome antigo do fundo (registrado em "
                    f"{top.get('matched_period')}); o nome atual é '{li.name}'."
                ),
                "matched_name": matched,
                "matched_period": top.get("matched_period"),
                "current_name": li.name,
                "sources": [src],
            }
        )
    given = codigo_cnpj(li.position.codigo)
    if given and li.cnpj and given != li.cnpj:
        li.findings.append(
            {
                "kind": "cnpj_conflict",
                "text": f"O CNPJ do extrato ({given}) difere do fundo resolvido ({li.cnpj}).",
                "sources": [src],
            }
        )
    return out


def _identify_etfs(
    lines: list[LineId], client: SiloClient, sec: Section, pos_date: dt.date, resolve_out: dict[int, dict[str, Any]]
) -> dict[int, dict[str, Any]]:
    """Ticker lines that may be ETFs: their CNPJ from SILO's ETF registry through portfolio_resolve (engine 1.5)."""
    out: dict[int, dict[str, Any]] = {}
    for li in lines:
        if li.etf_cnpj:  # named by its bare ticker: the first portfolio_resolve call already matched it
            fm = resolve_out.get(li.line_no) or {}
            chosen = fm.get("chosen") or {}
            out[li.line_no] = {"ticker": li.ticker, "cnpj": li.etf_cnpj, "name": chosen.get("name"), "match_kind": "etf_ticker",
                               "reason": chosen.get("reason"),
                               "use": "CNPJ do ETF usado só para a taxa; a linha continua identificada pelo ticker.",
                               "sources": fm.get("sources") or []}
    probe = []
    for li in lines:
        code = (li.position.codigo or "").strip().upper()
        if li.cnpj or li.etf_cnpj or not is_ticker(code):
            continue
        if li.position.tipo == "ETF" or (li.position.tipo == "outro" and li.asset_class != "equity"):
            probe.append((li, code))
    if not probe:
        return out
    res = call_tool(client, "portfolio_resolve", {"p_names": [code for _, code in probe]}, sec.errors)
    if not res.ok and res.transient:
        res = call_tool(client, "portfolio_resolve", {"p_names": [code for _, code in probe]}, sec.errors)  # one retry
    if not res.ok:
        if res.transient and any(li.status != "identified" for li, _ in probe):
            # a line the ETF registry was the last chance to identify: SILO did not answer, so no document
            raise SiloUnavailable()
        sec.degrade("portfolio_resolve falhou para os tickers que podem ser ETF; a taxa desses ETFs ficou desconhecida.",
                    code=R_TOOL_FAILED)
        return out
    by_line: dict[int, dict] = {}
    for row in res.rows or []:
        if row.get("match_kind") != "etf_ticker" or not row.get("candidate_cnpj"):
            continue  # only the ETF registry's exact ticker counts; a name match on a ticker is never used
        try:
            by_line.setdefault(int(row.get("line_no")), row)
        except (TypeError, ValueError):
            continue
    for idx, (li, code) in enumerate(probe, start=1):
        row = by_line.get(idx)
        if row is None:
            continue
        li.etf_cnpj = str(row["candidate_cnpj"])
        out[li.line_no] = {
            "ticker": code,
            "cnpj": li.etf_cnpj,
            "name": row.get("candidate_name"),
            "match_kind": "etf_ticker",
            "reason": row.get("reason"),
            "use": "CNPJ do ETF usado só para a taxa; a linha continua identificada pelo ticker.",
            "sources": [res.src(pos_date)],
        }
        if li.status != "identified":
            # a fixed income ETF is not in COTAHIST, so lookup does not find its ticker; the ETF registry does
            li.status, li.kind, li.ticker = "identified", "ticker", code
            li.reason_code = None
            li.name = li.name or row.get("candidate_name")
            li.reason = (f"ETF {code} identificado pelo ticker no registro de ETFs do SILO (cvm_etf_registry); "
                         "lookup não o encontrou (ETFs de renda fixa não estão no COTAHIST).")
    return out


def _identify_ticker(li: LineId, code: str, client: SiloClient, sec: Section, pos_date: dt.date) -> dict[str, Any]:
    out: dict[str, Any] = {"ticker": code}
    lk = call_tool(client, "lookup", {"p_query": code}, sec.errors)
    if not lk.ok:
        sec.degrade(f"lookup falhou para {code}.", code="consulta_falhou")
        if li.status != "identified":
            li.status, li.reason = "unknown", "lookup falhou (erro literal em errors)."
            li.reason_code = R_TOOL_FAILED
        return out
    exact = [r for r in lk.rows or [] if str(r.get("id", "")).upper() == code]
    out["lookup"] = {"rows": exact, "sources": [lk.src()]}
    if not exact:
        if li.status != "identified":
            li.status, li.reason = "unknown", f"Ticker {code} não encontrado no SILO (lookup sem correspondência exata)."
            li.reason_code = "ticker_nao_encontrado"
        return out
    row = exact[0]
    li.ticker = code
    li.isin = row.get("isin")
    li.asset_class = row.get("asset_class")
    if li.status != "identified" or li.kind is None:
        li.status, li.kind = "identified", "ticker"
        li.name = li.name or row.get("name")
        li.reason = None
    elif li.kind == "fund":
        li.reason = (li.reason + " " if li.reason else "") + f"Ticker {code} confirmado por lookup."

    q = call_tool(client, "quote_latest", {"p_ticker": code}, sec.errors)
    if q.ok and q.rows:
        qr = q.rows[0]
        out["reference_quote"] = {
            "close": ratio(dec(qr.get("close")), 6),
            "trade_date": qr.get("trade_date"),
            "label": "Cotação de referência; o valor da posição continua sendo o do extrato.",
            "sources": [q.src(qr.get("trade_date"))],
        }
    elif q.ok:
        out["reference_quote"] = None
    else:
        sec.degrade(f"quote_latest falhou para {code}.", code="consulta_falhou")

    if li.position.tipo == "ação" or li.asset_class == "equity":
        args = {"p_id": code, "p_from": (pos_date - dt.timedelta(days=548)).isoformat(), "p_to": pos_date.isoformat()}
        cf = call_tool(client, "company_financials", args, sec.errors)
        if cf.ok and cf.rows:
            latest = max(cf.rows, key=lambda r: str(r.get("ref_date") or ""))
            li.issuer_cnpj = latest.get("cnpj")
            li.issuer_setor = latest.get("setor")
            li.issuer_source = cf.src(latest.get("ref_date"))
            out["issuer"] = {
                "cnpj": li.issuer_cnpj,
                "company": latest.get("company"),
                "setor_cvm": li.issuer_setor,
                "sources": [li.issuer_source],
            }
        elif cf.ok:
            out["issuer"] = None
        else:
            sec.degrade(f"company_financials falhou para {code}; emissor e setor desconhecidos.", code="consulta_falhou")
    return out


def _statement_facts(p: Position) -> dict[str, Any]:
    """What the statement itself prints about the line, beyond name and value (all null for a spreadsheet)."""
    return {
        "vencimento": iso(p.vencimento),
        "taxa_texto": p.taxa_texto,
        "estrategia_corretora": p.estrategia_corretora,
        "classe_corretora": p.classe_corretora,
        "conta_ref": p.conta_ref,
        "preco_implicito": p.preco_implicito,
    }
