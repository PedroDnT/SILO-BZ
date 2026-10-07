"""Engine 2.0: the return, tax and equivalent blocks write codes; the report writes their reader text.

``src/portfolio/report/labels.py`` holds the text and ``adapt`` adds it at the view paths the renderer and the
Redator's placeholders always read, so the report did not change when the engine stopped writing it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.portfolio.report import adapt
from src.portfolio.report import labels as reader_text

FIXTURE = Path(__file__).parent / "fixtures" / "portfolio" / "demo_engine_output.json"
REMOVED = re.compile(r'"(status_label|basis_label|gross_label|pl_label|fee_label|etf_band_label|fund_band_label|'
                     r'rate_text|rate_today_text|instrument_label|third_party_label|regime_label|base_text|'
                     r'irrevocable_text)"')


def _engine() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_the_engine_writes_no_reader_text_in_the_three_blocks():
    eng = _engine()
    assert eng["schema_version"].startswith("2.")
    for block in ("returns", "tax", "equivalents"):
        assert not REMOVED.search(json.dumps(eng[block], ensure_ascii=False)), block


def test_the_view_adds_the_return_labels_from_the_codes():
    view = adapt.to_view(_engine())
    lines = view["returns"]["lines"]
    assert lines
    for ln in lines:
        assert ln["basis_label"] == reader_text.RETURN_BASIS.get(ln["basis"])
        assert ln["status_label"] == reader_text.RETURN_STATUS[ln["status"]]
        for w in ln["windows"]:
            assert w["status_label"] == reader_text.RETURN_STATUS[w["status"]]
            assert w["gross_label"] == "estimativa"
    assert any(ln["status_label"] == "não avaliado" for ln in lines)


def test_the_view_adds_the_equivalent_and_tax_labels():
    view = adapt.to_view(_engine())
    eq = view["equivalents"]
    assert eq["pl_label"] == reader_text.EQUIVALENT_PL and eq["fee_label"] == reader_text.EQUIVALENT_FEE
    found = [ln for ln in eq["lines"] if ln["etf"]]
    assert found
    for ln in found:
        assert "terceiros" in ln["etf"]["pl_label"] and "terceiros" in ln["etf"]["fee_label"]
        assert ln["etf"]["basis_label"] == reader_text.RETURN_BASIS[ln["etf"]["basis"]]
        for w in ln["windows"]:
            for who in ("etf", "fund"):
                assert w[f"{who}_band_label"] == reader_text.BANDS.get(w[f"{who}_band"])
    for ln in view["tax"]["lines"]:
        t = ln["tax"]
        assert t["status_label"] == reader_text.TAX_STATUS[t["status"]]
        assert t["rate_text"] == reader_text.tax_rate_text(t)
        assert t["instrument_label"] == reader_text.tax_instrument_label(t)
        assert all(c["rate_today_text"] == reader_text.pct_text(c["rate_today_pct"]) for c in t["candidates"])
    assert any(ln["tax"]["rate_text"] for ln in view["tax"]["lines"])


def test_pct_text_prints_the_rate_as_the_law_does():
    assert reader_text.pct_text(22.5) == "22,5%" and reader_text.pct_text(20.0) == "20%"
    assert reader_text.pct_text(15) == "15%" and reader_text.pct_text(None) is None
    assert reader_text.tax_rate_text({"status": "isento", "rate_today_pct": 0.0}) == "isento"
    assert reader_text.tax_rate_text({"status": "faixa", "rate_today_pct": None}) is None


def test_a_1x_document_still_reads_and_its_labels_are_the_reports():
    eng = _engine()
    assert adapt.is_engine_output(eng)
    old = json.loads(json.dumps(eng))
    old["schema_version"] = "1.15"
    old["returns"]["lines"][0]["basis_label"] = "texto antigo"
    assert adapt.is_engine_output(old)
    assert adapt.to_view(old)["returns"]["lines"][0]["basis_label"] == adapt.to_view(eng)["returns"]["lines"][0]["basis_label"]
