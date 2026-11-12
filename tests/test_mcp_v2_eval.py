"""Offline checks for native MCP v2 transport and the paid-run boundary."""

import json
from argparse import Namespace
from types import SimpleNamespace

import pytest
from mcp.types import CallToolResult, TextContent

from research_examples import agent_eval, mcp_v2_eval as v2


def reply(data=None, error=None):
    payload = {"error": {"code": error}} if error else {"data": data if data is not None else [{"value": 1}], "meta": {"resource": "test"}}
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(payload))], isError=bool(error))


@pytest.fixture
def no_delay(monkeypatch):
    async def sleep(_delay):
        pass
    monkeypatch.setattr(v2.asyncio, "sleep", sleep)


@pytest.mark.asyncio
async def test_catalog_gate_and_data_cap_prevent_network_calls(monkeypatch, no_delay):
    called = []

    async def remote(self, name, arguments, meta=None):
        called.append(name)
        return reply()

    monkeypatch.setattr(v2.MCPServerStreamableHttp, "call_tool", remote)
    server = v2.BoundedMCP()
    assert (await server.call_tool("silo_macro", {})).model_dump(by_alias=True)["isError"]
    assert not called
    await server.call_tool("silo_coverage", {"kind": "catalog"})
    for _ in range(agent_eval.MAX_DATA_CALLS):
        assert not (await server.call_tool("silo_macro", {})).model_dump(by_alias=True)["isError"]
    assert (await server.call_tool("silo_macro", {})).model_dump(by_alias=True)["isError"]
    assert len(called) == 1 + agent_eval.MAX_DATA_CALLS


@pytest.mark.asyncio
async def test_tool_errors_and_oversized_results_are_auditable(monkeypatch, no_delay):
    async def remote(self, name, arguments, meta=None):
        return reply(error="timeout") if arguments.get("fail") else reply([{}] * 101)

    monkeypatch.setattr(v2.MCPServerStreamableHttp, "call_tool", remote)
    server = v2.BoundedMCP()
    server.catalog_seen = True
    result = await server.call_tool("silo_macro", {"fail": True})
    assert result.model_dump(by_alias=True)["isError"]
    assert server.events[-1]["tool_error"]
    assert "timeout" in server.events[-1]["error_detail"]
    assert (await server.call_tool("silo_macro", {})).model_dump(by_alias=True)["isError"]
    assert server.events[-1]["error_type"] == "ToolResultLimitError"


@pytest.mark.asyncio
async def test_transport_exceptions_never_save_credentials(monkeypatch, no_delay):
    async def remote(self, name, arguments, meta=None):
        raise RuntimeError("Bearer synthetic-private-jwt sk-synthetic-key")

    monkeypatch.setattr(v2.MCPServerStreamableHttp, "call_tool", remote)
    server = v2.BoundedMCP()
    result = await server.call_tool("silo_coverage", {"kind": "catalog"})
    assert "synthetic" not in json.dumps(server.events) + result.model_dump_json()
    assert not server.catalog_seen


def test_envelope_rejects_empty_shape_and_preserves_paging():
    with pytest.raises(ValueError, match="data or meta"):
        v2.envelope(CallToolResult(content=[TextContent(type="text", text='{"data":[]}')]))
    data = reply().model_dump(by_alias=True)
    payload = json.loads(data["content"][0]["text"])
    payload.update(next_page_url="https://example.invalid/?cursor=opaque")
    result = CallToolResult(content=[TextContent(type="text", text=json.dumps(payload))])
    assert v2.envelope(result)["next_page_url"].endswith("cursor=opaque")


def test_catalog_has_separate_bound_without_truncating_data():
    result = reply([{"catalog": "x" * 100_000}])
    assert len(v2.envelope(result, catalog=True)["data"][0]["catalog"]) == 100_000
    with pytest.raises(agent_eval.ToolResultLimitError):
        v2.envelope(result)
    with pytest.raises(agent_eval.ToolResultLimitError):
        v2.envelope(reply([{"catalog": "x" * 160_000}]), catalog=True)


@pytest.mark.asyncio
async def test_preflight_requires_nonempty_live_research_rows():
    class Server:
        async def list_tools(self):
            return []

        async def call_tool(self, name, arguments):
            return reply([]) if name == "silo_funds" else reply()

    report = await v2.preflight(Server())
    assert report["status"] == "failed"
    assert report["checks"][2]["status"] == "failed"
    assert report["read_only"]


@pytest.mark.asyncio
async def test_list_tools_uses_live_manifest_and_rejects_missing_tool(monkeypatch):
    class Tool:
        def __init__(self, name):
            self.name = name

        def model_dump(self, **kwargs):
            return {"name": self.name, "inputSchema": {}, "annotations": {"readOnlyHint": True}}

    tools = [Tool(name) for name in v2.EXPECTED_TOOLS]

    async def listing(self, *args):
        return tools

    monkeypatch.setattr(v2.MCPServerStreamableHttp, "list_tools", listing)
    server = v2.BoundedMCP()
    await server.list_tools()
    assert len(server.manifest) == 14
    assert server.events == [{"name": "mcp_tools_list", "tool_count": 14}]
    tools.pop()
    with pytest.raises(ValueError, match="14 expected"):
        await server.list_tools()


def test_v2_discovery_checks_require_successful_catalog_before_data():
    events = [{"name": "mcp_tools_list"},
              {"name": "silo_coverage", "arguments": {"kind": "catalog"}},
              {"name": "silo_macro", "network_call": True}]
    assert v2.process_checks(events)["discovery_before_data"]
    events[1]["tool_error"] = True
    assert not v2.process_checks(events)["discovery_before_data"]


def test_baseline_comparison_does_not_score_v2_answers():
    result = v2.compare_baseline([{"id": case["id"], "status": "completed", "tool_events": []}
                                  for case in agent_eval.load_cases()])
    assert sum(row["v1_rubric_pass"] for row in result) == 2
    assert all(row["v2_rubric_pass"] is None for row in result)
    assert all(row["v1_technical_classification"] for row in result)
    assert v2.JSON_RESULT != agent_eval.JSON_RESULT
    assert v2.MARKDOWN_RESULT != agent_eval.MARKDOWN_RESULT


def test_default_budget_check_passes_all_twelve_cases_with_current_ledger(monkeypatch, capsys):
    def unexpected(*args, **kwargs):
        raise AssertionError("default must not call the network or inspect keys")

    monkeypatch.setattr(v2, "BoundedMCP", unexpected)
    monkeypatch.setattr(agent_eval, "load_local_openai_key", unexpected)
    assert v2.main([]) == 0
    out = capsys.readouterr().out
    assert "Validated 12 cases" in out and "reserve $17.55" in out


def test_default_refuses_unaffordable_reserve_without_network_or_credentials(monkeypatch, capsys):
    def unexpected(*args, **kwargs):
        raise AssertionError("default must not call the network or inspect keys")

    monkeypatch.setattr(v2, "BoundedMCP", unexpected)
    monkeypatch.setattr(agent_eval, "load_local_openai_key", unexpected)
    monkeypatch.setattr(agent_eval, "load_spend_ledger", lambda: {
        "entries": [{"estimated_usd": 7.0}], "estimated_usd": 7.0,
    })
    with pytest.raises(SystemExit) as exc:
        v2.main([])
    assert exc.value.code == 2
    assert "exceeds the cumulative budget" in capsys.readouterr().err


def test_prior_spend_blocks_preflight_before_network(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("over-budget preflight must not connect")

    monkeypatch.setattr(v2, "BoundedMCP", unexpected)
    monkeypatch.setattr(agent_eval, "load_spend_ledger", lambda: {
        "entries": [{"estimated_usd": 19.0}], "estimated_usd": 19.0,
    })
    with pytest.raises(SystemExit) as exc:
        v2.main(["--preflight"])
    assert exc.value.code == 2


@pytest.mark.parametrize("arguments", [["--budget-usd", "nan"], ["--budget-usd", "21"], ["--case-id", "missing"]])
def test_bad_budget_or_case_is_rejected(arguments):
    with pytest.raises(SystemExit):
        v2.main(arguments)


def test_original_entry_point_dispatches_v2_without_changing_v1(monkeypatch):
    observed = []
    monkeypatch.setattr(v2, "main", lambda argv: observed.append(argv) or 0)
    monkeypatch.setattr("sys.argv", ["agent_eval.py", "--transport", "mcp-v2", "--preflight", "--case-id", "L1"])
    assert agent_eval.main() == 0
    assert observed == [["--budget-usd", "20.0", "--case-id", "L1", "--preflight"]]


@pytest.mark.asyncio
async def test_failed_preflight_never_starts_paid_run(monkeypatch):
    class Server:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    async def preflight(_server):
        return {"status": "failed"}

    def unexpected(*args, **kwargs):
        raise AssertionError("failed preflight must stop before paid configuration")

    monkeypatch.setattr(v2, "BoundedMCP", Server)
    monkeypatch.setattr(v2, "preflight", preflight)
    monkeypatch.setattr(agent_eval, "load_local_openai_key", unexpected)
    assert await v2.run(Namespace(run=True), [], {}) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_paid_path_preserves_questions_outputs_and_unknown_cost_reserve(monkeypatch, tmp_path, fail):
    class Server:
        manifest = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def reset_case(self):
            self.events = []

    observed = []

    async def preflight(_server):
        return {"status": "passed"}

    async def model(agent, question, **kwargs):
        observed.append(question)
        assert agent.model == "gpt-6.1-terra"
        if fail:
            raise RuntimeError("model request failed")
        hooks = kwargs["hooks"]
        await hooks.on_llm_end(None, agent, SimpleNamespace(usage=SimpleNamespace(input_tokens=10, output_tokens=5)))
        return SimpleNamespace(final_output="Evidence is insufficient for a causal claim.")

    monkeypatch.setattr(v2, "BoundedMCP", Server)
    monkeypatch.setattr(v2, "preflight", preflight)
    monkeypatch.setattr(agent_eval, "load_local_openai_key", lambda: True)
    monkeypatch.setattr(v2, "set_default_openai_client", lambda *a, **kw: None)
    monkeypatch.setattr(v2, "AsyncOpenAI", lambda **kw: None)
    monkeypatch.setattr(v2.Runner, "run", model)
    monkeypatch.setattr(v2, "JSON_RESULT", tmp_path / "v2.json")
    monkeypatch.setattr(v2, "MARKDOWN_RESULT", tmp_path / "v2.md")
    monkeypatch.setattr(agent_eval, "SPEND_LEDGER", tmp_path / "spend.json")
    # Exercise persistence below a synthetic reserve, without relaxing the real cap.
    monkeypatch.setattr(agent_eval, "worst_case_cost_usd", lambda: 0.1)
    selected = agent_eval.load_cases()[-2:]
    status = await v2.run(Namespace(run=True, budget_usd=20), selected, {"entries": [], "estimated_usd": 0})
    result = json.loads(v2.JSON_RESULT.read_text())
    assert observed[0] == selected[0]["question"]
    assert result["baseline_comparison"][0]["v2_rubric_pass"] is None
    assert "manual review required" in v2.MARKDOWN_RESULT.read_text()
    assert "changed model" in v2.MARKDOWN_RESULT.read_text()
    assert result["price_basis_usd_per_million"] == agent_eval.PRICE_BASIS
    assert all(entry["model"] == agent_eval.MODEL for entry in json.loads(agent_eval.SPEND_LEDGER.read_text())["entries"])
    if fail:
        assert status == 1
        assert len(observed) == 1
        assert result["cumulative_estimated_usd"] == agent_eval.worst_case_cost_usd()
        assert result["cases"][0]["observed_usage_estimate_usd"] == 0
    else:
        assert status == 0
        assert observed == [case["question"] for case in selected]
        assert result["cumulative_estimated_usd"] > 0


@pytest.mark.asyncio
async def test_cap_refusal_stops_the_case_without_answer_or_reserve_and_continues(monkeypatch, tmp_path):
    class Server:
        manifest = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def reset_case(self):
            self.events = []

    filters = []

    async def preflight(_server):
        return {"status": "passed"}

    async def model(agent, question, **kwargs):
        filters.append(kwargs["run_config"].call_model_input_filter)
        assert isinstance(filters[-1], agent_eval.InputCapFilter)
        await kwargs["hooks"].on_llm_end(None, agent, SimpleNamespace(usage=SimpleNamespace(input_tokens=40_000, output_tokens=500)))
        raise agent_eval.ContextCapExceeded("Estimated 71000 input tokens exceed the 70000-token cap")

    monkeypatch.setattr(v2, "BoundedMCP", Server)
    monkeypatch.setattr(v2, "preflight", preflight)
    monkeypatch.setattr(agent_eval, "load_local_openai_key", lambda: True)
    monkeypatch.setattr(agent_eval, "_ENCODING", False)
    monkeypatch.setattr(v2, "set_default_openai_client", lambda *a, **kw: None)
    monkeypatch.setattr(v2, "AsyncOpenAI", lambda **kw: None)
    monkeypatch.setattr(v2.Runner, "run", model)
    monkeypatch.setattr(v2, "JSON_RESULT", tmp_path / "v2.json")
    monkeypatch.setattr(v2, "MARKDOWN_RESULT", tmp_path / "v2.md")
    monkeypatch.setattr(agent_eval, "SPEND_LEDGER", tmp_path / "spend.json")
    selected = agent_eval.load_cases()[-2:]
    assert await v2.run(Namespace(run=True, budget_usd=20), selected, {"entries": [], "estimated_usd": 0}) == 1
    result = json.loads(v2.JSON_RESULT.read_text())
    assert len(filters) == 2 and filters[0] is not filters[1]
    for case in result["cases"]:
        assert case["status"] == "context_cap_reached" and "answer" not in case
        assert case["estimated_usd"] == pytest.approx(agent_eval.actual_cost_usd(40_000, 500))
        assert "cost_basis" not in case
    assert result["run_note"] == ""
    assert {row["v2_technical_classification"] for row in result["baseline_comparison"]} == {"context_cap_reached"}
