"""Build a provider from config. SDKs are imported lazily inside each provider."""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

from marl_agents.config import PROJECT_ROOT, LLMSettings
from marl_agents.llm.base import GenerationConfig, LLMError, LLMProvider
from marl_agents.llm.mock import MockLLMProvider
from marl_agents.llm.rate_limit import DailyQuota, RateLimiter

if TYPE_CHECKING:
    from marl_agents.llm.groq import GroqProvider

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_DEFAULT_RPM = 30
GROQ_DEFAULT_TPM = 6000
# Free-plan limits of openai/gpt-oss-120b per Groq's rate-limits page (2026-11): 30 RPM, 1K RPD,
# 8K TPM, 200K TPD, counted per organization. Your console's limits page is authoritative.
GROQ_FREE_LIMITS = {"rpm": 30, "tpm": 8000, "rpd": 1000, "tpd": 200_000}
GROQ_KEY_ENVS = [f"GROQ_API_KEY_{i}" for i in range(1, 11)]
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
        rotating = _create_rotating_groq(settings, config)
        if rotating is not None:
            return rotating

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


def _create_rotating_groq(settings: LLMSettings, config: GenerationConfig) -> GroqProvider | None:
    """Groq with round-robin keys (D38), or None to keep the single-key path (GROQ_API_KEY).

    Used when `llm.key_rotation` is true, `llm.api_key_envs` is set, or GROQ_API_KEY_1..10 exist.
    """
    from marl_agents.llm.keys import KeyManager, Limits, load_keys

    names = settings.api_key_envs or GROQ_KEY_ENVS
    keys = load_keys(names)
    if not keys and not (settings.key_rotation or settings.api_key_envs):
        return None
    if not keys:
        keys = [("key1", s) for _, s in load_keys(["GROQ_API_KEY"])]
    if not keys:
        raise LLMError(
            f"No Groq API key found: set {names[0]} (up to {names[-1]}) in .env. "
            "Create keys at https://console.groq.com/keys"
        )
    from marl_agents.llm.groq import GROQ_BASE_URL as BASE
    from marl_agents.llm.groq import GroqProvider
    from marl_agents.llm.response_cache import ResponseCache

    free = GROQ_FREE_LIMITS
    per_key = Limits(
        rpm=settings.requests_per_minute or free["rpm"],
        tpm=settings.tokens_per_minute or free["tpm"],
        rpd=settings.requests_per_day or free["rpd"],
        tpd=settings.tokens_per_day or free["tpd"],
    )
    shared = Limits(
        rpm=settings.shared_requests_per_minute or per_key.rpm,
        tpm=settings.shared_tokens_per_minute or per_key.tpm,
        rpd=settings.shared_requests_per_day or per_key.rpd,
        tpd=settings.shared_tokens_per_day or per_key.tpd,
    )
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", str(settings.model))
    manager = KeyManager(
        keys,
        per_key=per_key,
        shared=shared,
        ledger_dir=PROJECT_ROOT / "data" / "cache" / "llm_quota",
        ledger_prefix=f"groq_{slug}",
        shared_org=settings.keys_share_limits,
    )
    cache = (
        ResponseCache(PROJECT_ROOT / settings.response_cache_dir / "groq")
        if settings.response_cache
        else None
    )
    return GroqProvider(
        model=str(settings.model),
        keys=manager,
        config=config,
        base_url=settings.base_url or BASE,
        timeout=settings.timeout_s,
        json_mode=settings.json_mode,
        extra_params=settings.extra_params,
        cache=cache,
    )
