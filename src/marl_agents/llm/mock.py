"""Deterministic offline provider for tests, CI and pipeline demos."""

from __future__ import annotations

import time
from collections.abc import Callable

from marl_agents.llm.base import GenerationConfig, LLMProvider, LLMResponse, Message


class MockLLMProvider(LLMProvider):
    """Returns canned responses in order, or computes them with a responder function.

    Every call is recorded in `self.calls` so tests can assert on the prompts sent.
    """

    name = "mock"

    def __init__(
        self,
        responses: list[str] | None = None,
        responder: Callable[[list[Message]], str] | None = None,
        default: str = '{"findings": []}',
    ) -> None:
        super().__init__(model="mock-model")
        self._responses = list(responses or [])
        self._responder = responder
        self._default = default
        self.calls: list[list[Message]] = []

    def generate(
        self, messages: list[Message], config: GenerationConfig | None = None
    ) -> LLMResponse:
        self.calls.append(list(messages))
        start = time.perf_counter()
        if self._responses:
            text = self._responses.pop(0)
        elif self._responder is not None:
            text = self._responder(messages)
        else:
            text = self._default
        return LLMResponse(
            text=text,
            model=self.model or "mock-model",
            started_at=start,
            latency_s=time.perf_counter() - start,
        )
