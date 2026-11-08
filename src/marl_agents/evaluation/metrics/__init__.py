"""Evaluation metrics (each implementation is unit-tested against hand-computed values)."""

from marl_agents.evaluation.metrics.agreement import (
    agreement_rates,
    pearson,
    spearman,
    weighted_kappa,
)
from marl_agents.evaluation.metrics.classification import (
    BinaryMetrics,
    binary_metrics,
    bootstrap_ci,
    roc_auc,
)
from marl_agents.evaluation.metrics.detection import (
    DetectionMetrics,
    ExpectedIssue,
    detection_metrics,
)
from marl_agents.evaluation.metrics.localization import (
    LocalizationMetrics,
    PairOutcomes,
    cohen_kappa,
    localization_metrics,
    mcnemar_exact,
    pair_outcomes,
    random_top_k,
)
from marl_agents.evaluation.metrics.retrieval import (
    hit_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from marl_agents.evaluation.metrics.text import (
    chrf,
    corpus_bleu_avg,
    rouge_l,
    sentence_bleu,
    tokenize,
)

__all__ = [
    "BinaryMetrics",
    "DetectionMetrics",
    "ExpectedIssue",
    "LocalizationMetrics",
    "PairOutcomes",
    "agreement_rates",
    "binary_metrics",
    "bootstrap_ci",
    "chrf",
    "cohen_kappa",
    "corpus_bleu_avg",
    "detection_metrics",
    "hit_at_k",
    "localization_metrics",
    "mcnemar_exact",
    "ndcg_at_k",
    "pair_outcomes",
    "pearson",
    "precision_at_k",
    "random_top_k",
    "recall_at_k",
    "reciprocal_rank",
    "roc_auc",
    "rouge_l",
    "sentence_bleu",
    "spearman",
    "tokenize",
    "weighted_kappa",
]
