"""A real, very small Gemini call. Skipped unless asked for and a key is configured:

    pytest -m llm tests/integration/test_gemini_live.py

Uses a single request of the free quota. Everything else in the suite is offline.
"""

from __future__ import annotations

import os

import pytest
from pydantic import BaseModel

from marl_agents.config import PROJECT_ROOT, load_dotenv, load_settings
from marl_agents.llm import Message
from marl_agents.llm.base import QuotaExhaustedError
from marl_agents.llm.factory import create_provider

pytestmark = pytest.mark.llm


class Ping(BaseModel):
    status: str


@pytest.fixture
def real_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MARL_NO_DOTENV", raising=False)
    load_dotenv(PROJECT_ROOT / ".env")
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        pytest.skip("no Gemini key configured")


def test_one_real_request_returns_valid_json_and_usage(real_env: None) -> None:
    settings = load_settings()
    settings.llm.provider = "gemini"
    settings.llm.model = os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash"
    llm = create_provider(settings.llm)
    messages = [
        Message(role="system", content="Reply with a JSON object only."),
        Message(role="user", content='Return exactly this JSON: {"status": "ok"}'),
    ]
    try:
        reply = llm.generate_structured(messages, Ping)
    except QuotaExhaustedError as exc:
        pytest.skip(f"free quota unavailable right now: {exc}")
    assert reply.status == "ok"
    assert llm.usage.input_tokens > 0 and llm.usage.output_tokens > 0
