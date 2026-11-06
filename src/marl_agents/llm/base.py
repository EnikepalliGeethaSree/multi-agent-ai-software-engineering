"""Model-agnostic LLM interface. The rest of the system depends only on this module."""

from __future__ import annotations

import json
import re
import threading
import time
from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel, Field, PrivateAttr, ValidationError

T = TypeVar("T", bound=BaseModel)


class CallAttempt(BaseModel):
    """One request to a provider, successful or not (failed calls still took time)."""

    started_at: float
    latency_s: float
    ok: bool = False
    status: int | None = None
    error_kind: str | None = None


class LLMError(RuntimeError):
    """Raised when a provider call fails or its output cannot be parsed.

    `attempts` keeps the failed requests so their time is not lost from the timing breakdown.
    """

    def __init__(self, message: str, attempts: list[CallAttempt] | None = None) -> None:
        super().__init__(message)
        self.attempts: list[CallAttempt] = list(attempts or [])


class RequestTooLargeError(LLMError):
    """The prompt exceeds the model's per-request token limit; retrying it unchanged is futile."""


class QuotaExhaustedError(LLMError):
    """A daily or free-tier quota is used up. Waiting seconds will not help; the review can resume.

    `retry_after_s` is the provider's stated wait (None if it did not give one); `resets_at` is an
    ISO timestamp when the reset time is known.
    """

    def __init__(
        self,
        message: str,
        attempts: list[CallAttempt] | None = None,
        retry_after_s: float | None = None,
        resets_at: str | None = None,
    ) -> None:
        super().__init__(message, attempts)
        self.retry_after_s = retry_after_s
        self.resets_at = resets_at


class Message(BaseModel):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str


class GenerationConfig(BaseModel):
    temperature: float = 0.0
    max_tokens: int = 2048
    seed: int | None = 42
    stop: list[str] | None = None


class LLMResponse(BaseModel):
    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    # Request -> response time of the API call alone (perf_counter clock; excludes rate-limit
    # waits and retries' back-off). Providers set it; None if unknown.
    started_at: float | None = None
    latency_s: float | None = None
    # Internal reasoning tokens, reported separately by some models; part of neither count above.
    thinking_tokens: int | None = None
    # Provider's stop reason, e.g. "STOP" or "MAX_TOKENS" (None if it does not report one).
    finish_reason: str | None = None
    # Failed requests that preceded this successful one (rate limits, timeouts).
    attempts: list[CallAttempt] = Field(default_factory=list)


class LLMCallRecord(BaseModel):
    """One request to the LLM. Token counts are None when the provider did not report them."""

    label: str | None = None
    latency_s: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    ok: bool = True
    retry: bool = False
    error_kind: str | None = None


class Usage(BaseModel):
    """Usage counters. One per provider (lifetime) and one per review run (passed to calls).

    Thread-safe: several review units (and several jobs) may call the same provider concurrently.
    """

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    parse_retries: int = 0
    failed_calls: int = 0
    thinking_tokens: int = 0
    calls_without_token_usage: int = 0
    _lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)
    # (kind, start, end) on the perf_counter clock: "inference" per API call, "parse" per
    # JSON-schema validation. Used for the run's timing breakdown.
    _spans: list[tuple[str, float, float]] = PrivateAttr(default_factory=list)
    _calls: list[LLMCallRecord] = PrivateAttr(default_factory=list)

    def record(self, response: LLMResponse, retry: bool = False, label: str | None = None) -> None:
        with self._lock:
            self.calls += 1
            self.input_tokens += response.input_tokens or 0
            self.output_tokens += response.output_tokens or 0
            self.thinking_tokens += response.thinking_tokens or 0
            if response.input_tokens is None and response.output_tokens is None:
                self.calls_without_token_usage += 1
            if retry:
                self.parse_retries += 1
            if response.started_at is not None and response.latency_s is not None:
                start = response.started_at
                self._spans.append(("inference", start, start + response.latency_s))
            self._calls.append(
                LLMCallRecord(
                    label=label,
                    latency_s=response.latency_s,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    retry=retry,
                )
            )

    def record_failures(self, attempts: list[CallAttempt], label: str | None = None) -> None:
        """Requests that failed: no tokens are known, but they took time and they happened."""
        with self._lock:
            for a in attempts:
                self.failed_calls += 1
                self._spans.append(("inference", a.started_at, a.started_at + a.latency_s))
                self._calls.append(
                    LLMCallRecord(
                        label=label, latency_s=a.latency_s, ok=False, error_kind=a.error_kind
                    )
                )

    def record_parse(self, start: float, end: float) -> None:
        with self._lock:
            self._spans.append(("parse", start, end))

    def spans(self) -> list[tuple[str, float, float]]:
        with self._lock:
            return list(self._spans)

    def call_log(self) -> list[LLMCallRecord]:
        with self._lock:
            return list(self._calls)

    def tokens_reported(self) -> bool:
        """False when no successful call reported tokens, so the totals mean "unavailable"."""
        with self._lock:
            return self.calls > self.calls_without_token_usage

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "calls": self.calls,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "parse_retries": self.parse_retries,
                "failed_calls": self.failed_calls,
                "thinking_tokens": self.thinking_tokens,
                "calls_without_token_usage": self.calls_without_token_usage,
            }


class LLMProvider(ABC):
    """Base class for all providers (OpenAI, Gemini, local, mock...)."""

    name: str = "base"

    def __init__(self, model: str | None = None, config: GenerationConfig | None = None) -> None:
        self.model = model
        self.config = config or GenerationConfig()
        self.usage = Usage()

    @abstractmethod
    def generate(
        self, messages: list[Message], config: GenerationConfig | None = None
    ) -> LLMResponse:
        """Return the model's reply to a chat-style message list."""

    def generate_structured(
        self,
        messages: list[Message],
        schema: type[T],
        config: GenerationConfig | None = None,
        max_retries: int = 1,
        usage: Usage | None = None,
        label: str | None = None,
    ) -> T:
        """Ask for JSON matching `schema`; retry with the validation error, then raise LLMError.

        Usage is recorded on the provider and, if given, on `usage` (the caller's own run).
        `label` names what the call was for (e.g. a review unit) in the per-call log.
        """
        attempt_messages = list(messages)
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                response = self.generate(attempt_messages, config)
            except LLMError as exc:
                for counter in (self.usage, usage):
                    if counter is not None:
                        counter.record_failures(exc.attempts, label)
                raise
            for counter in (self.usage, usage):
                if counter is not None:
                    counter.record_failures(response.attempts, label)
                    counter.record(response, retry=attempt > 0, label=label)
            parse_start = time.perf_counter()
            try:
                parsed = schema.model_validate_json(_strip_code_fence(response.text))
            except (ValidationError, json.JSONDecodeError) as exc:
                if usage is not None:
                    usage.record_parse(parse_start, time.perf_counter())
                last_error = exc
                if response.finish_reason == "MAX_TOKENS":
                    # The same request would be cut off again: do not spend quota on a retry.
                    raise LLMError(
                        f"Reply for {schema.__name__} was cut off at the output token limit; "
                        "raise llm.max_tokens"
                    ) from exc
                attempt_messages = [
                    *messages,
                    Message(role="assistant", content=response.text),
                    Message(
                        role="user",
                        content=f"Your reply did not match the required JSON schema: {exc}. "
                        "Reply again with only valid JSON.",
                    ),
                ]
                continue
            if usage is not None:
                usage.record_parse(parse_start, time.perf_counter())
            return parsed
        raise LLMError(f"Structured output failed for {schema.__name__}: {last_error}")


_THINK = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```(?:json|JSON)?\s*\n(.*?)```", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    """Extract the JSON payload from a model reply.

    Handles reasoning models' `<think>...</think>` blocks (e.g. Qwen3/DeepSeek-R1 on Groq),
    ```json fences, and prose before/after the JSON object.
    """
    cleaned = _THINK.sub("", text).strip()
    fenced = _FENCE.search(cleaned)
    if fenced:
        return fenced.group(1).strip()
    if cleaned.startswith("```"):  # unterminated fence
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
    if not cleaned.startswith(("{", "[")):
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if 0 <= start < end:
            return cleaned[start : end + 1]
    return cleaned.strip()
