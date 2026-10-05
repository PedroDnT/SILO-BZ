"""Offline tests of the Redator, the Revisor and the renderer, over a synthetic engine JSON."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from src.portfolio.report import build, llm, redator, render, revisor, values
from src.portfolio.report.redator import Finding

FIXTURE = Path(__file__).parent / "fixtures" / "portfolio" / "report_provisional_engine_output.json"


@pytest.fixture()
def engine() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def F(text, cites=("p1",), title="Título", section="achados", id="f1"):
    return Finding(id, section, title, text, list(cites))


# --- values / formatting -----------------------------------------------------


def test_brazilian_formatting(engine):
    assert values.format_value(engine, "portfolio.total_brl") == "R$ 900.000,00"
    assert values.format_value(engine, "fees.weighted_estimated_pct_year") == "0,79%"
    assert values.format_value(engine, "restatements.items[0].delinquency_new_brl") == "R$ 187,3 milhões"
    assert values.format_value(engine, "lines[2].cnpj") == "08.935.128/0001-59"
    assert values.format_value(engine, "valuation_date") == "30/09/2026"
    assert values.format_value(engine, "fees.by_line[0].month") == "08/2026"
    assert values.format_value(engine, "lines[3].identification.candidates[0].quota") == "1,542011"
    assert values.format_value(engine, "fees.total_disclosed_brl_year") == "—"


def test_timestamps_are_shown_in_utc_minus_3_with_utc_in_parentheses(engine):
    assert values.format_value(engine, "generated_at") == "03/10/2026 13:00 (UTC-3) (16:00 UTC)"
    assert engine["generated_at"] == "2026-10-03T16:00:00Z"  # stored value untouched


def test_resolve_and_malformed_paths(engine):
    assert values.resolve(engine, "lines[1].ticker") == "PETR4"
    assert values.resolve(engine, "lines[99].ticker") is values.MISSING
    assert values.resolve(engine, "lines[1]..x") is values.MISSING
    assert values.resolve(engine, "__import__('os')") is values.MISSING


# --- masking -----------------------------------------------------------------


def test_assert_masked_accepts_the_fixture(engine):
    redator.assert_masked(engine)


@pytest.mark.parametrize("patch", [
    {"cliente": "Fulano de Tal"},
    {"titular": {"nome": "x"}},
    {"conta": "12345-6"},
    {"note": "CPF 123.456.789-09"},
    {"note": "12345678909"},
])
def test_assert_masked_refuses_client_identity(engine, patch):
    engine["portfolio"].update(patch)
    with pytest.raises(redator.UnmaskedInputError):
        redator.assert_masked(engine)


def test_masked_value_and_numbers_are_not_flagged(engine):
    engine["portfolio"]["cliente"] = "****"
    engine["portfolio"]["big"] = 12345678909  # a number, not a CPF string
    redator.assert_masked(engine)


def test_redator_asserts_before_calling_the_model(engine):
    engine["portfolio"]["conta"] = "999"
    fake = llm.FakeProvider([{"findings": []}])
    with pytest.raises(redator.UnmaskedInputError):
        redator.write(engine, fake)
    assert fake.calls == []


def test_redator_sends_the_masked_engine_json_and_a_schema(engine):
    fake = llm.FakeProvider([{"findings": []}])
    redator.write(engine, fake)
    call = fake.calls[0]
    assert "PETR4" in call["user"] and call["schema"] is redator.FindingsOutput
    assert "nunca escreve um algarismo" in call["system"]


@pytest.mark.parametrize("reply", [
    {"findings": [{"id": "f1", "section": "opiniao", "title": "t", "text": "x", "citations": ["p1"]}]},  # off-enum
    {"findings": [{"id": "f1", "section": "resumo", "title": "t", "text": "x"}]},  # citations missing
    {"findings": [], "extra": True},  # a key the schema forbids
    {"achados": []},  # no findings list
])
def test_redator_reply_that_fails_validation_becomes_unknown_like_a_refusal(engine, reply):
    res = redator.write(engine, llm.FakeProvider([reply]))
    assert res.status == "unknown" and res.findings == [] and "LLMValidationError" in res.reason


def test_validation_failure_marks_the_narrative_unknown_and_tables_still_print(engine):
    bad = llm.FakeProvider([{"findings": [{"id": "f1", "section": "x", "title": "t", "text": "x", "citations": []}]}])
    narrative = build.make_narrative(engine, bad)
    html_text = render.render_html(engine, narrative)
    assert narrative.status == "unknown" and "LLMValidationError" in narrative.reason
    assert "Texto interpretativo indisponível" in html_text and "R$ 150.000,00" in html_text


def test_redator_failure_becomes_unknown_narrative(engine):
    class Boom:
        name = "fake"

        def complete(self, *a, **k):
            raise llm.LLMRefusalError("cyber")

    res = redator.write(engine, Boom())
    assert res.status == "unknown" and "LLMRefusalError" in res.reason


# --- the deterministic writer covers every section ---------------------------


def test_template_writer_covers_every_section_and_passes_the_revisor(engine):
    findings = redator._coerce_findings(redator.template_findings(engine))
    result = revisor.check(engine, findings)
    assert result.removed == []
    # "riscos" needs the engine 1.8 risks section, "retornos", "impostos" and "equivalentes" the 1.10, 1.11 and 1.13 blocks,
    # which the provisional view does not carry
    absent = {"riscos": "risks", "retornos": "returns", "impostos": "tax", "equivalentes": "equivalents"}
    expected = set(redator.SECTIONS) - {sec for sec, key in absent.items() if key not in engine}
    assert {f.section for f in result.kept} == expected
    for f in result.kept:  # rule zero: no digit outside a placeholder
        assert not re.search(r"\d", values.PLACEHOLDER_RE.sub("", f.text + f.title))


# --- Revisor -----------------------------------------------------------------


def test_placeholder_without_path_removes_the_sentence(engine):
    res = revisor.check(engine, [F("Isto é fato. Valor {{fees.nope}}. Outra frase.")])
    assert res.kept[0].text == "Isto é fato. Outra frase."
    assert "sem caminho" in res.removed[0].reason and not res.removed[0].whole_finding


def test_null_and_non_scalar_placeholders_are_removed(engine):
    res = revisor.check(engine, [F("A {{fees.total_disclosed_brl_year}}. B {{lines}}. C ok.")])
    assert res.kept[0].text == "C ok."
    reasons = " ".join(r.reason for r in res.removed)
    assert "nulo" in reasons and "não escalar" in reasons


def test_literal_digit_outside_placeholder_is_removed(engine):
    res = revisor.check(engine, [F("Custa 7 mil reais. O total é {{portfolio.total_brl}}.")])
    assert res.kept[0].text == "O total é {{portfolio.total_brl}}."
    assert res.removed[0].reason == "algarismo fora de marcador"


def test_digits_inside_a_placeholder_path_do_not_trip_the_digit_rule(engine):
    res = revisor.check(engine, [F("Linha {{lines[2].fund_name}}.")])
    assert res.removed == [] and len(res.kept) == 1


def test_unknown_citation_removes_the_whole_finding(engine):
    res = revisor.check(engine, [F("Frase {{portfolio.total_brl}}.", cites=("p99",))])
    assert res.kept == [] and res.removed[0].whole_finding and "p99" in res.removed[0].reason


def test_missing_citation_removes_the_whole_finding(engine):
    res = revisor.check(engine, [F("Frase {{portfolio.total_brl}}.", cites=())])
    assert res.kept == []


def test_source_named_outside_provenance_is_removed(engine):
    del engine["data_dates"]["BCB"]
    engine["provenance"] = [p for p in engine["provenance"] if p["source"] != "BCB"]
    res = revisor.check(engine, [F("Segundo o BCB algo mudou. Segundo a CVM outra coisa.")])
    assert res.kept[0].text == "Segundo a CVM outra coisa."


def test_extreme_delinquency_change_is_kept_with_a_second_path(engine):
    # items[0].delinquency_change_brl is confirmed by items[0].diff[0].change_brl
    f = F("A inadimplência mudou em {{restatements.items[0].delinquency_change_brl}}.")
    res = revisor.check(engine, [f])
    assert res.removed == [] and len(res.kept) == 1


def test_extreme_delinquency_change_is_removed_without_a_second_path(engine):
    engine["restatements"]["items"][0]["diff"] = []
    f = F("A inadimplência mudou em {{restatements.items[0].delinquency_change_brl}}.")
    res = revisor.check(engine, [f])
    assert res.kept == []
    assert any("valor extremo" in r.reason for r in res.removed)


def test_diff_row_alone_is_not_enough_either(engine):
    item = engine["restatements"]["items"][0]
    item["delinquency_change_brl"] = None
    item["delinquency_new_brl"] = None  # the restatement row no longer carries the amount
    f = F("A folha mudou em {{restatements.items[0].diff[0].change_brl}}.")
    res = revisor.check(engine, [f])
    assert res.kept == []  # the only other path carrying it is now null


def test_extreme_fee_needs_a_second_path(engine):
    engine["fees"]["by_line"][0]["estimated_pct_year"] = 6.25
    f = F("A taxa é {{fees.by_line[0].estimated_pct_year}}.")
    assert revisor.check(engine, [f]).kept == []
    engine["fees"]["by_line"][0]["confirmed_by"] = "fees.by_line[0].lamina_pct_year"
    engine["fees"]["by_line"][0]["lamina_pct_year"] = 6.25
    assert len(revisor.check(engine, [f]).kept) == 1


def test_extreme_exposure_is_removed_without_confirmation(engine):
    engine["lookthrough"]["shared_exposure"][0]["total_pct"] = 61.5
    f = F("A exposição é {{lookthrough.shared_exposure[0].total_pct}}.")
    assert revisor.check(engine, [f]).kept == []


def test_normal_values_are_not_treated_as_extreme(engine):
    f = F("Pós-fixado {{indexer.buckets[0].weight_pct}}, taxa {{fees.by_line[0].estimated_pct_year}}.")
    assert len(revisor.check(engine, [f]).kept) == 1


# --- optional LLM pass ---------------------------------------------------------


def _kept(engine):
    return revisor.check(engine, [F("Total {{portfolio.total_brl}}. Linhas {{portfolio.n_lines}}.", id="f1"),
                                  F("Taxa {{fees.weighted_estimated_pct_year}}.", id="f2")])


def test_llm_pass_can_delete_and_reword(engine):
    verdicts = {"verdicts": [
        {"id": "f1", "action": "reword", "text": "O total é {{portfolio.total_brl}}.", "reason": "tom"},
        {"id": "f2", "action": "delete", "text": "", "reason": "redundante"},
    ]}
    out = revisor.llm_review(engine, _kept(engine), llm.FakeProvider([verdicts]))
    assert [f.id for f in out.kept] == ["f1"] and out.kept[0].text == "O total é {{portfolio.total_brl}}."
    assert any("redundante" in r.reason for r in out.removed)


def test_llm_pass_cannot_add_a_placeholder(engine):
    verdicts = {"verdicts": [{"id": "f1", "action": "reword",
                              "text": "Total {{portfolio.total_brl}} e taxa {{fees.weighted_estimated_pct_year}}.", "reason": ""}]}
    out = revisor.llm_review(engine, _kept(engine), llm.FakeProvider([verdicts]))
    assert out.kept[0].text.startswith("Total {{portfolio.total_brl}}. Linhas")  # original kept
    assert any("acrescentou" in n for n in out.notes)


def test_llm_pass_cannot_add_a_digit(engine):
    verdicts = {"verdicts": [{"id": "f1", "action": "reword",
                              "text": "O total é {{portfolio.total_brl}}, uns 900 mil.", "reason": ""}]}
    out = revisor.llm_review(engine, _kept(engine), llm.FakeProvider([verdicts]))
    assert "900" not in out.kept[0].text
    assert any("deterministica" in n.replace("í", "i") for n in out.notes)


def test_llm_pass_failure_keeps_the_deterministic_result(engine):
    class Boom:
        name = "x"

        def complete(self, *a, **k):
            raise llm.CostCapExceeded("cap")

    base = _kept(engine)
    out = revisor.llm_review(engine, base, Boom())
    assert out.kept == base.kept and out.notes


def test_llm_pass_reply_that_fails_validation_keeps_the_deterministic_result(engine):
    bad = {"verdicts": [{"id": "f1", "action": "rewrite", "text": "", "reason": ""}]}  # action off the enum
    base = _kept(engine)
    out = revisor.llm_review(engine, base, llm.FakeProvider([bad]))
    assert out.kept == base.kept
    assert any("LLMValidationError" in n for n in out.notes)


def test_llm_pass_validates_a_reply_even_from_a_provider_that_does_not():
    class Raw:  # a provider that hands back an unvalidated dict
        name = "raw"

        def complete(self, *a, **k):
            return {"verdicts": [{"id": "f1", "action": "keep"}]}  # text and reason missing

    engine = json.loads(FIXTURE.read_text(encoding="utf-8"))
    out = revisor.llm_review(engine, _kept(engine), Raw())
    assert any("LLMValidationError" in n for n in out.notes)


# --- renderer ----------------------------------------------------------------


def _html(engine, provider="fake", signature=None):
    return build.build(engine, provider, signature)


def test_html_has_every_required_section_and_no_leftover_placeholders(engine):
    html_text, narrative = _html(engine)
    assert narrative.status == "complete"
    for title in ("Resumo", "Identificação linha a linha", "Custo em taxas", "Exposição", "Reapresentações",
                  "Sinais de risco", "O que não foi possível avaliar", "Metodologia e limitações"):
        assert f"<h2>{title}</h2>" in html_text
    assert "{{" not in html_text and "}}" not in html_text
    assert "SILO" in html_text


def test_html_shows_labels_unknowns_and_limits(engine):
    html_text, _ = _html(engine)
    for needle in ("estimativa", "sem classificação", "revisado, não avaliado", "Grupo econômico não avaliado",
                   "não é recomendação de investimento", "Não há previsão de retorno",
                   "Movimento anormal de cota ou de patrimônio", "não avaliado",
                   "não identificada"):
        assert needle in html_text, needle


def test_every_unknown_section_appears_with_a_fixed_label(engine):
    # a view without engine 1.7 "gaps": the section's name and a fixed status label, never its free-text reason
    html_text, _ = _html(engine)
    for name, sec in engine["sections"].items():
        if sec["status"] in ("partial", "unknown"):
            assert f"<strong>{name}</strong>: {render.SECTION_STATUS_LABELS[sec['status']]}." in html_text
            assert sec["reason"] not in html_text.split("O que não foi possível avaliar")[1].split("Metodologia")[0]


def test_footer_lists_sources_with_data_dates(engine):
    html_text, _ = _html(engine)
    footer = html_text.split('<footer class="rodape">')[1]
    for src, date in (("CVM", "31/08/2026"), ("B3", "02/10/2026"), ("FNET", "20/08/2026"), ("Banco Central", "02/10/2026")):
        assert re.search(rf"{src}[^<]*: dados até {date}", footer), src


def test_signature_default_cli_and_env(engine, monkeypatch):
    monkeypatch.delenv(render.SIGNATURE_ENV, raising=False)
    assert "Pedro Todescan, pesquisador independente" in _html(engine)[0]
    monkeypatch.setenv(render.SIGNATURE_ENV, "Outra Pessoa, analista")
    assert "Outra Pessoa, analista" in _html(engine)[0]
    assert "Cli Sig" in _html(engine, signature="Cli Sig")[0]


def test_no_client_identification_and_no_consultancy_on_the_cover(engine):
    html_text, _ = _html(engine)
    cover = html_text.split("</header>")[0]
    assert "<h1>Diagnóstico de carteira</h1>" in cover and "SILO" in cover
    assert not re.search(r"\d{3}\.\d{3}\.\d{3}-\d{2}", html_text)  # no CPF-shaped text


def test_engine_strings_are_html_escaped(engine):
    engine["lines"][1]["instrument"] = "<script>alert(1)</script>"
    html_text, _ = _html(engine)
    assert "<script>alert" not in html_text and "&lt;script&gt;" in html_text


def test_unknown_narrative_is_labelled_not_hidden(engine):
    class Refuse:
        name = "fake"
        meter = llm.CostMeter()

        def complete(self, *a, **k):
            raise llm.LLMRefusalError("SENTINELA-RECUSA")

    narrative = build.make_narrative(engine, Refuse())
    html_text = render.render_html(engine, narrative)
    assert narrative.status == "unknown"
    # engine 1.7: a fixed text; the error class and message stay in the narrative (logs, headers), not in the page
    assert "Texto interpretativo indisponível" in html_text and "LLMRefusalError" not in html_text and "SENTINELA" not in html_text
    assert narrative.reason_code == "LLMRefusalError"
    assert "R$ 150.000,00" in html_text  # the tables still come from the engine


def test_cost_cap_stops_the_narrative_and_marks_it_unknown(engine):
    meter = llm.CostMeter(cap_usd=0.001)
    provider = llm.AnthropicProvider(client=object(), meter=meter, fallbacks="off")
    narrative = build.make_narrative(engine, provider)
    assert narrative.status == "unknown" and "CostCapExceeded" in narrative.reason


def test_figures_in_html_all_come_from_the_engine(engine):
    """Rule zero, end to end: every R$ amount and percentage in the findings text is a formatted engine leaf."""
    html_text, narrative = _html(engine)
    allowed = set()
    for path, v in values.iter_leaves(engine):
        if values.is_number(v):
            allowed.add(values.format_value(engine, path, v))
    for f in narrative.kept:
        for ph in revisor.placeholders(f.text):
            assert values.format_value(engine, ph) in allowed or not values.is_number(values.resolve(engine, ph))


def test_cli_writes_html_offline(tmp_path):
    out_html = tmp_path / "r.html"
    assert build.main([str(FIXTURE), "--provider", "fake", "--html", str(out_html)]) == 0
    assert out_html.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_cli_writes_pdf_offline(tmp_path):
    try:  # an OSError, not an ImportError, when pango is missing
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        pytest.skip("weasyprint or its system libraries (pango) are not installed here (requirements-report.txt)")
    out_pdf = tmp_path / "r.pdf"
    assert build.main([str(FIXTURE), "--provider", "fake", "--out", str(out_pdf)]) == 0
    assert out_pdf.read_bytes()[:5] == b"%PDF-" and out_pdf.stat().st_size > 5_000


def test_fake_path_does_not_import_anthropic_openai_or_weasyprint():
    import subprocess, sys
    code = ("import sys, json; from src.portfolio.report import build; "
            f"e=json.load(open({str(FIXTURE)!r})); build.build(e, 'fake'); "
            "assert 'anthropic' not in sys.modules and 'weasyprint' not in sys.modules; "
            "assert 'openai' not in sys.modules")
    subprocess.run([sys.executable, "-c", code], check=True, cwd=Path(__file__).parent.parent)


def test_cli_refuses_an_unmasked_engine_json(tmp_path, engine, capsys):
    engine["portfolio"]["cpf"] = "123.456.789-09"
    p = tmp_path / "e.json"
    p.write_text(json.dumps(engine), encoding="utf-8")
    assert build.main([str(p), "--provider", "fake", "--html", str(tmp_path / "o.html")]) == 2
    assert "not masked" in capsys.readouterr().err


def test_fixture_is_synthetic_and_masked(engine):
    assert engine["illustrative"] is True and engine["masked"] is True
    assert copy.deepcopy(engine) == engine
