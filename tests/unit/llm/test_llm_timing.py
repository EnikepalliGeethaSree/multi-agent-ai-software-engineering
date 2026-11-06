"""LLM timing: inference latency covers only the API call (never rate-limit waits)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from marl_agents.llm import Message, MockLLMProvider
from marl_agents.llm.base import Usage
from marl_agents.llm.openai_compat import OpenAICompatibleProvider
from marl_agents.llm.rate_limit import RateLimiter

MSGS = [Message(role="user", content="hi")]


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.now += s


def test_openai_latency_excludes_rate_limit_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock()
    monkeypatch.setattr("marl_agents.llm.openai_compat.time.perf_counter", clock)

    def create(**kwargs: Any) -> Any:
        clock.now += 1.25  # the API call itself
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2),
            model="m",
        )

    limiter = RateLimiter(30, 6000, clock=clock, sleep=clock.sleep)
    limiter.pause(4.0)  # the provider must wait 4 s before calling
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    p = OpenAICompatibleProvider(model="m", client=client, rate_limiter=limiter)
    resp = p.generate(MSGS)
    assert resp.latency_s == pytest.approx(1.25)
    assert resp.started_at == pytest.approx(1004.0)  # after the wait
    assert limiter.waited_s == pytest.approx(4.0)


class Out(BaseModel):
    status: str


def test_usage_records_inference_and_parse_spans() -> None:
    llm = MockLLMProvider(responses=["not json", '{"status": "ok"}'])
    usage = Usage()
    assert llm.generate_structured(MSGS, Out, usage=usage).status == "ok"
    kinds = [k for k, _, _ in usage.spans()]
    assert kinds.count("inference") == 2 and kinds.count("parse") == 2  # failed + successful
    assert all(end >= start for _, start, end in usage.spans())
    assert usage.calls == 2 and usage.parse_retries == 1


def test_mock_provider_reports_latency() -> None:
    resp = MockLLMProvider().generate(MSGS)
    assert resp.latency_s is not None and resp.latency_s >= 0 and resp.started_at is not None
