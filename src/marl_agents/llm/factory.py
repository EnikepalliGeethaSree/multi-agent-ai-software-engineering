"""Build a provider from config. SDKs are imported lazily inside each provider."""

from __future__ import annotations

import os
import re

from marl_agents.config import PROJECT_ROOT, LLMSettings
from marl_agents.llm.base import GenerationConfig, LLMError, LLMProvider
from marl_agents.llm.mock import MockLLMProvider
from marl_agents.llm.rate_limit import DailyQuota, RateLimiter

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_DEFAULT_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "ollama": "",  # local: no key is read or sent
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

    if settings.provider == "groq":
        return _create_groq(settings, config, api_key)

    if settings.provider in {"openai", "local"}:
        from marl_agents.llm.openai_compat import OpenAICompatibleProvider

        base_url = settings.base_url
        rpm, tpm = settings.requests_per_minute, settings.tokens_per_minute
        if settings.provider == "local":
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
    if settings.provider == "ollama":
        from marl_agents.llm.ollama import DEFAULT_CONTEXT, OllamaProvider

        return OllamaProvider(
            model=settings.model,
            base_url=settings.base_url or os.environ.get("OLLAMA_BASE_URL"),
            config=config,
            timeout=settings.timeout_s,
            context_window=settings.context_window or DEFAULT_CONTEXT,
            json_mode=settings.json_mode,
            extra_options=settings.extra_params,
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


def _create_groq(
    settings: LLMSettings, config: GenerationConfig, api_key: str | None
) -> LLMProvider:
    """Groq with one API key (GROQ_API_KEY), Developer tier, pinned model (D39).

    Every limit and price comes from configuration (configs/groq.yaml, overridden by GROQ_* in
    .env); none is assumed. A paid provider needs a token or spending cap unless
    `allow_uncapped` is set.
    """
    from marl_agents.llm.budget import Prices, UsageBudget
    from marl_agents.llm.groq import GroqProvider
    from marl_agents.llm.rate_limit import next_utc_midnight, utc_date
    from marl_agents.llm.response_cache import ResponseCache

    if not api_key:
        raise LLMError(
            "GROQ_API_KEY is not set. Put one key in .env (see .env.example); create it at "
            "https://console.groq.com/keys"
        )
    if (
        settings.max_total_tokens is None
        and settings.max_estimated_cost_usd is None
        and not settings.allow_uncapped
    ):
        raise LLMError(
            "Groq is pay-as-you-go: set GROQ_MAX_TOTAL_TOKENS or GROQ_MAX_ESTIMATED_COST_USD in "
            ".env (or llm.allow_uncapped: true) before making calls"
        )
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", str(settings.model))
    ledgers = PROJECT_ROOT / "data" / "cache" / "llm_quota"
    try:
        budget = UsageBudget(
            ledgers / f"groq_{slug}_budget.json",
            Prices(
                input_per_mtok=settings.input_price_per_1m_tokens_usd,
                output_per_mtok=settings.output_price_per_1m_tokens_usd,
            ),
            max_total_tokens=settings.max_total_tokens,
            max_cost_usd=settings.max_estimated_cost_usd,
        )
    except ValueError as exc:
        raise LLMError(str(exc)) from exc
    daily = None
    if settings.requests_per_day is not None or settings.tokens_per_day is not None:
        daily = DailyQuota(
            ledgers / f"groq_{slug}_daily.json",
            settings.requests_per_day,
            settings.tokens_per_day,
            day_of=utc_date,
            next_reset=next_utc_midnight,
        )
    return GroqProvider(
        model=str(settings.model),
        api_key=api_key,
        config=config,
        base_url=settings.base_url or GROQ_BASE_URL,
        timeout=settings.timeout_s,
        json_mode=settings.json_mode,
        extra_params=settings.extra_params,
        limiter=RateLimiter(settings.requests_per_minute, settings.tokens_per_minute),
        daily=daily,
        budget=budget,
        cache=(
            ResponseCache(PROJECT_ROOT / settings.response_cache_dir / "groq")
            if settings.response_cache
            else None
        ),
        max_attempts=settings.max_retries,
        base_backoff_s=settings.base_backoff_s,
    )
