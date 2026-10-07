"""The diagnosis sections module: section status, the view's sections and the report's gap lines, offline."""

from __future__ import annotations

import pytest

from src.portfolio import sections as S
from src.portfolio.common import REASON_TEXT
from src.portfolio.report import redator

ENGINE_KEYS = [s.key for s in S.SECTIONS]
CODE_A, CODE_B = "sem_vencimento", "sem_gestor"  # two codes no gap line covers


def _block(status="complete", codes=(), reason=None):
    return {"status": status, "reason": reason, "reason_codes": list(codes)}


def _engine(statuses: dict[str, dict] | None = None, drop: tuple[str, ...] = ()) -> dict:
    """A minimal engine document: every section complete unless ``statuses`` says otherwise."""
    ss = {k: _block() for k in ENGINE_KEYS if k not in drop}
    ss.update(statuses or {})
    eng = {
        "section_status": ss,
        "risk_signals": {"abnormal_movement": "texto do motor antigo"},
        "restatements": {"assessment": "materialidade não avaliada"},
        "look_through": {"shared_exposure": {"note": "grupo econômico não avaliado"}},
    }
    if "movement" not in drop:
        eng["movement"] = {}
    return eng


def _line(n, asset_type="fundo", ident="identified"):
    return {"line_id": f"L{n}", "asset_type": asset_type, "identification": {"status": ident}}


def _view(eng, lines=(), **extra):
    view = {"sections": S.sections_view(eng, list(lines)), "fees": {}, "risk_screens": {}, "lines": list(lines)}
    view.update(extra)
    return view


# --- the declarations --------------------------------------------------------------------------------------------


def test_declarations_are_consistent():
    assert len(set(ENGINE_KEYS)) == len(ENGINE_KEYS)
    view_keys = [s.view_key for s in S.SECTIONS if s.view_key]
    assert len(set(view_keys)) == len(view_keys)
    assert not set(view_keys) & set(S.NOT_ASSESSED_TITLES)
    for s in S.SECTIONS:
        if s.gap_from_status or s.line_gap_codes or s.view_key:
            assert s.title, s.key
    assert all(c in REASON_TEXT for c in S.COVERED_CODES)


def test_redator_slots_are_the_declared_ones():
    assert redator.SECTIONS == tuple(k for k, _ in S.REPORT_SLOTS)
    assert redator.SECTION_TITLES == dict(S.REPORT_SLOTS)


@pytest.mark.parametrize("codes, expected", [
    ([], S.GENERIC_GAP),
    (["nao_existe"], S.GENERIC_GAP),
    ([CODE_A], REASON_TEXT[CODE_A]),
    ([CODE_A, CODE_A, CODE_B], f"{REASON_TEXT[CODE_A]}; {REASON_TEXT[CODE_B]}"),
])
def test_codes_text_is_the_fixed_text_of_each_code(codes, expected):
    assert S.codes_text(codes) == expected


# --- the engine side ---------------------------------------------------------------------------------------------


def test_status_of_follows_the_declared_order_and_skips_absent_sections():
    doc = {"liquidity": _block("partial", ["x"]), "statement": {}, "fees": _block(), "identification": _block("unknown")}
    ss = S.status_of(doc)
    assert list(ss) == ["identification", "fees", "liquidity"]
    assert ss["liquidity"] == {"status": "partial", "reason": None, "reason_codes": ["x"]}


@pytest.mark.parametrize("present, key, expected_after", [
    (["identification", "liquidity", "assumptions"], "risks", "liquidity"),
    (["identification", "liquidity", "risks", "assumptions"], "returns", "risks"),
    (["identification", "liquidity", "assumptions"], "returns", "liquidity"),  # risks absent: after the one before
    (["identification", "equivalents", "assumptions"], "investigation", "equivalents"),
])
def test_attach_places_a_late_block_after_the_section_declared_before_it(present, key, expected_after):
    doc = {k: _block() for k in present}
    doc["section_status"] = {}
    block = _block("unknown", ["linhas_sem_retorno"], reason="texto livre")
    out = S.attach(doc, key, block)
    keys = list(out)
    assert keys.index(key) == keys.index(expected_after) + 1
    assert out[key] is block
    assert out["section_status"][key] == {"status": "unknown", "reason": "texto livre",
                                          "reason_codes": ["linhas_sem_retorno"]}


# --- the view's sections -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("engine_key, view_key", [
    ("look_through", "lookthrough"), ("risk_signals", "risk_screens"), ("movement", "abnormal_movement"),
    ("fees", "fees"), ("equivalents", "equivalents"),
])
def test_sections_view_renames_and_writes_fixed_texts(engine_key, view_key):
    eng = _engine({engine_key: _block("partial", [CODE_A], reason="erro: api.x 500")})
    sec = S.sections_view(eng, [])[view_key]
    assert sec == {"status": "partial", "reason_codes": [CODE_A], "reason": REASON_TEXT[CODE_A]}


def test_sections_view_lists_later_sections_only_when_present_and_never_the_investigation():
    out = S.sections_view(_engine(drop=("risks", "returns", "tax", "equivalents", "investigation")), [])
    assert list(out) == ["identification", "fees", "lookthrough", "indexer", "sector", "restatements", "risk_screens",
                         "concentration", "allocation", "liquidity", "abnormal_movement", "material_restatement",
                         "economic_group", "benchmarks"]
    full = S.sections_view(_engine(), [])
    assert {"risks", "returns", "tax", "equivalents"} <= set(full) and "investigation" not in full
    assert out["identification"] == {"status": "complete", "reason_codes": []}


def test_sections_view_without_movement_block_is_unknown_with_the_screens_text():
    out = S.sections_view(_engine(drop=("movement",)), [])
    assert out["abnormal_movement"] == {"status": "unknown", "reason": "texto do motor antigo"}


@pytest.mark.parametrize("lines, ident_status, ntnb", [
    ([_line(1)], "complete", None),
    ([_line(1), _line(2, ident="unknown")], "partial", None),
    ([_line(1, "titulo_publico"), _line(2, "titulo_publico")], "complete", ["L1", "L2"]),
])
def test_sections_view_marks_unidentified_lines_and_tesouro(lines, ident_status, ntnb):
    out = S.sections_view(_engine(), lines)
    assert out["identification"]["status"] == ident_status
    if ident_status == "partial":
        assert out["identification"]["reason"] == REASON_TEXT["linhas_nao_identificadas"]
    assert (out.get("ntnb_price") or {}).get("affects") == ntnb


# --- the gap lines -----------------------------------------------------------------------------------------------


def _titles(gaps):
    return [g["title"] for g in gaps]


ALWAYS = ["Materialidade das reapresentações", "Grupo econômico", "Comparação com carteiras de referência"]


@pytest.mark.parametrize("statuses, expected", [
    ({}, ALWAYS),
    ({"fees": _block("partial", [CODE_A])}, ["Taxas", *ALWAYS]),
    ({"fees": _block("partial", ["sem_taxa_divulgada"])}, ALWAYS),  # covered: the fee lines say it, with their lines
    ({"returns": _block("partial", ["linhas_sem_retorno", CODE_B])}, ["Retorno por posição", *ALWAYS]),
    ({"equivalents": _block("unknown", [])}, ["Equivalente de mercado", *ALWAYS]),  # no code: one generic line
    ({"identification": _block("unknown", [CODE_A])}, ALWAYS),  # not a status-gap section
    ({"movement": _block("partial", [CODE_A]), "look_through": _block("partial", [CODE_B])},
     ["Look-through (carteira dos fundos)", "Movimento incomum", *ALWAYS]),  # declared order, not argument order
])
def test_section_status_gap_lines(statuses, expected):
    eng = _engine(statuses)
    assert _titles(S.report_gaps(eng, _view(eng))) == expected


def test_failed_screens_replace_the_screens_status_line():
    eng = _engine({"risk_signals": _block("partial", [CODE_A])})
    gaps = S.report_gaps(eng, _view(eng, risk_screens={"not_run": [{"screen": "screen_x"}]}))
    assert _titles(gaps) == ["Telas de risco", *ALWAYS]
    assert gaps[0]["text"] == f"{S.SCREEN_FAILED}: screen_x"


@pytest.mark.parametrize("key, lines, expected", [
    ("returns", [{"line_no": 1, "status": "nao_avaliado", "reason_code": CODE_A},
                 {"line_no": 2, "status": "avaliado", "windows": {"12m": {"status": "x", "reason_code": CODE_A}}}],
     ("Retorno por posição", REASON_TEXT[CODE_A], ["L1", "L2"])),
    ("tax", [{"line_no": 3, "tax": {"status": "sem_regra", "reason_code": CODE_B}},
             {"line_no": 4, "tax": {"status": "estimado", "reason_code": CODE_B}}],
     ("Taxa e imposto por posição", REASON_TEXT[CODE_B], ["L3"])),
    ("equivalents", [{"line_no": 5, "status": "encontrado", "windows": [{"etf_reason_code": CODE_A}]}],
     ("Equivalente de mercado", REASON_TEXT[CODE_A], ["L5"])),
])
def test_line_codes_are_grouped_into_one_line_per_code(key, lines, expected):
    eng = _engine()
    eng[key] = {"lines": lines}
    first = S.report_gaps(eng, _view(eng))[0]
    assert (first["title"], first["text"], first["line_ids"]) == (expected[0], expected[1].rstrip(". "), expected[2])


def test_chart_gaps_follow_the_status_gaps():
    eng = _engine()
    view = _view(eng, [_line(1)], concentration={"maturity_ladder": {"status": "unknown"}, "issuer": {"status": "complete"}},
                 risks={"rows": [{"status": "nao_avaliado", "risk": "Crédito", "reason": "sem dado", "reason_code": "z"}]})
    assert _titles(S.report_gaps(eng, view))[len(ALWAYS):] == [
        "Principais riscos: Crédito", "Gráfico de vencimentos", "Diagrama do look-through"]


def test_dated_keys_are_the_declared_ones_in_order():
    keys = S.dated_keys()
    assert keys == [k for k in ENGINE_KEYS if k in keys]
    assert "investigation" not in keys and "identification" in keys
