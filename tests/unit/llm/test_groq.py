"""Groq support: factory wiring, rate limiting, 429 handling, JSON-mode fallback, reasoning output."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from marl_agents.config import LLMSettings, load_dotenv, load_settings
from marl_agents.llm import LLMError, Message
from marl_agents.llm.base import _strip_code_fence
from marl_agents.llm.factory import GROQ_BASE_URL, create_provider
from marl_agents.llm.openai_compat import OpenAICompatibleProvider, _retry_after
from marl_agents.llm.rate_limit import RateLimiter

MSGS = [Message(role="user", content="hi")]


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.now += s


class APIError(Exception):
    """Mimics openai.APIStatusError: status_code + response.headers."""

    def __init__(self, msg: str, status: int, headers: dict[str, str] | None = None) -> None:
        super().__init__(msg)
        self.status_code = status
        self.response = SimpleNamespace(headers=headers or {})


def fake_client(replies: list[Any]) -> tuple[Any, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    def create(**kwargs: Any) -> Any:
        calls.append(kwargs)
        r = replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=r))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
            model="m",
        )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        models=SimpleNamespace(
            list=lambda: SimpleNamespace(data=[SimpleNamespace(id="b"), SimpleNamespace(id="a")])
        ),
    )
    return client, calls


# ---- factory -------------------------------------------------------------------------------------


def test_factory_builds_groq_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("openai")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    p = create_provider(LLMSettings(provider="groq", model="some-model", extra_params={"x": 1}))
    assert isinstance(p, OpenAICompatibleProvider) and p.name == "groq"
    assert str(p._client.base_url).rstrip("/") == GROQ_BASE_URL
    assert p.limiter.rpm == 30 and p.limiter.tpm == 6000  # safe defaults when unset
    assert p.extra_params == {"x": 1}
    custom = create_provider(
        LLMSettings(provider="groq", model="m", requests_per_minute=5, tokens_per_minute=900)
    )
    assert custom.limiter.rpm == 5 and custom.limiter.tpm == 900  # type: ignore[attr-defined]


def test_factory_groq_errors_are_actionable() -> None:
    with pytest.raises(LLMError, match="cli models"):
        create_provider(LLMSettings(provider="groq"))
    with pytest.raises(LLMError, match="GROQ_API_KEY"):
        create_provider(LLMSettings(provider="groq", model="m"))


def test_groq_overlay_config_layers_on_default() -> None:
    s = load_settings(Path(__file__).parents[3] / "configs" / "groq.yaml")
    assert s.llm.provider == "groq" and s.llm.requests_per_minute == 30
    assert s.review.concurrency == 2 and s.rag.max_context_chars == 8000
    assert s.rag.top_k == 6  # untouched keys still come from default.yaml


def test_dotenv_exports_keys_without_overriding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "# comment\nGROQ_API_KEY='gsk_from_file'\nexport OTHER_VAR=1\nEMPTY=\nKEEP=file\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("MARL_NO_DOTENV")
    monkeypatch.delenv("OTHER_VAR", raising=False)
    monkeypatch.delenv("EMPTY", raising=False)
    monkeypatch.setenv("KEEP", "shell")
    load_dotenv(env)
    import os

    assert os.environ["GROQ_API_KEY"] == "gsk_from_file"
    assert os.environ["OTHER_VAR"] == "1"
    assert "EMPTY" not in os.environ
    assert os.environ["KEEP"] == "shell"  # real environment wins
    monkeypatch.delenv("GROQ_API_KEY")
    monkeypatch.delenv("OTHER_VAR")


# ---- rate limiter ----------------------------------------------------------------------------------


def test_rate_limiter_enforces_requests_per_minute() -> None:
    clock = FakeClock()
    rl = RateLimiter(requests_per_minute=2, clock=clock, sleep=clock.sleep)
    rl.acquire(1)
    rl.acquire(1)
    rl.acquire(1)  # third request must wait for the first to leave the 60 s window
    assert clock.now == pytest.approx(60.0)


def test_rate_limiter_enforces_tokens_per_minute_and_settles() -> None:
    clock = FakeClock()
    rl = RateLimiter(tokens_per_minute=1000, clock=clock, sleep=clock.sleep)
    first = rl.acquire(600)
    rl.settle(first, 900)  # real usage was higher than estimated
    clock.now = 10.0
    rl.acquire(200)  # 900 + 200 > 1000 -> waits until t = 60
    assert clock.now == pytest.approx(60.0)
    assert rl.usage_last_minute == (1, 200)


def test_rate_limiter_lets_oversized_request_through_alone() -> None:
    clock = FakeClock()
    rl = RateLimiter(tokens_per_minute=100, clock=clock, sleep=clock.sleep)
    rl.acquire(5000)  # bigger than the whole budget: allowed on an empty window
    assert clock.now == 0.0


def test_pause_blocks_all_callers() -> None:
    clock = FakeClock()
    rl = RateLimiter(clock=clock, sleep=clock.sleep)
    rl.pause(7.5)
    rl.acquire(1)
    assert clock.now == pytest.approx(7.5)


# ---- provider behaviour against Groq-style errors -------------------------------------------------


def test_429_honours_retry_after_then_succeeds() -> None:
    clock = FakeClock()
    client, calls = fake_client([APIError("Rate limit reached", 429, {"retry-after": "3"}), "{}"])
    p = OpenAICompatibleProvider(
        "m",
        client=client,
        rate_limiter=RateLimiter(clock=clock, sleep=clock.sleep),
        sleep=clock.sleep,
    )
    assert p.generate(MSGS).text == "{}"
    assert len(calls) == 2 and p.rate_limited == 1 and clock.now == pytest.approx(3.0)


def test_retry_after_parsed_from_groq_message() -> None:
    assert _retry_after(Exception("Please try again in 7.66s. Visit ...")) == pytest.approx(7.66)
    assert _retry_after(Exception("Please try again in 350ms")) == pytest.approx(0.35)
    assert _retry_after(Exception("no hint")) is None


def test_json_validate_failed_falls_back_to_plain_mode() -> None:
    err = APIError("Error code: 400 - {'error': {'code': 'json_validate_failed'}}", 400)
    client, calls = fake_client([err, '{"ok": 1}'])
    p = OpenAICompatibleProvider("m", client=client, sleep=lambda _s: None)
    assert p.generate(MSGS).text == '{"ok": 1}'
    assert "response_format" in calls[0] and "response_format" not in calls[1]


def test_auth_error_is_not_retried() -> None:
    client, calls = fake_client([APIError("Invalid API Key", 401)] * 5)
    p = OpenAICompatibleProvider("m", client=client, sleep=lambda _s: None)
    with pytest.raises(LLMError, match="Invalid API Key"):
        p.generate(MSGS)
    assert len(calls) == 1


def test_extra_params_sent_as_extra_body_and_usage_settled() -> None:
    clock = FakeClock()
    rl = RateLimiter(tokens_per_minute=10_000, clock=clock, sleep=clock.sleep)
    client, calls = fake_client(["{}"])
    p = OpenAICompatibleProvider(
        "m", client=client, rate_limiter=rl, extra_params={"reasoning_format": "hidden"}
    )
    p.generate(MSGS)
    assert calls[0]["extra_body"] == {"reasoning_format": "hidden"}
    assert rl.usage_last_minute == (1, 120)  # estimate replaced by real 100 + 20 tokens


def test_list_models_sorted() -> None:
    client, _ = fake_client([])
    assert OpenAICompatibleProvider("m", client=client).list_models() == ["a", "b"]


# ---- reasoning-model output cleanup ------------------------------------------------------------------


class Out(BaseModel):
    status: str


@pytest.mark.parametrize(
    "raw",
    [
        '<think>Let me reason about {braces}...</think>\n{"status": "ok"}',
        'Sure! Here is the JSON:\n```json\n{"status": "ok"}\n```\nHope that helps.',
        'Here you go: {"status": "ok"} - done',
        '<think>unterminated reasoning {"status": "no"}',
    ],
)
def test_json_extraction_from_messy_replies(raw: str) -> None:
    cleaned = _strip_code_fence(raw)
    if "unterminated" in raw:
        assert cleaned == ""
    else:
        assert Out.model_validate_json(cleaned).status == "ok"


# ---- server-reported quota (x-ratelimit-* headers) ----------------------------------------------


def test_parse_groq_durations() -> None:
    from marl_agents.llm.openai_compat import parse_duration

    assert parse_duration("577ms") == pytest.approx(0.577)
    assert parse_duration("7.66s") == pytest.approx(7.66)
    assert parse_duration("1m26.4s") == pytest.approx(86.4)
    assert parse_duration("43m12s") == pytest.approx(2592)
    assert parse_duration("2h") == pytest.approx(7200)
    assert (
        parse_duration("") is None
        and parse_duration("soon") is None
        and parse_duration(None) is None
    )


def _raw_client(headers: list[dict[str, str]]) -> Any:
    def create(**kwargs: Any) -> Any:
        h = headers.pop(0)
        parsed = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
            model="m",
        )
        return SimpleNamespace(headers=h, parse=lambda: parsed)

    completions = SimpleNamespace(
        create=lambda **kw: pytest.fail("raw responses must be used when available"),
        with_raw_response=SimpleNamespace(create=create),
    )
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


def test_provider_follows_server_quota_headers() -> None:
    clock = FakeClock()
    limiter = RateLimiter(30, 6000, clock=clock, sleep=clock.sleep)
    low = {"x-ratelimit-remaining-tokens": "500", "x-ratelimit-reset-tokens": "7.5s"}
    plenty = {"x-ratelimit-remaining-tokens": "7900", "x-ratelimit-reset-tokens": "100ms"}
    p = OpenAICompatibleProvider(
        model="m", client=_raw_client([low, plenty, plenty]), rate_limiter=limiter
    )
    assert p.generate(MSGS).text == "ok"
    assert clock.slept == []  # first call goes immediately
    p.generate(MSGS)  # quota was reported low: waits for the server's reset
    assert clock.slept == [pytest.approx(7.5)]
    p.generate(MSGS)  # plenty left: no wait
    assert clock.slept == [pytest.approx(7.5)]


def test_missing_or_garbled_quota_headers_are_ignored() -> None:
    clock = FakeClock()
    limiter = RateLimiter(None, None, clock=clock, sleep=clock.sleep)
    p = OpenAICompatibleProvider(
        model="m",
        client=_raw_client([{}, {"x-ratelimit-remaining-tokens": "n/a"}, {}]),
        rate_limiter=limiter,
    )
    for _ in range(3):
        p.generate(MSGS)
    assert clock.slept == []


def test_daily_quota_fails_fast_with_a_clear_message() -> None:
    clock = FakeClock()
    msg = (
        "Error code: 429 - Rate limit reached for model `openai/gpt-oss-120b` in organization "
        "`org_secret123` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used "
        "199471, Requested 3744. Please try again in 23m8.88s. Need more tokens? Upgrade today"
    )
    client, calls = fake_client([APIError(msg, 429, {"retry-after": "1389"}), "never reached"])
    p = OpenAICompatibleProvider(
        model="openai/gpt-oss-120b",
        client=client,
        name="groq",
        rate_limiter=RateLimiter(30, 6000, clock=clock, sleep=clock.sleep),
    )
    with pytest.raises(LLMError) as err:
        p.generate(MSGS)
    text = str(err.value)
    assert "groq daily quota reached for model openai/gpt-oss-120b" in text
    assert "about 23 min" in text and "tokens per day" in text
    assert "org_secret123" not in text and "Upgrade" not in text
    assert len(calls) == 1 and clock.slept == []  # no pointless retries


@pytest.mark.parametrize(
    ("status", "msg"),
    [
        (
            413,
            "Request too large for model `q` in organization `org_x`: Limit 6000, Requested 9000",
        ),
        (429, "Request too large for model `q` in organization `org_x` on tokens per minute"),
    ],
)
def test_request_too_large_is_not_retried(status: int, msg: str) -> None:
    from marl_agents.llm import RequestTooLargeError

    clock = FakeClock()
    client, calls = fake_client([APIError(msg, status), "never"])
    p = OpenAICompatibleProvider(
        model="q", client=client, rate_limiter=RateLimiter(30, 6000, clock=clock, sleep=clock.sleep)
    )
    with pytest.raises(RequestTooLargeError) as err:
        p.generate(MSGS)
    assert len(calls) == 1 and clock.slept == [] and "org_x" not in str(err.value)
