"""The smoke test's own logic, offline. Its live results come only from a real run."""

from __future__ import annotations

import os
from typing import Any

import pytest

from marl_agents.config import LLMSettings, Settings
from marl_agents.evaluation.gemini_smoke import (
    INVALID_KEY_VALUE,
    INVALID_KEY_VARIABLE,
    run_smoke,
    summary_md,
)
from marl_agents.llm import Message, MockLLMProvider
from marl_agents.llm.base import CallAttempt, GenerationConfig, LLMError, LLMResponse
from tests.conftest import llm_json

SECRET = "a-real-looking-secret"


def attempt(kind: str, status: int | None = None) -> CallAttempt:
    return CallAttempt(started_at=0.0, latency_s=0.01, status=status, error_kind=kind)


class FakeGemini(MockLLMProvider):
    name = "gemini"

    def __init__(self, llm: LLMSettings, models: list[str]) -> None:
        super().__init__(
            responder=lambda m: '{"status": "ok"}' if "status" in m[-1].content else llm_json()
        )
        self.model = llm.model
        self.invalid = llm.api_key_env == INVALID_KEY_VARIABLE
        self.times_out = llm.timeout_s < 1
        self.models = models

    def list_models(self) -> list[str]:
        return self.models

    def generate(
        self, messages: list[Message], config: GenerationConfig | None = None
    ) -> LLMResponse:
        if self.invalid:
            raise LLMError("gemini request rejected (400): bad key", [attempt("fatal", 400)])
        if self.times_out:
            raise LLMError("failed", [attempt("transient"), attempt("transient")])
        return super().generate(messages, config)


def factory(models: list[str] | None = None, made: list[Any] | None = None) -> Any:
    def build(llm: LLMSettings) -> Any:
        variable = llm.api_key_env or "GEMINI_API_KEY"
        if not (os.environ.get(variable) or os.environ.get("GOOGLE_API_KEY")):
            raise LLMError("GEMINI_API_KEY is not set")
        provider = FakeGemini(llm, ["gemini-3.8-flash"] if models is None else models)
        if made is not None:
            made.append(provider)
        return provider

    return build


@pytest.fixture
def gemini(settings: Settings) -> Settings:
    settings.llm.provider = "gemini"
    settings.llm.model = "gemini-3.8-flash"
    return settings


def named(checks: list[Any]) -> dict[str, Any]:
    return {c.name: c for c in checks}


def test_no_key_stops_before_any_provider_exists(gemini: Settings) -> None:
    made: list[Any] = []
    checks = named(run_smoke(gemini, factory(made=made)))
    assert checks["missing_key"].passed is True
    assert checks["key"].passed is False
    assert made == []


def test_the_fallback_key_is_never_used_without_permission(
    gemini: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", SECRET)
    made: list[Any] = []
    checks = named(run_smoke(gemini, factory(made=made)))
    assert checks["key"].passed is False
    assert "--allow-google-api-key" in checks["key"].detail
    assert made == []
    assert named(run_smoke(gemini, factory(), allow_google_key=True))["key"].passed is True


def test_an_unavailable_model_is_reported_and_never_replaced(
    gemini: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    made: list[Any] = []
    checks = run_smoke(gemini, factory(["gemini-3.6-flash"], made))
    last = checks[-1]
    assert (last.name, last.passed) == ("model_access", False)
    assert "gemini-3.6-flash" in last.detail and "Not switching" in last.detail
    assert gemini.llm.model == "gemini-3.8-flash"
    assert all(not p.calls for p in made)


def test_a_full_run_labels_what_was_live_and_what_was_simulated(
    gemini: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    checks = named(run_smoke(gemini, factory()))
    for name in (
        "model_access",
        "json_and_schema",
        "agent_review",
        "invalid_key",
        "failed_request_is_safe",
        "timeout_and_retry",
    ):
        assert (checks[name].kind, checks[name].passed) == ("live", True), name
    for name in ("rate_limit_429", "daily_quota"):
        assert (checks[name].kind, checks[name].passed) == ("simulated", None)


def test_keys_never_reach_the_report_and_the_environment_is_restored(
    gemini: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    md = summary_md(run_smoke(gemini, factory()), gemini.llm.model)
    assert SECRET not in md and INVALID_KEY_VALUE not in md
    assert "variable: GEMINI_API_KEY" in md
    assert INVALID_KEY_VARIABLE not in os.environ
    assert os.environ["GEMINI_API_KEY"] == SECRET
