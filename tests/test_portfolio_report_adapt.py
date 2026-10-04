"""The engine's schema 1.x as the report's view (src/portfolio/report/adapt.py), and the fee rules in the report."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.portfolio.report import adapt, build, redator, revisor, values

FIXTURES = Path(__file__).parent / "fixtures" / "portfolio"
ENGINE = FIXTURES / "demo_engine_output.json"
PROVISIONAL = FIXTURES / "report_provisional_engine_output.json"


@pytest.fixture(scope="module")
def engine() -> dict:
    return json.loads(ENGINE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def view(engine) -> dict:
    return adapt.to_view(engine)


@pytest.fixture(scope="module")
def html_and_narrative(view):
    return build.build(view, "fake")


def test_engine_output_is_recognised_and_the_view_is_not_the_engine(engine, view):
    assert adapt.is_engine_output(engine) and not adapt.is_engine_output(view)
    assert view["schema_version"] == adapt.VIEW_VERSION and view["engine_schema_version"] == engine["schema_version"]
    redator.assert_masked(view)  # the view carries no holder, account or CPF-shaped string


def test_the_view_has_every_key_the_report_was_built_on(view):
    prov = json.loads(PROVISIONAL.read_text(encoding="utf-8"))
    for section in ("portfolio", "fees", "lookthrough", "indexer", "sector", "restatements", "risk_screens"):
        assert set(prov[section]) - {"provenance", "basis"} <= set(view[section]) | {"basis"}, section
    assert set(prov["lines"][0]) <= set(view["lines"][0])
    assert set(prov["fees"]["by_line"][0]) - {"estimated_pct_year_high", "reason"} <= set(view["fees"]["by_line"][0])
    assert set(prov["lookthrough"]["shared_exposure"][0]) - {"name"} <= set(view["lookthrough"]["shared_exposure"][0])
    assert set(prov["restatements"]["items"][0]) <= set(view["restatements"]["items"][0])
    assert set(prov["sections"]) - {"ntnb_price"} <= set(view["sections"])
    # engine 1.7: the request params and error text stay in the engine JSON, never in the report's view
    assert set(prov["provenance"][0]) - {"params", "error"} <= set(view["provenance"][0])
    assert not {"params", "error", "args"} & set(view["provenance"][0])


def test_numbers_are_copied_not_computed(engine, view):
    assert view["portfolio"]["total_brl"] == engine["statement"]["sum_of_lines_brl"]
    assert view["fees"]["total_estimated_brl_year"] == engine["fees"]["totals"]["estimate_adm_per_year_brl"]
    assert view["fees"]["weighted_estimated_pct_year"] == engine["fees"]["totals"]["estimate_adm_portfolio_pct"]
    assert [b["weight_pct"] for b in view["indexer"]["buckets"]] == [c["portfolio_pct"] for c in engine["indexer"]["classes"]]
    assert view["indexer"]["buckets"][-1]["indexer"] == "sem classificação"
    assert [ln["weight_pct"] for ln in view["lines"]] == [p["portfolio_pct"] for p in engine["statement"]["positions"]]


def test_fee_view_follows_the_owner_rules(view):
    by = {b["line_id"]: b for b in view["fees"]["by_line"]}
    # the disclosed fee is the headline and says where it comes from
    l3 = by["L3"]
    assert l3["disclosed_pct_year"] == 2.0 and l3["disclosed_origin"] == "extrato" and l3["disclosed_origin_label"] == "Extrato CVM"
    assert l3["disclosed_scope_label"] == "taxa da classe" and l3["disclosed_as_of"] == "2026-07-31"
    assert l3["estimate_label"] == "estimativa, não divulgada" and l3["estimated_pct_year"] == 1.98  # apart, labelled
    # a filed 0: shown, no rate, no R$, not summed
    l5 = by["L5"]
    assert l5["filed_zero_label"] == "0 informado; a conferir"
    assert l5["disclosed_pct_year"] is None and l5["disclosed_brl_year"] is None
    assert l5["filed_zero_pct"] == 0.0 and l5["needs_manual_check"] is True
    assert view["fees"]["total_disclosed_brl_year"] == pytest.approx(by["L3"]["disclosed_brl_year"] + by["L7"]["disclosed_brl_year"])
    # the lâmina's 24 months, and the Extrato's 36
    assert by["L7"]["disclosed_stale"] is True and by["L7"]["disclosed_stale_label"] == "defasada"
    und = {(u["parent_line_id"], u["fund_cnpj"]): u for u in view["fees"]["underlying"]}
    cash = und[("L4", "54891935000134")]
    assert cash["disclosed_origin"] == "extrato" and cash["disclosed_age_months"] == 30 and cash["disclosed_stale"] is False
    bad = und[("L4", "37525998000158")]
    assert bad["implausible_label"] == "valor informado acima de 5% a.a.; a conferir" and bad["implausible_raw"] == 14638.0
    assert bad["disclosed_pct_year"] is None
    assert all(u["label_not_added"] == "não somada" for u in und.values())
    # nothing says the estimate is the fee
    assert not any("estimativa" in str(b.get("disclosed_origin_label")) for b in by.values())
    # the declared expense ratio is its own fields
    assert l3["expense_ratio_pct"] == 2.31 and l3["expense_ratio_period_from"] == "2025-07-01"


def test_values_format_the_new_fields(view):
    f = lambda p: values.format_value(view, p)
    assert f("fees.by_line[0].disclosed_pct_year") == "2,00%"
    assert f("fees.by_line[0].disclosed_as_of") == "31/07/2026"
    assert f("fees.by_line[0].expense_ratio_pct") == "2,31%"
    assert f("fees.by_line[0].expense_ratio_period_from") == "01/07/2025"
    assert f("fees.by_line[0].disclosed_age_months") == "1"
    assert f("fees.by_line[2].filed_zero_label") == "0 informado; a conferir"
    # a raw implausible value is a plain number, never printed as a rate or as reais
    und = next(i for i, u in enumerate(view["fees"]["underlying"]) if u["implausible_raw"] is not None)
    assert f(f"fees.underlying[{und}].implausible_raw") == "14.638,00" and "%" not in f(f"fees.underlying[{und}].implausible_raw")
    assert f("restatements.items[0].competencia") == "07/2026"


def test_the_html_states_every_fee_rule(html_and_narrative):
    html_text, narrative = html_and_narrative
    assert narrative.status == "complete"
    for needle in (
        "Extrato CVM", "taxa da classe", "0 informado; a conferir", "valor informado acima de 5% a.a.; a conferir",
        "defasada", "estimativa, não divulgada", "não somada", "taxa divulgada não encontrada", "lâmina CVM",
        "Divulgado 0, balancete registra despesa.", "Estimativa e divulgada divergem", "a conferir; pode estar correto",
        "performance, como informado: 20% do que exceder 100% do Ibovespa", "Despesa declarada",
    ):
        assert needle in html_text, needle
    # the raw high value is only ever shown as the value as filed, to be checked
    shown = re.findall(r"[^>]{0,25}14\.638,00[^<]{0,40}", html_text)
    assert shown and all(x.startswith("valor informado: 14.638,00 (a conferir") for x in shown)
    assert "{{" not in html_text and "}}" not in html_text


def test_the_fee_findings_never_present_the_estimate_as_the_fee(html_and_narrative):
    _, narrative = html_and_narrative
    fee_text = " ".join(f.text for f in narrative.kept if f.section == "taxas")
    assert "{{fees.total_disclosed_brl_year}}" in fee_text and "{{fees.estimate_label}}" in fee_text
    for f in narrative.kept:
        if f.section == "taxas" and "estimated_pct_year" in f.text:
            assert "estimate_label" in f.text or "à parte" in f.text


def test_revisor_thresholds_are_unchanged():
    assert (revisor.FEE_PCT_YEAR_MAX, revisor.EXPOSURE_PCT_MAX, revisor.DELINQUENCY_CHANGE_BRL_MAX) == (5.0, 50.0, 100_000_000.0)


def test_cli_builds_html_from_an_engine_document(tmp_path):
    out = tmp_path / "r.html"
    assert build.main([str(ENGINE), "--provider", "fake", "--html", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "0 informado; a conferir" in text and "Extrato CVM" in text
    assert "[TITULAR]" not in text and "C1" not in text


def test_the_provisional_fixture_still_renders_with_the_old_fee_wording():
    prov = json.loads(PROVISIONAL.read_text(encoding="utf-8"))
    html_text, _ = build.build(prov, "fake")
    assert "estimativa" in html_text and "{{" not in html_text


def test_the_report_never_calls_a_filed_zero_or_a_high_value_wrong(html_and_narrative):
    html_text, narrative = html_and_narrative
    visible = re.sub(r"<[^>]+>", " ", html_text).lower()
    for old in ("provavelmente não preenchido", "implausível", "descartado", "erro de escala"):
        assert old not in visible, old
    assert "valor informado: 0,00% a.a." in re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_text))
    kept = " ".join(f.title + " " + f.text for f in narrative.kept if f.section == "taxas")
    assert "implausível" not in kept.lower() and "descart" not in kept.lower()
