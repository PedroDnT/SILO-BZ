"""resolve_rj (#846): search one AJ domain for one case; accept only a page printing its number."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.fetchers.rj import client as rj_client
from src.fetchers.rj.client import FetchError, RobotsDisallowed
from src.pipeline.resolve_rj import Resolution, candidates, masked, resolve_case

SEEN = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
NUMERO = "50247401420268240023"

SEARCH = """<html><body><header><a href="/">Home</a><a href="/contato/">Contato</a></header>
<main><article><a href="https://aj.example.com.br/processos/empresa-x/">Empresa X Ltda</a></article>
<article><a href="https://aj.example.com.br/processos/empresa-y/">Empresa Y Ltda</a></article>
<a href="https://outro.example.org/x/">fora</a><a href="/page/2/">próxima</a><a href="/?s=x">busca</a></main></body></html>"""

CASE_X = """<html><head><title>Empresa X Ltda</title></head><body><h1>Empresa X Ltda</h1>
<p>Processo nº 1000832-35.2025.8.24.0359</p><a href="/wp-content/uploads/plano-x.pdf">Plano de Recuperação Judicial</a></body></html>"""

CASE_Y = """<html><head><title>Empresa Y Ltda</title></head><body><h1>Empresa Y Ltda</h1>
<p>Processo nº 5024740-14.2026.8.24.0023 - 1ª Vara Regional de Falências</p>
<a href="/wp-content/uploads/rma-y.pdf">RMA agosto</a><a href="/wp-content/uploads/qgc-y.pdf">Quadro Geral de Credores</a>
<a href="/politica-de-privacidade/">Privacidade</a></body></html>"""


class _Site:
    def __init__(self, pages, robots_block=()):
        self.pages, self.robots_block, self.calls = pages, robots_block, []

    def get(self, url):
        self.calls.append(url)
        if any(url.startswith(b) for b in self.robots_block):
            raise RobotsDisallowed(url)
        if url not in self.pages:
            raise FetchError(url, 404)
        return rj_client.Page(url, 200, self.pages[url])


def test_masked_prints_the_cnj_form():
    assert masked(NUMERO) == "5024740-14.2026.8.24.0023"


def test_candidates_keep_same_domain_content_links_only():
    got = candidates(SEARCH, "https://aj.example.com.br/?s=x", "aj.example.com.br")
    assert got == ["https://aj.example.com.br/processos/empresa-x/", "https://aj.example.com.br/processos/empresa-y/"]


def test_results_inside_article_come_before_the_menu():
    # acfb.com.br, 2026-10-13: the whole content area carries a "search" class, and its
    # menu links came first in page order, so the one real result was never tried.
    page = """<html><body><div class="cmsms_search"><div class="menu"><a href="/project/falencia/">Falência</a>
    <a href="/processos/">Processos</a><a href="/contato/">Contato</a></div>
    <article><header><h3><a href="https://aj.example.com.br/empresa-y-ltda-2/">Empresa Y Ltda</a></h3></header></article>
    </div><footer><a href="/quem-somos/">Quem somos</a></footer></body></html>"""
    got = candidates(page, "https://aj.example.com.br/?s=x", "aj.example.com.br")
    assert got == ["https://aj.example.com.br/empresa-y-ltda-2/"]


def test_only_the_page_printing_the_number_is_accepted():
    site = _Site({
        f"https://aj.example.com.br/?s={masked(NUMERO)}": SEARCH,
        "https://aj.example.com.br/processos/empresa-x/": CASE_X,
        "https://aj.example.com.br/processos/empresa-y/": CASE_Y,
    })
    out = Resolution()
    assert resolve_case(site, NUMERO, "aj.example.com.br", "AJ Exemplo Ltda", SEEN, out)
    [case] = out.harvest.cases
    assert case["numero_processo"] == NUMERO and case["source"] == "aj_site:aj.example.com.br"
    assert case["aj_case_url"] == "https://aj.example.com.br/processos/empresa-y/"
    assert case["aj_name"] == "AJ Exemplo Ltda"
    assert {d["tipo"] for d in out.harvest.documents} == {"rma", "qgc"}
    assert all(d["numero_processo"] == NUMERO for d in out.harvest.documents)


def test_a_case_not_found_writes_nothing():
    site = _Site({f"https://aj.example.com.br/?s={masked(NUMERO)}": SEARCH,
                  "https://aj.example.com.br/processos/empresa-x/": CASE_X})
    out = Resolution()
    assert not resolve_case(site, NUMERO, "aj.example.com.br", "AJ", SEEN, out)
    assert out.harvest.cases == [] and out.harvest.documents == []


@pytest.mark.parametrize("block", ["https://aj.example.com.br/?s="])
def test_robots_disallowing_the_search_stops_quietly(block):
    site = _Site({}, robots_block=(block,))
    out = Resolution()
    assert not resolve_case(site, NUMERO, "aj.example.com.br", "AJ", SEEN, out)
    assert site.calls == [f"https://aj.example.com.br/?s={masked(NUMERO)}"]


def test_an_empty_page_is_not_found_and_does_not_stop_the_run():
    # behrmannratis.com, 2026-10-13: the search answered 200 with an empty body, and
    # lxml's "Document is empty" ended the whole run before it wrote anything.
    search = f"https://aj.example.com.br/?s={masked(NUMERO)}"
    assert not resolve_case(_Site({search: ""}), NUMERO, "aj.example.com.br", "AJ", SEEN, Resolution())
    site = _Site({search: SEARCH, "https://aj.example.com.br/processos/empresa-x/": "",
                  "https://aj.example.com.br/processos/empresa-y/": CASE_Y})
    assert resolve_case(site, NUMERO, "aj.example.com.br", "AJ", SEEN, Resolution())


def test_the_workflow_runs_the_resolver_after_djen():
    from pathlib import Path
    wf = (Path(__file__).resolve().parents[1] / ".github/workflows/rj_collect.yml").read_text()
    assert wf.index("- name: Discover RJ cases on DJEN") < wf.index("- name: Resolve DJEN cases on their AJ sites")
    assert "python -m src.pipeline.resolve_rj" in wf
