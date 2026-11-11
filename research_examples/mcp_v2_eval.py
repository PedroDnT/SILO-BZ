#!/usr/bin/env python3
"""Evaluate the same 12 questions through live MCP v2; default is an offline budget check."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents import Agent, ModelSettings, RunConfig, Runner, set_default_openai_client
from agents.mcp import MCPServerStreamableHttp
from mcp.types import CallToolResult, TextContent
from openai import AsyncOpenAI

from research_examples import agent_eval as baseline

MCP_URL = "https://zcjbtpxuhdekpwcxmepn.supabase.co/functions/v1/silo-mcp-v2"
JSON_RESULT = Path(__file__).with_name(f"eval-v2-{baseline.MODEL}-results.json")
MARKDOWN_RESULT = baseline.ROOT / f"docs/reference/research/agent-evaluation-v2-{baseline.MODEL}-results.md"
# The live v2 catalog is about 129 KB; retain it whole within the existing context reserve.
MAX_CATALOG_CHARS = 160_000
EXPECTED_TOOLS = {f"silo_{name}" for name in (
    "search", "prices", "statements", "funds", "fidc", "derivatives", "curves",
    "macro", "positioning", "events", "screens", "panel", "portfolio", "coverage",
)}
INSTRUCTIONS = baseline.INSTRUCTIONS.replace(
    "Start with the SILO catalog, then inspect the available public tools.",
    "The tools supplied here are the live MCP v2 schemas. Start with the SILO "
    "catalog using silo_coverage with kind=catalog, then inspect the available public tools.",
)
# Evaluator-only availability probes. Never include these arguments in model input.
PROBES = (
    ("silo_statements", {"id": "PETR4", "kind": "versions", "from": "2024-03-31", "to": "2024-03-31", "limit": 1}),
    ("silo_funds", {"id": "00332266000131", "kind": "properties", "from": "2025-03-31", "to": "2025-03-31", "limit": 1}),
    ("silo_macro", {"id": "IPCA", "kind": "expectations", "from": "2024-12-06", "to": "2024-12-06", "limit": 1,
                    "options": {"family": "annual", "horizon": "2025"}}),
)


def envelope(result: CallToolResult, *, catalog: bool = False) -> dict[str, Any]:
    """The first MCP text block is the gateway JSON; later blocks carry provenance."""
    payload = result.model_dump(by_alias=True, exclude_none=True)
    if len(json.dumps(payload)) > (MAX_CATALOG_CHARS if catalog else baseline.MAX_TOOL_CHARS):
        raise baseline.ToolResultLimitError("MCP response exceeds the evaluation character cap")
    value = json.loads(payload["content"][0]["text"])
    if not isinstance(value, dict):
        raise ValueError("MCP response must contain a gateway object")
    if payload.get("isError") or "error" in value:
        error = value.get("error")
        code = str(error.get("code", "unknown")) if isinstance(error, dict) else "unknown"
        raise ValueError("MCP gateway error: " + (code if re.fullmatch(r"[a-zA-Z0-9_]{1,40}", code) else "unknown"))
    if not isinstance(value.get("data"), list) or not isinstance(value.get("meta"), dict):
        raise ValueError("MCP response is missing data or meta")
    if len(value["data"]) > baseline.MAX_DATA_ROWS:
        raise baseline.ToolResultLimitError("MCP response exceeds the evaluation row cap")
    return value


class BoundedMCP(MCPServerStreamableHttp):
    """Use the installed MCP transport, adding only evaluation bounds and evidence."""

    def __init__(self) -> None:
        token = os.environ.get("SILO_USER_JWT", "")
        super().__init__(
            params={"url": MCP_URL, "timeout": 30,
                    "headers": {"Authorization": f"Bearer {token}"} if token else {}},
            cache_tools_list=True, max_retry_attempts=0, client_session_timeout_seconds=40,
        )
        self.manifest: list[dict[str, Any]] = []
        self.last_call = 0.0
        self.reset_case()

    def reset_case(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.catalog_seen = False
        self.data_calls = 0

    async def list_tools(self, run_context=None, agent=None):
        tools = await super().list_tools(run_context, agent)
        if {tool.name for tool in tools} != EXPECTED_TOOLS:
            raise ValueError("Live MCP v2 must expose exactly the 14 expected tools")
        self.manifest = [tool.model_dump(by_alias=True, exclude_none=True) for tool in tools]
        if any(tool.get("annotations", {}).get("readOnlyHint") is not True for tool in self.manifest):
            raise ValueError("Every evaluation tool must be declared read-only")
        if not any(event["name"] == "mcp_tools_list" for event in self.events):
            self.events.append({"name": "mcp_tools_list", "tool_count": len(tools)})
        return tools

    async def call_tool(self, tool_name, arguments, meta=None):
        started = time.monotonic()
        event: dict[str, Any] = {"name": tool_name, "arguments": arguments or {}}
        try:
            if tool_name not in EXPECTED_TOOLS:
                raise ValueError("Tool is not in the evaluation manifest")
            if tool_name != "silo_coverage":
                if not self.catalog_seen:
                    raise ValueError("Read silo_coverage with kind=catalog before substantive data")
                if self.data_calls >= baseline.MAX_DATA_CALLS:
                    raise ValueError("Data-call cap reached; synthesize the evidence already collected")
                self.data_calls += 1
            # Anonymous access allows ten calls/minute. Keep one shared cadence across cases.
            await asyncio.sleep(max(0, 6.1 - (time.monotonic() - self.last_call)))
            self.last_call = time.monotonic()
            event["network_call"] = True
            result = await super().call_tool(tool_name, arguments, meta)
            value = envelope(result, catalog=tool_name == "silo_coverage" and event["arguments"].get("kind") == "catalog")
            event["result_json"] = value
            event["result_sha256"] = hashlib.sha256(baseline._json(value).encode()).hexdigest()
            event["returned_rows"] = len(value["data"])
            if tool_name == "silo_coverage" and event["arguments"].get("kind") == "catalog":
                self.catalog_seen = True
            return result
        except Exception as exc:
            # Transport exception text can include credentials; persist only its type.
            event["error_type"] = type(exc).__name__
            event["tool_error"] = True
            message = str(exc) if isinstance(exc, (ValueError, baseline.ToolResultLimitError)) else "MCP request failed"
            event["error_detail"] = message
            return CallToolResult(content=[TextContent(type="text", text=json.dumps({"error": {"code": type(exc).__name__, "message": message}}))], isError=True)
        finally:
            event["duration_seconds"] = round(time.monotonic() - started, 3)
            self.events.append(event)


async def preflight(server: BoundedMCP) -> dict[str, Any]:
    await server.list_tools()
    probes = [("silo_coverage", {"kind": "catalog"}), *PROBES]
    checks = []
    for name, arguments in probes:
        try:
            value = envelope(await server.call_tool(name, arguments), catalog=name == "silo_coverage" and arguments.get("kind") == "catalog")
            if not value["data"]:
                raise ValueError("Required research probe returned no rows")
            checks.append({"tool": name, "status": "passed", "rows": len(value["data"])})
        except (ValueError, baseline.ToolResultLimitError) as exc:
            event = getattr(server, "events", [{}])[-1]
            checks.append({"tool": name, "status": "failed", "reason": event.get("error_detail", str(exc))})
    return {"checked_at": datetime.now(timezone.utc).isoformat(), "transport": "mcp-v2",
            "base_url": MCP_URL, "read_only": True, "checks": checks,
            "status": "passed" if all(c["status"] == "passed" for c in checks) else "failed"}


def process_checks(events: list[dict[str, Any]]) -> dict[str, Any]:
    listed = next((i for i, e in enumerate(events) if e["name"] == "mcp_tools_list"), None)
    catalog = next((i for i, e in enumerate(events) if e["name"] == "silo_coverage"
                    and e["arguments"].get("kind") == "catalog" and not e.get("tool_error")), None)
    data = [i for i, e in enumerate(events) if e["name"] in EXPECTED_TOOLS - {"silo_coverage"}]
    return {"catalog_discovered": catalog is not None, "tools_inspected": listed is not None,
            "discovery_before_data": listed is not None and catalog is not None
            and (not data or max(listed, catalog) < min(data)),
            "coverage_attempted": any(e["name"] == "silo_coverage" and e["arguments"].get("kind", "freshness") != "catalog" for e in events),
            "data_calls": sum(e.get("network_call", False) for e in events if e["name"] != "silo_coverage"),
            "substantive_accuracy": "manual_review_required"}


def write_results(record: dict[str, Any]) -> None:
    JSON_RESULT.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    shown_at = datetime.fromisoformat(record["started_at"]).astimezone(ZoneInfo("America/Sao_Paulo"))
    lines = ["# MCP v2 research evaluation", "", f"Run: {shown_at.isoformat()} (Brasília). Model: {record['model']}.",
             "Same questions as the historical gpt-5-mini baseline, with a changed model. "
             "Differences cannot be attributed to transport alone.",
             "No v2 rubric score until independent review. The original baseline remains 2/12.",
             f"Estimated spend this run: ${record['estimated_usd']:.6f}; cumulative: ${record['cumulative_estimated_usd']:.6f}.", ""]
    lines += ["| Case | V1 run | V1 technical classification | V1 rubric pass | V2 run | V2 technical classification | V2 rubric |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for comparison in record["baseline_comparison"]:
        lines.append(f"| {comparison['id']} | {comparison['v1_status']} | {comparison['v1_technical_classification']} | "
                     f"{comparison['v1_rubric_pass']} | {comparison['v2_status']} | {comparison['v2_technical_classification']} | manual review required |")
    lines.append("")
    for item in record["cases"]:
        lines += [f"## {item['id']}: {item['status']}", "", item["question"], "",
                  baseline._json(item["checks"]), "", item.get("answer", item.get("error_type", "No answer")), ""]
    lines += [record.get("run_note", ""), ""]
    MARKDOWN_RESULT.write_text("\n".join(lines))


def compare_baseline(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    run = json.loads((baseline.ROOT / "research_examples/baseline-results.json").read_text())
    review = json.loads((baseline.ROOT / "research_examples/baseline-review.json").read_text())
    if review["run_started_at"] != run["started_at"]:
        raise ValueError("Baseline grading does not match the saved baseline run")
    previous = {case["id"]: case for case in run["cases"]}
    return [{"id": case["id"], "v1_status": previous[case["id"]]["status"],
             "v1_technical_classification": baseline.technical_classification(previous[case["id"]]),
             "v1_rubric_pass": baseline.full_rubric_pass(previous[case["id"]], review["cases"][case["id"]]),
             "v2_status": case["status"], "v2_tool_errors": sum(bool(e.get("tool_error")) for e in case["tool_events"]),
             "v2_technical_classification": "mcp_tool_error" if case["status"] != "error" and any(e.get("tool_error") for e in case["tool_events"])
             else baseline.technical_classification(case),
             "v2_rubric_pass": None} for case in cases]


async def run(args, selected, ledger) -> int:
    compare_baseline([])  # Validate evaluator-only baseline evidence before any paid request.
    async with BoundedMCP() as server:
        report = await preflight(server)
        print(json.dumps(report, indent=2))
        if report["status"] != "passed" or not args.run:
            return 0 if report["status"] == "passed" else 1
        if not baseline.load_local_openai_key():
            raise ValueError("OPENAI_API_KEY is required in the environment or ignored .env")
        set_default_openai_client(AsyncOpenAI(max_retries=0, timeout=60), use_for_tracing=False)
        record = {"started_at": datetime.now(timezone.utc).isoformat(), "transport": "mcp-v2",
                  "base_url": MCP_URL, "access": "signed_in" if os.environ.get("SILO_USER_JWT") else "anonymous",
                  "model": baseline.MODEL, "budget_usd": args.budget_usd,
                  "price_basis_usd_per_million": baseline.PRICE_BASIS,
                  "estimated_usd": 0.0, "cumulative_estimated_usd": ledger["estimated_usd"],
                  "preflight": report, "mcp_tools": server.manifest, "cases": [], "baseline_comparison": [], "run_note": ""}
        record["limits"] = {"data_calls": baseline.MAX_DATA_CALLS, "data_rows": baseline.MAX_DATA_ROWS,
                            "data_characters": baseline.MAX_TOOL_CHARS, "catalog_characters": MAX_CATALOG_CHARS}
        for case in selected:
            if ledger["estimated_usd"] + baseline.worst_case_cost_usd() > args.budget_usd:
                record["run_note"] = "Stopped before the next case to preserve the cumulative spend cap."
                break
            server.reset_case()
            hooks = baseline.UsageHooks()
            agent = Agent(name="SILO research analyst", model=baseline.MODEL, instructions=INSTRUCTIONS,
                          mcp_servers=[server], mcp_config={"convert_schemas_to_strict": False},
                          model_settings=ModelSettings(max_tokens=baseline.MAX_OUTPUT_TOKENS,
                                                       parallel_tool_calls=False, verbosity="low"))
            item: dict[str, Any] = {"id": case["id"], "question": case["question"], "status": "error"}
            started = time.monotonic()
            try:
                result = await Runner.run(agent, baseline.runtime_question(case), max_turns=baseline.MAX_TURNS,
                                          hooks=hooks, run_config=RunConfig(tracing_disabled=True))
                item["answer"] = str(result.final_output or "")
                item["status"] = "completed" if item["answer"] else "empty_answer"
            except Exception as exc:
                item["error_type"] = type(exc).__name__
            item.update(duration_seconds=round(time.monotonic() - started, 3), tool_events=server.events,
                        usage={"requests": hooks.requests, "input_tokens": hooks.input_tokens, "output_tokens": hooks.output_tokens},
                        estimated_usd=round(hooks.estimated_usd, 6),
                        checks=process_checks(server.events))
            if item["status"] == "error" or not (hooks.input_tokens or hooks.output_tokens):
                item["observed_usage_estimate_usd"] = item["estimated_usd"]
                item["estimated_usd"] = max(item["estimated_usd"], baseline.worst_case_cost_usd())
                item["cost_basis"] = "worst_case_reserve_for_unobserved_cost"
                record["run_note"] = "Stopped after a model error or missing usage; the whole-case reserve is retained for unknown billed cost."
            record["cases"].append(item)
            record["baseline_comparison"] = compare_baseline(record["cases"])
            record["estimated_usd"] = round(sum(c["estimated_usd"] for c in record["cases"]), 6)
            ledger["entries"].append({"run": record["started_at"], "model": baseline.MODEL, "transport": "mcp-v2", "case": case["id"], "estimated_usd": item["estimated_usd"]})
            ledger["estimated_usd"] = round(sum(e["estimated_usd"] for e in ledger["entries"]), 6)
            record["cumulative_estimated_usd"] = ledger["estimated_usd"]
            baseline.SPEND_LEDGER.write_text(json.dumps(ledger, indent=2) + "\n")
            write_results(record)
            print(f"{case['id']}: {item['status']}; estimated ${item['estimated_usd']:.6f}")
            if record["run_note"]:
                break
        write_results(record)
        return 0 if len(record["cases"]) == len(selected) and all(c["status"] == "completed" for c in record["cases"]) else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preflight", action="store_true", help="Read-only MCP checks; no model requests")
    mode.add_argument("--run", action="store_true", help="Paid model requests only after live MCP preflight passes")
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--budget-usd", type=float, default=baseline.DEFAULT_BUDGET_USD)
    args = parser.parse_args(argv)
    try:
        cases = baseline.load_cases()
        ledger = baseline.load_spend_ledger()
        if set(args.case_id or []) - {case["id"] for case in cases}:
            raise ValueError("Unknown case ID")
        selected = [case for case in cases if not args.case_id or case["id"] in args.case_id]
        reserve = len(selected) * baseline.worst_case_cost_usd()
        if not math.isfinite(args.budget_usd) or not 0 < args.budget_usd <= baseline.DEFAULT_BUDGET_USD:
            raise ValueError("Budget must be positive and at most US$20")
        if ledger["estimated_usd"] + reserve > args.budget_usd:
            parser.error(f"Prior spend ${ledger['estimated_usd']:.6f} plus reserve ${reserve:.2f} "
                         f"exceeds the cumulative budget ${args.budget_usd:.2f}")
        if args.run or args.preflight:
            return asyncio.run(run(args, selected, ledger))
        print(f"Validated {len(selected)} cases: prior ${ledger['estimated_usd']:.6f} + reserve ${reserve:.2f} <= ${args.budget_usd:.2f}. No network or model requests.")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(f"Evaluation configuration or preflight failed: {type(exc).__name__}")


if __name__ == "__main__":
    raise SystemExit(main())
