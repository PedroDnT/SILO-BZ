"""Engine 1.12, offline: the investigator of official documents (#605). Every HTTP, Exa and LLM call is a fake.
Synthetic data only: every code, CNPJ, name, value and document text below is invented."""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pytest

from src.portfolio.client import FakeClient, load_fake_rows
from src.portfolio.diagnose import FAKE_CLOCK
from src.portfolio.engine import default_params, run_engine
from src.portfolio.identify import LineId
from src.portfolio.investigator import extract as ex
from src.portfolio.investigator import run as R
from src.portfolio.investigator.cache import BundleDocumentCache, MemoryDocumentCache, cache_key, sha256_text
from src.portfolio.investigator.sources import ExaClient, FnetReader, HttpResponse, SourceError, source_type_of
from src.portfolio.investigator.text import keyword_excerpt, normalize, numbers_within, numeric_tokens, quote_found
from src.portfolio.investigator.tiers import TIER_A, TIER_B, TIER_C, assess
from src.portfolio.report.llm import FakeProvider
from src.portfolio.statement import Position, read_statement

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "docs" / "reference" / "portfolio" / "statement-template.xlsx"
FAKE_ROWS = ROOT / "tests" / "fixtures" / "portfolio" / "fake_silo_rows.json"
D = dt.date(2026, 9, 30)
CLOCK = lambda: FAKE_CLOCK  # noqa: E731

ISIN = "BREXMPCRA001"
TERMO = """TERMO DE SECURITIZAÇÃO DE DIREITOS CREDITÓRIOS DO AGRONEGÓCIO da 1ª Emissão da
SECURITIZADORA EXEMPLO S.A., inscrita no CNPJ sob o nº 90.000.000/0005-00, na qualidade de Emissora.
Os CRA são lastreados em Direitos Creditórios do Agronegócio devidos pela DEVEDORA EXEMPLO S.A.
“Data de Vencimento dos CRA”: significa 15 de abril de 2032, ressal-
vadas as hipóteses de resgate antecipado.
Remuneração: os CRA farão jus a juros remuneratórios correspondentes a IPCA acrescido de 8,7400% ao ano.
(xvii) Classificação de Risco: Não haverá classificação de risco para a Emissão.
| Série | Taxa | Vencimento |
| 1ª | IPCA + 8,7400% | 15/04/2032 |
"""
CERT_ROW = {"id": 777, "text": f"SEC EXEMPLO CRA Emissão:1 Série:1 DEVEDORA 01/2026 {ISIN}"}


def doc_row(fid, cat, tipo="", entrega="02/02/2026 07:24", ref="02/02/2026", status="AC"):
    return {"id": fid, "categoriaDocumento": cat, "tipoDocumento": tipo, "dataEntrega": entrega, "dataReferencia": ref,
            "status": status, "descricaoFundo": "SINTETICO", "versao": 1}


# --- fakes ------------------------------------------------------------------------------------------

class FakeHttp:
    """Answers by path; records every request (method, url, params, payload, headers)."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def _answer(self, method, url, params, payload, headers):
        self.calls.append({"method": method, "url": url, "params": dict(params or {}), "payload": payload,
                           "headers": dict(headers or {})})
        for key, fn in self.routes.items():
            if key in url:
                return fn(params or {}, payload)
        return HttpResponse(404, "text/plain", b"not found")

    def get(self, url, params=None, headers=None):
        return self._answer("GET", url, params, None, headers)

    def post_json(self, url, payload, headers=None):
        return self._answer("POST", url, None, payload, headers)


def js(obj, status=200):
    return HttpResponse(status, "application/json", json.dumps(obj).encode("utf-8"))


def fnet_routes(listing_rows=None, cert_rows=(CERT_ROW,), docs=None, fund_rows=None):
    docs = docs or {1001: TERMO}
    listing_rows = listing_rows if listing_rows is not None else [doc_row(1001, "Termo de Securitização")]

    def listar(params, _):
        return js({"results": [r for r in cert_rows if params.get("term") in r["text"]], "more": False})

    def pesquisar(params, _):
        rows = fund_rows if "cnpjFundo" in params else listing_rows
        s = int(params.get("s", 0))
        return js({"data": rows[s:s + 200], "recordsTotal": len(rows), "draw": 1})

    def download(params, _):
        fid = int(params["id"])
        if fid not in docs:
            return HttpResponse(500, "text/html", b"<html>erro</html>")
        return HttpResponse(200, "text/plain", docs[fid].encode("utf-8"))

    return {"listarFundos": listar, "pesquisarGerenciadorDocumentosDados": pesquisar, "downloadDocumento": download}


def provider(model, responder):
    p = FakeProvider(responder)
    p.model = model
    return p


def credit_extractor(system, user, schema):
    """A canned extractor: copies values from the synthetic termo (the prompt's text field)."""
    text = json.loads(user)["text"]
    facts = []
    if "15 de abril de 2032" in text:
        facts.append({"field": "vencimento", "value": "15 de abril de 2032",
                      "quote": "“Data de Vencimento dos CRA”: significa 15 de abril de 2032, ressalvadas", "subject": None})
    if "8,7400%" in text:
        facts.append({"field": "indexador", "value": "IPCA acrescido de 8,7400% ao ano",
                      "quote": "correspondentes a IPCA acrescido de 8,7400% ao ano", "subject": "1ª série"})
        # a paraphrase of the table row: not verbatim, so only a judge can accept it (tier B)
        facts.append({"field": "vencimento", "value": "15/04/2032",
                      "quote": "Série 1ª, taxa IPCA + 8,7400%, vencimento 15/04/2032", "subject": "1ª série"})
        # a number the document does not carry: discarded in every tier
        facts.append({"field": "rating", "value": "brAA+ (nota 9)", "quote": "Classificação de Risco: brAA+ (nota 9)",
                      "subject": None})
    return {"facts": facts}


def judge_yes(system, user, schema):
    return {"supported": True}


def models(extractor=credit_extractor, judge=judge_yes, em="extrator-x", jm="juiz-y"):
    return ex.pair(provider(em, extractor), provider(jm, judge) if judge else None)


def credit_line(line_no=11, codigo=f"CRA-{ISIN}", status="identified", flags=("vencimento_diverge",), tipo="CRA",
                linha="SENTINELA LINHA EXTRATO", valor=Decimal("987654.32")):
    p = Position(line_no=line_no, source_row=line_no + 2, linha_extrato=linha, tipo=tipo, codigo=codigo,
                 quantidade=Decimal("7"), preco_unitario=Decimal("141093.4743"), valor=valor, data_posicao=D,
                 vencimento=dt.date(2031, 10, 15), taxa_texto="IPCA + 8,74%", conta_ref="C9",
                 emissor="SENTINELA EMISSOR IMPRESSO")
    li = LineId(position=p, status=status)
    if status == "identified":
        li.credit = {"matched": True, "code": ISIN if codigo.endswith(ISIN) else codigo, "cnpj_securit": "90000000000500",
                     "data_vencimento": "2032-04-15", "taxa_juros": "IPCA+ 8,7400% a.a",
                     "classificacao_risco_atual": None, "cd_isin": None,
                     "flags": [{"code": c} for c in flags]}
    return li


def fund_line(line_no, cnpj, tipo="fundo", entity_type="fi", name="FUNDO SINTETICO NA CVM"):
    p = Position(line_no=line_no, source_row=line_no + 2, linha_extrato="SENTINELA LINHA FUNDO", tipo=tipo,
                 codigo=cnpj, quantidade=None, preco_unitario=None, valor=Decimal("555444.33"), data_posicao=D)
    return LineId(position=p, status="identified", kind="fund", cnpj=cnpj, entity_type=entity_type, name=name)


def investigator(http, mdl=None, exa=None, cache=None, budget=None):
    deps = R.InvestigatorDeps(http=http, cache=cache or MemoryDocumentCache(), models=mdl or models(), exa=exa,
                              exa_note=None if exa else R.MSG_NO_EXA, budget=budget or R.Budget(deadline_s=None))
    return R.Investigator(deps)


def run(inv, lines, doc=None, client=None):
    return inv.run(lines, doc or {"movement": {}}, client or FakeClient({}), CLOCK)


# --- text and tiers ---------------------------------------------------------------------------------

def test_tier_a_normalizes_accents_quotes_line_breaks_and_hyphenation():
    text = 'Data de Vencimento dos CRA": significa 15 de abril de 2032, ressal-\nvadas as hipóteses'
    assert quote_found("DATA DE VENCIMENTO DOS CRA\": significa 15 de abril   de 2032, ressalvadas as hipoteses", text)
    v = assess("vencimento", "15 de abril de 2032", "“Data de Vencimento dos CRA”: significa 15 de abril de 2032, ressalvadas",
               TERMO, None)
    assert v.tier == TIER_A and v.reason_code is None
    assert normalize("Ação  ÚNICA\n“x”") == 'acao unica "x"'


def test_a_short_quote_proves_nothing():
    assert not quote_found("2032", TERMO)


def test_numbers_are_canonical_and_must_appear_in_the_passage():
    assert numeric_tokens("1.000.000,00 e 8,7400% em 15/04/2032") == {"1000000", "8.74", "15/04/2032"}
    assert numbers_within("8,74%", "IPCA + 8,7400% a.a.")
    assert not numbers_within("9,10%", "IPCA + 8,7400% a.a.")


def test_tier_b_needs_a_judge_and_every_number_in_the_located_passage():
    quote = "Série 1ª, taxa IPCA + 8,7400%, vencimento 15/04/2032"
    b = assess("vencimento", "15/04/2032", quote, TERMO, lambda f, v, p: True)
    assert b.tier == TIER_B and b.passage and "15/04/2032" in b.passage
    assert assess("vencimento", "15/04/2032", quote, TERMO, lambda f, v, p: False).reason_code == "juiz_rejeitou"
    assert assess("vencimento", "15/04/2032", quote, TERMO, None).reason_code == "juiz_indisponivel"
    # the judge says yes, but 16/04/2032 is not in the passage: the code discards it, whatever the model says
    wrong = assess("vencimento", "16/04/2032", "Série 1ª, taxa IPCA + 8,7400%, vencimento 16/04/2032", TERMO,
                   lambda f, v, p: True)
    assert wrong.tier == TIER_C and wrong.reason_code == "numero_fora_do_trecho"

    def boom(f, v, p):
        raise RuntimeError("timeout")

    assert assess("vencimento", "15/04/2032", quote, TERMO, boom).reason_code == "juiz_falhou"


def test_a_verbatim_quote_with_an_invented_number_in_the_value_is_discarded():
    v = assess("indexador", "IPCA + 9,10%", "correspondentes a IPCA acrescido de 8,7400% ao ano", TERMO, None)
    assert v.tier == TIER_C and v.reason_code == "numero_fora_do_trecho"


def test_same_model_is_refused_for_tier_b():
    m = ex.pair(provider("gpt-x", credit_extractor), provider("gpt-x", judge_yes))
    assert m.tier_b_enabled is False and m.judge is None and "igual" in m.note
    assert ex.pair(provider("a", credit_extractor), provider("b", judge_yes)).tier_b_enabled is True
    assert ex.pair(provider("a", credit_extractor), None).note.startswith("modelo juiz não configurado")


def test_models_from_env_have_different_defaults_and_degrade_without_a_key(monkeypatch):
    for k in ("OPENAI_API_KEY", ex.EXTRACTOR_ENV, ex.JUDGE_ENV):
        monkeypatch.delenv(k, raising=False)
    m = ex.models_from_env("openai")
    assert m.extractor is None and "chave" in m.note
    assert ex.DEFAULT_EXTRACTOR["openai"] != ex.DEFAULT_JUDGE["openai"]
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.setenv(ex.JUDGE_ENV, "gpt-5.1")
    same = ex.models_from_env("openai")
    assert same.extractor_model == same.judge_model == "gpt-5.1" and same.tier_b_enabled is False


def test_keyword_excerpt_keeps_the_original_text():
    long = ("x" * 5000) + " Data de Vencimento: 15 de março de 2032 " + ("y" * 5000)
    out = keyword_excerpt(long, ("Data de Vencimento",), 3000, radius=100)
    assert "Data de Vencimento: 15 de março de 2032" in out and len(out) <= 3000 + 20


# --- the credit path: Fundos.NET certificados ----------------------------------------------------------

def test_credit_trigger_reads_the_termo_and_tiers_every_fact():
    http = FakeHttp(fnet_routes())
    sec = run(investigator(http), [credit_line()])
    assert sec["status"] == "complete" and sec["counts"]["triggers"] == 1
    tiers = sorted((f["field"], f["tier"]) for f in sec["facts"])
    assert tiers == [("indexador", "A"), ("vencimento", "A"), ("vencimento", "B")]
    # the invented rating is not in the document: discarded and counted, never shown
    assert sec["discarded"] == {"count": 1, "text": "1 fatos descartados",
                                "by_reason": {"trecho_nao_localizado": {"count": 1,
                                                                         "text": "citação não localizada no documento"}}}
    assert not any(f["field"] == "rating" for f in sec["facts"])
    f = next(f for f in sec["facts"] if f["tier"] == "A" and f["field"] == "vencimento")
    assert f["url"].endswith("downloadDocumento?id=1001") and f["fnet_id"] == 1001 and f["source_type"] == "fnet"
    assert f["document_date"] == "02/02/2026" and f["read_date"] == "2026-10-03" and f["tier_label"] == "verificado na fonte"
    # cross-checked against portfolio_instruments: agrees with the registry; the statement's own date beside it
    assert f["cross_check"]["agrees"] is True and f["cross_check"]["statement_vencimento"] == "2031-10-15"
    b = next(f for f in sec["facts"] if f["tier"] == "B")
    assert b["passage"] and b["tier_label"] == "conferido por modelo; a conferir"
    t = sec["triggers"][0]
    assert t["kind"] == "credito_vencimento_diverge" and t["message"].startswith("3 fato(s) com citação")
    assert sec["documents_consulted"][0]["status"] == "lido" and sec["documents_consulted"][0]["cache"] == "miss"
    # one certificate lookup and one listing page: two counted searches
    assert sec["searches_used"] == 2 and sec["searches_by_kind"] == {"fnet_certificado": 1, "fnet_listagem": 1}


def test_fnet_certificados_sends_the_parameter_and_the_isin():
    http = FakeHttp(fnet_routes())
    run(investigator(http), [credit_line()])
    lst = next(c for c in http.calls if "listarFundos" in c["url"])
    assert lst["params"]["term"] == ISIN and lst["params"]["paraCerts"] == "true" and lst["params"]["idTipoFundo"] == 6
    pq = next(c for c in http.calls if "pesquisarGerenciadorDocumentosDados" in c["url"])
    assert pq["params"]["paginaCertificados"] == "true" and pq["params"]["idFundo"] == 777
    assert pq["headers"]["X-Requested-With"] == "XMLHttpRequest"


def test_a_divergence_is_shown_never_overwritten():
    li = credit_line()
    li.credit["data_vencimento"] = "2033-01-01"
    sec = run(investigator(FakeHttp(fnet_routes())), [li])
    f = next(f for f in sec["facts"] if f["tier"] == "A" and f["field"] == "vencimento")
    assert f["value"] == "15 de abril de 2032" and f["cross_check"]["silo_value"] == "2033-01-01"
    assert f["cross_check"]["agrees"] is False and "a conferir" in f["cross_check"]["note"]
    assert li.credit["data_vencimento"] == "2033-01-01" and sec["counts"]["divergences"] == 2  # tiers A and B


def test_without_isin_fundos_net_is_not_asked_and_the_message_is_never_blank():
    li = credit_line(codigo="CRA-0260000X", status="unknown", flags=())
    http = FakeHttp(fnet_routes())
    sec = run(investigator(http), [li])
    t = sec["triggers"][0]
    assert t["kind"] == "credito_nao_identificado" and not http.calls
    assert t["message"] == f"não encontrado em: Fundos.NET; {R.MSG_NO_EXA}"
    assert "sem ISIN" in t["notes"][0] and sec["status"] == "partial"
    assert "busca_web_indisponivel" in sec["reason_codes"] and sec["web_search"]["available"] is False


def test_not_found_lists_every_source_tried():
    li = credit_line(status="unknown", flags=())
    http = FakeHttp({**fnet_routes(cert_rows=()), "api.exa.ai/agent/runs": lambda p, b: js(
        {"id": "agent_run_1", "status": "completed", "output": {"structured": {"facts": []}}})})
    exa = ExaClient(http, "exa-test-key", sleep=lambda s: None)
    sec = run(investigator(http, exa=exa), [li])
    assert sec["triggers"][0]["message"] == "não encontrado em: Fundos.NET, sites oficiais, busca aberta"
    assert sec["searches_by_kind"] == {"exa_agent": 2, "fnet_certificado": 1}


# --- Exa fallback --------------------------------------------------------------------------------------

def exa_routes(facts, page_text, url="https://www.securitizadora-exemplo.com.br/termo.pdf"):
    created = []

    def runs(params, payload):
        if payload is not None:  # POST create
            created.append(payload)
            return js({"id": f"agent_run_{len(created)}", "status": "running"})
        return js({"id": "agent_run_x", "status": "completed", "costDollars": {"total": 0.05},
                   "output": {"structured": {"facts": [dict(f, url=f.get("url", url)) for f in facts]}}})

    def contents(params, payload):
        assert payload["text"] is True and "urls" not in payload  # the HTTP API takes the URLs in "ids"
        return js({"results": [{"url": payload["ids"][0], "text": page_text, "publishedDate": "2026-02-02"}],
                   "statuses": [{"id": payload["ids"][0], "status": "success"}]})

    return {"api.exa.ai/agent/runs": runs, "api.exa.ai/contents": contents}, created


def test_exa_fallback_checks_the_page_text_and_labels_the_source_by_domain():
    li = credit_line(codigo="CRA-0260000X", status="unknown", flags=())
    facts = [{"field": "vencimento", "value": "15 de abril de 2032",
              "quote": "“Data de Vencimento dos CRA”: significa 15 de abril de 2032, ressalvadas"},
             {"field": "vencimento", "value": "2040-01-01", "quote": "vencimento em 2040-01-01 conforme o termo"}]
    routes, created = exa_routes(facts, TERMO + "\nCódigo CETIP dos CRA: 0260000X\n")
    http = FakeHttp(routes)
    exa = ExaClient(http, "exa-test-key", sleep=lambda s: None)
    sec = run(investigator(http, exa=exa), [li])
    assert len(created) == 1  # the official phase found a fact: the open web is not asked
    assert created[0]["outputSchema"]["properties"]["facts"]["maxItems"] == 12 and created[0]["effort"] == "low"
    f = sec["facts"][0]
    assert f["tier"] == "A" and f["source_type"] == "web_dominio_nao_verificado" and f["fnet_id"] is None
    assert f["document_date"] == "2026-02-02"  # Exa's published date when the agent gave none
    assert sec["counts"]["discarded"] == 1
    assert source_type_of("https://conteudo.cvm.gov.br/x.pdf", "open") == "web_cvm"
    assert source_type_of("https://blog.example.com/x", "open") == "web_busca_aberta"
    assert all(c["headers"].get("x-api-key") == "exa-test-key" for c in http.calls if "api.exa.ai" in c["url"])
    assert "exa-test-key" not in repr(exa)


def test_a_web_page_that_does_not_name_the_asset_is_discarded():
    """A quote can be verbatim in a page about another CRA: without this line's code or ISIN it is not a fact."""
    li = credit_line(codigo="CRA-0260000X", status="unknown", flags=())
    facts = [{"field": "vencimento", "value": "15 de abril de 2032",
              "quote": "“Data de Vencimento dos CRA”: significa 15 de abril de 2032, ressalvadas"}]
    routes, created = exa_routes(facts, TERMO + "\nCódigo CETIP dos CRA: 0999999Z\n")
    http = FakeHttp(routes)
    sec = run(investigator(http, exa=ExaClient(http, "k", sleep=lambda s: None)), [li])
    assert sec["facts"] == [] and len(created) == 2
    assert sec["discarded"]["by_reason"]["documento_sem_identificador"]["count"] == 2


def test_exa_run_that_never_finishes_is_a_note_not_a_failure():
    t = [0.0]

    def mono():
        t[0] += 50
        return t[0]

    http = FakeHttp({"api.exa.ai/agent/runs": lambda p, b: js({"id": "agent_run_1", "status": "running"})})
    exa = ExaClient(http, "k", sleep=lambda s: None, monotonic=mono, max_wait_s=90)
    with pytest.raises(SourceError) as e:
        exa.agent_run("q", "s", {})
    assert e.value.code == "exa_tempo_esgotado"


# --- budget --------------------------------------------------------------------------------------------

def test_budget_five_per_trigger_and_twenty_per_report():
    b = R.Budget(deadline_s=None)
    b.start()
    for _ in range(3):
        b.start_trigger()
        for _ in range(5):
            b.charge("x")
        with pytest.raises(R.BudgetExhausted) as e:
            b.charge("x")
        assert e.value.scope == "trigger"
    b.start_trigger()
    for _ in range(5):
        b.charge("x")
    with pytest.raises(R.BudgetExhausted) as e:
        b.charge("x")
    assert e.value.scope == "report" and b.used_report == 20


def test_report_limit_message_and_every_trigger_keeps_a_line():
    lines = [credit_line(line_no=i) for i in range(1, 13)]  # 12 triggers x 2 searches > 20
    sec = run(investigator(FakeHttp(fnet_routes())), lines)
    assert sec["searches_used"] == 20
    msgs = [t["message"] for t in sec["triggers"]]
    assert msgs[-1] == "limite de 20 buscas atingido; a conferir" and all(msgs)
    assert "limite_buscas" in sec["reason_codes"]


def test_deadline_stops_the_searches():
    t = [0.0]

    def mono():
        t[0] += 100
        return t[0]

    sec = run(investigator(FakeHttp(fnet_routes()), budget=R.Budget(deadline_s=150, monotonic=mono)),
              [credit_line(), credit_line(line_no=12)])
    assert R.MSG_DEADLINE in [x["message"] for x in sec["triggers"]]


# --- cache ---------------------------------------------------------------------------------------------

def test_a_document_is_read_once_and_kept_by_id_and_text_hash():
    cache = MemoryDocumentCache()
    http = FakeHttp(fnet_routes())
    run(investigator(http, cache=cache), [credit_line()])
    sec = run(investigator(http, cache=cache), [credit_line()])
    downloads = [c for c in http.calls if "downloadDocumento" in c["url"]]
    assert len(downloads) == 1 and cache.hits == 1 and cache.misses == 1
    assert sec["documents_consulted"][0]["cache"] == "hit"
    # the listing is re-queried in every report
    assert sum(1 for c in http.calls if "pesquisarGerenciadorDocumentosDados" in c["url"]) == 2


def test_bundle_cache_hands_new_documents_to_the_worker_and_serves_valid_preloads():
    c = BundleDocumentCache()
    doc = c.put("fnet", "1001", TERMO)
    assert doc.key == cache_key("fnet", "1001", sha256_text(TERMO))
    assert c.pending() == {doc.key: TERMO.encode("utf-8")}
    good = BundleDocumentCache({doc.key: TERMO.encode("utf-8"), "docs/fnet/9/" + "0" * 64 + ".txt": b"forged"})
    assert good.get("fnet", "1001").text == TERMO and good.get("fnet", "9") is None and good.pending() == {}
    with pytest.raises(ValueError):
        cache_key("fnet", "../x", "0" * 64)


# --- FIP and movement ----------------------------------------------------------------------------------

FIP_CNPJ = "90000000000700"
DF = ("Demonstrações contábeis. O Fundo tem como principal ativo a participação na COMPANHIA ALVO SINTETICA S.A. "
      "detendo 28,02% das ações ON e 28,04% das ações PN do seu capital, totalizando 28,03%.")


def fip_extractor(system, user, schema):
    return {"facts": [
        {"field": "empresa_investida", "value": "COMPANHIA ALVO SINTETICA S.A.",
         "quote": "a participação na COMPANHIA ALVO SINTETICA S.A. detendo 28,02%", "subject": None},
        {"field": "participacao_pct", "value": "28,03%", "quote": "do seu capital, totalizando 28,03%.",
         "subject": "COMPANHIA ALVO SINTETICA S.A."}]}


def test_fip_reads_the_newest_periodic_report_that_reads():
    rows = [doc_row(2001, "Informes Periódicos", "Informe Anual Estruturado", "28/09/2026 15:23", "02/2026"),
            doc_row(2002, "Informes Periódicos", "Demonstrações Financeiras", "22/09/2026 17:17", "28/02/2026"),
            doc_row(2003, "Informes Periódicos", "Informe Mensal Estruturado ", "29/09/2026 10:00", "08/2026"),
            doc_row(2004, "Assembleia", "AGO", "30/09/2026 10:00", "30/09/2026")]
    http = FakeHttp(fnet_routes(fund_rows=rows, docs={2002: DF}))  # 2001 does not download
    sec = run(investigator(http, mdl=models(extractor=fip_extractor)), [fund_line(4, FIP_CNPJ, "FIP", "fip")])
    assert [f["tier"] for f in sec["facts"]] == ["A", "A"]
    assert sec["facts"][1]["value"] == "28,03%" and sec["facts"][1]["fnet_id"] == 2002
    st = {d["fnet_id"]: d["status"] for d in sec["documents_consulted"]}
    assert st == {2001: "não lido", 2002: "lido"}
    fund_call = next(c for c in http.calls if "pesquisar" in c["url"])
    assert fund_call["params"]["cnpjFundo"] == FIP_CNPJ and "paginaCertificados" not in fund_call["params"]


def test_forte_movement_reads_fato_relevante_of_the_month():
    rows = [doc_row(3001, "Fato Relevante", "", "10/09/2026 18:00", "10/09/2026"),
            doc_row(3002, "Fato Relevante", "", "10/01/2026 18:00", "10/01/2026")]
    text = "FATO RELEVANTE. A Administradora comunica a amortização extraordinária de cotas do Fundo."

    def mv(system, user, schema):
        return {"facts": [{"field": "evento", "value": "amortização extraordinária de cotas",
                           "quote": "A Administradora comunica a amortização extraordinária de cotas do Fundo.",
                           "subject": None}]}

    http = FakeHttp(fnet_routes(fund_rows=rows, docs={3001: text}))
    doc = {"movement": {"month": "2026-09-01", "investigator_trigger_line_nos": [5]}}
    sec = run(investigator(http, mdl=models(extractor=mv)), [fund_line(5, "90000000000800")], doc)
    assert sec["triggers"][0]["kind"] == "movimento_forte" and sec["facts"][0]["fnet_id"] == 3001


# --- privacy -------------------------------------------------------------------------------------------

SENTINELS = ("SENTINELA", "987654", "555444", "141093", "C9", "[TITULAR]", "IPCA + 8,74%")


def test_nothing_from_the_statement_leaves_the_engine():
    """URLs, query parameters, request bodies and every LLM prompt carry public identifiers only."""
    li = credit_line(codigo="CRA-0260000X", status="unknown", flags=())
    seen = []

    def rec_extract(system, user, schema):
        seen.append(user)
        return credit_extractor(system, user, schema)

    def rec_judge(system, user, schema):
        seen.append(user)
        return {"supported": True}

    routes, _ = exa_routes([{"field": "vencimento", "value": "15/04/2032",
                             "quote": "Série 1ª, taxa IPCA + 8,7400%, vencimento 15/04/2032"}], TERMO)
    http = FakeHttp({**fnet_routes(fund_rows=[doc_row(2002, "Informes Periódicos", "Demonstrações Financeiras")],
                                   docs={2002: DF}), **routes})
    exa = ExaClient(http, "k", sleep=lambda s: None)
    inv = investigator(http, mdl=models(extractor=rec_extract, judge=rec_judge), exa=exa)
    run(inv, [li, credit_line(line_no=12), fund_line(4, FIP_CNPJ, "FIP", "fip")])
    outgoing = [json.dumps(c, ensure_ascii=False, default=str) for c in http.calls] + seen
    assert len(outgoing) > 8
    for blob in outgoing:
        for s in SENTINELS:
            assert s not in blob, (s, blob[:200])


# --- engine and server wiring --------------------------------------------------------------------------

def test_engine_off_by_default_is_not_applicable_and_on_runs_last():
    stmt = read_statement(TEMPLATE)
    client = FakeClient(load_fake_rows(FAKE_ROWS), clock=CLOCK)
    off = run_engine(stmt, client, default_params(stmt.position_date), clock=CLOCK)
    assert off["schema_version"] == "1.14" and off["investigation"]["status"] == "not_applicable"
    assert off["section_status"]["investigation"]["reason_codes"] == ["investigador_desligado"]
    assert list(off).index("investigation") == list(off).index("equivalents") + 1

    client = FakeClient(load_fake_rows(FAKE_ROWS), clock=CLOCK)
    routes, _ = exa_routes([{"field": "vencimento", "value": "15 de abril de 2032",
                             "quote": "“Data de Vencimento dos CRA”: significa 15 de abril de 2032, ressalvadas"}], TERMO)
    http = FakeHttp({**fnet_routes(fund_rows=[]), **routes})
    inv = investigator(http, exa=ExaClient(http, "k", sleep=lambda s: None))
    on = run_engine(stmt, client, default_params(stmt.position_date), clock=CLOCK, investigator=inv)
    sec = on["investigation"]
    kinds = {t["kind"] for t in sec["triggers"]}
    assert "credito_vencimento_diverge" in kinds and "movimento_forte" in kinds
    cra = next(t for t in sec["triggers"] if t["kind"] == "credito_vencimento_diverge")
    assert cra["identifiers"]["codigo"] == "0260000X" and "isin" not in cra["identifiers"]
    assert on["section_status"]["investigation"]["status"] == sec["status"]
    # the earlier sections are untouched by the investigator
    for k in ("identification", "fees", "tax", "returns"):
        assert on[k] == off[k]


def test_a_failing_investigator_never_fails_the_report():
    class Boom:
        def run(self, *a):
            raise RuntimeError("x")

    stmt = read_statement(TEMPLATE)
    doc = run_engine(stmt, FakeClient(load_fake_rows(FAKE_ROWS), clock=CLOCK), default_params(stmt.position_date),
                     clock=CLOCK, investigator=Boom())
    assert doc["investigation"]["status"] == "unknown"
    assert doc["investigation"]["reason_codes"] == ["investigador_falhou"]


def test_from_env_is_off_unless_asked_and_degrades_without_keys(monkeypatch):
    assert R.from_env({}) is None
    inv = R.from_env({"SILO_INVESTIGATOR": "on", "SILO_LLM_PROVIDER": "fake"})
    assert inv is not None and inv.deps.exa is None and inv.deps.exa_note == R.MSG_NO_EXA
    assert inv.deps.models.extractor is None
    with_key = R.from_env({"SILO_INVESTIGATOR": "on", "EXA_API_KEY": "k", "SILO_LLM_PROVIDER": "fake"})
    assert with_key.deps.exa is not None and isinstance(with_key.deps.cache, BundleDocumentCache)


def test_server_bundle_carries_the_documents_for_the_worker():
    from src.portfolio import server, trace

    rec = trace.RunRecord(start_ns=1, end_ns=2, status=200, stage="pdf")
    rec.documents = {"docs/fnet/1001/" + sha256_text(TERMO) + ".txt": TERMO.encode("utf-8")}
    bundle = json.loads(server.trace_bundle(trace.build_trace(rec), rec))
    assert list(bundle["documents"]) == list(rec.documents)


def test_a_maturity_of_another_series_is_not_called_a_divergence():
    t = R.manual_trigger(1, "CRA", isin=ISIN, credit={"matched": True, "data_vencimento": "2036-02-15", "numero_serie": 3})
    other = R._cross_check(t, "vencimento", "17 de fevereiro de 2031", "CRA da Primeira Série")
    same = R._cross_check(t, "vencimento", "15 de fevereiro de 2036", "CRA da Terceira Série")
    assert other["agrees"] is None and "série 1" in other["note"] and same["agrees"] is True
    assert R._series_of("1ª série") == 1 and R._series_of("série 2") == 2 and R._series_of("Emissora") is None


def test_tier_a_matches_the_value_on_word_boundaries():
    text = "(xvii) Classificação de Risco: a emissão recebeu a nota AAA(bra) da agência sintética."
    quote = "Classificação de Risco: a emissão recebeu a nota AAA(bra)"
    assert assess("rating", "AA", quote, text, None).tier == TIER_C
    assert assess("rating", "AAA(bra)", quote, text, None).tier == TIER_A


def test_a_network_failure_is_a_note_on_its_item_and_the_others_keep_their_facts():
    routes = fnet_routes()
    calls = {"n": 0}

    def flaky_listar(params, payload):
        calls["n"] += 1
        if calls["n"] == 2:
            raise SourceError("rede_falhou", "TimeoutError")
        if calls["n"] == 3:
            raise OSError("socket")
        return routes["listarFundos"](params, payload)

    http = FakeHttp({**routes, "listarFundos": flaky_listar})
    sec = run(investigator(http), [credit_line(1), credit_line(2), credit_line(3)])
    ok, net, boom = sec["triggers"]
    assert ok["fact_ids"] and not net["fact_ids"] and not boom["fact_ids"]
    assert net["notes"] == ["Fundos.NET: rede_falhou"] and "OSError" in boom["notes"][0]
    assert sec["status"] == "partial"


def test_no_public_identifier_means_no_web_search():
    li = fund_line(4, None, "FIP", "fip")
    li.cnpj = None
    http = FakeHttp({})
    exa = ExaClient(http, "k", sleep=lambda s: None)
    sec = run(investigator(http, exa=exa), [li])
    assert not http.calls and "nenhum identificador público" in sec["triggers"][0]["notes"][-1]


def test_rad_reads_the_original_escritura_and_newest_aditamentos_within_the_cap():
    rows = [{"protocol": f"P{i}", "delivery_date": f"2026-0{i}-01", "category": "Escrituras e aditamentos de debêntures",
             "source_url": f"https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx?p={i}"} for i in range(1, 8)]
    client = FakeClient({"company_events": [{"match": {"p_id": "90000000000900"}, "rows": rows}]})
    li = credit_line(codigo="DEB-EXMP11", status="unknown", flags=(), tipo="debênture")
    li.issuer_cnpj = "90000000000900"
    for cap, expected in ((1, ["P1"]), (3, ["P1", "P6", "P7"])):
        http = FakeHttp({"rad.cvm.gov.br": lambda p, b: HttpResponse(200, "text/plain", TERMO.encode())})
        inv = investigator(http)
        inv.deps.max_docs_per_trigger = cap
        sec = run(inv, [li], client=client)
        assert [d["rad_protocol"] for d in sec["documents_consulted"]] == expected
        assert sec["searches_by_kind"] == {"rad_escrituras": 1}


def test_a_fip_asks_for_the_newest_page_only_and_a_movement_for_its_window():
    http = FakeHttp(fnet_routes(fund_rows=[]))
    doc = {"movement": {"month": "2026-11-01", "investigator_trigger_line_nos": [5]}}
    run(investigator(http), [fund_line(4, FIP_CNPJ, "FIP", "fip"), fund_line(5, "90000000000800")], doc)
    fip, mv = [c["params"] for c in http.calls if "pesquisar" in c["url"]]
    assert fip["o[0][dataEntrega]"] == "desc" and "dataInicial" not in fip
    assert mv["dataInicial"] == "01/11/2026" and mv["dataFinal"] == "31/01/2027" and mv["o[0][dataEntrega]"] == "asc"


def test_fnet_reader_walks_again_when_ties_reorder_a_page():
    rows = [doc_row(i, "Informes Periódicos") for i in range(1, 401)]
    walks = {"n": 0}

    def unstable(params, _):
        s = int(params["s"])
        if s == 0:
            walks["n"] += 1
        page = rows[s:s + 200]
        if walks["n"] == 1 and s == 200:
            page = [rows[0]] + page[1:]  # a tie served twice, one id missing: walk again
        return js({"data": page, "recordsTotal": 400})

    got = FnetReader(FakeHttp({"pesquisarGerenciadorDocumentosDados": unstable})).documents(cnpj=FIP_CNPJ)
    assert len(got) == 400 and walks["n"] == 2


def test_fnet_reader_refuses_a_short_listing():
    def short(params, _):
        return js({"data": [doc_row(1, "Termo de Securitização")], "recordsTotal": 3})

    with pytest.raises(SourceError) as e:
        FnetReader(FakeHttp({"pesquisarGerenciadorDocumentosDados": short})).documents(id_fundo=1, certificados=True)
    assert e.value.code == "fnet_listagem_incompleta"


@pytest.mark.parametrize("served, codigo, expected", [
    (ISIN, "CRA0260025T", ISIN),            # the served ISIN is used for a CETIP-coded line
    ("NÃO TEM", "CRA0260025T", None),       # a filed non-ISIN is never a search term
    ("00000", f"CRA-{ISIN}", ISIN),         # ... and the statement's own ISIN is used instead
    (None, "CRA0260025T", None),
])
def test_only_an_isin_shaped_value_is_the_fundos_net_term(served, codigo, expected):
    li = credit_line(codigo=codigo)
    li.credit["cd_isin"] = served
    li.credit["code"] = codigo.removeprefix("CRA-")
    [t] = R.find_triggers([li], {})
    assert t.identifiers.get("isin") == expected
