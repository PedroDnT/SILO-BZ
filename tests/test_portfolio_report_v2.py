"""Report v2 presentation fixes (#765): page 1 in the reader's order, the cost over the portfolio, "% do CDI" as n/a with
one footnote, no internal words in the reader's text, and the Revisor removing a finding that restates the risk table."""

from __future__ import annotations

import copy
import html
import json
import re
from pathlib import Path

import pytest

from src.portfolio.report import adapt, build, render, revisor
from src.portfolio.report.redator import Finding

DEMO = Path(__file__).parent / "fixtures" / "portfolio" / "demo_engine_output.json"

# Words of the engine and the pipeline that must never reach the reader (#765, item F)
INTERNAL_TERMS = ("parked", "empty_shell", "threshold", "unknown", "nao_avaliado")


@pytest.fixture(scope="module")
def view() -> dict:
    return adapt.to_view(json.loads(DEMO.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def report_html(view) -> str:
    html_text, _ = build.build(copy.deepcopy(view), "fake")
    return html_text


def visible_text(html_text: str) -> str:
    body = re.sub(r"<(style|svg|script)\b.*?</\1>", " ", html_text, flags=re.S | re.I)
    return html.unescape(re.sub(r"<[^>]+>", " ", body))


def page_one(html_text: str) -> str:
    start = html_text.index('<section class="brief"')
    return html_text[start:html_text.index("</section>", start)]


@pytest.mark.parametrize("term", INTERNAL_TERMS)
def test_no_internal_word_reaches_the_reader(report_html, term):
    assert term not in visible_text(report_html).lower()


def test_page_one_is_in_the_readers_order(report_html):
    p1 = visible_text(page_one(report_html))
    heads = ["Quanto custa", "Retorno contra o CDI", "O que pede atenção", "Não avaliado"]
    assert [p1.index(h) for h in heads] == sorted(p1.index(h) for h in heads)


def test_page_one_lists_attention_rows_one_line_each_and_never_says_nothing_to_check(view, report_html):
    p1 = page_one(report_html)
    rows = [r for r in view["risks"]["rows"] if r.get("status") == "avaliado" and r.get("severity") in ("atencao", "moderado")]
    assert rows
    assert "não apontaram ponto a conferir" not in p1 and "Nenhuma linha da tabela de riscos" not in p1
    items = re.findall(r"<li>(.*?)</li>", p1.split("O que pede atenção")[1].split("</ul>")[0], re.S)
    assert 0 < len(items) <= render.PAGE_ONE_ATTENTION_LINES
    assert "Mais " in p1 and 'href="#s-o-que-pede-atencao"' in p1  # the demo has more rows than fit
    assert not any("Movimento anormal de cota" in li for li in items)  # its level is the table-only one
    assert sum("limite do FGC" in li or "FGC: emissores" in li for li in items) == 1  # never twice


def test_page_one_says_nothing_needs_attention_only_when_no_row_does(view):
    calm = copy.deepcopy(view)
    for r in calm["risks"]["rows"]:
        r["severity"] = "baixo"
    calm.get("concentration", {}).get("fgc", {})["issuers"] = []
    calm["restatements"] = {"items": []}
    calm.get("movement", {})["strong"] = []
    html_text, _ = build.build(calm, "fake")
    assert "Nenhuma linha da tabela de riscos ficou em atenção ou moderado" in page_one(html_text)


def test_page_one_has_no_redator_text(report_html):
    assert 'class="achado"' not in page_one(report_html)


def test_cost_headline_states_its_coverage_of_the_portfolio(view, report_html):
    sm = view["fees"]["summary"]
    totals_cov = sm["coverage_fixed_portfolio_pct"]
    assert totals_cov is not None and totals_cov < 50  # the demo's fixed fee covers about 17% of the portfolio
    p1 = visible_text(page_one(report_html))
    assert "custo conhecido só para" in p1 and "da carteira" in p1
    assert 'class="numero">R$' not in page_one(report_html).split("faixa divulgada")[0]


def test_cost_headline_shows_the_value_big_when_coverage_is_half_or_more(view):
    big = copy.deepcopy(view)
    big["fees"]["summary"]["coverage_fixed_portfolio_pct"] = 80.0
    html_text, _ = build.build(big, "fake")
    assert "cobre 80,00% da carteira" in visible_text(page_one(html_text))


def test_pct_of_cdi_empty_is_na_with_one_footnote(view):
    v2 = copy.deepcopy(view)
    reason = "só para fundo com índice de referência CDI ou DI arquivado"
    n = 0
    for ln in v2["returns"]["lines"]:
        for w in ln.get("windows") or []:
            if w.get("id") == "12m" and w.get("status") == "avaliado":
                w["pct_of_cdi"], w["pct_of_cdi_reason"] = None, reason
                n += 1
    assert n >= 2
    html_text, _ = build.build(v2, "fake")
    body = html_text[html_text.index('<table class="ret-cdi">'):]
    table = body[:body.index("</table>")]
    assert reason not in table and table.count(">n/a<") == n
    section = html_text.split("<h2>Retorno passado contra o CDI</h2>")[1].split("</section>")[0]
    assert visible_text(section).count(reason) == 1  # the annex's detail table keeps its own per-line reasons


def _risk_finding(text: str, title: str = "Risco") -> Finding:
    return Finding("f1", "riscos", title, text, ["p1"])


def test_revisor_removes_a_finding_that_restates_the_risk_table(view):
    eng = copy.deepcopy(view)
    eng.setdefault("provenance", []).append({"id": "p1", "source": "CVM"})
    f = _risk_finding("{{risks.rows[2].risk}} está em {{risks.rows[2].value_pct}} da carteira.")
    kept, removals = revisor.check_finding(eng, f)
    assert kept is None and removals[-1].reason == revisor.RESTATES_RISK_TABLE


def test_revisor_keeps_one_sentence_per_risk_finding(view):
    eng = copy.deepcopy(view)
    eng.setdefault("provenance", []).append({"id": "p1", "source": "CVM"})
    f = _risk_finding("As duas linhas tratam do mesmo emissor. A tabela mostra o resto.")
    kept, removals = revisor.check_finding(eng, f)
    assert kept is not None and kept.text == "As duas linhas tratam do mesmo emissor."
    assert any(r.reason == "mais de uma frase por achado" for r in removals)
