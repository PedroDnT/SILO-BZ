"""Provider-agnostic LLM interface for the report's Redator and Revisor.

One function shape, ``complete(system, user, schema) -> dict | str``: with a
JSON schema the provider returns the parsed object, without one the text.
The provider is chosen by ``SILO_LLM_PROVIDER`` (``anthropic`` or ``fake``),
so the owner can swap the model vendor without touching the engine or the
report. Numbers never come from here: rule zero says every figure in the
report is read from the engine JSON by the renderer.

Cost cap (owner decision): at most US$1.00 per report. One ``CostMeter`` is
shared by every call of a report. Before a call it adds the worst case (input
estimated from the prompt length, output at ``max_tokens``) and refuses the
call when that would pass the cap; after the call it books the real tokens
from ``response.usage``. The caller marks the narrative unknown on refusal.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"
DEFAULT_MAX_TOKENS = 16000
COST_CAP_USD = 1.00

# US$ per million tokens: (input, output, cache write, cache read). Taken from
# Anthropic's model table as cached on 2026-09-25 (claude-api skill). Cache
# writes are priced at 1.25x input (5-minute TTL). A model missing here (a
# different SILO_LLM_MODEL, or a fallback model that served a turn) is priced at
# UNKNOWN_MODEL_PRICE, the most expensive row, so the cap errs high. Add a row
# here, with its date, to price another model exactly.
PRICES_TAKEN_ON = "2026-09-25"
PRICES_USD_PER_MTOK: dict[str, tuple[float, float, float, float]] = {
    DEFAULT_MODEL: (4.00, 20.00, 5.00, 0.20),
}
UNKNOWN_MODEL_PRICE = (10.00, 50.00, 12.50, 1.00)

# Conservative input estimate for the pre-call check: one token per three
# characters (JSON and Portuguese both tokenize denser than that).
_CHARS_PER_TOKEN_ESTIMATE = 3

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    """Base class: the narrative could not be produced."""


class LLMConfigError(LLMError):
    """The provider is misconfigured (unknown provider, missing key)."""


class LLMRefusalError(LLMError):
    """The model declined (``stop_reason == "refusal"``)."""

    def __init__(self, category: str | None, explanation: str | None = None):
        self.category = category
        self.explanation = explanation
        super().__init__(f"model refused (category={category!r})")


class LLMOutputError(LLMError):
    """The model returned no usable output (truncated, empty or invalid JSON)."""


class CostCapExceeded(LLMError):
    """The next call could take the report past its cost cap."""


def price_for(model: str | None) -> tuple[float, float, float, float]:
    return PRICES_USD_PER_MTOK.get(model or "", UNKNOWN_MODEL_PRICE)


def tokens_cost_usd(
    model: str | None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    p_in, p_out, p_cw, p_cr = price_for(model)
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
        self.calls.append({"role": role, "model": model, "cost_usd": round(cost_usd, 6), **tokens})


class Provider(Protocol):
    name: str

    def complete(self, system: str, user: str, schema: dict | None = None) -> dict | str: ...


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
    structured outputs (``output_config.format``).
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

    def complete(self, system: str, user: str, schema: dict | None = None) -> dict | str:
        self.meter.check(self.model, len(system) + len(user), self.max_tokens)
        output_config: dict[str, Any] = {"effort": self.effort}
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}
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
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMOutputError(f"response is not valid JSON: {exc.msg}") from None


Responder = Callable[[str, str, dict | None], dict | str]


class FakeProvider:
    """Offline provider for tests and ``--provider fake``.

    ``responses`` is a callable ``(system, user, schema) -> dict | str`` or a
    list consumed in order. Every call is recorded in ``self.calls``.
    """

    name = "fake"

    def __init__(self, responses: Responder | list[dict | str] | None = None, meter: CostMeter | None = None):
        self._responses = responses
        self.meter = meter if meter is not None else CostMeter()
        self.calls: list[dict[str, Any]] = []
        self.served_by: list[str] = []
        self.model = "fake"

    def complete(self, system: str, user: str, schema: dict | None = None) -> dict | str:
        self.calls.append({"system": system, "user": user, "schema": schema})
        self.meter.book("fake", "fake", 0.0)
        if callable(self._responses):
            return self._responses(system, user, schema)
        if isinstance(self._responses, list) and self._responses:
            return self._responses.pop(0)
        raise LLMOutputError("FakeProvider has no response queued")


def get_provider(
    name: str | None = None,
    meter: CostMeter | None = None,
    fake_responses: Responder | list[dict | str] | None = None,
    role: str = "llm",
) -> Provider:
    """The provider named by ``name`` or ``SILO_LLM_PROVIDER`` (default anthropic)."""
    chosen = (name or os.environ.get("SILO_LLM_PROVIDER") or "anthropic").strip().lower()
    if chosen == "anthropic":
        return AnthropicProvider(meter=meter, role=role)
    if chosen == "fake":
        return FakeProvider(fake_responses, meter=meter)
    raise LLMConfigError(f"unknown SILO_LLM_PROVIDER {chosen!r} (anthropic|fake)")


def complete(system: str, user: str, schema: dict | None = None, provider: Provider | None = None) -> dict | str:
    """Module-level shortcut: one call on ``provider`` or the env-selected one."""
    return (provider or get_provider()).complete(system, user, schema)
