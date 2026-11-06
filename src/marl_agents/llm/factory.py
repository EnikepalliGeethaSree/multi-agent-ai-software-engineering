"""Build a provider from config. SDKs are imported lazily inside each provider."""

from __future__ import annotations

import os
import re

from marl_agents.config import PROJECT_ROOT, LLMSettings
from marl_agents.llm.base import GenerationConfig, LLMError, LLMProvider
from marl_agents.llm.mock import MockLLMProvider
from marl_agents.llm.rate_limit import DailyQuota, RateLimiter

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_DEFAULT_RPM = 30
GROQ_DEFAULT_TPM = 6000
_DEFAULT_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "local": "",
}


def create_provider(settings: LLMSettings) -> LLMProvider:
    config = GenerationConfig(
        temperature=settings.temperature, max_tokens=settings.max_tokens, seed=settings.seed
    )
    if settings.provider == "mock":
        provider: LLMProvider = MockLLMProvider()
        provider.config = config
        return provider

    if not settings.model:
        hint = " (list them with: python -m marl_agents.cli models --provider groq)"
        raise LLMError(
            f"Set llm.model (MARL_LLM__MODEL) for provider '{settings.provider}'"
            + (hint if settings.provider == "groq" else "")
        )
    key_env = settings.api_key_env or _DEFAULT_KEY_ENV.get(settings.provider, "")
    api_key = os.environ.get(key_env) if key_env else None
    if settings.provider == "gemini" and not api_key:
        api_key = os.environ.get("GOOGLE_API_KEY")  # the SDK's own variable also works

    if settings.provider in {"openai", "groq", "local"}:
        from marl_agents.llm.openai_compat import OpenAICompatibleProvider

        base_url = settings.base_url
        rpm, tpm = settings.requests_per_minute, settings.tokens_per_minute
        if settings.provider == "groq":
            base_url = base_url or GROQ_BASE_URL
            # Conservative defaults so an unconfigured run throttles instead of hitting 429s.
            rpm = rpm or GROQ_DEFAULT_RPM
            tpm = tpm or GROQ_DEFAULT_TPM
            if not api_key:
                raise LLMError(
                    f"{key_env} is not set (create a key at https://console.groq.com/keys)"
                )
        elif settings.provider == "local":
            base_url = base_url or os.environ.get("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
        elif not api_key and not base_url:
            raise LLMError(f"{key_env} is not set")
        return OpenAICompatibleProvider(
            model=settings.model,
            api_key=api_key,
            base_url=base_url,
            config=config,
            max_retries=settings.max_retries,
            timeout=settings.timeout_s,
            json_mode=settings.json_mode,
            name=settings.provider,
            rate_limiter=RateLimiter(rpm, tpm),
            extra_params=settings.extra_params,
        )
    if settings.provider == "gemini":
        from marl_agents.llm.gemini import GeminiProvider

        if not api_key:
            raise LLMError(
                f"{key_env} is not set. Create a free key at https://aistudio.google.com/apikey "
                "and put it in .env (never in a config file)."
            )
        slug = re.sub(r"[^A-Za-z0-9._-]+", "_", settings.model)
        return GeminiProvider(
            model=settings.model,
            api_key=api_key,
            config=config,
            max_retries=settings.max_retries,
            timeout=settings.timeout_s,
            json_mode=settings.json_mode,
            rate_limiter=RateLimiter(settings.requests_per_minute, settings.tokens_per_minute),
            daily_quota=DailyQuota(
                PROJECT_ROOT / "data" / "cache" / "llm_quota" / f"gemini_{slug}.json",
                settings.requests_per_day,
                settings.tokens_per_day,
            ),
            max_input_tokens=settings.max_input_tokens,
            extra_params=settings.extra_params,
        )
    raise LLMError(f"Unknown LLM provider '{settings.provider}'")
