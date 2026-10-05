"""Owner's decision Q42 = A (2026-10-05): the exposure-origin chart, "where does the exposure to asset X come from",
on synthetic data only (``tests/fixtures/portfolio/demo_engine_output.json``)."""

from __future__ import annotations

import copy
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from src.portfolio.report import adapt, build, charts, redator, render, revisor
from src.portfolio.report.redator import Finding
from src.portfolio.report.values import format_value

FIXTURE = Path(__file__).parent / "fixtures" / "portfolio" / "demo_engine_output.json"
SVG_NS = "{http://www.w3.org/2000/svg}"


@pytest.fixture()
def engine() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture()
def view(engine) -> dict:
    return adapt.to_view(engine)


def svg_of(fig: str) -> ET.Element:
    start, end = fig.index("<svg"), fig.index("</svg>") + len("</svg>")
    return ET.fromstring(fig[start:end])


def texts(root: ET.Element) -> list[str]:
    return [t.text or "" for t in root.iter(f"{SVG_NS}text")]


def bars(root: ET.Element) -> list[ET.Element]:
    return list(root.iter(f"{SVG_NS}path"))


def shared_groups(eng: dict) -> list[dict]:
    return eng["look_through"]["shared_exposure"]["groups"]


def petr4(view: dict) -> tuple[int, dict]:
    return next((i, g) for i, g in enumerate(view["lookthrough"]["exposure_origin"]) if g["asset"].startswith("PETR4 "))


# --- the adapter: engine values, copied -----------------------------------------------------------------------------------


def test_the_view_holds_the_five_largest_same_asset_groups_by_total(engine, view):
    origin = view["lookthrough"]["exposure_origin"]
    same = sorted((g for g in shared_groups(engine) if g["kind"] == "mesmo_ativo"), key=lambda g: -g["total_exposure_brl"])
    assert len(origin) == adapt.ORIGIN_ASSETS == 5
    assert [o["asset"] for o in origin] == [g["label"] for g in same[:5]]
    assert [o["total_brl"] for o in origin] == sorted((o["total_brl"] for o in origin), reverse=True)
    for o, g in zip(origin, same):
        assert o["total_brl"] == g["total_exposure_brl"] and o["total_pct"] == g["total_exposure_portfolio_pct"]
        assert len(o["segments"]) == len(g["lines"]) > 1


def test_segments_add_up_to_the_engine_total_for_every_group(view):
    for o in view["lookthrough"]["exposure_origin"]:
        # the engine sums unrounded values and rounds once: the rounded lines can differ by a centavo
        assert round(abs(sum(s["value_brl"] for s in o["segments"]) - o["total_brl"]), 2) <= 0.01


def test_petr4_is_the_direct_holding_plus_the_fund_it_is_reached_through(view):
    _, g = petr4(view)
    direct, via = g["segments"]
    assert g["total_brl"] == 1031894.86 and g["total_pct"] == 16.6531
    assert (direct["line_id"], direct["direct"], direct["value_brl"]) == ("L2", True, 988000.0)
    assert direct["weight_in_line"] is None and direct["cda_month"] is None  # a direct holding has no CDA
    assert (via["line_id"], via["direct"], via["value_brl"]) == ("L3", False, 43894.86)
    assert via["weight_in_line"] == 0.16588196 and via["cda_month"] == "2026-05-01"
    assert via["cda_age_months"] == 4  # statement of 2026-09-30, CDA of 2026-05


def test_a_fund_that_holds_the_asset_by_several_paths_shows_the_value_and_the_paths_not_a_sum(view):
    multi = [s for o in view["lookthrough"]["exposure_origin"] for s in o["segments"] if s["n_paths"]]
    assert multi
    for s in multi:
        assert s["n_paths"] > 1 and s["weight_in_line"] is None and s["value_brl"] > 0 and s["cda_month"] == "2026-05-01"


@pytest.mark.parametrize("period, position, expected", [
    ("2026-05-01", "2026-09-30", 4), ("2026-09-01", "2026-09-30", 0), ("2026-08-01", "2026-09-01", 1),
    ("2025-11-01", "2026-02-15", 3), ("2026-10-01", "2026-09-30", None), (None, "2026-09-30", None),
    ("2026-05-01", None, None), ("garbage", "2026-09-30", None),
])
def test_the_cda_age_is_whole_calendar_months_between_two_engine_dates(period, position, expected):
    assert adapt.cda_age_months(period, position) == expected


def test_an_asset_in_a_single_line_is_not_a_group_and_never_charts(engine):
    eng = copy.deepcopy(engine)
    groups = shared_groups(eng)
    groups[:] = [g for g in groups if g["kind"] == "mesmo_ativo"][:1]
    groups[0]["line_nos"], groups[0]["lines"] = groups[0]["line_nos"][:1], groups[0]["lines"][:1]
    assert adapt._exposure_origin(eng) == []
    assert charts.exposure_origin_chart(adapt.to_view(eng)) == ""


def test_other_kinds_of_group_are_not_charted(engine):
    eng = copy.deepcopy(engine)
    shared_groups(eng)[:] = [g for g in shared_groups(eng) if g["kind"] != "mesmo_ativo"]
    assert adapt._exposure_origin(eng) == []


def test_a_segment_whose_rows_do_not_reconcile_with_the_line_value_shows_the_value_only(engine):
    eng = copy.deepcopy(engine)
    for ln in eng["look_through"]["lines"]:
        if ln["line_no"] == 3:
            for e in ln["exposures"]:
                if e["asset_key"] == "PETR4":
                    e["exposure_brl"] += 5.0
    via = adapt.to_view(eng)["lookthrough"]["exposure_origin"]
    seg = next(g for g in via if g["asset"].startswith("PETR4 "))["segments"][1]
    assert seg["value_brl"] == 43894.86
    assert (seg["weight_in_line"], seg["cda_month"], seg["cda_age_months"], seg["n_paths"]) == (None, None, None, None)


def test_a_missing_weight_in_line_is_left_out_not_guessed(engine):
    eng = copy.deepcopy(engine)
    for ln in eng["look_through"]["lines"]:
        for e in ln["exposures"]:
            if e["asset_key"] == "PETR4":
                e["weight_in_line"] = None
    v = adapt.to_view(eng)
    _, g = petr4(v)
    assert g["segments"][1]["weight_in_line"] is None
    root = svg_of(charts.exposure_origin_chart(v))
    shown = texts(root)
    assert any("R$ 43.894,86" == t for t in shown)
    petr_detail = [t for t in shown if t.startswith("CDA de 05/2026")]
    assert petr_detail  # the CDA month is still the engine's, without a weight beside it


# --- the chart: what it prints ---------------------------------------------------------------------------------------------


def test_the_chart_prints_the_engine_total_and_one_row_per_statement_line(view):
    fig = charts.exposure_origin_chart(view)
    root = svg_of(fig)
    shown = texts(root)
    i, g = petr4(view)
    base = f"lookthrough.exposure_origin[{i}]"
    assert f"{format_value(view, f'{base}.total_brl')} · {format_value(view, f'{base}.total_pct')} da carteira" in shown
    assert "PETR4 (BRPETRACNPR6)" in shown
    assert "direta · PETROBRAS PN" in shown and format_value(view, f"{base}.segments[0].value_brl") in shown
    assert "via · GERAÇÃO L. PAR FIA" in shown and format_value(view, f"{base}.segments[1].value_brl") in shown
    assert "peso no fundo: 0,165882 · CDA de 05/2026, 4 meses antes do extrato" in shown
    # one bar segment per positive line and nothing else drawn as a bar
    assert len(bars(root)) == sum(len(o["segments"]) for o in view["lookthrough"]["exposure_origin"])


def extent(d: str) -> tuple[float, float]:
    """Left and right x of a segment path (``M x,y``, ``H x``, ``A rx,ry rot large sweep x,y`` commands)."""
    xs = []
    for cmd, args in re.findall(r"([MHA])([^MHAVZ]*)", d):
        nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", args)]
        xs.append(nums[0] if cmd in "MH" else nums[5])
    return min(xs), max(xs)


def test_segment_widths_are_proportional_to_the_lines_and_fill_the_bar(view):
    root = svg_of(charts.exposure_origin_chart(view))
    by_title = {p.find(f"{SVG_NS}title").text: extent(p.get("d")) for p in bars(root)}
    direct = by_title["direta: PETROBRAS PN: R$ 988.000,00"]
    via = by_title["via: GERAÇÃO L. PAR FIA: R$ 43.894,86"]
    w_direct, w_via = direct[1] - direct[0], via[1] - via[0]
    assert w_direct / w_via == pytest.approx(988000.0 / 43894.86, rel=0.01)
    assert direct[0] == 0 and via[1] == pytest.approx(charts.WIDTH, abs=0.2) and via[0] == pytest.approx(direct[1], abs=0.2)


def test_the_caveat_is_fixed_text_under_the_chart_and_reuses_the_engines_notes(engine, view):
    fig = charts.exposure_origin_chart(view)
    caption = fig.split("<figcaption>")[1]
    assert "no mês da CDA, não na data do extrato" in caption
    assert "fundos sem CDA no mês não são abertos, então o total é um piso" in caption
    assert "PETR3 e PETR4" in caption and "ativos diferentes aqui" in caption
    assert engine["look_through"]["shared_exposure"]["economic_group_assessed"] is False
    assert "Grupo econômico NÃO avaliado" in caption  # the engine's own note, through its view path
    assert "fundo(s) sem carteira na CDA do mês" in caption  # REASON_TEXT of the engine's reason code
    assert "<br>" in caption  # on a line of its own, under the caption


def test_the_engines_note_is_not_printed_when_it_says_the_group_was_assessed(view):
    view["lookthrough"]["economic_group_assessed"] = True
    assert "Grupo econômico NÃO avaliado" not in charts.exposure_origin_chart(view)


def test_the_svg_is_labelled_for_assistive_technology(view):
    root = svg_of(charts.exposure_origin_chart(view))
    assert root.get("role") == "img"
    label = root.get("aria-label")
    assert label.startswith("Origem da exposição") and "PETR4 (BRPETRACNPR6)" in label
    assert format_value(view, "lookthrough.exposure_origin[1].total_brl") in label


def test_the_chart_uses_only_literal_colours_and_no_script(view):
    fig = charts.exposure_origin_chart(view)
    for banned in ("var(", "<script", "<image", "href=", "url("):
        assert banned not in fig
    root = svg_of(fig)
    fills = {p.get("fill") for p in bars(root)}
    assert fills <= {charts.DIRECT_FILL, *charts.VIA_FILLS}


# --- edge cases ----------------------------------------------------------------------------------------------------------


def _one_group(view: dict, segments: list[dict], total: float | None = None) -> dict:
    view["lookthrough"]["exposure_origin"] = [{
        "asset": "ATIVO X (BRXXXXACNOR0)", "total_brl": total if total is not None else sum(s["value_brl"] for s in segments),
        "total_pct": 1.5, "segments": segments}]
    return view


def seg(line, value, direct=False, name=None, **kw) -> dict:
    return {"line_id": f"L{line}", "name": name or f"LINHA {line}", "direct": direct, "value_brl": value,
            "weight_in_line": None, "cda_month": None, "cda_age_months": None, "n_paths": None, **kw}


def test_a_group_of_direct_lines_only_has_rows_with_the_value_and_no_fund_detail(view):
    _one_group(view, [seg(1, 100.0, True), seg(2, 300.0, True)])
    shown = texts(svg_of(charts.exposure_origin_chart(view)))
    assert "direta · LINHA 1" in shown and "direta · LINHA 2" in shown
    assert not any("peso no fundo" in t or "CDA de" in t for t in shown)
    assert len(bars(svg_of(charts.exposure_origin_chart(view)))) == 2


def test_a_negative_or_zero_exposure_is_listed_as_text_and_never_drawn_as_a_bar(view):
    _one_group(view, [seg(1, 600.0, True), seg(2, 400.0), seg(3, -50.0), seg(4, 0.0)], total=950.0)
    root = svg_of(charts.exposure_origin_chart(view))
    assert len(bars(root)) == 2
    shown = texts(root)
    assert any(t.startswith("via · LINHA 3 (não desenhada") for t in shown) and "-R$ 50,00" in shown
    assert any(t.startswith("via · LINHA 4 (não desenhada") for t in shown)
    # the printed total is the engine's, not the sum of what is drawn
    assert "R$ 950,00 · 1,50% da carteira" in shown


def test_a_group_without_a_positive_total_is_not_drawn_and_a_chart_with_none_is_absent(view):
    _one_group(view, [seg(1, -10.0, True), seg(2, -20.0)], total=-30.0)
    assert charts.exposure_origin_chart(view) == ""
    view["lookthrough"]["exposure_origin"] = []
    assert charts.exposure_origin_chart(view) == ""
    del view["lookthrough"]["exposure_origin"]
    assert charts.exposure_origin_chart(view) == ""


def test_a_very_long_fund_name_is_truncated_and_escaped(view):
    _one_group(view, [seg(1, 100.0, True), seg(2, 300.0, name="FUNDO <A> & B " + "MUITO LONGO " * 30)])
    root = svg_of(charts.exposure_origin_chart(view))  # parses, so the & and < were escaped
    long_rows = [t for t in texts(root) if t.startswith("via · FUNDO <A> & B")]
    assert long_rows and long_rows[0].endswith("…") and len(long_rows[0]) <= 90


def test_a_group_with_a_missing_portfolio_percent_prints_only_the_total(view):
    _one_group(view, [seg(1, 100.0, True), seg(2, 300.0)])
    view["lookthrough"]["exposure_origin"][0]["total_pct"] = None
    assert "R$ 400,00" in texts(svg_of(charts.exposure_origin_chart(view)))


def test_the_chart_is_absent_and_nothing_breaks_when_the_engine_has_no_shared_asset(engine):
    eng = copy.deepcopy(engine)
    shared_groups(eng).clear()
    v = adapt.to_view(eng)
    assert v["lookthrough"]["exposure_origin"] == []
    assert charts.exposure_origin_chart(v) == ""
    html_text, _ = build.build(v, "fake")
    assert "De onde vem a exposição" not in html_text and "{{" not in html_text


def test_an_older_view_without_the_key_renders_without_the_chart():
    old = json.loads((Path(__file__).parent / "fixtures" / "portfolio" / "report_provisional_engine_output.json").read_text(encoding="utf-8"))
    assert charts.exposure_origin_chart(old) == ""


# --- the report and the Redator / Revisor ----------------------------------------------------------------------------------


def test_the_report_places_the_chart_after_the_overlap_table(view):
    html_text, _ = build.build(view, "fake")
    order = [html_text.index(t) for t in ("<h3>Sobreposição</h3>", "<h3>De onde vem a exposição ao mesmo ativo</h3>",
                                           "<h3>O que está por baixo")]
    assert order == sorted(order)
    assert "{{" not in html_text


def test_the_redator_never_sees_the_chart_data_and_a_placeholder_into_it_has_no_path(view):
    assert "exposure_origin" in view["lookthrough"] and "cda_age_months" in json.dumps(view)
    assert "exposure_origin" not in json.dumps(redator.redator_view(view))
    f = Finding("f1", "exposicao", "Título", "O total é {{lookthrough.exposure_origin[0].total_brl}}.", ["p1"])
    res = revisor.check(view, [f])
    assert not res.kept and "sem caminho" in res.removed[0].reason


def test_a_digit_the_model_types_about_the_cda_age_is_removed(view):
    f = Finding("f1", "exposicao", "Título", "A CDA é 4 meses mais velha que o extrato.", ["p1"])
    res = revisor.check(view, [f])
    assert not res.kept and "algarismo fora de marcador" in res.removed[0].reason


def test_the_pdf_carries_the_chart(tmp_path, engine):
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
    assert "De onde vem a exposição ao mesmo ativo" in text
    assert "CDA de 05/2026, 4 meses antes do extrato" in text
    assert "fundos sem CDA no mês não são abertos" in text


def test_the_html_has_the_heading_and_the_caption(view):
    html_text = render.render_html(view, render.Narrative(status="complete"))
    assert html_text.count("De onde vem a exposição ao mesmo ativo") >= 2  # the heading and the caption
