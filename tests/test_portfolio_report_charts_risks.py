"""Engine 1.8 and the report: charts, the fee headline and "Principais riscos", on synthetic data only."""

from __future__ import annotations

import copy
import json
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path

import pytest

from src.portfolio import risks as R
from src.portfolio.fees import summarize
from src.portfolio.report import adapt, build, charts, redator, render, revisor
from src.portfolio.report.redator import Finding
from src.portfolio.report.values import format_value

FIXTURE = Path(__file__).parent / "fixtures" / "portfolio" / "demo_engine_output.json"
PROVISIONAL = Path(__file__).parent / "fixtures" / "portfolio" / "report_provisional_engine_output.json"
SVG_NS = "{http://www.w3.org/2000/svg}"


@pytest.fixture()
def engine() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture()
def view(engine) -> dict:
    return adapt.to_view(engine)


def svg_of(fig: str) -> ET.Element:
    """The one <svg> inside a chart's <figure>, parsed as XML (so it is well-formed)."""
    start, end = fig.index("<svg"), fig.index("</svg>") + len("</svg>")
    root = ET.fromstring(fig[start:end])
    assert root.tag == f"{SVG_NS}svg" and root.get("viewBox")
    return root


def texts(root: ET.Element) -> list[str]:
    return [t.text or "" for t in root.iter(f"{SVG_NS}text")]


# --- charts: valid SVG, values that are the input's -------------------------------------------------------------------


def test_allocation_chart_draws_every_class_with_its_value_and_sem_classificacao_apart(view):
    view["allocation"]["buckets"][-1]["weight_pct"] = 3.5  # a synthetic unclassified share
    fig = charts.allocation_chart(view)
    root = svg_of(fig)
    labels = texts(root)
    for i, b in enumerate(view["allocation"]["buckets"]):
        assert format_value(view, f"allocation.buckets[{i}].weight_pct") in labels
    assert "sem classificação" in labels
    fills = [p.get("fill") for p in root.iter(f"{SVG_NS}path")]
    assert charts.UNCLASSIFIED_FILL in fills and charts.SERIES in fills


def test_indexer_chart_values_match_the_table(view):
    root = svg_of(charts.indexer_chart(view))
    for i, _ in enumerate(view["indexer"]["buckets"]):
        assert format_value(view, f"indexer.buckets[{i}].weight_pct") in texts(root)


def test_maturity_chart_one_column_per_year_with_the_year_as_text(view):
    years = view["concentration"]["maturity_ladder"]["by_year"]
    root = svg_of(charts.maturity_chart(view))
    labels = texts(root)
    assert [y["year"] for y in years] == [t for t in labels if t.isdigit()]  # "2028", never "2.028"
    for i, _ in enumerate(years):
        assert format_value(view, f"concentration.maturity_ladder.by_year[{i}].weight_pct") in labels
    assert len(list(root.iter(f"{SVG_NS}path"))) == len(years)


def test_issuer_and_fund_charts_print_the_engine_values(view):
    labels = texts(svg_of(charts.issuer_chart(view)))
    g0 = "concentration.issuer.groups[0]"
    assert f"{format_value(view, g0 + '.value_brl')} · {format_value(view, g0 + '.weight_pct')}" in labels
    idx = charts.fund_positions(view)
    assert idx and [view["lines"][i]["value_brl"] for i in idx] == sorted((view["lines"][i]["value_brl"] for i in idx), reverse=True)
    labels = texts(svg_of(charts.fund_chart(view)))
    assert f"{format_value(view, f'lines[{idx[0]}].value_brl')} · {format_value(view, f'lines[{idx[0]}].weight_pct')}" in labels


def test_lookthrough_diagram_has_only_the_engine_paths(view):
    tree = view["lookthrough"]["tree"]
    assert 0 < len(tree) <= adapt.TREE_FUNDS
    root = svg_of(charts.lookthrough_chart(view))
    labels = texts(root)
    assert "Carteira" in labels and format_value(view, "portfolio.total_brl") in labels
    for i, f in enumerate(tree):
        assert f"{format_value(view, f'lookthrough.tree[{i}].weight_pct')} da carteira" in labels
        assert 0 < len(f["children"]) <= adapt.TREE_ASSETS
        for j, _ in enumerate(f["children"]):
            assert f"{format_value(view, f'lookthrough.tree[{i}].children[{j}].weight_pct')} da carteira" in labels
    # every child is an exposure the engine lists for that fund's line, with its own portfolio_pct
    eng_lines = {f"L{ln['line_no']}": ln for ln in json.loads(FIXTURE.read_text(encoding="utf-8"))["look_through"]["lines"]}
    for f in tree:
        pcts = {x["portfolio_pct"] for x in eng_lines[f["line_id"]]["exposures"]}
        assert all(c["weight_pct"] in pcts for c in f["children"])


def test_fee_chart_one_bar_per_fund_with_a_fee_and_the_etf_site_bar_outlined(view):
    fig = charts.fee_chart(view)
    assert "Barras contornadas" not in fig  # no ETF bar, no ETF clause
    root = svg_of(fig)
    with_fee = [i for i, b in enumerate(view["fees"]["by_line"]) if b.get("disclosed_brl_year")]
    labels = texts(root)
    for i in with_fee:
        assert any(t.startswith(format_value(view, f"fees.by_line[{i}].disclosed_brl_year")) for t in labels)
    assert not any(p.get("stroke") == charts.THIRD_PARTY for p in root.iter(f"{SVG_NS}path"))
    # a synthetic ETF line with a fee from the third-party site
    etf = copy.deepcopy(view["fees"]["by_line"][with_fee[0]])
    etf.update(fund_name="ETF EXEMPLO", disclosed_brl_year=321.0, disclosed_pct_year=0.3,
               etf_site_label="taxa informada pelo site etfsbrasil.com.br (fonte de terceiros, não é documento da CVM)")
    view["fees"]["by_line"].append(etf)
    fig = charts.fee_chart(view)
    assert "Barras contornadas: taxa de ETF do site etfsbrasil.com.br (terceiros), somada à parte" in fig
    root = svg_of(fig)
    assert any(p.get("stroke") == charts.THIRD_PARTY and p.get("fill") == charts.THIRD_PARTY_FILL for p in root.iter(f"{SVG_NS}path"))
    labels = texts(root)
    assert any("site de terceiros" in t and t.startswith("R$ 321,00") for t in labels)
    assert any("etfsbrasil.com.br (terceiros)" in t for t in labels)  # the legend names it


def test_names_are_escaped_and_truncated_in_the_svg(view):
    view["allocation"]["buckets"][0]["asset_class"] = "A & B <x> " + "muito longo " * 10
    root = svg_of(charts.allocation_chart(view))  # parses, so the & and < were escaped
    assert any(t.startswith("A & B <x>") and t.endswith("…") for t in texts(root))


# --- charts: nothing when the data is missing ---------------------------------------------------------------------------


@pytest.mark.parametrize("builder, breaker", [
    (charts.allocation_chart, lambda w: w.pop("allocation")),
    (charts.allocation_chart, lambda w: [b.update(weight_pct=0.0) for b in w["allocation"]["buckets"]]),
    (charts.indexer_chart, lambda w: w["indexer"].update(buckets=[])),
    (charts.maturity_chart, lambda w: w["concentration"]["maturity_ladder"].update(by_year=[])),
    (charts.maturity_chart, lambda w: w.pop("concentration")),
    (charts.issuer_chart, lambda w: w["concentration"]["issuer"].update(groups=[])),
    (charts.fund_chart, lambda w: [ln.update(asset_type="acao") for ln in w["lines"]]),
    (charts.lookthrough_chart, lambda w: w["lookthrough"].update(tree=[])),
    (charts.fee_chart, lambda w: [b.update(disclosed_brl_year=None) for b in w["fees"]["by_line"]]),
])
def test_a_chart_without_data_is_not_drawn(view, builder, breaker):
    assert builder(view)  # drawn with the data
    breaker(view)
    assert builder(view) == ""


def test_old_views_render_without_charts_or_new_sections():
    old = json.loads(PROVISIONAL.read_text(encoding="utf-8"))
    for b in (charts.allocation_chart, charts.maturity_chart, charts.issuer_chart, charts.lookthrough_chart):
        assert b(old) == ""
    html_text, _ = build.build(old, "fake")
    assert "<h2>Principais riscos</h2>" not in html_text and "{{" not in html_text


def test_the_gaps_say_why_a_chart_is_missing(engine):
    eng = copy.deepcopy(engine)
    for ln in eng["look_through"]["lines"]:
        ln["exposures"] = []
    eng["concentration"]["maturity_ladder"].update(status="not_applicable", by_year=[])
    v = adapt.to_view(eng)
    titles = {g["title"]: g["text"] for g in v["gaps"]}
    assert "Diagrama do look-through" in titles and "Gráfico de vencimentos" in titles
    assert charts.lookthrough_chart(v) == "" and charts.maturity_chart(v) == ""
    html_text = render.render_html(v, render.Narrative(status="complete"))
    assert "Diagrama do look-through" in html_text.split("O que não foi possível avaliar")[1]


def test_the_report_places_risks_and_the_fee_headline_after_the_summary(view):
    html_text, _ = build.build(view, "fake")
    order = [html_text.index(f"<h2>{t}</h2>") for t in ("Resumo", "Principais riscos", "Quanto a carteira paga em taxas",
                                                         "Identificação linha a linha", "Custo em taxas")]
    assert order == sorted(order)
    assert html_text.count('<figure class="grafico">') == 9
    assert "{{" not in html_text


def test_the_pdf_carries_the_charts(tmp_path, engine):
    try:
        import weasyprint  # noqa: F401
        from pypdf import PdfReader
    except (ImportError, OSError):
        pytest.skip("weasyprint (pango) or pypdf not installed here (requirements-report.txt)")
    src = tmp_path / "e.json"
    src.write_text(json.dumps(engine), encoding="utf-8")
    out = tmp_path / "r.pdf"
    assert build.main([str(src), "--provider", "fake", "--out", str(out)]) == 0
    text = " ".join(" ".join(p.extract_text() for p in PdfReader(str(out)).pages).split())
    for caption in ("Carteira por classe de ativo", "Valor que vence por ano", "Maiores emissores de crédito direto",
                    "Look-through: da carteira", "administração por fundo, em R$ por ano", "Principais riscos",
                    "Quanto a carteira paga em taxas"):
        assert caption in text, caption
    assert "LFT (linha agregada sint" in text  # a label drawn inside the look-through SVG


# --- the fee headline ---------------------------------------------------------------------------------------------------


def _fee_line(no, kind=None, per_year=None, value=100.0, perf=None):
    h = None
    if kind == "faixa":
        h = {"kind": "faixa", "per_year_min_brl": per_year[0], "per_year_max_brl": per_year[1]}
    elif kind:
        h = {"kind": kind, "per_year_brl": per_year, "counted_as_cost": True}
    return {"line_no": no, "position_value_brl": value, "headline": h,
            "disclosed": {"perf_as_filed": perf} if perf else {}, "estimate": {"adm_per_year_brl": 1.0}}


def test_fee_summary_totals_coverage_and_what_is_left_out():
    from src.portfolio.fees import _totals

    lines = [_fee_line(1, "fixa", 10.0, 1000.0, perf="20% do que exceder o CDI"), _fee_line(2, "lamina_mais_recente", 5.0, 500.0),
             _fee_line(3, "faixa", (2.0, 4.0), 250.0), _fee_line(4, "etf_site", 3.0, 250.0), _fee_line(5, None, None, 1000.0),
             _fee_line(6, "zero_informado", None, 1000.0)]
    lines[5]["headline"]["counted_as_cost"] = False
    fees = {"lines": lines, "underlying": [], "totals": _totals(lines)}
    sm = summarize(fees, Decimal("8000"), {"groups": [{"line_nos": [7, 8]}], "not_printed_line_nos": [9],
                                           "direct_credit_value_brl": 300.0})
    assert sm["adm_disclosed_fixed_per_year_brl"] == 15.0  # fixed + the newer lâmina, never the ETF or the estimate
    assert sm["adm_etf_site_per_year_brl"] == 3.0 and "adm_fee_per_year_brl" not in sm  # never summed with the ETF site
    assert (sm["adm_disclosed_range_low_per_year_brl"], sm["adm_disclosed_range_high_per_year_brl"]) == (2.0, 4.0)
    assert sm["fund_value_brl"] == 4000.0 and sm["fund_value_portfolio_pct"] == 50.0
    assert sm["coverage_fixed_fund_value_pct"] == 37.5
    assert sm["coverage_range_fund_value_pct"] == 6.25
    assert sm["coverage_etf_site_fund_value_pct"] == 6.25
    assert sm["coverage_without_fee_fund_value_pct"] == 50.0
    ni = {x["id"]: x for x in sm["not_included"]}
    assert set(ni) == {"performance", "carregamento_pgbl", "spread_credito_direto", "sem_taxa"}
    assert ni["performance"]["line_nos"] == [1] and ni["performance"]["value_brl"] is None  # never summed
    assert ni["spread_credito_direto"] == {**ni["spread_credito_direto"], "line_nos": [7, 8, 9], "value_brl": 300.0}
    assert ni["sem_taxa"]["line_nos"] == [5, 6] and ni["sem_taxa"]["value_brl"] == 2000.0
    assert sm["estimate_adm_per_year_brl"] == 6.0  # the estimate is reported apart


def test_fee_summary_without_a_fixed_fee_has_no_total():
    from src.portfolio.fees import _totals

    lines = [_fee_line(1, None, None, 100.0)]
    sm = summarize({"lines": lines, "underlying": [], "totals": _totals(lines)}, Decimal("100"), None)
    assert sm["adm_disclosed_fixed_per_year_brl"] is None
    assert sm["coverage_without_fee_fund_value_pct"] == 100.0


def test_the_demo_fee_headline_matches_the_engine_totals(engine):
    t, sm = engine["fees"]["totals"], engine["fees"]["summary"]
    assert sm["adm_disclosed_fixed_per_year_brl"] == t["adm_disclosed_fixed_per_year_brl"]
    assert sm["adm_disclosed_fixed_portfolio_pct"] == t["adm_disclosed_fixed_portfolio_pct"]
    assert t["adm_disclosed_range_low_portfolio_pct"] <= t["adm_disclosed_range_high_portfolio_pct"]
    shares = [sm[k] for k in ("coverage_fixed_fund_value_pct", "coverage_range_fund_value_pct",
                              "coverage_etf_site_fund_value_pct", "coverage_without_fee_fund_value_pct")]
    assert abs(sum(shares) - 100) < 0.001


# --- Principais riscos --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("risk_id, value, expected", [
    ("concentracao_emissor", 10.0, "moderado"), ("concentracao_emissor", 10.01, "atencao"), ("concentracao_emissor", 5.0, "baixo"),
    ("concentracao_fundo", 25.01, "atencao"), ("concentracao_fundo", 15.5, "moderado"),
    ("credito_privado", 30.0, "moderado"), ("credito_sem_fgc", 20.5, "atencao"), ("vencimentos", 40.0, "moderado"),
    ("indexador", 80.0, "moderado"), ("indexador", 100.0, "atencao"), ("indexador", 60.0, "baixo"),
    ("fgc_acima_limite", 0, "baixo"), ("fgc_acima_limite", 1, "atencao"),
    ("reapresentacoes", 0, "baixo"), ("reapresentacoes", 5, "moderado"), ("movimento_anormal", 1, "atencao"),
])
def test_severity_is_strictly_above_the_fixed_threshold(risk_id, value, expected):
    assert R.severity(risk_id, value) == expected


def _pos(no, tipo, valor, total, venc=None):
    return {"line_no": no, "tipo": tipo, "linha_extrato": f"{tipo} {no}", "valor_brl": valor,
            "portfolio_pct": round(valor / total * 100, 4), "vencimento": venc,
            "source": {"tool": "statement", "call_id": None, "args": {"line_no": no}, "data_date": "2026-09-30"}}


def synthetic_doc():
    total = 1000.0
    positions = [_pos(1, "fundo", 300.0, total), _pos(2, "CDB", 400.0, total, "2028-01-01"), _pos(3, "CRA", 100.0, total, "2028-06-01"),
                 _pos(4, "FIDC", 200.0, total)]
    return {
        "statement": {"sum_of_lines_brl": total, "positions": positions},
        "identification": {"lines": [{"line_no": 1, "identity": {"kind": "fund", "name": "FUNDO A"}},
                                     {"line_no": 4, "identity": {"kind": "fund", "name": "FIDC B"}}]},
        "concentration": {
            "issuer": {"status": "complete", "direct_credit_value_brl": 500.0, "direct_credit_portfolio_pct": 50.0,
                       "groups": [{"issuer_as_printed": "BANCO X", "line_nos": [2], "value_brl": 400.0, "portfolio_pct": 40.0},
                                  {"issuer_as_printed": "AGRO Y", "line_nos": [3], "value_brl": 100.0, "portfolio_pct": 10.0}],
                       "not_printed_line_nos": []},
            "fgc": {"status": "complete", "limit_brl": 250.0, "n_above_limit": 1, "label": "a conferir",
                    "issuers": [{"issuer_as_printed": "BANCO X", "line_nos": [2], "eligible_value_brl": 400.0,
                                 "above_limit": True, "excess_brl": 150.0}]},
            "maturity_ladder": {"status": "complete", "by_year": [{"year": "2028", "value_brl": 500.0, "portfolio_pct": 50.0,
                                                                   "line_nos": [2, 3]}]},
            "fund_liquidity": {"status": "unknown", "reason_code": "liquidez_sem_api"},
        },
        "indexer": {"status": "complete", "portfolio_value_brl": total,
                    "classes": [{"indexer_class": "pós-fixado (CDI)", "value_brl": 450.0},
                                {"indexer_class": "pós-fixado (Selic)", "value_brl": 400.0},
                                {"indexer_class": "inflação (IPCA)", "value_brl": 100.0},
                                {"indexer_class": "sem classificação", "value_brl": 50.0}]},
        "restatements": {"status": "complete", "assessment": "reapresentado, não avaliado",
                         "lines": [{"line_no": 4, "restatements": [{"sources": []}, {"sources": []}]}]},
        "movement": {"status": "complete", "counts": {"funds": 1, "normal": 0, "atencao": 1, "forte": 0, "nao_avaliado": 0},
                     "lines": [{"line_no": 1, "level": "atencao", "fund_name": "FUNDO A", "sources": []}]},
    }


def test_every_risk_row_with_its_value_source_and_severity():
    rows = {r["id"]: r for r in R.compute_risks(synthetic_doc())["rows"]}
    assert set(rows) == set(R.THRESHOLDS)  # none omitted
    e = rows["concentracao_emissor"]
    assert (e["value_pct"], e["subject"], e["severity"], e["source_path"]) == (40.0, "BANCO X", "atencao",
                                                                              "concentration.issuer.groups[0].portfolio_pct")
    f = rows["concentracao_fundo"]
    assert (f["value_pct"], f["subject"], f["severity"]) == (30.0, "FUNDO A", "atencao")
    assert rows["credito_privado"]["value_pct"] == 50.0 and rows["credito_privado"]["severity"] == "atencao"
    # not covered: 500 of direct credit - min(400, 250) covered = 250, 25% of the portfolio
    s = rows["credito_sem_fgc"]
    assert (s["value_pct"], s["value_brl_detail"], s["severity"]) == (25.0, 250.0, "atencao")
    g = rows["fgc_acima_limite"]
    assert (g["value_count"], g["value_brl_detail"], g["severity"]) == (1, 150.0, "atencao")
    m = rows["vencimentos"]
    assert (m["value_pct"], m["subject"], m["severity"]) == (50.0, "2028", "atencao")
    ix = rows["indexador"]
    assert (ix["value_pct"], ix["subject"], ix["severity"]) == (85.0, "pós-fixado", "atencao")
    assert {p["group"]: p["portfolio_pct"] for p in ix["parts"]}["inflação"] == 10.0
    assert rows["reapresentacoes"]["value_count"] == 2 and rows["reapresentacoes"]["severity"] == "moderado"
    liq = rows["liquidez"]
    assert liq["status"] == "nao_avaliado" and liq["value_pct"] is None and liq["reason"]
    for r in rows.values():
        assert r["explanation"] and r["thresholds"] == R.THRESHOLDS[r["id"]]


def test_attention_level_movement_is_table_only():
    rk = R.compute_risks(synthetic_doc())
    mv = next(r for r in rk["rows"] if r["id"] == "movimento_anormal")
    assert (mv["value_count"], mv["severity"], mv["text_allowed"]) == (0, "moderado", False)
    assert mv["table_only"]["n_atencao"] == 1


def test_missing_inputs_are_not_evaluated_and_absent_ones_do_not_apply():
    doc = synthetic_doc()
    doc["concentration"]["issuer"] = {"status": "not_applicable", "reason_code": "sem_credito_direto", "groups": []}
    doc["concentration"]["fgc"] = {"status": "not_applicable", "issuers": []}
    doc["concentration"]["maturity_ladder"] = {"status": "not_applicable", "by_year": []}
    doc["restatements"] = {"status": "complete", "lines": []}
    doc["movement"] = {"status": "unknown", "counts": {}}
    doc["indexer"]["status"] = "unknown"
    rk = R.compute_risks(doc)
    rows = {r["id"]: r for r in rk["rows"]}
    assert set(rows) == set(R.THRESHOLDS)
    for rid in ("vencimentos", "movimento_anormal", "indexador", "liquidez"):
        assert rows[rid]["status"] == "nao_avaliado" and rows[rid]["reason"], rid
    for rid in ("concentracao_emissor", "credito_privado", "credito_sem_fgc", "fgc_acima_limite", "reapresentacoes"):
        assert rows[rid]["status"] == "nao_se_aplica" and rows[rid]["reason"], rid
    assert rk["status"] == "partial" and "riscos_nao_avaliados" in rk["reason_codes"]
    # ordered: evaluated by severity first, then not evaluated, then not applicable
    ranks = [{"avaliado": 0, "nao_avaliado": 1, "nao_se_aplica": 2}[r["status"]] for r in rk["rows"]]
    assert ranks == sorted(ranks)


def test_the_demo_engine_carries_the_risks_and_the_report_view_copies_them(engine, view):
    assert engine["schema_version"] == "1.11"
    rows = engine["risks"]["rows"]
    assert {r["id"] for r in rows} == set(R.THRESHOLDS)
    sev = [R.SEVERITY_RANK.get(r["severity"] or "", 3) for r in rows if r["status"] == "avaliado"]
    assert sev == sorted(sev)
    assert [r["id"] for r in view["risks"]["rows"]] == [r["id"] for r in rows]
    html_text, _ = build.build(view, "fake")
    section = html_text.split("<h2>Principais riscos</h2>")[1].split("<h2>")[0]
    for i, r in enumerate(view["risks"]["rows"]):
        assert render.e(r["risk"]) in section
        if r["status"] == "avaliado":
            assert format_value(view, f"risks.rows[{i}].value_{r['unit']}") in section


# --- rule zero: the narrative never bypasses the placeholders -----------------------------------------------------------


def F(text, cites=("p1",), section="riscos"):
    return Finding("f1", section, "Título", text, list(cites))


def test_a_table_only_risk_row_cannot_be_cited(view):
    i = next(k for k, r in enumerate(view["risks"]["rows"]) if r["id"] == "movimento_anormal")
    view["risks"]["rows"][i]["text_allowed"] = False
    res = revisor.check(view, [F(f"O risco {{{{risks.rows[{i}].risk}}}} aparece.")])
    assert not res.kept and "só em tabela" in res.removed[0].reason
    # the attention-level count is dropped from what the Redator sees, so a placeholder to it has no path
    view["risks"]["rows"][i]["text_allowed"] = True
    assert "table_only" not in json.dumps(redator.redator_view(view))
    res = revisor.check(view, [F(f"Fundos: {{{{risks.rows[{i}].table_only.n_atencao}}}}.")])
    assert not res.kept and "sem caminho" in res.removed[0].reason


def test_the_movement_rows_semaforo_word_stays_in_the_table(view):
    i = next(k for k, r in enumerate(view["risks"]["rows"]) if r["id"] == "movimento_anormal")
    res = revisor.check(view, [F(f"Semáforo {{{{risks.rows[{i}].severity_label}}}}.")])
    assert not res.kept


def test_risk_digits_outside_placeholders_are_removed_and_placeholders_kept(view):
    ok = F("Maior emissor: {{risks.rows[2].subject}}, {{risks.rows[2].value_pct}} da carteira.")
    bad = F("Maior emissor com 6,29% da carteira.")
    assert revisor.check(view, [ok]).kept and not revisor.check(view, [bad]).kept


def test_fee_coverage_is_a_share_not_an_extreme_fee(view):
    view["fees"]["summary"]["coverage_fixed_fund_value_pct"] = 97.5
    res = revisor.check(view, [F("Cobertura: {{fees.summary.coverage_fixed_fund_value_pct}} do valor em fundos.", section="taxas")])
    assert res.kept and not res.removed


def test_template_findings_on_the_engine_view_all_resolve(view):
    findings = redator._coerce_findings(redator.template_findings(view))
    res = revisor.check(view, findings)
    kept_risks = [f for f in res.kept if f.section == "riscos"]
    assert kept_risks and all("{{risks.rows[" in f.text for f in kept_risks)
    assert not any("movimento_anormal" in json.dumps(view["risks"]["rows"][int(f.text.split("risks.rows[")[1].split("]")[0])]["id"])
                   for f in kept_risks)
    for f in res.kept:
        assert not revisor._DIGIT_RE.search(revisor.PLACEHOLDER_RE.sub("", f.text)), f.text


def test_the_prompt_asks_for_the_top_risks_without_recommendation_or_forecast():
    p = redator.SYSTEM_PROMPT
    assert "riscos (risks" in p and "atenção primeiro" in p
    assert "Nunca recomende" in p and "previsão de mercado" in p
    assert "riscos" in redator.SECTIONS
