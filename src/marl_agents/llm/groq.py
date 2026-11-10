"""Groq provider with round-robin API keys, pacing, retries and a response cache (D38).

Groq exposes an OpenAI-compatible endpoint (https://api.groq.com/openai/v1). This provider posts
to `/chat/completions` with `httpx`, so tests can swap in a fake HTTP layer (`httpx.MockTransport`).

One request, step by step:

1. Response cache: a hit returns at once, sends nothing and uses no quota.
2. `KeyManager.acquire`: the next eligible key in round-robin order, after waiting for the
   per-key and shared per-minute limits.
3. POST. The `x-ratelimit-*` headers update that key's limits and remaining budget.
4. Failures:

   ============================  ===============================================================
   429, per-minute              rest that key for `retry-after` (else exponential backoff with
                                jitter) and retry on the next eligible key; at most 5 attempts
   429, daily (long wait or     mark the key spent until its reset and move on; when no key is
   "per day")                   left, QuotaExhaustedError -> the run saves and stops
   401 / 403                    the key is rejected: skip it from now on, use the others
   413 / "request too large"    RequestTooLargeError (the agent retries without context)
   400 json_validate_failed     retry once without JSON mode (our parser extracts the JSON)
   other 4xx                    stop: repeating a bad request cannot help
   5xx, timeout, network        exponential backoff with jitter, then retry
   ============================  ===============================================================

API keys never reach logs, errors, checkpoints or result files: only labels such as "key3".
"""

from __future__ import annotations

import logging
import random
import re
import time
from collections.abc import Callable
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
from marl_agents.llm.keys import KeyManager, Lease
from marl_agents.llm.openai_compat import parse_duration
from marl_agents.llm.rate_limit import estimate_tokens
from marl_agents.llm.response_cache import CachedReply, ResponseCache, cache_key

logger = logging.getLogger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-120b"
MAX_ATTEMPTS = 5
MAX_BACKOFF_S = 60.0
# A server asking for a longer wait than this has hit a daily limit, not a per-minute one.
QUOTA_EXHAUSTED_S = 120.0
# gpt-oss output, reasoning included, is ~1.5k tokens per review call (planted benchmark, D24).
EXPECTED_OUTPUT_TOKENS = 1500
DETAIL_CHARS = 300
_SECRETS = re.compile(r"gsk_[0-9A-Za-z]{8,}|Bearer\s+\S+|org_[0-9A-Za-z]+")
_RETRY_IN = re.compile(r"try again in\s*([0-9hms.]+)", re.IGNORECASE)


def scrub(text: str, secrets: list[str] | None = None) -> str:
    """Remove API keys, bearer tokens and organization ids from a message."""
    cleaned = _SECRETS.sub("***", text)
    for s in secrets or []:
        if s:
            cleaned = cleaned.replace(s, "***")
    return cleaned


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


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(
        self,
        model: str,
        keys: KeyManager,
        config: GenerationConfig | None = None,
        base_url: str = GROQ_BASE_URL,
        timeout: float = 120.0,
        json_mode: bool = True,
        extra_params: dict[str, Any] | None = None,
        cache: ResponseCache | None = None,
        max_attempts: int = MAX_ATTEMPTS,
        client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        super().__init__(model=model, config=config)
        self.keys = keys
        self.base_url = base_url.rstrip("/")
        self.json_mode = json_mode
        self.extra_params = dict(extra_params or {})
        self.cache = cache
        self.max_attempts = max(1, max_attempts)
        self._sleep = sleep
        self._rng = rng or random.Random()  # noqa: S311 - retry jitter, not cryptography
        if client is None:
            try:
                import httpx
            except ImportError as exc:
                raise LLMError("Install the `llm` extra: pip install -e '.[llm]'") from exc
            client = httpx.Client(timeout=timeout)
        self._client = client

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
        base = min(2.0 ** (attempt + 1), MAX_BACKOFF_S)
        return base / 2 + self._rng.uniform(0, base / 2)  # "equal jitter"

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
                logger.info("groq call model=%s key=- cache=hit prompt_tokens=%s "
                            "completion_tokens=%s latency=0.00s", hit.model, hit.input_tokens,
                            hit.output_tokens)  # fmt: skip
                return LLMResponse(
                    text=hit.text, model=hit.model, input_tokens=hit.input_tokens,
                    output_tokens=hit.output_tokens, finish_reason=hit.finish_reason,
                    latency_s=0.0, cache_hit=True,
                )  # fmt: skip

        body = self._payload(messages, cfg)
        estimate = estimate_tokens("".join(m.content for m in messages)) + min(
            cfg.max_tokens, EXPECTED_OUTPUT_TOKENS
        )
        attempts: list[CallAttempt] = []
        attempt = 0
        last = "no attempt made"
        while attempt < self.max_attempts:
            try:
                lease = self.keys.acquire(estimate)
            except QuotaExhaustedError as exc:
                exc.attempts = attempts + exc.attempts
                raise
            started = time.perf_counter()
            try:
                resp = self._client.post(
                    f"{self.base_url}/chat/completions",
                    json=body,
                    headers={"Authorization": f"Bearer {lease.secret}"},
                )
            except Exception as exc:  # httpx timeouts and network errors
                self.keys.settle(lease, ok=False)
                last = scrub(f"{type(exc).__name__}: {exc}", [lease.secret])
                attempts.append(self._attempt(started, None, "transient", lease))
                attempt += 1
                if attempt < self.max_attempts:
                    wait = self._backoff(attempt)
                    logger.warning("groq %s: %s; retrying in %.1fs", lease.label, last, wait)
                    self._sleep(wait)
                continue
            status = resp.status_code
            text = scrub(resp.text or "", [lease.secret])
            if status == 200:
                return self._success(resp, lease, started, attempts, key)
            self.keys.settle(lease, ok=False)
            last = f"HTTP {status}: {text[:DETAIL_CHARS]}"
            if status == 429:
                asked = _retry_after(resp.headers, text)
                if "request too large" in text.lower():
                    raise RequestTooLargeError(f"groq: request too large for {model}: {text[:200]}",
                                               attempts)  # fmt: skip
                if _is_daily(text, asked):
                    attempts.append(self._attempt(started, status, "quota", lease))
                    self.keys.exhaust(lease, asked)
                    continue  # bounded: each key can be spent only once, then acquire raises
                attempts.append(self._attempt(started, status, "rate_limit", lease))
                self.keys.cool_down(lease, asked if asked is not None else self._backoff(attempt))
                attempt += 1
                continue
            if status in (401, 403):
                attempts.append(self._attempt(started, status, "auth", lease))
                self.keys.disable(lease, f"HTTP {status}")
                continue  # bounded: once every key is rejected, acquire raises LLMError
            if status == 413 or "request too large" in text.lower():
                attempts.append(self._attempt(started, status, "too_large", lease))
                raise RequestTooLargeError(f"groq: request too large for {model}: {text[:200]}",
                                           attempts)  # fmt: skip
            if (
                status == 400
                and "response_format" in body
                and ("json_validate_failed" in text or "response_format" in text)
            ):
                logger.info("JSON mode rejected by the server; retrying without it")
                body.pop("response_format")
                attempts.append(self._attempt(started, status, "json_mode", lease))
                continue
            if 400 <= status < 500 and status not in (408, 409):
                attempts.append(self._attempt(started, status, "fatal", lease))
                break
            attempts.append(self._attempt(started, status, "transient", lease))
            attempt += 1
            if attempt < self.max_attempts:
                self._sleep(self._backoff(attempt))
        raise LLMError(f"groq call failed after {len(attempts)} attempt(s): {last}", attempts)

    def _attempt(self, started: float, status: int | None, kind: str, lease: Lease) -> CallAttempt:
        return CallAttempt(
            started_at=started, latency_s=time.perf_counter() - started, ok=False,
            status=status, error_kind=kind, key_id=lease.label,
        )  # fmt: skip

    def _success(
        self, resp: Any, lease: Lease, started: float, attempts: list[CallAttempt], key: str
    ) -> LLMResponse:
        latency = time.perf_counter() - started
        try:
            data = resp.json()
            choice = data["choices"][0]
            text = choice["message"].get("content") or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            self.keys.settle(lease, ok=False)
            raise LLMError(f"groq returned an unreadable reply: {exc}", attempts) from exc
        usage = data.get("usage") or {}
        in_tok, out_tok = usage.get("prompt_tokens"), usage.get("completion_tokens")
        self.keys.settle(lease, ok=True, input_tokens=in_tok, output_tokens=out_tok)
        self.keys.apply_headers(lease, resp.headers, EXPECTED_OUTPUT_TOKENS)
        model = data.get("model") or str(self.model)
        finish = choice.get("finish_reason")
        logger.info("groq call model=%s key=%s cache=miss prompt_tokens=%s completion_tokens=%s "
                    "latency=%.2fs", model, lease.label, in_tok, out_tok, latency)  # fmt: skip
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
            key_id=lease.label,
        )

    def list_models(self) -> list[str]:
        """Model ids available to the first usable key (`GET /models`)."""
        lease = self.keys.acquire(1)
        try:
            resp = self._client.get(
                f"{self.base_url}/models", headers={"Authorization": f"Bearer {lease.secret}"}
            )
        finally:
            self.keys.release(lease)  # listing models is not a completion
        if resp.status_code != 200:
            raise LLMError(f"groq /models: HTTP {resp.status_code}: "
                           f"{scrub(resp.text or '', [lease.secret])[:DETAIL_CHARS]}")  # fmt: skip
        return sorted(m["id"] for m in resp.json().get("data", []))
