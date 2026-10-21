"""Parse ANBIMA's public debenture pages into stored rows (#1006).

Input is a ``PageCapture`` from ``src.fetchers.anbima_debenture_fetcher``: the
page text and its tables, header first. Columns are found by their header
label, never by position, and characteristics by their visible label. Values
are stored as published: a '-' or '--' is NULL, never a guess. The indicative
rate is ANBIMA's model value, not a trade.

``parse_remuneracao`` splits the published remuneration text (``IPCA + 6,57%``,
``114,65% DI``, ``Pré-Fixado 14,35%``) into an indexer and a rate. Text it does
not recognise keeps the published string and leaves both parts NULL.

A page whose layout changed (a required label or column is missing, a date does
not parse) raises ``AnbimaParseError``. The pipeline then keeps the raw text.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from src.parsers.validation import DataValidator

SOURCE = "anbima_data_debentures"
_VALIDATOR = DataValidator()


class AnbimaParseError(ValueError):
    """The page layout is not the one this parser knows."""


def _norm(label: str) -> str:
    s = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9%]+", " ", s.lower()).strip()


def _missing(value: Optional[str]) -> bool:
    return value is None or value.strip() in ("", "-", "--", "N/A")


def num(value: Optional[str]) -> Optional[Decimal]:
    """'R$ 1.036,781970' → 1036.781970; '6,5700 %' → 6.5700; '50%' → 50."""
    if _missing(value):
        return None
    s = re.sub(r"[R$%\s]|dias(?: corridos| uteis| úteis)?", "", value.strip())
    s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation as exc:
        raise AnbimaParseError(f"not a number: {value!r}") from exc


def day(value: Optional[str]) -> Optional[date]:
    if _missing(value):
        return None
    try:
        return datetime.strptime(value.strip(), "%d/%m/%Y").date()
    except ValueError as exc:
        raise AnbimaParseError(f"not a dd/mm/yyyy date: {value!r}") from exc


def cnpj(value: Optional[str]) -> Optional[str]:
    """Digits only. An invalid CNPJ raises: it is never stored as a guess."""
    if _missing(value):
        return None
    digits = re.sub(r"\D", "", value)
    ok, msg = _VALIDATOR.validate_field("cnpj", digits, "cnpj")
    if not ok:
        raise AnbimaParseError(f"invalid CNPJ {value!r}: {msg}")
    return digits


_REMUNERACAO = (
    # (pattern, form). The indexer is the published word, upper-cased.
    (re.compile(r"^(DI|IPCA|IGPM|IGP-M|INPC|TR|DOLAR|DÓLAR)\s*\+\s*([\d.,]+)\s*%$", re.I), "spread"),
    (re.compile(r"^([\d.,]+)\s*%\s*(DI)$", re.I), "percentual"),
    (re.compile(r"^(PR[ÉE]-?FIXADO)\s+([\d.,]+)\s*%$", re.I), "prefixado"),
)


def parse_remuneracao(text: Optional[str]) -> dict[str, Any]:
    out = {"remuneracao": None if _missing(text) else text.strip(),
           "indexador": None, "forma_remuneracao": None, "taxa_remuneracao_pct": None}
    if out["remuneracao"] is None:
        return out
    for pattern, form in _REMUNERACAO:
        m = pattern.match(out["remuneracao"])
        if not m:
            continue
        if form == "percentual":
            rate, index = m.group(1), m.group(2)
        else:
            index, rate = m.group(1), m.group(2)
        index = _norm(index).upper().replace(" ", "-")
        out.update(indexador={"PRE-FIXADO": "PRE", "PREFIXADO": "PRE", "IGP-M": "IGPM"}.get(index, index),
                   forma_remuneracao=form, taxa_remuneracao_pct=num(rate))
        return out
    return out


# ── characteristics ──────────────────────────────────────────────────────────
# Visible label → column. Labels repeat between the series and the issue
# blocks ("Quantidade em mercado na B3"), so each block is read on its own.
_SERIES = {
    "remuneracao": "remuneracao_text",
    "data de inicio da rentabilidade": "data_inicio_rentabilidade",
    "expressao do papel": "expressao_papel",
    "quantidade da serie na data de emissao": "quantidade_serie_emissao",
    "volume da serie na data de emissao": "volume_serie_emissao_brl",
    "vne valor nominal na emissao": "vne_brl",
    "vna valor nominal atual": "vna_brl",
    "quantidade em mercado na b3": "quantidade_mercado_b3",
    "estoque em mercado na b3": "estoque_mercado_b3_brl",
    "data da emissao": "data_emissao",
    "data de vencimento": "data_vencimento",
    "proxima repactuacao": "proxima_repactuacao",
    "resgate antecipado": "resgate_antecipado",
    "isin": "isin",
}
_ISSUE = {
    "empresa": "emissor",
    "setor": "setor",
    "cnpj": "emissor_cnpj",
    "volume da emissao": "volume_emissao_brl",
    "quantidade da emissao": "quantidade_emissao",
}
_AGENTS = {"coordenador lider": "coordenador_lider", "agente fiduciario": "agente_fiduciario",
           "banco mandatario": "banco_mandatario"}
_REQUIRED = ("remuneracao_text", "data_emissao", "data_vencimento", "emissor", "emissor_cnpj")
_DATES = {"data_inicio_rentabilidade", "data_emissao", "data_vencimento", "proxima_repactuacao"}
_NUMS = {"quantidade_serie_emissao", "volume_serie_emissao_brl", "vne_brl", "vna_brl",
         "quantidade_mercado_b3", "estoque_mercado_b3_brl", "volume_emissao_brl",
         "quantidade_emissao"}
_SECTIONS = {"CONDIÇÕES GERAIS DA SÉRIE", "INCENTIVO", "EMISSOR", "CONDIÇÕES GERAIS DA EMISSÃO",
             "AGENTES CONTRATADOS", "GARANTIAS"}
_CNPJ_LINE = re.compile(r"^\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}$")


def _block(lines: list[str], start: str) -> list[str]:
    """Lines under an upper-case section heading, up to the next heading."""
    try:
        i = lines.index(start)
    except ValueError:
        return []
    j = next((k for k in range(i + 1, len(lines)) if lines[k] in _SECTIONS), len(lines))
    return lines[i + 1:j]


def _pairs(block: list[str], labels: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for i, line in enumerate(block[:-1]):
        col = labels.get(_norm(line))
        if col and col not in out:
            out[col] = block[i + 1].strip()
    return out


def parse_caracteristicas(capture) -> dict[str, Any]:
    lines = [x.strip() for x in capture.text.splitlines() if x.strip()]
    raw = _pairs(_block(lines, "CONDIÇÕES GERAIS DA SÉRIE"), _SERIES)
    raw.update(_pairs(_block(lines, "EMISSOR"), _ISSUE))
    issue = _pairs(_block(lines, "CONDIÇÕES GERAIS DA EMISSÃO"), _ISSUE)
    raw.update({k: v for k, v in issue.items() if k not in raw})
    incentive = _pairs(_block(lines, "INCENTIVO"), {"lei 12 431": "lei_12431",
                                                     "artigo": "lei_12431_artigo"})
    agents_block = _block(lines, "AGENTES CONTRATADOS")
    guarantee = _pairs(_block(lines, "GARANTIAS"), {"garantia": "garantia"})
    missing = [c for c in _REQUIRED if _missing(raw.get(c))]
    if missing:
        raise AnbimaParseError(f"{capture.codigo}: characteristics without {missing}")

    row: dict[str, Any] = {"codigo": capture.codigo}
    for col in set(_SERIES.values()) | set(_ISSUE.values()):
        value = raw.get(col)
        if col in _DATES:
            row[col] = day(value)
        elif col in _NUMS:
            row[col] = num(value)
        elif col == "emissor_cnpj":
            row[col] = cnpj(value)
        else:
            row[col] = None if _missing(value) else value
    rem = parse_remuneracao(row.pop("remuneracao_text"))
    row.update(rem)
    row["resgate_antecipado"] = {"Sim": True, "Não": False}.get(row["resgate_antecipado"] or "")
    row["lei_12431"] = {"Sim": True, "Não": False}.get(incentive.get("lei_12431", ""))
    art = incentive.get("lei_12431_artigo")
    row["lei_12431_artigo"] = None if _missing(art) else art
    for col in _AGENTS.values():
        row[col] = row[col + "_cnpj"] = None
    for i, line in enumerate(agents_block):
        col = _AGENTS.get(_norm(line))
        if col and i + 1 < len(agents_block):
            row[col] = agents_block[i + 1]
            if i + 2 < len(agents_block) and _CNPJ_LINE.match(agents_block[i + 2]):
                row[col + "_cnpj"] = cnpj(agents_block[i + 2])
    row["garantia"] = None if _missing(guarantee.get("garantia")) else guarantee["garantia"]
    serie = next((x for x in lines if re.fullmatch(r"\d+ª Série", x)), None)
    emissao = next((x for x in lines if re.fullmatch(r"\d+ª Emissão", x)), None)
    row["serie"] = serie
    row["emissao"] = emissao
    return row


# ── tables ───────────────────────────────────────────────────────────────────
def _table(capture, must_have: str) -> Optional[dict]:
    for t in capture.tables:
        if any(must_have in _norm(h) for h in t["headers"]):
            return t
    return None


def _columns(table: dict, wanted: dict[str, str], codigo: str) -> dict[str, int]:
    headers = [_norm(h) for h in table["headers"]]
    idx = {}
    for label, col in wanted.items():
        hits = [i for i, h in enumerate(headers) if h == label]
        if len(hits) != 1:
            raise AnbimaParseError(f"{codigo}: column {label!r} found {len(hits)} times in {headers}")
        idx[col] = hits[0]
    return idx


_AGENDA = {"data do evento": "data_evento", "data de liquidacao": "data_liquidacao",
           "evento": "evento", "percentual taxa": "percentual_taxa", "valor pago": "valor_pago",
           "status": "status"}


def parse_agenda(capture) -> list[dict[str, Any]]:
    if capture.total_rows == 0 and not capture.tables:
        return []
    table = _table(capture, "data do evento")
    if table is None:
        raise AnbimaParseError(f"{capture.codigo}: agenda table missing")
    if capture.total_rows is not None and len(table["rows"]) != capture.total_rows:
        raise AnbimaParseError(
            f"{capture.codigo}: agenda read {len(table['rows'])} rows, ANBIMA shows {capture.total_rows}")
    idx = _columns(table, _AGENDA, capture.codigo)
    rows, seen = [], set()
    for cells in table["rows"]:
        r = {col: cells[i] for col, i in idx.items()}
        row = {"codigo": capture.codigo, "data_evento": day(r["data_evento"]),
               "data_liquidacao": day(r["data_liquidacao"]), "evento": r["evento"].strip(),
               "percentual_taxa_pct": num(r["percentual_taxa"]),
               "valor_pago_brl": num(r["valor_pago"]),
               "status": None if _missing(r["status"]) else r["status"].strip()}
        if row["data_evento"] is None or not row["evento"]:
            raise AnbimaParseError(f"{capture.codigo}: agenda row without date or event: {cells}")
        key = (row["data_evento"], row["evento"])
        if key in seen:
            # Two rows on one key would silently overwrite each other on upsert.
            raise AnbimaParseError(f"{capture.codigo}: duplicate agenda event {key}")
        seen.add(key)
        rows.append(row)
    return rows


_RATES = {"data": "data_referencia", "intervalo indic min": "intervalo_min_pct",
          "intervalo indic max": "intervalo_max_pct", "taxa de compra": "taxa_compra_pct",
          "taxa de venda": "taxa_venda_pct", "taxa indicativa": "taxa_indicativa_pct",
          "desvio padrao": "desvio_padrao", "duration dias uteis": "duration_du",
          "% pu par": "pct_pu_par", "pu indicativo": "pu_indicativo_brl",
          "% reune": "pct_reune", "referencia ntn b": "referencia_ntnb"}


def parse_precos(capture) -> list[dict[str, Any]]:
    """The last-5-sessions table. A bond without indicative prices yields []."""
    table = _table(capture, "taxa indicativa")
    if table is None:
        if not any(_table(capture, h) for h in ("vna",)):
            raise AnbimaParseError(f"{capture.codigo}: price page rendered no table")
        return []
    idx = _columns(table, _RATES, capture.codigo)
    rows = []
    for cells in table["rows"]:
        r = {col: cells[i] for col, i in idx.items()}
        row = {"codigo": capture.codigo, "data_referencia": day(r["data_referencia"])}
        if row["data_referencia"] is None:
            raise AnbimaParseError(f"{capture.codigo}: rate row without date: {cells}")
        for col in _RATES.values():
            if col not in row:
                row[col] = day(r[col]) if col == "referencia_ntnb" else num(r[col])
        rows.append(row)
    if len({r["data_referencia"] for r in rows}) != len(rows):
        raise AnbimaParseError(f"{capture.codigo}: duplicate rate dates")
    return rows
