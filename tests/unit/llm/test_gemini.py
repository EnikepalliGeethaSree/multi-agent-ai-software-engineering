"""GeminiProvider against a fake client: no network, no key. Error shapes follow google.genai."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from marl_agents.config import LLMSettings, load_settings
from marl_agents.core.schemas import AgentRequest
from marl_agents.llm import GenerationConfig, LLMError, Message
from marl_agents.llm.base import QuotaExhaustedError, RequestTooLargeError, Usage
from marl_agents.llm.factory import create_provider
from marl_agents.llm.gemini import (
    FREE_TIER_PREFERENCE,
    GeminiProvider,
    classify_failure,
    recommend_model,
    retry_delay,
)
from marl_agents.llm.rate_limit import DailyQuota, RateLimiter, next_pacific_midnight, pacific_date

MSGS = [Message(role="system", content="sys"), Message(role="user", content="hi")]
KEY = "AIzaSyD-not-a-real-key-0123456789"


class ApiError(Exception):
    """Same attributes as google.genai.errors.APIError."""

    def __init__(self, code: int, message: str, details: list[dict[str, Any]] | None = None):
        super().__init__(f"{code}. {message}")
        self.code = code
        self.message = message
        self.details = {"error": {"code": code, "message": message, "details": details or []}}


def retry_info(delay: str) -> dict[str, Any]:
    return {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay}


def quota_failure(quota_id: str) -> dict[str, Any]:
    return {
        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
        "violations": [{"quotaId": quota_id}],
    }


def per_minute(delay: str = "7s") -> ApiError:
    return ApiError(
        429,
        "Resource has been exhausted",
        [quota_failure("GenerateRequestsPerMinutePerProjectPerModel-FreeTier"), retry_info(delay)],
    )


def per_day() -> ApiError:
    return ApiError(
        429,
        "You exceeded your current quota",
        [quota_failure("GenerateRequestsPerDayPerProjectPerModel-FreeTier"), retry_info("3600s")],
    )


def ok(
    text: str = '{"a": 1}',
    usage: Any = "default",
    finish: str | None = "STOP",
) -> Any:
    if usage == "default":
        usage = SimpleNamespace(
            prompt_token_count=5,
            candidates_token_count=2,
            thoughts_token_count=3,
            total_token_count=10,
        )
    candidates = [SimpleNamespace(finish_reason=SimpleNamespace(name=finish))] if finish else []
    return SimpleNamespace(text=text, usage_metadata=usage, candidates=candidates)


class Client:
    def __init__(self, replies: list[Any]) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []
        self.models = SimpleNamespace(generate_content=self._generate, list=self._list)

    def _generate(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    @staticmethod
    def _list() -> list[Any]:
        return [
            SimpleNamespace(name="models/gemini-3.6-flash", supported_actions=["generateContent"]),
            SimpleNamespace(name="models/embedding-001", supported_actions=["embedContent"]),
        ]


def provider(replies: list[Any], **kwargs: Any) -> tuple[GeminiProvider, Client, list[float]]:
    client = Client(replies)
    slept: list[float] = []
    limiter = RateLimiter(sleep=slept.append)
    p = GeminiProvider(
        "gemini-x", client=client, api_key=KEY, sleep=slept.append, rate_limiter=limiter, **kwargs
    )
    return p, client, slept


class Out(BaseModel):
    a: int


# ---- request and response ---------------------------------------------------------------------


def test_request_carries_generation_settings_and_json_mode() -> None:
    p, client, _ = provider([ok()], config=GenerationConfig(temperature=0, max_tokens=99, seed=7))
    p.generate(MSGS)
    sent = client.calls[0]
    assert sent["model"] == "gemini-x"
    assert sent["config"]["temperature"] == 0 and sent["config"]["max_output_tokens"] == 99
    assert sent["config"]["seed"] == 7
    assert sent["config"]["response_mime_type"] == "application/json"
    assert sent["config"]["system_instruction"] == "sys"


def test_token_usage_and_latency_are_reported() -> None:
    p, _, _ = provider([ok()])
    r = p.generate(MSGS)
    assert (r.input_tokens, r.output_tokens, r.thinking_tokens) == (5, 2, 3)
    assert r.finish_reason == "STOP" and r.latency_s is not None and r.latency_s >= 0


def test_missing_usage_stays_unavailable_not_zero() -> None:
    p, _, _ = provider([ok(usage=None)])
    r = p.generate(MSGS)
    assert r.input_tokens is None and r.output_tokens is None
    usage = Usage()
    usage.record(r)
    assert usage.tokens_reported() is False


def test_structured_output_uses_the_pydantic_schema() -> None:
    p, _, _ = provider([ok('```json\n{"a": 4}\n```')])
    assert p.generate_structured(MSGS, Out).a == 4


def test_invalid_json_is_retried_once_with_the_error_then_raises() -> None:
    p, client, _ = provider([ok("nonsense"), ok("still nonsense")])
    with pytest.raises(LLMError, match="Structured output failed"):
        p.generate_structured(MSGS, Out)
    assert len(client.calls) == 2
    assert "did not match" in client.calls[1]["contents"][-1]["parts"][0]["text"]


def test_truncated_reply_does_not_spend_quota_on_a_retry() -> None:
    p, client, _ = provider([ok('{"a": ', finish="MAX_TOKENS"), ok()])
    with pytest.raises(LLMError, match="output token limit"):
        p.generate_structured(MSGS, Out)
    assert len(client.calls) == 1


def test_blocked_response_is_an_error_not_empty_findings() -> None:
    blocked = SimpleNamespace(
        text=None,
        usage_metadata=None,
        candidates=[],
        prompt_feedback=SimpleNamespace(block_reason=SimpleNamespace(name="SAFETY")),
    )
    p, _, _ = provider([blocked])
    with pytest.raises(LLMError, match="SAFETY"):
        p.generate(MSGS)


# ---- failure classification --------------------------------------------------------------------


def test_retry_delay_comes_from_retry_info_then_message() -> None:
    assert retry_delay(per_minute("12s")) == 12.0
    assert retry_delay(ApiError(429, "Please retry in 1.5s.")) == 1.5
    assert retry_delay(ApiError(429, "slow down")) is None


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (per_minute(), "rate_limit"),
        (per_day(), "quota"),
        (per_minute("3600s"), "quota"),  # a wait this long is not a per-minute limit
        (ApiError(429, "free_tier_requests, limit: 0"), "quota"),  # model has no free quota
        (ApiError(400, "The input token count exceeds the maximum"), "too_large"),
        (ApiError(413, "payload"), "too_large"),
        (ApiError(400, "API key not valid"), "fatal"),
        (ApiError(403, "permission denied"), "fatal"),
        (ApiError(404, "model not found"), "fatal"),
        (ApiError(500, "internal"), "transient"),
        (ApiError(503, "overloaded"), "transient"),
        (TimeoutError("read timed out"), "transient"),
        (ConnectionError("connection reset"), "transient"),
    ],
)
def test_failures_are_classified(exc: Exception, kind: str) -> None:
    assert classify_failure(exc).kind == kind


def test_real_sdk_error_class_is_understood() -> None:
    errors = pytest.importorskip("google.genai.errors")
    body = {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED",
                      "details": [quota_failure("PerDayPerProject"), retry_info("40s")]}}  # fmt: skip
    failure = classify_failure(errors.ClientError(429, body))
    assert failure.kind == "quota" and failure.wait_s == 40.0


# ---- retries, rate limits, quota --------------------------------------------------------------


def test_rate_limit_waits_as_the_server_asked_then_succeeds() -> None:
    p, client, _ = provider([per_minute("7s"), ok()])
    now = p.limiter._clock()
    r = p.generate(MSGS)
    assert r.text and len(client.calls) == 2 and p.rate_limited == 1
    assert p.limiter._blocked_until >= now + 7
    assert [a.error_kind for a in r.attempts] == ["rate_limit"]


def test_transient_failures_back_off_exponentially_and_stop() -> None:
    p, client, slept = provider([ApiError(503, "busy")] * 3, max_retries=2)
    with pytest.raises(LLMError, match="3 attempt") as err:
        p.generate(MSGS)
    assert len(client.calls) == 3 and slept == [1.0, 2.0]
    assert len(err.value.attempts) == 3


def test_timeout_and_connection_errors_are_retried() -> None:
    p, client, _ = provider([TimeoutError("timed out"), ConnectionError("reset"), ok()])
    assert p.generate(MSGS).text and len(client.calls) == 3


def test_fatal_errors_are_not_retried() -> None:
    p, client, _ = provider([ApiError(404, "no such model"), ok()])
    with pytest.raises(LLMError, match="rejected"):
        p.generate(MSGS)
    assert len(client.calls) == 1


def test_daily_quota_stops_at_once_and_says_when_it_resets() -> None:
    p, client, _ = provider([per_day(), ok()])
    with pytest.raises(QuotaExhaustedError) as err:
        p.generate(MSGS)
    assert len(client.calls) == 1
    assert "resumed" in str(err.value) and err.value.resets_at
    assert err.value.retry_after_s == 3600.0


def test_oversized_prompt_is_refused_before_sending() -> None:
    p, client, _ = provider([ok()], max_input_tokens=1)
    with pytest.raises(RequestTooLargeError, match="estimate"):
        p.generate([Message(role="user", content="x" * 100)])
    assert client.calls == []


def test_server_says_too_large() -> None:
    p, _, _ = provider([ApiError(400, "input token count exceeds the maximum")])
    with pytest.raises(RequestTooLargeError):
        p.generate(MSGS)


def test_local_daily_budget_refuses_without_calling_the_api(tmp_path: Path) -> None:
    daily = DailyQuota(tmp_path / "q.json", requests_per_day=1)
    p, client, _ = provider([ok(), ok()], daily_quota=daily)
    p.generate(MSGS)
    with pytest.raises(QuotaExhaustedError, match="No request was sent"):
        p.generate(MSGS)
    assert len(client.calls) == 1


def test_failed_attempts_keep_their_time_in_the_call_log() -> None:
    p, _, _ = provider([ok()])
    p._client.replies[:0] = [per_minute("1s")]
    usage = Usage()
    assert p.generate_structured(MSGS, Out, usage=usage, label="a.py:1-9").a == 1
    log = usage.call_log()
    assert [c.ok for c in log] == [False, True] and {c.label for c in log} == {"a.py:1-9"}
    assert usage.failed_calls == 1 and len([s for s in usage.spans() if s[0] == "inference"]) == 2


def test_failure_without_success_is_still_logged() -> None:
    p, _, _ = provider([per_day()])
    usage = Usage()
    with pytest.raises(QuotaExhaustedError):
        p.generate_structured(MSGS, Out, usage=usage)
    assert usage.failed_calls == 1 and usage.call_log()[0].error_kind == "quota"


# ---- daily ledger -----------------------------------------------------------------------------


def test_daily_ledger_survives_restarts_and_resets_at_pacific_midnight(tmp_path: Path) -> None:
    now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    clock = {"t": now}
    path = tmp_path / "q.json"
    first = DailyQuota(path, requests_per_day=5, clock=lambda: clock["t"])
    first.record(100)
    again = DailyQuota(path, requests_per_day=5, clock=lambda: clock["t"])
    assert (again.requests, again.tokens) == (1, 100)
    clock["t"] = next_pacific_midnight(now) + timedelta(minutes=1)
    assert again.status()["requests_used"] == 0


def test_pacific_day_boundary() -> None:
    # 2026-11-06 07:30 UTC is still 2026-11-05 in Los Angeles (PST, UTC-8)
    late = datetime(2026, 11, 6, 7, 30, tzinfo=UTC)
    assert pacific_date(late) == "2026-11-05"
    assert next_pacific_midnight(late).isoformat() == "2026-11-06T08:00:00+00:00"


def test_corrupt_ledger_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "q.json"
    path.write_text("{not json", encoding="utf-8")
    assert DailyQuota(path).requests == 0


# ---- credentials ------------------------------------------------------------------------------


def test_api_key_never_reaches_error_messages() -> None:
    leak = ApiError(400, f"bad request for key={KEY} and also {KEY}")
    p, _, _ = provider([leak])
    with pytest.raises(LLMError) as err:
        p.generate(MSGS)
    assert KEY not in str(err.value)


def test_transient_error_text_is_scrubbed_too() -> None:
    p, _, _ = provider([ConnectionError(f"https://x/?key={KEY} failed")] * 2, max_retries=1)
    with pytest.raises(LLMError) as err:
        p.generate(MSGS)
    assert KEY not in str(err.value)


# ---- configuration and provider selection ---------------------------------------------------


def test_llm_provider_and_model_env_beat_older_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARL_LLM__PROVIDER", "groq")
    monkeypatch.setenv("MARL_LLM__MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.6-flash")
    s = load_settings()
    assert (s.llm.provider, s.llm.model) == ("gemini", "gemini-3.6-flash")


def test_leftover_model_of_another_provider_is_not_sent_to_gemini(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MARL_LLM__MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    assert load_settings().llm.model == "gemini-3.8-flash"


def test_groq_stays_available_as_legacy_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("MARL_LLM__MODEL", "m")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    s = load_settings()
    assert create_provider(s.llm).name == "groq"


def test_missing_key_explains_where_to_get_one() -> None:
    with pytest.raises(LLMError, match=r"GEMINI_API_KEY is not set.*aistudio"):
        create_provider(LLMSettings(provider="gemini", model="gemini-x"))


def test_google_api_key_also_works(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("google.genai")
    monkeypatch.setenv("GOOGLE_API_KEY", "abc")
    assert create_provider(LLMSettings(provider="gemini", model="gemini-x")).name == "gemini"


def test_recommendation_is_limited_to_what_the_key_offers() -> None:
    assert recommend_model(["gemini-3.1-flash-lite", "gemini-3.6-flash"]) == "gemini-3.6-flash"
    assert recommend_model(["gemma-x"]) is None
    assert FREE_TIER_PREFERENCE[0] == "gemini-3.8-flash"


def test_list_models_keeps_only_text_generation_models() -> None:
    p, _, _ = provider([])
    assert p.list_models() == ["gemini-3.6-flash"]


def test_agent_request_is_unaffected_by_provider_choice() -> None:
    assert AgentRequest(snippet="x = 1").snippet == "x = 1"


def test_a_quota_message_keeps_the_limit_that_follows_a_long_preamble() -> None:
    from marl_agents.llm.gemini import classify_failure

    message = "x" * 280 + " Quota exceeded for metric: requests, limit: 20, model: m"
    failure = classify_failure(Exception(message))
    assert "limit: 20" in failure.detail
