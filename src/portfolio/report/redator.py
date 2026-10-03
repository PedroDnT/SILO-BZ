"""Redator: Portuguese findings written from the engine JSON.

Rule zero: the model never types a figure. Every number, date, CNPJ or name
with a digit is a placeholder bound to a JSON path of the engine output
(``{{fees.total_estimated_brl_year}}``); ``render.py`` substitutes the value.
The model sees the masked engine JSON only, and ``assert_masked`` refuses the
call when anything that looks like the client (name, CPF, account) is in it.

``template_findings`` is a deterministic writer over the same placeholders. It
backs ``--provider fake`` so the CLI produces a complete report offline, and it
shows the shape the model is asked for.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from src.portfolio.report.llm import LLMError, Provider

SECTIONS = (
    "resumo",
    "achados",
    "identificacao",
    "taxas",
    "exposicao",
    "reapresentacoes",
    "sinais_de_risco",
)

SECTION_TITLES = {
    "resumo": "Resumo",
    "achados": "Achados que ninguém pegaria à mão",
    "identificacao": "Identificação linha a linha",
    "taxas": "Custo em taxas",
    "exposicao": "Exposição",
    "reapresentacoes": "Reapresentações",
    "sinais_de_risco": "Sinais de risco",
}

# Keys that would carry the client's identity. Fund and issuer names are public
# and expected; these are not.
FORBIDDEN_KEYS = frozenset(
    {
        "cliente", "nome_cliente", "client", "client_name", "customer", "customer_name",
        "titular", "nome_titular", "holder_name", "investidor", "investor_name",
        "cpf", "cpf_cliente", "conta", "numero_conta", "account", "account_id",
        "account_number", "agencia", "branch", "email", "telefone", "phone", "endereco", "address",
    }
)
_CPF_RE = re.compile(r"(?<!\d)(\d{3}\.\d{3}\.\d{3}-\d{2}|\d{11})(?!\d)")
_MASK_RE = re.compile(r"^[\*xX#•\-\s]*$")


class UnmaskedInputError(ValueError):
    """The engine JSON carries something that identifies the client."""


def _walk(doc: Any, path: str = "") -> Any:
    if isinstance(doc, dict):
        for k, v in doc.items():
            yield from _walk(v, f"{path}.{k}" if path else str(k))
    elif isinstance(doc, list):
        for i, v in enumerate(doc):
            yield from _walk(v, f"{path}[{i}]")
    yield path, doc


def assert_masked(engine: dict) -> None:
    """Raise ``UnmaskedInputError`` (naming paths, never values) if unmasked."""
    bad: list[str] = []
    for path, value in _walk(engine):
        key = re.split(r"[.\[]", path)[-1].lower() if path else ""
        if key in FORBIDDEN_KEYS and value not in (None, "", [], {}):
            if not (isinstance(value, str) and _MASK_RE.match(value)):
                bad.append(f"{path} (client field)")
        if isinstance(value, str) and _CPF_RE.search(value):
            bad.append(f"{path} (CPF-shaped string)")
    if bad:
        raise UnmaskedInputError("engine JSON is not masked: " + ", ".join(sorted(set(bad))))


@dataclass
class Finding:
    id: str
    section: str
    title: str
    text: str
    citations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RedatorResult:
    status: str  # "complete" | "unknown"
    findings: list[Finding]
    reason: str | None = None


FINDINGS_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "section": {"type": "string", "enum": list(SECTIONS)},
                    "title": {"type": "string"},
                    "text": {"type": "string"},
                    "citations": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "section", "title", "text", "citations"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """Você é o Redator do SILO, um diagnóstico independente de carteira de investimentos feito só com dados públicos (CVM, BCB, B3, FNET). Você recebe um JSON produzido pelo motor do SILO e escreve achados em português do Brasil para o investidor.

Regra zero: todo número vem do JSON. Você nunca escreve um algarismo. Cada valor, percentual, data, contagem, CNPJ ou nome que contenha algarismo entra como marcador ligado a um caminho do JSON, no formato {{caminho}}, por exemplo {{fees.total_estimated_brl_year}} ou {{lines[3].fund_name}}. O renderizador substitui o marcador pelo valor do JSON já formatado (R$, %, datas), então não escreva "R$", "%" nem unidades ao lado do marcador. Uma frase com algarismo fora de marcador é apagada pelo Revisor. Um marcador cujo caminho não existe ou é nulo também apaga a frase.

O que escrever, nesta ordem de importância:
1. identificacao: a carteira identificada fundo a fundo; linhas ambíguas e como foram desempatadas; fundos que mudaram de nome; linhas não identificadas e o motivo.
2. taxas: a taxa de administração DIVULGADA de cada fundo (fees.by_line[i].disclosed_pct_year, com a origem e a data em disclosed_origin_label e disclosed_as_of); a estimativa do balancete só como comparação, sempre dita "estimativa, não divulgada" e nunca somada nem apresentada como a taxa; sem taxa divulgada, diga "taxa divulgada não encontrada"; um 0 informado é "0 informado; a conferir" (filed_zero_label) e um valor acima de 5% a.a. é "valor informado acima de 5% a.a.; a conferir" (implausible_label, o valor informado fica em implausible_raw): nunca diga que estão errados, pois podem estar corretos, nunca os use como custo, some ou compare, e mostre o valor informado; taxa defasada (disclosed_stale) é dita defasada; é taxa da classe quando disclosed_scope_label diz; taxa de performance e demais termos como o JSON traz, sem interpretar; a taxa do master de um FIC nunca se soma à do FIC (fees.underlying é "não somada"); o total de despesas declarado (expense_ratio_pct) é outra coisa e nunca se soma.
3. exposicao: onde a carteira se sobrepõe e o que está por baixo (look-through, exposição compartilhada, indexador, setor). Mostre "sem classificação" quando houver.
4. achados: o que ninguém pegaria à mão (fundo renomeado, reapresentação, sinal de risco, linha ambígua, dois fundos com a mesma carteira por baixo).
5. reapresentacoes: cada reapresentação, com o texto de avaliação que o JSON traz ("revisado, não avaliado"); não julgue materialidade.
6. sinais_de_risco: telas de risco com ocorrência e telas que não puderam rodar.
7. resumo: dois a quatro achados curtos para abrir o relatório.

Regras:
- citations lista os ids de provenance (campo "id" em provenance) que sustentam o achado; pelo menos um, só ids que existem.
- Não recomende comprar, vender ou manter. Não faça previsão de retorno. Não avalie grupo econômico.
- Não invente fatos fora do JSON. Se uma seção está como unknown, diga que não foi possível avaliar e cite o motivo do JSON por marcador.
- Tom sóbrio, frases curtas, sem adjetivos de alarme.
- id: f1, f2, f3... na ordem em que escrever."""


def build_user_message(engine: dict) -> str:
    payload = json.dumps(engine, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (
        "JSON do motor (mascarado; os números do relatório vêm só daqui):\n"
        f"{payload}\n\nEscreva os achados no formato pedido."
    )


def _coerce_findings(raw: Any) -> list[Finding]:
    if not isinstance(raw, dict) or not isinstance(raw.get("findings"), list):
        raise LLMError("Redator output has no findings list")
    out = []
    for i, f in enumerate(raw["findings"], start=1):
        if not isinstance(f, dict):
            continue
        section = f.get("section") if f.get("section") in SECTIONS else "achados"
        out.append(
            Finding(
                id=str(f.get("id") or f"f{i}"),
                section=section,
                title=str(f.get("title") or ""),
                text=str(f.get("text") or ""),
                citations=[str(c) for c in (f.get("citations") or [])],
            )
        )
    return out


def write(engine: dict, provider: Provider) -> RedatorResult:
    """Run the Redator once. LLM failures become an unknown narrative, not a crash."""
    assert_masked(engine)
    try:
        if hasattr(provider, "role"):
            provider.role = "redator"
        raw = provider.complete(SYSTEM_PROMPT, build_user_message(engine), FINDINGS_SCHEMA)
        return RedatorResult("complete", _coerce_findings(raw))
    except LLMError as exc:
        return RedatorResult("unknown", [], f"{type(exc).__name__}: {exc}")


# --- deterministic writer (fake provider, offline sample) -------------------


def _ids(*lists: Any) -> list[str]:
    for lst in lists:
        if isinstance(lst, list) and lst:
            return [str(x) for x in lst]
    return []


def template_findings(engine: dict) -> dict:
    """Findings for every section, built from the engine JSON with placeholders only."""
    out: list[dict] = []
    all_prov = [p.get("id") for p in engine.get("provenance", []) if isinstance(p, dict) and p.get("id")]

    def add(section: str, title: str, text: str, cites: list[str]) -> None:
        out.append(
            {"id": f"f{len(out) + 1}", "section": section, "title": title, "text": text,
             "citations": cites or all_prov[:1]}
        )

    lines = engine.get("lines") or []
    pf = engine.get("portfolio") or {}
    line_prov = sorted({c for ln in lines for c in (ln.get("provenance") or [])})

    # identificacao
    if pf:
        add("identificacao", "Carteira identificada fundo a fundo",
            "A carteira soma {{portfolio.total_brl}} em {{portfolio.n_lines}} linhas. "
            "Linhas identificadas nos dados públicos: {{portfolio.n_identified}}. "
            "Linhas com ambiguidade desempatada: {{portfolio.n_ambiguous}}. "
            "Linhas sem identificação: {{portfolio.n_unknown}}.", line_prov)
    for i, ln in enumerate(lines):
        ident = ln.get("identification") or {}
        p = f"lines[{i}]"
        if ident.get("renamed_from"):
            txt = (f"A linha {{{{{p}.instrument}}}} é o fundo {{{{{p}.fund_name}}}}, CNPJ {{{{{p}.cnpj}}}}. "
                   f"O nome antigo era {{{{{p}.identification.renamed_from}}}}, e a identificação usou o histórico de nomes da CVM.")
            if ident.get("renamed_at"):
                txt += f" A troca de nome aparece a partir de {{{{{p}.identification.renamed_at}}}}."
            add("identificacao", "Fundo renomeado", txt, ln.get("provenance"))
            add("achados", "Um fundo da carteira mudou de nome",
                f"O fundo {{{{{p}.fund_name}}}} aparece no extrato com um nome que a CVM já não usa. "
                "Uma busca pelo nome atual não o encontraria.", ln.get("provenance"))
        if ident.get("status") == "ambiguous":
            cands = ident.get("candidates") or []
            txt = f"O nome do extrato em {{{{{p}.instrument}}}} corresponde a mais de um fundo."
            for j, c in enumerate(cands):
                q = f"{p}.identification.candidates[{j}]"
                txt += (f" Candidato: {{{{{q}.fund_name}}}}, CNPJ {{{{{q}.cnpj}}}}, cota de {{{{{q}.quota}}}}"
                        + (f" em {{{{{q}.quota_date}}}}." if c.get("quota_date") else "."))
            chosen = next((j for j, c in enumerate(cands) if c.get("chosen")), None)
            if chosen is not None:
                txt += (f" A cota do extrato desempatou a favor de "
                        f"{{{{{p}.identification.candidates[{chosen}].fund_name}}}}.")
            add("identificacao", "Linha ambígua desempatada pela cota", txt, ln.get("provenance"))
            add("achados", "Nome abreviado com dois fundos possíveis",
                f"A linha {{{{{p}.instrument}}}} podia ser o fundo investidor ou o master. "
                "Só a cota separa os dois.", ln.get("provenance"))
        if ident.get("status") == "unknown":
            add("identificacao", "Linha não identificada",
                f"A linha {{{{{p}.instrument}}}}, de {{{{{p}.value_brl}}}}, não foi identificada: "
                f"{{{{{p}.identification.reason}}}}. Ela fica fora da análise de taxas e de exposição.",
                ln.get("provenance"))

    # taxas
    fees = engine.get("fees") or {}
    by_line = fees.get("by_line") or []
    fee_prov = _ids(*[b.get("provenance") for b in by_line])
    new_view = any("fee_status" in b for b in by_line)
    if new_view:
        # catalog v52 view: the disclosed fee first, the estimate beside it and labelled
        if fees.get("total_disclosed_brl_year") is not None:
            add("taxas", "Custo em taxas divulgadas",
                "As taxas de administração divulgadas somam {{fees.total_disclosed_brl_year}} por ano, "
                "ou {{fees.total_disclosed_pct_year}} ao ano sobre a carteira, nos fundos com taxa fixa utilizável.", fee_prov)
        else:
            add("taxas", "Taxa divulgada ausente",
                "Nenhum fundo da carteira tem taxa de administração fixa e utilizável divulgada nos dados do SILO.", fee_prov)
        if fees.get("total_estimated_brl_year") is not None:
            add("taxas", "Estimativa do balancete, à parte",
                "A estimativa do balancete, {{fees.estimate_label}}, soma {{fees.total_estimated_brl_year}} por ano, "
                "ou {{fees.weighted_estimated_pct_year}} ao ano sobre a carteira. Ela é um controle e não é somada à taxa divulgada.", fee_prov)
        for i, b in enumerate(by_line):
            q = f"fees.by_line[{i}]"
            if b.get("disclosed_pct_year") is not None:
                txt = (f"A taxa de administração divulgada da linha {{{{{q}.line_id}}}} é {{{{{q}.disclosed_pct_year}}}} ao ano, "
                       f"cerca de {{{{{q}.disclosed_brl_year}}}} por ano. Origem: {{{{{q}.disclosed_origin_label}}}}, "
                       f"data {{{{{q}.disclosed_as_of}}}}.")
                if b.get("disclosed_scope_label"):
                    txt += f" É {{{{{q}.disclosed_scope_label}}}}."
                if b.get("disclosed_stale"):
                    txt += f" Está {{{{{q}.disclosed_stale_label}}}}."
                if b.get("estimated_pct_year") is not None:
                    txt += (f" Estimativa do balancete, à parte: {{{{{q}.estimated_pct_year}}}} ao ano "
                            f"({{{{{q}.estimate_label}}}}).")
                add("taxas", "Taxa de administração divulgada", txt, b.get("provenance"))
            elif b.get("disclosed_min_pct_year") is not None:
                add("taxas", "Faixa de taxa divulgada",
                    f"A linha {{{{{q}.line_id}}}} tem classes com taxas diferentes: faixa divulgada de {{{{{q}.disclosed_min_pct_year}}}} "
                    f"a {{{{{q}.disclosed_max_pct_year}}}} ao ano.", b.get("provenance"))
            elif b.get("filed_zero_label"):
                add("taxas", "Taxa zero informada",
                    f"Na linha {{{{{q}.line_id}}}} a fonte informou {{{{{q}.filed_zero_pct}}}} ao ano: {{{{{q}.filed_zero_label}}}}. "
                    "O valor pode estar correto e não é contado como custo, nem somado, nem comparado.",
                    b.get("provenance"))
            elif b.get("implausible_label"):
                add("taxas", "Valor informado acima do limite, a conferir",
                    f"Na linha {{{{{q}.line_id}}}} a fonte informou {{{{{q}.implausible_raw}}}}: {{{{{q}.implausible_label}}}}. "
                    "O valor pode estar correto e não entra em nenhuma conta.", b.get("provenance"))
            else:
                add("taxas", "Taxa divulgada não encontrada",
                    f"A linha {{{{{q}.line_id}}}}: {{{{{q}.fee_status}}}}. {{{{{q}.reason}}}}", _ids(b.get("provenance"), fee_prov))
        for i, fi in enumerate(fees.get("findings") or []):
            if fi.get("level") == "atenção":
                q = f"fees.findings[{i}]"
                add("achados", "Taxa: sinal de atenção",
                    f"Linha {{{{{q}.line_id}}}}: {{{{{q}.text}}}}", fi.get("provenance"))
    else:
        if fees.get("total_estimated_brl_year") is not None:
            add("taxas", "Custo estimado em taxas",
                "O custo anual estimado em taxas é de {{fees.total_estimated_brl_year}}, "
                "ou {{fees.weighted_estimated_pct_year}} ao ano sobre a carteira. "
                "Base do cálculo: {{fees.basis}}.", fee_prov)
        if fees.get("total_disclosed_brl_year") is None and by_line:
            add("taxas", "Taxa divulgada ausente",
                "Nenhuma linha tem a taxa divulgada nos dados do SILO, então o custo acima é estimado e não declarado pelo fundo.",
                fee_prov)
        known = [(i, b) for i, b in enumerate(by_line) if b.get("estimated_pct_year") is not None]
        if known:
            i, b = max(known, key=lambda t: t[1]["estimated_pct_year"])
            q = f"fees.by_line[{i}]"
            txt = (f"A taxa estimada mais alta é a da linha {{{{{q}.line_id}}}}, CNPJ {{{{{q}.cnpj}}}}: "
                   f"{{{{{q}.estimated_pct_year}}}} ao ano, cerca de {{{{{q}.estimated_brl_year}}}} por ano.")
            if b.get("estimated_pct_year_high") is not None:
                txt += f" Conforme o mês de referência, a estimativa chega a {{{{{q}.estimated_pct_year_high}}}}."
            add("taxas", "Maior custo estimado", txt, b.get("provenance"))
        for i, b in enumerate(by_line):
            if b.get("label") == "desconhecido":
                add("taxas", "Taxa não estimada",
                    f"A taxa da linha {{{{fees.by_line[{i}].line_id}}}} não foi estimada: {{{{fees.by_line[{i}].reason}}}}.",
                    _ids(b.get("provenance"), fee_prov))

    # exposicao
    lt = engine.get("lookthrough") or {}
    for i, s in enumerate(lt.get("shared_exposure") or []):
        q = f"lookthrough.shared_exposure[{i}]"
        name = f"{{{{{q}.name}}}}" if s.get("name") else f"{{{{{q}.key}}}}"
        txt = (f"A carteira tem {name} por mais de um caminho: {{{{{q}.total_brl}}}} no total, "
               f"{{{{{q}.total_pct}}}} da carteira.")
        for j, _leg in enumerate(s.get("legs") or []):
            txt += f" Pela linha {{{{{q}.legs[{j}].line_id}}}} ({{{{{q}.legs[{j}].via}}}}): {{{{{q}.legs[{j}].value_brl}}}}."
        add("exposicao", "Exposição compartilhada", txt, s.get("provenance"))
        if s.get("level") == "fundo":
            add("achados", "Duas linhas, uma carteira por baixo",
                f"Duas linhas do extrato investem no mesmo fundo, {name}. "
                "Elas parecem diversificação, mas por baixo são a mesma carteira.", s.get("provenance"))
    ix = engine.get("indexer") or {}
    buckets = ix.get("buckets") or []
    if buckets:
        top = max(range(len(buckets)), key=lambda k: buckets[k].get("weight_pct") or 0)
        txt = (f"Por indexador, a maior parte está em {{{{indexer.buckets[{top}].indexer}}}}: "
               f"{{{{indexer.buckets[{top}].weight_pct}}}} da carteira.")
        unc = next((k for k, b in enumerate(buckets) if b.get("indexer") == "sem classificação"), None)
        if unc is not None:
            txt += (f" Sem classificação de indexador: {{{{indexer.buckets[{unc}].value_brl}}}}, "
                    f"{{{{indexer.buckets[{unc}].weight_pct}}}} da carteira.")
        add("exposicao", "Indexador", txt, ix.get("provenance"))
    sc = engine.get("sector") or {}
    sb = sc.get("buckets") or []
    if sb:
        top = max(range(len(sb)), key=lambda k: (sb[k].get("weight_pct") or 0) if sb[k].get("sector") != "sem classificação" else -1)
        txt = (f"O setor com mais exposição é {{{{sector.buckets[{top}].sector}}}}, com "
               f"{{{{sector.buckets[{top}].weight_pct}}}} da carteira.")
        unc = next((k for k, b in enumerate(sb) if b.get("sector") == "sem classificação"), None)
        if unc is not None:
            txt += f" Sem classificação de setor: {{{{sector.buckets[{unc}].weight_pct}}}}."
        add("exposicao", "Setor", txt, sc.get("provenance"))

    # reapresentacoes
    rs = engine.get("restatements") or {}
    for i, r in enumerate(rs.get("items") or []):
        q = f"restatements.items[{i}]"
        txt = (f"O {{{{{q}.fund_name}}}} reapresentou o {{{{{q}.document}}}} da competência {{{{{q}.competencia}}}} "
               f"em {{{{{q}.delivered_at}}}}, com {{{{{q}.n_fields_changed}}}} campos alterados.")
        if r.get("delinquency_new_brl") is not None:
            txt += (f" A inadimplência informada passou de {{{{{q}.delinquency_old_brl}}}} "
                    f"para {{{{{q}.delinquency_new_brl}}}}.")
        txt += f" Situação: {{{{{q}.assessment}}}}."
        add("reapresentacoes", "Informe reapresentado", txt, r.get("provenance"))
        if r.get("delinquency_change_brl") is not None:
            add("achados", "Inadimplência revista depois da entrega",
                f"O informe do {{{{{q}.fund_name}}}} foi entregue de novo e a inadimplência mudou em "
                f"{{{{{q}.delinquency_change_brl}}}}. Quem leu só a primeira versão não viu essa mudança.",
                r.get("provenance"))

    # sinais de risco
    rk = engine.get("risk_screens") or {}
    if rk:
        hits = rk.get("hits") or []
        for i, _h in enumerate(hits):
            add("sinais_de_risco", "Sinal de risco",
                f"A tela {{{{risk_screens.hits[{i}].screen}}}} marcou a linha {{{{risk_screens.hits[{i}].line_id}}}}.",
                rk.get("provenance"))
        if not hits and rk.get("screens_run") is not None:
            add("sinais_de_risco", "Telas sem ocorrência",
                "Telas de risco executadas sobre os fundos da carteira: {{risk_screens.screens_run}}. Nenhuma marcou um fundo da carteira.",
                rk.get("provenance"))
        for i, _n in enumerate(rk.get("not_run") or []):
            add("sinais_de_risco", "Tela que não rodou",
                f"A tela {{{{risk_screens.not_run[{i}].screen}}}} não rodou: {{{{risk_screens.not_run[{i}].reason}}}}.",
                rk.get("provenance"))

    # resumo: the first identification line, the fee total, the first shared exposure
    if pf:
        add("resumo", "A carteira em uma frase",
            "Das {{portfolio.n_lines}} linhas do extrato, {{portfolio.n_identified}} foram identificadas nos dados públicos.",
            line_prov)
    if new_view and fees.get("total_disclosed_brl_year") is not None:
        add("resumo", "Custo", "As taxas de administração divulgadas custam {{fees.total_disclosed_brl_year}} por ano nos fundos com taxa fixa utilizável.", fee_prov)
    elif fees.get("total_estimated_brl_year") is not None:
        add("resumo", "Custo", "As taxas custam cerca de {{fees.total_estimated_brl_year}} por ano, por estimativa.", fee_prov)
    if lt.get("shared_exposure"):
        add("resumo", "Sobreposição",
            "Parte da carteira se repete por baixo dos fundos; a seção de exposição mostra onde.",
            _ids(lt["shared_exposure"][0].get("provenance")))
    if rs.get("items"):
        add("resumo", "Reapresentação",
            "Há informe reapresentado em fundo da carteira, listado sem avaliação de materialidade.",
            _ids(rs["items"][0].get("provenance")))
    return {"findings": out}
