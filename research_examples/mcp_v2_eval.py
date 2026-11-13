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
# The live v2 catalog is about 129 KB. Below 140,000 characters it stays under
# the 70,000-token input cap at o200k rates (about 4.4 characters per token for
# this JSON); with the 14 tool schemas (about 17,500 tokens) the next request
# may still be refused by baseline.InputCapFilter, which is recorded, not trimmed.
MAX_CATALOG_CHARS = 140_000
PRO_MODEL = "gpt-5-mini"
PRO_INPUT_CAP = 120_000
PRO_PRICE_BASIS = {"input": 0.25, "output": 2.0, "accounting": "uncached standard rates"}
PRO_RESULTS = Path(__file__).with_name("eval-v2-pro-gpt-5-mini-120k-results.json")
PRO_REPORT = baseline.ROOT / "docs/reference/research/agent-evaluation-v2-pro-gpt-5-mini-120k-results.md"


def pro_cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * PRO_PRICE_BASIS["input"] + output_tokens * PRO_PRICE_BASIS["output"]) / 1_000_000


def case_reserve(pro: bool) -> float:
    if not pro:
        return baseline.worst_case_cost_usd()
    return round(1.25 * baseline.MAX_TURNS * pro_cost(PRO_INPUT_CAP, baseline.MAX_OUTPUT_TOKENS), 6)


class ProUsageHooks(baseline.UsageHooks):
    async def on_llm_end(self, context, agent, response):
        await super().on_llm_end(context, agent, response)
        self.estimated_usd = pro_cost(self.input_tokens, self.output_tokens)


class ProInputCap:
    def __init__(self, client, manifest):
        self.client = client
        self.tools = [{"type": "function", "name": t["name"], "description": t["description"],
                       "parameters": t["inputSchema"], "strict": False} for t in manifest]
        self.checked = 0
        self.largest = 0

    async def __call__(self, data):
        model_data = data.model_data
        count = await self.client.responses.input_tokens.count(
            model=PRO_MODEL, instructions=model_data.instructions or "",
            input=model_data.input, tools=self.tools,
        )
        self.checked += 1
        self.largest = max(self.largest, count.input_tokens)
        if count.input_tokens > PRO_INPUT_CAP:
            raise baseline.ContextCapExceeded(
                f"Counted {count.input_tokens} tokens, above the {PRO_INPUT_CAP} token cap."
            )
        return model_data

    def summary(self):
        return {"cap_tokens": PRO_INPUT_CAP, "estimator": "responses.input_tokens",
                "requests_checked": self.checked, "largest_estimate": self.largest}

EXPECTED_TOOLS = {f"silo_{name}" for name in (
    "search", "prices", "statements", "funds", "fidc", "derivatives", "curves",
    "macro", "positioning", "events", "screens", "panel", "portfolio", "coverage",
)}
INSTRUCTIONS = baseline.INSTRUCTIONS.replace(
    "Start with the SILO catalog, then inspect the available public tools.",
    "The tools supplied here are the live MCP v2 schemas. Start with the SILO "
    "catalog using silo_coverage with kind=catalog, then inspect the available public tools.",
) + """
Use the catalog to choose evidence. For issuer-specific claims, retrieve actual
filed rows and cite them. Prefer narrow dates, a small page and relevant account
filters; follow cursors before claiming completeness. For forecasts, distinguish
survey dates from target horizons and use matched survey windows. Check arithmetic
and group membership before reporting. If the data cannot identify a causal
effect, state the missing design and finish early. Give a bounded final answer
within the available calls, without asking for permission to continue.
"""
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

    def __init__(self, *, require_pro: bool = False, data_call_limit: int = baseline.MAX_DATA_CALLS) -> None:
        self.require_pro = require_pro
        self.data_call_limit = data_call_limit
        self.tier_failed = False
        token = os.environ.get("SILO_INTEGRATION_KEY" if require_pro else "SILO_USER_JWT", "")
        if require_pro and not token:
            raise ValueError("SILO_INTEGRATION_KEY is required for the Pro evaluation")
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
            if self.tier_failed:
                raise ValueError("Evaluation stopped receiving Pro responses")
            if tool_name not in EXPECTED_TOOLS:
                raise ValueError("Tool is not in the evaluation manifest")
            if tool_name != "silo_coverage":
                if not self.catalog_seen:
                    raise ValueError("Read silo_coverage with kind=catalog before substantive data")
                if self.data_calls >= self.data_call_limit:
                    raise ValueError("Data-call cap reached; synthesize the evidence already collected")
                self.data_calls += 1
            # Anonymous access allows ten calls/minute. Keep one shared cadence across cases.
            await asyncio.sleep(max(0, 6.1 - (time.monotonic() - self.last_call)))
            self.last_call = time.monotonic()
            event["network_call"] = True
            result = await super().call_tool(tool_name, arguments, meta)
            value = envelope(result, catalog=tool_name == "silo_coverage" and event["arguments"].get("kind") == "catalog")
            event["tier"] = value["meta"].get("tier")
            if self.require_pro and event["tier"] != "pro":
                self.tier_failed = True
                raise ValueError("MCP data response did not report Pro access")
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
            if isinstance(exc, baseline.ToolResultLimitError):
                message += ". Retry with a smaller limit or narrower date window."
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
            checks.append({"tool": name, "status": "passed", "rows": len(value["data"]),
                           "tier": value["meta"].get("tier")})
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
    path = PRO_RESULTS if record.get("access") == "pro" else JSON_RESULT
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    shown_at = datetime.fromisoformat(record["started_at"]).astimezone(ZoneInfo("America/Sao_Paulo"))
    lines = ["# MCP v2 research evaluation", "", f"Run: {shown_at.isoformat()} (Brasília). Model: {record['model']}.",
             ("The model matches the historical v1 and previous Pro runs. Tool descriptions and input limits differ."
              if record.get("access") == "pro" else
              "Same questions as the historical gpt-5-mini baseline, with a changed model. Differences reflect the full run configuration."),
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
    path = PRO_REPORT if record.get("access") == "pro" else MARKDOWN_RESULT
    path.write_text("\n".join(lines))


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
             "v2_technical_classification": "mcp_tool_error" if case["status"] not in {"error", "context_cap_reached"} and any(e.get("tool_error") for e in case["tool_events"])
             else baseline.technical_classification(case),
             "v2_rubric_pass": None} for case in cases]


def save_spend(path: Path, ledger: dict[str, Any]) -> None:
    ledger["estimated_usd"] = round(sum(e["estimated_usd"] for e in ledger["entries"]), 6)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(ledger, indent=2) + "\n")
    temporary.replace(path)


async def run(args, selected, ledger) -> int:
    compare_baseline([])  # Validate evaluator-only baseline evidence before any paid request.
    pro = getattr(args, "pro", False)
    model = PRO_MODEL if pro else baseline.MODEL
    follow_up = getattr(args, "follow_up", False)
    data_call_limit = 8 if follow_up else baseline.MAX_DATA_CALLS
    instructions = INSTRUCTIONS.replace("five substantive data calls", "eight substantive data calls") if follow_up else INSTRUCTIONS
    reserve = case_reserve(pro)
    ledger_path = getattr(args, "spend_ledger", None) or baseline.SPEND_LEDGER
    async with (BoundedMCP(require_pro=True, data_call_limit=data_call_limit) if pro else BoundedMCP()) as server:
        report = await preflight(server)
        print(json.dumps(report, indent=2))
        if report["status"] != "passed" or not args.run:
            return 0 if report["status"] == "passed" else 1
        if not baseline.load_local_openai_key():
            raise ValueError("OPENAI_API_KEY is required in the environment or ignored .env")
        client = AsyncOpenAI(max_retries=0, timeout=60)
        if pro:
            await client.models.retrieve(model)
        set_default_openai_client(client, use_for_tracing=False)
        record = {"started_at": datetime.now(timezone.utc).isoformat(), "transport": "mcp-v2",
                  "base_url": MCP_URL, "access": "pro" if pro else ("signed_in" if os.environ.get("SILO_USER_JWT") else "anonymous"),
                  "model": model, "budget_usd": args.budget_usd,
                  "price_basis_usd_per_million": PRO_PRICE_BASIS if pro else baseline.PRICE_BASIS,
                  # Resolved before any paid request, so a failed tokenizer load bills nothing.
                  "input_cap": {"tokens": PRO_INPUT_CAP if pro else baseline.MAX_CONTEXT_TOKENS,
                                "estimator": "responses.input_tokens" if pro else baseline.token_estimator()},
                  "estimated_usd": 0.0, "cumulative_estimated_usd": ledger["estimated_usd"],
                  "preflight": report, "mcp_tools": server.manifest, "cases": [], "baseline_comparison": [], "run_note": ""}
        if pro and not PRO_RESULTS.exists():
            write_results(record)
        if pro and PRO_RESULTS.exists():
            previous = json.loads(PRO_RESULTS.read_text())
            if previous.get("access") != "pro" or previous.get("model") != model:
                raise ValueError("Existing Pro evaluation record does not match this profile")
            recorded_ids = {item["id"] for item in previous["cases"]}
            ledger_ids = {entry["case"] for entry in ledger["entries"] if entry.get("run") == previous["started_at"]}
            if recorded_ids != ledger_ids:
                raise ValueError("Existing Pro evaluation record and ledger do not agree")
            selected = [case for case in selected if case["id"] not in recorded_ids]
            record.update(previous, preflight=report, run_note="")
        record["limits"] = {"data_calls": data_call_limit, "data_rows": baseline.MAX_DATA_ROWS,
                            "data_characters": baseline.MAX_TOOL_CHARS, "catalog_characters": MAX_CATALOG_CHARS}
        for case in selected:
            if ledger["estimated_usd"] + reserve > args.budget_usd:
                record["run_note"] = "Stopped before the next case to preserve the cumulative spend cap."
                break
            if pro and server.tier_failed:
                record["run_note"] = "Stopped after an MCP response failed to confirm Pro access."
                break
            server.reset_case()
            hooks = ProUsageHooks() if pro else baseline.UsageHooks()
            agent = Agent(name="SILO research analyst", model=model, instructions=instructions,
                          mcp_servers=[server], mcp_config={"convert_schemas_to_strict": False},
                          model_settings=ModelSettings(max_tokens=baseline.MAX_OUTPUT_TOKENS,
                                                       parallel_tool_calls=False, verbosity="low",
                                                       reasoning={"effort": "low"} if follow_up else None))
            item: dict[str, Any] = {"id": case["id"], "question": case["question"], "status": "error"}
            cap = ProInputCap(client, server.manifest) if pro else baseline.InputCapFilter()
            started = time.monotonic()
            entry = {"run": record["started_at"], "model": model, "transport": "mcp-v2",
                     "case": case["id"], "estimated_usd": reserve}
            if pro:
                ledger["entries"].append(entry)
                save_spend(ledger_path, ledger)
            try:
                result = await Runner.run(agent, baseline.runtime_question(case), max_turns=baseline.MAX_TURNS, hooks=hooks,
                                          run_config=RunConfig(tracing_disabled=True, call_model_input_filter=cap))
                item["answer"] = str(result.final_output or "")
                item["status"] = "completed" if item["answer"] else "empty_answer"
            except baseline.ContextCapExceeded as exc:
                baseline.record_cap_refusal(item, exc)
            except Exception as exc:
                item["error_type"] = type(exc).__name__
            item.update(duration_seconds=round(time.monotonic() - started, 3), tool_events=server.events,
                        usage={"requests": hooks.requests, "input_tokens": hooks.input_tokens, "output_tokens": hooks.output_tokens},
                        input_cap=cap.summary(), estimated_usd=round(hooks.estimated_usd, 6),
                        checks=process_checks(server.events))
            # A cap refusal sent nothing, so every billed request was observed.
            if item["status"] == "error" or (item["status"] != "context_cap_reached"
                                             and not (hooks.input_tokens or hooks.output_tokens)):
                item["observed_usage_estimate_usd"] = item["estimated_usd"]
                item["estimated_usd"] = max(item["estimated_usd"], reserve)
                item["cost_basis"] = "worst_case_reserve_for_unobserved_cost"
                record["run_note"] = "Stopped after a model error or missing usage; the whole-case reserve is retained for unknown billed cost."
            record["cases"].append(item)
            record["baseline_comparison"] = compare_baseline(record["cases"])
            record["estimated_usd"] = round(sum(c["estimated_usd"] for c in record["cases"]), 6)
            entry["estimated_usd"] = item["estimated_usd"]
            if not pro:
                ledger["entries"].append(entry)
            save_spend(ledger_path, ledger)
            record["cumulative_estimated_usd"] = ledger["estimated_usd"]
            write_results(record)
            print(f"{case['id']}: {item['status']}; estimated ${item['estimated_usd']:.6f}")
            if record["run_note"] and not pro:
                break
        write_results(record)
        return 0 if all(c["status"] == "completed" for c in record["cases"]) and not record["run_note"] else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preflight", action="store_true", help="Read-only MCP checks; no model requests")
    mode.add_argument("--run", action="store_true", help="Paid model requests only after live MCP preflight passes")
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--pro", action="store_true", help="Require the integration key and run GPT-5 mini at 120k input tokens")
    parser.add_argument("--follow-up", action="store_true", help="Use eight data calls and low reasoning for a targeted Pro rerun")
    parser.add_argument("--spend-ledger", type=Path, help="Reconciled cumulative ledger for the Pro run")
    parser.add_argument("--budget-usd", type=float, default=baseline.DEFAULT_BUDGET_USD)
    args = parser.parse_args(argv)
    try:
        if args.follow_up and (not args.pro or not args.case_id):
            parser.error("--follow-up requires --pro and explicit --case-id selections")
        cases = baseline.load_cases()
        if args.pro and (not args.spend_ledger or args.budget_usd > 10):
            parser.error("Pro requires a reconciled --spend-ledger and --budget-usd of at most 10")
        ledger = baseline.load_spend_ledger(args.spend_ledger) if args.spend_ledger else baseline.load_spend_ledger()
        if set(args.case_id or []) - {case["id"] for case in cases}:
            raise ValueError("Unknown case ID")
        selected = [case for case in cases if not args.case_id or case["id"] in args.case_id]
        completed = set()
        if args.pro and PRO_RESULTS.exists():
            completed = {item["id"] for item in json.loads(PRO_RESULTS.read_text())["cases"]}
        reserve = sum(case["id"] not in completed for case in selected) * case_reserve(args.pro)
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
