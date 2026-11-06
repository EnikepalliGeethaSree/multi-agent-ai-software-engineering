import pytest
from pydantic import BaseModel

from marl_agents.config import LLMSettings, load_settings
from marl_agents.llm import LLMError, Message, MockLLMProvider
from marl_agents.llm.factory import create_provider


class Answer(BaseModel):
    value: int


def user(text: str) -> list[Message]:
    return [Message(role="user", content=text)]


def test_mock_returns_canned_responses_in_order_and_records_calls() -> None:
    llm = MockLLMProvider(responses=["first", "second"])
    assert llm.generate(user("a")).text == "first"
    assert llm.generate(user("b")).text == "second"
    assert llm.generate(user("c")).text == '{"findings": []}'
    assert [c[0].content for c in llm.calls] == ["a", "b", "c"]


def test_generate_structured_parses_fenced_json() -> None:
    llm = MockLLMProvider(responses=['```json\n{"value": 3}\n```'])
    assert llm.generate_structured(user("q"), Answer).value == 3


def test_generate_structured_retries_once_with_error_feedback() -> None:
    llm = MockLLMProvider(responses=["not json", '{"value": 7}'])
    assert llm.generate_structured(user("q"), Answer).value == 7
    assert len(llm.calls) == 2
    assert "did not match" in llm.calls[1][-1].content


def test_generate_structured_raises_after_retries() -> None:
    llm = MockLLMProvider(responses=["nope", "still nope"])
    with pytest.raises(LLMError):
        llm.generate_structured(user("q"), Answer)


def test_factory_builds_mock_and_requires_model_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    assert isinstance(create_provider(LLMSettings(provider="mock")), MockLLMProvider)
    with pytest.raises(LLMError, match=r"llm.model"):
        create_provider(LLMSettings(provider="openai"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMError, match="OPENAI_API_KEY"):
        create_provider(LLMSettings(provider="openai", model="gpt-x"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        create_provider(LLMSettings(provider="gemini", model="gemini-x"))


def test_default_config_uses_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MARL_LLM__PROVIDER", raising=False)
    settings = load_settings()
    assert settings.llm.provider == "gemini"
    assert settings.rag.top_k > 0


def test_env_var_overrides_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARL_RAG__ENABLED", "false")
    assert load_settings().rag.enabled is False
