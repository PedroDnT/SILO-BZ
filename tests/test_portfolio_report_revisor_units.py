"""The Revisor and the renderer read a figure's unit from the same declared table (values.UNIT_RULES).

The Revisor's extreme-value rules are thresholds in a unit (a fee above 5% a.a., an exposure above 50%, a
delinquency change above R$100M). Each must apply only to a figure the renderer prints in that unit, so a key's
spelling cannot make the two disagree.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.portfolio.report import adapt, redator, render, revisor
from src.portfolio.report.values import BRL, PCT, PCT_CDI, is_number, iter_leaves, parent_path, resolve, unit_of

FIXTURES = Path(__file__).parent / "fixtures" / "portfolio"
PROBE = 1e12  # above every threshold, in any unit


def _views() -> dict[str, dict]:
    demo = adapt.to_view(json.loads((FIXTURES / "demo_engine_output.json").read_text(encoding="utf-8")))
    prov = json.loads((FIXTURES / "report_provisional_engine_output.json").read_text(encoding="utf-8"))
    return {"demo": redator.redator_view(demo), "provisional": redator.redator_view(prov)}


VIEWS = _views()


def _printed(view: dict, path: str, value: float) -> str:
    """The text the renderer puts in the report for ``value`` at ``path``."""
    return render.e(render.format_value(view, path, value))


@pytest.mark.parametrize("name", sorted(VIEWS))
def test_every_extreme_rule_reads_the_renderers_unit(name: str) -> None:
    view = VIEWS[name]
    kinds = set()
    for path, value in iter_leaves(view):
        if not path or not is_number(value):
            continue
        for probe in (PROBE, -PROBE):
            ext = revisor._extreme(view, path, probe)
            if ext is None:
                continue
            kind = ext[0]
            kinds.add(kind)
            assert unit_of(view, path) == revisor.EXTREME_UNITS[kind], path
            text = _printed(view, path, probe)
            if revisor.EXTREME_UNITS[kind] == PCT:
                assert text.endswith("%") and "CDI" not in text, (path, text)
            else:
                assert text.lstrip("-").startswith("R$"), (path, text)
    # not vacuous: both fixtures together reach every rule
    assert kinds, name


def test_both_fixtures_reach_every_extreme_rule() -> None:
    kinds = {
        ext[0]
        for view in VIEWS.values()
        for path, value in iter_leaves(view)
        if path and is_number(value)
        for ext in [revisor._extreme(view, path, PROBE)]
        if ext
    }
    assert kinds == set(revisor.EXTREME_UNITS)


@pytest.mark.parametrize("name", sorted(VIEWS))
def test_pct_of_cdi_rule_is_the_renderers_pct_cdi(name: str) -> None:
    """The Revisor's '% do CDI' check fires on exactly the figures the renderer prints as '% do CDI'."""
    view = VIEWS[name]
    _, sources = revisor._provenance(view)
    seen = 0
    for path, value in iter_leaves(view):
        if not path or not is_number(value):
            continue
        printed_cdi = _printed(view, path, value).endswith("% do CDI")
        assert printed_cdi == (unit_of(view, path) == PCT_CDI), path
        if printed_cdi:
            seen += 1
            reason = revisor.check_sentence(view, f"Rendeu {{{{{path}}}}}.", sources)
            cdi_like = resolve(view, parent_path(path) + ".cdi_like") is True
            assert (reason is None) == cdi_like, (path, reason)
    if name == "demo":
        assert seen


def test_unit_not_spelling_decides_an_extreme_fee() -> None:
    """A key that contains '_pct' but is not a percentage (by the unit table) is no fee rate: no fee threshold."""
    view = {"fees": {"by_line": [{"fee_pctile": PROBE, "estimated_pct_year": PROBE}]}}
    assert unit_of(view, "fees.by_line[0].fee_pctile") != PCT
    assert revisor._extreme(view, "fees.by_line[0].fee_pctile", PROBE) is None
    assert revisor._extreme(view, "fees.by_line[0].estimated_pct_year", PROBE) == ("fee", PROBE)


def test_unit_not_spelling_decides_an_extreme_delinquency_change() -> None:
    """A restatement diff number is reais only on a VL_* field (DIFF_NUMBER_KEYS); a plain one is no R$100M change."""
    rows = [{"leaf": "VL_INAD", "change": 2e9}, {"leaf": "QT_INAD", "change": 2e9}]
    view = {"restatements": {"items": [{"diff": rows}]}}
    assert unit_of(view, "restatements.items[0].diff[0].change") == BRL
    assert revisor._extreme(view, "restatements.items[0].diff[0].change", 2e9) == ("delinquency_change", 2e9)
    assert unit_of(view, "restatements.items[0].diff[1].change") != BRL
    assert revisor._extreme(view, "restatements.items[0].diff[1].change", 2e9) is None
