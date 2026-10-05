"""Engine and blocks, offline: the FakeClient answers from canned rows."""

from __future__ import annotations

import copy
import datetime as dt
import json
import logging
from decimal import Decimal
from pathlib import Path

import pytest

from src.portfolio.client import FakeClient, load_fake_rows
from src.portfolio.diagnose import FAKE_CLOCK, main
from src.portfolio.engine import default_params, dumps, run_engine
from src.portfolio.fees import ESTIMATE_LABEL, IMPLAUSIBLE_LABEL, NOT_ADDED, NOT_FOUND, ZERO_LABEL
from src.portfolio.identify import identify, parse_tesouro
from src.portfolio.indexer import classify, load_rules
from src.portfolio.lookthrough import Exposure, compute_lookthrough
from src.portfolio.restatements import NOT_ASSESSED
from src.portfolio.statement import parse_rows, read_statement

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "docs" / "reference" / "portfolio" / "statement-template.xlsx"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "portfolio"
FAKE_ROWS = FIXTURE_DIR / "fake_silo_rows.json"
FIXTURE = FIXTURE_DIR / "demo_engine_output.json"


def fake(canned=None):
    return FakeClient(canned if canned is not None else load_fake_rows(FAKE_ROWS), clock=lambda: FAKE_CLOCK)


def run(canned=None):
    stmt = read_statement(TEMPLATE)
    return run_engine(stmt, fake(canned), default_params(stmt.position_date), clock=lambda: FAKE_CLOCK)


@pytest.fixture(scope="module")
def doc():
    return run()


# ---------------------------------------------------------------------------
# The fixture the report agent builds against.
# ---------------------------------------------------------------------------


def test_fixture_regenerates_byte_for_byte(tmp_path):
    out = tmp_path / "out.json"
    assert main([str(TEMPLATE), "--client", "fake", "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == FIXTURE.read_text(encoding="utf-8"), (
        "the committed fixture is stale: regenerate with "
        "`python -m src.portfolio.diagnose docs/reference/portfolio/statement-template.xlsx --client fake "
        "--out tests/fixtures/portfolio/demo_engine_output.json` and say so in the PR (schema_version rules)"
    )


def test_top_level_schema_is_stable(doc):
    assert list(doc) == [
        "schema_version", "generated_at_utc", "engine", "statement", "identification", "fees", "look_through",
        "indexer", "sector", "restatements", "risk_signals", "movement", "concentration", "allocation", "liquidity", "risks",
        "assumptions", "section_status", "provenance",
    ]
    assert doc["schema_version"] == "1.9"
    for sec in ("identification", "fees", "look_through", "indexer", "sector", "restatements", "risk_signals", "movement",
                "concentration", "allocation", "liquidity", "risks"):
        assert {"status", "reason", "errors", "reason_codes"} <= set(doc[sec])
        assert doc["section_status"][sec]["reason_codes"] == doc[sec]["reason_codes"]


def test_provenance_lists_every_call_with_count_or_error(doc):
    prov = doc["provenance"]
    assert [p["call_id"] for p in prov] == list(range(1, len(prov) + 1))
    assert all((p["row_count"] is None) != (p["error"] is None) for p in prov)
    assert all(p["requested_at_utc"] == "2026-10-03T15:00:00Z" for p in prov)


def test_every_number_source_points_at_a_recorded_call(doc):
    call_ids = {p["call_id"] for p in doc["provenance"]}

    def walk(x):
        if isinstance(x, dict):
            if "tool" in x and "call_id" in x and "data_date" in x:
                if x["tool"] != "statement":
                    assert x["call_id"] in call_ids
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(doc)


# ---------------------------------------------------------------------------
# Demo findings, block by block.
# ---------------------------------------------------------------------------


def test_identification_demo(doc):
    lines = {ln["line_no"]: ln for ln in doc["identification"]["lines"]}
    assert all(lines[n]["status"] == "identified" and lines[n]["reason_code"] is None for n in range(1, 9))
    # the bank-issued credit lines: not identified, grouped by a fixed reason code with their value
    assert {n: lines[n]["reason_code"] for n in range(9, 11)} == {9: "bancario_sem_fonte", 10: "bancario_sem_fonte"}
    groups = {g["reason_code"]: g for g in doc["identification"]["unknown_groups"]}
    assert groups["bancario_sem_fonte"]["line_nos"] == [9, 10] and groups["bancario_sem_fonte"]["value_brl"] == 390000.0
    # engine 1.9: the CRA and the debênture are identified by their registry code
    assert all(lines[n]["status"] == "identified" and lines[n]["identity"]["kind"] == "credito" for n in (11, 12))
    assert lines[11]["credit_match"]["match_kind"] == "securit_cetip" and lines[12]["credit_match"]["match_kind"] == "cda_ticker"
    assert "credito_sem_fonte" not in groups
    assert lines[1]["identity"]["tesouro_title"] == "NTN-B" and lines[1]["identity"]["tesouro_maturity"] == "2035-05-15"
    assert lines[1]["valuation"]["basis"] == "statement"
    assert lines[2]["identity"]["issuer_cnpj"] == "33000167000101"
    assert lines[2]["ticker_match"]["reference_quote"]["trade_date"] == "2026-10-01"  # reference only
    assert lines[4]["identity"]["cnpj"] == "50088190000119"  # the quota separated FIC from master
    assert [c["cnpj"] for c in lines[4]["fund_match"]["candidates"]] == ["50088190000119", "35377390000106"]
    assert [f["kind"] for f in lines[7]["findings"]] == ["renamed"]
    assert lines[7]["findings"][0]["matched_period"] == "2024-01-01"


def test_ambiguous_and_unknown_lines():
    stmt = parse_rows(
        [["total_extrato", 30.0], ["linha_extrato", "tipo", "codigo", "quantidade", "preco_unitario", "valor", "data_posicao"],
         ["FUNDO AMBIGUO", "fundo", None, 1, 10, 10.0, dt.date(2026, 9, 30)],
         ["CDB BANCO X", "CDB", None, 1, 10, 10.0, dt.date(2026, 9, 30)],
         ["FUNDO SEM RESPOSTA", "fundo", None, 1, 10, 10.0, dt.date(2026, 9, 30)]]
    )
    cand = lambda ln, rank, amb: dict(line_no=ln, candidate_cnpj=f"0000000000{rank}000"[:14], candidate_name=f"F{rank}", matched_name=f"F{rank}", matched_period="2026-05-01",
                                      entity_type="fi", match_kind="name_history", similarity=0.5, rank=rank, quota_on_date=1.0, quota_rel_diff=0.001, ambiguous=amb, reason="duas cotas iguais")
    c = FakeClient({"portfolio_resolve": [{"match": {}, "rows": [cand(1, 1, True), cand(1, 2, True)]}]})
    section, lines = identify(stmt, c)
    by = {ln["line_no"]: ln for ln in section["lines"]}
    assert by[1]["status"] == "ambiguous" and len(by[1]["fund_match"]["candidates"]) == 2
    assert by[2]["status"] == "unknown" and "CDB" in by[2]["reason"]
    assert by[3]["status"] == "unknown" and "nome (histórico)" in by[3]["reason"]
    assert section["status"] == "partial"


def test_parse_tesouro_titles():
    assert parse_tesouro("NTN-B 2035-05-15") == ("NTN-B", "2035-05-15")
    assert parse_tesouro("Tesouro IPCA+ 15/08/2030") == ("NTN-B PRINCIPAL", "2030-08-15")
    assert parse_tesouro("LFT 2029") == ("LFT", "2029")
    assert parse_tesouro("TITULO QUALQUER 2035") is None


def test_fees_headline_is_the_disclosed_fee_and_the_estimate_stays_apart(doc):
    by = {ln["line_no"]: ln for ln in doc["fees"]["lines"]}
    f3, f4, f5, f6, f7, f8 = (by[n] for n in (3, 4, 5, 6, 7, 8))
    # an Extrato fee: headline, R$/year = position value x rate, the origin named, the class scope said
    h = f3["headline"]
    assert (h["kind"], h["rate_pct_year"], h["origin"], h["as_of"], h["age_months"], h["stale"]) == ("fixa", 2.0, "extrato", "2026-07-31", 1, False)
    assert h["per_year_brl"] == round(264615.00 * 0.02, 2) and h["scope_label"] == "taxa da classe"
    d3 = f3["disclosed"]
    assert d3["origin"] == "extrato" and d3["origin_label"] == "Extrato CVM" and d3["source"] == "cvm_fi_extrato"
    assert "DT_COMPTC" in d3["as_of_meaning"] and "cad_fi" not in d3["as_of_meaning"]  # not the cad_fi provenance sentence
    assert d3["class_note"].startswith("class-level row")
    # the estimate is its own field, labelled, never the headline and never averaged with it
    e = f3["estimate"]
    assert e["label"] == ESTIMATE_LABEL == "estimativa, não divulgada" and e["adm_pct_year"] == 1.98 and e["method"]
    assert h["rate_pct_year"] != e["adm_pct_year"] and "média" not in str(f3)
    # performance fee and the other terms: as filed, nothing parsed, never R$ from the performance fee
    assert d3["perf_as_filed"] == "20% do que exceder 100% do Ibovespa"
    t3 = d3["terms_as_filed"]
    assert t3["performance"] == {"exists": "S", "taxa_perfm_as_filed": 20.0, "param_as_filed": "Ibovespa", "calc_as_filed": "semestral",
                                 "info_as_filed": "20% do que exceder 100% do Ibovespa"}
    assert t3["entry"]["exists"] == "N" and t3["exit"]["exists"] == "N" and t3["custody_max_as_filed"] == 0.05
    assert not any(k.startswith("perf_per_year") for k in d3)
    # the declared total expense ratio: its own field, with its period, never added to the fee
    x = f3["expense_ratio"]
    assert x["declared_pct"] == 2.31 and x["period"] == {"from": "2025-07-01", "to": "2026-06-30"} and x["source"] == "cvm_fi_lamina"
    assert h["rate_pct_year"] != x["declared_pct"] and f3["estimate"]["adm_pct_year"] != x["declared_pct"]
    assert f4["expense_ratio"]["declared_pct"] is None and "lâmina" in f4["expense_ratio"]["note"]
    # classes that differ (lâmina): the range as filed, no single value
    assert f4["fee_status"] == "faixa divulgada" and f4["headline"]["kind"] == "faixa" and f4["disclosed"]["origin"] == "lamina"
    assert (f4["headline"]["rate_min_pct_year"], f4["headline"]["rate_max_pct_year"]) == (0.15, 0.30)
    assert f4["disclosed"]["adm_rate_pct_year"] is None
    # a filed 0 is shown as such, never a zero cost: no rate, no R$, not summed, plus the attention finding
    assert f5["fee_status"] == ZERO_LABEL == "0 informado; a conferir"
    assert f5["headline"]["kind"] == "zero_informado" and f5["headline"]["rate_pct_year"] is None
    assert f5["headline"]["per_year_brl"] is None and f5["headline"]["counted_as_cost"] is False
    assert f5["disclosed"]["filed_zero"] is True and f5["disclosed"]["adm_rate_pct_year"] == 0.0
    assert f5["needs_manual_check"] is True and f5["headline"]["filed_pct_year"] == 0.0  # the filed value is shown
    assert f3["needs_manual_check"] is False and f6["needs_manual_check"] is False
    assert "pode estar correto" in f5["reason"] and "errado" not in f5["reason"].lower() and "erro" not in f5["reason"].lower()
    z = next(x for x in f5["findings"] if x["kind"] == "divulgado_zero_balancete_registra_despesa")
    assert z["level"] == "atenção" and z["text"] == "Divulgado 0, balancete registra despesa."
    # nothing disclosed anywhere: taxa divulgada não encontrada, the estimate is NOT substituted
    assert f6["fee_status"] == NOT_FOUND and f6["headline"] is None and f6["estimate"] is None  # FIDC: no row
    assert f8["fee_status"] == NOT_FOUND
    # the lâmina's staleness limit is 24 months; the finding names the origin
    assert f7["disclosed"]["origin"] == "lamina" and f7["disclosed"]["stale"] is True and f7["disclosed"]["stale_after_months"] == 24
    assert f7["disclosed"]["stale_label"] == "defasada" and f7["disclosed"]["age_months"] == 29
    assert "lamina_defasada" in {x["kind"] for x in f7["findings"]}
    # estimate vs a fixed fee: attention, worded as divergence, not as one of them being wrong
    diff = next(x for x in f7["findings"] if x["kind"] == "estimativa_difere_da_divulgada")
    assert diff["level"] == "atenção" and diff["difference_pp"] == pytest.approx(0.47)
    assert diff["text"].startswith("Estimativa e divulgada divergem") and "qual das duas está errada" in diff["text"]
    assert not any(x["kind"] == "estimativa_difere_da_divulgada" for x in f3["findings"])  # 0.02 p.p. is within tolerance
    # totals: only usable disclosed fees are summed; the zero is not
    t = doc["fees"]["totals"]
    assert t["adm_disclosed_fixed_per_year_brl"] == round(f3["headline"]["per_year_brl"] + f7["headline"]["per_year_brl"], 2)
    assert t["adm_disclosed_range_low_per_year_brl"] == f4["headline"]["per_year_min_brl"]
    assert t["fund_value_with_filed_zero_brl"] == f5["position_value_brl"]
    assert t["fund_value_without_disclosed_fee_brl"] == pytest.approx(f5["position_value_brl"] + f6["position_value_brl"] + f8["position_value_brl"])
    assert t["estimate_label"] == ESTIMATE_LABEL and "fee_units" in {a["id"] for a in doc["assumptions"]}
    assert doc["fees"]["source_order"] == ["extrato", "lamina", "cad_fi"]
    assert doc["fees"]["stale_after_months_by_origin"] == {"extrato": 36, "lamina": 24, "cad_fi": None}


def test_underlying_funds_keep_their_own_fee_and_are_not_added(doc):
    und = doc["fees"]["underlying"]
    assert und and all(u["label"] == NOT_ADDED and u["added_to_totals"] is False for u in und)
    master = next(u for u in und if u["fund_cnpj"] == "35377390000106" and u["line_no"] == 4)
    # a filed 0 (lâmina) is not a cost; the balancete shows an expense, hence the finding
    assert master["fee_status"] == ZERO_LABEL and master["headline"]["rate_pct_year"] is None
    f = next(x for x in master["findings"] if x["kind"] == "divulgado_zero_balancete_registra_despesa")
    assert f["level"] == "atenção" and f["text"] == "Divulgado 0, balancete registra despesa."
    # the feeder's own fee is untouched by its master's
    feeder = next(l for l in doc["fees"]["lines"] if l["line_no"] == 4)
    assert feeder["headline"]["kind"] == "faixa"
    assert doc["fees"]["totals"]["fund_value_brl"] == pytest.approx(sum(l["position_value_brl"] for l in doc["fees"]["lines"]))


def test_an_implausible_filed_value_is_discarded_with_the_raw_value_apart(doc):
    u = next(u for u in doc["fees"]["underlying"] if u["fund_cnpj"] == "37525998000158" and u["line_no"] == 4)
    assert u["fee_status"] == IMPLAUSIBLE_LABEL == "valor informado acima de 5% a.a.; a conferir"
    assert u["headline"] is None and u["disclosed"]["adm_rate_pct_year"] is None and u["needs_manual_check"] is True
    assert "pode estar correto" in u["reason"] and "erro" not in u["reason"].lower() and "descart" not in u["reason"].lower()
    assert "descart" not in json.dumps(u, ensure_ascii=False).lower() or "rejected" in u["disclosed"]
    assert u["disclosed"]["implausible_filed"] is True and u["disclosed"]["adm_filed_raw"] == 14638.0
    assert u["disclosed"]["rejected"]["raw_value"] == 14638.0 and u["disclosed"]["scope_label"] == "taxa do fundo"
    assert "valor_implausivel_descartado" in {x["kind"] for x in u["findings"]}
    # the raw value is a plain field, not a _pct one: nothing prints 14638 as a rate
    assert not any("14638" in k for k in u["disclosed"]) and "adm_pct" not in "".join(u["disclosed"])


def test_the_extrato_is_defasada_after_36_months_not_24(doc):
    u = next(u for u in doc["fees"]["underlying"] if u["fund_cnpj"] == "54891935000134" and u["line_no"] == 4)
    assert u["disclosed"]["origin"] == "extrato" and u["disclosed"]["age_months"] == 30
    assert u["disclosed"]["stale"] is False and u["disclosed"]["stale_after_months"] == 36
    assert u["estimate"]["available"] is False and u["estimate"]["fiscal_reset_suspect"] is True


def _fees_run(row_edits):
    canned = load_fake_rows(FAKE_ROWS)
    for entry in canned["portfolio_fees"]:
        for row in entry["rows"]:
            row.update(row_edits.get(row["cnpj"], {}))
    return run(canned)


def test_provenance_sentence_follows_disclosed_origin_not_source():
    d = _fees_run({"08935128000159": {"disclosed_origin": "cad_fi", "disclosed_source": "cvm_fund_registry (cad_fi)"}})
    f3 = next(l for l in d["fees"]["lines"] if l["line_no"] == 3)
    assert f3["disclosed"]["origin"] == "cad_fi" and "cad_fi" in f3["disclosed"]["as_of_meaning"]
    assert f3["disclosed"]["stale_after_months"] is None and f3["disclosed"]["stale"] is False
    # an old v51 row (no disclosed_origin) still gets the right origin from disclosed_source
    d = _fees_run({"08935128000159": {"disclosed_origin": None}})
    assert next(l for l in d["fees"]["lines"] if l["line_no"] == 3)["disclosed"]["origin"] == "extrato"


def test_extrato_age_falls_back_to_days_and_the_threshold_is_36_months():
    d = _fees_run({"08935128000159": {"disclosed_age_months": None, "disclosed_age_days": 1200}})
    assert next(l for l in d["fees"]["lines"] if l["line_no"] == 3)["disclosed"]["stale"] is True  # 39 months
    d = _fees_run({"08935128000159": {"disclosed_age_months": 37}})
    assert next(l for l in d["fees"]["lines"] if l["line_no"] == 3)["disclosed"]["stale_label"] == "defasada"


def test_lookthrough_three_levels_and_overlap(doc):
    lt = {ln["line_no"]: ln for ln in doc["look_through"]["lines"]}
    assert lt[4]["status"] == "complete" and lt[4]["max_depth_seen"] >= 3  # root's own holdings are depth 0
    kinds = {g["kind"] for g in doc["look_through"]["shared_exposure"]["groups"]}
    assert {"mesmo_ativo", "mesmo_emissor_raiz_cnpj", "mesmo_codigo_emissor_b3", "mesmo_fundo_investido"} <= kinds
    assert doc["look_through"]["shared_exposure"]["economic_group_assessed"] is False
    groups = doc["look_through"]["shared_exposure"]["groups"]
    petr = next(g for g in groups if g["kind"] == "mesmo_ativo" and g["label"].startswith("PETR4"))
    assert petr["line_nos"] == [2, 3]
    assert next(l for l in petr["lines"] if l["line_no"] == 2)["direct"] is True
    master = next(g for g in groups if g["kind"] == "mesmo_fundo_investido" and g["fund_cnpj"] == "35377390000106")
    assert master["line_nos"] == [4, 5]
    root = next(g for g in groups if g["kind"] == "mesmo_emissor_raiz_cnpj")
    assert root["issuer_cnpj_root"] == "33000167" and root["line_nos"] == [2, 4, 5]


def test_lookthrough_exposure_is_value_times_weight(doc):
    ln = next(l for l in doc["look_through"]["lines"] if l["line_no"] == 3)
    petr = next(e for e in ln["exposures"] if e["asset_key"] == "PETR4")
    assert petr["exposure_brl"] == pytest.approx(264615.00 * petr["weight_in_line"], abs=0.01)
    assert ln["unexplained_weight"] == pytest.approx(1 - ln["explained_weight"])


def test_cycle_rows_are_not_followed():
    canned = load_fake_rows(FAKE_ROWS)
    rows = copy.deepcopy(canned["portfolio_lookthrough"][0]["rows"])
    cyc = dict(rows[0], is_cycle=True, asset_kind="fund_quota_cycle")
    canned["portfolio_lookthrough"][0]["rows"] = rows + [cyc]
    d = run(canned)
    ln = next(l for l in d["look_through"]["lines"] if l["line_no"] == 3)
    assert ln["n_cycle_rows_skipped"] == 1


def test_indexer_rules_and_unclassified_always_shown(doc):
    idx = doc["indexer"]
    classes = {c["indexer_class"]: c for c in idx["classes"]}
    assert "sem classificação" in classes and idx["classes"][-1]["indexer_class"] == "sem classificação"
    assert abs(idx["sum_check_brl"]) < 0.02
    assert sum(c["portfolio_pct"] for c in idx["classes"]) == pytest.approx(100.0, abs=0.01)
    assert {"pós-fixado (Selic)", "renda variável", "inflação (IPCA)", "pós-fixado (CDI)"} <= set(classes)
    assert idx["never_inferred_from_name"] is True and len(idx["rules_sha256"]) == 64
    reasons = " ".join(u["reason"] for u in idx["unclassified_breakdown"])
    assert "Compromissada" in reasons and "Indexador nulo" in reasons


def _exp(**kw):
    base = dict(line_no=1, via="f", depth=1, block=None, asset_kind=None, asset_key=None, asset_name=None, isin=None, issuer_cnpj=None,
                issuer_code=None, tp_aplic=None, tp_ativo=None, tp_titpub=None, indexer_code=None, maturity=None, weight=Decimal(1),
                value_brl=Decimal(1), period=None)
    base.update(kw)
    return Exposure(**base)


@pytest.mark.parametrize(
    "kw,expected",
    [
        (dict(block="1", tp_aplic="Títulos Públicos", tp_titpub="LETRAS FINANCEIRAS DO TESOURO"), "pós-fixado (Selic)"),
        (dict(block="1", tp_aplic="Títulos Públicos", tp_titpub="LETRAS DO TESOURO NACIONAL"), "pré-fixado"),
        (dict(block="1", tp_aplic="Títulos Públicos", tp_titpub="NOTAS DO TESOURO NACIONAL - SERIE F"), "pré-fixado"),
        (dict(block="1", tp_aplic="Títulos Públicos", tp_titpub="NOTAS DO TESOURO NACIONAL SERIE B"), "inflação (IPCA)"),
        (dict(block="1", tp_aplic="Títulos Públicos", tp_titpub="NOTAS DO TESOURO NACIONAL SERIE C"), "inflação (IGP-M)"),
        (dict(block="1", tp_aplic="Títulos Públicos", tp_titpub="NOTAS DO TESOURO NACIONAL SERIE I"), "câmbio"),
        (dict(block="1", tp_aplic="Operações Compromissadas", tp_titpub="LETRAS FINANCEIRAS DO TESOURO"), "sem classificação"),
        (dict(block="6", indexer_code="DI1"), "pós-fixado (CDI)"),
        (dict(block="6", indexer_code="SEL"), "pós-fixado (Selic)"),
        (dict(block="6", indexer_code="IAP"), "inflação (IPCA)"),
        (dict(block="6", indexer_code="PRE"), "pré-fixado"),
        (dict(block="6", indexer_code="DOL"), "câmbio"),
        (dict(block="6", indexer_code="TR"), "pós-fixado (TR)"),
        (dict(block="6", indexer_code="OUT"), "sem classificação"),
        (dict(block="6", indexer_code=None), "sem classificação"),
        (dict(block="4", tp_aplic="Ações"), "renda variável"),
        (dict(block="4", tp_aplic="Brazilian Depository Receipt - BDR"), "renda variável"),
        (dict(block="4", tp_aplic="Debêntures", asset_name="DEBENTURE IPCA+ 6%"), "sem classificação"),  # never from a name
        (dict(block="1", tp_aplic="Títulos Públicos", tp_titpub="NOME NOVO IPCA", asset_name="IPCA"), "sem classificação"),
        (dict(block="4", tp_aplic="Opções - Posições lançadas"), "sem classificação"),
        (dict(block="2", opaque_fund=True), "sem classificação"),
    ],
)
def test_indexer_classification_rules(kw, expected):
    cls, rule, why = classify(_exp(**kw), load_rules())
    assert cls == expected


def test_indexer_rules_csv_has_no_duplicates_and_known_columns():
    rules = load_rules()
    assert {k[0] for k in rules} == {"block1", "block4", "block6", "direct_tesouro", "direct", "statement_taxa"}
    first = (ROOT / "src/portfolio/rules/indexer_rules.csv").read_text(encoding="utf-8").splitlines()[0]
    assert first == "source,field,value,indexer_class,note"


def test_sector_from_published_fields_only(doc):
    sec = doc["sector"]
    names = {s["sector"] for s in sec["sectors"]}
    assert "Petróleo e Gás" in names and "Agronegócio" in names and sec["sectors"][-1]["sector"] == "sem classificação"
    assert abs(sec["sum_check_brl"]) < 0.02
    fii = next(i for i in sec["items"] if i["line_no"] == 8)
    assert fii["sector"] == "sem classificação" and "segmento_atuacao" in fii["reason_unclassified"]
    assert any(i["taxonomy"] == "CVM (cvm_fidc_setor)" for i in sec["items"])  # FIDC from tab II
    assert not any(i["sector"] in ("Serviços - transporte",) for i in sec["items"])  # members are not summed with parents


def test_restatements_reported_not_assessed(doc):
    r = doc["restatements"]
    mn = next(l for l in r["lines"] if l["cnpj"] == "32113885000121")
    assert mn["n_restatements"] == 3
    dec2025 = next(x for x in mn["restatements"] if x["fnet_id"] == 1086024)
    assert dec2025["assessment"] == NOT_ASSESSED and dec2025["leaves_complete"] is True
    leaf = next(x for x in dec2025["leaves"] if x["leaf"] == "VL_CRED_EXISTE_INAD")
    assert (leaf["old_num"], leaf["new_num"]) == (0.0, 187284652.71)
    assert (leaf["fnet_id"], leaf["previous_fnet_id"]) == (1086024, 1085168)
    assert leaf["delivered_at"] == "2026-01-16 11:16:00" and leaf["previous_delivered_at"] == "2026-01-15 19:38:00"
    assert leaf["assessment"] == NOT_ASSESSED
    calls = [p for p in doc["provenance"] if p["tool"] == "fund_restatement_diff"]
    assert len(calls) == 3 and all("p_fnet_id" in c["args"] for c in calls)


def test_risk_signals_match_by_cnpj_and_pin_dormant(doc):
    s = doc["risk_signals"]
    mn = next(l for l in s["lines"] if l["cnpj"] == "32113885000121")
    assert {x["screen"] for x in mn["signals"]} == {"screen_delinquency_drivers", "screen_restatements"}
    assert all(l["n_signals"] == 0 for l in s["lines"] if l["cnpj"] != "32113885000121")
    dormant = [p for p in doc["provenance"] if p["tool"] == "screen_dormant_funds"]
    assert [p["args"] for p in dormant] == [
        {"p_lookback_months": 3, "p_dormancy": "empty_shell"},
        {"p_lookback_months": 3, "p_min_nav": 1000000000},
    ]
    assert isinstance(dormant[1]["args"]["p_min_nav"], int)
    assert "R$ 1 bilhão" in s["dormant_coverage_note"]
    assert "seção movement" in s["abnormal_movement"]
    assert {x["status"] for x in s["screens"] if x["screen"] in ("screen_overdue_securit", "screen_dormant_trend")} == {"not_applicable"}


# ---------------------------------------------------------------------------
# A refusal makes its SECTION unknown with the verbatim error, never the report.
# ---------------------------------------------------------------------------

REFUSAL = '{"code":"22023","message":"portfolio_fees: more than one page"}'


def test_refused_fees_makes_fees_unknown_only():
    canned = load_fake_rows(FAKE_ROWS)
    canned["portfolio_fees"] = [{"match": {}, "error": REFUSAL}]
    d = run(canned)
    assert d["fees"]["status"] == "unknown" and d["fees"]["errors"][0]["error"] == REFUSAL
    assert all(l["fee_status"] == NOT_FOUND for l in d["fees"]["lines"])
    for sec in ("identification", "look_through", "indexer", "sector", "restatements", "risk_signals"):
        assert d[sec]["status"] != "unknown", sec
    assert any(p["error"] == REFUSAL for p in d["provenance"])


def test_one_refused_lookthrough_marks_one_line_and_section_partial():
    canned = load_fake_rows(FAKE_ROWS)
    canned["portfolio_lookthrough"][0] = {"match": {"p_cnpjs": ["08935128000159"]}, "error": REFUSAL}
    d = run(canned)
    assert d["look_through"]["status"] == "partial"
    ln = next(l for l in d["look_through"]["lines"] if l["line_no"] == 3)
    assert ln["status"] == "unknown"
    assert next(l for l in d["look_through"]["lines"] if l["line_no"] == 4)["status"] == "complete"
    # the indexer block carries the refused line as unclassified, with the reason
    assert any("linha 3" in u["reason"] for u in d["indexer"]["unclassified_breakdown"])
    assert abs(d["indexer"]["sum_check_brl"]) < 0.02


def test_one_refused_screen_leaves_the_other_screens():
    canned = load_fake_rows(FAKE_ROWS)
    canned["screen_restatements"] = [{"match": {}, "error": REFUSAL}]
    d = run(canned)
    s = d["risk_signals"]
    assert s["status"] == "partial"
    bad = next(x for x in s["screens"] if x["screen"] == "screen_restatements")
    assert bad["status"] == "unknown"
    mn = next(l for l in s["lines"] if l["cnpj"] == "32113885000121")
    assert {x["screen"] for x in mn["signals"]} == {"screen_delinquency_drivers"}
    assert mn["unknown_screens"] == ["screen_restatements"]


def test_resolve_refusal_makes_fund_lines_unknown_and_downstream_degrade():
    canned = load_fake_rows(FAKE_ROWS)
    canned["portfolio_resolve"] = [{"match": {}, "error": REFUSAL}]
    d = run(canned)
    assert d["identification"]["status"] == "partial"
    by = {l["line_no"]: l for l in d["identification"]["lines"]}
    # engine 1.7: a refused call is not retried; the lines with no CNPJ on the statement stay unknown...
    for n in (3, 4, 7):
        assert by[n]["status"] == "unknown" and by[n]["reason_code"] == "consulta_falhou"
    # ...and the two with one are identified by it, marked, with the name left unchecked (null)
    for n, cnpj in ((5, "51488342000133"), (6, "32113885000121")):
        assert by[n]["status"] == "identified" and by[n]["reason_code"] == "cnpj_extrato"
        assert by[n]["identity"]["cnpj"] == cnpj and by[n]["identity"]["name"] is None
        assert by[n]["fund_match"]["chosen"]["match_kind"] == "cnpj_extrato"
    assert d["identification"]["cnpj_extrato_line_nos"] == [5, 6]
    # downstream runs for them
    assert {l["cnpj"] for l in d["fees"]["lines"]} >= {"51488342000133", "32113885000121"}
    assert any(l["cnpj"] == "32113885000121" for l in d["restatements"]["lines"])
    assert any(l["cnpj"] == "32113885000121" for l in d["risk_signals"]["lines"])
    assert d["indexer"]["classes"][-1]["indexer_class"] == "sem classificação"
    assert sum(1 for p in d["provenance"] if p["tool"] == "portfolio_resolve") == 3  # one per call, no retry


# ---------------------------------------------------------------------------
# Masking through the whole engine.
# ---------------------------------------------------------------------------

NAME, CPF, CONTA = "BEATRIZ SINTETICA LIMA", "111.444.777-35", "98765-4"


def test_no_original_string_survives_engine_output_logs_or_errors(caplog):
    caplog.set_level(logging.DEBUG)
    hdr = ["linha_extrato", "tipo", "codigo", "quantidade", "preco_unitario", "valor", "data_posicao"]
    rows = [["titular", NAME], ["cpf", CPF], ["conta", CONTA], ["total_extrato", 30.0], [], hdr,
            [f"FUNDO DA {NAME}", "fundo", f"conta {CONTA}", 1, 10.0, 10.0, dt.date(2026, 9, 30)],
            [f"PETROBRAS {CPF}", "ação", "PETR4", 1, 10.0, 10.0, dt.date(2026, 9, 30)],
            ["TESOURO", "tesouro", "LFT 2029", 1, 10.0, 10.0, dt.date(2026, 9, 30)]]
    stmt = parse_rows(rows)
    client = fake({})  # nothing canned: every tool call is an error that echoes its args
    out = dumps(run_engine(stmt, client, clock=lambda: FAKE_CLOCK))
    blob = out + caplog.text + json.dumps([e.as_dict() for e in client.provenance], ensure_ascii=False)
    for original in (NAME, "BEATRIZ", "SINTETICA", CPF, "11144477735", CONTA, "987654"):
        assert original not in blob, original
    assert "[TITULAR]" in out and "[CONTA]" in out


def test_cli_stops_on_a_total_mismatch(tmp_path, capsys):
    f = tmp_path / "e.csv"
    f.write_text(
        "titular,Fulano Sintetico\ntotal_extrato,999\n\nlinha_extrato,tipo,codigo,quantidade,preco_unitario,valor,data_posicao\n"
        "A,ação,PETR4,1,10,10,2026-09-30\n", encoding="utf-8")
    assert main([str(f), "--client", "fake"]) == 2
    err = capsys.readouterr().err
    assert "difference R$ -989" in err and "Fulano" not in err
