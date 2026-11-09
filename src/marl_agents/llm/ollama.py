"""Local inference through Ollama's own API (http://localhost:11434 by default).

Uses `/api/chat` rather than Ollama's OpenAI-compatible route, because only the native API takes a
context window (`num_ctx`). Ollama's default window is small and it cuts longer prompts silently, so
the window is always set and a prompt that would not fit is refused before sending: the agent then
retries without retrieved context, as it does for any provider's size limit.

Standard library only. Nothing secret is sent: Ollama needs no key.

Failures that a retry cannot fix are raised at once with what to do: Ollama not running, model not
installed, request timed out (raise `llm.timeout_s`), server error. Malformed JSON is handled by
`generate_structured`, which asks once for a corrected reply.
"""

from __future__ import annotations

import json
import logging
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from marl_agents.llm.base import (
    CallAttempt,
    GenerationConfig,
    LLMError,
    LLMProvider,
    LLMResponse,
    Message,
    RequestTooLargeError,
)
from marl_agents.llm.rate_limit import estimate_tokens

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5-coder:7b"
DEFAULT_CONTEXT = 16384
LIST_TIMEOUT_S = 10.0

Opener = Callable[..., Any]


def base_url_of(url: str | None) -> str:
    """Ollama's root URL. An OpenAI-style '/v1' suffix is dropped, so either form works.

    Only http and https are accepted, so a misconfigured URL can never open a local file.
    """
    root = (url or DEFAULT_BASE_URL).rstrip("/")
    if not root.startswith(("http://", "https://")):
        raise LLMError(f"Ollama base URL must start with http:// or https://, not {root!r}")
    return root[:-3] if root.endswith("/v1") else root


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str | None = None,
        config: GenerationConfig | None = None,
        timeout: float = 600.0,
        context_window: int = DEFAULT_CONTEXT,
        json_mode: bool = True,
        extra_options: dict[str, Any] | None = None,
        opener: Opener = urllib.request.urlopen,
    ) -> None:
        super().__init__(model=model, config=config)
        self.base_url = base_url_of(base_url)
        self.timeout = timeout
        self.context_window = context_window
        self.json_mode = json_mode
        self.extra_options = dict(extra_options or {})
        self._open = opener

    # ---- HTTP -----------------------------------------------------------------------------------

    def _request(self, path: str, body: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310 - scheme checked in base_url_of
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if body is not None else "GET",
        )
        # The scheme is checked in base_url_of: http or https only.
        with self._open(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else {}

    def _failure(self, exc: Exception) -> LLMError:
        """One clear message per failure kind. None of these is worth retrying."""
        if isinstance(exc, urllib.error.HTTPError):
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("error", "")
            except (ValueError, OSError, AttributeError):
                detail = str(exc)
            if exc.code == 404 or "not found" in str(detail).lower():
                return LLMError(
                    f"Ollama model '{self.model}' is not installed. Run: ollama pull {self.model}"
                )
            return LLMError(f"Ollama returned HTTP {exc.code}: {str(detail)[:300]}")
        if isinstance(exc, TimeoutError | socket.timeout) or "timed out" in str(exc).lower():
            return LLMError(
                f"Ollama did not answer within {self.timeout:.0f}s. Local inference can be slow; "
                "raise llm.timeout_s or use a smaller prompt."
            )
        if isinstance(exc, urllib.error.URLError | ConnectionError):
            return LLMError(
                f"Cannot reach Ollama at {self.base_url}. Start it (the Ollama app, or "
                "`ollama serve`) and try again."
            )
        return LLMError(f"Ollama request failed: {type(exc).__name__}: {exc}")

    # ---- models ---------------------------------------------------------------------------------

    def list_models(self) -> list[str]:
        try:
            tags = self._request("/api/tags", None, LIST_TIMEOUT_S)
        except (OSError, ValueError) as exc:
            raise self._failure(exc) from exc
        return sorted(str(m.get("name")) for m in tags.get("models", []) if m.get("name"))

    def ensure_model(self) -> None:
        """Raise with the install command if the configured model is not present."""
        if self.model not in self.list_models():
            raise LLMError(
                f"Ollama model '{self.model}' is not installed. Run: ollama pull {self.model}"
            )

    # ---- generation -----------------------------------------------------------------------------

    def generate(
        self, messages: list[Message], config: GenerationConfig | None = None
    ) -> LLMResponse:
        cfg = config or self.config
        prompt_tokens = estimate_tokens("".join(m.content for m in messages))
        if prompt_tokens + cfg.max_tokens > self.context_window:
            raise RequestTooLargeError(
                f"ollama: about {prompt_tokens} prompt tokens (local estimate) plus "
                f"{cfg.max_tokens} for the reply exceed the {self.context_window}-token context "
                "window; not sent, because Ollama would cut the prompt silently"
            )
        options: dict[str, Any] = {
            "temperature": cfg.temperature,
            "num_predict": cfg.max_tokens,
            "num_ctx": self.context_window,
            **self.extra_options,
        }
        if cfg.seed is not None:
            options["seed"] = cfg.seed
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": options,
        }
        if self.json_mode:
            body["format"] = "json"
        start = time.perf_counter()
        try:
            reply = self._request("/api/chat", body, self.timeout)
        except (OSError, ValueError) as exc:
            failure = self._failure(exc)
            failure.attempts = [
                CallAttempt(
                    started_at=start,
                    latency_s=time.perf_counter() - start,
                    status=getattr(exc, "code", None),
                    error_kind="fatal",
                )
            ]
            raise failure from exc
        latency = time.perf_counter() - start
        if reply.get("error"):
            raise LLMError(f"Ollama error: {str(reply['error'])[:300]}")
        used_in = reply.get("prompt_eval_count")
        used_out = reply.get("eval_count")
        if isinstance(used_in, int) and used_in >= self.context_window - 8:
            raise RequestTooLargeError(
                f"ollama: the prompt filled the {self.context_window}-token context window, so it "
                "may have been cut; refusing the reply"
            )
        done = reply.get("done_reason")
        return LLMResponse(
            text=str((reply.get("message") or {}).get("content") or ""),
            model=str(reply.get("model") or self.model),
            input_tokens=used_in if isinstance(used_in, int) else None,
            output_tokens=used_out if isinstance(used_out, int) else None,
            finish_reason="MAX_TOKENS" if done == "length" else (str(done) if done else None),
            started_at=start,
            latency_s=latency,
        )
