"""Fine-tuned change classifier: "will this change draw a review comment?".

The model scores diffs so review effort goes to the riskiest changes first. It predicts human
attention, not defects, so it only ever orders or gates LLM work; it never removes a finding.

Lives in `llm` because it is the only package allowed to import `transformers`. Heavy imports are
lazy, and a model is only ever loaded from a local directory, never downloaded at review time.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from marl_agents.config import ClassifierSettings
from marl_agents.llm.base import LLMError

logger = logging.getLogger(__name__)

METADATA_FILE = "classifier.json"
MAX_CHANGE_CHARS = 4000


def change_text(patch: str, max_chars: int = MAX_CHANGE_CHARS) -> str:
    """The one input format used by training, evaluation and review time.

    Keeps the unified diff, whose +/- markers are the signal. Long diffs keep their start, where
    the hunk header and the first changed lines are.
    """
    return patch.replace("\r\n", "\n").strip()[:max_chars]


class ClassifierMetadata(BaseModel):
    """Written next to the weights by the trainer, so a model always carries its provenance."""

    base_model: str
    max_length: int = 256
    threshold: float = 0.5
    trained_at: str | None = None
    train_examples: int | None = None
    method: str = "fine-tuning"


class ChangeClassifier(ABC):
    model_id: str = "base"
    threshold: float = 0.5  # the model's own operating point, chosen on dev at training time

    @abstractmethod
    def score(self, texts: list[str]) -> list[float]:
        """Probability-like score per change, higher = more likely to need review."""


class FixedScoreClassifier(ChangeClassifier):
    """Offline stand-in for tests: scores by a callable."""

    model_id = "fixed"

    def __init__(self, scorer: Any) -> None:
        self._scorer = scorer

    def score(self, texts: list[str]) -> list[float]:
        return [float(self._scorer(t)) for t in texts]


class TransformersChangeClassifier(ChangeClassifier):
    def __init__(self, model_dir: Path, batch_size: int = 16) -> None:
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as exc:
            raise LLMError("Install the `train` extra: pip install -e '.[train]'") from exc
        meta_path = model_dir / METADATA_FILE
        if not meta_path.is_file():
            raise LLMError(f"{model_dir} has no {METADATA_FILE}; train a model first")
        self.metadata = ClassifierMetadata.model_validate_json(
            meta_path.read_text(encoding="utf-8")
        )
        self.model_id = f"{model_dir.name} ({self.metadata.base_model})"
        self.threshold = self.metadata.threshold
        self.batch_size = batch_size
        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
        self._model = AutoModelForSequenceClassification.from_pretrained(
            model_dir, local_files_only=True
        ).eval()

    def score(self, texts: list[str]) -> list[float]:
        out: list[float] = []
        with self._torch.no_grad():
            for i in range(0, len(texts), self.batch_size):
                batch = self._tokenizer(
                    texts[i : i + self.batch_size],
                    truncation=True,
                    padding=True,
                    max_length=self.metadata.max_length,
                    return_tensors="pt",
                )
                logits = self._model(**batch).logits
                out.extend(self._torch.softmax(logits, dim=-1)[:, 1].tolist())
        return out


def create_classifier(settings: ClassifierSettings) -> ChangeClassifier | None:
    """None when the classifier is off. Asking for a missing model is an error, not a silent no."""
    if not settings.enabled:
        return None
    if not settings.model_dir:
        raise LLMError("classifier.enabled is true but classifier.model_dir is not set")
    path = Path(settings.model_dir)
    if not path.is_dir():
        raise LLMError(f"Classifier model not found: {path}")
    return TransformersChangeClassifier(path)


def read_metadata(model_dir: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((model_dir / METADATA_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
