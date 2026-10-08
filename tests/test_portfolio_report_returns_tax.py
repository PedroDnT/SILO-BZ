"""The report's returns (engine 1.10), tax (engine 1.11) and ETF fee peers (catalog v66): adapter, renderer, Revisor.

Synthetic data only: the demo engine fixture and positions built in the test; no real statement is read.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from src.portfolio.client import FakeClient
from src.portfolio.common import REASON_TEXT
from src.portfolio.fee_peers import ETF_PEER_KEYS, compute_fee_peers
from src.portfolio.identify import LineId
from src.portfolio.report import adapt, build, redator, render, revisor, values
from src.portfolio.report.redator import Finding
from src.portfolio.statement import Position, parse_rows
from src.portfolio.tax import compute_tax

ENGINE = Path(__file__).parent / "fixtures" / "portfolio" / "demo_engine_output.json"
D = dt.date(2026, 9, 30)


@pytest.fixture(scope="module")
def engine() -> dict:
    return json.loads(ENGINE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def view(engine) -> dict:
    return adapt.to_view(engine)


@pytest.fixture(scope="module")
def html(view) -> str:
    return build.build(view, "fake")[0]


def section(html_text: str, title: str) -> str:
    return html_text.split(f"<h2>{title}</h2>")[1].split("</section>")[0]


def text_of(fragment: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment))


# --- returns: adapter ------------------------------------------------------------------------------------------------


def test_returns_view_copies_every_figure_and_reshapes_windows_into_a_citable_list(engine, view):
    rv = view["returns"]
    assert [w["id"] for w in rv["windows"]] == ["12m", "6m"]
    assert [c["id"] for c in rv["coverage"]] == ["12m", "6m"]
    assert rv["coverage"][0]["coverage_portfolio_value_pct"] == engine["returns"]["coverage"]["12m"]["coverage_portfolio_value_pct"]
    for ln_e, ln_v in zip(engine["returns"]["lines"], rv["lines"]):
        assert ln_v["line_id"] == f"L{ln_e['line_no']}" and ln_v["value_brl"] == ln_e["valor_brl"]
        for w_v in ln_v["windows"]:
            w_e = ln_e["windows"][w_v["id"]]
            for k in ("net_return_pct", "cdi_pct", "net_minus_cdi_pp", "volatility_annual_pct", "max_drawdown_pct",
                      "fee_per_point", "sharpe_drag", "gross_return_est_pct"):
                assert w_v[k] == w_e[k], k
    # a path with "12m" in it could not be a placeholder; the list index can
    assert values.resolve(view, "returns.lines[1].windows[0].net_return_pct") == engine["returns"]["lines"][1]["windows"]["12m"]["net_return_pct"]
    assert values.resolve(view, "returns.lines[1].windows.12m.net_return_pct") is values.MISSING


def test_returns_view_has_no_portfolio_total_and_only_fixed_reason_texts(view):
    rv = view["returns"]
    assert not any(k for k in rv if "total" in k or "mean" in k or "median" in k or "rank" in k)
    for ln in rv["lines"]:
        if ln["status"] != "avaliado":
            assert ln["reason"] == REASON_TEXT[ln["reason_code"]]
        if ln["fee"]["reason_code"]:
            assert ln["fee"]["reason"] == REASON_TEXT[ln["fee"]["reason_code"]]
        for w in ln["windows"]:
            assert "sources" not in w and (w["reason"] is None or w["reason"] == REASON_TEXT[w["reason_code"]])


def test_returns_sources_are_named_and_dated(view):
    assert view["data_dates"]["BCB"] == "2026-09-30"  # the CDI, SGS 12
    tools = {p["endpoint"]: p["source"] for p in view["provenance"]}
    assert tools["api.macro_series"] == "BCB" and tools["api.fund_nav"] == "CVM" and tools["api.quote_history"] == "B3"


def test_lines_without_a_return_or_a_tax_rule_are_gaps_grouped_by_code(view):
    gaps = {(g["title"], g["text"]): g["line_ids"] for g in view["gaps"]}
    assert gaps[("Retorno por posição", REASON_TEXT["retorno_credito_sem_serie"].rstrip(". "))] == ["L9", "L10", "L11", "L12"]
    assert gaps[("Taxa e imposto por posição", REASON_TEXT["imposto_sem_regra"].rstrip(". "))] == ["L1", "L6"]
    assert all(g["value_brl"] is None for g in view["gaps"] if g["title"] in ("Retorno por posição", "Taxa e imposto por posição"))
    # the section-level code is the same lines again, so it is not printed twice
    assert not any(t == REASON_TEXT["linhas_sem_retorno"] for _, t in gaps)


def test_a_missing_window_keeps_its_position_and_a_failed_window_is_a_gap(engine):
    eng = copy.deepcopy(engine)
    ln = eng["returns"]["lines"][1]
    del ln["windows"]["12m"]
    ln["windows"]["6m"].update(status="nao_avaliado", status_label="não avaliado", reason_code="serie_incompleta")
    v = adapt.to_view(eng)
    wins = v["returns"]["lines"][1]["windows"]
    assert [w["id"] for w in wins] == ["12m", "6m"] and wins[0]["status"] == "nao_avaliado" and wins[0]["reason"]
    assert wins[1]["reason"] == REASON_TEXT["serie_incompleta"]
    gap = next(g for g in v["gaps"] if g["text"] == REASON_TEXT["serie_incompleta"].rstrip(". "))
    assert gap["line_ids"] == ["L2"] and gap["title"] == "Retorno por posição"


# --- returns: renderer -----------------------------------------------------------------------------------------------


def test_returns_section_shows_each_window_beside_the_cdi_and_never_a_total(html):
    sec = section(html, "Retorno por posição em detalhe")
    txt = text_of(sec)
    for needle in ("26,00%", "12,27%", "14,42%", "6,91%", "11,58 p.p.", "-6,64 p.p.", "09/2025 a 09/2026", "03/2026 a 09/2026",
                   "30/09/2025 a 30/09/2026", "12 observações; estimativa ruidosa", "-7,83%", "03/2026 a 07/2026",
                   "taxa por ponto: 0,204442", "perda de Sharpe: 0,1948",
                   "não aplicável: volatilidade anualizada abaixo de 1% a.a.",  # the cash-like fund (L7)
                   "fora de qualquer média ou ranking",  # L3's 6-month fee per point, gross below zero
                   REASON_TEXT["retorno_tesouro_sem_serie"], REASON_TEXT["sem_taxa_utilizavel"], REASON_TEXT["taxa_nao_aplicavel"],
                   "sem total da carteira", "estimativa", "retorno do período de 6 meses, não anualizado",
                   "taxa por ponto: taxa do período dividida pelo retorno bruto estimado do período"):
        assert needle in txt, needle
    # engine 1.13: "% do CDI" only where the engine wrote it (a fund whose filed benchmark is CDI or DI)
    table = text_of(sec.split("<table")[1].split("</table>")[0])
    assert len(re.findall(r"\d+,\d+% do CDI", table)) == 4 and "(e % do CDI)" in table
    assert "carteira rendeu" not in txt and "média dos retornos" not in txt


# --- tax: adapter ----------------------------------------------------------------------------------------------------


def test_tax_view_copies_the_engine_and_says_why_with_fixed_texts(engine, view):
    tv = view["tax"]
    assert "date_missing" not in tv["labels"] and tv["labels"]["info"] == "informativo; não é recomendação"
    assert "total" not in " ".join(tv)
    for ln_e, ln_v in zip(engine["tax"]["lines"], tv["lines"]):
        assert ln_v["line_id"] == f"L{ln_e['line_no']}"
        assert ln_v["fee"].get("per_year_brl") == ln_e["fee"].get("per_year_brl")
        assert ln_v["tax"]["rate_today_pct"] == ln_e["tax"]["rate_today_pct"]
        assert ln_v["tax"]["estimate"]["tax_brl"] == ln_e["tax"]["estimate"]["tax_brl"]
        code = ln_e["tax"]["estimate"]["reason_code"]
        assert ln_v["tax"]["estimate"]["reason"] == (REASON_TEXT[code] if code else None)
        assert "rule_source" not in json.dumps(ln_v)
    assert tv["person"]["flags"][0]["line_ids"] == ["L2"]


# --- tax: renderer ---------------------------------------------------------------------------------------------------


def test_tax_section_on_the_demo(html):
    sec = section(html, "Taxa e imposto por posição")
    txt = text_of(sec)
    for needle in ("R$ 5.292,30 por ano", "R$ 2.081,71 a R$ 4.163,43 por ano", "estimativa", "15% (fundo de ações (FIA))",
                   "Lei 14.754/2023, art. 24", "isento (LCA)", "Lei 11.033/2004, art. 3º, IV",
                   "alíquota entre 15% e 22,5% conforme o prazo; data de aplicação não informada, a conferir",
                   "informativo; não é recomendação", "come-cotas", "Na pessoa física", "não calculado",
                   "Tributação mínima: depende da renda total anual; fora do escopo", REASON_TEXT["imposto_sem_regra"]):
        assert needle in txt, needle
    # no line of the demo prints an application date, so no R$ tax figure and no IOF line
    assert "sobre o ganho de 12 meses" not in txt and "<h3>IOF</h3>" not in sec
    assert "Previdência (PGBL e VGBL)" not in txt  # no pension line in the demo


def _pos(n, tipo, valor="100000", aplicacao=None, estrategia=None, classe=None):
    return Position(line_no=n, source_row=n, linha_extrato=f"Linha {n}", tipo=tipo, codigo=None, quantidade=None,
                    preco_unitario=None, valor=Decimal(valor), data_posicao=D, vencimento=None, taxa_texto=None,
                    estrategia_corretora=estrategia, classe_corretora=classe, data_aplicacao=aplicacao)


@pytest.fixture(scope="module")
def synthetic_tax_view() -> dict:
    """A FII with an application date and a 12-month return (the engine computes the R$ tax), a PGBL line, and a CDB
    bought ten days before the position date (IOF)."""
    positions = [_pos(1, "FII", "110000", aplicacao=dt.date(2024, 5, 2)),
                 _pos(2, "fundo", estrategia="Previdência PGBL", classe="Previdência"),
                 _pos(3, "CDB", aplicacao=dt.date(2026, 9, 20))]
    ret = {"lines": [{"line_no": 1, "basis": "close_sem_proventos",
                      "windows": {"12m": {"status": "avaliado", "net_return_pct": 10.0, "base_date": "2025-09-30"}},
                      "sources": []}]}
    tax = compute_tax([LineId(p) for p in positions], {"lines": []}, ret, D)
    return {"tax": adapt._tax_view({"tax": tax})}


def test_tax_in_reais_only_when_the_engine_computed_it(synthetic_tax_view):
    fii = synthetic_tax_view["tax"]["lines"][0]
    assert fii["tax"]["estimate"]["tax_brl"] == 2000.0
    txt = text_of(render._tax_section(synthetic_tax_view))
    assert "R$ 2.000,00 estimativa" in txt and "20,00% sobre o ganho de 12 meses de R$ 10.000,00 (retorno de 10,00%)" in txt
    cdb = text_of(render._tax_brl_html(synthetic_tax_view["tax"]["lines"][2]["tax"]))
    assert not re.search(r"R\$ \d", cdb) and REASON_TEXT["ganho_12m_indisponivel"] in cdb  # no 12-month return: no figure


def test_pension_shows_both_regimes_in_two_columns_and_picks_neither(synthetic_tax_view):
    sec = render._tax_section(synthetic_tax_view)
    txt = text_of(sec)
    assert "Previdência (PGBL e VGBL): os dois regimes, nenhum indicado" in txt
    assert "<th>Regime regressivo</th><th>Regime progressivo</th>" in sec
    assert "PGBL; imposto sobre valor total do resgate" in txt and "opção do participante; não informada" in txt
    assert "até 2 anos: 35,00%" in txt and "acima de 10 anos: 10,00%" in txt and "até — anos" not in txt
    assert "15% antecipado; ajuste anual pela tabela progressiva" in txt and "irretratável" in txt
    assert not re.search(r"\b(escolha|recomendamos|melhor regime)\b", txt, re.I)


def test_iof_only_when_present(synthetic_tax_view):
    txt = text_of(render._tax_section(synthetic_tax_view))
    assert "IOF L3: IOF regressivo nos primeiros 30 dias; a conferir" in txt
    assert txt.count("IOF regressivo nos primeiros 30 dias") == 1


# --- ETF fee peers (catalog v66) --------------------------------------------------------------------------------------


def test_engine_copies_the_etf_peer_split_as_served():
    stmt = parse_rows([["total_extrato", 100], ["linha_extrato", "tipo", "codigo", "quantidade", "preco_unitario", "valor",
                                                "data_posicao"], ["Fundo", "fundo", "08935128000159", 1, 100, 100, D]])
    li = LineId(stmt.positions[0], status="identified", kind="fund", cnpj="08935128000159", entity_type="fi", name="Fundo")
    fees = {"lines": [{"line_no": 1, "headline": {"origin": "extrato", "kind": "fixa", "stale": False, "as_of": "2026-07-31",
                                                  "rate_pct_year": 2}}]}
    row = dict(cnpj="08935128000159", classe_anbima="AÇÕES - ATIVO - DIVIDENDOS", fundo_cotas="N", tp_fundo_classe="FI",
               taxa_adm=2, fee_as_of="2026-07-31", comparison_as_of="2026-10-03", activity_from="2026-08-01",
               activity_to="2026-10-01", n_peers=34, n_excluded=2, peer_fee_oldest="2024-01-31", peer_fee_newest="2026-09-30",
               p25_pct_year=0.75, median_pct_year=1, p75_pct_year=1.5, percentile_pct=90, difference_pp=1,
               status="compared", reason_code=None, n_fund_peers=31, n_etf_peers=3, n_etf_excluded=1,
               etf_peer_tickers=["DIVD11", "DIVO11", "NDIV11"], etf_peer_fee_oldest="2026-09-01",
               etf_peer_fee_newest="2026-10-01", etf_peer_fee_source="etfsbrasil.com.br (site de terceiros, não é documento da CVM)")
    sec = compute_fee_peers([li], fees, FakeClient({"portfolio_fee_peers": [{"match": {}, "rows": [row]}]}),
                            dt.date(2026, 10, 3), Decimal(100))
    line = sec["lines"][0]
    assert line["status"] == "compared" and {k: line[k] for k in ETF_PEER_KEYS} == {k: row[k] for k in ETF_PEER_KEYS}


def test_etf_peers_are_counted_apart_and_labelled_not_a_recommendation(view, html):
    compared = next(r for r in view["fees"]["comparison"]["by_line"] if r["status"] == "compared")
    assert compared["n_fund_peers"] == 40 and compared["n_etf_peers"] == 0
    txt = text_of(html.split("Taxas versus fundos comparáveis")[1])
    assert "Dos pares: 40 fundos e 0 ETFs" in txt and "não é recomendação" in txt
    assert "incluem esses ETFs" not in txt
    v = copy.deepcopy(view)
    r = next(r for r in v["fees"]["comparison"]["by_line"] if r["status"] == "compared")
    r.update(n_fund_peers=31, n_etf_peers=3, n_etf_excluded=1, etf_peer_tickers=["DIVD11", "DIVO11", "NDIV11"],
             etf_peer_fee_oldest="2026-09-01", etf_peer_fee_newest="2026-10-01",
             etf_peer_fee_source="etfsbrasil.com.br (site de terceiros, não é documento da CVM)")
    txt = text_of(render._fee_comparison_html(v))
    assert "31 fundos e 3 ETFs (ETFs sem taxa utilizável, fora: 1)" in txt
    assert "a mediana, os quartis e o percentil acima incluem esses ETFs" in txt
    assert "ETFs: DIVD11, DIVO11, NDIV11" in txt and "site de terceiros" in txt and "01/09/2026 a 01/10/2026" in txt


def test_an_older_comparison_without_the_split_prints_no_etf_line(view):
    v = copy.deepcopy(view)
    for r in v["fees"]["comparison"]["by_line"]:
        for k in ETF_PEER_KEYS:
            r.pop(k, None)
    assert "Dos pares" not in render._fee_comparison_html(v)


# --- Redator and Revisor ---------------------------------------------------------------------------------------------


def F(text, section, cites=("p43",), title="Título"):
    return Finding("f1", section, title, text, list(cites))


def test_the_template_writer_covers_the_new_sections_and_passes_the_revisor(view):
    findings = redator._coerce_findings(redator.template_findings(redator.redator_view(view)))
    result = revisor.check(view, findings)
    kept = {f.section for f in result.kept}
    assert {"retornos", "impostos"} <= kept
    assert not [r for r in result.removed if r.section in ("retornos", "impostos")]
    for f in result.kept:
        if f.section in ("retornos", "impostos"):
            assert not re.search(r"\d", values.PLACEHOLDER_RE.sub("", f.text + f.title))
            assert "% do CDI" not in f.text and "total" not in f.text


@pytest.mark.parametrize("sec,text", [
    ("retornos", "A linha rendeu 26% em doze meses."),
    ("retornos", "O retorno da carteira foi de 12,5%."),
    ("retornos", "A linha {{returns.lines[1].line_id}} rendeu 103% do CDI."),
    ("impostos", "O imposto estimado é de R$ 2.000."),
    ("impostos", "A taxa da linha {{tax.lines[2].line_id}} custa 5292 reais por ano."),
])
def test_an_invented_number_in_the_new_sections_is_rejected(view, sec, text):
    res = revisor.check(view, [F(text, sec)])
    assert res.kept == [] and res.removed[0].reason in ("algarismo fora de marcador", "nenhuma frase restou")
    assert any(r.reason == "algarismo fora de marcador" for r in res.removed)


@pytest.mark.parametrize("ph,why", [
    ("returns.lines[1].windows[0].portfolio_return_pct", "sem caminho"),   # no such key: a total the engine never wrote
    ("returns.total_return_pct", "sem caminho"),
    ("returns.lines[1].windows.12m.net_return_pct", "sem caminho"),        # malformed: a key must start with a letter
    ("returns.lines[1].windows[0].pct_of_cdi", "nulo"),                    # a share: the engine wrote no "% do CDI"
    ("returns.lines[1].windows[0].total_pct_of_cdi", "sem caminho"),       # a key the engine never writes
    ("tax.lines[8].tax.estimate.tax_brl", "nulo"),                          # the engine computed no R$ tax for the line
    ("tax.total_tax_brl", "sem caminho"),
])
def test_a_placeholder_the_engine_did_not_write_is_rejected(view, ph, why):
    res = revisor.check(view, [F(f"Valor: {{{{{ph}}}}}. A linha {{{{returns.lines[1].line_id}}}} foi avaliada.", "retornos")])
    assert res.kept and res.kept[0].text == "A linha {{returns.lines[1].line_id}} foi avaliada."
    assert why in res.removed[0].reason


def test_engine_values_in_the_new_sections_are_kept(view):
    text = ("A linha {{returns.lines[1].line_id}} rendeu {{returns.lines[1].windows[0].net_return_pct}}, contra "
            "{{returns.lines[1].windows[0].cdi_pct}} do CDI: {{returns.lines[1].windows[0].net_minus_cdi_pp}}.")
    res = revisor.check(view, [F(text, "retornos", cites=("p44", "p43"))])
    assert res.removed == [] and res.kept[0].text == text
    t = "A linha {{tax.lines[9].line_id}} é {{tax.lines[9].tax.rate_text}} ({{tax.lines[9].tax.article}})."
    assert revisor.check(view, [F(t, "impostos", cites=("p17",))]).removed == []


def test_a_period_fee_is_set_against_the_annual_cap(view):
    v = copy.deepcopy(view)
    v["returns"]["lines"][2]["windows"][1]["fee_pct_period"] = 4.567891  # 6 months: 9,14% a.a.
    res = revisor.check(v, [F("Taxa do período: {{returns.lines[2].windows[1].fee_pct_period}}.", "retornos")])
    assert res.kept == [] and "valor extremo (fee)" in res.removed[0].reason


def test_a_large_past_return_is_not_an_exposure_but_a_fee_above_five_still_needs_a_second_path(view):
    v = copy.deepcopy(view)
    v["returns"]["lines"][1]["windows"][0]["net_return_pct"] = 87.123456
    res = revisor.check(v, [F("Retorno: {{returns.lines[1].windows[0].net_return_pct}}.", "retornos")])
    assert res.removed == []
    v["tax"]["lines"][2]["fee"]["rate_pct_year"] = 7.654321
    res = revisor.check(v, [F("Taxa: {{tax.lines[2].fee.rate_pct_year}}.", "impostos")])
    assert res.kept == [] and "valor extremo (fee)" in res.removed[0].reason


# Retroactive contribution (engine 1.15) -------------------------------------------------------------------------


def test_the_view_copies_the_contribution_per_window_with_line_ids_and_adds_no_total(view, engine):
    c = view["returns"]["contribution"]
    src = engine["returns"]["contribution"]["windows"]
    assert [w["id"] for w in c["windows"]] == ["12m", "6m"] and "retroativa" in c["label"]
    w = c["windows"][0]
    assert w["covered_return_pct"] == src["12m"]["covered_return_pct"] and w["n_lines"] == src["12m"]["n_lines"]
    assert [x["line_id"] for x in w["lines"]] == [f"L{x['line_no']}" for x in src["12m"]["lines"]]
    assert set(c) == {"label", "note", "windows"}  # no portfolio total, no ranking field


def test_the_report_shows_the_contribution_labelled_with_its_coverage(engine, view):
    html = render._contribution_html(view)
    assert "retroativa" in html and "não é o retorno da carteira" in html
    cov = values.format_value(view, "returns.contribution.windows[0].coverage_portfolio_value_pct")
    assert cov in html
    assert "p.p." in html  # contributions are in percentage points


def test_a_view_without_contribution_renders_nothing(view):
    v2 = copy.deepcopy(view)
    v2["returns"]["contribution"] = None
    assert render._contribution_html(v2) == ""


# Page 1, "Resumo para a reunião" (report restructure, stage 1) -----------------------------------------------


def _page1(view):
    html = render.render_html(view, render.Narrative(status="unknown"))
    return html, html.split('<section class="brief" id="resumo">')[1].split("</section>")[0]


def test_page_one_lists_points_to_check_by_name_from_engine_facts(view):
    _, page = _page1(view)
    assert "O que pede atenção" in page  # #765: the fixed points, then one line per risk row at atenção or moderado
    assert "Emissor acima do limite do FGC" in page and "BANCO EXEMPLO" in page  # an issuer, never an L-id
    assert "Informe reapresentado" in page and "Cota fora da faixa da classe" in page
    assert re.search(r"\bL\d+\b", page) is None
    assert len(render._points_to_check(view)) <= 4


def _restated_points(view):
    _, page = _page1(view)
    pts = page.split("O que pede atenção")[1].split("</ul>")[0]
    return [li for li in re.findall(r"<li>(.*?)</li>", pts, re.S) if "Informe reapresentado" in li]


def test_page_one_groups_the_restatements_of_one_fund_into_one_point(view):
    items = view["restatements"]["items"]
    assert len(items) == 3 and len({it["line_id"] for it in items}) == 1  # the demo: one FIDC, three informes
    pts = _restated_points(view)
    assert len(pts) == 1
    li = pts[0]
    assert "3 informes" in li and li.count(render.e(items[0]["fund_name"])) == 1
    comps = [values.format_value(view, f"restatements.items[{i}].competencia") for i in range(3)]
    assert [li.index(c) for c in comps] == sorted(li.index(c) for c in comps)  # the engine's order
    assert all(f"{c}: 2 campos" in li for c in comps)
    assert li.count(render.e(items[0]["assessment"])) == 1


def test_a_missing_field_count_reads_not_available_never_a_dash(view):
    v2 = copy.deepcopy(view)
    v2["restatements"]["items"][1]["n_fields_changed"] = None
    v2["restatements"]["items"][0]["n_fields_changed"] = 1
    li = _restated_points(v2)[0]
    c1 = values.format_value(v2, "restatements.items[1].competencia")
    assert f"{c1}: número de campos não disponível" in li
    assert "— campos" not in li and "None" not in li
    assert "1 campo;" in li and "1 campos" not in li  # singular


def test_page_one_shows_the_fixed_fee_and_the_range_side_by_side_never_summed(view):
    _, page = _page1(view)
    cost = page.split("<h3>Quanto custa</h3>")[-1].split("<h3>")[0]
    s = view["fees"]["summary"]
    for k in ("adm_disclosed_fixed_per_year_brl", "adm_disclosed_range_low_per_year_brl",
              "adm_disclosed_range_high_per_year_brl", "coverage_fixed_fund_value_pct", "coverage_range_fund_value_pct"):
        assert s[k] is not None and values.format_value(view, f"fees.summary.{k}") in cost
    assert cost.count('<td class="destaque">') == 2 and "não são somadas" in cost
    v2 = copy.deepcopy(view)
    for k in ("adm_disclosed_range_low_per_year_brl", "adm_disclosed_range_high_per_year_brl",
              "adm_disclosed_range_low_portfolio_pct", "adm_disclosed_range_high_portfolio_pct"):
        v2["fees"]["summary"][k] = None
    _, page2 = _page1(v2)
    cost2 = page2.split("<h3>Quanto custa</h3>")[-1].split("<h3>")[0]
    assert "nenhum fundo com faixa divulgada" in cost2 and "R$ 0,00" not in cost2


def test_the_fgc_caveat_appears_once_in_the_template_finding(view):
    f = next(f for f in redator.template_findings(view)["findings"] if "limite do FGC" in f["title"])
    html = render.substitute(view, f["title"] + " " + f["text"])
    assert html.count("a conferir") == 1


def test_page_one_states_the_cost_with_its_coverage_and_what_was_not_assessed(view):
    _, page = _page1(view)
    s = view["fees"]["summary"]
    assert values.format_value(view, "fees.summary.adm_disclosed_fixed_per_year_brl") in page
    # #765: the coverage of each known fee over the whole portfolio, and over the fund value in small type
    for k in ("coverage_fixed_portfolio_pct", "coverage_range_portfolio_pct", "coverage_fixed_fund_value_pct",
              "coverage_range_fund_value_pct"):
        assert values.format_value(view, f"fees.summary.{k}") in page
    assert "Não é o custo total" in page and "Não avaliado" in page
    assert s["adm_disclosed_fixed_per_year_brl"] is not None


def test_the_contents_links_point_to_sections_that_exist_and_the_aviso_has_its_anchor(view):
    html, page = _page1(view)
    targets = re.findall(r'href="#([^"]+)"', page)
    assert targets and all(f'id="{t}"' in html for t in targets)
    assert 'id="s-o-que-nao-foi-possivel-avaliar"' in html and '<h2 id="aviso">Aviso</h2>' in html


def test_the_appendix_no_longer_repeats_the_summary_findings(view):
    html = render.render_html(view, render.Narrative(status="complete", kept=[
        Finding(id="f1", section="resumo", title="T1", text="Texto do resumo.", citations=["p1"])]))
    assert html.count("Texto do resumo.") == 1  # page 1 only, not again in the appendix


# Reader text, report restructure stage 2 ---------------------------------------------------------------------------


def _reader_text(html):
    body = html.split("<main>")[1]
    return re.sub(r"<[^>]+>", " ", body)


@pytest.fixture(scope="module")
def built_demo(view):
    html, _ = build.build(view, "fake")
    return html


def test_the_reader_text_has_no_engine_codes_or_repo_paths(built_demo):
    t = _reader_text(built_demo)
    assert re.search(r"\bL\d+\b", t) is None  # a line is its name
    assert re.search(r"\[p\d", t) is None  # citations stay in the markup, not in the text
    assert "api." not in t and "nota #611" not in t and "src/portfolio" not in t


def test_citations_stay_in_the_markup_as_data(built_demo):
    assert re.search(r'class="achado" data-fontes="p\d', built_demo)
    assert 'data-consultas="' in built_demo


def test_a_line_is_named_by_its_instrument_and_not_doubled(view, built_demo):
    t = _reader_text(built_demo)
    assert "XP LIQUIDEZ FIC" in t
    assert "XP LIQUIDEZ FIC XP LIQUIDEZ FIC" not in t
    assert "<th>Nº no extrato</th>" in built_demo


def test_charts_keep_their_own_labels(view):
    html = "<p>L5</p><svg><text>L5</text></svg>"
    out = render._readable_lines(html, {"lines": [{"line_id": "L5", "instrument": "FUNDO X"}]})
    assert out == "<p>FUNDO X</p><svg><text>L5</text></svg>"


def test_two_lines_with_the_same_name_keep_their_statement_order():
    names = render._line_names({"lines": [{"line_id": "L1", "instrument": "CDB A"}, {"line_id": "L2", "instrument": "CDB A"},
                                          {"line_id": "L3", "instrument": "LCI B"}]})
    assert names["L1"] == "CDB A (linha 1 do extrato)" and names["L2"] == "CDB A (linha 2 do extrato)" and names["L3"] == "LCI B"


# Section order and the annex, report restructure stage 3 ---------------------------------------------------------


BODY_ORDER = ("Resumo para a reunião", "O que pede atenção", "Achados", "Quanto a carteira paga em taxas", "O que a carteira tem",
              "Concentração e liquidez", "Retorno passado contra o CDI", "Taxa e imposto por posição",
              "Informes reapresentados e movimento incomum", "O que não foi possível avaliar")
ANNEX = ("Resumo escrito pelo redator", "Como cada posição foi identificada", "Crédito direto no registro da CVM", "Detalhe da exposição", "Taxa por fundo", "Todos os riscos e seus limites",
         "Retorno por posição em detalhe", "ETF comparável (não é recomendação)", "Metodologia e limitações")


def test_the_body_answers_in_the_order_a_cio_asks_and_the_evidence_is_in_the_annex(built_demo):
    h2 = re.findall(r"<h2[^>]*>([^<]*)</h2>", built_demo)
    body = [t for t in h2 if t in BODY_ORDER]
    assert body == [t for t in BODY_ORDER if t in h2] and len(body) == len(BODY_ORDER)
    annex_html = built_demo.split('<details id="apendice">')[1].split("</details>")[0]
    assert [t for t in re.findall(r"<h2[^>]*>([^<]*)</h2>", annex_html)] == list(ANNEX)
    assert all(f"<h2>{t}</h2>" not in built_demo.split('<details id="apendice">')[0] for t in ANNEX)


def test_the_body_risk_table_has_four_columns_and_only_atencao_and_moderado_rows(view, built_demo):
    sec = built_demo.split("<h2>O que pede atenção</h2>")[1].split("</section>")[0]
    assert re.findall(r"<th[^>]*>([^<]*)</th>", sec) == ["Risco", "Valor", "Nível", "O que significa"]
    rows = view["risks"]["rows"]
    shown = {r["risk"] for r in rows if r["status"] == "avaliado" and r["severity"] in ("atencao", "moderado")}
    hidden = {r["risk"] for r in rows} - shown
    assert shown and all(render.e(x) in sec for x in shown)
    assert not any(render.e(x) in sec for x in hidden)
    assert "Limites" not in sec


def test_the_body_return_table_has_one_row_per_evaluated_position_and_no_total(view, built_demo):
    sec = built_demo.split("<h2>Retorno passado contra o CDI</h2>")[1].split("</section>")[0]
    first = sec.split("<table")[1].split("</table>")[0]
    assert re.findall(r"<th[^>]*>([^<]*)</th>", first) == ["Posição", "Retorno líquido em 12 meses", "CDI nas mesmas datas",
                                                           "Líquido menos CDI", "% do CDI"]
    evaluated = [ln for ln in view["returns"]["lines"] if ln["windows"][0]["status"] == "avaliado"]
    assert first.count("<tr>") - 1 == len(evaluated) and "retroativa" in sec and "6 meses" not in first


def test_the_body_return_table_shows_pct_of_cdi_or_the_engine_reason_never_zero_or_dash(view, built_demo):
    sec = built_demo.split("<h2>Retorno passado contra o CDI</h2>")[1].split("</section>")[0]
    rows = sec.split("<table")[1].split("</table>")[0].split("<tbody>")[1].split("</tr>")[:-1]
    evaluated = [ln["windows"][0] for ln in view["returns"]["lines"] if ln["windows"][0]["status"] == "avaliado"]
    assert len(rows) == len(evaluated)
    seen_value = seen_reason = False
    for w, row in zip(evaluated, rows):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        assert len(cells) == 5
        assert "p.p." in cells[3]  # the difference stays in percentage points, in its own column
        pct = cells[4]
        if w["pct_of_cdi"] is not None:
            assert values.format_value(w, "pct_of_cdi") in pct and "do CDI" in pct
            seen_value = True
        else:  # #765: "n/a" in the cell, the engine's reason once in the footnote (also for a share)
            assert pct.strip() == "n/a"
            reason = render.e(REASON_TEXT[w["pct_of_cdi_reason_code"]])
            assert reason not in rows[0] and sec.count(reason) == 1
            seen_reason = True
    assert seen_value and seen_reason


def test_the_contents_list_ends_with_the_annex(built_demo):
    toc = built_demo.split('<p class="toc">')[1].split("</p>")[0]
    assert toc.rstrip().endswith("Anexo: evidência linha a linha e metodologia</a>")
    assert 'href="#apendice"' in toc and 'id="apendice"' in built_demo


def _risk_row_html(html, risk_name):
    full = html.split('<table class="riscos">')[-1].split("</table>")[0]  # the annex table: every row
    return next(tr for tr in full.split("<tr>") if render.e(risk_name) in tr)


def test_the_fgc_risk_row_prints_its_caveat_once_and_keeps_a_different_one(view):
    html = render.render_html(view, render.Narrative(status="unknown"))
    rows = {r["id"]: r for r in view["risks"]["rows"]}
    fgc = _risk_row_html(html, rows["fgc_acima_limite"]["risk"])
    assert fgc.count("limite por CPF e instituição") == 1 and fgc.count("a conferir") == 1
    assert "emissores impressos cujos CDB, LCI e LCA somam mais que o limite do FGC" in fgc  # the rest stays
    sem = _risk_row_html(html, rows["credito_sem_fgc"]["risk"])
    assert "conglomerado" in sem  # a caveat the check_label does not carry is never dropped
    assert rows["fgc_acima_limite"]["explanation"].endswith("a conferir: limite por CPF e instituição")  # engine text unchanged
