"""Owner's decision Q42 = A (2026-10-05), redrawn 2026-10-06 as an arrow flow diagram: "where does the exposure to asset
X come from". One diagram per asset: a box per statement line (name first), a ribbon with an arrowhead to the asset's
box, thickness proportional to the line's R$. Synthetic data only
(``tests/fixtures/portfolio/demo_engine_output.json``)."""

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


def diagrams(fig: str) -> list[ET.Element]:
    """The svg of every figure, in order."""
    return [ET.fromstring(m) for m in re.findall(r"<svg.*?</svg>", fig, flags=re.S)]


def svg_of(fig: str) -> ET.Element:
    found = diagrams(fig)
    assert len(found) == 1, f"expected one diagram, got {len(found)}"
    return found[0]


def diagram_for(fig: str, asset_prefix: str) -> ET.Element:
    return next(d for d in diagrams(fig) if f"exposição a {asset_prefix}" in d.get("aria-label"))


def texts(root: ET.Element) -> list[str]:
    return [t.text or "" for t in root.iter(f"{SVG_NS}text")]


def with_class(root: ET.Element, cls: str) -> list[ET.Element]:
    return [e for e in root.iter() if e.get("class") == cls]


def ribbons(root: ET.Element) -> list[ET.Element]:
    return with_class(root, "ribbon")


def thickness(path: ET.Element) -> float:
    """Left thickness of a ribbon path (``M x0,yt H xa C ... V yeb C ... xa,yb H x0 Z``): its bottom y minus its top y."""
    nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", path.get("d"))]
    assert len(nums) == 17
    return nums[15] - nums[1]


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
    assert g["total_brl"] == 1031894.86 and g["total_pct"] == 16.6531 and g["overflow"] is None
    assert (direct["line_no"], direct["direct"], direct["value_brl"]) == (2, True, 988000.0)
    assert (direct["name"], direct["tipo"], direct["position_brl"]) == ("PETROBRAS PN", "ação", 988000.0)
    assert direct["weight_in_line"] is None and direct["cda_month"] is None  # a direct holding has no CDA
    assert (via["line_no"], via["direct"], via["value_brl"]) == (3, False, 43894.86)
    assert (via["name"], via["tipo"], via["position_brl"]) == ("GERAÇÃO L. PAR FIA", "fundo", 264615.0)
    assert via["weight_in_line"] == 0.16588196 and via["cda_month"] == "2026-05-01"
    assert via["cda_age_months"] == 4  # statement of 2026-09-30, CDA of 2026-05


def test_the_weight_in_the_fund_is_the_engines_fraction_times_100_for_a_percent_path(view):
    _, g = petr4(view)
    via = g["segments"][1]
    assert via["weight_in_line_pct"] == 16.588196  # 0.16588196 x 100, taken in the adapter, never in the chart
    assert format_value(view, f"lookthrough.exposure_origin[{petr4(view)[0]}].segments[1].weight_in_line_pct") == "16,59%"
    assert g["segments"][0]["weight_in_line_pct"] is None


def test_a_fund_that_holds_the_asset_by_several_paths_shows_the_value_and_the_paths_not_a_sum(view):
    multi = [s for o in view["lookthrough"]["exposure_origin"] for s in o["segments"] if s["n_paths"]]
    assert multi
    for s in multi:
        assert (s["n_paths"] > 1 and s["weight_in_line"] is None and s["weight_in_line_pct"] is None
                and s["value_brl"] > 0 and s["cda_month"] == "2026-05-01")


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
    assert (seg["weight_in_line"], seg["weight_in_line_pct"], seg["cda_month"], seg["cda_age_months"], seg["n_paths"]) == \
        (None, None, None, None, None)


def test_a_missing_weight_in_line_is_left_out_not_guessed(engine):
    eng = copy.deepcopy(engine)
    for ln in eng["look_through"]["lines"]:
        for e in ln["exposures"]:
            if e["asset_key"] == "PETR4":
                e["weight_in_line"] = None
    v = adapt.to_view(eng)
    _, g = petr4(v)
    assert g["segments"][1]["weight_in_line"] is None and g["segments"][1]["weight_in_line_pct"] is None
    shown = texts(diagram_for(charts.exposure_origin_chart(v), "PETR4"))
    assert "via fundo: R$ 43.894,86" in shown  # no weight beside the value
    assert "CDA 05/2026 (4 meses antes do extrato)" in shown  # the CDA month is still the engine's
    assert not any("do fundo" in t for t in shown)


def test_a_missing_position_value_is_left_out_not_guessed(engine):
    eng = copy.deepcopy(engine)
    next(p for p in eng["statement"]["positions"] if p["line_no"] == 3)["valor_brl"] = None
    v = adapt.to_view(eng)
    _, g = petr4(v)
    assert g["segments"][1]["position_brl"] is None and g["segments"][0]["position_brl"] == 988000.0
    shown = texts(diagram_for(charts.exposure_origin_chart(v), "PETR4"))
    assert "linha 3 · fundo" in shown  # the box says nothing about a position it does not have
    assert "linha 2 · ação · posição R$ 988.000,00" in shown


def test_the_overflow_marks_the_smaller_lines_past_six_and_sums_their_engine_values():
    values = [500.0, 400.0, 300.0, 200.0, 100.0, 50.0, 30.25, 20.1, 0.0, -5.0]
    segs = [{"value_brl": v, "hidden": False} for v in values]
    overflow = adapt._mark_overflow(segs)
    assert overflow == {"n_lines": 3, "value_brl": 100.35}  # 50 + 30.25 + 20.1, the three smallest positive lines
    assert [s["hidden"] for s in segs] == [False] * 5 + [True] * 3 + [False] * 2
    six = [{"value_brl": v, "hidden": False} for v in values[:6]]
    assert adapt._mark_overflow(six) is None and not any(s["hidden"] for s in six)


# --- the chart: what it prints ---------------------------------------------------------------------------------------------


def test_there_is_one_diagram_per_asset_in_the_views_order(view):
    fig = charts.exposure_origin_chart(view)
    assert fig.count('<figure class="grafico">') == len(diagrams(fig)) == 5
    for i, (o, d) in enumerate(zip(view["lookthrough"]["exposure_origin"], diagrams(fig))):
        assert f"exposição a {o['asset']}: total {format_value(view, f'lookthrough.exposure_origin[{i}].total_brl')}" in d.get("aria-label")


def test_the_boxes_say_the_name_first_then_the_line_its_type_and_its_position(view):
    shown = texts(diagram_for(charts.exposure_origin_chart(view), "PETR4"))
    assert shown.index("PETROBRAS PN") < shown.index("linha 2 · ação · posição R$ 988.000,00")
    assert shown.index("GERAÇÃO L. PAR FIA") < shown.index("linha 3 · fundo · posição R$ 264.615,00")
    assert "direta" in shown and "via fundo" in shown  # the small type tags


def test_the_asset_box_prints_the_code_the_isin_and_the_engines_total_and_percent(view):
    i, _ = petr4(view)
    base = f"lookthrough.exposure_origin[{i}]"
    shown = texts(diagram_for(charts.exposure_origin_chart(view), "PETR4"))
    assert "PETR4" in shown and "(BRPETRACNPR6)" in shown
    assert format_value(view, f"{base}.total_brl") in shown
    assert f"{format_value(view, f'{base}.total_pct')} da carteira" in shown


def test_the_arrows_carry_the_value_the_weight_as_a_percent_and_the_cda_month_with_its_age(view):
    shown = texts(diagram_for(charts.exposure_origin_chart(view), "PETR4"))
    assert "direta: R$ 988.000,00" in shown
    assert "via fundo: 16,59% do fundo = R$ 43.894,86" in shown
    assert "CDA 05/2026 (4 meses antes do extrato)" in shown
    assert not any("0,165882" in t for t in shown)  # never the fraction as if it were a percent


def test_a_fund_with_several_paths_keeps_the_phrase_and_no_weight(view):
    d = diagram_for(charts.exposure_origin_chart(view), "BRSTNCLF1RS0")
    shown = texts(d)
    assert "via fundo: R$ 1,1 milhão" in shown
    assert "3 caminhos dentro do fundo (peso não somado)" not in shown  # this asset's fund has seven paths
    assert "7 caminhos dentro do fundo (peso não somado)" in shown
    assert not any("do fundo =" in t for t in shown if "caminhos" in t)


def test_an_arrow_label_that_does_not_fit_wraps_and_never_splits_the_reais_from_their_number():
    lines = charts._wrap("via fundo: 16,59% do fundo = R$ 43.894,86 com um texto bem comprido para quebrar", 120, 8)
    assert len(lines) > 1 and all("R$" not in ln or re.search(r"R\$ \d", ln) for ln in lines)
    assert "".join(ln.replace(" ", "") for ln in lines) == "viafundo:16,59%dofundo=R$43.894,86comumtextobemcompridoparaquebrar"


def extent(p: ET.Element) -> list[float]:
    return [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", p.get("d"))]


def test_every_ribbon_ends_in_an_arrowhead_at_the_asset_box(view):
    for d in diagrams(charts.exposure_origin_chart(view)):
        rs, heads, box = ribbons(d), with_class(d, "arrowhead"), with_class(d, "asset-box")[0]
        assert len(rs) == len(heads) >= 2
        box_x, box_y, box_h = float(box.get("x")), float(box.get("y")), float(box.get("height"))
        for r, h in zip(rs, heads):
            nums = extent(h)  # M xe,y1 L xtip,y L xe,y2 Z
            assert nums[2] == pytest.approx(box_x - 0.0, abs=0.01)  # the tip touches the asset box
            assert box_y <= min(nums[1], nums[5]) and max(nums[1], nums[5]) <= box_y + box_h  # inside it
            assert float(extent(r)[7]) == pytest.approx(nums[0], abs=0.1)  # the ribbon ends where the head starts


def test_ribbon_thickness_is_proportional_to_the_lines_exposure(view):
    _one_group(view, [seg(1, 600.0, True), seg(2, 300.0), seg(3, 150.0)])
    t = [thickness(r) for r in ribbons(svg_of(charts.exposure_origin_chart(view)))]
    assert t[0] == pytest.approx(charts.ORIGIN_T_MAX)
    assert t[0] / t[1] == pytest.approx(2.0, rel=0.01) and t[1] / t[2] == pytest.approx(2.0, rel=0.01)
    assert t[0] / t[2] == pytest.approx(600.0 / 150.0, rel=0.01)


def test_a_tiny_slice_keeps_a_minimum_thickness(view):
    d = diagram_for(charts.exposure_origin_chart(view), "PETR4")
    t = [thickness(r) for r in ribbons(d)]
    assert t[0] == pytest.approx(charts.ORIGIN_T_MAX)
    # 43,894.86 / 988,000 of 22 px is under one pixel: the ribbon is still drawn at the minimum
    assert t[1] == pytest.approx(charts.ORIGIN_T_MIN) and t[1] > 22 * 43894.86 / 988000.0


def test_ribbons_are_listed_largest_first_so_none_cross(view):
    _one_group(view, [seg(1, 100.0, True), seg(2, 500.0), seg(3, 300.0)])
    shown = texts(svg_of(charts.exposure_origin_chart(view)))
    names = [t for t in shown if t.startswith("LINHA ")]
    assert names == ["LINHA 2", "LINHA 3", "LINHA 1"]


def test_the_boxes_and_the_labels_do_not_overlap(view):
    for d in diagrams(charts.exposure_origin_chart(view)):
        boxes = sorted((float(b.get("y")), float(b.get("y")) + float(b.get("height"))) for b in with_class(d, "line-box"))
        for (_, bottom), (top, _) in zip(boxes, boxes[1:]):
            assert bottom < top  # a gap between two statement boxes
        # the arrow labels sit in the flat part, to the right of the boxes, and no two share a baseline
        ys = [float(t.get("y")) for t in d.iter(f"{SVG_NS}text") if float(t.get("x")) > charts.ORIGIN_LEFT_W]
        assert len(ys) == len(set(ys))
        # nothing is drawn below the svg's own height
        assert max(float(t.get("y")) for t in d.iter(f"{SVG_NS}text")) < float(d.get("height"))


def test_the_diagram_is_taller_for_more_lines(view):
    heights = {len(ribbons(d)): float(d.get("height")) for d in diagrams(charts.exposure_origin_chart(view))}
    assert heights[3] > heights[2]


def test_the_caveat_is_fixed_text_under_each_diagram_and_reuses_the_engines_notes(engine, view):
    fig = charts.exposure_origin_chart(view)
    figs = fig.split('<figure class="grafico">')[1:]
    assert len(figs) == 5
    assert engine["look_through"]["shared_exposure"]["economic_group_assessed"] is False
    for f in figs:
        caption = f.split("<figcaption>")[1]
        assert "no mês da CDA, não na data do extrato" in caption
        assert "fundos sem CDA no mês não são abertos, então o total é um piso" in caption
        assert "PETR3 e PETR4" in caption and "ativos diferentes aqui" in caption
        assert "Grupo econômico NÃO avaliado" in caption  # the engine's own note, through its view path
        assert "fundo(s) sem carteira na CDA do mês" in caption  # REASON_TEXT of the engine's reason code
        assert "<br>" in caption  # on a line of its own, under the caption
        assert "Peso no fundo: fração" not in caption  # the old sentence: the weight is a percent now


def test_the_engines_note_is_not_printed_when_it_says_the_group_was_assessed(view):
    view["lookthrough"]["economic_group_assessed"] = True
    assert "Grupo econômico NÃO avaliado" not in charts.exposure_origin_chart(view)


def test_each_diagram_is_labelled_for_assistive_technology(view):
    for d in diagrams(charts.exposure_origin_chart(view)):
        assert d.get("role") == "img"
        label = d.get("aria-label")
        assert label.startswith("Origem da exposição a ") and "Linhas: " in label
        assert d.find(f"{SVG_NS}title").text == label  # the same sentence, as the svg's own title
    petr = diagram_for(charts.exposure_origin_chart(view), "PETR4")
    assert "PETROBRAS PN, direta, R$ 988.000,00" in petr.get("aria-label")
    assert "GERAÇÃO L. PAR FIA, via fundo, R$ 43.894,86" in petr.get("aria-label")
    assert any(t.text.startswith("PETROBRAS PN: direta: R$ 988.000,00") for t in petr.iter(f"{SVG_NS}title"))


def test_the_chart_uses_only_literal_colours_no_script_and_nothing_below_the_smallest_size(view):
    fig = charts.exposure_origin_chart(view)
    for banned in ("var(", "<script", "<image", "href=", "url(", "opacity"):
        assert banned not in fig
    for d in diagrams(fig):
        for el in d.iter():
            for attr in ("fill", "stroke"):
                v = el.get(attr)
                assert v in (None, "none") or re.fullmatch(r"#[0-9a-f]{6}", v), v
        sizes = {float(t.get("font-size")) for t in d.iter(f"{SVG_NS}text")}
        assert min(sizes) >= charts.ORIGIN_SMALL_SIZE == 7.5


# --- edge cases ----------------------------------------------------------------------------------------------------------


def _one_group(view: dict, segments: list[dict], total: float | None = None) -> dict:
    overflow = adapt._mark_overflow(segments)
    view["lookthrough"]["exposure_origin"] = [{
        "asset": "ATIVO X (BRXXXXACNOR0)", "total_brl": total if total is not None else sum(s["value_brl"] for s in segments),
        "total_pct": 1.5, "segments": segments, "overflow": overflow}]
    return view


def seg(line, value, direct=False, name=None, **kw) -> dict:
    return {"line_no": line, "name": f"LINHA {line}" if name is None else name, "tipo": "fundo",
            "direct": direct, "position_brl": None if value is None else value * 2, "value_brl": value, "weight_in_line": None, "weight_in_line_pct": None,
            "cda_month": None, "cda_age_months": None, "n_paths": None, "hidden": False, **kw}


def test_a_group_of_direct_lines_only_has_arrows_with_the_value_and_no_fund_detail(view):
    _one_group(view, [seg(1, 100.0, True), seg(2, 300.0, True)])
    root = svg_of(charts.exposure_origin_chart(view))
    shown = texts(root)
    assert "direta: R$ 100,00" in shown and "direta: R$ 300,00" in shown
    assert not any("do fundo" in t or "CDA" in t for t in shown)
    assert len(ribbons(root)) == 2


def test_a_negative_or_zero_exposure_is_listed_as_text_and_never_drawn_as_a_ribbon(view):
    _one_group(view, [seg(1, 600.0, True), seg(2, 400.0), seg(3, -50.0), seg(4, 0.0)], total=950.0)
    root = svg_of(charts.exposure_origin_chart(view))
    assert len(ribbons(root)) == 2 and len(with_class(root, "line-box")) == 2
    shown = texts(root)
    assert ("Não desenhada (exposição zero, negativa ou ausente): LINHA 3, linha 3: -R$ 50,00") in shown
    assert ("Não desenhada (exposição zero, negativa ou ausente): LINHA 4, linha 4: R$ 0,00") in shown
    # the printed total is the engine's, not the sum of what is drawn
    assert "R$ 950,00" in shown and "1,50% da carteira" in shown


def test_a_missing_exposure_value_is_listed_as_text_with_a_dash(view):
    _one_group(view, [seg(1, 600.0, True), seg(2, 400.0), seg(3, None)], total=1000.0)
    shown = texts(svg_of(charts.exposure_origin_chart(view)))
    assert "Não desenhada (exposição zero, negativa ou ausente): LINHA 3, linha 3: —" in shown


def test_a_group_without_a_positive_total_or_a_positive_line_is_not_drawn_and_a_chart_with_none_is_absent(view):
    _one_group(view, [seg(1, -10.0, True), seg(2, -20.0)], total=-30.0)
    assert charts.exposure_origin_chart(view) == ""
    _one_group(view, [seg(1, -10.0, True), seg(2, -20.0)], total=30.0)
    assert charts.exposure_origin_chart(view) == ""
    view["lookthrough"]["exposure_origin"] = []
    assert charts.exposure_origin_chart(view) == ""
    del view["lookthrough"]["exposure_origin"]
    assert charts.exposure_origin_chart(view) == ""


def test_a_very_long_name_is_truncated_in_the_box_kept_whole_in_the_title_and_escaped(view):
    long_name = "FUNDO <A> & B " + "MUITO LONGO " * 30
    _one_group(view, [seg(1, 100.0, True), seg(2, 300.0, name=long_name)])
    root = svg_of(charts.exposure_origin_chart(view))  # parses, so the & and < were escaped
    box = [t for t in texts(root) if t.startswith("FUNDO <A> & B")]
    assert box and box[0].endswith("…") and len(box[0]) <= 24  # the box's own width, beside the tag
    assert any(t.text.startswith(f"{long_name}: via fundo") for t in root.iter(f"{SVG_NS}title"))


def test_a_long_type_is_shortened_in_the_box_but_the_position_value_is_never_cut(view):
    _one_group(view, [seg(1, 100.0, True), seg(12, 30000.0, tipo="debênture incentivada de infraestrutura " * 3)])
    detail = [t for t in texts(svg_of(charts.exposure_origin_chart(view))) if t.startswith("linha 12 · deb")]
    assert detail and "…" in detail[0] and detail[0].endswith(" · posição R$ 60.000,00")
    # no room even for a short type: the type goes, the number stays whole
    spec = {"line_no": 12, "tipo": "debênture", "position_brl": 60000.0}
    assert charts._box_detail(view, "lookthrough.exposure_origin[0].segments[1]", seg(12, 30000.0), 10) == \
        "linha 12 · posição R$ 60.000,00"
    assert spec["tipo"] and charts._box_detail({}, "x", spec) == "linha — · debênture · posição —"


def test_a_not_drawn_row_with_a_long_name_keeps_the_exposure_value_whole(view):
    long_name = "BB RENDA FIXA CURTO PRAZO AUTOMÁTICO FUNDO DE INVESTIMENTO EM COTAS DE FUNDOS DE INVESTIMENTO " * 2
    _one_group(view, [seg(1, 600.0, True), seg(2, 400.0), seg(7, -12345.67, name=long_name)], total=987.65)
    row = next(t for t in texts(svg_of(charts.exposure_origin_chart(view))) if t.startswith("Não desenhada"))
    assert "…" in row and row.endswith(", linha 7: -R$ 12.345,67")


def test_a_tiny_weight_is_not_printed_as_zero_percent(view):
    _one_group(view, [seg(1, 100.0, True), seg(2, 1234.0, weight_in_line_pct=0.003, cda_age_months=2)])
    shown = texts(svg_of(charts.exposure_origin_chart(view)))
    assert "via fundo: menos de 0,01% do fundo = R$ 1.234,00" in " ".join(shown)
    assert not any("0,00%" in t for t in shown)


def test_six_lines_reached_through_funds_get_six_different_colours(view):
    _one_group(view, [seg(n + 1, 100.0 * (7 - n)) for n in range(6)])
    root = svg_of(charts.exposure_origin_chart(view))
    colours = [r.get("stroke") for r in ribbons(root)]
    assert len(colours) == len(set(colours)) == 6


def test_a_line_without_a_name_is_called_by_its_number(view):
    _one_group(view, [seg(1, 100.0, True, name=""), seg(2, 300.0)])
    assert "linha 1" in texts(svg_of(charts.exposure_origin_chart(view)))


def test_more_than_six_lines_draw_the_five_largest_and_one_text_row_for_the_rest(view):
    values = [800.0, 700.0, 600.0, 500.0, 400.0, 90.5, 30.25, 20.1]
    _one_group(view, [seg(n + 1, v) for n, v in enumerate(values)])
    o = view["lookthrough"]["exposure_origin"][0]
    assert o["overflow"] == {"n_lines": 3, "value_brl": 140.85}
    root = svg_of(charts.exposure_origin_chart(view))
    assert len(ribbons(root)) == len(with_class(root, "line-box")) == 5
    shown = texts(root)
    assert "+3 linhas menores: R$ 140,85 (não desenhadas)" in shown
    assert {"LINHA 1", "LINHA 5"} <= set(shown) and not {"LINHA 6", "LINHA 7", "LINHA 8"} & set(shown)


def test_exactly_six_lines_are_all_drawn_and_have_no_overflow_row(view):
    _one_group(view, [seg(n + 1, 100.0 * (7 - n)) for n in range(6)])
    root = svg_of(charts.exposure_origin_chart(view))
    assert len(ribbons(root)) == 6 and not any("linhas menores" in t for t in texts(root))


def test_the_arrows_the_text_rows_and_the_overflow_add_up_to_the_group_total_to_the_centavo(view):
    values = [812.55, 700.1, 600.0, 500.0, 400.0, 90.5, 30.25, 20.1, 0.0, -12.34]
    total = round(sum(values), 2)
    _one_group(view, [seg(n + 1, v) for n, v in enumerate(values)], total=total)
    shown = texts(svg_of(charts.exposure_origin_chart(view)))

    def reais(text: str) -> float:
        m = re.search(r"(-?)R\$ ([\d.]+),(\d\d)", text)
        return float(("-" if m.group(1) else "") + m.group(2).replace(".", "") + "." + m.group(3))

    arrows = [reais(t) for t in shown if t.startswith("direta:") or t.startswith("via fundo:")]
    rows = [reais(t) for t in shown if t.startswith("Não desenhada")]
    more = [reais(t) for t in shown if "linhas menores" in t]
    assert len(arrows) == 5 and len(rows) == 2 and len(more) == 1
    assert round(abs(sum(arrows) + sum(rows) + sum(more) - total), 2) <= 0.01


def test_the_demo_groups_add_up_in_the_view_drawn_overflow_and_listed(view):
    for o in view["lookthrough"]["exposure_origin"]:
        shown = sum(s["value_brl"] for s in o["segments"] if not s["hidden"] and s["value_brl"] > 0)
        hidden = sum(s["value_brl"] for s in o["segments"] if s["hidden"])
        listed = sum(s["value_brl"] for s in o["segments"] if s["value_brl"] <= 0)
        assert round(abs(shown + hidden + listed - o["total_brl"]), 2) <= 0.01
        assert (o["overflow"] or {"value_brl": 0})["value_brl"] == pytest.approx(hidden, abs=0.005)


def test_a_group_with_a_missing_portfolio_percent_prints_only_the_total(view):
    _one_group(view, [seg(1, 100.0, True), seg(2, 300.0)])
    view["lookthrough"]["exposure_origin"][0]["total_pct"] = None
    shown = texts(svg_of(charts.exposure_origin_chart(view)))
    assert "R$ 400,00" in shown and not any("da carteira" in t for t in shown)


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


def test_the_report_keeps_the_overlap_table_in_the_body_and_the_origin_diagrams_in_the_annex(view):
    html_text, _ = build.build(view, "fake")
    annex_at = html_text.index('<details id="apendice">')
    body_order = [html_text.index(t) for t in ("<h3>Sobreposição</h3>", "<h3>O que está por baixo")]
    assert body_order == sorted(body_order) and body_order[-1] < annex_at
    assert html_text.index("<h3>De onde vem a exposição ao mesmo ativo</h3>") > annex_at
    assert "{{" not in html_text


def test_the_redator_never_sees_the_chart_data_and_a_placeholder_into_it_has_no_path(view):
    assert "exposure_origin" in view["lookthrough"] and "cda_age_months" in json.dumps(view)
    assert "exposure_origin" not in json.dumps(redator.redator_view(view))
    assert "weight_in_line_pct" not in json.dumps(redator.redator_view(view))
    f = Finding("f1", "exposicao", "Título", "O total é {{lookthrough.exposure_origin[0].total_brl}}.", ["p1"])
    res = revisor.check(view, [f])
    assert not res.kept and "sem caminho" in res.removed[0].reason


def test_a_digit_the_model_types_about_the_cda_age_is_removed(view):
    f = Finding("f1", "exposicao", "Título", "A CDA é 4 meses mais velha que o extrato.", ["p1"])
    res = revisor.check(view, [f])
    assert not res.kept and "algarismo fora de marcador" in res.removed[0].reason


def test_the_pdf_carries_the_diagrams(tmp_path, engine):
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
    assert "PETROBRAS PN" in text and "linha 3 · fundo · posição R$ 264.615,00" in text
    assert "via fundo: 16,59% do fundo = R$ 43.894,86" in text
    assert "CDA 05/2026 (4 meses antes do extrato)" in text
    assert "fundos sem CDA no mês não são abertos" in text


def test_the_html_has_the_heading_and_one_caption_per_asset(view):
    html_text = render.render_html(view, render.Narrative(status="complete"))
    assert html_text.count("<h3>De onde vem a exposição ao mesmo ativo</h3>") == 1
    assert html_text.count("De onde vem a exposição a ") == 5  # one figcaption per asset
