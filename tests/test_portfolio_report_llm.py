"""Offline tests of src/portfolio/report/llm.py: no network, no key."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from src.portfolio.report import llm, redator, revisor


class Ok(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool


OK_JSON_SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}


# --- Anthropic -----------------------------------------------------------------


def _resp(text='{"ok": true}', stop="end_turn", usage=None, details=None, model=llm.DEFAULT_MODEL):
    usage = usage or SimpleNamespace(
        input_tokens=1000, output_tokens=500, cache_creation_input_tokens=0, cache_read_input_tokens=0, iterations=None
    )
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop, stop_details=details, usage=usage, model=model,
    )


class _Messages:
    def __init__(self, parent, kind):
        self.parent = parent
        self.kind = kind

    def create(self, **kw):
        self.parent.calls.append((self.kind, kw))
        return self.parent.response


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.messages = _Messages(self, "messages")
        self.beta = SimpleNamespace(messages=_Messages(self, "beta"))


def test_request_shape_uses_structured_output_and_no_thinking_or_prefill():
    client = FakeClient(_resp())
    p = llm.AnthropicProvider(client=client, fallbacks="off")
    assert p.complete("sys", "user", Ok) == Ok(ok=True)
    kind, kw = client.calls[0]
    assert kind == "messages"
    assert kw["model"] == llm.DEFAULT_MODEL
    assert "thinking" not in kw and "temperature" not in kw
    assert kw["output_config"]["format"] == {"type": "json_schema", "schema": OK_JSON_SCHEMA}
    assert kw["output_config"]["effort"] == llm.DEFAULT_EFFORT
    assert [m["role"] for m in kw["messages"]] == ["user"]  # no assistant prefill


def test_text_mode_without_schema_returns_text():
    p = llm.AnthropicProvider(client=FakeClient(_resp("olá")), fallbacks="off")
    assert p.complete("s", "u") == "olá"


def test_fallbacks_use_the_beta_endpoint_by_default():
    client = FakeClient(_resp())
    llm.AnthropicProvider(client=client).complete("s", "u", Ok)
    kind, kw = client.calls[0]
    assert kind == "beta" and kw["fallbacks"] == "default" and kw["betas"] == [llm.FALLBACK_BETA]


def test_model_from_env(monkeypatch):
    monkeypatch.setenv("SILO_LLM_MODEL", "some-other-model")
    p = llm.AnthropicProvider(client=FakeClient(_resp()), fallbacks="off")
    assert p.model == "some-other-model"


def test_refusal_raises_typed_error_with_category():
    details = SimpleNamespace(category="cyber", explanation="x")
    p = llm.AnthropicProvider(client=FakeClient(_resp(stop="refusal", details=details)), fallbacks="off")
    with pytest.raises(llm.LLMRefusalError) as exc:
        p.complete("s", "u", Ok)
    assert exc.value.category == "cyber"


def test_refusal_without_details_still_raises():
    p = llm.AnthropicProvider(client=FakeClient(_resp(stop="refusal", details=None)), fallbacks="off")
    with pytest.raises(llm.LLMRefusalError):
        p.complete("s", "u", Ok)


def test_truncation_and_bad_json_are_output_errors():
    with pytest.raises(llm.LLMOutputError):
        llm.AnthropicProvider(client=FakeClient(_resp(stop="max_tokens")), fallbacks="off").complete("s", "u", Ok)
    with pytest.raises(llm.LLMValidationError):
        llm.AnthropicProvider(client=FakeClient(_resp("not json")), fallbacks="off").complete("s", "u", Ok)


def test_anthropic_reply_that_fails_the_model_is_a_validation_error_after_booking():
    meter = llm.CostMeter()
    p = llm.AnthropicProvider(client=FakeClient(_resp('{"ok": true, "extra": 1}')), meter=meter, fallbacks="off")
    with pytest.raises(llm.LLMValidationError):
        p.complete("s", "u", Ok)
    assert meter.spent_usd > 0  # usage was booked before the reply was rejected


def test_missing_key_is_a_config_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(llm.LLMConfigError) as exc:
        llm.AnthropicProvider()
    assert "ANTHROPIC_API_KEY" in str(exc.value)


def test_key_is_never_in_repr(monkeypatch):
    seen = {}
    fake_sdk = SimpleNamespace(Anthropic=lambda api_key: seen.setdefault("key", api_key) and SimpleNamespace())
    monkeypatch.setitem(sys.modules, "anthropic", fake_sdk)  # the SDK is not in requirements.txt
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-secret-123")
    p = llm.AnthropicProvider(fallbacks="off")
    assert seen["key"] == "sk-test-secret-123"  # the key is passed explicitly, from the env only
    assert "sk-test-secret-123" not in repr(p)


def test_cost_is_booked_from_usage():
    meter = llm.CostMeter()
    p = llm.AnthropicProvider(client=FakeClient(_resp()), meter=meter, fallbacks="off")
    p.complete("s", "u", Ok)
    # 1000 input at 4 and 500 output at 20, per million
    assert meter.spent_usd == pytest.approx((1000 * 4 + 500 * 20) / 1e6)
    assert meter.calls[0]["input_tokens"] == 1000


def test_fallback_iterations_are_priced_by_their_own_model():
    its = [
        SimpleNamespace(type="message", model=llm.DEFAULT_MODEL, input_tokens=100, output_tokens=0,
                        cache_creation_input_tokens=0, cache_read_input_tokens=0),
        SimpleNamespace(type="fallback_message", model="other-model", input_tokens=100, output_tokens=100,
                        cache_creation_input_tokens=0, cache_read_input_tokens=0),
    ]
    usage = SimpleNamespace(input_tokens=0, output_tokens=0, iterations=its,
                            cache_creation_input_tokens=0, cache_read_input_tokens=0)
    meter = llm.CostMeter()
    p = llm.AnthropicProvider(client=FakeClient(_resp(usage=usage)), meter=meter, fallbacks="off")
    p.complete("s", "u", Ok)
    unknown_in, unknown_out = llm.UNKNOWN_MODEL_PRICE[0], llm.UNKNOWN_MODEL_PRICE[1]
    expected = (100 * 4.0 + 100 * unknown_in + 100 * unknown_out) / 1e6
    assert meter.spent_usd == pytest.approx(expected)
    assert p.served_by == ["other-model"]


def test_cap_refuses_before_the_call_when_it_would_be_exceeded():
    meter = llm.CostMeter(cap_usd=0.01)
    client = FakeClient(_resp())
    p = llm.AnthropicProvider(client=client, meter=meter, fallbacks="off")  # 16000 max tokens = US$0.32 worst case
    with pytest.raises(llm.CostCapExceeded):
        p.complete("s", "u", Ok)
    assert client.calls == []


def test_cap_counts_what_earlier_calls_spent():
    meter = llm.CostMeter(cap_usd=0.40)
    p = llm.AnthropicProvider(client=FakeClient(_resp()), meter=meter, fallbacks="off")
    p.complete("s", "u", Ok)  # worst case 0.32 fits, books about 0.014
    meter.spent_usd = 0.39
    with pytest.raises(llm.CostCapExceeded):
        p.complete("s", "u", Ok)


def test_default_cap_is_one_dollar():
    assert llm.COST_CAP_USD == 1.00 and llm.CostMeter().cap_usd == 1.00


# --- one schema, one validation ---------------------------------------------------


# The hand-written schemas the Redator and the Revisor sent before the Pydantic models
# (main at a5a1b47). The derived schema must stay exactly these: the Anthropic request is unchanged.
LEGACY_FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "section": {"type": "string", "enum": list(redator.SECTIONS)},
                    "title": {"type": "string"},
                    "text": {"type": "string"},
                    "citations": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "section", "title", "text", "citations"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}
LEGACY_VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "action": {"type": "string", "enum": ["keep", "delete", "reword"]},
                    "text": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "action", "text", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}


def test_derived_schemas_equal_the_hand_written_ones():
    assert llm.json_schema_for(redator.FindingsOutput) == LEGACY_FINDINGS_SCHEMA
    assert llm.json_schema_for(revisor.VerdictsOutput) == LEGACY_VERDICT_SCHEMA
    assert llm.json_schema_for(Ok) == OK_JSON_SCHEMA


def test_a_property_named_title_survives_and_the_keyword_does_not():
    schema = llm.json_schema_for(redator.FindingsOutput)
    assert "title" in schema["properties"]["findings"]["items"]["properties"]
    assert "title" in schema["properties"]["findings"]["items"]["required"]
    assert "title" not in json.dumps(schema["properties"]["findings"]["items"]["properties"]["title"])


def test_openai_sdk_asks_for_the_same_shape_as_anthropic():
    parsing = pytest.importorskip("openai.lib._parsing._responses")
    for model in (redator.FindingsOutput, revisor.VerdictsOutput):
        fmt = parsing.type_to_text_format_param(model)
        assert fmt["strict"] is True and fmt["name"] == model.__name__
        assert llm.flatten_schema(fmt["schema"]) == llm.json_schema_for(model)


def test_schema_must_be_a_pydantic_model():
    with pytest.raises(TypeError):
        llm.json_schema_for({"type": "object"})


def test_validate_output_accepts_text_dict_and_instance():
    assert llm.validate_output(Ok, '{"ok": true}') == Ok(ok=True)
    assert llm.validate_output(Ok, {"ok": False}) == Ok(ok=False)
    inst = Ok(ok=True)
    assert llm.validate_output(Ok, inst) is inst


def test_validate_output_failure_is_typed_and_names_fields_not_values():
    with pytest.raises(llm.LLMValidationError) as exc:
        llm.validate_output(redator.FindingsOutput, {"findings": [
            {"id": "f1", "section": "opiniao", "title": "t", "text": "SEGREDO-123", "citations": []}]})
    assert isinstance(exc.value, llm.LLMOutputError) and isinstance(exc.value, llm.LLMError)
    assert "findings.0.section" in str(exc.value) and "SEGREDO-123" not in str(exc.value)
    with pytest.raises(llm.LLMValidationError):
        llm.validate_output(Ok, "not json")
    with pytest.raises(llm.LLMValidationError):
        llm.validate_output(Ok, {"ok": True, "extra": 1})  # extra="forbid"


# --- OpenAI ----------------------------------------------------------------------


def _usage(input_tokens=1000, output_tokens=500, cached=0, written=0, reasoning=0):
    return {
        "input_tokens": input_tokens,
        "input_tokens_details": {"cached_tokens": cached, "cache_write_tokens": written},
        "output_tokens": output_tokens,
        "output_tokens_details": {"reasoning_tokens": reasoning},
        "total_tokens": input_tokens + output_tokens,
    }


def _body(text='{"ok": true}', status="completed", incomplete=None, usage=None, refusal=None, phase=None,
          model="gpt-6-luna-2026-09-01"):
    content = [{"type": "refusal", "refusal": refusal}] if refusal else [
        {"type": "output_text", "text": text, "annotations": []}]
    return {
        "id": "resp_1", "object": "response", "model": model, "status": status,
        "incomplete_details": {"reason": incomplete} if incomplete else None,
        "output": [
            {"type": "reasoning", "id": "rs_1", "summary": []},
            {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed", "phase": phase,
             "content": content},
        ],
        "usage": usage if usage is not None else _usage(),
    }


class _RawParsed:
    """What ``responses.with_raw_response.parse`` returns: ``parse()`` validates like the SDK."""

    def __init__(self, body, text_format):
        self._body = body
        self._format = text_format
        self.http_response = SimpleNamespace(json=lambda: json.loads(json.dumps(body)))

    def parse(self):
        for item in self._body["output"]:
            if item["type"] == "message" and item.get("phase") in (None, "final_answer"):
                for part in item["content"]:
                    if part["type"] == "output_text":
                        self._format.model_validate_json(part["text"])  # raises ValidationError, as the SDK does
        return llm._namespace(self._body)


class FakeOpenAI:
    def __init__(self, body):
        self.body = body
        self.calls = []
        client = self

        class _Raw:
            def parse(self, **kw):
                client.calls.append(("parse", kw))
                return _RawParsed(client.body, kw["text_format"])

        class _Responses:
            with_raw_response = _Raw()

            def create(self, **kw):
                client.calls.append(("create", kw))
                return llm._namespace(client.body)

        self.responses = _Responses()


def test_openai_defaults_to_the_owners_model_and_medium_reasoning(monkeypatch):
    monkeypatch.delenv("SILO_LLM_MODEL", raising=False)
    monkeypatch.delenv("SILO_LLM_EFFORT", raising=False)
    client = FakeOpenAI(_body())
    p = llm.OpenAIProvider(client=client)
    assert p.model == "gpt-6-luna" == llm.OPENAI_DEFAULT_MODEL and p.effort == "medium"
    assert p.complete("sys", "user", Ok) == Ok(ok=True)
    kind, kw = client.calls[0]
    assert kind == "parse" and kw["text_format"] is Ok  # native structured output, the Pydantic model
    assert kw["model"] == "gpt-6-luna" and kw["reasoning"] == {"effort": "medium"}
    assert kw["instructions"] == "sys" and kw["input"] == [{"role": "user", "content": "user"}]
    assert kw["store"] is False and kw["max_output_tokens"] == llm.DEFAULT_MAX_TOKENS
    assert "tools" not in kw and "text" not in kw and "service_tier" not in kw  # no hosted tool, Standard tier


def test_openai_model_and_effort_from_env(monkeypatch):
    monkeypatch.setenv("SILO_LLM_MODEL", "gpt-6.1-sol")
    monkeypatch.setenv("SILO_LLM_EFFORT", "high")
    p = llm.OpenAIProvider(client=FakeOpenAI(_body()))
    assert (p.model, p.effort) == ("gpt-6.1-sol", "high")
    monkeypatch.setenv("SILO_LLM_EFFORT", "off")
    client = FakeOpenAI(_body())
    llm.OpenAIProvider(client=client).complete("s", "u", Ok)
    assert "reasoning" not in client.calls[0][1]


def test_openai_text_mode_uses_create():
    client = FakeOpenAI(_body("olá"))
    assert llm.OpenAIProvider(client=client).complete("s", "u") == "olá"
    assert client.calls[0][0] == "create" and "text_format" not in client.calls[0][1]


def test_openai_refusal_is_a_typed_refusal_error():
    meter = llm.CostMeter()
    p = llm.OpenAIProvider(client=FakeOpenAI(_body(refusal="I can't help with that.")), meter=meter)
    with pytest.raises(llm.LLMRefusalError) as exc:
        p.complete("s", "u", Ok)
    assert exc.value.explanation == "I can't help with that."
    assert meter.spent_usd > 0


def test_openai_content_filter_is_a_refusal():
    p = llm.OpenAIProvider(client=FakeOpenAI(_body("", status="incomplete", incomplete="content_filter")))
    with pytest.raises(llm.LLMRefusalError) as exc:
        p.complete("s", "u", Ok)
    assert exc.value.category == "content_filter"


def test_openai_invalid_payload_is_rejected_by_pydantic_and_still_booked():
    meter = llm.CostMeter()
    p = llm.OpenAIProvider(client=FakeOpenAI(_body('{"ok": "maybe", "extra": 1}')), meter=meter)
    with pytest.raises(llm.LLMValidationError) as exc:
        p.complete("s", "u", Ok)
    assert "ok" in str(exc.value) and "maybe" not in str(exc.value)
    assert meter.spent_usd == pytest.approx((1000 * 0.10 + 500 * 0.50) / 1e6)


def test_openai_truncation_is_named_not_reported_as_bad_json():
    meter = llm.CostMeter()
    body = _body('{"ok": tr', status="incomplete", incomplete="max_output_tokens")
    with pytest.raises(llm.LLMOutputError) as exc:
        llm.OpenAIProvider(client=FakeOpenAI(body), meter=meter).complete("s", "u", Ok)
    assert not isinstance(exc.value, llm.LLMValidationError) and "max_output_tokens" in str(exc.value)
    assert meter.spent_usd > 0


def test_openai_commentary_phase_is_not_the_answer():
    body = _body('{"ok": true}', phase="final_answer")
    body["output"].insert(1, {"type": "message", "id": "msg_0", "role": "assistant", "status": "completed",
                              "phase": "commentary", "content": [{"type": "output_text", "text": "pensando...",
                                                                  "annotations": []}]})
    assert llm.OpenAIProvider(client=FakeOpenAI(body)).complete("s", "u", Ok) == Ok(ok=True)


def test_openai_cost_is_booked_from_usage_with_cache_parts():
    meter = llm.CostMeter()
    usage = _usage(input_tokens=15000, output_tokens=2000, cached=12000, written=3000, reasoning=1500)
    llm.OpenAIProvider(client=FakeOpenAI(_body(usage=usage)), meter=meter).complete("s", "u", Ok)
    # gpt-6-luna: cached 0.01, cache write 0.125, output 0.50 (reasoning included); no uncached input left
    assert meter.spent_usd == pytest.approx((12000 * 0.01 + 3000 * 0.125 + 2000 * 0.50) / 1e6)
    call = meter.calls[0]
    assert call["input_tokens"] == 0 and call["cache_read_tokens"] == 12000 and call["cache_write_tokens"] == 3000
    assert call["reasoning_tokens"] == 1500 and call["model"] == "gpt-6-luna-2026-09-01"


def test_openai_long_context_rate_above_272k_input_tokens():
    assert llm.tokens_cost_usd("gpt-6-luna", input_tokens=272_000) == pytest.approx(272_000 * 0.10 / 1e6)
    assert llm.tokens_cost_usd("gpt-6-luna", input_tokens=272_001, output_tokens=1000) == pytest.approx(
        (272_001 * 0.20 + 1000 * 0.75) / 1e6)
    assert llm.tokens_cost_usd("gpt-6-astra", input_tokens=200_000, cache_read_tokens=100_000) == pytest.approx(
        (200_000 * 20.00 + 100_000 * 2.00) / 1e6)


def test_openai_missing_usage_books_the_worst_case():
    body = _body()
    body["usage"] = None
    meter = llm.CostMeter()
    llm.OpenAIProvider(client=FakeOpenAI(body), meter=meter).complete("s", "u", Ok)
    assert meter.spent_usd == pytest.approx(llm.tokens_cost_usd("gpt-6-luna", input_tokens=1, output_tokens=16000))


def test_openai_cap_refuses_before_the_call():
    client = FakeOpenAI(_body())
    p = llm.OpenAIProvider(client=client, model="unpriced-model", meter=llm.CostMeter(cap_usd=0.01))
    with pytest.raises(llm.CostCapExceeded):
        p.complete("s", "u", Ok)
    assert client.calls == []


def test_openai_missing_key_is_a_config_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(llm.LLMConfigError) as exc:
        llm.OpenAIProvider()
    assert "OPENAI_API_KEY" in str(exc.value)


def test_openai_key_from_env_only_and_never_in_repr(monkeypatch):
    seen = {}
    fake_sdk = SimpleNamespace(OpenAI=lambda api_key: seen.setdefault("key", api_key) and SimpleNamespace())
    monkeypatch.setitem(sys.modules, "openai", fake_sdk)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-secret-456")
    p = llm.OpenAIProvider()
    assert seen["key"] == "sk-openai-secret-456"
    assert "sk-openai-secret-456" not in repr(p)


def test_unknown_price_errs_high_against_every_priced_row():
    for model, row in llm.PRICES_USD_PER_MTOK.items():
        assert all(u >= r for u, r in zip(llm.UNKNOWN_MODEL_PRICE, row)), model
    # an unpriced prompt above the long-context threshold is refused by the cap anyway
    assert llm.tokens_cost_usd("unpriced", input_tokens=272_001) > llm.COST_CAP_USD


def test_openai_through_the_real_sdk_over_a_mock_transport(monkeypatch):
    openai = pytest.importorskip("openai")
    httpx2 = pytest.importorskip("httpx2")
    seen = []

    def handler(request):
        seen.append((request.url.path, json.loads(request.content)))
        return httpx2.Response(200, json=_body('{"ok": true}', usage=_usage(2000, 300, cached=1000)))

    client = openai.OpenAI(api_key="sk-mock", base_url="https://api.openai.test/v1", max_retries=0,
                           http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    meter = llm.CostMeter()
    out = llm.OpenAIProvider(client=client, meter=meter).complete("sys", "user", Ok)
    assert out == Ok(ok=True)
    path, body = seen[0]
    assert path == "/v1/responses"
    assert body["model"] == "gpt-6-luna" and body["reasoning"] == {"effort": "medium"} and body["store"] is False
    fmt = body["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True and fmt["name"] == "Ok"
    assert llm.flatten_schema(fmt["schema"]) == OK_JSON_SCHEMA
    assert "tools" not in body
    assert meter.spent_usd == pytest.approx((1000 * 0.10 + 1000 * 0.01 + 300 * 0.50) / 1e6)

    seen.clear()

    def bad(request):
        seen.append(request)
        return httpx2.Response(200, json=_body('{"nope": 1}'))

    client = openai.OpenAI(api_key="sk-mock", base_url="https://api.openai.test/v1", max_retries=0,
                           http_client=httpx2.Client(transport=httpx2.MockTransport(bad)))
    meter = llm.CostMeter()
    with pytest.raises(llm.LLMValidationError):
        llm.OpenAIProvider(client=client, meter=meter).complete("sys", "user", Ok)
    assert meter.spent_usd == pytest.approx((1000 * 0.10 + 500 * 0.50) / 1e6)  # booked from the body


# --- selection and the fake ---------------------------------------------------------


def test_provider_selection_by_env(monkeypatch):
    monkeypatch.setenv("SILO_LLM_PROVIDER", "fake")
    assert isinstance(llm.get_provider(), llm.FakeProvider)
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda api_key: SimpleNamespace()))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.delenv("SILO_LLM_MODEL", raising=False)
    monkeypatch.setenv("SILO_LLM_PROVIDER", "openai")
    p = llm.get_provider()
    assert isinstance(p, llm.OpenAIProvider) and p.model == "gpt-6-luna"
    monkeypatch.setenv("SILO_LLM_PROVIDER", "nope")
    with pytest.raises(llm.LLMConfigError) as exc:
        llm.get_provider()
    assert "openai" in str(exc.value)


def test_fake_provider_queue_callable_and_validation():
    f = llm.FakeProvider([{"ok": True}, "texto", {"ok": "x"}])
    assert f.complete("s", "u", Ok) == Ok(ok=True)
    assert f.complete("s", "u") == "texto"
    with pytest.raises(llm.LLMValidationError):
        f.complete("s", "u", Ok)
    assert len(f.calls) == 3
    with pytest.raises(llm.LLMOutputError):
        f.complete("s", "u")
    assert llm.FakeProvider(lambda s, u, sch: "x").complete("s", "u") == "x"


def test_validation_error_is_not_a_bare_pydantic_error():
    with pytest.raises(llm.LLMError):
        llm.validate_output(Ok, {})
    try:
        llm.validate_output(Ok, {})
    except ValidationError:  # pragma: no cover - the wrapper must not leak it
        pytest.fail("pydantic.ValidationError leaked")
    except llm.LLMValidationError:
        pass
