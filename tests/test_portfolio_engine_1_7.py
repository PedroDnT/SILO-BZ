"""Engine 1.7, offline: split identification with retry, the statement's CNPJ as identity, the retryable error and
the server's 503, the spreadsheet's vencimento and taxa, merging one asset listed twice, concentration, and the
report's fixed texts (no error text, request params or Revisor notes on the page). Synthetic data only."""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pytest

from src.portfolio import server
from src.portfolio.client import FakeClient, ToolError, load_fake_rows
from src.portfolio.common import SiloUnavailable
from src.portfolio.consolidate import merge_same_identity
from src.portfolio.diagnose import FAKE_CLOCK
from src.portfolio.engine import default_params, run_engine
from src.portfolio.identify import RESOLVE_CHUNK, identify
from src.portfolio.report import adapt, build, redator
from src.portfolio.statement import StatementTotalMismatch, parse_rows, read_statement

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "docs" / "reference" / "portfolio" / "statement-template.xlsx"
FAKE_ROWS = ROOT / "tests" / "fixtures" / "portfolio" / "fake_silo_rows.json"
DEMO = ROOT / "tests" / "fixtures" / "portfolio" / "demo_engine_output.json"
D = dt.date(2026, 9, 30)
HDR = ["linha_extrato", "tipo", "codigo", "quantidade", "preco_unitario", "valor", "data_posicao", "vencimento", "taxa"]
TIMEOUT = '{"code":"57014","details":null,"hint":null,"message":"canceling statement due to statement timeout"}'


def stmt(*lines):
    total = sum(r[5] for r in lines)
    return parse_rows([["total_extrato", total], HDR, *[list(r) for r in lines]])


def fund(name, valor=10.0, codigo=None, tipo="fundo"):
    return [name, tipo, codigo, 1, valor, valor, D, None, None]


def cand(line_no, cnpj, name):
    return dict(line_no=line_no, candidate_cnpj=cnpj, candidate_name=name, matched_name=name, matched_period="2026-05-01",
                entity_type="fi", match_kind="name_history", similarity=0.9, rank=1, quota_on_date=None, quota_rel_diff=None,
                ambiguous=False, reason="nome")


class Scripted(FakeClient):
    """portfolio_resolve answers from ``answer(names, attempt)``: rows, or a ToolError to raise."""

    def __init__(self, answer):
        super().__init__({})
        self.answer = answer
        self.seen: list[list[str]] = []

    def _request(self, tool, args):
        if tool != "portfolio_resolve":
            raise ToolError(tool, "not canned")
        names = list(args["p_names"])
        self.seen.append(names)
        out = self.answer(names, sum(1 for n in self.seen if n == names))
        if isinstance(out, ToolError):
            raise out
        return out


def resolve_calls(client):
    return [p.args["p_names"] for p in client.provenance if p.tool == "portfolio_resolve"]


# --- 2b: the split ---------------------------------------------------------------------------------------------------


def test_cnpj_lines_go_in_one_call_and_the_others_in_chunks_of_three():
    s = stmt(fund("A"), fund("B"), fund("C X", codigo="11.111.111/0001-11"), fund("D"), fund("E"), fund("F"),
             fund("G FIDC", codigo="22222222000122", tipo="FIDC"))
    c = Scripted(lambda names, _n: [cand(i, f"{i:014d}", n) for i, n in enumerate(names, 1) if len(n) == 1])
    sec, lines = identify(s, c)
    assert RESOLVE_CHUNK == 3
    assert resolve_calls(c) == [["C X", "G FIDC"], ["A", "B", "D"], ["E", "F"]]
    by = {ln["line_no"]: ln for ln in sec["lines"]}
    # each call's line_no is the index into ITS p_names
    assert by[4]["identity"]["cnpj"] == "00000000000003" and by[6]["identity"]["cnpj"] == "00000000000002"


def test_a_timeout_is_retried_once_with_the_chunk_halved_and_indices_map_per_call():
    s = stmt(fund("A"), fund("B"), fund("C"))

    def answer(names, attempt):
        if names == ["A", "B", "C"]:
            return ToolError("portfolio_resolve", TIMEOUT)
        return [cand(i, f"9{i:013d}" if n == "A" else f"8{i:013d}", n) for i, n in enumerate(names, 1)]

    c = Scripted(answer)
    sec, _ = identify(s, c)
    assert resolve_calls(c) == [["A", "B", "C"], ["A"], ["B", "C"]]
    by = {ln["line_no"]: ln for ln in sec["lines"]}
    assert [by[n]["identity"]["cnpj"] for n in (1, 2, 3)] == ["90000000000001", "80000000000001", "80000000000002"]
    assert sec["errors"][0]["transient"] is True


def test_a_refusal_is_not_retried_and_costs_only_its_own_lines():
    s = stmt(fund("A"), fund("B"), fund("C"), fund("D"))
    refusal = ToolError("portfolio_resolve", '{"code":"22023","message":"no"}')
    c = Scripted(lambda names, _n: refusal if "A" in names else [cand(1, "77777777000177", "D")])
    sec, _ = identify(s, c)
    assert resolve_calls(c) == [["A", "B", "C"], ["D"]]
    by = {ln["line_no"]: ln for ln in sec["lines"]}
    assert [by[n]["reason_code"] for n in (1, 2, 3)] == ["consulta_falhou"] * 3
    assert by[4]["status"] == "identified"
    assert sec["status"] == "partial" and "consulta_falhou" in sec["reason_codes"]


def test_a_line_without_cnpj_still_failing_on_infrastructure_raises_retryable():
    s = stmt(fund("A"), fund("B"))
    c = Scripted(lambda names, _n: ToolError("portfolio_resolve", "MCP HTTP 503: upstream", http_status=503))
    with pytest.raises(SiloUnavailable):
        identify(s, c)
    assert resolve_calls(c) == [["A", "B"], ["A"], ["B"]]


# --- 2a: the statement's CNPJ is the identity when resolve does not return it ----------------------------------------


@pytest.mark.parametrize("answer", [lambda names, _n: ToolError("portfolio_resolve", TIMEOUT), lambda names, _n: []])
def test_the_statement_cnpj_identifies_a_fund_on_error_or_no_candidate(answer):
    s = stmt(fund("FUNDO SINTETICO", codigo="33.333.333/0001-33"), fund("FIDC SINTETICO", codigo="44444444000144", tipo="FIDC"))
    sec, lines = identify(s, Scripted(answer))  # no raise: every line that failed has a CNPJ
    for ln, cnpj in zip(sec["lines"], ("33333333000133", "44444444000144")):
        assert ln["status"] == "identified" and ln["reason_code"] == "cnpj_extrato"
        assert ln["identity"]["cnpj"] == cnpj and ln["identity"]["kind"] == "fund" and ln["identity"]["name"] is None
        assert ln["fund_match"]["chosen"]["match_kind"] == "cnpj_extrato"
        assert ln["reason"] == "CNPJ do extrato; nome não conferido."
    assert sec["cnpj_extrato_line_nos"] == [1, 2]
    assert all(li.kind == "fund" and li.cnpj for li in lines)


# --- 2c: an ETF with a ticker skips the name path -----------------------------------------------------------------------


def test_an_etf_line_with_a_ticker_codigo_is_not_sent_by_name():
    s = stmt(["DEBB11 BTG DEB DI FI11", "ETF", "DEBB11", 1, 10.0, 10.0, D, None, None], fund("A"))
    c = Scripted(lambda names, _n: [])
    identify(s, c)
    calls = resolve_calls(c)
    assert ["A"] in calls and not any("DEBB11 BTG DEB DI FI11" in n for n in calls)
    assert ["DEBB11"] in calls  # the ETF registry probe, by the bare ticker


# --- transient classification -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("err,transient", [
    (ToolError("t", TIMEOUT), True),
    (ToolError("t", "PostgREST error HTTP 502 from /rpc/x\nprovenance: ..."), True),
    (ToolError("t", "Network error calling /rpc/x: reset"), True),
    (ToolError("t", "x", http_status=504), True),
    (ToolError("t", "URLError: timed out", network=True), True),
    (ToolError("t", '{"code":"22023","message":"more than one page"}'), False),
    (ToolError("t", "FakeClient: no canned answer for t"), False),
    (ToolError("t", "MCP HTTP 401: no", http_status=401), False),
])
def test_transient_is_infrastructure_only(err, transient):
    assert err.transient is transient


# --- 2d: the server answers 503 with Retry-After and no PDF -------------------------------------------------------------


def test_server_answers_503_with_retry_after_when_silo_times_out(monkeypatch):
    monkeypatch.setenv(server.TOKEN_ENV, "t0k")
    canned = load_fake_rows(FAKE_ROWS)
    canned["portfolio_resolve"] = [{"match": {}, "error": TIMEOUT}]
    app = server.create_app(client_factory=lambda: FakeClient(canned)).test_client()
    r = app.post("/diagnose", data=TEMPLATE.read_bytes(), headers={"Authorization": "Bearer t0k"})
    assert r.status_code == 503 and r.mimetype == "application/json"
    assert r.headers["Retry-After"] == str(server.RETRY_AFTER_S)
    assert r.headers["X-Silo-Error"] == "silo_unavailable" and r.headers["X-Silo-Stage"] == "engine"
    body = r.get_data(as_text=True)
    assert "57014" not in body and "p_names" not in body and "%PDF" not in body
    assert not any("57014" in v or "MARIA" in v for v in r.headers.values())


# --- 3a: the spreadsheet's optional columns -----------------------------------------------------------------------------


def test_vencimento_and_taxa_are_read_and_a_bad_vencimento_is_an_unreadable_row():
    s = stmt(["CDB X", "CDB", "CDB-1", 1, 10.0, 10.0, D, "15/03/2028", "105,00% do CDI"])
    assert s.positions[0].vencimento == dt.date(2028, 3, 15) and s.positions[0].taxa_texto == "105,00% do CDI"
    with pytest.raises(StatementTotalMismatch) as ei:
        stmt(["CDB X", "CDB", "CDB-1", 1, 10.0, 10.0, D, "março", None])
    assert "vencimento is not a date" in str(ei.value)
    old = parse_rows([["total_extrato", 10.0], HDR[:7], ["A", "fundo", None, 1, 10.0, 10.0, D]])  # columns optional
    assert old.positions[0].vencimento is None and old.positions[0].taxa_texto is None


# --- 3c: one asset listed twice is one position --------------------------------------------------------------------------


def test_same_cnpj_or_same_code_and_maturity_merge_and_codeless_lines_do_not():
    s = stmt(fund("F A", 100.0, "55.555.555/0001-55"), fund("F A (conta 2)", 50.0, "55555555000155"),
             ["CDB B", "CDB", "cdb-9", 1, 30.0, 30.0, D, dt.date(2028, 1, 1), "CDI"],
             ["CDB B", "CDB", "CDB-9", 1, 20.0, 20.0, D, dt.date(2028, 1, 1), "CDI"],
             ["CDB B", "CDB", "CDB-9", 1, 5.0, 5.0, D, dt.date(2029, 1, 1), "CDI"],
             ["CDB SEM CODIGO", "CDB", None, 1, 7.0, 7.0, D, None, None],
             ["CDB SEM CODIGO", "CDB", None, 1, 8.0, 8.0, D, None, None])
    merged, n = merge_same_identity(s)
    assert n == 2 and len(merged.positions) == 5
    p1, p2, p3, p4, p5 = merged.positions
    assert p1.valor == Decimal("150.0") and [c.source_row for c in p1.contas] == [3, 4]
    assert all(c.conta_ref is None and c.titular_ref is None for c in p1.contas)  # no account is invented
    assert p2.valor == Decimal("50.0") and p2.taxa_texto == "CDI" and p2.vencimento == dt.date(2028, 1, 1)
    assert p3.valor == Decimal("5.0")  # another maturity: another bond
    assert (p4.valor, p5.valor) == (Decimal("7.0"), Decimal("8.0"))  # no code: never merged by name
    assert merged.sum_of_lines == s.sum_of_lines and [p.line_no for p in merged.positions] == [1, 2, 3, 4, 5]
    assert merge_same_identity(stmt(fund("A"), fund("B")))[1] == 0


# --- the demo document: 3b, 3c, 4e ------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def demo():
    return json.loads(DEMO.read_text(encoding="utf-8"))


def test_demo_merges_the_repeated_cdb(demo):
    st = demo["statement"]
    assert (st["n_lines_read"], st["n_lines"], st["n_positions_merged"]) == (13, 12, 1)
    cdb = st["positions"][8]
    assert cdb["valor_brl"] == 270000.0 and len(cdb["contas"]) == 2


def test_demo_classifies_direct_credit_by_the_printed_rate(demo):
    by = {p["line_no"]: [c["indexer_class"] for c in p["classes"]] for p in demo["indexer"]["by_position"]}
    assert by[9] == ["pós-fixado (CDI)"] and by[10] == ["pós-fixado (CDI)"]
    assert by[11] == ["inflação (IPCA)"] and by[12] == ["pré-fixado"]
    rules = {i["line_no"]: i["rule"] for i in demo["indexer"]["items"] if i["line_no"] >= 9}
    assert all(r.startswith("statement_taxa/regex=") for r in rules.values())


def test_demo_concentration_fgc_and_ladder(demo):
    c = demo["concentration"]
    iss = c["issuer"]
    assert iss["label"] == "emissor como impresso no extrato; grupo econômico não avaliado"
    assert iss["groups"][0]["issuer_as_printed"] == "BANCO EXEMPLO" and iss["groups"][0]["value_brl"] == 390000.0
    fgc = c["fgc"]
    assert fgc["limit_brl"] == 250000.0 and fgc["n_above_limit"] == 1
    assert fgc["issuers"][0]["excess_brl"] == 140000.0 and fgc["issuers"][0]["tipos"] == ["CDB", "LCA"]
    assert fgc["label"].startswith("a conferir: limite por CPF e instituição")
    assert "4.222" in fgc["rule"] and "LF" in fgc["rule"]
    lad = c["maturity_ladder"]
    assert abs(lad["sum_check_brl"]) < 0.01
    assert {b["bucket"]: b["line_nos"] for b in lad["buckets"]}["de 5 a 10 anos"] == [1, 11]
    assert c["manager"]["reason_code"] == "gestor_sem_api" and c["fund_liquidity"]["reason_code"] == "liquidez_sem_api"


# --- 2e, 4a, 4b, 4d: nothing of the pipeline's text reaches the Redator or the page ------------------------------------

SENTINEL = "SENTINELA-XYZZY"


def _leaky_engine():
    canned = load_fake_rows(FAKE_ROWS)
    leak = '{"code":"22023","message":"' + SENTINEL + ' p_names=[...]"}'
    canned["portfolio_resolve"] = [{"match": {}, "error": leak}]
    canned["screen_restatements"] = [{"match": {}, "error": leak}]
    canned["portfolio_movement"] = [{"match": {}, "error": "PostgREST error HTTP 500 " + SENTINEL}]
    s = read_statement(TEMPLATE)
    return run_engine(s, FakeClient(canned, clock=lambda: FAKE_CLOCK), default_params(s.position_date), clock=lambda: FAKE_CLOCK)


def test_no_error_text_params_or_revisor_notes_reach_the_page():
    eng = _leaky_engine()
    assert SENTINEL in json.dumps(eng)  # the engine JSON keeps the detail in errors / provenance
    view = adapt.to_view(eng)
    html, narrative = build.build(view, "fake")
    for bad in (SENTINEL, "erro literal", "falhou (", "PostgREST", "p_names", "Notas do Revisor", "portfolio_resolve falhou"):
        assert bad not in html, bad
    gaps = html.split("O que não foi possível avaliar")[1].split("Metodologia")[0]
    assert gaps.count("Linhas não identificadas") >= 1 and "uma consulta ao SILO falhou" in gaps
    # the unidentified lines come grouped: one line per reason, not one per line
    assert gaps.count("Linhas não identificadas") == len(eng["identification"]["unknown_groups"])


def test_the_redator_sees_facts_and_codes_only():
    view = adapt.to_view(_leaky_engine())
    msg = redator.build_user_message(view)
    assert SENTINEL not in msg and '"reason"' not in msg and '"params"' not in msg and '"error"' not in msg
    sent = json.loads(msg.split("\n", 1)[1].rsplit("\n\nEscreva", 1)[0])
    assert "gaps" not in sent and all(set(v) <= {"status", "reason_codes"} for v in sent["sections"].values())
    assert sent["sections"]["identification"]["reason_codes"]  # the status codes stay
    assert "Achados são sobre a carteira" in redator.SYSTEM_PROMPT and "devolva findings vazio" in redator.SYSTEM_PROMPT


def test_a_finding_that_quotes_a_provenance_error_is_removed():
    from src.portfolio.report import revisor
    view = adapt.to_view(_leaky_engine())
    f = redator.Finding("f1", "achados", "Falha", "A consulta falhou: {{provenance[0].endpoint}}.", ["p1"])
    res = revisor.check(view, [f])
    assert res.kept == []


def test_two_lines_that_resolve_to_one_fund_are_flagged_and_never_a_finding():
    # different printed names, no code: not merged by the statement; identification finds the same CNPJ
    s = stmt(fund("FUNDO SINTETICO A"), fund("FDO SINTETICO A CONTA 2", 20.0))
    sec, _ = identify(s, Scripted(lambda names, _n: [cand(i, "66666666000166", "F") for i, _ in enumerate(names, 1)]))
    assert sec["same_identity_line_groups"] == [{"kind": "cnpj", "key": "66666666000166", "line_nos": [1, 2]}]
    view = {"lookthrough": {"shared_exposure": [
        {"key": "f", "name": "f", "level": "fundo", "total_brl": 1.0, "total_pct": 1.0, "same_position": True,
         "legs": [{"line_id": "L1", "via": "x", "value_brl": 1.0}, {"line_id": "L2", "via": "y", "value_brl": 1.0}],
         "provenance": ["p1"]}]}, "provenance": [{"id": "p1"}]}
    titles = [f["title"] for f in redator.template_findings(view)["findings"]]
    assert "Duas linhas, uma carteira por baixo" not in titles


def test_codeless_fund_lines_merge_only_with_the_same_name_type_and_printed_quota():
    s = stmt(["FUNDO X", "fundo", None, 10, 1.5, 15.0, D, None, None], ["FUNDO X", "fundo", None, 20, 1.5, 30.0, D, None, None],
             ["FUNDO X", "fundo", None, 1, 1.7, 1.7, D, None, None])
    merged, n = merge_same_identity(s)
    assert n == 1 and [p.valor for p in merged.positions] == [Decimal("45.0"), Decimal("1.7")]
    assert merged.positions[0].quantidade == 30 and merged.positions[0].preco_unitario == Decimal("1.5")
