"""Ollama provider, offline: a fake HTTP layer stands in for the local server."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from marl_agents.config import DEFAULT_OLLAMA_MODEL, LLMSettings, Settings, load_settings, model_for
from marl_agents.llm import Message
from marl_agents.llm.base import GenerationConfig, LLMError, RequestTooLargeError
from marl_agents.llm.factory import create_provider
from marl_agents.llm.ollama import OllamaProvider, base_url_of

MSGS = [Message(role="system", content="sys"), Message(role="user", content="hi")]


class Ping(BaseModel):
    status: str


class FakeResponse(io.BytesIO):
    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_a: object) -> None:
        self.close()


class FakeOllama:
    """Records each request and answers from a queue (dicts, or exceptions to raise)."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.requests: list[Any] = []

    def __call__(self, request: Any, timeout: float) -> FakeResponse:
        self.requests.append((request, timeout))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return FakeResponse(json.dumps(answer).encode("utf-8"))

    def body(self, i: int = -1) -> dict[str, Any]:
        return json.loads(self.requests[i][0].data.decode("utf-8"))


def chat(content: str = '{"status": "ok"}', **extra: Any) -> dict[str, Any]:
    return {
        "model": "qwen2.5-coder:7b",
        "message": {"role": "assistant", "content": content},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 40,
        "eval_count": 7,
        **extra,
    }


def provider(fake: FakeOllama, **kw: Any) -> OllamaProvider:
    return OllamaProvider(model="qwen2.5-coder:7b", opener=fake, **kw)


def test_a_reply_carries_text_tokens_and_timing() -> None:
    fake = FakeOllama(chat())
    reply = provider(fake).generate(MSGS)
    assert reply.text == '{"status": "ok"}'
    assert (reply.input_tokens, reply.output_tokens) == (40, 7)
    assert reply.latency_s is not None and reply.finish_reason == "stop"


def test_the_request_sets_the_context_window_json_mode_and_generation_settings() -> None:
    fake = FakeOllama(chat())
    cfg = GenerationConfig(temperature=0.0, max_tokens=512, seed=7)
    provider(fake, context_window=8192, extra_options={"num_thread": 6}).generate(MSGS, cfg)
    body = fake.body()
    assert body["stream"] is False and body["format"] == "json"
    assert body["options"] == {
        "temperature": 0.0, "num_predict": 512, "num_ctx": 8192, "num_thread": 6, "seed": 7,
    }  # fmt: skip
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert fake.requests[-1][0].full_url == "http://localhost:11434/api/chat"


def test_no_credential_is_ever_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "a-secret-gemini-key")
    fake = FakeOllama(chat())
    provider(fake).generate(MSGS)
    request = fake.requests[-1][0]
    assert {k.lower() for k in request.headers} == {"content-type"}
    assert b"a-secret-gemini-key" not in request.data


def test_structured_output_validates_with_the_pydantic_schema() -> None:
    assert provider(FakeOllama(chat())).generate_structured(MSGS, Ping).status == "ok"


def test_malformed_json_is_retried_once_with_the_error_then_fails() -> None:
    fake = FakeOllama(chat("not json"), chat("still not json"))
    with pytest.raises(LLMError, match="Structured output failed"):
        provider(fake).generate_structured(MSGS, Ping)
    assert len(fake.requests) == 2
    assert "did not match the required JSON schema" in fake.body()["messages"][-1]["content"]


def test_a_cut_off_reply_is_not_retried() -> None:
    fake = FakeOllama(chat('{"stat', done_reason="length"))
    with pytest.raises(LLMError, match="cut off"):
        provider(fake).generate_structured(MSGS, Ping)
    assert len(fake.requests) == 1


def test_a_prompt_too_long_for_the_window_is_refused_before_sending() -> None:
    fake = FakeOllama()
    big = [Message(role="user", content="x" * 40_000)]
    with pytest.raises(RequestTooLargeError, match="context window"):
        provider(fake, context_window=4096).generate(big)
    assert fake.requests == []


def test_a_reply_that_filled_the_window_is_refused() -> None:
    fake = FakeOllama(chat(prompt_eval_count=4096))
    with pytest.raises(RequestTooLargeError, match="may have been cut"):
        provider(fake, context_window=4096).generate(MSGS)


def _http_error(code: int, message: str) -> urllib.error.HTTPError:
    body = io.BytesIO(json.dumps({"error": message}).encode("utf-8"))
    return urllib.error.HTTPError("http://x", code, message, {}, body)  # type: ignore[arg-type]


def test_a_missing_model_says_how_to_install_it_and_is_not_retried() -> None:
    fake = FakeOllama(_http_error(404, "model 'qwen2.5-coder:7b' not found"))
    with pytest.raises(LLMError, match=r"ollama pull qwen2\.5-coder:7b") as exc:
        provider(fake).generate(MSGS)
    assert len(fake.requests) == 1
    assert exc.value.attempts and exc.value.attempts[0].error_kind == "fatal"


def test_ollama_not_running_is_a_clear_error_without_retries() -> None:
    fake = FakeOllama(urllib.error.URLError(ConnectionRefusedError(10061, "refused")))
    with pytest.raises(LLMError, match="Cannot reach Ollama"):
        provider(fake).generate(MSGS)
    assert len(fake.requests) == 1


def test_a_timeout_names_the_setting_to_raise() -> None:
    fake = FakeOllama(TimeoutError("timed out"))
    with pytest.raises(LLMError, match=r"llm\.timeout_s"):
        provider(fake, timeout=30).generate(MSGS)


def test_a_server_error_is_reported() -> None:
    fake = FakeOllama(_http_error(500, "out of memory"))
    with pytest.raises(LLMError, match=r"HTTP 500: out of memory"):
        provider(fake).generate(MSGS)


def test_models_are_listed_and_a_missing_one_is_explained() -> None:
    tags = {"models": [{"name": "qwen2.5-coder:7b"}, {"name": "llama3:8b"}]}
    p = provider(FakeOllama(tags, tags))
    assert p.list_models() == ["llama3:8b", "qwen2.5-coder:7b"]
    p.ensure_model()
    with pytest.raises(LLMError, match=r"ollama pull missing:1b"):
        OllamaProvider(model="missing:1b", opener=FakeOllama(tags)).ensure_model()


@pytest.mark.parametrize(
    ("given", "root"),
    [(None, "http://localhost:11434"), ("http://localhost:11434/v1", "http://localhost:11434"),
     ("http://box:1234/", "http://box:1234")],
)  # fmt: skip
def test_base_url_accepts_both_forms(given: str | None, root: str) -> None:
    assert base_url_of(given) == root


# ---- configuration ------------------------------------------------------------------------------


def test_switching_to_ollama_never_keeps_a_hosted_model_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    assert model_for("ollama", "gemini-3.6-flash") == DEFAULT_OLLAMA_MODEL
    assert model_for("ollama", "openai/gpt-oss-120b") == DEFAULT_OLLAMA_MODEL
    assert model_for("ollama", None) == DEFAULT_OLLAMA_MODEL
    assert model_for("ollama", "llama3:8b") == "llama3:8b"
    monkeypatch.setenv("OLLAMA_MODEL", "codellama:7b")
    assert model_for("ollama", "llama3:8b") == "codellama:7b"


def test_gemini_selection_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert model_for("gemini", "qwen2.5-coder:7b").startswith("gemini")
    assert model_for("gemini", "gemini-3.6-flash") == "gemini-3.6-flash"
    assert model_for("groq", "openai/gpt-oss-120b") == "openai/gpt-oss-120b"


def test_the_ollama_config_file_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    s = load_settings(Path("configs/ollama.yaml"))
    assert (s.llm.provider, s.llm.model) == ("ollama", "qwen2.5-coder:7b")
    assert s.llm.context_window == 16384 and s.llm.timeout_s == 900


def test_the_factory_builds_ollama_without_reading_any_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    llm = create_provider(
        LLMSettings(provider="ollama", model="qwen2.5-coder:7b", context_window=8192, timeout_s=5)
    )
    assert isinstance(llm, OllamaProvider)
    assert (llm.name, llm.context_window, llm.timeout) == ("ollama", 8192, 5)


def test_the_cli_provider_switch_brings_the_right_model(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from marl_agents import cli

    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    args = cli.main.__globals__["argparse"].Namespace(
        config=None, mode=None, provider="ollama", model=None, base_url=None, rpm=None, tpm=None,
        no_rag=False, no_structural=False, store=None, embedder=None, min_confidence=None,
        concurrency=None, classifier=None, classifier_mode=None, no_cache=False,
    )  # fmt: skip
    s = cli.build_settings(args)
    assert (s.llm.provider, s.llm.model) == ("ollama", DEFAULT_OLLAMA_MODEL)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://box", "localhost:11434"])
def test_only_http_urls_are_accepted(url: str) -> None:
    with pytest.raises(LLMError, match="must start with http"):
        base_url_of(url)


# ---- switching provider for one request (dashboard) -------------------------------------------


def test_with_provider_builds_ollama_settings_from_its_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marl_agents.config import Settings, with_provider

    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    server = Settings()
    server.llm.provider, server.llm.model = "gemini", "gemini-3.6-flash"
    server.llm.requests_per_day = 20
    s = with_provider(server, "ollama")
    assert (s.llm.provider, s.llm.model) == ("ollama", "qwen2.5-coder:7b")
    assert s.llm.requests_per_day is None and s.llm.context_window == 16384
    assert s.review.concurrency == 1
    assert server.llm.provider == "gemini"  # the server's settings are untouched


def test_with_provider_back_to_gemini_keeps_its_quota_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marl_agents.config import Settings, with_provider

    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    server = Settings()
    server.llm.provider, server.llm.model = "ollama", "qwen2.5-coder:7b"
    s = with_provider(server, "gemini")
    assert s.llm.provider == "gemini" and str(s.llm.model).startswith("gemini")
    assert s.llm.requests_per_day == 20  # the daily ledger stays on for the free tier


def test_with_provider_rejects_other_providers() -> None:
    from marl_agents.config import Settings, with_provider

    with pytest.raises(ValueError, match="provider must be one of"):
        with_provider(Settings(), "openai")
