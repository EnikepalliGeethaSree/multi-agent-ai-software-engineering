"""OpenAI-compatible chat provider.

Covers OpenAI and every server exposing the same API: Groq, Ollama, LM Studio, vLLM, OpenRouter,
Together... (set `base_url`). The `openai` SDK is imported lazily (`llm` extra).

Hosted-API robustness (important for Groq's per-minute quotas):
- client-side request/token rate limiting shared by all threads (`RateLimiter`);
- HTTP 429 honours the server's `retry-after` header and pauses every thread;
- if the server rejects JSON mode output (`json_validate_failed`) or does not support JSON mode, the
  call is retried without it and our own parser extracts the JSON.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from marl_agents.llm.base import (
    GenerationConfig,
    LLMError,
    LLMProvider,
    LLMResponse,
    Message,
    RequestTooLargeError,
)
from marl_agents.llm.rate_limit import RateLimiter, estimate_tokens

logger = logging.getLogger(__name__)

# Token-quota estimate before the real usage is known. gpt-oss models emit ~1.5-1.7k output tokens
# per review call (reasoning included; measured on the planted benchmark).
EXPECTED_OUTPUT_TOKENS = 1500
MAX_BACKOFF_S = 60.0
# A server asking for a longer wait than this has hit a daily/hourly quota: fail fast and say so
# instead of retrying for minutes (e.g. Groq "tokens per day (TPD)").
QUOTA_EXHAUSTED_S = 120.0
_ORG = re.compile(r"\s*in organization `[^`]*`")
_DURATION = re.compile(
    r"^(?:(?P<h>[\d.]+)h)?(?:(?P<m>[\d.]+)m(?!s))?(?:(?P<s>[\d.]+)s)?(?:(?P<ms>[\d.]+)ms)?$"
)


def parse_duration(text: str | None) -> float | None:
    """Groq-style durations: '577ms', '7.66s', '1m26.4s', '2h3m' -> seconds."""
    if not text:
        return None
    m = _DURATION.match(text.strip())
    if not m or not any(m.groupdict().values()):
        return None
    g = {k: float(v) if v else 0.0 for k, v in m.groupdict().items()}
    return g["h"] * 3600 + g["m"] * 60 + g["s"] + g["ms"] / 1000


_RETRY_IN = re.compile(r"(?:try again in|retry after)\s*([\d.]+)\s*(ms|s)?", re.IGNORECASE)


def _status(exc: Exception) -> int | None:
    status = getattr(exc, "status_code", None)
    return int(status) if isinstance(status, int) else None


def _retry_after(exc: Exception) -> float | None:
    """Seconds to wait, from the `retry-after` header or a 'try again in 7.5s' message."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is not None:
        value = headers.get("retry-after")
        if value is not None:
            try:
                return float(value)
            except ValueError:
                pass
    m = _RETRY_IN.search(str(exc))
    if m:
        seconds = float(m.group(1))
        return seconds / 1000 if (m.group(2) or "s").lower() == "ms" else seconds
    return None


def quota_message(provider: str, model: str, wait_s: float, exc: Exception) -> str:
    """Readable 'quota exhausted' error; drops the organisation id the server includes."""
    detail = _ORG.sub("", str(exc)).split(" Need more tokens?")[0].strip()
    minutes = max(1, round(wait_s / 60))
    kind = "daily" if "per day" in detail.lower() else "usage"
    return (
        f"{provider} {kind} quota reached for model {model}: try again in about {minutes} min, "
        f"or choose another model. Server said: {detail[:300]}"
    )


def _json_mode_rejected(exc: Exception) -> bool:
    text = str(exc)
    return "json_validate_failed" in text or ("response_format" in text and _status(exc) != 429)


class OpenAICompatibleProvider(LLMProvider):
    name = "openai"

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        config: GenerationConfig | None = None,
        max_retries: int = 5,
        timeout: float = 120.0,
        json_mode: bool = True,
        client: Any | None = None,
        name: str | None = None,
        rate_limiter: RateLimiter | None = None,
        extra_params: dict[str, Any] | None = None,
        sleep: Any = time.sleep,
    ) -> None:
        super().__init__(model=model, config=config)
        if name:
            self.name = name
        self.json_mode = json_mode
        self.max_retries = max_retries
        self.limiter = rate_limiter or RateLimiter()
        self.extra_params = dict(extra_params or {})
        self._sleep = sleep
        self.rate_limited = 0  # number of 429 responses received
        if client is not None:
            self._client = client
        else:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise LLMError("Install the `llm` extra: pip install -e '.[llm]'") from exc
            self._client = OpenAI(
                api_key=api_key or "not-needed", base_url=base_url, timeout=timeout, max_retries=0
            )

    def _kwargs(self, messages: list[Message], cfg: GenerationConfig) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [m.model_dump() for m in messages],
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
        }
        if cfg.seed is not None:
            kwargs["seed"] = cfg.seed
        if cfg.stop:
            kwargs["stop"] = cfg.stop
        if self.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if self.extra_params:
            # Provider-specific options (e.g. Groq's reasoning_format / reasoning_effort).
            kwargs["extra_body"] = dict(self.extra_params)
        return kwargs

    def generate(
        self, messages: list[Message], config: GenerationConfig | None = None
    ) -> LLMResponse:
        cfg = config or self.config
        kwargs = self._kwargs(messages, cfg)
        estimate = estimate_tokens("".join(m.content for m in messages)) + min(
            cfg.max_tokens, EXPECTED_OUTPUT_TOKENS
        )

        last_exc: Exception | None = None
        attempt = 0
        while attempt <= self.max_retries:
            entry = self.limiter.acquire(estimate)
            call_start = time.perf_counter()  # after the limiter: waits are not inference time
            try:
                resp = self._create(kwargs, estimate)
            except Exception as exc:
                self.limiter.settle(entry, 0)
                last_exc = exc
                status = _status(exc)
                if "response_format" in kwargs and _json_mode_rejected(exc):
                    logger.info("JSON mode rejected by the server; retrying without it")
                    kwargs.pop("response_format")
                    continue  # not counted as an attempt
                if status == 413 or "request too large" in str(exc).lower():
                    detail = _ORG.sub("", str(exc))[:300]
                    raise RequestTooLargeError(
                        f"{self.name}: request too large for model {self.model}: {detail}"
                    ) from exc
                if status == 429:
                    self.rate_limited += 1
                    requested = _retry_after(exc)
                    if requested is not None and requested > QUOTA_EXHAUSTED_S:
                        message = quota_message(self.name, str(self.model), requested, exc)
                        raise LLMError(message) from exc
                    wait = min(requested or 2.0 ** (attempt + 1), MAX_BACKOFF_S)
                    logger.warning("Rate limited (429); waiting %.1fs", wait)
                    self.limiter.pause(wait)
                elif status is not None and 400 <= status < 500 and status not in (408, 409):
                    break  # bad request / auth / unknown model: retrying will not help
                elif attempt < self.max_retries:
                    wait = min(2.0**attempt, MAX_BACKOFF_S)
                    logger.warning("LLM call failed (%s); retrying in %.0fs", exc, wait)
                    self._sleep(wait)
                attempt += 1
                continue
            choice = resp.choices[0]
            usage = getattr(resp, "usage", None)
            in_tok = getattr(usage, "prompt_tokens", None)
            out_tok = getattr(usage, "completion_tokens", None)
            if in_tok is not None or out_tok is not None:
                self.limiter.settle(entry, (in_tok or 0) + (out_tok or 0))
            return LLMResponse(
                text=choice.message.content or "",
                model=getattr(resp, "model", None) or str(self.model),
                input_tokens=in_tok,
                output_tokens=out_tok,
                started_at=call_start,
                latency_s=time.perf_counter() - call_start,
            )
        raise LLMError(f"LLM call failed after {attempt} attempt(s): {last_exc}")

    def _create(self, kwargs: dict[str, Any], next_estimate: int) -> Any:
        """Call the API; when the server reports its quota (Groq/OpenAI `x-ratelimit-*` headers),
        follow it. Those counters are account-wide, so this also covers other processes (dashboard,
        CLI, evaluations) sharing the same key, which a client-side window cannot see."""
        completions = self._client.chat.completions
        raw_api = getattr(completions, "with_raw_response", None)
        if raw_api is None:
            return completions.create(**kwargs)
        raw = raw_api.create(**kwargs)
        self._follow_server_quota(getattr(raw, "headers", {}) or {}, next_estimate)
        return raw.parse()

    def _follow_server_quota(self, headers: Any, next_estimate: int) -> None:
        try:
            remaining = int(float(headers.get("x-ratelimit-remaining-tokens")))
        except (TypeError, ValueError):
            return
        reset = parse_duration(headers.get("x-ratelimit-reset-tokens"))
        if reset and remaining < next_estimate:
            wait = min(reset, MAX_BACKOFF_S)
            logger.info("Server token quota low (%d left); pausing %.1fs", remaining, wait)
            self.limiter.pause(wait)

    def list_models(self) -> list[str]:
        """Model ids available to this API key (OpenAI-compatible `/models`)."""
        return sorted(m.id for m in self._client.models.list().data)
