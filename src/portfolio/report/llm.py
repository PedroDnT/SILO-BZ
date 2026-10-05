"""Provider-agnostic LLM interface for the report's Redator and Revisor.

One function shape, ``complete(system, user, schema) -> BaseModel | str``:
``schema`` is a Pydantic model class. With one, the provider requests
structured output with that model's JSON schema (``json_schema_for`` for
Anthropic, the SDK's ``text_format`` for OpenAI: one shape) and returns the
model instance ``validate_output`` built from the reply; without one it returns
the text. A
reply that does not validate raises ``LLMValidationError``, a typed ``LLMError``,
so the caller marks the narrative unknown as it does for a refusal.

The provider is chosen by ``SILO_LLM_PROVIDER`` (``anthropic``, ``openai`` or
``fake``) and the model by ``SILO_LLM_MODEL``, so the owner can swap the model
vendor without touching the engine or the report. Defaults: ``anthropic`` runs
``claude-opus-5-5``; ``openai`` runs ``gpt-5.1`` at medium reasoning (the
owner's choice, 2026-10-03); ``SILO_LLM_MODEL`` and ``SILO_LLM_EFFORT`` override
either. No hosted tool (web search, file search, ...) is ever enabled: the
Redator and the Revisor read only the masked engine JSON in the prompt; hosted
tools are reserved for the later Investigator. Each vendor's key is read from its own
variable only (``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY``), passed explicitly to
its SDK and never logged. Numbers never come from here: rule zero says every
figure in the report is read from the engine JSON by the renderer.

Cost cap (owner decision): at most US$1.00 per report. One ``CostMeter`` is
shared by every call of a report. Before a call it adds the worst case (input
estimated from the prompt length, output at ``max_tokens``) and refuses the
call when that would pass the cap; after the call it books the real tokens
from ``response.usage``. The caller marks the narrative unknown on refusal.
"""

from __future__ import annotations

import copy
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"
# The owner's choice for SILO_LLM_PROVIDER=openai (2026-10-04): gpt-5.1 at medium
# reasoning, replacing gpt-6-luna (2026-10-03), because the repository's OPENAI_API_KEY
# gets 403 model_not_found on every gpt-6-* model (probe_openai_models.yml lists gpt-5,
# gpt-5.1, gpt-5-mini, gpt-5-nano, gpt-5-pro, gpt-4o and gpt-4o-mini as callable). Its
# model page (https://developers.openai.com/api/docs/models/gpt-5.1, read 2026-10-04)
# lists reasoning.effort none (default), low, medium and high, so medium is sent
# explicitly, and structured outputs on the Responses API. The same page and
# https://developers.openai.com/api/docs/deprecations (read 2026-10-04) mark gpt-5.1
# deprecated on 2026-10-01, shutdown 2027-04-01, recommended replacement gpt-6-sol.
OPENAI_DEFAULT_MODEL = "gpt-5.1"
OPENAI_DEFAULT_EFFORT = "medium"
DEFAULT_MAX_TOKENS = 16000
# gpt-5.1's reasoning tokens count against max_output_tokens: deploy run 37230811125
# had the Redator stop at 16,000 output tokens, 11,091 of them reasoning, so the reply
# was cut (LLMOutputError). The owner chose 32,000 (2026-10-04): worst case US$0.32 of
# output per call, inside the US$1.00 cap for the Redator plus the Revisor's pass.
OPENAI_DEFAULT_MAX_TOKENS = 32000
COST_CAP_USD = 1.00

# US$ per million tokens: (input, output, cache write, cache read). Taken from
# Anthropic's model table as cached on 2026-09-25 (claude-api skill). Cache
# writes are priced at 1.25x input (5-minute TTL). A model missing here (a
# different SILO_LLM_MODEL, or a fallback model that served a turn) is priced at
# UNKNOWN_MODEL_PRICE, the most expensive row, so the cap errs high. Add a row
# here, with its date, to price another model exactly.
PRICES_TAKEN_ON = "2026-09-25"
# OpenAI rows: read on OpenAI's pricing page, https://developers.openai.com/api/docs/pricing
# (https://platform.openai.com/docs/pricing redirects there), "Flagship models", Standard
# tier, short context, accessed 2026-10-03, and on each model's page under
# https://developers.openai.com/api/docs/models/. OpenAI lists input, cached input, cache
# writes and output; the tuple order is the one above (cache write, then cache read =
# cached input). Only the Standard tier is priced: Fast mode (2x), Batch and Flex (0.5x)
# and regional processing (+10%) are not modelled, and the provider sends no service_tier.
OPENAI_PRICES_TAKEN_ON = "2026-10-04"  # the gpt-5.1 row; the gpt-6 rows were read 2026-10-03
PRICES_USD_PER_MTOK: dict[str, tuple[float, float, float, float]] = {
    DEFAULT_MODEL: (4.00, 20.00, 5.00, 0.20),
    "gpt-6-astra": (10.00, 50.00, 12.50, 1.00),
    "gpt-6.1-sol": (2.00, 10.00, 2.50, 0.10),
    "gpt-6-luna": (0.10, 0.50, 0.125, 0.01),
    # gpt-5.1: the pricing page's Standard row (input $1.25, cached input $0.125, output
    # $10.00, cache writes "-", no long-context columns) and its model page, both read
    # 2026-10-04. "-" means no separate write fee: written tokens are part of
    # input_tokens, so they are priced at the input rate here, never as free.
    "gpt-5.1": (1.25, 10.00, 1.25, 0.125),
}
# "Prompts with more than 272K input tokens are priced at 2x input and cache rates and 1.5x
# output for the full request" (the gpt-6-astra, gpt-6.1-sol and gpt-6-luna model pages,
# 2026-10-03). The rows are the pricing page's long-context column. 272K is read as 272,000,
# the lower reading, so the long rate applies early rather than late. Total input is the
# uncached, cache-write and cache-read tokens together.
LONG_CONTEXT_USD_PER_MTOK: dict[str, tuple[int, tuple[float, float, float, float]]] = {
    "gpt-6-astra": (272_000, (20.00, 75.00, 25.00, 2.00)),
    "gpt-6.1-sol": (272_000, (4.00, 15.00, 5.00, 0.20)),
    "gpt-6-luna": (272_000, (0.20, 0.75, 0.25, 0.02)),
}
# The most expensive short-context row. A prompt above 272K tokens at this price (US$2.72 of
# input alone) is refused by the cap before any call, so it needs no long-context row.
UNKNOWN_MODEL_PRICE = (10.00, 50.00, 12.50, 1.00)

# Conservative input estimate for the pre-call check: one token per three
# characters (JSON and Portuguese both tokenize denser than that).
_CHARS_PER_TOKEN_ESTIMATE = 3

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    """Base class: the narrative could not be produced."""


class LLMConfigError(LLMError):
    """The provider is misconfigured (unknown provider, missing key or model)."""


class LLMRefusalError(LLMError):
    """The model declined (``stop_reason == "refusal"``, or an OpenAI ``refusal`` part)."""

    def __init__(self, category: str | None, explanation: str | None = None):
        self.category = category
        self.explanation = explanation
        super().__init__(f"model refused (category={category!r})")


class LLMOutputError(LLMError):
    """The model returned no usable output (truncated, empty or invalid JSON)."""


class LLMValidationError(LLMOutputError):
    """The reply does not validate against the Pydantic model it was asked for."""

    def __init__(self, schema_name: str, errors: list[str]):
        self.schema_name = schema_name
        self.errors = errors
        shown = "; ".join(errors[:5]) + (f"; and {len(errors) - 5} more" if len(errors) > 5 else "")
        super().__init__(f"reply does not validate against {schema_name}: {shown}")


class CostCapExceeded(LLMError):
    """The next call could take the report past its cost cap."""


def price_for(model: str | None, total_input_tokens: int = 0) -> tuple[float, float, float, float]:
    long_ctx = LONG_CONTEXT_USD_PER_MTOK.get(model or "")
    if long_ctx and total_input_tokens > long_ctx[0]:
        return long_ctx[1]
    return PRICES_USD_PER_MTOK.get(model or "", UNKNOWN_MODEL_PRICE)


def tokens_cost_usd(
    model: str | None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    p_in, p_out, p_cw, p_cr = price_for(model, input_tokens + cache_write_tokens + cache_read_tokens)
    return (
        input_tokens * p_in
        + output_tokens * p_out
        + cache_write_tokens * p_cw
        + cache_read_tokens * p_cr
    ) / 1_000_000


@dataclass
class CostMeter:
    """Spend of one report, in US$, against ``cap_usd``."""

    cap_usd: float = COST_CAP_USD
    spent_usd: float = 0.0
    calls: list[dict[str, Any]] = field(default_factory=list)

    def check(self, model: str, prompt_chars: int, max_tokens: int) -> float:
        """Raise ``CostCapExceeded`` if the worst case would pass the cap."""
        est_input = -(-prompt_chars // _CHARS_PER_TOKEN_ESTIMATE)
        worst = tokens_cost_usd(model, input_tokens=est_input, output_tokens=max_tokens)
        if self.spent_usd + worst > self.cap_usd:
            raise CostCapExceeded(
                f"next call could cost up to US${worst:.4f}; spent US${self.spent_usd:.4f} "
                f"of the US${self.cap_usd:.2f} cap"
            )
        return worst

    def book(self, role: str, model: str | None, cost_usd: float, **tokens: int) -> None:
        self.spent_usd += cost_usd
        # ended_unix_nano: when the call returned, for the run trace's agent spans (src/portfolio/trace.py).
        self.calls.append({"role": role, "model": model, "cost_usd": round(cost_usd, 6), **tokens,
                           "ended_unix_nano": time.time_ns()})


class Provider(Protocol):
    name: str

    def complete(self, system: str, user: str, schema: type[BaseModel] | None = None) -> BaseModel | str: ...


# --- one schema and one validation, for every provider -------------------------

# JSON Schema keywords whose value is a schema, and those whose value is a list of schemas.
_SUBSCHEMA_KEYS = ("items", "additionalProperties", "not", "contains")
_SUBSCHEMA_LIST_KEYS = ("anyOf", "allOf", "oneOf", "prefixItems")


def json_schema_for(schema: type[BaseModel]) -> dict:
    """The JSON schema a provider is asked to fill, derived from the Pydantic model.

    Pydantic's schema with every ``$ref`` inlined (the models here are not
    recursive) and the ``title`` keyword dropped. ``title`` is dropped only where
    it is a schema keyword, never as a property name (a finding has a ``title``).
    The Anthropic provider sends this dict; the OpenAI SDK derives its strict
    schema from the same model (``text_format``), and the tests pin that both
    ask for one shape.
    """
    if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
        raise TypeError(f"schema must be a Pydantic model class, not {schema!r}")
    return flatten_schema(schema.model_json_schema())


def flatten_schema(raw: dict) -> dict:
    """A JSON schema with its ``$defs`` inlined and the ``title`` keyword dropped."""
    raw = copy.deepcopy(raw)
    defs = raw.pop("$defs", {})

    def walk(node: Any, seen: tuple[str, ...]) -> Any:
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[-1]
            if name in seen:
                raise ValueError(f"recursive schema {name!r} is not supported")
            return walk(copy.deepcopy(defs[name]), seen + (name,))
        out: dict = {}
        for k, v in node.items():
            if k == "title":
                continue
            if k == "properties":
                out[k] = {prop: walk(sub, seen) for prop, sub in v.items()}
            elif k in _SUBSCHEMA_KEYS:
                out[k] = walk(v, seen)
            elif k in _SUBSCHEMA_LIST_KEYS:
                out[k] = [walk(sub, seen) for sub in v]
            else:
                out[k] = v
        return out

    return walk(raw, ())


def validate_output(schema: type[BaseModel], raw: Any) -> BaseModel:
    """``raw`` (JSON text, a dict or an instance) as a ``schema`` instance, else ``LLMValidationError``.

    The error names the failing fields and why, never the values the model wrote.
    """
    if isinstance(raw, schema):
        return raw
    try:
        if isinstance(raw, (str, bytes, bytearray)):
            return schema.model_validate_json(raw)
        return schema.model_validate(raw)
    except ValidationError as exc:
        errors = [
            f"{'.'.join(str(p) for p in e.get('loc', ())) or '<root>'}: {e.get('msg', '')}"
            for e in exc.errors(include_url=False, include_input=False)
        ]
        raise LLMValidationError(schema.__name__, errors) from None


def _usage_cost(usage: Any, requested_model: str) -> tuple[float, dict[str, int], list[str]]:
    """Price ``response.usage``; per iteration when fallbacks served the turn."""
    served_by: list[str] = []
    iterations = getattr(usage, "iterations", None) or []
    if iterations:
        total = 0.0
        tok = {"input_tokens": 0, "output_tokens": 0, "cache_write_tokens": 0, "cache_read_tokens": 0}
        for it in iterations:
            model = getattr(it, "model", None)
            if getattr(it, "type", None) == "fallback_message" and model:
                served_by.append(str(model))
            t = {
                "input_tokens": getattr(it, "input_tokens", 0) or 0,
                "output_tokens": getattr(it, "output_tokens", 0) or 0,
                "cache_write_tokens": getattr(it, "cache_creation_input_tokens", 0) or 0,
                "cache_read_tokens": getattr(it, "cache_read_input_tokens", 0) or 0,
            }
            # An iteration with no model is the requested one; an unknown
            # model id is priced at the most expensive row.
            total += tokens_cost_usd(str(model) if model else requested_model, **t)
            for k, v in t.items():
                tok[k] += v
        return total, tok, served_by
    tok = {
        "input_tokens": getattr(usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        "cache_write_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
    }
    return tokens_cost_usd(requested_model, **tok), tok, served_by


class AnthropicProvider:
    """Claude through the official ``anthropic`` SDK (Messages API).

    The key is read from ``ANTHROPIC_API_KEY`` only and passed explicitly, so
    no other credential source (auth token, CLI profile) is picked up. It is
    never logged or stored on the instance. Thinking is not configured:
    ``claude-opus-5-5`` always thinks and ``budget_tokens`` is rejected; depth
    is set with ``output_config.effort``. No assistant prefill: JSON comes from
    structured outputs (``output_config.format``), with the schema
    ``json_schema_for`` derives from the Pydantic model, and the reply is
    validated with that model.
    """

    name = "anthropic"

    def __init__(
        self,
        client: Any | None = None,
        meter: CostMeter | None = None,
        model: str | None = None,
        effort: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        fallbacks: str | None = None,
        role: str = "llm",
    ):
        self.model = model or os.environ.get("SILO_LLM_MODEL") or DEFAULT_MODEL
        self.effort = effort or os.environ.get("SILO_LLM_EFFORT") or DEFAULT_EFFORT
        self.max_tokens = max_tokens
        fb = fallbacks if fallbacks is not None else os.environ.get("SILO_LLM_FALLBACKS", "default")
        self.fallbacks = None if fb in ("", "off", "none") else fb
        self.meter = meter if meter is not None else CostMeter()
        self.role = role
        self.served_by: list[str] = []
        if client is None:
            key = os.environ.get("ANTHROPIC_API_KEY")
            if not key:
                raise LLMConfigError("ANTHROPIC_API_KEY is not set")
            import anthropic

            client = anthropic.Anthropic(api_key=key)
        self._client = client

    def __repr__(self) -> str:  # never show the client (it holds the key)
        return f"AnthropicProvider(model={self.model!r}, effort={self.effort!r})"

    def complete(self, system: str, user: str, schema: type[BaseModel] | None = None) -> BaseModel | str:
        self.meter.check(self.model, len(system) + len(user), self.max_tokens)
        output_config: dict[str, Any] = {"effort": self.effort}
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": json_schema_for(schema)}
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_config": output_config,
        }
        if self.fallbacks:
            response = self._client.beta.messages.create(
                betas=[FALLBACK_BETA], fallbacks=self.fallbacks, **kwargs
            )
        else:
            response = self._client.messages.create(**kwargs)

        cost, tok, served_by = _usage_cost(response.usage, self.model)
        self.meter.book(self.role, getattr(response, "model", self.model), cost, **tok)
        self.served_by.extend(served_by)

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise LLMRefusalError(
                getattr(details, "category", None) if details else None,
                getattr(details, "explanation", None) if details else None,
            )
        if response.stop_reason == "max_tokens":
            raise LLMOutputError(f"output truncated at max_tokens={self.max_tokens}")
        text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
        if not text.strip():
            raise LLMOutputError("empty response")
        if schema is None:
            return text
        return validate_output(schema, text)


def _openai_usage_cost(usage: Any, model: str) -> tuple[float, dict[str, int]]:
    """Price a Responses API ``usage``.

    ``cached_tokens`` and ``cache_write_tokens`` are parts of ``input_tokens``
    (OpenAI's prompt caching guide: 15,000 input = 12,000 cached + 3,000
    written), so the uncached input is what is left. ``output_tokens`` already
    includes the reasoning tokens, which are billed as output.
    """
    details = getattr(usage, "input_tokens_details", None)
    cached = getattr(details, "cached_tokens", 0) or 0
    written = getattr(details, "cache_write_tokens", 0) or 0
    total_in = getattr(usage, "input_tokens", 0) or 0
    tok = {
        "input_tokens": max(total_in - cached - written, 0),
        "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        "cache_write_tokens": written,
        "cache_read_tokens": cached,
    }
    return tokens_cost_usd(model, **tok), tok


def _namespace(doc: Any) -> Any:
    """A JSON body as attribute access, so it is read like an SDK object."""
    if isinstance(doc, dict):
        return SimpleNamespace(**{k: _namespace(v) for k, v in doc.items()})
    if isinstance(doc, list):
        return [_namespace(v) for v in doc]
    return doc


class OpenAIProvider:
    """OpenAI models through the official ``openai`` SDK (Responses API).

    Model ``SILO_LLM_MODEL``, default ``gpt-5.1``; ``reasoning.effort`` from
    ``SILO_LLM_EFFORT``, default ``medium`` (``off`` sends no reasoning
    parameter, for a model without reasoning). The key is read from
    ``OPENAI_API_KEY`` only and passed explicitly; it is never logged or stored
    on the instance.

    Structured output is the SDK's native path, ``responses.parse`` with
    ``text_format=<Pydantic model>``; no hosted tool is sent. ``parse`` validates
    inside the SDK, and a reply that fails there raises before the response is
    returned, so the call goes through ``with_raw_response``: on that failure the
    HTTP body is still read for its ``usage`` (booked on the cost meter), its
    status and any refusal, and the text is then validated here with the same
    model, which raises ``LLMValidationError``. Every reply, parsed or not, is
    validated by ``validate_output``. Reasoning tokens count against
    ``max_output_tokens``, so a truncated reply is an ``LLMOutputError`` naming
    it. ``store`` is off: OpenAI does not keep the response for later retrieval.
    """

    name = "openai"

    def __init__(
        self,
        client: Any | None = None,
        meter: CostMeter | None = None,
        model: str | None = None,
        effort: str | None = None,
        max_tokens: int = OPENAI_DEFAULT_MAX_TOKENS,
        role: str = "llm",
    ):
        self.model = model or os.environ.get("SILO_LLM_MODEL") or OPENAI_DEFAULT_MODEL
        eff = effort or os.environ.get("SILO_LLM_EFFORT") or OPENAI_DEFAULT_EFFORT
        self.effort = None if eff.strip().lower() == "off" else eff.strip()
        self.max_tokens = max_tokens
        self.meter = meter if meter is not None else CostMeter()
        self.role = role
        self.served_by: list[str] = []
        if client is None:
            key = os.environ.get("OPENAI_API_KEY")
            if not key:
                raise LLMConfigError("OPENAI_API_KEY is not set")
            import openai

            client = openai.OpenAI(api_key=key)
        self._client = client

    def __repr__(self) -> str:  # never show the client (it holds the key)
        return f"OpenAIProvider(model={self.model!r}, effort={self.effort!r})"

    def complete(self, system: str, user: str, schema: type[BaseModel] | None = None) -> BaseModel | str:
        worst = self.meter.check(self.model, len(system) + len(user), self.max_tokens)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "instructions": system,
            "input": [{"role": "user", "content": user}],
            "max_output_tokens": self.max_tokens,
            "store": False,
        }
        if self.effort:
            kwargs["reasoning"] = {"effort": self.effort}
        if schema is None:
            response = self._client.responses.create(**kwargs)
        else:
            raw = self._client.responses.with_raw_response.parse(text_format=schema, **kwargs)
            try:
                response = raw.parse()
            except ValidationError:
                # The SDK could not validate the reply into the model. Read the body
                # instead, so usage is booked and a truncation or refusal is named.
                response = _namespace(raw.http_response.json())

        # Priced at the requested model: the response names a snapshot id the table may not hold.
        usage = getattr(response, "usage", None)
        if usage is None:  # no usage reported: book the worst case, so the cap errs high
            self.meter.book(self.role, self.model, worst, usage_missing=1)
        else:
            cost, tok = _openai_usage_cost(usage, self.model)
            reasoning = getattr(getattr(usage, "output_tokens_details", None), "reasoning_tokens", 0) or 0
            self.meter.book(
                self.role, getattr(response, "model", None) or self.model, cost, reasoning_tokens=reasoning, **tok
            )

        texts: list[str] = []
        for item in getattr(response, "output", None) or []:
            if getattr(item, "type", None) != "message":
                continue
            # The SDK's own rule (parse_text): a message whose phase is not
            # final_answer is commentary, not the structured result.
            if getattr(item, "phase", None) not in (None, "final_answer"):
                continue
            for part in getattr(item, "content", None) or []:
                kind = getattr(part, "type", None)
                if kind == "refusal":
                    raise LLMRefusalError(None, getattr(part, "refusal", None))
                if kind == "output_text":
                    texts.append(getattr(part, "text", "") or "")
        status = getattr(response, "status", None)
        if status == "incomplete":
            reason = getattr(getattr(response, "incomplete_details", None), "reason", None)
            if reason == "content_filter":  # the platform withheld the output: handled as a refusal
                raise LLMRefusalError("content_filter")
            raise LLMOutputError(f"response incomplete ({reason}); max_output_tokens={self.max_tokens}")
        if status not in (None, "completed"):
            error = getattr(response, "error", None)
            raise LLMOutputError(f"response status {status!r} (error code {getattr(error, 'code', None)!r})")
        text = "".join(texts)
        if not text.strip():
            raise LLMOutputError("empty response")
        if schema is None:
            return text
        return validate_output(schema, text)


Responder = Callable[[str, str, Any], Any]


class FakeProvider:
    """Offline provider for tests and ``--provider fake``.

    ``responses`` is a callable ``(system, user, schema) -> dict | str`` or a
    list consumed in order. With a schema the reply is validated as a real
    provider's is (``validate_output``), so a malformed canned reply raises
    ``LLMValidationError``. Every call is recorded in ``self.calls``.
    """

    name = "fake"

    def __init__(self, responses: Responder | list[Any] | None = None, meter: CostMeter | None = None):
        self._responses = responses
        self.meter = meter if meter is not None else CostMeter()
        self.calls: list[dict[str, Any]] = []
        self.served_by: list[str] = []
        self.model = "fake"

    def complete(self, system: str, user: str, schema: type[BaseModel] | None = None) -> BaseModel | str:
        self.calls.append({"system": system, "user": user, "schema": schema})
        self.meter.book("fake", "fake", 0.0)
        if callable(self._responses):
            raw = self._responses(system, user, schema)
        elif isinstance(self._responses, list) and self._responses:
            raw = self._responses.pop(0)
        else:
            raise LLMOutputError("FakeProvider has no response queued")
        return raw if schema is None else validate_output(schema, raw)


def get_provider(
    name: str | None = None,
    meter: CostMeter | None = None,
    fake_responses: Responder | list[Any] | None = None,
    role: str = "llm",
) -> Provider:
    """The provider named by ``name`` or ``SILO_LLM_PROVIDER`` (default anthropic)."""
    chosen = (name or os.environ.get("SILO_LLM_PROVIDER") or "anthropic").strip().lower()
    if chosen == "anthropic":
        return AnthropicProvider(meter=meter, role=role)
    if chosen == "openai":
        return OpenAIProvider(meter=meter, role=role)
    if chosen == "fake":
        return FakeProvider(fake_responses, meter=meter)
    raise LLMConfigError(f"unknown SILO_LLM_PROVIDER {chosen!r} (anthropic|openai|fake)")


def complete(
    system: str, user: str, schema: type[BaseModel] | None = None, provider: Provider | None = None
) -> BaseModel | str:
    """Module-level shortcut: one call on ``provider`` or the env-selected one."""
    return (provider or get_provider()).complete(system, user, schema)
