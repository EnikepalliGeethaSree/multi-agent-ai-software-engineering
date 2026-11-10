"""Groq provider with round-robin keys (D38): fake HTTP layer, fake clock, no network, no keys."""

from __future__ import annotations

import json
import logging
import random
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

httpx = pytest.importorskip("httpx")

from marl_agents.config import LLMSettings  # noqa: E402
from marl_agents.llm.base import (  # noqa: E402
    GenerationConfig,
    LLMError,
    Message,
    QuotaExhaustedError,
    RequestTooLargeError,
    Usage,
)
from marl_agents.llm.factory import create_provider  # noqa: E402
from marl_agents.llm.groq import GroqProvider, scrub  # noqa: E402
from marl_agents.llm.keys import KeyManager, Limits, key_label, load_keys  # noqa: E402
from marl_agents.llm.response_cache import ResponseCache, cache_key  # noqa: E402

MSGS = [Message(role="user", content="review this")]
SECRETS = {f"key{i}": f"gsk_SECRET{i:02d}abcdefghijkl" for i in range(1, 11)}
LABEL = {v: k for k, v in SECRETS.items()}


class Clock:
    """Monotonic clock + sleep that only advance when slept."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.slept.append(round(s, 3))
        self.now += s


Reply = int | tuple[int, dict[str, str], str]


class FakeGroq:
    """The fake HTTP layer: records which key each request used and answers from a script."""

    def __init__(self, script: Callable[[str, int], Reply] | None = None) -> None:
        self.used: list[str] = []
        self.bodies: list[dict[str, Any]] = []
        self.script = script or (lambda label, n: 200)

    def handler(self, request: Any) -> Any:
        secret = request.headers["Authorization"].removeprefix("Bearer ")
        label = LABEL[secret]
        self.used.append(label)
        self.bodies.append(json.loads(request.content))
        reply = self.script(label, len(self.used))
        status, headers, text = (reply, {}, "") if isinstance(reply, int) else reply
        if status == 200 and not text:
            text = json.dumps({
                "model": "openai/gpt-oss-120b",
                "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            })  # fmt: skip
        return httpx.Response(status, headers=headers, text=text)

    def client(self) -> Any:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def manager(
    n: int = 3,
    clock: Clock | None = None,
    per_key: Limits | None = None,
    shared: Limits | None = None,
    shared_org: bool = False,
    ledger_dir: Path | None = None,
    now: Callable[[], datetime] | None = None,
) -> KeyManager:
    clock = clock or Clock()
    return KeyManager(
        [(f"key{i}", SECRETS[f"key{i}"]) for i in range(1, n + 1)],
        per_key=per_key,
        shared=shared,
        ledger_dir=ledger_dir,
        shared_org=shared_org,
        clock=clock,
        sleep=clock.sleep,
        now=now or (lambda: datetime(2026, 11, 10, 12, 0, tzinfo=UTC)),
    )


def provider(
    keys: KeyManager, fake: FakeGroq, clock: Clock | None = None, cache: ResponseCache | None = None
) -> GroqProvider:
    clock = clock or Clock()
    return GroqProvider(
        "openai/gpt-oss-120b", keys, client=fake.client(), cache=cache, sleep=clock.sleep,
        rng=random.Random(0),
    )  # fmt: skip


# ---- key loading -----------------------------------------------------------------------------------


def test_load_keys_skips_absent_and_duplicate_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for i in range(1, 11):
        monkeypatch.delenv(f"GROQ_API_KEY_{i}", raising=False)
    monkeypatch.setenv("GROQ_API_KEY_1", "gsk_a")
    monkeypatch.setenv("GROQ_API_KEY_3", "gsk_b")
    monkeypatch.setenv("GROQ_API_KEY_7", "gsk_a")  # duplicate of key 1
    monkeypatch.setenv("GROQ_API_KEY_9", "  ")
    keys = load_keys([f"GROQ_API_KEY_{i}" for i in range(1, 11)])
    assert [label for label, _ in keys] == ["key1", "key3"]
    assert key_label("MY_KEY", 4) == "key4"


def test_manager_needs_a_key() -> None:
    with pytest.raises(ValueError):
        KeyManager([])


# ---- rotation ---------------------------------------------------------------------------------------


def test_round_robin_rotation_wraps_after_the_last_key() -> None:
    fake = FakeGroq()
    p = provider(manager(3), fake)
    served = [p.generate(MSGS).key_id for _ in range(7)]
    assert fake.used == ["key1", "key2", "key3", "key1", "key2", "key3", "key1"]
    assert served == fake.used


def test_key_selection_is_thread_safe_and_even() -> None:
    keys = manager(4)
    with ThreadPoolExecutor(max_workers=8) as pool:
        leases = list(pool.map(lambda _: keys.acquire(10), range(40)))
    assert Counter(lease.label for lease in leases) == {f"key{i}": 10 for i in range(1, 5)}


def test_rotation_continues_after_failures_and_retries() -> None:
    fake = FakeGroq(lambda label, n: 503 if n == 1 else 200)
    clock = Clock()
    p = provider(manager(3, clock), fake, clock)
    r = p.generate(MSGS)
    assert fake.used == ["key1", "key2"] and r.key_id == "key2"
    assert [a.key_id for a in r.attempts] == ["key1"] and r.attempts[0].error_kind == "transient"
    p.generate(MSGS)
    assert fake.used[-1] == "key3"  # the retry did not reset the rotation


# ---- pacing -----------------------------------------------------------------------------------------


def test_per_key_requests_per_minute() -> None:
    clock = Clock()
    keys = manager(2, clock, per_key=Limits(rpm=2), shared=Limits(rpm=100))
    for _ in range(4):
        keys.acquire(10)
    assert clock.slept == []  # 2 keys x 2 requests fit in the first minute
    keys.acquire(10)
    assert clock.slept and clock.slept[0] == pytest.approx(60.0)


def test_per_key_tokens_per_minute() -> None:
    clock = Clock()
    keys = manager(1, clock, per_key=Limits(tpm=1000))
    lease = keys.acquire(800)
    keys.settle(lease, True, 700, 200)  # real usage 900 replaces the estimate
    keys.acquire(200)
    assert clock.slept and clock.slept[0] == pytest.approx(60.0)


def test_shared_limit_caps_all_keys_together() -> None:
    clock = Clock()
    keys = manager(3, clock, per_key=Limits(rpm=10), shared=Limits(rpm=3))
    labels = [keys.acquire(10).label for _ in range(3)]
    assert clock.slept == [] and labels == ["key1", "key2", "key3"]
    keys.acquire(10)  # ten keys do not mean ten times the quota
    assert clock.slept[0] == pytest.approx(60.0)


def test_shared_daily_limit_stops_the_run(tmp_path: Path) -> None:
    keys = manager(3, per_key=Limits(rpd=100), shared=Limits(rpd=2), ledger_dir=tmp_path)
    for _ in range(2):
        keys.settle(keys.acquire(10), True, 5, 5)
    with pytest.raises(QuotaExhaustedError) as err:
        keys.acquire(10)
    assert "shared daily limit" in str(err.value) and err.value.resets_at


# ---- 429 and fallback -------------------------------------------------------------------------------


def test_429_waits_for_retry_after_then_succeeds_shared_org() -> None:
    clock = Clock()
    fake = FakeGroq(
        lambda label, n: (429, {"retry-after": "7"}, "rate limit (RPM)") if n == 1 else 200
    )
    p = provider(manager(3, clock, shared_org=True), fake, clock)
    r = p.generate(MSGS)
    assert r.text == '{"ok": true}' and fake.used == ["key1", "key2"]
    assert clock.slept and clock.slept[0] == pytest.approx(7.0)  # the whole org rests
    assert r.attempts[0].error_kind == "rate_limit"


def test_rate_limited_key_falls_back_to_another_key_at_once() -> None:
    clock = Clock()
    script = lambda label, n: (429, {"retry-after": "30"}, "slow down") if label == "key1" else 200  # noqa: E731
    fake = FakeGroq(script)
    keys = manager(3, clock, shared_org=False)
    p = provider(keys, fake, clock)
    assert p.generate(MSGS).key_id == "key2"
    assert clock.slept == []  # no wait: another eligible key took the request
    assert p.generate(MSGS).key_id == "key3"
    assert p.generate(MSGS).key_id == "key2"  # key1 is still cooling down
    assert keys.status()[0]["rate_limited"] == 1


def test_backoff_with_jitter_when_no_retry_after_and_at_most_five_attempts() -> None:
    clock = Clock()
    fake = FakeGroq(lambda label, n: (429, {}, "too many requests"))
    p = provider(manager(1, clock), fake, clock)
    with pytest.raises(LLMError) as err:
        p.generate(MSGS)
    assert len(fake.used) == 5 and len(err.value.attempts) == 5
    assert all(0 < s <= 60 for s in clock.slept)


def test_daily_limit_on_every_key_raises_checkpoint_error_without_secrets() -> None:
    body = ("Rate limit reached for model `openai/gpt-oss-120b` in organization `org_abc123` on "
            "tokens per day (TPD): Limit 200000, Used 199900. Please try again in 1h2m3s.")  # fmt: skip
    fake = FakeGroq(lambda label, n: (429, {"retry-after": "3723"}, body))
    keys = manager(3, shared_org=False)
    p = provider(keys, fake)
    with pytest.raises(QuotaExhaustedError) as err:
        p.generate(MSGS)
    assert fake.used == ["key1", "key2", "key3"]  # each key tried once, then a clean stop
    text = str(err.value)
    assert "resume after" in text and err.value.resets_at
    assert not any(s in text for s in SECRETS.values()) and "org_abc123" not in text
    assert all(row["state"].startswith("daily limit") for row in keys.status())


def test_daily_limit_on_one_key_of_an_org_stops_every_key() -> None:
    fake = FakeGroq(lambda label, n: (429, {}, "Limit reached on requests per day (RPD)"))
    p = provider(manager(3, shared_org=True), fake)
    with pytest.raises(QuotaExhaustedError):
        p.generate(MSGS)
    assert fake.used == ["key1"]  # the shared organization limit is not probed with every key


def test_exhausted_key_comes_back_after_its_reset() -> None:
    now = [datetime(2026, 11, 10, 12, 0, tzinfo=UTC)]
    keys = manager(2, now=lambda: now[0])
    keys.exhaust(keys.acquire(10), seconds=600)
    assert keys.acquire(10).label == "key2" and keys.acquire(10).label == "key2"
    now[0] += timedelta(minutes=11)
    assert keys.acquire(10).label == "key1"


def test_rejected_key_is_skipped_and_all_rejected_is_an_error() -> None:
    fake = FakeGroq(lambda label, n: 401 if label == "key1" else 200)
    keys = manager(2)
    p = provider(keys, fake)
    assert p.generate(MSGS).key_id == "key2"
    assert p.generate(MSGS).key_id == "key2"
    assert keys.status()[0]["state"] == "rejected (HTTP 401)"
    all_bad = provider(manager(2), FakeGroq(lambda label, n: 403))
    with pytest.raises(LLMError, match="every API key was rejected"):
        all_bad.generate(MSGS)


def test_headers_adjust_limits_and_exhaust_a_key() -> None:
    headers = {
        "x-ratelimit-limit-requests": "1000",
        "x-ratelimit-limit-tokens": "8000",
        "x-ratelimit-remaining-requests": "0",
        "x-ratelimit-reset-requests": "2h0m0s",
        "x-ratelimit-remaining-tokens": "7000",
    }
    keys = manager(2)
    p = provider(keys, FakeGroq(lambda label, n: (200, headers, "") if n == 1 else 200))
    p.generate(MSGS)
    assert keys.status()[0]["state"].startswith("daily limit until")
    assert keys._keys[0].limits.rpd == 1000 and keys._keys[0].limits.tpm == 8000
    assert p.generate(MSGS).key_id == "key2"


def test_request_too_large_and_bad_request_are_not_retried() -> None:
    big = provider(manager(2), FakeGroq(lambda label, n: (413, {}, "Request too large")))
    with pytest.raises(RequestTooLargeError):
        big.generate(MSGS)
    fake = FakeGroq(lambda label, n: (400, {}, "unknown model"))
    with pytest.raises(LLMError):
        provider(manager(2), fake).generate(MSGS)
    assert len(fake.used) == 1


def test_json_mode_rejection_retries_once_without_it() -> None:
    fake = FakeGroq(lambda label, n: (400, {}, "json_validate_failed") if n == 1 else 200)
    p = provider(manager(2), fake)
    p.generate(MSGS)
    assert "response_format" in fake.bodies[0] and "response_format" not in fake.bodies[1]


def test_request_is_deterministic() -> None:
    fake = FakeGroq()
    provider(manager(1), fake).generate(MSGS)
    assert fake.bodies[0]["temperature"] == 0.0 and fake.bodies[0]["seed"] == 42


# ---- cache ------------------------------------------------------------------------------------------


def test_cache_hit_costs_no_request_and_no_quota(tmp_path: Path) -> None:
    fake = FakeGroq()
    keys = manager(2)
    p = provider(keys, fake, cache=ResponseCache(tmp_path))
    first, second = p.generate(MSGS), p.generate(MSGS)
    assert not first.cache_hit and second.cache_hit and second.text == first.text
    assert len(fake.used) == 1 and sum(r["requests"] for r in keys.status()) == 1
    no_cache = provider(manager(2), fake)  # --no-cache: no ResponseCache at all
    no_cache.generate(MSGS)
    assert len(fake.used) == 2


def test_cache_key_covers_model_temperature_prompt_and_template_version() -> None:
    base = GenerationConfig()
    k = cache_key("groq", "m", MSGS, base)
    assert k == cache_key("groq", "m", MSGS, GenerationConfig())
    assert k != cache_key("groq", "m2", MSGS, base)
    assert k != cache_key("ollama", "m", MSGS, base)
    assert k != cache_key("groq", "m", MSGS, GenerationConfig(temperature=0.5))
    assert k != cache_key("groq", "m", MSGS, GenerationConfig(prompt_version="review=1.2"))
    assert k != cache_key("groq", "m", [Message(role="user", content="other")], base)


def test_cut_off_replies_are_not_cached(tmp_path: Path) -> None:
    body = json.dumps({"choices": [{"message": {"content": "{"}, "finish_reason": "length"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1}})  # fmt: skip
    fake = FakeGroq(lambda label, n: (200, {}, body))
    p = provider(manager(1), fake, cache=ResponseCache(tmp_path))
    assert p.generate(MSGS).finish_reason == "MAX_TOKENS"
    p.generate(MSGS)
    assert len(fake.used) == 2


# ---- accounting, metadata and secrecy ---------------------------------------------------------------


class Ok(BaseModel):
    ok: bool


def test_usage_records_model_key_and_cache_per_call(tmp_path: Path) -> None:
    p = provider(manager(2), FakeGroq(), cache=ResponseCache(tmp_path))
    run = Usage()
    p.generate_structured(MSGS, Ok, usage=run, label="u1")
    p.generate_structured(MSGS, Ok, usage=run, label="u1")
    p.generate_structured([Message(role="user", content="b")], Ok, usage=run, label="u2")
    log = run.call_log()
    assert [(c.key_id, c.cache_hit) for c in log] == [
        ("key1", False),
        (None, True),
        ("key2", False),
    ]
    assert log[0].model == "openai/gpt-oss-120b" and log[0].input_tokens == 100
    assert run.snapshot()["calls"] == 2 and run.snapshot()["cache_hits"] == 1
    assert run.by_key() == {
        "key1": {"calls": 1, "failed": 0, "input_tokens": 100, "output_tokens": 20},
        "key2": {"calls": 1, "failed": 0, "input_tokens": 100, "output_tokens": 20},
    }


def test_secrets_never_reach_logs_errors_ledgers_or_status(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    echo = lambda label, n: (500, {}, f"upstream echoed Bearer {SECRETS[label]}")  # noqa: E731
    keys = manager(2, ledger_dir=tmp_path)
    p = provider(keys, FakeGroq(echo))
    with pytest.raises(LLMError) as err:
        p.generate(MSGS)
    provider(keys, FakeGroq()).generate(MSGS)  # writes the daily ledgers
    dumped = " ".join([
        str(err.value), caplog.text, json.dumps(keys.status()), repr(keys._keys[0]),
        *(f.read_text(encoding="utf-8") for f in tmp_path.iterdir()),
    ])  # fmt: skip
    assert not any(s in dumped for s in SECRETS.values())
    assert "key1" in json.dumps(keys.status())
    assert scrub("x gsk_ABCDEFGHIJKL y Bearer abc org_zz9") == "x *** y *** ***"


def test_daily_ledgers_survive_a_restart(tmp_path: Path) -> None:
    keys = manager(1, per_key=Limits(rpd=2), ledger_dir=tmp_path)
    keys.settle(keys.acquire(1), True, 1, 1)
    keys.settle(keys.acquire(1), True, 1, 1)
    again = manager(1, per_key=Limits(rpd=2), ledger_dir=tmp_path)  # a new process, same day
    with pytest.raises(QuotaExhaustedError):
        again.acquire(1)


# ---- factory ----------------------------------------------------------------------------------------


def test_factory_builds_rotating_provider_from_numbered_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for i in range(1, 11):
        monkeypatch.delenv(f"GROQ_API_KEY_{i}", raising=False)
    monkeypatch.setenv("GROQ_API_KEY_2", "gsk_two")
    monkeypatch.setenv("GROQ_API_KEY_5", "gsk_five")
    p = create_provider(LLMSettings(provider="groq", model="openai/gpt-oss-120b",
                                    response_cache=False))  # fmt: skip
    assert isinstance(p, GroqProvider) and p.keys.labels == ["key2", "key5"]
    assert p.keys.per_key == Limits(rpm=30, tpm=8000, rpd=1000, tpd=200_000)
    assert p.keys.shared_limits == p.keys.per_key and p.keys.shared_org  # one org by default
    assert p.cache is None


def test_factory_rotation_without_keys_explains_what_to_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in [f"GROQ_API_KEY_{i}" for i in range(1, 11)] + ["GROQ_API_KEY"]:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(LLMError, match="GROQ_API_KEY_1"):
        create_provider(LLMSettings(provider="groq", model="m", key_rotation=True))
