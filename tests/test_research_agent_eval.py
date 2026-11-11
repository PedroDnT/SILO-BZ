"""Offline guards for the paid research-agent evaluation path."""

import json
from decimal import Decimal
from datetime import datetime, timezone

import pytest

from research_examples import agent_eval


def test_replacement_preserves_cases_but_full_context_reserve_exceeds_existing_cap():
    cases = agent_eval.load_cases()
    assert len(cases) == 12
    assert {case["expected_disposition"] for case in cases} == {
        "answer_or_bounded_limit", "limitation"
    }
    assert agent_eval.DEFAULT_BUDGET_USD == 20
    assert agent_eval.worst_case_cost_usd() == pytest.approx(69.69)
    assert len(cases) * agent_eval.worst_case_cost_usd() > agent_eval.DEFAULT_BUDGET_USD


def test_discovery_check_rejects_failed_or_late_catalog_calls():
    valid = [
        {"name": "silo_catalog", "arguments": {}},
        {"name": "silo_tools", "arguments": {"query": ""}},
        {"name": "silo_call", "arguments": {"endpoint": "coverage"}},
        {"name": "silo_call", "arguments": {"endpoint": "inflation"}},
    ]
    assert agent_eval.process_checks(valid, "answer_or_bounded_limit")["discovery_before_data"]

    failed_catalog = [{**valid[0], "error_type": "SiloTimeout"}, *valid[1:]]
    assert not agent_eval.process_checks(failed_catalog, "answer_or_bounded_limit")["discovery_before_data"]
    assert not agent_eval.process_checks([valid[2], valid[0], valid[1]], "answer_or_bounded_limit")["discovery_before_data"]


def test_summary_keeps_evaluator_review_notes_out_of_agent_answer():
    record = {
        "started_at": "2026-09-23T00:00:00Z", "model": "gpt-5-mini",
        "budget_usd": 20.0, "estimated_usd": 0.01, "run_note": "",
        "cases": [{
            "id": "Q1", "question": "A professional question?", "status": "completed",
            "duration_seconds": 1.5, "estimated_usd": 0.01, "answer": "Limited answer.",
            "checks": {"discovery_before_data": True, "data_calls": 1,
                       "catalog_discovered": True, "tools_inspected": True,
                       "coverage_attempted": True},
        }],
    }
    summary = agent_eval._summary_md(record)
    assert "Limited answer." in summary
    assert "Discovery before data" in summary
    assert "OPENAI_API_KEY" not in summary


def test_empty_inherited_key_uses_ignored_local_file(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("OPENAI_API_KEY=synthetic-test-value\n")
    monkeypatch.setattr(agent_eval, "ROOT", tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "")
    assert agent_eval.load_local_openai_key()
    assert agent_eval.os.environ["OPENAI_API_KEY"] == "synthetic-test-value"


def test_published_schema_discovery_exposes_sdk_names_types_and_requiredness():
    contract = json.loads((agent_eval.ROOT / "openapi.json").read_text())
    args = agent_eval.endpoint_arguments(contract, "focus_expectations")
    by_name = {item["name"]: item for item in args}
    assert by_name["endpoint"]["required"] is True
    assert by_name["horizon"]["required"] is True
    assert by_name["start"]["required"] is False
    assert by_name["start"]["format"] == "date"
    assert "p_endpoint" not in by_name


def test_invalid_arguments_fail_before_network_call():
    contract = json.loads((agent_eval.ROOT / "openapi.json").read_text())

    class NoNetwork:
        def focus_expectations(self, **kwargs):
            raise AssertionError("network call should not happen")

    adapter = agent_eval.SiloTools(NoNetwork(), contract)
    adapter.catalog_seen = adapter.tools_seen = True
    with pytest.raises(agent_eval.ArgumentValidationError, match="Missing required.*horizon"):
        adapter.invoke_endpoint("focus_expectations", '{"endpoint":"ExpectativasMercadoAnuais"}')
    with pytest.raises(agent_eval.ArgumentValidationError, match="Unknown argument.*p_endpoint"):
        adapter.invoke_endpoint("focus_expectations", '{"p_endpoint":"x","horizon":"2025"}')
    with pytest.raises(agent_eval.ArgumentValidationError, match="ISO date"):
        adapter.invoke_endpoint("focus_expectations", '{"endpoint":"ExpectativasMercadoAnuais","horizon":"2025","start":"yesterday"}')
    assert adapter.data_calls == 0


def test_valid_schema_arguments_reach_sdk_and_are_auditable():
    contract = json.loads((agent_eval.ROOT / "openapi.json").read_text())
    observed = []

    class FakeClient:
        def focus_expectations(self, endpoint, horizon, indicator=None, start=None, end=None):
            observed.append((endpoint, horizon, indicator, start, end))
            return [{"survey_date": "2024-12-06", "median": 4.59}]

    adapter = agent_eval.SiloTools(FakeClient(), contract)
    adapter.catalog_seen = adapter.tools_seen = True
    result = adapter._record("silo_call", {"endpoint": "focus_expectations"}, lambda: adapter.invoke_endpoint(
        "focus_expectations", '{"endpoint":"ExpectativasMercadoAnuais","horizon":"2025","indicator":"IPCA","start":"2024-12-06"}'))
    assert json.loads(result)[0]["median"] == 4.59
    assert observed == [("ExpectativasMercadoAnuais", "2025", "IPCA", "2024-12-06", None)]
    assert adapter.events[0]["result_json"] == result
    assert len(adapter.events[0]["result_sha256"]) == 64


def test_safe_api_error_retains_code_and_message_without_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-secret-token")
    error = agent_eval.SiloError(404, json.dumps({
        "code": "PGRST202", "message": "function unavailable synthetic-secret-token"
    }), "https://example.invalid/rpc/focus_expectations")
    safe = agent_eval.safe_tool_error(error)
    assert safe["status"] == 404
    assert safe["code"] == "PGRST202"
    assert "function unavailable" in safe["message"]
    assert "synthetic-secret-token" not in json.dumps(safe)
    assert "example.invalid" not in json.dumps(safe)


def test_runtime_input_is_only_the_professional_question():
    case = {"question": "What changed?", "review": "private answer", "expected_disposition": "limitation"}
    assert agent_eval.runtime_question(case) == "What changed?"


def test_private_references_cover_every_case_and_question_has_no_endpoint_hint():
    cases = agent_eval.load_cases()
    reference = json.loads((agent_eval.ROOT / "research_examples/eval_reference.json").read_text())
    contract = json.loads((agent_eval.ROOT / "openapi.json").read_text())
    assert set(reference["cases"]) == {case["id"] for case in cases}
    for case in cases:
        assert all(reference["cases"][case["id"]].get(key) for key in
                   ("contract_endpoints", "identifier", "date_rule", "valid_join", "calculation", "required_caveat", "deterministic_check"))
        assert all(f"/rpc/{endpoint}" in contract["paths"] for endpoint in reference["cases"][case["id"]]["contract_endpoints"])
        assert "/rpc/" not in case["question"]


def test_technical_failure_and_full_rubric_pass_are_separate():
    item = {"status": "completed", "tool_events": [{"error": {"code": "PGRST202"}}]}
    assert agent_eval.technical_classification(item) == "api_unavailable"
    checks = dict.fromkeys(("disposition", "identifiers_and_periods", "calculation_or_limitation",
                            "source_citation", "material_caveats"), True)
    assert agent_eval.full_rubric_pass(item, checks)
    assert not agent_eval.full_rubric_pass(item, {**checks, "hard_failures": ["invented_join"]})
    assert not agent_eval.full_rubric_pass(item, {**checks, "source_citation": False})
    assert not agent_eval.full_rubric_pass({"status": "error"}, checks)
    assert agent_eval.technical_classification({"status": "error", "error_type": "MaxTurnsExceeded"}) == "turn_exhaustion"
    assert agent_eval.technical_classification({"status": "completed", "tool_events": [{"error_type": "SiloOverCap"}]}) == "query_data_failure"


def test_baseline_review_is_complete_and_does_not_confuse_completion_with_pass():
    run = json.loads((agent_eval.ROOT / "research_examples/baseline-results.json").read_text())
    review = json.loads((agent_eval.ROOT / "research_examples/baseline-review.json").read_text())
    assert review["run_started_at"] == run["started_at"]
    assert set(review["cases"]) == {case["id"] for case in run["cases"]}
    passed = [case["id"] for case in run["cases"] if agent_eval.full_rubric_pass(case, review["cases"][case["id"]])]
    assert passed == ["L1", "L3"]
    assert sum(case["status"] == "completed" for case in run["cases"]) == 11
    assert Decimal("56508.93") * Decimal("0.124") == Decimal("7007.10732")
    assert Decimal("4.59") - Decimal("4.26") == Decimal("0.33")


def test_paid_run_requires_fresh_matching_passed_live_preflight(tmp_path):
    now = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
    path = tmp_path / "preflight.json"
    report = {
        "checked_at": "2026-09-25T11:00:00Z", "base_url": "https://example.invalid",
        "read_only": True, "status": "passed",
        "endpoints": {name: {"status": "passed"} for name in agent_eval.REQUIRED_RESEARCH_RPCS},
    }
    path.write_text(json.dumps(report))
    agent_eval.validate_preflight_report(path, "https://example.invalid", now)
    report["endpoints"]["focus_expectations"]["status"] = "PGRST202"
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="all three"):
        agent_eval.validate_preflight_report(path, "https://example.invalid", now)
    report["endpoints"]["focus_expectations"]["status"] = "passed"
    report["checked_at"] = "2026-09-24T00:00:00Z"
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="six hours"):
        agent_eval.validate_preflight_report(path, "https://example.invalid", now)


def test_discovery_does_not_silently_trim_more_than_41_tools():
    paths = {f"/view_{i}": {"get": {"description": "Public view", "parameters": []}} for i in range(55)}
    adapter = agent_eval.SiloTools(object(), {"paths": paths})
    adapter.catalog_seen = True
    tools = json.loads(adapter.discover_tools(""))
    assert len(tools) == 55
    assert tools[-1]["endpoint"] == "view_54"


def test_published_nested_types_and_numeric_limits_are_checked():
    specs = [{"name": "ids", "type": "array", "items": {"type": "string"}, "required": True},
             {"name": "limit", "type": "integer", "maximum": 1000, "required": False}]
    assert agent_eval.validate_arguments(specs, {"ids": ["PETR4"], "limit": 10})
    with pytest.raises(agent_eval.ArgumentValidationError, match="ids item must be string"):
        agent_eval.validate_arguments(specs, {"ids": [42]})
    with pytest.raises(agent_eval.ArgumentValidationError, match="at most 1000"):
        agent_eval.validate_arguments(specs, {"ids": [], "limit": 1001})
    with pytest.raises(agent_eval.ArgumentValidationError, match="ISO date"):
        agent_eval.validate_arguments([{"name": "start", "type": "string", "format": "date", "required": True}], {"start": "20240901"})


def test_safe_server_hint_and_local_result_limit_remain_actionable():
    error = agent_eval.SiloError(400, json.dumps({"code": "22023", "message": "too many rows",
        "hint": "narrow start/end; token=synthetic-secret"}), "https://example.invalid")
    safe = agent_eval.safe_tool_error(error)
    assert safe["hint"].startswith("narrow start/end")
    assert "synthetic-secret" not in json.dumps(safe)
    assert agent_eval.safe_tool_error(agent_eval.ToolResultLimitError("More than 100 rows; narrow the window"))["message"].startswith("More than 100 rows")


def test_spend_ledger_fails_closed_on_inconsistent_estimate(monkeypatch, tmp_path):
    path = tmp_path / "ledger.json"
    monkeypatch.setattr(agent_eval, "SPEND_LEDGER", path)
    path.write_text(json.dumps({"estimated_usd": 0.1, "entries": [{"estimated_usd": 0.5}]}))
    with pytest.raises(ValueError, match="consistent nonnegative"):
        agent_eval.load_spend_ledger()


@pytest.mark.parametrize("tokens, expected", [(272_000, 0.692), (272_001, 1.378005)])
def test_replacement_cost_includes_cache_writes_and_long_context(tokens, expected):
    assert agent_eval.actual_cost_usd(tokens, 1000) == pytest.approx(expected)


@pytest.mark.asyncio
async def test_usage_is_priced_per_request_not_aggregate_context():
    from types import SimpleNamespace

    hooks = agent_eval.UsageHooks()
    response = SimpleNamespace(usage=SimpleNamespace(input_tokens=200_000, output_tokens=1000))
    await hooks.on_llm_end(None, None, response)
    await hooks.on_llm_end(None, None, response)
    assert hooks.input_tokens == 400_000 and hooks.requests == 2
    assert hooks.estimated_usd == pytest.approx(1.024)
    assert hooks.estimated_usd < agent_eval.actual_cost_usd(400_000, 2000)


@pytest.mark.parametrize("args", [[], ["--run", "--case-id", "L1"]])
def test_replacement_refuses_unaffordable_v1_before_credentials_or_network(monkeypatch, args):
    def unexpected(*args, **kwargs):
        raise AssertionError("must refuse before loading a key or connecting")

    monkeypatch.setattr(agent_eval, "load_local_openai_key", unexpected)
    monkeypatch.setattr(agent_eval, "SiloClient", unexpected)
    monkeypatch.setattr(agent_eval, "AsyncOpenAI", unexpected)
    monkeypatch.setattr(agent_eval.sys, "argv", ["agent_eval.py", *args])
    with pytest.raises(SystemExit) as exc:
        agent_eval.main()
    assert exc.value.code == 2


def test_replacement_writes_separate_results_without_rewriting_baseline(monkeypatch, tmp_path):
    from research_examples import mcp_v2_eval as v2

    assert agent_eval.MODEL in agent_eval.JSON_RESULT.name
    assert agent_eval.MODEL in agent_eval.MARKDOWN_RESULT.name
    assert agent_eval.MODEL in v2.JSON_RESULT.name
    assert agent_eval.MODEL in v2.MARKDOWN_RESULT.name
    historical = tmp_path / "eval-results.json"
    historical.write_text('historical baseline\n')
    monkeypatch.setattr(agent_eval, "JSON_RESULT", tmp_path / agent_eval.JSON_RESULT.name)
    monkeypatch.setattr(agent_eval, "MARKDOWN_RESULT", tmp_path / agent_eval.MARKDOWN_RESULT.name)
    record = {"started_at": "2026-11-11T12:00:00-03:00", "model": agent_eval.MODEL,
              "budget_usd": 20, "estimated_usd": 0, "cases": [], "price_basis_usd_per_million": agent_eval.PRICE_BASIS}
    agent_eval.write_results(record)
    assert historical.read_text() == 'historical baseline\n'
    assert json.loads(agent_eval.JSON_RESULT.read_text())["price_basis_usd_per_million"]["cache_write"] == 2.5
    assert agent_eval.MODEL in agent_eval.MARKDOWN_RESULT.read_text()


@pytest.mark.asyncio
async def test_replacement_agent_uses_responses_and_tools_through_real_sdk():
    import httpx2
    from agents.models.openai_provider import OpenAIProvider

    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        assert request.url.path == "/v1/responses"
        return httpx2.Response(200, json={
            "id": "resp_mock", "created_at": 0, "object": "response", "status": "completed",
            "model": agent_eval.MODEL, "parallel_tool_calls": False, "tool_choice": "auto",
            "tools": [], "output": [{"type": "message", "id": "msg_mock", "role": "assistant",
                "status": "completed", "content": [{"type": "output_text", "text": "Limited answer.", "annotations": []}]}],
            "usage": {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110,
                      "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}},
        })

    client = agent_eval.AsyncOpenAI(api_key="synthetic-test-key", max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
    adapter = agent_eval.SiloTools(object(), {"paths": {}})
    agent = agent_eval.Agent(name="Offline migration test", model=agent_eval.MODEL,
        instructions=agent_eval.INSTRUCTIONS, tools=adapter.as_agent_tools(),
        model_settings=agent_eval.ModelSettings(max_tokens=agent_eval.MAX_OUTPUT_TOKENS,
                                               parallel_tool_calls=False, verbosity="low"))
    hooks = agent_eval.UsageHooks()
    async with client:
        result = await agent_eval.Runner.run(agent, "What changed?", hooks=hooks,
            run_config=agent_eval.RunConfig(tracing_disabled=True,
                model_provider=OpenAIProvider(openai_client=client)))
    assert result.final_output == "Limited answer."
    request = seen[0]
    assert request["model"] == "gpt-5.6-terra"
    assert request["max_output_tokens"] == 2000 and request["parallel_tool_calls"] is False
    assert request["text"]["verbosity"] == "low"
    assert {tool["name"] for tool in request["tools"]} == {"silo_catalog", "silo_tools", "silo_call"}
    assert hooks.estimated_usd == pytest.approx(.00037)


def test_v1_model_error_retains_reserve_and_stops_without_rewriting_old_spend(monkeypatch, tmp_path):
    class Client:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def catalog(self):
            return []

    observed = []
    def fail(agent, question, **kwargs):
        observed.append(question)
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(agent_eval, "SiloClient", Client)
    monkeypatch.setattr(agent_eval, "validate_preflight_report", lambda *a: None)
    monkeypatch.setattr(agent_eval, "load_local_openai_key", lambda: True)
    monkeypatch.setattr(agent_eval, "AsyncOpenAI", lambda **kw: None)
    monkeypatch.setattr(agent_eval, "set_default_openai_client", lambda *a, **kw: None)
    monkeypatch.setattr(agent_eval.Runner, "run_sync", fail)
    monkeypatch.setattr(agent_eval, "worst_case_cost_usd", lambda: .1)
    monkeypatch.setenv("SILO_URL", "https://example.invalid")
    monkeypatch.setenv("SILO_ANON_KEY", "synthetic-test-key")
    monkeypatch.setattr(agent_eval.sys, "argv", ["agent_eval.py", "--run", "--preflight-report", "synthetic.json"])
    for name in ("JSON_RESULT", "MARKDOWN_RESULT", "SPEND_LEDGER"):
        monkeypatch.setattr(agent_eval, name, tmp_path / getattr(agent_eval, name).name)
    previous = {"run": "historical", "estimated_usd": .5}
    agent_eval.SPEND_LEDGER.write_text(json.dumps({"estimated_usd": .5, "entries": [previous]}))
    assert agent_eval.main() == 1
    assert len(observed) == 1
    record = json.loads(agent_eval.JSON_RESULT.read_text())
    ledger = json.loads(agent_eval.SPEND_LEDGER.read_text())
    assert ledger["entries"][0] == previous and ledger["estimated_usd"] == .6
    assert record["cases"][0]["estimated_usd"] == .1
    assert record["cases"][0]["observed_usage_estimate_usd"] == 0
    assert ledger["entries"][1]["model"] == agent_eval.MODEL
