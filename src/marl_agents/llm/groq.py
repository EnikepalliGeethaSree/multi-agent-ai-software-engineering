"""Groq provider: one API key, Developer tier (pay-as-you-go), one pinned model (D39).

Groq exposes an OpenAI-compatible endpoint (https://api.groq.com/openai/v1). This provider posts to
`/chat/completions` with `httpx`, so tests can swap in a fake HTTP layer (`httpx.MockTransport`).

One request, step by step:

1. Response cache: a hit returns at once, sends nothing, uses no tokens and costs nothing.
2. Usage caps (`UsageBudget`): if the request could, at its worst case, take the cumulative tokens
   or estimated cost past a configured cap, it is not sent (QuotaExhaustedError: save and stop).
3. Daily caps (optional, `DailyQuota`): the same for requests and tokens per UTC day.
4. Pacing (`RateLimiter`): wait until the request fits the requests- and tokens-per-minute limits.
   Limits are the organization's, read from configuration; none are assumed. The server's
   `x-ratelimit-*` headers update them while running.
5. POST, then record tokens, latency and cost.

Failures:

=============================  =================================================================
429, per-minute limit          wait `retry-after` (else exponential backoff with jitter), retry
429, daily limit               QuotaExhaustedError with the reset time: the run saves and stops
401 / 403                      stop: the key is missing, revoked or invalid
413 / "request too large"      RequestTooLargeError (the agent retries without context)
400 json_validate_failed       retry once without JSON mode (our parser extracts the JSON)
other 4xx                      stop: repeating a bad request cannot help
5xx, timeout, network          exponential backoff with jitter, then retry
=============================  =================================================================

At most `max_attempts` (default 5) attempts per request. The API key never reaches a log, an error,
a checkpoint or a result file; server text is scrubbed of keys, bearer tokens and organization ids.
"""

from __future__ import annotations

import logging
import random
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from marl_agents.llm.base import (
    CallAttempt,
    GenerationConfig,
    LLMError,
    LLMProvider,
    LLMResponse,
    Message,
    QuotaExhaustedError,
    RequestTooLargeError,
)
from marl_agents.llm.budget import UsageBudget
from marl_agents.llm.openai_compat import parse_duration
from marl_agents.llm.rate_limit import DailyQuota, RateLimiter, estimate_tokens
from marl_agents.llm.response_cache import CachedReply, ResponseCache, cache_key

logger = logging.getLogger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-120b"
MAX_ATTEMPTS = 5
BASE_BACKOFF_S = 2.0
MAX_BACKOFF_S = 60.0
# A server asking for a longer wait than this has hit a daily limit, not a per-minute one.
QUOTA_EXHAUSTED_S = 120.0
# Used only for pacing estimates before the real usage is known (gpt-oss reasoning + JSON).
EXPECTED_OUTPUT_TOKENS = 1500
DETAIL_CHARS = 300
_SECRETS = re.compile(r"gsk_[0-9A-Za-z]{8,}|Bearer\s+\S+|org_[0-9A-Za-z]+")
_RETRY_IN = re.compile(r"try again in\s*([0-9hms.]+)", re.IGNORECASE)


def scrub(text: str, secret: str | None = None) -> str:
    """Remove API keys, bearer tokens and organization ids from a message."""
    cleaned = _SECRETS.sub("***", text)
    return cleaned.replace(secret, "***") if secret else cleaned


def _retry_after(headers: Any, body_text: str) -> float | None:
    value = headers.get("retry-after") if headers is not None else None
    if value is not None:
        try:
            return float(value)
        except ValueError:
            pass
    m = _RETRY_IN.search(body_text)
    return parse_duration(m.group(1).rstrip(".")) if m else None


def _is_daily(body_text: str, wait: float | None) -> bool:
    lower = body_text.lower()
    daily_words = "per day" in lower or "(rpd)" in lower or "(tpd)" in lower
    return daily_words or (wait is not None and wait > QUOTA_EXHAUSTED_S)


def _num(headers: Any, name: str) -> int | None:
    try:
        return int(float(headers.get(name)))
    except (TypeError, ValueError):
        return None


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(
        self,
        model: str,
        api_key: str,
        config: GenerationConfig | None = None,
        base_url: str = GROQ_BASE_URL,
        timeout: float = 120.0,
        json_mode: bool = True,
        extra_params: dict[str, Any] | None = None,
        limiter: RateLimiter | None = None,
        daily: DailyQuota | None = None,
        budget: UsageBudget | None = None,
        cache: ResponseCache | None = None,
        max_attempts: int = MAX_ATTEMPTS,
        base_backoff_s: float = BASE_BACKOFF_S,
        client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        super().__init__(model=model, config=config)
        if not api_key:
            raise LLMError("GROQ_API_KEY is not set. Put it in .env (see .env.example).")
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.json_mode = json_mode
        self.extra_params = dict(extra_params or {})
        self.limiter = limiter or RateLimiter()
        self.daily = daily
        self.budget = budget
        self.cache = cache
        self.max_attempts = max(1, max_attempts)
        self.base_backoff_s = base_backoff_s
        self._sleep = sleep
        self._rng = rng or random.Random()  # noqa: S311 - retry jitter, not cryptography
        self._now = now
        self._blocked_until: datetime | None = None  # the server said today's requests are spent
        self.rate_limited = 0
        if client is None:
            try:
                import httpx
            except ImportError as exc:
                raise LLMError("Install the `llm` extra: pip install -e '.[llm]'") from exc
            client = httpx.Client(timeout=timeout)
        self._client = client

    def __repr__(self) -> str:  # never show the key
        return f"GroqProvider(model={self.model!r})"

    # ---- request --------------------------------------------------------------------------------

    def _payload(self, messages: list[Message], cfg: GenerationConfig) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [m.model_dump() for m in messages],
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
        }
        if cfg.seed is not None:
            body["seed"] = cfg.seed
        if cfg.stop:
            body["stop"] = cfg.stop
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        body.update(self.extra_params)  # e.g. reasoning_effort for gpt-oss
        return body

    def _backoff(self, attempt: int) -> float:
        base = min(self.base_backoff_s * 2.0**attempt, MAX_BACKOFF_S)
        return base / 2 + self._rng.uniform(0, base / 2)  # "equal jitter"

    def _check_caps(self, prompt_chars: int, cfg: GenerationConfig, estimate: int) -> None:
        if self._blocked_until is not None:
            if self._now() < self._blocked_until:
                raise QuotaExhaustedError(
                    "Groq reports today's request limit is used up. The run saved its progress; "
                    f"resume after {self._blocked_until.isoformat(timespec='minutes')}.",
                    resets_at=self._blocked_until.isoformat(),
                )
            self._blocked_until = None
        if self.budget is not None:
            self.budget.check(prompt_chars, cfg.max_tokens)
        if self.daily is not None:
            why = self.daily.exhausted(estimate)
            if why is not None:
                reset = self.daily.resets_at()
                raise QuotaExhaustedError(
                    f"Configured daily limit reached ({why}). The run saved its progress; resume "
                    f"after {reset.isoformat(timespec='minutes')}.",
                    resets_at=reset.isoformat(),
                )

    def generate(
        self, messages: list[Message], config: GenerationConfig | None = None
    ) -> LLMResponse:
        cfg = config or self.config
        model = str(self.model)
        key = (
            cache_key(self.name, model, messages, cfg, self.json_mode, self.extra_params)
            if self.cache is not None
            else ""
        )
        if self.cache is not None:
            hit = self.cache.get(key)
            if hit is not None:
                logger.info(
                    "groq call model=%s cache=hit prompt_tokens=%s completion_tokens=%s "
                    "latency=0.00s",
                    hit.model,
                    hit.input_tokens,
                    hit.output_tokens,
                )
                return LLMResponse(
                    text=hit.text, model=hit.model, input_tokens=hit.input_tokens,
                    output_tokens=hit.output_tokens, finish_reason=hit.finish_reason,
                    latency_s=0.0, cache_hit=True,
                )  # fmt: skip

        body = self._payload(messages, cfg)
        prompt_chars = sum(len(m.content) for m in messages)
        estimate = estimate_tokens("".join(m.content for m in messages)) + min(
            cfg.max_tokens, EXPECTED_OUTPUT_TOKENS
        )
        attempts: list[CallAttempt] = []
        attempt = 0
        last = "no attempt made"
        while attempt < self.max_attempts:
            try:
                self._check_caps(prompt_chars, cfg, estimate)
            except QuotaExhaustedError as exc:
                exc.attempts = attempts + exc.attempts
                raise
            entry = self.limiter.acquire(estimate)
            started = time.perf_counter()  # after pacing: waits are not inference time
            try:
                resp = self._client.post(
                    f"{self.base_url}/chat/completions",
                    json=body,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
            except Exception as exc:  # httpx timeouts and network errors
                self.limiter.settle(entry, 0)
                last = scrub(f"{type(exc).__name__}: {exc}", self._api_key)
                attempts.append(self._attempt(started, None, "transient"))
                attempt += 1
                if attempt < self.max_attempts:
                    wait = self._backoff(attempt)
                    logger.warning("groq: %s; retrying in %.1fs", last, wait)
                    self._sleep(wait)
                continue
            status = resp.status_code
            text = scrub(resp.text or "", self._api_key)
            if status == 200:
                return self._success(resp, entry, started, attempts, key)
            self.limiter.settle(entry, 0)
            last = f"HTTP {status}: {text[:DETAIL_CHARS]}"
            if status == 429:
                self.rate_limited += 1
                asked = _retry_after(resp.headers, text)
                if "request too large" in text.lower():
                    attempts.append(self._attempt(started, status, "too_large"))
                    raise RequestTooLargeError(f"groq: request too large for {model}: {text[:200]}",
                                               attempts)  # fmt: skip
                if _is_daily(text, asked):
                    attempts.append(self._attempt(started, status, "quota"))
                    reset = self._now() + timedelta(seconds=asked or 0)
                    raise QuotaExhaustedError(
                        f"Groq daily limit reached for {model}. The run saved its progress; resume "
                        f"after {reset.isoformat(timespec='minutes')}. Server said: "
                        f"{text[:DETAIL_CHARS]}",
                        attempts,
                        retry_after_s=asked,
                        resets_at=reset.isoformat() if asked else None,
                    )
                attempts.append(self._attempt(started, status, "rate_limit"))
                wait = asked if asked is not None else self._backoff(attempt)
                logger.warning("groq rate limited (429); waiting %.1fs", wait)
                self.limiter.pause(wait)
                attempt += 1
                continue
            if status in (401, 403):
                attempts.append(self._attempt(started, status, "auth"))
                raise LLMError(f"groq rejected GROQ_API_KEY (HTTP {status}): it is missing, "
                               "revoked or invalid. Create a new key in the Groq console.",
                               attempts)  # fmt: skip
            if status == 413 or "request too large" in text.lower():
                attempts.append(self._attempt(started, status, "too_large"))
                raise RequestTooLargeError(f"groq: request too large for {model}: {text[:200]}",
                                           attempts)  # fmt: skip
            if (
                status == 400
                and "response_format" in body
                and ("json_validate_failed" in text or "response_format" in text)
            ):
                logger.info("JSON mode rejected by the server; retrying without it")
                body.pop("response_format")
                attempts.append(self._attempt(started, status, "json_mode"))
                continue
            if 400 <= status < 500 and status not in (408, 409):
                attempts.append(self._attempt(started, status, "fatal"))
                break
            attempts.append(self._attempt(started, status, "transient"))
            attempt += 1
            if attempt < self.max_attempts:
                self._sleep(self._backoff(attempt))
        raise LLMError(f"groq call failed after {len(attempts)} attempt(s): {last}", attempts)

    @staticmethod
    def _attempt(started: float, status: int | None, kind: str) -> CallAttempt:
        return CallAttempt(
            started_at=started, latency_s=time.perf_counter() - started, ok=False,
            status=status, error_kind=kind,
        )  # fmt: skip

    def _success(
        self, resp: Any, entry: Any, started: float, attempts: list[CallAttempt], key: str
    ) -> LLMResponse:
        latency = time.perf_counter() - started
        try:
            data = resp.json()
            choice = data["choices"][0]
            text = choice["message"].get("content") or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            self.limiter.settle(entry, 0)
            raise LLMError(f"groq returned an unreadable reply: {exc}", attempts) from exc
        usage = data.get("usage") or {}
        in_tok, out_tok = usage.get("prompt_tokens"), usage.get("completion_tokens")
        total = (in_tok or 0) + (out_tok or 0)
        self.limiter.settle(entry, total if (in_tok is not None or out_tok is not None) else None)
        if self.budget is not None:
            self.budget.record(in_tok, out_tok)
        if self.daily is not None:
            self.daily.record(total)
        self._follow_headers(resp.headers)
        model = data.get("model") or str(self.model)
        finish = choice.get("finish_reason")
        logger.info("groq call model=%s cache=miss prompt_tokens=%s completion_tokens=%s "
                    "latency=%.2fs", model, in_tok, out_tok, latency)  # fmt: skip
        if self.cache is not None and finish != "length":
            reply = CachedReply(
                text=text,
                model=model,
                input_tokens=in_tok,
                output_tokens=out_tok,
                finish_reason=finish,
            )
            self.cache.put(key, reply)
        return LLMResponse(
            text=text,
            model=model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            started_at=started,
            latency_s=latency,
            finish_reason="MAX_TOKENS" if finish == "length" else finish,
            attempts=attempts,
        )

    def _follow_headers(self, headers: Any) -> None:
        """Groq: `*-requests` headers describe requests per day, `*-tokens` tokens per minute.

        A reported limit replaces the configured one; no requests left blocks until the reset;
        too few tokens left pauses pacing until the token window resets.
        """
        limit_req, limit_tok = (
            _num(headers, "x-ratelimit-limit-requests"),
            _num(headers, "x-ratelimit-limit-tokens"),
        )
        if limit_tok:
            self.limiter.tpm = limit_tok
        if limit_req and self.daily is not None:
            self.daily.rpd = limit_req
        rem_req = _num(headers, "x-ratelimit-remaining-requests")
        rem_tok = _num(headers, "x-ratelimit-remaining-tokens")
        if rem_req is not None and rem_req <= 0:
            reset = parse_duration(headers.get("x-ratelimit-reset-requests"))
            self._blocked_until = self._now() + timedelta(seconds=reset or 0)
        if rem_tok is not None and rem_tok < EXPECTED_OUTPUT_TOKENS:
            reset = parse_duration(headers.get("x-ratelimit-reset-tokens"))
            if reset:
                self.limiter.pause(min(reset, MAX_BACKOFF_S))

    # ---- reporting ------------------------------------------------------------------------------

    def usage_report(self) -> dict[str, Any]:
        """Run-level totals: calls, tokens, cache hits and misses, cumulative cost and caps."""
        snap = self.usage.snapshot()
        hits = self.cache.hits if self.cache is not None else 0
        misses = self.cache.misses if self.cache is not None else 0
        return {
            "provider": self.name,
            "model": self.model,
            **snap,
            "cache_hits": hits,
            "cache_misses": misses,
            "cache_hit_rate": round(hits / (hits + misses), 4) if hits + misses else None,
            "rate_limited": self.rate_limited,
            "pacing_wait_s": round(self.limiter.waited_s, 2),
            "budget": self.budget.status() if self.budget is not None else None,
        }

    def list_models(self) -> list[str]:
        """Model ids available to the key (`GET /models`)."""
        resp = self._client.get(
            f"{self.base_url}/models", headers={"Authorization": f"Bearer {self._api_key}"}
        )
        if resp.status_code != 200:
            raise LLMError(f"groq /models: HTTP {resp.status_code}: "
                           f"{scrub(resp.text or '', self._api_key)[:DETAIL_CHARS]}")  # fmt: skip
        return sorted(m["id"] for m in resp.json().get("data", []))
