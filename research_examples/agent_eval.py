#!/usr/bin/env python3
"""Run the 12 discovery-first SILO research questions with a bounded agent.

Only each case's ``question`` reaches the model. Expected dispositions and
review notes stay in the local evaluator. The run uses public read-only SILO
SDK methods, and writes a Markdown summary plus a machine-readable record.
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdk"))

from agents import Agent, ModelSettings, RunConfig, RunHooks, Runner, function_tool, set_default_openai_client
from dotenv import dotenv_values
from openai import AsyncOpenAI
from silo_client import SiloClient


MODEL = "gpt-5-mini"
MAX_TURNS = 12
MAX_OUTPUT_TOKENS = 2_000
MAX_CONTEXT_TOKENS = 400_000
USD_PER_M_INPUT = 0.25
USD_PER_M_OUTPUT = 2.00
DEFAULT_BUDGET_USD = 20.00
MAX_DATA_ROWS = 100
MAX_DATA_CALLS = 5
MAX_TOOL_CHARS = 80_000
CASE_FILE = Path(__file__).with_name("eval_cases.json")
JSON_RESULT = Path(__file__).with_name("eval-results.json")
MARKDOWN_RESULT = ROOT / "docs" / "research" / "agent-evaluation-results.md"

# Pricing and context are fixed to this model and were checked against the
# official model page on 2026-09-23. Update these constants if the model or
# prices change: https://developers.openai.com/api/docs/models/gpt-5-mini

INSTRUCTIONS = """You are a careful Brazilian public-markets research analyst.
Start with the SILO catalog, then inspect the available public tools. Check
coverage before treating a missing observation as zero or current. Choose
datasets from discovery, inspect endpoint arguments, and make bounded read
calls. State your identifiers, as-of dates, units, calculation, source
limitations, and whether the result is descriptive. If coverage or a necessary
source is unavailable, give a clearly limited answer. Never invent values or
make causal claims from observational data alone. For a causal question, check
whether the available sources identify the effect; if they do not, explain
the limitation promptly instead of estimating correlation. Use no more than
five substantive data calls. Synthesize a conclusion from bounded evidence,
even when that conclusion is that the evidence is insufficient. Do
not ask for credentials.
"""


def load_cases(path: Path = CASE_FILE) -> list[dict[str, str]]:
    cases = json.loads(path.read_text())["cases"]
    ids = [case["id"] for case in cases]
    if ids != [*(f"Q{i}" for i in range(1, 10)), "L1", "L2", "L3"]:
        raise ValueError("case file must contain Q1-Q9 and L1-L3 in order")
    for case in cases:
        if not case["question"].strip() or case["expected_disposition"] not in {
            "answer_or_bounded_limit", "limitation"
        }:
            raise ValueError(f"invalid evaluator case {case['id']}")
    return cases


def worst_case_cost_usd(turns: int = MAX_TURNS) -> float:
    """Reserve whole-context charges plus 25% for unobserved failure cost."""
    return 1.25 * turns * (
        MAX_CONTEXT_TOKENS * USD_PER_M_INPUT
        + MAX_OUTPUT_TOKENS * USD_PER_M_OUTPUT
    ) / 1_000_000


def actual_cost_usd(input_tokens: int, output_tokens: int) -> float:
    # Cached input, if any, is deliberately charged at the full input rate.
    return (input_tokens * USD_PER_M_INPUT + output_tokens * USD_PER_M_OUTPUT) / 1_000_000


def _json(value: Any) -> str:
    if hasattr(value, "to_dict") and hasattr(value, "columns"):
        value = value.to_dict(orient="records")
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


class SiloTools:
    """Public SDK adapter with discovery gates and inspectable tool records."""

    def __init__(self, client: SiloClient, openapi: dict[str, Any]):
        self.client = client
        self.paths = openapi["paths"]
        self.catalog_seen = False
        self.tools_seen = False
        self.data_calls = 0
        self.events: list[dict[str, Any]] = []

    def _record(self, name: str, args: dict[str, Any], call: Callable[[], str]) -> str:
        started = time.monotonic()
        event: dict[str, Any] = {"name": name, "arguments": args}
        try:
            result = call()
            event["result_characters"] = len(result)
            if result.startswith('{"error"'):
                event["tool_error"] = True
            return result
        except Exception as exc:
            # Tool errors are returned to the agent. Never include headers,
            # request objects, environment variables, or a secret value.
            event["error_type"] = type(exc).__name__
            return _json({"error": type(exc).__name__, "advice": "Narrow the request or explain the unavailable source."})
        finally:
            event["duration_seconds"] = round(time.monotonic() - started, 3)
            self.events.append(event)

    def as_agent_tools(self) -> list[Any]:
        @function_tool
        def silo_catalog() -> str:
            """Read SILO's live catalog of metrics, constraints, and limits."""

            def fetch() -> str:
                result = _json(self.client.catalog())
                if len(result) > MAX_TOOL_CHARS:
                    raise ValueError("catalog exceeds evaluation tool size limit")
                self.catalog_seen = True
                return result

            return self._record("silo_catalog", {}, fetch)

        @function_tool
        def silo_tools(query: str) -> str:
            """Search the published API tool list by topic or endpoint name; an empty query lists all."""

            def search() -> str:
                if not self.catalog_seen:
                    return _json({"error": "Call silo_catalog first."})
                term = query.strip().lower()
                matches = []
                for path, operations in self.paths.items():
                    operation = operations.get("post") or operations.get("get") or {}
                    name = path.rsplit("/", 1)[-1]
                    description = operation.get("description") or ""
                    if term and term not in (name + " " + description).lower():
                        continue
                    method = getattr(self.client, name, None)
                    if path.startswith("/rpc/") and not callable(method):
                        continue
                    matches.append({
                        "endpoint": name,
                        "kind": "rpc" if path.startswith("/rpc/") else "view",
                        "description": description[:1_200 if term else 150],
                        "sdk_signature": str(inspect.signature(method)) if callable(method) else "view(name, limit, filters)",
                    })
                self.tools_seen = True
                return _json(matches[:41])

            return self._record("silo_tools", {"query": query}, search)

        @function_tool
        def silo_call(endpoint: str, arguments_json: str) -> str:
            """Call one published read-only SILO endpoint with JSON keyword arguments."""

            def invoke() -> str:
                if not (self.catalog_seen and self.tools_seen):
                    return _json({"error": "Call silo_catalog and silo_tools before querying data."})
                if endpoint not in {"coverage", "metric_coverage"}:
                    if self.data_calls >= MAX_DATA_CALLS:
                        return _json({"error": "Data-call limit reached. Answer from the evidence already collected or explain the limitation."})
                    self.data_calls += 1
                arguments = json.loads(arguments_json)
                if not isinstance(arguments, dict):
                    raise ValueError("arguments_json must be a JSON object")
                rpc_path = f"/rpc/{endpoint}"
                if rpc_path in self.paths and endpoint != "catalog":
                    method = getattr(self.client, endpoint, None)
                    if not callable(method):
                        raise ValueError("endpoint is not wrapped by the public SDK")
                    inspect.signature(method).bind(**arguments)
                    value = method(**arguments)
                elif f"/{endpoint}" in self.paths:
                    limit = arguments.pop("limit", None)
                    if not isinstance(limit, int) or not 1 <= limit <= MAX_DATA_ROWS:
                        raise ValueError("view reads require 1 <= limit <= 100")
                    value = self.client.view(endpoint, limit=limit, **arguments)
                else:
                    raise ValueError("endpoint is not in the published API")
                if isinstance(value, list) and len(value) > MAX_DATA_ROWS:
                    raise ValueError("more than 100 rows; narrow the source query")
                result = _json(value)
                if len(result) > MAX_TOOL_CHARS:
                    raise ValueError("result too large; narrow the source query")
                return result

            return self._record("silo_call", {"endpoint": endpoint, "arguments_json": arguments_json}, invoke)

        return [silo_catalog, silo_tools, silo_call]


class UsageHooks(RunHooks):
    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.requests = 0

    async def on_llm_end(self, context: Any, agent: Any, response: Any) -> None:
        self.requests += 1
        self.input_tokens += response.usage.input_tokens
        self.output_tokens += response.usage.output_tokens


def process_checks(events: list[dict[str, Any]], expected: str) -> dict[str, Any]:
    catalog_at = next((i for i, e in enumerate(events) if e["name"] == "silo_catalog" and not e.get("error_type") and not e.get("tool_error")), None)
    tools_at = next((i for i, e in enumerate(events) if e["name"] == "silo_tools" and not e.get("error_type") and not e.get("tool_error")), None)
    data_at = [i for i, event in enumerate(events) if event["name"] == "silo_call"]
    coverage_attempted = any(
        event["name"] == "silo_call" and event["arguments"].get("endpoint") == "coverage"
        for event in events
    )
    discovery_before_data = (
        catalog_at is not None and tools_at is not None
        and (not data_at or catalog_at < min(data_at) and tools_at < min(data_at))
    )
    return {
        "catalog_discovered": catalog_at is not None,
        "tools_inspected": tools_at is not None,
        "discovery_before_data": discovery_before_data,
        "coverage_attempted": coverage_attempted,
        "data_calls": sum(event["name"] == "silo_call" and event["arguments"].get("endpoint") != "coverage" for event in events),
        "expected_disposition": expected,
        "substantive_accuracy": "manual_review_required",
    }


def _published_demo_access() -> tuple[str, str]:
    text = (ROOT / "api-docs" / "agents.mdx").read_text()
    url = re.search(r'export SILO_URL="(https://[^"]+)"', text)
    key = re.search(r'export SILO_ANON_KEY="([^"]+)"', text)
    if not url or not key:
        raise RuntimeError("published demo Data API access is absent from api-docs/agents.mdx")
    return url.group(1).removesuffix("/rest/v1"), key.group(1)


def safe_error_detail(exc: Exception) -> str:
    detail = str(exc)
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        detail = detail.replace(key, "[redacted]")
    return re.sub(r"sk-[A-Za-z0-9_-]+", "[redacted]", detail)[:500]


def load_local_openai_key() -> bool:
    """Use the ignored file only when the inherited variable is unset/empty."""
    if os.environ.get("OPENAI_API_KEY"):
        return True
    key = dotenv_values(ROOT / ".env").get("OPENAI_API_KEY")
    if key:
        os.environ["OPENAI_API_KEY"] = key
    return bool(key)


def _summary_md(record: dict[str, Any]) -> str:
    rows = []
    for case in record["cases"]:
        checks = case.get("checks", {})
        rows.append(
            f"| {case['id']} | {case['status']} | "
            f"{'yes' if checks.get('discovery_before_data') else 'no'} | "
            f"{checks.get('data_calls', 0)} | "
            f"{case.get('duration_seconds', 0):.1f}s | "
            f"${case.get('estimated_usd', 0):.4f} |"
        )
    lines = [
        "# SILO research agent evaluation results", "",
        f"Run: {record['started_at']} · Model: `{record['model']}` · Cases: {len(record['cases'])}/12", "",
        f"Estimated model spend: **${record['estimated_usd']:.4f}** of ${record['budget_usd']:.2f} cap.", "",
        "This is a live-agent process record. Numeric and analytical correctness requires",
        "manual review against the evaluator-private references and source rows.", "",
        "| Case | Run status | Discovery before data | Data calls | Latency | Est. spend |",
        "| --- | --- | --- | ---: | ---: | ---: |", *rows, "",
        "## Case notes", "",
    ]
    for case in record["cases"]:
        checks = case.get("checks", {})
        lines += [f"### {case['id']}", "", f"**Question:** {case['question']}", "",
                  f"**Outcome:** {case['status']}; catalog discovery: {checks.get('catalog_discovered', False)}; "
                  f"tool inspection: {checks.get('tools_inspected', False)}; "
                  f"coverage attempted: {checks.get('coverage_attempted', False)}.", ""]
        answer = case.get("answer") or case.get("error_type") or "No agent answer recorded."
        lines += ["**Answer excerpt:**", "", "> " + str(answer).replace("\n", "\n> ")[:1_500], ""]
    if record.get("run_note"):
        lines += ["## Run limitation", "", record["run_note"], ""]
    return "\n".join(lines)


def write_results(record: dict[str, Any]) -> None:
    JSON_RESULT.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    MARKDOWN_RESULT.write_text(_summary_md(record))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Make paid OpenAI requests; default validates configuration only")
    parser.add_argument("--public-demo", action="store_true", help="Use the read-only publishable testing access documented in api-docs/agents.mdx")
    parser.add_argument("--case-id", action="append", help="Run only the specified case ID; may be repeated")
    parser.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD)
    args = parser.parse_args()

    all_cases = load_cases()
    selected = [case for case in all_cases if not args.case_id or case["id"] in args.case_id]
    if not selected or args.budget_usd <= 0:
        parser.error("select valid cases and a positive budget")
    reserved = len(selected) * worst_case_cost_usd()
    if reserved > args.budget_usd:
        parser.error(f"worst-case reserve ${reserved:.2f} exceeds budget ${args.budget_usd:.2f}")
    if not args.run:
        print(f"Validated {len(selected)} cases; conservative maximum ${reserved:.2f} < ${args.budget_usd:.2f}. Use --run for live calls.")
        return 0

    if not load_local_openai_key():
        parser.error("OPENAI_API_KEY is required in the environment or ignored .env")
    # A failed request is never silently retried: retries could bill again
    # without contributing usage to the local spend ledger.
    set_default_openai_client(AsyncOpenAI(max_retries=0, timeout=60), use_for_tracing=False)
    silo_url, silo_key = _published_demo_access() if args.public_demo else (
        os.environ.get("SILO_URL", ""), os.environ.get("SILO_ANON_KEY", "")
    )
    if not silo_url or not silo_key:
        parser.error("set SILO_URL and SILO_ANON_KEY or pass --public-demo")

    record: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "model": MODEL, "budget_usd": args.budget_usd, "estimated_usd": 0.0,
        "price_basis_usd_per_million": {"input": USD_PER_M_INPUT, "output": USD_PER_M_OUTPUT},
        "cases": [], "run_note": "",
    }
    openapi = json.loads((ROOT / "openapi.json").read_text())
    try:
        with SiloClient(url=silo_url, key=silo_key, timeout=8, retries=0) as client:
            # A failed catalog is a hard preflight failure: no paid calls follow.
            client.catalog()
            for case in selected:
                if record["estimated_usd"] + worst_case_cost_usd() > args.budget_usd:
                    record["run_note"] = "Stopped before the next case to preserve the spend cap."
                    break
                tools = SiloTools(client, openapi)
                hooks = UsageHooks()
                agent = Agent(
                    name="SILO research analyst", model=MODEL,
                    instructions=INSTRUCTIONS, tools=tools.as_agent_tools(),
                    model_settings=ModelSettings(max_tokens=MAX_OUTPUT_TOKENS, parallel_tool_calls=False, verbosity="low"),
                )
                started = time.monotonic()
                item: dict[str, Any] = {"id": case["id"], "question": case["question"], "status": "error"}
                try:
                    result = Runner.run_sync(
                        agent, case["question"], max_turns=MAX_TURNS,
                        hooks=hooks, run_config=RunConfig(tracing_disabled=True),
                    )
                    item["answer"] = str(result.final_output or "")
                    item["status"] = "completed" if item["answer"] else "empty_answer"
                except Exception as exc:
                    item["error_type"] = type(exc).__name__
                    item["error_detail"] = safe_error_detail(exc)
                item["duration_seconds"] = round(time.monotonic() - started, 3)
                item["usage"] = {"requests": hooks.requests, "input_tokens": hooks.input_tokens,
                                 "output_tokens": hooks.output_tokens}
                item["estimated_usd"] = round(actual_cost_usd(hooks.input_tokens, hooks.output_tokens), 6)
                item["tool_events"] = tools.events
                item["checks"] = process_checks(tools.events, case["expected_disposition"])
                record["cases"].append(item)
                record["estimated_usd"] = round(sum(c["estimated_usd"] for c in record["cases"]), 6)
                write_results(record)
                print(f"{case['id']}: {item['status']}, discovery={item['checks']['discovery_before_data']}, cost=${item['estimated_usd']:.4f}")
                if hooks.requests and not (hooks.input_tokens or hooks.output_tokens):
                    record["run_note"] = "Usage unavailable after a billed request; stopped to protect the budget."
                    break
    except Exception as exc:
        record["run_note"] = f"Stopped before or during agent cases: {type(exc).__name__}."
    write_results(record)
    return 0 if len(record["cases"]) == len(selected) and all(c["status"] == "completed" for c in record["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
