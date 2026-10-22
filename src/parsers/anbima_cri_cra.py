"""Parse ANBIMA's public CRI and CRA pages into stored rows (#1014).

The pages share the debenture layout (``src.parsers.anbima_debenture``): the
same agenda table, the same indicative-rate table without the interval
columns, and characteristics read by section and label. What differs is the
characteristics: a CRI or CRA has a devedor and a cedente (names only, no CNPJ
on the page), a securitizadora with its CNPJ, and a classification block.

Values are stored as published: a '-' is NULL, never a guess. A page whose
layout changed raises ``AnbimaParseError``.
"""

from __future__ import annotations

import re
from typing import Any

from src.parsers.anbima_debenture import (
    _CNPJ_LINE, AnbimaParseError, _block, _missing, _norm, _pairs, cnpj, day, num,
    parse_agenda, parse_precos as _parse_precos, parse_remuneracao,
)

__all__ = ["AnbimaParseError", "parse_agenda", "parse_caracteristicas", "parse_precos"]

_SECTIONS = frozenset({"CONDIÇÕES GERAIS DA SÉRIE", "CLASSIFICAÇÃO", "PARTES ENVOLVIDAS",
                       "CONDIÇÕES GERAIS DA EMISSÃO", "AGENTES CONTRATADOS", "GARANTIAS"})
_SERIES = {
    "remuneracao": "remuneracao_text",
    "data de inicio da rentabilidade": "data_inicio_rentabilidade",
    "expressao do papel": "expressao_papel",
    "quantidade da serie na data de emissao": "quantidade_serie_emissao",
    "volume da serie na data de emissao": "volume_serie_emissao_brl",
    "vne valor nominal na emissao": "vne_brl",
    "vna valor nominal atual": "vna_brl",
    "data da emissao": "data_emissao",
    "data de vencimento": "data_vencimento",
    "resgate antecipado": "resgate_antecipado",
    "isin": "isin",
}
_CLASS = {"classe": "classe", "concentracao": "concentracao", "categoria": "categoria",
          "setor": "setor", "tipo de lastro": "tipo_lastro"}
_PARTIES = {"devedor": "devedor", "cedente": "cedente"}
_ISSUE = {"quantidade da emissao": "quantidade_emissao", "volume da emissao": "volume_emissao_brl",
          "tipo": "tipo"}
# Label → column; each is followed by a name line and, when published, a CNPJ line.
_NAMED = {"securitizadora": "securitizadora", "coordenador lider": "coordenador_lider",
          "agente fiduciario": "agente_fiduciario"}
_REQUIRED = ("remuneracao_text", "data_emissao", "data_vencimento", "tipo",
             "securitizadora", "securitizadora_cnpj")
_DATES = {"data_inicio_rentabilidade", "data_emissao", "data_vencimento"}
_NUMS = {"quantidade_serie_emissao", "volume_serie_emissao_brl", "vne_brl", "vna_brl",
         "quantidade_emissao", "volume_emissao_brl"}

# The CRI/CRA rate table: the debenture one without the indicative interval.
RATES = {"data": "data_referencia", "taxa de compra": "taxa_compra_pct",
         "taxa de venda": "taxa_venda_pct", "taxa indicativa": "taxa_indicativa_pct",
         "desvio padrao": "desvio_padrao", "duration dias uteis": "duration_du",
         "% pu par": "pct_pu_par", "pu indicativo": "pu_indicativo_brl",
         "% reune": "pct_reune", "referencia ntn b": "referencia_ntnb"}


def _named(block: list[str], codigo: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for i, line in enumerate(block):
        col = _NAMED.get(_norm(line))
        if not col or col in out or i + 1 >= len(block):
            continue
        name = block[i + 1]
        out[col] = None if _missing(name) else name
        nxt = block[i + 2] if i + 2 < len(block) else ""
        out[col + "_cnpj"] = cnpj(nxt) if _CNPJ_LINE.match(nxt) else None
    return out


def parse_caracteristicas(capture) -> dict[str, Any]:
    lines = [x.strip() for x in capture.text.splitlines() if x.strip()]
    raw = _pairs(_block(lines, "CONDIÇÕES GERAIS DA SÉRIE", _SECTIONS), _SERIES)
    raw.update(_pairs(_block(lines, "CLASSIFICAÇÃO", _SECTIONS), _CLASS))
    raw.update(_pairs(_block(lines, "PARTES ENVOLVIDAS", _SECTIONS), _PARTIES))
    issue_block = _block(lines, "CONDIÇÕES GERAIS DA EMISSÃO", _SECTIONS)
    raw.update(_pairs(issue_block, _ISSUE))
    named = _named(issue_block, capture.codigo)
    named.update({k: v for k, v in _named(_block(lines, "AGENTES CONTRATADOS", _SECTIONS),
                                           capture.codigo).items() if k not in named})
    raw.update(named)
    missing = [c for c in _REQUIRED if _missing(raw.get(c))]
    if missing:
        raise AnbimaParseError(f"{capture.codigo}: characteristics without {missing}")
    if raw["tipo"] not in ("CRI", "CRA"):
        raise AnbimaParseError(f"{capture.codigo}: unknown type {raw['tipo']!r}")

    row: dict[str, Any] = {"codigo": capture.codigo}
    for col in (set(_SERIES.values()) | set(_CLASS.values()) | set(_PARTIES.values())
                | set(_ISSUE.values())):
        value = raw.get(col)
        if col in _DATES:
            row[col] = day(value)
        elif col in _NUMS:
            row[col] = num(value)
        else:
            row[col] = None if _missing(value) else value
    for col in _NAMED.values():
        row[col] = raw.get(col)
        row[col + "_cnpj"] = raw.get(col + "_cnpj")
    row.update(parse_remuneracao(row.pop("remuneracao_text")))
    row["resgate_antecipado"] = {"Sim": True, "Não": False}.get(row["resgate_antecipado"] or "")
    row["serie"] = next((x for x in lines if re.fullmatch(r"\d+ª Série", x)), None)
    row["emissao"] = next((x for x in lines if re.fullmatch(r"\d+ª Emissão", x)), None)
    return row


def parse_precos(capture) -> list[dict[str, Any]]:
    return _parse_precos(capture, RATES)
