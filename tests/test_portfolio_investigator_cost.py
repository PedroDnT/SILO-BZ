"""Engine 1.12, offline: the investigator under the report's single US$1.00 cap (owner, #605 Q37), its cost in
X-Silo-Cost-Usd and the trace, the demo shipping with it off, and the coordinator's site (owner's addendum).
Synthetic data only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.portfolio.client import FakeClient, load_fake_rows
from src.portfolio.investigator import coordinators
from src.portfolio.investigator import extract as ex
from src.portfolio.investigator import run as R
from src.portfolio.investigator.sources import ExaClient
from src.portfolio.report.llm import CostMeter, validate_output
from tests.test_portfolio_investigator import (
    FAKE_ROWS,
    ISIN,
    ROOT,
    TEMPLATE,
    TERMO,
    FakeHttp,
    credit_extractor,
    credit_line,
    doc_row,
    exa_routes,
    fnet_routes,
    investigator,
    models,
    run,
)


class CostlyProvider:
    """A provider that checks and books on its meter like the real ones (US$0.12 per call)."""

    def __init__(self, meter, model, responder, role, cost=0.12):
        self.meter, self.model, self._r, self.role, self.cost = meter, model, responder, role, cost
        self.served_by = []

    def complete(self, system, user, schema=None):
        self.meter.check(self.model, len(system) + len(user), 3000)  # worst case US$0.15 or more, above the 0.12 booked
        self.meter.book(self.role, self.model, self.cost, input_tokens=10, output_tokens=5)
        return validate_output(schema, self._r(system, user, schema))


def test_the_investigator_books_on_the_reports_meter_and_stops_at_its_share():
    report = CostMeter()
    share = ex.ShareMeter(report)
    assert share.cap_usd == ex.INVESTIGATOR_SHARE_USD == 0.30 and report.cap_usd == 1.00
    mdl = ex.pair(CostlyProvider(share, "extrator-x", credit_extractor, "investigator_extractor"), None, share)
    sec = run(investigator(FakeHttp(fnet_routes()), mdl=mdl), [credit_line(line_no=i) for i in (1, 2, 3, 4)])
    msgs = [t["message"] for t in sec["triggers"]]
    # two extractions fit the US$0.30 share (0.12 each); the third would pass it, so the investigator stops
    assert all(m.endswith("fato(s) com citação (nível A: 2; nível B: 0)") for m in msgs[:2])
    assert msgs[2] == msgs[3] == R.MSG_LIMIT_COST
    assert report.spent_usd == pytest.approx(0.24) and share.spent_usd == pytest.approx(0.24)
    assert {c["role"] for c in report.calls} == {"investigator_extractor"}
    assert sec["costs"]["usd"] == pytest.approx(0.24) and sec["costs"]["share_cap_usd"] == 0.30
    assert sec["costs"]["report_cap_usd"] == 1.00
    # at least US$0.70 of the report's cap stays for the Redator and the Revisor
    assert report.cap_usd - report.spent_usd >= 0.70


def test_a_report_meter_already_spent_stops_the_investigator_too():
    report = CostMeter()
    report.book("redator", "x", 0.95)
    share = ex.ShareMeter(report)
    mdl = ex.pair(CostlyProvider(share, "extrator-x", credit_extractor, "investigator_extractor"), None, share)
    sec = run(investigator(FakeHttp(fnet_routes()), mdl=mdl), [credit_line()])
    assert sec["triggers"][0]["message"] == R.MSG_LIMIT_COST and report.spent_usd == pytest.approx(0.95)


def test_exa_is_priced_before_and_booked_after_on_the_same_meter():
    report = CostMeter()
    share = ex.ShareMeter(report)
    routes, _ = exa_routes([], TERMO)
    exa = ExaClient(FakeHttp(routes), "k", sleep=lambda s: None, meter=share)
    exa.agent_run("q", "s", {})  # the fake run reports costDollars.total 0.05
    exa.contents("https://x.example/doc")  # no costDollars: the list price, US$0.001
    assert [c["role"] for c in report.calls] == ["investigator_exa", "investigator_exa"]
    assert report.spent_usd == pytest.approx(0.051) and share.by_role["investigator_exa"] == pytest.approx(0.051)
    share.spent_usd = 0.29
    with pytest.raises(ex.CostShareSpent):
        exa.agent_run("q", "s", {})  # US$0.025 would pass the share


def test_server_cost_header_and_trace_include_the_investigator(monkeypatch):
    from src.portfolio import server, trace

    monkeypatch.setenv(server.TOKEN_ENV, "tok")
    monkeypatch.setenv("SILO_LLM_PROVIDER", "fake")

    def stub_pdf(html_text, out_path):
        Path(out_path).write_bytes(b"%PDF-1.7\n% stub\n")
        return Path(out_path)

    monkeypatch.setattr(server, "html_to_pdf", stub_pdf)

    class Booking:
        def __init__(self, meter):
            self.meter = meter

        def run(self, lines, doc, client, clock):
            share = ex.ShareMeter(self.meter)
            share.book("investigator_extractor", "gpt-5.1", 0.2, input_tokens=100, output_tokens=50)
            share.book("investigator_exa", "exa-agent", 0.025)
            return R.not_run_section("sem_gatilho_investigador")

    app = server.create_app(client_factory=lambda: FakeClient(load_fake_rows(FAKE_ROWS)),
                            investigator_factory=lambda meter: Booking(meter)).test_client()
    r = app.post("/diagnose", data=TEMPLATE.read_bytes(), headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200, r.data[:200]
    assert float(r.headers["X-Silo-Cost-Usd"]) == pytest.approx(0.225)
    tid = r.headers[server.TRACE_HEADER]
    bundle = json.loads(app.get(f"/trace/{tid}", headers={"Authorization": "Bearer tok"}).data)
    spans = bundle["trace"]["resourceSpans"][0]["scopeSpans"][0]["spans"]

    def attrs(name):
        span = next(s for s in spans if s["name"] == name)
        return {a["key"]: next(iter(a["value"].values())) for a in span["attributes"]}

    inv = attrs("invoke_agent investigator")
    assert inv["gen_ai.agent.name"] == "investigator" and inv["app.cost_usd"] == pytest.approx(0.225)
    assert inv["app.exa.calls"] == "1" and inv["gen_ai.request.model"] == "gpt-5.1"
    assert trace.root_attributes(bundle["trace"])["app.cost_usd"] == pytest.approx(0.225)
    assert attrs("invoke_agent redator")["app.cost_usd"] == 0.0  # the investigator is not counted twice


def test_the_deployed_demo_ships_with_the_investigator_off():
    text = (ROOT / "deploy" / "cloudflare" / "wrangler.jsonc").read_text(encoding="utf-8")
    assert '"SILO_INVESTIGATOR": "off"' in text


# --- the coordinator's site ---------------------------------------------------------------------------

COORD_YAML = """coordinators:
  - cnpj: "90000000001000"
    names: ["BANCO COORDENADOR SINTETICO S.A"]
    domains: ["ofertas.coordenador-sintetico.com.br"]
    status: aprovada
    evidence: "https://ofertas.coordenador-sintetico.com.br/ (synthetic)"
    checked_on: "2026-10-05"
  - cnpj: null
    names: ["OUTRO BANCO PROPOSTO S.A"]
    domains: ["outro-banco.com.br"]
    status: proposta
    evidence: "https://outro-banco.com.br/ofertas (synthetic)"
    checked_on: "2026-10-05"
"""
ANUNCIO = ("ANÚNCIO DE INÍCIO da oferta de CRA. O BANCO COORDENADOR SINTETICO S.A., inscrito no CNPJ sob o nº "
           "90.000.000/0010-00, na qualidade de Coordenador Líder, comunica o início da distribuição.")


def coord_extractor(system, user, schema):
    if "Coordenador Líder" in json.loads(user)["text"]:
        return {"facts": [{"field": "coordenador", "value": "BANCO COORDENADOR SINTETICO S.A.",
                           "quote": "O BANCO COORDENADOR SINTETICO S.A., inscrito no CNPJ", "subject": None}]}
    return {"facts": []}


def test_an_approved_coordinator_domain_is_searched_first_and_labelled(tmp_path):
    path = tmp_path / "coordinators.yaml"
    path.write_text(COORD_YAML, encoding="utf-8")
    routes, created = exa_routes([{"field": "vencimento", "value": "15 de abril de 2032",
                                   "quote": "“Data de Vencimento dos CRA”: significa 15 de abril de 2032, ressalvadas",
                                   "url": "https://ofertas.coordenador-sintetico.com.br/cra/termo.pdf"}],
                                 TERMO + f"\nISIN {ISIN}\n")
    listing = [doc_row(1005, "Documentos de Oferta de Distribuição Pública", "Anúncio de Início de Distribuição Pública")]
    http = FakeHttp({**fnet_routes(listing_rows=listing, docs={1005: ANUNCIO}), **routes})
    inv = investigator(http, mdl=models(extractor=coord_extractor), exa=ExaClient(http, "k", sleep=lambda s: None))
    inv.deps.coordinators_path = path
    sec = run(inv, [credit_line()])
    t = sec["triggers"][0]
    # the coordinator fact alone is not "found": the web fallback runs, with its domain listed first
    assert t["coordinator"]["domains"] == ["ofertas.coordenador-sintetico.com.br"]
    assert t["coordinator"]["list_status"] == "aprovada"
    sp = created[0]["systemPrompt"]
    assert sp.index("ofertas.coordenador-sintetico.com.br") < sp.index("cvm.gov.br")
    web = next(f for f in sec["facts"] if f["field"] == "vencimento")
    assert web["source_type"] == "web_coordenador" and web["tier"] == "A"


def test_a_proposed_coordinator_is_never_used(tmp_path):
    path = tmp_path / "coordinators.yaml"
    path.write_text(COORD_YAML, encoding="utf-8")
    entries = coordinators.load(path)
    assert coordinators.approved_domains("OUTRO BANCO PROPOSTO S.A.", entries) == []
    assert coordinators.proposed_match("OUTRO BANCO PROPOSTO S.A.", entries)
    assert coordinators.approved_domains("cnpj 90.000.000/0010-00", entries) == ["ofertas.coordenador-sintetico.com.br"]
    # the repository's file loads, and nothing in it is approved yet: the owner reviews the proposals
    real = coordinators.load()
    assert real and all(c.status == "proposta" for c in real) and all(c.evidence.startswith("http") for c in real)
    bad = tmp_path / "bad.yaml"
    bad.write_text(COORD_YAML.replace("status: aprovada", "status: ok"), encoding="utf-8")
    with pytest.raises(ValueError):
        coordinators.load(bad)
