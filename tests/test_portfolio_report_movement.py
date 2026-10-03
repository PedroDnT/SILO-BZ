"""Movimento incomum in the report (owner decisions of 2026-10-03, map #510).

`atencao` (strictly beyond 2 class standard deviations) is shown in a table only; `forte` (beyond 3) may be written in
the text, with {{placeholders}} only; a fund the engine could not judge is written as "não avaliado" with its reason.
Nothing is a forecast or a recommendation. Offline, over the engine fixture (synthetic canned rows).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.portfolio.report import adapt, build, redator, revisor, values
from src.portfolio.report.redator import Finding

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
def built(view):
    return build.build(view, "fake")


def F(text, title="Título", section="sinais_de_risco", cites=("p36",), id="f1"):
    return Finding(id, section, title, text, list(cites))


def _line(view, level):
    return next(i for i, x in enumerate(view["movement"]["by_line"]) if x["level"] == level)


# --- the view ---------------------------------------------------------------


def test_the_view_separates_the_table_the_text_and_the_unevaluated(view):
    mv = view["movement"]
    assert mv["month"] == "2026-09-01" and mv["min_peers"] == 30
    assert mv["counts"] == {"funds": 6, "normal": 1, "atencao": 1, "forte": 1, "nao_avaliado": 3}
    assert [x["level"] for x in mv["table"]] == ["atencao", "forte"]
    assert [x["level"] for x in mv["strong"]] == ["forte"]
    assert [x["line_id"] for x in mv["not_evaluated"]] == ["L4", "L6", "L8"]
    assert all(x["reason"] for x in mv["not_evaluated"])
    assert mv["by_line"][_line(view, "forte")]["investigator_trigger"] is True
    assert not any(x["investigator_trigger"] for x in mv["by_line"] if x["level"] != "forte")
    assert view["sections"]["abnormal_movement"]["status"] == "partial"


def test_the_numbers_are_copied_from_the_engine_not_computed(engine, view):
    eng = {ln["line_no"]: ln for ln in engine["movement"]["lines"]}
    for x in view["movement"]["by_line"]:
        e = eng[int(x["line_id"][1:])]
        for k in ("own_value_pct", "class_mean_pct", "class_sd_pct", "z", "n_peers", "class_as_filed", "level", "reason"):
            assert x[k] == e[k], k
    redator.assert_masked(view)


def test_an_engine_document_before_1_3_has_no_movement_section_and_still_renders():
    prov = json.loads(PROVISIONAL.read_text(encoding="utf-8"))
    assert "movement" not in prov
    html, narrative = build.build(prov, "fake")
    assert "regra ainda não foi definida" in html and narrative.status == "complete"
    eng = json.loads(ENGINE.read_text(encoding="utf-8"))
    del eng["movement"]
    del eng["section_status"]["movement"]
    old = adapt.to_view(eng)
    assert "movement" not in old and old["sections"]["abnormal_movement"]["status"] == "unknown"


# --- the Redator: the text carries forte only --------------------------------


def test_the_template_writer_writes_forte_and_the_unevaluated_and_never_atencao(view, built):
    html, narrative = built
    texts = [f for f in narrative.kept if "movement." in " ".join(re.findall(r"\{\{[^}]*\}\}", f.text))]
    assert texts, "the movement findings were removed"
    for f in texts:
        for ph in revisor.placeholders(f.text):
            assert ph.startswith(revisor.MOVEMENT_TEXT_PATHS), ph
        assert not re.search(r"movement\.(table|by_line)", f.text)
    assert any("movement.strong[0]" in f.text for f in texts)
    assert any("movement.counts.nao_avaliado" in f.text for f in texts)
    drafted = redator.template_findings(view)["findings"]
    joined = " ".join(f["text"] for f in drafted)
    assert "movement.table" not in joined and "movement.by_line" not in joined


def test_the_system_prompt_keeps_atencao_out_of_the_text():
    p = redator.SYSTEM_PROMPT
    assert "movement.strong" in p and "NUNCA entra no texto" in p and "não avaliado" in p
    assert "previsão" in p and "recomendação" in p


# --- the Revisor -------------------------------------------------------------


def test_a_sentence_citing_the_table_or_by_line_is_removed(view):
    i = _line(view, "atencao")
    for path in (f"movement.by_line[{i}].fund_name", "movement.table[0].fund_name", f"movement.by_line[{i}].z"):
        kept, removals = revisor.check_finding(view, F(f"O fundo teve sinal {{{{{path}}}}}."))
        assert kept is None and any("só aparece em tabela" in r.reason for r in removals), path


def test_a_sentence_citing_strong_is_kept_and_so_is_the_not_evaluated_reason(view):
    ok = F("O fundo {{movement.strong[0].fund_name}} ficou a {{movement.strong[0].z}} desvios padrão da média da classe "
           "{{movement.strong[0].class_as_filed}}, com {{movement.strong[0].n_peers}} fundos em {{movement.month}}.")
    kept, removals = revisor.check_finding(view, ok)
    assert kept is not None and not removals
    ne = F("Movimento incomum não avaliado para {{movement.not_evaluated[0].fund_name}}: {{movement.not_evaluated[0].reason}}.")
    kept, removals = revisor.check_finding(view, ne)
    assert kept is not None and not removals


def test_a_movement_sentence_that_says_atencao_is_removed(view):
    f = F("O fundo {{movement.strong[0].fund_name}} está em atenção no movimento contra a classe.")
    kept, removals = revisor.check_finding(view, f)
    assert kept is None and any("só aparece em tabela" in r.reason for r in removals)


def test_a_digit_in_a_movement_sentence_outside_a_placeholder_is_removed(view):
    kept, removals = revisor.check_finding(view, F("O fundo {{movement.strong[0].fund_name}} passou de 3 desvios padrão."))
    assert kept is None and any("algarismo fora de marcador" in r.reason for r in removals)


def test_a_large_class_relative_return_is_not_treated_as_an_exposure(view):
    # own_value_pct above 50 would trip the exposure rule (an exposure above 50% of the portfolio needs a second path);
    # a class-relative return is a sample statistic, so the rule does not apply to movement paths.
    eng = json.loads(json.dumps(view))
    eng["movement"]["strong"][0]["own_value_pct"] = 120.0
    kept, removals = revisor.check_finding(eng, F("Retorno de {{movement.strong[0].own_value_pct}} no mês."))
    assert kept is not None and not removals
    assert revisor._extreme(eng, "movement.strong[0].own_value_pct", 120.0) is None
    # the rule still applies where it was written
    assert revisor._extreme(eng, "sector.buckets[0].weight_pct", 80.0) == ("exposure", 80.0)


# --- the page ----------------------------------------------------------------


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def test_the_page_shows_atencao_and_forte_in_the_table_and_the_unevaluated_with_reason(view, built):
    html, _ = built
    t = _text(html)
    i = t.index("Movimento incomum em")
    seg = t[i: i + 4500]
    assert "09/2026" in seg and "Classe ANBIMA" in seg and "Desvio padrão da classe" in seg
    # table rows: atenção and forte, with class, sample size, return, mean, sd and z
    assert "GERACAO L. PAR FUNDO DE INVESTIMENTO EM ACOES AÇÕES - ATIVO - LIVRE 1.773 11,00% 4,36% 3,08% 2,1549 atenção" in seg
    assert "RENDA FIXA LIVRE DURAÇÃO - CRÉDITO LIVRE 2.243 -2,90% 0,54% 0,96% -3,5911 forte" in seg
    # not evaluated, written as such, with the reason
    assert "XP BANCOS FIC FIF RENDA FIXA ( não avaliado ): fundo fora do Extrato da CVM: sem classe ANBIMA informada." in seg
    assert "não é fundo FI com cota diária no SILO (fidc)" in seg
    assert "previsão de retorno, veredito nem recomendação" in seg


def test_the_attention_fund_is_not_named_in_any_movement_finding(view, built):
    html, narrative = built
    name = view["movement"]["table"][0]["fund_name"]  # the atencao fund
    assert view["movement"]["table"][0]["level"] == "atencao"
    divs = re.findall(r'<div class="achado">(.*?)</div>', html, re.S)
    movement = [_text(d) for d in divs if "Movimento incomum" in _text(d)]
    assert len(movement) == 2  # the forte fund and the not-evaluated count
    assert not any(name in m for m in movement)
    assert not any("movement.by_line" in f.text or "movement.table" in f.text for f in narrative.kept)


def test_no_leftover_placeholders_in_the_page(built):
    html, _ = built
    assert "{{" not in html and "}}" not in html


def test_the_section_without_fund_lines_is_not_applicable():
    from src.portfolio.movement import compute_movement
    import datetime as dt
    from src.portfolio.client import FakeClient

    out = compute_movement([], FakeClient({}), dt.date(2026, 9, 1))
    assert out["status"] == "not_applicable" and out["lines"] == [] and out["counts"]["funds"] == 0
