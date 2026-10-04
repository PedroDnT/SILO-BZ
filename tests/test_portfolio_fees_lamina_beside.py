"""The lâmina beside the Extrato, and the newer lâmina (catalog v55, engine 1.4, issue #552; summed since engine 1.5).

The SQL is executed in tests/sql/portfolio_behaviour.sql (EXT1 to EXT9). Here the engine, the report view and
the HTML are run offline on the canned rows with one statement fund (line 3, 08935128000159) edited into each
shape: Extrato 0 with a lâmina of 1.5; Extrato 15 with a lâmina of 1.5 (factor 10); Extrato 2 (no lâmina line);
Extrato 0 with no lâmina; and the Inter Corporate shape measured on 2026-10-03 (Extrato 25.0 of 2024-05-03, lâmina
0.25 of 2026-08-31, newer). Every number in the assertions comes from the canned row; nothing is computed here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.portfolio.client import FakeClient, load_fake_rows
from src.portfolio.diagnose import FAKE_CLOCK
from src.portfolio.engine import default_params, run_engine
from src.portfolio.fees import (
    IMPLAUSIBLE_LABEL,
    LAMINA_BESIDE_LABEL,
    LAMINA_NEWER_LABEL,
    SCALE_FLAG_LABEL,
    SOURCES_DIFFER_LABEL,
    ZERO_LABEL,
)
from src.portfolio.report import adapt, build, render
from src.portfolio.statement import read_statement

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "docs" / "reference" / "portfolio" / "statement-template.xlsx"
FAKE_ROWS = ROOT / "tests" / "fixtures" / "portfolio" / "fake_silo_rows.json"
CNPJ = "08935128000159"  # statement line 3 in the demo template; the Extrato 2.0 fund in the canned rows

NO_EXTRATO_TERMS = {k: None for k in (
    "extrato_tp_fundo_classe", "extrato_classe_anbima", "extrato_class_note", "extrato_existe_taxa_perfm",
    "extrato_taxa_perfm", "extrato_param_taxa_perfm", "extrato_calc_taxa_perfm", "extrato_inf_taxa_perfm",
)}

SHAPES = {
    # Extrato filed 0, an older lâmina discloses 1.5: the Extrato stays, the lâmina beside it.
    "zero_lamina": dict(
        disclosed_taxa_adm=0.0, disclosed_taxa_adm_min=0.0, disclosed_taxa_adm_max=0.0, filed_zero=True,
        implausible_filed=False, taxa_adm_filed_raw=0.0, fee_resolution="extrato_lamina_beside",
        lamina_taxa_adm=1.5, lamina_taxa_adm_min=1.5, lamina_taxa_adm_max=1.5, lamina_n_classes=1,
        lamina_as_of="2026-03-31", lamina_age_months=5, extrato_taxa_adm_filed=0.0, extrato_as_of="2026-07-31",
        extrato_lamina_ratio=None, extrato_scale_factor=None,
    ),
    # Extrato filed 15, an older lâmina 1.5: withheld, the lâmina beside, factor 10 flagged.
    "fifteen_lamina": dict(
        disclosed_taxa_adm=None, disclosed_taxa_adm_min=None, disclosed_taxa_adm_max=None, filed_zero=False,
        implausible_filed=True, taxa_adm_filed_raw=15.0, fee_resolution="extrato_lamina_beside",
        lamina_taxa_adm=1.5, lamina_taxa_adm_min=1.5, lamina_taxa_adm_max=1.5, lamina_n_classes=1,
        lamina_as_of="2026-03-31", lamina_age_months=5, extrato_taxa_adm_filed=15.0, extrato_as_of="2026-07-31",
        extrato_lamina_ratio=10.0, extrato_scale_factor=10,
    ),
    # Extrato 2 (in range) with a lâmina: no lâmina line, no flag.
    "two_lamina": dict(
        fee_resolution="extrato", lamina_taxa_adm=1.5, lamina_taxa_adm_min=1.5, lamina_taxa_adm_max=1.5,
        lamina_n_classes=1, lamina_as_of="2026-03-31", lamina_age_months=5, extrato_taxa_adm_filed=2.0,
        extrato_as_of="2026-07-31", extrato_lamina_ratio=1.3333, extrato_scale_factor=None,
    ),
    # Extrato 0 and no lâmina: nothing beside, still to check.
    "zero_alone": dict(
        disclosed_taxa_adm=0.0, disclosed_taxa_adm_min=0.0, disclosed_taxa_adm_max=0.0, filed_zero=True,
        implausible_filed=False, taxa_adm_filed_raw=0.0, fee_resolution="extrato_to_check",
        lamina_taxa_adm=None, lamina_taxa_adm_min=None, lamina_taxa_adm_max=None, lamina_n_classes=None,
        lamina_as_of=None, lamina_age_months=None, extrato_taxa_adm_filed=0.0, extrato_as_of="2026-07-31",
        extrato_lamina_ratio=None, extrato_scale_factor=None,
    ),
    # Inter Corporate shape (36443522000105, measured 2026-10-03): the newer lâmina is the source.
    "lamina_newer": dict(
        disclosed_taxa_adm=0.25, disclosed_taxa_adm_min=0.25, disclosed_taxa_adm_max=0.25, filed_zero=False,
        implausible_filed=False, taxa_adm_filed_raw=0.25, disclosed_origin="lamina", disclosed_source="cvm_fi_lamina",
        disclosed_as_of="2026-08-31", disclosed_age_months=0, disclosed_age_days=33, disclosed_taxa_perfm=None,
        fee_resolution="lamina_newer", lamina_taxa_adm=0.25, lamina_taxa_adm_min=0.25, lamina_taxa_adm_max=0.25,
        lamina_n_classes=1, lamina_as_of="2026-08-31", lamina_age_months=0, extrato_taxa_adm_filed=25.0,
        extrato_as_of="2024-05-03", extrato_lamina_ratio=100.0, extrato_scale_factor=100, **NO_EXTRATO_TERMS,
    ),
}


def _run(shape: str) -> dict:
    canned = load_fake_rows(FAKE_ROWS)
    for entry in canned["portfolio_fees"]:
        for row in entry["rows"]:
            if row["cnpj"] == CNPJ:
                row.update(SHAPES[shape])
    stmt = read_statement(TEMPLATE)
    return run_engine(stmt, FakeClient(canned, clock=lambda: FAKE_CLOCK), default_params(stmt.position_date),
                      clock=lambda: FAKE_CLOCK)


def _line(doc: dict) -> dict:
    return next(ln for ln in doc["fees"]["lines"] if ln["cnpj"] == CNPJ)


def _others_fixed_total(doc: dict) -> float:
    return round(sum(ln["headline"]["per_year_brl"] for ln in doc["fees"]["lines"]
                     if ln["cnpj"] != CNPJ and (ln.get("headline") or {}).get("kind") == "fixa"), 2)


def _html(doc: dict) -> str:
    html_text, _ = build.build(adapt.to_view(doc), "fake")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_text))


@pytest.fixture(scope="module")
def runs() -> dict:
    return {k: _run(k) for k in SHAPES}


def test_extrato_zero_shows_the_lamina_beside_and_sums_neither(runs):
    doc = runs["zero_lamina"]
    ln = _line(doc)
    assert ln["fee_status"] == ZERO_LABEL and ln["needs_manual_check"] is True
    assert ln["headline"]["kind"] == "zero_informado" and ln["headline"]["counted_as_cost"] is False
    lb = ln["lamina_beside"]
    assert lb["label"] == LAMINA_BESIDE_LABEL == "lâmina informa" and lb["check_label"] == "a conferir"
    assert lb["lamina_pct_year"] == 1.5 and lb["as_of"] == "2026-03-31" and lb["counted_as_cost"] is False
    assert ln["scale_flag"] is None and ln["extrato_beside"] is None
    assert ln["fee_resolution"] == "extrato_lamina_beside"
    t = doc["fees"]["totals"]
    assert t["adm_disclosed_fixed_per_year_brl"] == _others_fixed_total(doc)  # neither the 0 nor the 1.5 is summed
    assert t["fund_value_with_filed_zero_brl"] >= ln["position_value_brl"]
    assert "lâmina informa 1,50% a.a.; a conferir (lâmina de 31/03/2026)" in _html(doc)


def test_extrato_fifteen_against_lamina_one_and_a_half_flags_a_possible_scale_error(runs):
    doc = runs["fifteen_lamina"]
    ln = _line(doc)
    assert ln["fee_status"] == IMPLAUSIBLE_LABEL and ln["needs_manual_check"] is True and ln["headline"] is None
    assert ln["disclosed"]["adm_filed_raw"] == 15.0  # as filed, never rescaled to 0.15 or 1.5
    assert ln["lamina_beside"]["lamina_pct_year"] == 1.5
    sf = ln["scale_flag"]
    assert sf["label"] == SCALE_FLAG_LABEL == "possível erro de escala no Extrato"
    assert sf["factor"] == 10 and sf["extrato_lamina_ratio"] == 10.0
    finding = next(f for f in ln["findings"] if f["kind"] == "possivel_erro_de_escala_no_extrato")
    assert finding["factor"] == 10 and "nada foi corrigido" in finding["text"]
    t = doc["fees"]["totals"]
    assert t["adm_disclosed_fixed_per_year_brl"] == _others_fixed_total(doc)
    # the implausible bucket holds the line (engine 1.3 read a key the record never had, so it stayed 0)
    assert t["fund_value_with_implausible_fee_brl"] == ln["position_value_brl"]
    text = _html(doc)
    assert "lâmina informa 1,50% a.a.; a conferir" in text and "possível erro de escala no Extrato" in text
    assert "valor informado: 15,00 (a conferir" in text


def test_an_extrato_in_range_shows_no_lamina_line(runs):
    doc = runs["two_lamina"]
    ln = _line(doc)
    assert ln["fee_status"] == "divulgada" and ln["needs_manual_check"] is False
    assert ln["headline"]["rate_pct_year"] == 2.0
    assert ln["lamina_beside"] is None and ln["extrato_beside"] is None and ln["scale_flag"] is None
    assert not any(f["kind"].startswith(("lamina_", "possivel_")) for f in ln["findings"])
    bl = next(b for b in adapt.to_view(doc)["fees"]["by_line"] if b["cnpj"] == CNPJ)
    assert bl["lamina_beside_label"] is None and bl["scale_flag_label"] is None
    view = adapt.to_view(doc)
    i = next(k for k, b in enumerate(view["fees"]["by_line"]) if b["cnpj"] == CNPJ)
    assert "lâmina informa" not in " ".join(render._fee_row(view, f"fees.by_line[{i}]", view["fees"]["by_line"][i]))


def test_an_extrato_zero_without_a_lamina_has_no_line_and_is_still_to_check(runs):
    doc = runs["zero_alone"]
    ln = _line(doc)
    assert ln["fee_status"] == ZERO_LABEL and ln["needs_manual_check"] is True
    assert ln["lamina_beside"] is None and ln["scale_flag"] is None and ln["fee_resolution"] == "extrato_to_check"
    assert doc["fees"]["totals"]["adm_disclosed_fixed_per_year_brl"] == _others_fixed_total(doc)


def test_a_newer_lamina_is_the_headline_summed_and_compared_and_still_to_check(runs):
    """Owner's decision of 2026-10-03 (engine 1.5): the newer lâmina's fee is a disclosed fee like any other."""
    doc = runs["lamina_newer"]
    ln = _line(doc)
    assert ln["fee_resolution"] == "lamina_newer" and ln["fee_status"] == LAMINA_NEWER_LABEL
    # still flagged for review: the two documents disagree
    assert ln["needs_manual_check"] is True and ln["disclosed"]["needs_manual_check"] is True
    h = ln["headline"]
    assert h["kind"] == "lamina_mais_recente" and h["rate_pct_year"] == 0.25 and h["origin"] == "lamina"
    assert h["sources_differ_label"] == SOURCES_DIFFER_LABEL == "fontes divergem"
    # a cost: the statement's value (264.615,00) times the lâmina's 0,25% a.a., from the canned rows
    assert h["as_of"] == "2026-08-31" and h["counted_as_cost"] is True
    assert h["per_year_brl"] == round(ln["position_value_brl"] * 0.25 / 100, 2) == 661.54
    xb = ln["extrato_beside"]
    assert xb["filed_value"] == 25.0 and xb["as_of"] == "2024-05-03" and xb["counted_as_cost"] is False
    assert ln["lamina_beside"] is None
    assert ln["scale_flag"]["factor"] == 100
    # compared with the balancete estimate (1,98% a.a. in the canned row) like any disclosed fee
    diff = next(f for f in ln["findings"] if f["kind"] == "estimativa_difere_da_divulgada")
    assert diff["disclosed_pct_year"] == 0.25 and diff["estimate_pct_year"] == 1.98
    note = next(f for f in ln["findings"] if f["kind"] == "lamina_mais_recente_que_extrato")
    assert "Fontes divergem" in note["text"] and "entra na soma" in note["text"]
    t = doc["fees"]["totals"]
    # summed: the other fixed fees plus this one; the Extrato's 25 is never summed
    assert t["adm_disclosed_fixed_per_year_brl"] == pytest.approx(_others_fixed_total(doc) + 661.54, abs=0.01)
    assert t["fund_value_with_lamina_newer_fee_brl"] == ln["position_value_brl"]
    assert t["fund_value_with_fixed_fee_brl"] >= ln["position_value_brl"]  # a subset of it since 1.5
    # counted once: not in the bucket of lines without a usable fee
    zero_check = runs["zero_lamina"]["fees"]["totals"]
    assert t["fund_value_without_disclosed_fee_brl"] == pytest.approx(
        zero_check["fund_value_without_disclosed_fee_brl"] - ln["position_value_brl"], abs=0.01)
    assert t["fund_value_brl"] == pytest.approx(sum(x["position_value_brl"] for x in doc["fees"]["lines"]))
    assert any("fontes divergem" in d for d in [doc["fees"].get("reason") or ""])
    view = adapt.to_view(doc)
    bl = next(b for b in view["fees"]["by_line"] if b["cnpj"] == CNPJ)
    assert bl["disclosed_pct_year"] == 0.25 and bl["disclosed_brl_year"] == 661.54
    assert bl["extrato_beside_value"] == 25.0 and bl["lamina_newer_label"] == LAMINA_NEWER_LABEL
    assert bl["sources_differ_label"] == "fontes divergem"
    assert view["fees"]["total_disclosed_brl_year"] == t["adm_disclosed_fixed_per_year_brl"]
    text = _html(doc)
    assert "0,25% a.a." in text and LAMINA_NEWER_LABEL in text and "fontes divergem" in text
    assert "R$ 661,54 por ano" in text
    assert "Extrato de 03/05/2024 informa 25,00 (como informado; não somado)" in text
    assert "possível erro de escala no Extrato" in text


def test_the_redator_writes_the_pair_with_placeholders_only(runs):
    view = adapt.to_view(runs["lamina_newer"])
    i = next(k for k, b in enumerate(view["fees"]["by_line"]) if b["cnpj"] == CNPJ)
    _, narrative = build.build(view, "fake")
    kept = [f for f in narrative.kept if f.section == "taxas" and f"fees.by_line[{i}]" in f.text]
    assert any("extrato_beside_value" in f.text and "lamina_newer_label" in f.text for f in kept)
    for f in kept:
        assert not re.search(r"\d", re.sub(r"\{\{[^}]+\}\}", "", f.text))  # every number is a placeholder
