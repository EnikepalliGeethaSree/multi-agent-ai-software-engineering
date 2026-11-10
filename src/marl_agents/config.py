"""Settings from configs/default.yaml, overridden by MARL_-prefixed environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "default.yaml"


# Listed as free on Google's pricing page (checked 2026-11-06) but badged "New", not "Stable", so
# `cli check` verifies it against the key and suggests a replacement if it is unavailable.
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
DEFAULT_OLLAMA_MODEL = "qwen2.5-coder:7b"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"


class LLMSettings(BaseModel):
    provider: Literal["mock", "openai", "groq", "gemini", "local", "ollama"] = "mock"
    model: str | None = None
    temperature: float = 0.0
    max_tokens: int = 2048
    seed: int | None = 42
    base_url: str | None = None
    api_key_env: str | None = None
    # Hosted-API quotas (Groq enforces per-model requests/tokens per minute). None = unlimited.
    requests_per_minute: int | None = None
    tokens_per_minute: int | None = None
    # Daily budgets checked locally before each request (Gemini). None = not checked.
    requests_per_day: int | None = None
    tokens_per_day: int | None = None
    # Refuse a request whose estimated input exceeds this; the agent retries it without context.
    max_input_tokens: int | None = None
    # Ollama only: the context window it is asked to use. It cuts longer prompts silently.
    context_window: int | None = None
    max_retries: int = 5
    timeout_s: float = 120.0
    json_mode: bool = True
    # Extra provider-specific request fields, e.g. {"reasoning_format": "hidden"} on Groq.
    extra_params: dict[str, Any] = {}
    # Pay-as-you-go safeguards (Groq Developer tier, D39). Cumulative across runs until the ledger
    # data/cache/llm_quota/groq_<model>_budget.json is reset on purpose. None = not capped.
    max_total_tokens: int | None = None
    max_estimated_cost_usd: float | None = None
    # USD per million tokens, from the provider's console. None = unknown (no cost estimate).
    input_price_per_1m_tokens_usd: float | None = None
    output_price_per_1m_tokens_usd: float | None = None
    # A paid provider refuses to start without a token or spending cap unless this is true.
    allow_uncapped: bool = False
    base_backoff_s: float = 2.0
    response_cache: bool = True
    response_cache_dir: str = "data/cache/llm_responses"


class IngestionSettings(BaseModel):
    max_zip_bytes: int = 100 * 1024 * 1024
    max_uncompressed_bytes: int = 500 * 1024 * 1024
    max_files: int = 20_000
    max_file_bytes: int = 2 * 1024 * 1024
    include_extensions: list[str] = [".py", ".md", ".txt", ".yaml", ".yml", ".json", ".toml"]
    ignore_dirs: list[str] = [".git", ".venv", "venv", "__pycache__", "node_modules"]
    workspace_dir: str = "data/workspaces"


class RAGSettings(BaseModel):
    enabled: bool = True
    vector_store: Literal["chroma", "memory"] = "chroma"
    persist_dir: str | None = "data/chroma"
    embedding_model: str = "hashing"
    top_k: int = 6
    guideline_k: int = 2
    structural_context: bool = True
    max_context_chars: int = 12_000


class ReviewSettings(BaseModel):
    mode: Literal["full", "static_only", "llm_only"] = "full"
    min_confidence: float = 0.3
    require_llm_evidence: bool = True
    max_unit_lines: int = 200
    max_units: int = 200
    include_info: bool = True
    llm_triage_static: bool = True
    scope_slack: int = 3
    include_tests: bool = False
    concurrency: int = 4
    type_check: bool = True  # mypy cross-file type checking (when installed)
    drop_vague: bool = True  # drop / downgrade non-actionable LLM findings
    suggest_fixes: bool = True  # LLM-written fixes, verified by re-analysis
    max_llm_fixes: int = 8
    max_impact_checks: int = 15  # change review: LLM checks of callers not updated
    # Reuse earlier work so a rerun after a quota stop repeats nothing. Off here and in evaluation
    # (a benchmark must measure real work); on in configs/default.yaml.
    unit_cache: bool = False
    analysis_cache: bool = False
    cache_dir: str = "data/cache"
    cache_ttl_hours: int = 168
    resume_ttl_hours: int = 72  # how long a partial dashboard review keeps its uploaded input


class BugSettings(BaseModel):
    """Bug Detection Agent. Each reviewed unit costs one LLM request, so scans are budgeted."""

    max_units: int = 12  # highest-risk units sent to the LLM in a scan; the rest are reported
    max_candidates: int = 40  # functions shown to the LLM for fault localization
    candidate_lines: int = 30  # lines of each candidate function in that prompt
    max_prompt_chars: int = 40_000  # candidates beyond this are ranked by static signals alone
    retrieval_k: int = 20  # extra candidates from retrieval (configuration D only)
    require_trigger: bool = True  # reject LLM bugs that do not say what makes the code fail


class ClassifierSettings(BaseModel):
    """Fine-tuned change classifier. It prioritizes review work; it never decides code is safe."""

    enabled: bool = False
    model_dir: str | None = None
    # "prioritize" reviews riskiest units first; "gate" also skips units scored below `threshold`.
    mode: Literal["prioritize", "gate"] = "prioritize"
    # None uses the model's own threshold, the one chosen on dev and evaluated on test.
    threshold: float | None = None


class DatasetSettings(BaseModel):
    root: str = "capstone-datasets"
    cache_dir: str = "data/cache"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MARL_",
        env_nested_delimiter="__",
        env_file=str(PROJECT_ROOT / ".env"),
        extra="ignore",
    )

    llm: LLMSettings = LLMSettings()
    ingestion: IngestionSettings = IngestionSettings()
    rag: RAGSettings = RAGSettings()
    review: ReviewSettings = ReviewSettings()
    datasets: DatasetSettings = DatasetSettings()
    classifier: ClassifierSettings = ClassifierSettings()
    bugs: BugSettings = BugSettings()


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_dotenv(path: Path | None = None) -> None:
    """Export KEY=VALUE lines from .env into os.environ (existing variables win).

    pydantic-settings only reads .env for MARL_* fields; provider keys such as GROQ_API_KEY are
    read from os.environ by the LLM factory, so they must be exported. Values are never logged.
    """
    env_path = path or PROJECT_ROOT / ".env"
    if os.environ.get("MARL_NO_DOTENV") or not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key and value and key not in os.environ:
            os.environ[key] = value


def _apply_llm_env(data: dict[str, Any]) -> dict[str, Any]:
    """LLM_PROVIDER / GEMINI_MODEL beat MARL_LLM__* and YAML: they are the documented switches.

    A leftover model id from another provider (e.g. a Groq model in .env) is not sent to Gemini.
    """
    llm = dict(data.get("llm") or {})
    provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if provider:
        llm["provider"] = provider
    llm["model"] = model_for(str(llm.get("provider") or ""), llm.get("model"))
    return {**data, "llm": llm}


def _foreign_to_ollama(model: str) -> bool:
    """Hosted model ids (Gemini, 'org/model') cannot be an Ollama model name."""
    return not model or model.startswith(("gemini", "gemma", "models/")) or "/" in model


# GROQ_* variables in .env override configs/groq.yaml (D39). Empty or "TBD" means "not set".
GROQ_ENV: dict[str, tuple[str, type]] = {
    "GROQ_MODEL": ("model", str),
    "GROQ_RPM": ("requests_per_minute", int),
    "GROQ_TPM": ("tokens_per_minute", int),
    "GROQ_DAILY_REQUEST_LIMIT": ("requests_per_day", int),
    "GROQ_DAILY_TOKEN_LIMIT": ("tokens_per_day", int),
    "GROQ_MAX_TOTAL_TOKENS": ("max_total_tokens", int),
    "GROQ_MAX_ESTIMATED_COST_USD": ("max_estimated_cost_usd", float),
    "GROQ_INPUT_PRICE_PER_1M_TOKENS_USD": ("input_price_per_1m_tokens_usd", float),
    "GROQ_OUTPUT_PRICE_PER_1M_TOKENS_USD": ("output_price_per_1m_tokens_usd", float),
    "GROQ_MAX_RETRIES": ("max_retries", int),
    "GROQ_BASE_BACKOFF_SECONDS": ("base_backoff_s", float),
}


def apply_groq_env(llm: LLMSettings) -> None:
    """Copy the GROQ_* settings from the environment into `llm`, so runs record what they used."""
    for name, (field, kind) in GROQ_ENV.items():
        raw = os.environ.get(name, "").strip()
        if not raw or raw.upper() == "TBD":
            continue
        try:
            value = kind(raw.replace(",", "").replace("_", "")) if kind is not str else raw
        except ValueError as exc:
            raise ValueError(f"{name} must be a number or TBD, not {raw!r}") from exc
        setattr(llm, field, value)


def model_for(provider: str, model: str | None) -> str | None:
    """The model a provider should use, so no run records another provider's model id.

    GEMINI_MODEL and OLLAMA_MODEL win for their provider. A leftover id from another provider is
    replaced by that provider's default.
    """
    current = str(model or "")
    if provider == "gemini":
        explicit = os.environ.get("GEMINI_MODEL", "").strip()
        if explicit:
            return explicit
        return (
            current if current.startswith(("gemini", "gemma", "models/")) else DEFAULT_GEMINI_MODEL
        )
    if provider == "groq":
        explicit = os.environ.get("GROQ_MODEL", "").strip()
        if explicit and explicit.upper() != "TBD":
            return explicit
        foreign = current.startswith(("gemini", "gemma", "models/")) or ":" in current
        return DEFAULT_GROQ_MODEL if not current or foreign else current
    if provider == "ollama":
        explicit = os.environ.get("OLLAMA_MODEL", "").strip()
        if explicit:
            return explicit
        return DEFAULT_OLLAMA_MODEL if _foreign_to_ollama(current) else current
    return model


# Providers one request (a dashboard review) may switch to, and the file holding their settings.
SELECTABLE_PROVIDERS: dict[str, Path] = {
    "gemini": PROJECT_ROOT / "configs" / "gemini.yaml",
    "ollama": PROJECT_ROOT / "configs" / "ollama.yaml",
}


def with_provider(settings: Settings, provider: str) -> Settings:
    """A copy of `settings` that uses another LLM provider, configured as `--provider X --config
    configs/X.yaml` would: default.yaml's llm section overlaid by the provider's file.

    Only the LLM settings and review concurrency change; everything else stays as the server has it.
    """
    if provider not in SELECTABLE_PROVIDERS:
        raise ValueError(
            f"provider must be one of {sorted(SELECTABLE_PROVIDERS)}, not {provider!r}"
        )
    if provider == settings.llm.provider:
        return settings.model_copy(deep=True)
    data = _read_yaml(DEFAULT_CONFIG) if DEFAULT_CONFIG.exists() else {}
    path = SELECTABLE_PROVIDERS[provider]
    if path.exists():
        data = _deep_merge(data, _read_yaml(path))
    llm = dict(data.get("llm") or {})
    llm["provider"] = provider
    llm["model"] = model_for(provider, llm.get("model"))
    out = settings.model_copy(deep=True)
    out.llm = LLMSettings(**llm)
    concurrency = (data.get("review") or {}).get("concurrency")
    if concurrency is not None:
        out.review.concurrency = int(concurrency)
    return out


def load_settings(config_path: Path | None = None) -> Settings:
    """configs/default.yaml, overlaid by `config_path` (e.g. configs/gemini.yaml), then env vars."""
    load_dotenv()
    data = _read_yaml(DEFAULT_CONFIG) if DEFAULT_CONFIG.exists() else {}
    if config_path is not None and Path(config_path).resolve() != DEFAULT_CONFIG.resolve():
        data = _deep_merge(data, _read_yaml(Path(config_path)))
    # Init kwargs beat env vars in pydantic-settings, so merge env on top explicitly.
    # MARL_NO_DOTENV=1 (set by the test suite) ignores .env so results do not depend on it.
    env_file = None if os.environ.get("MARL_NO_DOTENV") else str(PROJECT_ROOT / ".env")
    env_only = Settings(_env_file=env_file)
    merged = _apply_llm_env(_deep_merge(data, env_only.model_dump(exclude_defaults=True)))
    settings = Settings(_env_file=env_file, **merged)
    if settings.llm.provider == "groq":
        apply_groq_env(settings.llm)
    return settings
