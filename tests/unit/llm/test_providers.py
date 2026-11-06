from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from marl_agents.llm import GenerationConfig, LLMError, Message
from marl_agents.llm.gemini import GeminiProvider
from marl_agents.llm.openai_compat import OpenAICompatibleProvider

MSGS = [Message(role="system", content="sys"), Message(role="user", content="hi")]


class FakeCompletions:
    def __init__(self, replies: list[Any]) -> None:
        self.replies = replies
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=reply))],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
            model="fake-model",
        )


def fake_openai(replies: list[Any]) -> tuple[Any, FakeCompletions]:
    comp = FakeCompletions(replies)
    return SimpleNamespace(chat=SimpleNamespace(completions=comp)), comp


def test_openai_provider_sends_config_and_parses_usage() -> None:
    client, comp = fake_openai(['{"a": 1}'])
    p = OpenAICompatibleProvider("m", client=client, config=GenerationConfig(temperature=0, seed=7))
    r = p.generate(MSGS)
    assert r.text == '{"a": 1}' and r.input_tokens == 11 and r.output_tokens == 7
    sent = comp.calls[0]
    assert sent["model"] == "m" and sent["temperature"] == 0 and sent["seed"] == 7
    assert sent["response_format"] == {"type": "json_object"}
    assert sent["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
    ]


def test_openai_provider_drops_json_mode_when_unsupported() -> None:
    client, comp = fake_openai([RuntimeError("response_format not supported"), "{}"])
    p = OpenAICompatibleProvider("m", client=client)
    assert p.generate(MSGS).text == "{}"
    assert "response_format" not in comp.calls[1]


def test_openai_provider_retries_then_raises() -> None:
    slept: list[float] = []
    client, comp = fake_openai([RuntimeError("boom")] * 3)
    p = OpenAICompatibleProvider("m", client=client, max_retries=2, sleep=slept.append)
    with pytest.raises(LLMError, match="3 attempt"):
        p.generate(MSGS)
    assert len(comp.calls) == 3 and slept == [1.0, 2.0]  # exponential backoff


class Out(BaseModel):
    a: int


def test_usage_accumulates_over_structured_calls() -> None:
    client, _ = fake_openai(['{"a": 1}', "oops", '{"a": 2}'])
    p = OpenAICompatibleProvider("m", client=client)
    assert p.generate_structured(MSGS, Out).a == 1
    assert p.generate_structured(MSGS, Out).a == 2
    assert p.usage.calls == 3 and p.usage.input_tokens == 33 and p.usage.parse_retries == 1


def test_gemini_provider_maps_roles_and_system_instruction() -> None:
    calls: list[dict[str, Any]] = []

    def generate_content(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return SimpleNamespace(
            text='{"ok": true}',
            usage_metadata=SimpleNamespace(prompt_token_count=5, candidates_token_count=2),
        )

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    p = GeminiProvider("gem", client=client)
    msgs = [*MSGS, Message(role="assistant", content="prev")]
    r = p.generate(msgs)
    assert r.text == '{"ok": true}' and r.output_tokens == 2
    sent = calls[0]
    assert sent["config"]["system_instruction"] == "sys"
    assert [c["role"] for c in sent["contents"]] == ["user", "model"]
    assert sent["config"]["response_mime_type"] == "application/json"
