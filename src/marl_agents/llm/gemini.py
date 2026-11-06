"""Google Gemini provider via the official `google-genai` SDK (imported lazily, `llm` extra).

Built for the free tier of the Gemini API, whose limits are per project, vary by model and are not
guaranteed. Every failure is classified, because each kind needs a different answer:

    per-minute 429         wait as long as the server says, then retry
    daily / free quota     stop at once with QuotaExhaustedError: the review can resume later
    request too large      RequestTooLargeError: the agent retries without retrieved context
    bad key/model/request  stop at once: repeating it cannot help
    5xx, timeout, network  bounded exponential backoff

Retries are bounded by `max_retries`. API keys never reach logs or error messages (`_scrub`).
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
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
from marl_agents.llm.rate_limit import DailyQuota, RateLimiter, estimate_tokens

logger = logging.getLogger(__name__)

# Free text models from Google's pricing page, best first (checked 2026-11-06). The list changes,
# so `recommend_model` always intersects this with what the key can really use.
FREE_TIER_PREFERENCE = (
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
)
EXPECTED_OUTPUT_TOKENS = 1500
MAX_BACKOFF_S = 60.0
DETAIL_CHARS = 700  # long enough to keep the limit in a quota message
# A server asking for a longer wait than this has hit a daily quota, not a per-minute one.
QUOTA_EXHAUSTED_S = 120.0
TOO_LARGE_MARKERS = ("exceeds the maximum", "input token count", "payload size", "too large")
_API_KEY = re.compile(r"AIza[0-9A-Za-z_\-]{10,}|(?<=key=)[^&\s'\"]+")
_RETRY_IN = re.compile(r"retry in\s*([\d.]+)\s*(ms|s)", re.IGNORECASE)
_DELAY = re.compile(r"^([\d.]+)s$")


@dataclass(frozen=True)
class Failure:
    kind: str  # rate_limit | quota | too_large | fatal | transient
    status: int | None
    detail: str
    wait_s: float | None = None


def _scrub(text: str, secret: str | None = None) -> str:
    cleaned = _API_KEY.sub("***", text)
    return cleaned.replace(secret, "***") if secret else cleaned


def _error_details(exc: Exception) -> list[dict[str, Any]]:
    """google.rpc detail entries of an APIError (`details` is the decoded response body)."""
    body = getattr(exc, "details", None)
    if isinstance(body, dict):
        inner = body.get("error", body)
        items = inner.get("details") if isinstance(inner, dict) else None
        if isinstance(items, list):
            return [i for i in items if isinstance(i, dict)]
    return []


def retry_delay(exc: Exception) -> float | None:
    """The wait the server asked for, in seconds: RetryInfo, then a 'retry in 12.5s' message."""
    for item in _error_details(exc):
        if str(item.get("@type", "")).endswith("RetryInfo"):
            m = _DELAY.match(str(item.get("retryDelay", "")))
            if m:
                return float(m.group(1))
    m = _RETRY_IN.search(str(exc))
    if m:
        value = float(m.group(1))
        return value / 1000 if m.group(2).lower() == "ms" else value
    return None


def _quota_ids(exc: Exception) -> list[str]:
    ids: list[str] = []
    for item in _error_details(exc):
        violations = item.get("violations")
        if isinstance(violations, list):
            ids.extend(str(v.get("quotaId", "")) for v in violations if isinstance(v, dict))
    return ids


def classify_failure(exc: Exception, secret: str | None = None) -> Failure:
    code = getattr(exc, "code", None)
    status = code if isinstance(code, int) else None
    message = str(getattr(exc, "message", None) or exc)
    detail = _scrub(message, secret)[:DETAIL_CHARS]
    lower = message.lower()
    if status == 413 or (status == 400 and any(m in lower for m in TOO_LARGE_MARKERS)):
        return Failure("too_large", status, detail)
    if status == 429:
        wait = retry_delay(exc)
        ids = " ".join(_quota_ids(exc)).lower()
        daily = "perday" in ids or "per day" in lower or "daily" in lower
        no_quota = bool(re.search(r"limit:\s*0\b", lower))
        if daily or no_quota or (wait is not None and wait > QUOTA_EXHAUSTED_S):
            return Failure("quota", status, detail, wait)
        return Failure("rate_limit", status, detail, wait)
    if status in (408, 409) or (status is not None and status >= 500):
        return Failure("transient", status, detail)
    if status is not None:
        return Failure("fatal", status, detail)
    return Failure("transient", None, f"{type(exc).__name__}: {detail}")


def recommend_model(available: Iterable[str]) -> str | None:
    """The best free-tier model this key can use, or None if none of the known ones is offered."""
    names = set(available)
    return next((m for m in FREE_TIER_PREFERENCE if m in names), None)


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        config: GenerationConfig | None = None,
        max_retries: int = 5,
        client: Any | None = None,
        timeout: float = 120.0,
        json_mode: bool = True,
        rate_limiter: RateLimiter | None = None,
        daily_quota: DailyQuota | None = None,
        max_input_tokens: int | None = None,
        extra_params: dict[str, Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(model=model, config=config)
        self.max_retries = max_retries
        self.json_mode = json_mode
        self.limiter = rate_limiter or RateLimiter()
        self.daily = daily_quota or DailyQuota(None)
        self.max_input_tokens = max_input_tokens
        self.extra_params = dict(extra_params or {})
        self._sleep = sleep
        self._secret = api_key
        self.rate_limited = 0  # number of 429 responses received
        self.quota_stop: str | None = None  # why the last request was refused, if it was
        if client is not None:
            self._client = client
            return
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise LLMError("Install the `llm` extra: pip install -e '.[llm]'") from exc
        self._client = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout * 1000))
        )

    def _request_config(self, messages: list[Message], cfg: GenerationConfig) -> dict[str, Any]:
        system = "\n\n".join(m.content for m in messages if m.role == "system") or None
        gen_config: dict[str, Any] = {
            "temperature": cfg.temperature,
            "max_output_tokens": cfg.max_tokens,
        }
        if self.json_mode:
            gen_config["response_mime_type"] = "application/json"
        if system:
            gen_config["system_instruction"] = system
        if cfg.seed is not None:
            gen_config["seed"] = cfg.seed
        if cfg.stop:
            gen_config["stop_sequences"] = cfg.stop
        gen_config.update(self.extra_params)
        return gen_config

    def _refuse_if_spent(self, estimate: int, attempts: list[CallAttempt]) -> None:
        reason = self.daily.exhausted(estimate)
        if reason is None:
            return
        self.quota_stop = reason
        resets = str(self.daily.status()["resets_at"])
        raise QuotaExhaustedError(
            f"gemini daily budget reached for model {self.model} ({reason}, by this machine's "
            f"count). No request was sent. It resets at {resets}. Finished review units are "
            "saved, so the review can be resumed then.",
            attempts,
            resets_at=resets,
        )

    def _quota_error(self, failure: Failure, attempts: list[CallAttempt]) -> QuotaExhaustedError:
        resets = str(self.daily.status()["resets_at"])
        self.quota_stop = failure.detail
        return QuotaExhaustedError(
            f"gemini quota reached for model {self.model}. Daily quotas reset at {resets} "
            "(midnight Pacific). Finished review units are saved, so the review can be resumed "
            f"then. Server said: {failure.detail}",
            attempts,
            retry_after_s=failure.wait_s,
            resets_at=resets,
        )

    def generate(
        self, messages: list[Message], config: GenerationConfig | None = None
    ) -> LLMResponse:
        cfg = config or self.config
        contents = [
            {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
            for m in messages
            if m.role != "system"
        ]
        gen_config = self._request_config(messages, cfg)
        input_estimate = estimate_tokens("".join(m.content for m in messages))
        if self.max_input_tokens and input_estimate > self.max_input_tokens:
            raise RequestTooLargeError(
                f"gemini: about {input_estimate} input tokens (local estimate) exceeds "
                f"llm.max_input_tokens={self.max_input_tokens}; not sent"
            )
        estimate = input_estimate + min(cfg.max_tokens, EXPECTED_OUTPUT_TOKENS)

        attempts: list[CallAttempt] = []
        last: Failure | None = None
        attempt = 0
        while attempt <= self.max_retries:
            self._refuse_if_spent(estimate, attempts)
            entry = self.limiter.acquire(estimate)
            call_start = time.perf_counter()  # after the limiter: waits are not inference time
            try:
                resp = self._client.models.generate_content(
                    model=self.model, contents=contents, config=gen_config
                )
            except Exception as exc:  # the SDK raises several unrelated types; each is classified
                latency = time.perf_counter() - call_start
                self.limiter.settle(entry, 0)
                last = classify_failure(exc, self._secret)
                attempts.append(
                    CallAttempt(
                        started_at=call_start,
                        latency_s=latency,
                        status=last.status,
                        error_kind=last.kind,
                    )
                )
                if last.kind == "too_large":
                    message = f"gemini: request too large for {self.model}: {last.detail}"
                    raise RequestTooLargeError(message, attempts) from exc
                if last.kind == "quota":
                    raise self._quota_error(last, attempts) from exc
                if last.kind == "fatal":
                    message = f"gemini request rejected ({last.status}): {last.detail}"
                    raise LLMError(message, attempts) from exc
                attempt += 1
                if attempt > self.max_retries:
                    break
                self._wait(last, attempt)
                continue
            return self._response(resp, entry, call_start, attempts)
        detail = last.detail if last else "no attempt made"
        raise LLMError(f"Gemini call failed after {attempt} attempt(s): {detail}", attempts)

    def _wait(self, failure: Failure, attempt: int) -> None:
        if failure.kind == "rate_limit":
            self.rate_limited += 1
            wait = min(failure.wait_s or 2.0**attempt, MAX_BACKOFF_S)
            logger.warning("Gemini rate limited (429); waiting %.1fs", wait)
            self.limiter.pause(wait)
            return
        wait = min(2.0 ** (attempt - 1), MAX_BACKOFF_S)
        logger.warning("Gemini call failed (%s); retrying in %.0fs", failure.kind, wait)
        self._sleep(wait)

    def _response(
        self, resp: Any, entry: Any, call_start: float, attempts: list[CallAttempt]
    ) -> LLMResponse:
        latency = time.perf_counter() - call_start
        usage = getattr(resp, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", None)
        output_tokens = getattr(usage, "candidates_token_count", None)
        thinking = getattr(usage, "thoughts_token_count", None)
        total = getattr(usage, "total_token_count", None)
        if total is None and (input_tokens is not None or output_tokens is not None):
            total = (input_tokens or 0) + (output_tokens or 0) + (thinking or 0)
        self.limiter.settle(entry, total)
        self.daily.record(total)
        candidates = getattr(resp, "candidates", None) or []
        finish = getattr(candidates[0], "finish_reason", None) if candidates else None
        finish_reason = str(getattr(finish, "name", finish)) if finish is not None else None
        text = getattr(resp, "text", None) or ""
        if not text:
            feedback = getattr(resp, "prompt_feedback", None)
            blocked = getattr(feedback, "block_reason", None)
            reason = blocked if blocked is not None else finish_reason
            name = str(getattr(reason, "name", reason)) if reason is not None else None
            if name == "MAX_TOKENS":
                raise LLMError(
                    "gemini reply cut off before any text; raise llm.max_tokens", attempts
                )
            if name is not None and name != "STOP":
                raise LLMError(f"gemini returned no text (reason: {name})", attempts)
        return LLMResponse(
            text=text,
            model=str(self.model),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            thinking_tokens=thinking,
            finish_reason=finish_reason,
            started_at=call_start,
            latency_s=latency,
            attempts=attempts,
        )

    def list_models(self) -> list[str]:
        """Text models this API key can call, without the `models/` prefix."""
        out = []
        for m in self._client.models.list():
            actions = getattr(m, "supported_actions", None) or []
            if "generateContent" in actions:
                out.append(str(m.name).removeprefix("models/"))
        return sorted(out)

    def quota_status(self) -> dict[str, object]:
        return {**self.daily.status(), "last_stop": self.quota_stop}
