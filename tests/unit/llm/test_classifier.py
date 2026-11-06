"""Classifier configuration: asking for a missing model must fail loudly, never silently skip."""

from __future__ import annotations

from pathlib import Path

import pytest

from marl_agents.config import ClassifierSettings, Settings
from marl_agents.evaluation.configurations import classify_config_dict, classify_settings
from marl_agents.llm import LLMError
from marl_agents.llm.classifier import (
    METADATA_FILE,
    ClassifierMetadata,
    create_classifier,
    read_metadata,
)


def test_classifier_is_off_by_default() -> None:
    assert create_classifier(ClassifierSettings()) is None


def test_enabled_without_a_model_is_an_error() -> None:
    with pytest.raises(LLMError, match="model_dir"):
        create_classifier(ClassifierSettings(enabled=True))


def test_missing_model_folder_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(LLMError, match="not found"):
        create_classifier(ClassifierSettings(enabled=True, model_dir=str(tmp_path / "nope")))


def test_folder_without_metadata_is_an_error(tmp_path: Path) -> None:
    pytest.importorskip("transformers")
    with pytest.raises(LLMError, match=METADATA_FILE):
        create_classifier(ClassifierSettings(enabled=True, model_dir=str(tmp_path)))


def test_metadata_round_trip(tmp_path: Path) -> None:
    meta = ClassifierMetadata(base_model="microsoft/codebert-base", threshold=0.42)
    (tmp_path / METADATA_FILE).write_text(meta.model_dump_json(), encoding="utf-8")
    assert read_metadata(tmp_path)["threshold"] == 0.42  # type: ignore[index]
    assert read_metadata(tmp_path / "missing") is None


def test_a_run_with_the_classifier_is_never_counted_as_d(settings: Settings) -> None:
    assert classify_settings(settings).key == "static_llm_rag"
    settings.classifier.enabled = True
    assert classify_settings(settings).letter == "E"
    cfg = {"review": {"mode": "full"}, "rag": {"enabled": True}, "classifier": {"enabled": True}}
    assert classify_config_dict(cfg).letter == "E"  # type: ignore[union-attr]
    assert classify_config_dict({"review": {"mode": "full"}}).letter == "D"  # type: ignore[union-attr]
