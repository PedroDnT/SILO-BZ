"""Offline tests of src/portfolio/report/llm.py: no network, no key."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.portfolio.report import llm


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


SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}


def test_request_shape_uses_structured_output_and_no_thinking_or_prefill():
    client = FakeClient(_resp())
    p = llm.AnthropicProvider(client=client, fallbacks="off")
    assert p.complete("sys", "user", SCHEMA) == {"ok": True}
    kind, kw = client.calls[0]
    assert kind == "messages"
    assert kw["model"] == llm.DEFAULT_MODEL
    assert "thinking" not in kw and "temperature" not in kw
    assert kw["output_config"]["format"] == {"type": "json_schema", "schema": SCHEMA}
    assert kw["output_config"]["effort"] == llm.DEFAULT_EFFORT
    assert [m["role"] for m in kw["messages"]] == ["user"]  # no assistant prefill


def test_text_mode_without_schema_returns_text():
    p = llm.AnthropicProvider(client=FakeClient(_resp("olá")), fallbacks="off")
    assert p.complete("s", "u") == "olá"


def test_fallbacks_use_the_beta_endpoint_by_default():
    client = FakeClient(_resp())
    llm.AnthropicProvider(client=client).complete("s", "u", SCHEMA)
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
        p.complete("s", "u", SCHEMA)
    assert exc.value.category == "cyber"


def test_refusal_without_details_still_raises():
    p = llm.AnthropicProvider(client=FakeClient(_resp(stop="refusal", details=None)), fallbacks="off")
    with pytest.raises(llm.LLMRefusalError):
        p.complete("s", "u", SCHEMA)


def test_truncation_and_bad_json_are_output_errors():
    with pytest.raises(llm.LLMOutputError):
        llm.AnthropicProvider(client=FakeClient(_resp(stop="max_tokens")), fallbacks="off").complete("s", "u", SCHEMA)
    with pytest.raises(llm.LLMOutputError):
        llm.AnthropicProvider(client=FakeClient(_resp("not json")), fallbacks="off").complete("s", "u", SCHEMA)


def test_missing_key_is_a_config_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(llm.LLMConfigError) as exc:
        llm.AnthropicProvider()
    assert "ANTHROPIC_API_KEY" in str(exc.value)


def test_key_is_never_in_repr(monkeypatch):
    import sys

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
    p.complete("s", "u", SCHEMA)
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
    p.complete("s", "u", SCHEMA)
    unknown_in, unknown_out = llm.UNKNOWN_MODEL_PRICE[0], llm.UNKNOWN_MODEL_PRICE[1]
    expected = (100 * 4.0 + 100 * unknown_in + 100 * unknown_out) / 1e6
    assert meter.spent_usd == pytest.approx(expected)
    assert p.served_by == ["other-model"]


def test_cap_refuses_before_the_call_when_it_would_be_exceeded():
    meter = llm.CostMeter(cap_usd=0.01)
    client = FakeClient(_resp())
    p = llm.AnthropicProvider(client=client, meter=meter, fallbacks="off")  # 16000 max tokens = US$0.32 worst case
    with pytest.raises(llm.CostCapExceeded):
        p.complete("s", "u", SCHEMA)
    assert client.calls == []


def test_cap_counts_what_earlier_calls_spent():
    meter = llm.CostMeter(cap_usd=0.40)
    p = llm.AnthropicProvider(client=FakeClient(_resp()), meter=meter, fallbacks="off")
    p.complete("s", "u", SCHEMA)  # worst case 0.32 fits, books about 0.014
    meter.spent_usd = 0.39
    with pytest.raises(llm.CostCapExceeded):
        p.complete("s", "u", SCHEMA)


def test_default_cap_is_one_dollar():
    assert llm.COST_CAP_USD == 1.00 and llm.CostMeter().cap_usd == 1.00


def test_provider_selection_by_env(monkeypatch):
    monkeypatch.setenv("SILO_LLM_PROVIDER", "fake")
    assert isinstance(llm.get_provider(), llm.FakeProvider)
    monkeypatch.setenv("SILO_LLM_PROVIDER", "nope")
    with pytest.raises(llm.LLMConfigError):
        llm.get_provider()


def test_fake_provider_queue_and_callable():
    f = llm.FakeProvider([{"a": 1}, "texto"])
    assert f.complete("s", "u", SCHEMA) == {"a": 1}
    assert f.complete("s", "u") == "texto"
    assert len(f.calls) == 2
    with pytest.raises(llm.LLMOutputError):
        f.complete("s", "u")
    assert llm.FakeProvider(lambda s, u, sch: "x").complete("s", "u") == "x"
