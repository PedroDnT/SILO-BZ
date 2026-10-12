"""RJ document-link collector (#845): parsing, the polite client, the site list
and the per-site harvest. Offline: saved HTML fixtures and httpx.MockTransport.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.parse import urlsplit
from unittest.mock import patch
from urllib.parse import urlsplit

import httpx
import pytest

from src.fetchers.rj import client as rj_client
from src.fetchers.rj.client import FetchError, PoliteClient, RobotsDisallowed
from src.fetchers.rj.parse import case_links, classify_tipo, cnj_numbers, parse_case_page
from src.fetchers.rj.sites import SITES
from src.pipeline import ingest_rj
from src.pipeline.ingest_rj import EmptySiteError, RJIngestor, harvest_site

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "rj"
SEEN = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)

# What each fixture holds (read 2026-10-12): cases on the list page, the case
# page's process number and its document links.
EXPECTED = {
    "marquesadmjudicial.com.br": (50, "00128226620198160185", 78),
    "cataliseaj.com.br": (42, "50035729420208210072", 84),
    "flaviocardosoadv.com.br": (28, "55033580920238090029", 52),
    "recupereadmjudicial.com.br": (3, "50247401420268240023", 17),
    "scalzilliaj.com.br": (83, "50098563820248210021", 55),
    "mpbadmjudicial.com.br": (22, "10050354620228110041", 1),
    "lasproconsultores.com.br": (197, "10004845020238260306", 0),
    "administradorjudicial.adv.br": (25, "50029393220208240062", 117),
    # Batch 1, read 2026-10-12. n2wbrasil lists 6 cases, 1 of them a recuperação judicial; cb2d lists
    # 72, 30 of them recuperação judicial; trustdobrasil's list page holds 4 RJ cases.
    "pmmadv.com.br": (14, "11559062020248260100", 17),
    "n2wbrasil.com.br": (1, "10001656420258260354", 12),
    "trustdobrasil.com.br": (4, "11155260420148260100", 29),
    "cb2d.com.br": (30, "50038749820228210090", 24),
    "integrarecuperacaojudicial.com.br": (17, "00198130520258172001", 2),
    "valorizeadmjudicial.com.br": (18, "10435294320238110041", 10),
    "jscadministracaojudicial.com.br": (6, "00147714320258272729", 2),
    "recuperasolucoes.com": (8, "00099716220268172810", 5),
    "pbbadvogados.com.br": (104, "00334388120158130251", 1),
    "tpaj.com.br": (11, "50130793820268240023", 1),
    "costapaivasantiago.com.br": (5, "50037171620238130672", 12),
    "administradorajudicial.adv.br": (25, "50233417120258210021", 17),
    "mvbrecuperacoesjudiciais.com.br": (23, "08158040420238190021", 7),
    "fontanaexperts.com.br": (8, "40984543020268260100", 7),
    "scalzilliedias.com.br": (10, "07200514920268020001", 12),
    "atrioconsultores.com.br": (3, "08022340820248180032", 14),
    "actionaj.com.br": (5, "40000604220268260373", 15),
    "fvsadmj.com.br": (3, "10398814220258260114", 2),
    "excelia-aj.com.br": (27, "10124090620178260451", 64),
    "expertisemais.com.br": (31, "10943620220228260100", 67),
    "tapxure.com.br": (9, "10008254320258260359", 8),
    "erikasantiago.adv.br": (10, "50010497720178130027", 4),
    # Batch 6, read 2026-10-12.
    "k2consultoria.com": (27, "00214130320198190001", 11),
    "bbsadvogados.com.br": (57, "00015183120238160185", 29),
    "madgav.com.br": (2, "10026767720268130672", 15),
    "rroadvogados.adv.br": (1, "09649089620248190001", 29),
    "fraj.com.br": (85, "10081715320188260565", 9),
    "rlg-aj.com.br": (13, "50114607620258210028", 18),
    "clesciogalvao.adv.br": (2, "50020627320188130384", 7),
    "fatorfiscal.com.br": (3, "00011573120188080017", 35),
    # Batch 8, read 2026-10-12. Diligence lists 47 cards, 26 of them recuperação judicial (one is the
    # site's template); LRF lists 78, 51 of them recuperação judicial or extrajudicial; stenius reads
    # only the /rj-<name>/ posts of its first page.
    "julianamorais.com.br": (25, "00909041720168130342", 12),
    "stenius.com.br": (8, "57759089220258090014", 3),
    "diligence.adm.br": (26, "01089231520258172001", 19),
    "lrflideres.com.br": (51, "00007422920178173090", 76),
    "inova-aj.com.br": (16, "00122399620218190001", 110),
}


def _fixture(domain: str, kind: str) -> str:
    return (FIX / f"{domain}__{kind}.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def test_cnj_numbers_printed_and_bare():
    text = "Processo nº 0012822-66.2019.8.16.0185 e incidente 1001190-70.2020.8.26.0069"
    assert cnj_numbers(text) == ["00128226620198160185", "10011907020208260069"]
    assert cnj_numbers("Processo: 50942334920248240023") == ["50942334920248240023"]
    # Twenty digits with no "processo" label are not a process number.
    assert cnj_numbers("arquivo_50942334920248240023.pdf") == []


@pytest.mark.parametrize("title,section,tipo", [
    ("Petição Inicial", "", "peticao_inicial"),
    ("1. Pet. Inicial", "", "peticao_inicial"),
    ("Plano de Recuperação Judicial", "", "plano"),
    ("Aditivo ao Plano de Recuperação Judicial", "", "aditivo_plano"),
    ("Relatório Mensal de Atividades - Agosto/2024", "", "rma"),
    ("Agosto/2024", "Relatórios Mensais", "rma"),
    ("Quadro Geral de Credores", "", "qgc"),
    ("Ata da Assembleia Geral de Credores", "", "ata_agc"),
    ("Edital de Convocação da Assembleia Geral de Credores", "", "edital_agc"),
    ("Edital do art. 52, §1º e art. 7, §1º da Lei 11.101/2005", "", "relacao_credores_devedor"),
    ("Edital do art. 7º, §2º - Relação de Credores do Administrador Judicial", "", "relacao_credores_aj"),
    ("Relação de Credores", "", "relacao_credores_devedor"),
    ("Decisão que deferiu o processamento da Recuperação Judicial", "", "decisao_deferimento"),
    ("2.- Decisão Deferimento RJ", "", "decisao_deferimento"),
    ("3.- PRJ", "", "plano"),
    ("Relatório de cumprimento do PRJ", "", "outros"),
    ("Sentença de concessão da recuperação judicial", "", "sentenca_concessao"),
    ("Balanço Patrimonial 2023", "", "demonstracoes_contabeis"),
    ("Decisão deferimento RJ", "", "decisao_deferimento"),
    ("Decisão de deferimento da Recuperação Judicial e nomeação da Administradora Judicial", "", "decisao_deferimento"),
    ("Pedido de Recuperação Judicial", "", "peticao_inicial"),
    ("Edital 5003717-16.2023.8.13.0672-Relacao Credores", "", "relacao_credores_devedor"),
    ("1° Edital de Credores", "", "relacao_credores_devedor"),
    ("2° Edital de Credores Retificado", "", "relacao_credores_aj"),
    ("Decisão Deferimento RJ AFA Plásticos", "", "decisao_deferimento"),
    ("Despacho que determinou perícia prévia", "", "outros"),
    ("Decisão de deferimento da recuperação judicial - 20.02.2024", "", "decisao_deferimento"),
    ("Deferimento do pedido de Recuperação Judicial", "", "decisao_deferimento"),
    ("Decisão de Processamento da RJ", "", "decisao_deferimento"),
    ("Homologação do Plano de Recuperação Judicial, conforme art. 58 da Lei 11.101/05", "", "sentenca_concessao"),
    ("Lista de Credores AJ - Comercial Mabruk Ltda.", "", "relacao_credores_aj"),
    ("Decisão de deferimento da prorrogação do stay period da recuperação judicial", "", "outros"),
    ("1. Relatorio inicial de atividades", "", "rma"),
    ("3. Edital art. 7, par. segundo", "", "relacao_credores_aj"),
    ("1. Edital art. 52, par. primeiro", "", "relacao_credores_devedor"),
    ("Decisão - Deferimento da Recuperação Judicial e Nomeação FEX", "", "decisao_deferimento"),
    ("Decisão - Deferimento de Tutela Cautelar", "", "outros"),
    ("Decisão de deferimento de Recuperação Judicial: 08.09.2022;", "", "decisao_deferimento"),
    ("DECISAO - DEFERIMENTO RJ", "", "decisao_deferimento"),
    ("CARLOS PERES DECISAO DEF PROC RJ E NOMEACAO TAPXURE", "", "decisao_deferimento"),
    ("Decisão homologatória concedendo a recuperação judicial", "", "sentenca_concessao"),
    ("Relatório Inicial da Administradora Judicial;", "", "outros"),
])
def test_classify_tipo(title, section, tipo):
    assert classify_tipo(title, section) == tipo


@pytest.mark.parametrize("site", SITES, ids=lambda s: s.domain)
def test_fixture_pages_parse(site):
    n_cases, numero, n_docs = EXPECTED[site.domain]
    links = case_links(_fixture(site.domain, "list"), site.list_urls[0], site.case_pattern, site.case_text, site.case_card)
    assert len(links) == n_cases
    hosts = {urlsplit(link).hostname for link in links}
    assert all(h == site.domain or h.endswith("." + site.domain) for h in hosts), hosts
    cp = parse_case_page(_fixture(site.domain, "case"), links[0], site.doc_pattern, site.debtor_xpath,
                         site.debtor_from_title)
    assert cp.numero_processo == numero
    assert cp.devedor_nome
    assert len(cp.documents) == n_docs
    assert len({d.url for d in cp.documents}) == n_docs  # one row per link
    assert all(d.titulo for d in cp.documents)


def test_actionaj_second_list_page_adds_five_more_cases():
    site = next(s for s in SITES if s.domain == "actionaj.com.br")
    first = case_links(_fixture(site.domain, "list"), site.list_urls[0], site.case_pattern)
    second = case_links(_fixture(site.domain, "list2"), site.list_urls[1], site.case_pattern)
    assert len(second) == 5 and not set(first) & set(second)


def test_download_button_takes_the_title_printed_beside_it():
    site = next(s for s in SITES if s.domain == "scalzilliedias.com.br")
    cp = parse_case_page(_fixture(site.domain, "case"), "https://scalzilliedias.com.br/processo/x/", site.doc_pattern)
    assert "Petição inicial" in {d.titulo for d in cp.documents}
    assert not any(d.titulo == "Download" for d in cp.documents)


def test_doubleone_title_comes_from_the_download_name():
    site = next(s for s in SITES if s.domain == "marquesadmjudicial.com.br")
    cp = parse_case_page(_fixture(site.domain, "case"), "https://marquesadmjudicial.com.br/processo/x__1",
                         site.doc_pattern)
    first = cp.documents[0]
    assert first.titulo == "Petição Inicial" and classify_tipo(first.titulo, first.section) == "peticao_inicial"


def test_every_site_is_html_and_allowed_by_the_inventory():
    with open(ROOT / "src/fetchers/rj/aj_sites.csv", encoding="utf-8", newline="") as fh:
        inventory = {r["domain"]: r for r in csv.DictReader(fh)}
    domains = [s.domain for s in SITES]
    assert len(domains) == len(set(domains))
    for s in SITES:
        row = inventory[s.domain]
        assert row["structure"] == "html", s.domain
        assert row["robots_ok"] != "no", s.domain
        assert s.source == f"aj_site:{s.domain}"


# ---------------------------------------------------------------------------
# The polite client
# ---------------------------------------------------------------------------
def _client(routes, sleeps=None):
    def handler(request: httpx.Request) -> httpx.Response:
        assert "SILO-BZ" in request.headers["user-agent"]
        return routes(request)
    clock = iter(range(0, 10_000))
    return PoliteClient(transport=httpx.MockTransport(handler),
                        sleep=(sleeps.append if sleeps is not None else lambda s: None),
                        clock=lambda: float(next(clock)) * 0.25)


def test_robots_disallow_is_never_fetched():
    seen = []

    def routes(req):
        seen.append(req.url.path)
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /privado\n")
        return httpx.Response(200, text="ok")

    c = _client(routes)
    with pytest.raises(RobotsDisallowed):
        c.get("https://aj.example/privado/caso")
    assert c.get("https://aj.example/processos").text == "ok"
    assert "/privado/caso" not in seen


def test_non_200_raises_and_missing_robots_allows():
    def routes(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(503)

    with pytest.raises(FetchError) as e:
        _client(routes).get("https://aj.example/processos")
    assert e.value.status == 503


def test_one_request_per_second_per_host():
    sleeps: list = []
    c = _client(lambda req: httpx.Response(200, text="x"), sleeps)
    c.get("https://aj.example/a")
    c.get("https://aj.example/b")
    assert sleeps and all(s <= rj_client.MIN_INTERVAL_S for s in sleeps)


def test_status_falls_back_to_get_when_head_is_refused():
    def routes(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(405 if req.method == "HEAD" else 200)

    assert _client(routes).status("https://aj.example/doc.pdf") == 200


# ---------------------------------------------------------------------------
# Harvest and the watchdog
# ---------------------------------------------------------------------------
class _FixtureClient:
    """Serves the list fixture, the case fixture for the first two cases, and fails the rest."""

    def __init__(self, site, fail_after=2):
        self.site, self.fail_after, self.cases = site, fail_after, 0

    def get(self, url):
        if url in self.site.list_urls:
            return rj_client.Page(url, 200, _fixture(self.site.domain, "list"))
        self.cases += 1
        if self.cases > self.fail_after:
            raise FetchError(url, 500)
        return rj_client.Page(url, 200, _fixture(self.site.domain, "case"))

    def status(self, url):
        return 200

    def close(self):
        pass


def test_harvest_counts_failed_case_pages_and_keeps_the_rest():
    site = next(s for s in SITES if s.domain == "recupereadmjudicial.com.br")
    h = harvest_site(site, _FixtureClient(site), SEEN)
    assert h.case_pages == 2 and len(h.failed_pages) == 1
    assert {c["numero_processo"] for c in h.cases} == {"50247401420268240023"}
    assert all(c["source"] == "aj_site:recupereadmjudicial.com.br" for c in h.cases)
    assert all(d["found_on"].startswith("https://recupereadmjudicial.com.br/") for d in h.documents)
    assert all("first_seen_at" not in r for r in h.cases + h.documents)  # set once by the DEFAULT


def test_a_list_page_failure_raises():
    site = SITES[0]

    class Down(_FixtureClient):
        def get(self, url):
            raise FetchError(url, 502)

    with pytest.raises(FetchError):
        harvest_site(site, Down(site), SEEN)


class _Ingestor(RJIngestor):
    def __init__(self, stored, client):
        self._pg, self._head_budget, self._stored, self._client = object(), 10, stored, client
        self._client_factory = lambda: client

    def _stored_cases(self, source):
        return self._stored

    def _unchecked_documents(self, source, limit):
        return []


def test_watchdog_fails_a_site_that_lost_its_cases():
    site = next(s for s in SITES if s.domain == "recupereadmjudicial.com.br")

    class NoCases(_FixtureClient):
        def get(self, url):
            return rj_client.Page(url, 200, "<html><body>Em manutenção</body></html>")

    with patch.object(ingest_rj, "upsert_rows", side_effect=AssertionError("must not write")):
        with pytest.raises(EmptySiteError):
            _Ingestor(stored=3, client=NoCases(site))._collect_sync(site, SEEN)


def test_failed_case_pages_end_the_site_as_error_with_its_rows():
    site = next(s for s in SITES if s.domain == "recupereadmjudicial.com.br")
    written = {}

    def fake_upsert(pg, table, rows, conflict_columns=None):
        written[table] = rows
        return len(rows)

    with patch.object(ingest_rj, "upsert_rows", side_effect=fake_upsert):
        out = _Ingestor(stored=0, client=_FixtureClient(site))._collect_sync(site, SEEN)
    assert out.status == "error" and "failed=1" in out.error
    assert out.rows == len(written["rj_case"]) + len(written["rj_document"]) > 0


def test_robots_follows_rfc_9309_on_errors():
    def routes_for(code):
        def routes(req):
            if req.url.path == "/robots.txt":
                return httpx.Response(code)
            return httpx.Response(200, text="ok")
        return routes

    assert _client(routes_for(403)).get("https://s3.example/doc.pdf").text == "ok"
    with pytest.raises(RobotsDisallowed):
        _client(routes_for(503)).get("https://aj.example/processos")


# ---------------------------------------------------------------------------
# Batch 1 parsing rules (#845)
# ---------------------------------------------------------------------------
def test_relative_links_follow_base_href_and_drop_the_fragment():
    page = ('<html><head><base href="https://www.aj.example/"></head><body>'
            '<a href="processos/rj/alfa#topo">Alfa</a><a href="/menu">Menu</a></body></html>')
    assert case_links(page, "http://aj.example/processos/rj", r"/processos/rj/[^/]+$") == [
        "https://www.aj.example/processos/rj/alfa"]


def test_download_links_take_their_title_from_the_text_before_them():
    page = ('<p>:: Plano - <a href="/f/plano.pdf"><b>DOWNLOAD AQUI</b></a><br>'
            ':: Edital - <a href="/f/edital.pdf">Baixar</a></p>')
    cp = parse_case_page(page, "https://aj.example/c", r"/f/")
    assert [d.titulo for d in cp.documents] == ["Plano", "Edital"]


def test_a_utf8_page_with_a_legacy_encoded_file_name_keeps_the_bytes():
    resp = httpx.Response(200, content=b'<a href="a-art-52-\xe2\xa71o.pdf">Edital \xc3\xa7</a>')
    assert rj_client.decode_body(resp) == '<a href="a-art-52-%E2%A71o.pdf">Edital ç</a>'
    trust = next(s for s in SITES if s.domain == "trustdobrasil.com.br")
    cp = parse_case_page(_fixture(trust.domain, "case"), "https://www.trustdobrasil.com.br/x", trust.doc_pattern)
    assert any("%E2%A71o" in d.url for d in cp.documents)
    assert not any("�" in d.url for d in cp.documents)


def test_mixed_lists_keep_only_the_case_type_the_site_names():
    cb2d = next(s for s in SITES if s.domain == "cb2d.com.br")
    page = _fixture(cb2d.domain, "list")
    assert len(case_links(page, cb2d.list_urls[0], cb2d.case_pattern)) == 72
    assert len(case_links(page, cb2d.list_urls[0], cb2d.case_pattern, cb2d.case_text)) == 30
def test_icon_only_links_are_titled_from_the_file_name_and_rows_can_be_links():
    # FVS: the case list rows carry the URL in onclick; the document anchors hold only an icon.
    site = next(s for s in SITES if s.domain == "fvsadmj.com.br")
    cp = parse_case_page(_fixture(site.domain, "case"), site.list_urls[0], site.doc_pattern)
    assert [d.titulo for d in cp.documents] == ["Deferimento recuperacao CHAMA", "LISTA DE CREDORES"]


def test_batch8_card_text_keeps_the_recuperacao_cards_and_second_page_adds_more():
    dil = next(s for s in SITES if s.domain == "diligence.adm.br")
    page = _fixture(dil.domain, "list")
    assert len(case_links(page, dil.list_urls[0], r"^https://diligence\.adm\.br/processos/[a-z0-9-]+/$")) == 47
    assert len(case_links(page, dil.list_urls[0], dil.case_pattern, dil.case_text, dil.case_card)) == 26
    # Without ``card`` the link text (empty on these cards) cannot tell the types apart.
    assert case_links(page, dil.list_urls[0], dil.case_pattern, dil.case_text) == []
    st = next(s for s in SITES if s.domain == "stenius.com.br")
    first = case_links(_fixture(st.domain, "list"), st.list_urls[0], st.case_pattern)
    second = case_links(_fixture(st.domain, "list2"), st.list_urls[1], st.case_pattern)
    assert len(second) == 5 and not set(first) & set(second)


def test_batch8_parse_rules():
    # A typographic hyphen inside the process number (Inova prints it so).
    assert cnj_numbers("Processo nº 0012239\u201096.2021.8.19.0001") == ["00122399620218190001"]
    # A "Download" button takes the heading above it, not a paragraph from the page header.
    site = next(s for s in SITES if s.domain == "julianamorais.com.br")
    cp = parse_case_page(_fixture(site.domain, "case"), site.list_urls[0], site.doc_pattern, site.debtor_xpath)
    assert cp.devedor_nome == "Auto Center"
    assert cp.documents[0].titulo == "Pedido de Recuperação Judicial"
    inova = next(s for s in SITES if s.domain == "inova-aj.com.br")
    cp = parse_case_page(_fixture(inova.domain, "case"), inova.list_urls[0], inova.doc_pattern)
    assert cp.devedor_nome == "Cimento Tupi"

