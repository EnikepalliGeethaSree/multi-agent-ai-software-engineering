"""The four ablation configurations of the Code Review Agent evaluation, and run metadata.

    A  Static Only         static ON   LLM OFF  RAG OFF   review.mode=static_only
    B  LLM Only            static OFF  LLM ON   RAG OFF   review.mode=llm_only, rag.enabled=false
    C  Static + LLM        static ON   LLM ON   RAG OFF   review.mode=full,     rag.enabled=false
    D  Static + LLM + RAG  static ON   LLM ON   RAG ON    review.mode=full,     rag.enabled=true

"RAG" is the agent's whole project-context layer (`ContextBuilder`): vector retrieval of similar
code and of coding guidelines, plus call-graph neighbours. With ``rag.enabled=false`` no retriever
and no context builder are created, so the LLM sees only the code under review (and in C the static
findings it is asked to triage). Static Only never builds a retriever whatever ``rag.enabled`` says,
so its effective RAG flag is always off.

A configuration is classified from the *effective* settings, never from a run's name, so runs saved
before this module existed are classified exactly from their ``config.yaml``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from marl_agents.config import Settings


class ExperimentConfiguration(BaseModel):
    key: str
    letter: str | None = None
    label: str
    static: bool
    llm: bool
    rag: bool
    mode: str
    description: str = ""


CONFIGURATIONS: dict[str, ExperimentConfiguration] = {
    c.key: c
    for c in (
        ExperimentConfiguration(
            key="static_only", letter="A", label="Static Only", static=True, llm=False,
            rag=False, mode="static_only",
            description="Ruff, Radon, AST checks, secrets, test gaps (and mypy when enabled).",
        ),
        ExperimentConfiguration(
            key="llm_only", letter="B", label="LLM Only", static=False, llm=True, rag=False,
            mode="llm_only",
            description="The LLM reviews the code alone: no static findings, no project context.",
        ),
        ExperimentConfiguration(
            key="static_llm", letter="C", label="Static + LLM", static=True, llm=True, rag=False,
            mode="full",
            description="Static findings plus LLM review and triage, without project context.",
        ),
        ExperimentConfiguration(
            key="static_llm_rag", letter="D", label="Static + LLM + RAG", static=True, llm=True,
            rag=True, mode="full",
            description="The full agent: static analysis, LLM review, retrieved project context.",
        ),
    )
}  # fmt: skip
ORDER = list(CONFIGURATIONS)
# The full agent with the fine-tuned classifier ordering or gating its LLM work. Kept apart from D
# so a run with the classifier can never be counted as a D run.
WITH_CLASSIFIER = ExperimentConfiguration(
    key="static_llm_rag_classifier",
    letter="E",
    label="Static + LLM + RAG + Classifier",
    static=True,
    llm=True,
    rag=True,
    mode="full",
)
# Not one of the four, but reachable with `--mode llm_only` (RAG on by default): kept distinct.
LLM_RAG = ExperimentConfiguration(
    key="llm_rag", label="LLM + RAG (no static)", static=False, llm=True, rag=True, mode="llm_only"
)


def classify(mode: str, rag_enabled: bool) -> ExperimentConfiguration:
    """The configuration a run actually used (effective flags, not the requested ones)."""
    static, llm = mode != "llm_only", mode != "static_only"
    rag = llm and bool(rag_enabled)
    for c in CONFIGURATIONS.values():
        if (c.static, c.llm, c.rag) == (static, llm, rag):
            return c
    return LLM_RAG


def classify_settings(settings: Settings) -> ExperimentConfiguration:
    config = classify(settings.review.mode, settings.rag.enabled)
    if settings.classifier.enabled and config.key == "static_llm_rag":
        return WITH_CLASSIFIER
    return config


def classify_config_dict(cfg: dict[str, Any]) -> ExperimentConfiguration | None:
    """Classify a saved run's ``config.yaml`` (None when it does not say)."""
    review, rag = cfg.get("review"), cfg.get("rag")
    if not isinstance(review, dict) or "mode" not in review:
        return None
    enabled = rag.get("enabled", True) if isinstance(rag, dict) else True
    config = classify(str(review["mode"]), bool(enabled))
    classifier = cfg.get("classifier")
    if isinstance(classifier, dict) and classifier.get("enabled") and config.letter == "D":
        return WITH_CLASSIFIER
    return config


def apply_configuration(base: Settings, key: str) -> Settings:
    """A copy of `base` where only the variables under test (static / LLM / RAG) differ."""
    if key not in CONFIGURATIONS:
        raise ValueError(f"unknown configuration {key!r}; choose from {ORDER}")
    c = CONFIGURATIONS[key]
    s = base.model_copy(deep=True)
    s.review.mode = c.mode  # type: ignore[assignment]
    s.rag.enabled = c.rag
    return s


def sample_fingerprint(sample_ids: Iterable[str]) -> str:
    """Order-independent id of a sample set: equal fingerprints = identical samples."""
    joined = "\n".join(sorted(set(sample_ids)))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def experiment_metadata(
    settings: Settings,
    *,
    benchmark: str,
    llm_used: bool,
    sample_ids: list[str] | None = None,
    n_evaluated: int | None = None,
    n_failed: int | None = None,
    dataset: str | None = None,
    split: str | None = None,
    seed: int | None = None,
    limit: int | None = None,
    evaluation_rules: dict[str, Any] | None = None,
    analyzers: list[str] | None = None,
    group_id: str | None = None,
    repeat: int | None = None,
    repeats: int | None = None,
) -> dict[str, Any]:
    """Everything needed to reproduce (and fairly compare) one evaluation run.

    Saved in both meta.json and metrics.json under ``experiment``.
    """
    from marl_agents.agents.code_review.prompts import prompt_versions

    config = classify_settings(settings)
    llm = settings.llm
    rag = settings.rag
    return {
        "configuration": config.model_dump(exclude={"description"}),
        "benchmark": benchmark,
        "dataset": dataset,
        "split": split,
        "sampling_seed": seed,
        "limit": limit,
        "sample_count": len(sample_ids) if sample_ids is not None else None,
        "sample_fingerprint": sample_fingerprint(sample_ids) if sample_ids else None,
        "n_evaluated": n_evaluated,
        "n_failed": n_failed,
        "llm": {
            "provider": llm.provider,
            "model": llm.model,
            "temperature": llm.temperature,
            "seed": llm.seed,
            "max_tokens": llm.max_tokens,
        }
        if llm_used and config.llm
        else None,
        "rag": {
            "top_k": rag.top_k,
            "guideline_k": rag.guideline_k,
            "embedding_model": rag.embedding_model,
            "vector_store": rag.vector_store,
            "structural_context": rag.structural_context,
            "max_context_chars": rag.max_context_chars,
        }
        if config.rag
        else None,
        "static_analyzers": analyzers if config.static else [],
        "classifier": settings.classifier.model_dump() if settings.classifier.enabled else None,
        "confidence_threshold": settings.review.min_confidence,
        "include_info": settings.review.include_info,
        "evaluation_rules": evaluation_rules or {},
        "prompt_versions": prompt_versions() if config.llm else {},
        "group_id": group_id,
        "repeat": repeat,
        "repeats": repeats,
        "timestamp": datetime.now(UTC).isoformat(),
    }
