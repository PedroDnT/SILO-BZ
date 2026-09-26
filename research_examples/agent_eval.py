#!/usr/bin/env python3
"""Run the 12 discovery-first SILO research questions with a bounded agent.

Only each case's ``question`` reaches the model. Expected dispositions and
review notes stay in the local evaluator. The run uses public read-only SILO
SDK methods, and writes a Markdown summary plus a machine-readable record.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdk"))

from agents import Agent, ModelSettings, RunConfig, RunHooks, Runner, function_tool, set_default_openai_client
from dotenv import dotenv_values
from openai import AsyncOpenAI
from silo_client import SiloClient, SiloError


MODEL = "gpt-5-mini"
MAX_TURNS = 12
MAX_OUTPUT_TOKENS = 2_000
MAX_CONTEXT_TOKENS = 400_000
USD_PER_M_INPUT = 0.25
USD_PER_M_OUTPUT = 2.00
DEFAULT_BUDGET_USD = 20.00
REQUIRED_RESEARCH_RPCS = ("financial_statement_history", "fii_property_history", "focus_expectations")
MAX_DATA_ROWS = 100
MAX_DATA_CALLS = 5
MAX_TOOL_CHARS = 80_000
CASE_FILE = Path(__file__).with_name("eval_cases.json")
JSON_RESULT = Path(__file__).with_name("eval-results.json")
SPEND_LEDGER = Path(__file__).with_name("eval-spend.json")
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


def runtime_question(case: dict[str, str]) -> str:
    """Keep every evaluator-only field out of the model input."""
    return case["question"]


def worst_case_cost_usd(turns: int = MAX_TURNS) -> float:
    """Reserve whole-context charges plus 25% for unobserved failure cost."""
    return 1.25 * turns * (
        MAX_CONTEXT_TOKENS * USD_PER_M_INPUT
        + MAX_OUTPUT_TOKENS * USD_PER_M_OUTPUT
    ) / 1_000_000


def actual_cost_usd(input_tokens: int, output_tokens: int) -> float:
    # Cached input, if any, is deliberately charged at the full input rate.
    return (input_tokens * USD_PER_M_INPUT + output_tokens * USD_PER_M_OUTPUT) / 1_000_000


def load_spend_ledger() -> dict[str, Any]:
    ledger = json.loads(SPEND_LEDGER.read_text())
    costs = [entry["estimated_usd"] for entry in ledger["entries"]]
    total = ledger["estimated_usd"]
    if (any(type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0 for cost in costs)
            or type(total) not in (int, float) or not math.isfinite(total) or total < 0
            or not math.isclose(total, sum(costs), abs_tol=0.000001)):
        raise ValueError("spend ledger must contain consistent nonnegative observed estimates")
    return ledger


def validate_preflight_report(path: Path, base_url: str, now: datetime | None = None) -> None:
    """Require fresh, read-only live proof for all research RPCs before billing."""
    try:
        report = json.loads(path.read_text())
        if not isinstance(report, dict):
            raise ValueError("preflight report must be a JSON object")
        checked_at = datetime.fromisoformat(report["checked_at"].replace("Z", "+00:00"))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError("a readable live preflight report with checked_at is required") from exc
    clock = now or datetime.now(timezone.utc)
    age_seconds = (clock - checked_at).total_seconds() if checked_at.tzinfo else float("inf")
    if not 0 <= age_seconds <= 6 * 3600:
        raise ValueError("live preflight report must be no more than six hours old")
    if report.get("base_url", "").rstrip("/") != base_url.rstrip("/") or report.get("read_only") is not True:
        raise ValueError("live preflight must match this read-only SILO API")
    endpoints = report.get("endpoints", {})
    if not isinstance(endpoints, dict):
        endpoints = {}
    if report.get("status") != "passed" or any(
        not isinstance(endpoints.get(name), dict) or endpoints[name].get("status") != "passed"
        for name in REQUIRED_RESEARCH_RPCS
    ):
        raise ValueError("all three research RPCs must pass live preflight before paid evaluation")


def _json(value: Any) -> str:
    if hasattr(value, "to_dict") and hasattr(value, "columns"):
        value = value.to_dict(orient="records")
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


class ArgumentValidationError(ValueError):
    """A model argument did not match the published endpoint contract."""


class ToolResultLimitError(ValueError):
    """A public result exceeded the evaluator's explicit tool-size bound."""


def _sdk_arg(api_name: str) -> str:
    return {"p_from": "start", "p_to": "end"}.get(api_name, api_name.removeprefix("p_"))


def endpoint_arguments(openapi: dict[str, Any], endpoint: str) -> list[dict[str, Any]]:
    """Expose callable SDK argument names with types from the published OpenAPI."""
    path = f"/rpc/{endpoint}"
    if path in openapi["paths"]:
        operation = openapi["paths"][path]["post"]
        schema = operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
        method = getattr(SiloClient, endpoint, None)
        supported = set(inspect.signature(method).parameters) - {"self"} if callable(method) else set()
        return [{
            "name": name, "type": spec.get("type", "string"),
            "required": api_name in schema.get("required", []),
            **{key: spec[key] for key in ("format", "items", "enum", "minimum", "maximum", "minItems", "maxItems") if key in spec},
            **({"examples": spec["examples"]} if "examples" in spec else {}),
            **({"description": spec["description"][:160]} if "description" in spec else {}),
        } for api_name, spec in schema.get("properties", {}).items()
            if (name := _sdk_arg(api_name)) in supported]
    operation = openapi["paths"].get(f"/{endpoint}", {}).get("get", {})
    return [{
        "name": item["name"], "type": item.get("schema", {}).get("type", "string"),
        "required": item["name"] == "limit", "description": item.get("description", "")[:160],
        **{key: item["schema"][key] for key in ("format", "items", "enum", "minimum", "maximum") if key in item.get("schema", {})},
    } for item in operation.get("parameters", []) if item.get("in") == "query"]


def _validate_value(name: str, spec: dict[str, Any], value: Any) -> None:
    types = spec.get("type", "string")
    if isinstance(types, str):
        types = [types]
    if value is None and "null" in types:
        return
    matches = any((kind == "string" and isinstance(value, str)) or
                  (kind == "integer" and type(value) is int) or
                  (kind == "number" and type(value) in (int, float) and math.isfinite(value)) or
                  (kind == "boolean" and type(value) is bool) or
                  (kind == "array" and isinstance(value, list)) for kind in types)
    if not matches:
        raise ArgumentValidationError(f"{name} must be {' or '.join(types)}")
    if "enum" in spec and value not in spec["enum"]:
        raise ArgumentValidationError(f"{name} must be one of the published enum values")
    if type(value) in (int, float):
        if "minimum" in spec and value < spec["minimum"]:
            raise ArgumentValidationError(f"{name} must be at least {spec['minimum']}")
        if "maximum" in spec and value > spec["maximum"]:
            raise ArgumentValidationError(f"{name} must be at most {spec['maximum']}")
    if isinstance(value, list):
        if "minItems" in spec and len(value) < spec["minItems"]:
            raise ArgumentValidationError(f"{name} has fewer items than the published minimum")
        if "maxItems" in spec and len(value) > spec["maxItems"]:
            raise ArgumentValidationError(f"{name} exceeds the published item limit")
        if "items" in spec:
            for item in value:
                _validate_value(f"{name} item", spec["items"], item)
    if spec.get("format") == "date":
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError("date shape")
            date.fromisoformat(value)
        except (ValueError, TypeError) as exc:
            raise ArgumentValidationError(f"{name} must be an ISO date (YYYY-MM-DD)") from exc


def validate_arguments(specs: list[dict[str, Any]], arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ArgumentValidationError("arguments_json must be a JSON object")
    known = {spec["name"]: spec for spec in specs}
    unknown = sorted(set(arguments) - set(known))
    missing = sorted(name for name, spec in known.items() if spec["required"] and name not in arguments)
    if unknown:
        raise ArgumentValidationError(f"Unknown argument(s): {', '.join(unknown)}. Allowed: {', '.join(known)}")
    if missing:
        raise ArgumentValidationError(f"Missing required argument(s): {', '.join(missing)}")
    for name, value in arguments.items():
        _validate_value(name, known[name], value)
    return arguments


def safe_tool_error(exc: Exception, secrets: tuple[str | None, ...] = ()) -> dict[str, Any]:
    if isinstance(exc, ArgumentValidationError):
        return {"error": "InvalidArguments", "message": str(exc)[:300]}
    if isinstance(exc, ToolResultLimitError):
        return {"error": "ToolResultLimit", "message": str(exc)[:300]}
    if isinstance(exc, SiloError):
        try:
            body = json.loads(exc.body)
        except (ValueError, TypeError):
            body = {}
        if not isinstance(body, dict):
            body = {}
        def redact(value: Any) -> str:
            message = str(value)
            for secret in (*secrets, os.environ.get("OPENAI_API_KEY"), os.environ.get("SILO_ANON_KEY")):
                if secret:
                    message = message.replace(secret, "[redacted]")
            message = re.sub(r"sk-[A-Za-z0-9_-]+", "[redacted]", message)
            message = re.sub(r"(?i)Bearer\s+\S+", "Bearer [redacted]", message)
            message = re.sub(r"(?i)(?:apikey|authorization|token)\s*[:=]\s*\S+", "[redacted credential]", message)
            return re.sub(r"https?://\S+", "[redacted URL]", message)[:300]

        code = str(body.get("code") or "")
        return {"error": type(exc).__name__, "status": exc.status,
                "code": code if re.fullmatch(r"[A-Z0-9_]{1,40}", code) else "",
                "message": redact(body.get("message") or "API request failed"),
                **({"hint": redact(body["hint"])} if body.get("hint") else {})}
    return {"error": type(exc).__name__, "message": "The request failed; inspect the endpoint arguments or availability."}


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
            event["result_sha256"] = hashlib.sha256(result.encode()).hexdigest()
            if name == "silo_call":
                # Public read-only response rows are required for independent
                # numeric review; each result is already capped above.
                event["result_json"] = result
                parsed = json.loads(result)
                if isinstance(parsed, list):
                    event["returned_rows"] = len(parsed)
            if result.startswith('{"error"'):
                event["tool_error"] = True
            return result
        except Exception as exc:
            # Only a bounded, redacted API status/code/message reaches the model.
            event["error_type"] = type(exc).__name__
            error = safe_tool_error(exc, (getattr(self.client, "_key", None),))
            event["error"] = error
            return _json(error)
        finally:
            event["duration_seconds"] = round(time.monotonic() - started, 3)
            self.events.append(event)

    def discover_tools(self, query: str) -> str:
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
                "arguments": endpoint_arguments({"paths": self.paths}, name),
            })
        result = _json(matches)
        if len(result) > MAX_TOOL_CHARS:
            raise ToolResultLimitError("The complete tool list is too large; search a topic or endpoint name with silo_tools.")
        self.tools_seen = True
        return result

    def invoke_endpoint(self, endpoint: str, arguments_json: str) -> str:
        if not (self.catalog_seen and self.tools_seen):
            return _json({"error": "Call silo_catalog and silo_tools before querying data."})
        rpc_path = f"/rpc/{endpoint}"
        if rpc_path not in self.paths and f"/{endpoint}" not in self.paths:
            raise ArgumentValidationError("endpoint is not in the published API; call silo_tools")
        try:
            arguments = json.loads(arguments_json)
        except json.JSONDecodeError as exc:
            raise ArgumentValidationError("arguments_json must contain valid JSON") from exc
        specs = endpoint_arguments({"paths": self.paths}, endpoint)
        arguments = validate_arguments(specs, arguments)
        if f"/{endpoint}" in self.paths:
            limit = arguments.get("limit")
            if not isinstance(limit, int) or not 1 <= limit <= MAX_DATA_ROWS:
                raise ArgumentValidationError("view limit must be between 1 and 100")
        if endpoint not in {"coverage", "metric_coverage"}:
            if self.data_calls >= MAX_DATA_CALLS:
                return _json({"error": "Data-call limit reached. Answer from the evidence already collected or explain the limitation."})
            self.data_calls += 1
        if rpc_path in self.paths and endpoint != "catalog":
            method = getattr(self.client, endpoint, None)
            if not callable(method):
                raise ArgumentValidationError("endpoint is not wrapped by the public SDK")
            inspect.signature(method).bind(**arguments)
            value = method(**arguments)
        elif f"/{endpoint}" in self.paths:
            value = self.client.view(endpoint, **arguments)
        else:
            raise ArgumentValidationError("endpoint is not callable")
        if isinstance(value, list) and len(value) > MAX_DATA_ROWS:
            raise ToolResultLimitError("More than 100 rows; narrow the date window, identifiers, or requested metrics.")
        result = _json(value)
        if len(result) > MAX_TOOL_CHARS:
            raise ToolResultLimitError("Result too large; narrow the date window, identifiers, or requested metrics.")
        return result

    def as_agent_tools(self) -> list[Any]:
        @function_tool
        def silo_catalog() -> str:
            """Read SILO's live catalog of metrics, constraints, and limits."""

            def fetch() -> str:
                result = _json(self.client.catalog())
                if len(result) > MAX_TOOL_CHARS:
                    raise ToolResultLimitError("Catalog exceeds the evaluation tool-size limit; catalog discovery remains unverified.")
                self.catalog_seen = True
                return result

            return self._record("silo_catalog", {}, fetch)

        @function_tool
        def silo_tools(query: str) -> str:
            """Search the published API tool list by topic or endpoint name; an empty query lists all."""
            return self._record("silo_tools", {"query": query}, lambda: self.discover_tools(query))

        @function_tool
        def silo_call(endpoint: str, arguments_json: str) -> str:
            """Call one published read-only SILO endpoint with JSON keyword arguments."""
            return self._record("silo_call", {"endpoint": endpoint, "arguments_json": arguments_json},
                                lambda: self.invoke_endpoint(endpoint, arguments_json))

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


def technical_classification(item: dict[str, Any]) -> str:
    """Classify execution separately from the answer's research quality."""
    if item.get("status") == "error":
        return "turn_exhaustion" if item.get("error_type") == "MaxTurnsExceeded" else "technical_error"
    events = item.get("tool_events", [])
    if any(event.get("error", {}).get("code") == "PGRST202" for event in events):
        return "api_unavailable"
    if any(event.get("error_type") in {"TypeError", "ArgumentValidationError", "InvalidArguments"}
           for event in events):
        return "tool_contract_failure"
    if any(event.get("error_type") in {"SiloOverCap", "SiloTimeout", "ToolResultLimitError"}
           or event.get("error", {}).get("code") in {"22023", "57014"} for event in events):
        return "query_data_failure"
    if any(event.get("error_type") == "SiloError" for event in events):
        return "api_error_unclassified"
    return "no_recorded_technical_failure"


def full_rubric_pass(item: dict[str, Any], manual: dict[str, Any]) -> bool:
    """The evaluator supplies independent checks; run status cannot pass a case."""
    required = ("disposition", "identifiers_and_periods", "calculation_or_limitation",
                "source_citation", "material_caveats")
    return (item.get("status") == "completed" and all(manual.get(name) is True for name in required)
            and not manual.get("hard_failures"))


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
            f"| {case['id']} | {case['status']} | {technical_classification(case)} | "
            f"{'yes' if checks.get('discovery_before_data') else 'no'} | "
            f"{checks.get('data_calls', 0)} | "
            f"{case.get('duration_seconds', 0):.1f}s | "
            f"${case.get('estimated_usd', 0):.4f} |"
        )
    lines = [
        "# SILO research agent evaluation results", "",
        f"Run: {record['started_at']} · Model: `{record['model']}` · Cases: {len(record['cases'])}/12", "",
        f"Estimated model spend: **${record['estimated_usd']:.4f}** of ${record['budget_usd']:.2f} cap.", "",
        f"Cumulative observed estimate including earlier runs: **${record.get('cumulative_estimated_usd', record['estimated_usd']):.4f}**.", "",
        "This is a live-agent process record. A completed run is not an answer-quality pass.",
        "See [independent grading](agent-evaluation-grade.md) for baseline classifications,",
        "API availability, and answer-quality findings.", "",
        "| Case | Run status | Technical classification | Discovery before data | Data calls | Latency | Est. spend |",
        "| --- | --- | --- | --- | ---: | ---: | ---: |", *rows, "",
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
    parser.add_argument("--preflight-report", type=Path, help="Fresh read-only live contract report required with --run")
    parser.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD)
    args = parser.parse_args()

    all_cases = load_cases()
    try:
        ledger = load_spend_ledger()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(f"a valid cumulative spend ledger is required: {type(exc).__name__}")
    selected = [case for case in all_cases if not args.case_id or case["id"] in args.case_id]
    if not selected or not 0 < args.budget_usd <= DEFAULT_BUDGET_USD:
        parser.error("select valid cases and a positive total budget no greater than US$20")
    reserved = len(selected) * worst_case_cost_usd()
    if ledger["estimated_usd"] + reserved > args.budget_usd:
        parser.error(f"prior estimated spend ${ledger['estimated_usd']:.4f} plus reserve ${reserved:.2f} exceeds total budget ${args.budget_usd:.2f}")
    if not args.run:
        print(f"Validated {len(selected)} cases; prior estimate ${ledger['estimated_usd']:.4f} + "
              f"conservative reserve ${reserved:.2f} < ${args.budget_usd:.2f} total cap. "
              "Use --run only after live API preflight passes.")
        return 0

    silo_url, silo_key = _published_demo_access() if args.public_demo else (
        os.environ.get("SILO_URL", ""), os.environ.get("SILO_ANON_KEY", "")
    )
    if not silo_url or not silo_key:
        parser.error("set SILO_URL and SILO_ANON_KEY or pass --public-demo")
    try:
        if args.preflight_report is None:
            raise ValueError("--preflight-report is required with --run")
        validate_preflight_report(args.preflight_report, silo_url)
    except ValueError as exc:
        parser.error(str(exc))
    if not load_local_openai_key():
        parser.error("OPENAI_API_KEY is required in the environment or ignored .env")
    # A failed request is never silently retried: retries could bill again
    # without contributing usage to the local spend ledger.
    set_default_openai_client(AsyncOpenAI(max_retries=0, timeout=60), use_for_tracing=False)

    record: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "model": MODEL, "budget_usd": args.budget_usd, "estimated_usd": 0.0,
        "prior_estimated_usd": ledger["estimated_usd"],
        "price_basis_usd_per_million": {"input": USD_PER_M_INPUT, "output": USD_PER_M_OUTPUT},
        "cases": [], "run_note": "",
    }
    openapi = json.loads((ROOT / "openapi.json").read_text())
    try:
        with SiloClient(url=silo_url, key=silo_key, timeout=8, retries=0) as client:
            # A failed catalog is a hard preflight failure: no paid calls follow.
            client.catalog()
            for case in selected:
                if ledger["estimated_usd"] + worst_case_cost_usd() > args.budget_usd:
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
                        agent, runtime_question(case), max_turns=MAX_TURNS,
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
                item["technical_classification"] = technical_classification(item)
                item["checks"] = process_checks(tools.events, case["expected_disposition"])
                record["cases"].append(item)
                record["estimated_usd"] = round(sum(c["estimated_usd"] for c in record["cases"]), 6)
                ledger["entries"].append({"run": record["started_at"], "case": case["id"],
                                          "estimated_usd": item["estimated_usd"]})
                ledger["estimated_usd"] = round(sum(entry["estimated_usd"] for entry in ledger["entries"]), 6)
                SPEND_LEDGER.write_text(json.dumps(ledger, indent=2) + "\n")
                record["cumulative_estimated_usd"] = ledger["estimated_usd"]
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
