"""Single-key Groq provider (D39): fake HTTP layer and fake clock; no network, no real key."""

from __future__ import annotations

import json
import logging
import random
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

httpx = pytest.importorskip("httpx")

from marl_agents.config import LLMSettings, apply_groq_env, load_settings  # noqa: E402
from marl_agents.llm.base import (  # noqa: E402
    GenerationConfig,
    LLMError,
    Message,
    QuotaExhaustedError,
    RequestTooLargeError,
    Usage,
)
from marl_agents.llm.budget import Prices, UsageBudget, worst_case_input_tokens  # noqa: E402
from marl_agents.llm.factory import create_provider  # noqa: E402
from marl_agents.llm.groq import GroqProvider, scrub  # noqa: E402
from marl_agents.llm.rate_limit import (  # noqa: E402
    DailyQuota,
    RateLimiter,
    next_utc_midnight,
    utc_date,
)
from marl_agents.llm.response_cache import ResponseCache, cache_key  # noqa: E402

MSGS = [Message(role="user", content="review this")]
SECRET = "gsk_TESTSECRET0123456789abcdef"
NOON = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)

Reply = int | tuple[int, dict[str, str], str]


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.slept.append(round(s, 3))
        self.now += s


class FakeGroq:
    """The fake HTTP layer: checks the key is sent, records requests, answers from a script."""

    def __init__(
        self, script: Callable[[int], Reply] | None = None, usage: tuple[int, int] = (100, 20)
    ) -> None:
        self.bodies: list[dict[str, Any]] = []
        self.script = script or (lambda n: 200)
        self.usage = usage

    def handler(self, request: Any) -> Any:
        assert request.headers["Authorization"] == f"Bearer {SECRET}"
        self.bodies.append(json.loads(request.content))
        reply = self.script(len(self.bodies))
        status, headers, text = (reply, {}, "") if isinstance(reply, int) else reply
        if status == 200 and not text:
            text = json.dumps({
                "model": "openai/gpt-oss-120b",
                "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": self.usage[0], "completion_tokens": self.usage[1]},
            })  # fmt: skip
        return httpx.Response(status, headers=headers, text=text)

    def client(self) -> Any:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def provider(
    fake: FakeGroq,
    clock: Clock | None = None,
    limiter: RateLimiter | None = None,
    budget: UsageBudget | None = None,
    daily: DailyQuota | None = None,
    cache: ResponseCache | None = None,
    now: Callable[[], datetime] = lambda: NOON,
) -> GroqProvider:
    clock = clock or Clock()
    return GroqProvider(
        "openai/gpt-oss-120b", SECRET, client=fake.client(), sleep=clock.sleep,
        limiter=limiter or RateLimiter(clock=clock, sleep=clock.sleep), budget=budget,
        daily=daily, cache=cache, rng=random.Random(0), now=now,
    )  # fmt: skip


# ---- configuration ----------------------------------------------------------------------------------


def test_single_key_configuration_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name, value in {
        "GROQ_API_KEY": SECRET, "GROQ_MODEL": "openai/gpt-oss-120b", "GROQ_RPM": "40",
        "GROQ_TPM": "250,000", "GROQ_DAILY_REQUEST_LIMIT": "TBD", "GROQ_MAX_TOTAL_TOKENS": "2000000",
        "GROQ_MAX_ESTIMATED_COST_USD": "5", "GROQ_INPUT_PRICE_PER_1M_TOKENS_USD": "0.15",
        "GROQ_OUTPUT_PRICE_PER_1M_TOKENS_USD": "0.60", "GROQ_MAX_RETRIES": "5",
        "GROQ_BASE_BACKOFF_SECONDS": "2",
    }.items():  # fmt: skip
        monkeypatch.setenv(name, value)
    s = load_settings(Path(__file__).parents[3] / "configs" / "groq.yaml")
    llm = s.llm
    assert (llm.requests_per_minute, llm.tokens_per_minute) == (40, 250_000)
    assert llm.requests_per_day is None  # TBD = not set
    assert llm.max_total_tokens == 2_000_000 and llm.max_estimated_cost_usd == 5.0
    assert llm.input_price_per_1m_tokens_usd == 0.15 and llm.output_price_per_1m_tokens_usd == 0.6
    llm.response_cache = False
    p = create_provider(llm)
    assert isinstance(p, GroqProvider) and SECRET not in repr(p)
    assert p.limiter.rpm == 40 and p.budget is not None and p.budget.max_cost_usd == 5.0


def test_bad_number_in_env_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_RPM", "fast")
    with pytest.raises(ValueError, match="GROQ_RPM"):
        apply_groq_env(LLMSettings(provider="groq"))


def test_old_numbered_keys_are_not_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY_1", "gsk_old")
    with pytest.raises(LLMError, match="GROQ_API_KEY is not set"):
        create_provider(LLMSettings(provider="groq", model="m", max_total_tokens=10))


def test_missing_key_fails_clearly() -> None:
    with pytest.raises(LLMError, match="GROQ_API_KEY is not set"):
        GroqProvider("m", "")


# ---- request ---------------------------------------------------------------------------------------


def test_request_is_deterministic_and_sends_the_key_only_in_the_header() -> None:
    fake = FakeGroq()
    r = provider(fake).generate(MSGS)
    body = fake.bodies[0]
    assert (
        body["temperature"] == 0.0 and body["seed"] == 42 and body["model"] == "openai/gpt-oss-120b"
    )
    assert SECRET not in json.dumps(body)
    assert (r.input_tokens, r.output_tokens, r.cache_hit) == (100, 20, False)
    assert r.latency_s is not None and r.latency_s >= 0


def test_request_pacing_per_minute() -> None:
    clock = Clock()
    p = provider(FakeGroq(), clock, RateLimiter(2, None, clock=clock, sleep=clock.sleep))
    p.generate(MSGS)
    p.generate(MSGS)
    assert clock.slept == []
    p.generate(MSGS)
    assert clock.slept and clock.slept[0] == pytest.approx(60.0)


def test_token_pacing_per_minute() -> None:
    clock = Clock()
    p = provider(
        FakeGroq(usage=(900, 50)), clock, RateLimiter(None, 1000, clock=clock, sleep=clock.sleep)
    )
    p.generate(MSGS)  # 950 real tokens now count in the window
    p.generate(MSGS)
    assert clock.slept and clock.slept[0] == pytest.approx(60.0)


def test_headers_update_limits_and_block_when_requests_are_spent() -> None:
    clock = Clock()
    headers = {
        "x-ratelimit-limit-requests": "14400", "x-ratelimit-limit-tokens": "250000",
        "x-ratelimit-remaining-requests": "0", "x-ratelimit-reset-requests": "2m0s",
        "x-ratelimit-remaining-tokens": "249000",
    }  # fmt: skip
    daily = DailyQuota(None, None, None, clock=lambda: NOON, day_of=utc_date,
                       next_reset=next_utc_midnight)  # fmt: skip
    p = provider(FakeGroq(lambda n: (200, headers, "")), clock, daily=daily)
    p.generate(MSGS)
    assert p.limiter.tpm == 250_000 and daily.rpd == 14400  # the organization's real limits
    with pytest.raises(QuotaExhaustedError) as err:
        p.generate(MSGS)  # the server said no requests are left
    assert err.value.resets_at is not None


def test_low_remaining_tokens_pause_pacing() -> None:
    clock = Clock()
    headers = {"x-ratelimit-remaining-tokens": "100", "x-ratelimit-reset-tokens": "7.5s"}
    p = provider(FakeGroq(lambda n: (200, headers, "") if n == 1 else 200), clock)
    p.generate(MSGS)
    p.generate(MSGS)
    assert clock.slept and clock.slept[0] == pytest.approx(7.5)


# ---- 429, retries, failures -------------------------------------------------------------------------


def test_429_honours_retry_after() -> None:
    clock = Clock()
    fake = FakeGroq(lambda n: (429, {"retry-after": "7"}, "rate limit (RPM)") if n == 1 else 200)
    r = provider(fake, clock).generate(MSGS)
    assert r.text == '{"ok": true}' and len(fake.bodies) == 2
    assert clock.slept and clock.slept[0] == pytest.approx(7.0)
    assert r.attempts[0].error_kind == "rate_limit" and r.attempts[0].status == 429


def test_exponential_backoff_with_jitter_and_five_attempts() -> None:
    clock = Clock()
    fake = FakeGroq(lambda n: 503)
    p = provider(fake, clock)
    with pytest.raises(LLMError) as err:
        p.generate(MSGS)
    assert len(fake.bodies) == 5 and len(err.value.attempts) == 5
    assert len(clock.slept) == 4
    for attempt, wait in enumerate(clock.slept, start=1):
        base = min(2.0 * 2**attempt, 60.0)  # base backoff 2 s, doubled per attempt
        assert base / 2 <= wait <= base  # equal jitter


def test_429_without_retry_after_backs_off() -> None:
    clock = Clock()
    fake = FakeGroq(lambda n: (429, {}, "too many requests") if n < 3 else 200)
    provider(fake, clock).generate(MSGS)
    assert len(clock.slept) == 2 and all(0 < s <= 60 for s in clock.slept)


def test_daily_429_stops_with_a_reset_time_and_no_secret() -> None:
    body = (f"Rate limit reached for model `openai/gpt-oss-120b` in organization `org_abc123` on "
            f"tokens per day (TPD). Key {SECRET}. Please try again in 1h2m3s.")  # fmt: skip
    fake = FakeGroq(lambda n: (429, {"retry-after": "3723"}, body))
    with pytest.raises(QuotaExhaustedError) as err:
        provider(fake).generate(MSGS)
    assert len(fake.bodies) == 1 and err.value.resets_at is not None
    assert SECRET not in str(err.value) and "org_abc123" not in str(err.value)


def test_rejected_key_is_not_retried() -> None:
    fake = FakeGroq(lambda n: 401)
    with pytest.raises(LLMError, match="rejected GROQ_API_KEY"):
        provider(fake).generate(MSGS)
    assert len(fake.bodies) == 1


def test_request_too_large_and_bad_request_are_not_retried() -> None:
    with pytest.raises(RequestTooLargeError):
        provider(FakeGroq(lambda n: (413, {}, "Request too large"))).generate(MSGS)
    fake = FakeGroq(lambda n: (400, {}, "unknown model"))
    with pytest.raises(LLMError):
        provider(fake).generate(MSGS)
    assert len(fake.bodies) == 1


def test_json_mode_rejection_retries_once_without_it() -> None:
    fake = FakeGroq(lambda n: (400, {}, "json_validate_failed") if n == 1 else 200)
    provider(fake).generate(MSGS)
    assert "response_format" in fake.bodies[0] and "response_format" not in fake.bodies[1]


# ---- caps and checkpoint ----------------------------------------------------------------------------


def test_hard_token_cap_stops_before_it_could_be_exceeded(tmp_path: Path) -> None:
    budget = UsageBudget(tmp_path / "b.json", max_total_tokens=5000)
    fake = FakeGroq(usage=(1000, 500))
    p = provider(fake, budget=budget)
    cfg = GenerationConfig(max_tokens=1000)
    p.generate(MSGS, cfg)
    p.generate(MSGS, cfg)  # 3,000 used
    worst = worst_case_input_tokens(sum(len(m.content) for m in MSGS)) + 1000
    p.generate(MSGS, cfg)  # 3,000 + worst <= 5,000: allowed; 4,500 used
    with pytest.raises(QuotaExhaustedError, match="token cap"):
        p.generate(MSGS, cfg)  # 4,500 + worst > 5,000: refused, nothing sent
    assert len(fake.bodies) == 3 and budget.total_tokens == 4500 and worst > 500


def test_spending_cap_uses_input_and_output_prices(tmp_path: Path) -> None:
    prices = Prices(input_per_mtok=0.15, output_per_mtok=0.60)
    budget = UsageBudget(tmp_path / "b.json", prices, max_cost_usd=0.0015)
    fake = FakeGroq(usage=(4000, 1000))  # 0.0006 + 0.0006 = $0.0012 per call
    p = provider(fake, budget=budget)
    cfg = GenerationConfig(max_tokens=1000)
    p.generate(MSGS, cfg)
    st = budget.status()
    assert st["estimated_input_cost_usd"] == pytest.approx(0.0006)
    assert st["estimated_output_cost_usd"] == pytest.approx(0.0006)
    with pytest.raises(QuotaExhaustedError, match="spending cap"):
        p.generate(MSGS, cfg)  # 0.0012 + worst case 0.0006+ would pass $0.0015
    assert len(fake.bodies) == 1


def test_spending_cap_without_prices_is_refused() -> None:
    with pytest.raises(ValueError, match="PRICE_PER_1M"):
        UsageBudget(None, Prices(), max_cost_usd=1.0)


def test_usage_ledger_survives_a_restart_so_caps_hold_across_runs(tmp_path: Path) -> None:
    path = tmp_path / "budget.json"
    provider(FakeGroq(usage=(800, 200)), budget=UsageBudget(path, max_total_tokens=3000)).generate(
        MSGS, GenerationConfig(max_tokens=500)
    )
    again = UsageBudget(path, max_total_tokens=3000)  # a new process
    assert again.total_tokens == 1000 and again.requests == 1
    assert SECRET not in path.read_text(encoding="utf-8")


def test_cap_stop_is_a_checkpoint_error_the_agent_handles(settings, make_repo, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from marl_agents.agents.code_review import CodeReviewAgent
    from marl_agents.core.schemas import AgentRequest

    settings.review.mode = "llm_only"
    repo = make_repo({"a.py": "def f(x):\n    return x\n", "b.py": "def g(y):\n    return y\n"})
    budget = UsageBudget(tmp_path / "b.json", max_total_tokens=1)  # no request fits
    fake = FakeGroq()
    agent = CodeReviewAgent(provider(fake, budget=budget), settings=settings)
    result = agent.run(AgentRequest(repo_path=str(repo.root)))
    assert fake.bodies == []  # nothing was sent
    assert result.stats.get("quota") is not None  # the agent recorded a resumable stop


def test_configured_daily_limit_stops_cleanly() -> None:
    daily = DailyQuota(None, 1, None, clock=lambda: NOON, day_of=utc_date,
                       next_reset=next_utc_midnight)  # fmt: skip
    p = provider(FakeGroq(), daily=daily)
    p.generate(MSGS)
    with pytest.raises(QuotaExhaustedError, match="daily limit") as err:
        p.generate(MSGS)
    assert err.value.resets_at == "2026-11-11T00:00:00+00:00"


# ---- cache ------------------------------------------------------------------------------------------


def test_cache_hit_sends_nothing_and_costs_nothing(tmp_path: Path) -> None:
    fake = FakeGroq()
    budget = UsageBudget(tmp_path / "b.json", max_total_tokens=10_000)
    p = provider(fake, budget=budget, cache=ResponseCache(tmp_path / "cache"))
    first, second = p.generate(MSGS), p.generate(MSGS)
    assert not first.cache_hit and second.cache_hit and second.text == first.text
    assert len(fake.bodies) == 1 and budget.requests == 1
    report = p.usage_report()
    assert (report["cache_hits"], report["cache_misses"], report["cache_hit_rate"]) == (1, 1, 0.5)
    provider(fake).generate(MSGS)  # --no-cache: no ResponseCache
    assert len(fake.bodies) == 2


def test_cache_key_covers_provider_model_temperature_prompt_and_template_version() -> None:
    base = GenerationConfig()
    k = cache_key("groq", "m", MSGS, base)
    assert k == cache_key("groq", "m", MSGS, GenerationConfig())
    assert len({
        k, cache_key("groq", "m2", MSGS, base), cache_key("ollama", "m", MSGS, base),
        cache_key("groq", "m", MSGS, GenerationConfig(temperature=0.5)),
        cache_key("groq", "m", MSGS, GenerationConfig(prompt_version="review=1.2")),
        cache_key("groq", "m", [Message(role="user", content="other")], base),
    }) == 6  # fmt: skip


def test_cut_off_replies_are_not_cached(tmp_path: Path) -> None:
    body = json.dumps({"choices": [{"message": {"content": "{"}, "finish_reason": "length"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1}})  # fmt: skip
    fake = FakeGroq(lambda n: (200, {}, body))
    p = provider(fake, cache=ResponseCache(tmp_path))
    assert p.generate(MSGS).finish_reason == "MAX_TOKENS"
    p.generate(MSGS)
    assert len(fake.bodies) == 2


# ---- metadata and secrecy ---------------------------------------------------------------------------


class Ok(BaseModel):
    ok: bool


def test_result_metadata_per_call(tmp_path: Path) -> None:
    p = provider(FakeGroq(), cache=ResponseCache(tmp_path))
    run = Usage()
    p.generate_structured(MSGS, Ok, usage=run, label="u1")
    p.generate_structured(MSGS, Ok, usage=run, label="u1")
    log = run.call_log()
    assert [(c.model, c.cache_hit, c.input_tokens) for c in log] == [
        ("openai/gpt-oss-120b", False, 100),
        ("openai/gpt-oss-120b", True, 100),
    ]
    assert run.snapshot()["calls"] == 1 and run.snapshot()["cache_hits"] == 1
    assert log[0].latency_s is not None


def test_secrets_never_reach_logs_errors_ledgers_or_reports(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    budget = UsageBudget(tmp_path / "b.json", max_total_tokens=100_000)
    echo = FakeGroq(lambda n: (500, {}, f"upstream echoed Bearer {SECRET} and {SECRET}"))
    with pytest.raises(LLMError) as err:
        provider(echo, budget=budget).generate(MSGS)
    ok = provider(FakeGroq(), budget=budget, cache=ResponseCache(tmp_path / "c"))
    ok.generate(MSGS)
    cached = " ".join(f.read_text(encoding="utf-8") for f in (tmp_path / "c").rglob("*.json"))
    dumped = " ".join([str(err.value), caplog.text, json.dumps(ok.usage_report()), repr(ok),
                       (tmp_path / "b.json").read_text(encoding="utf-8"), cached])  # fmt: skip
    assert SECRET not in dumped
    assert scrub("x gsk_ABCDEFGHIJKL y Bearer abc org_zz9") == "x *** y *** ***"
