"""Read saved evaluation runs (experiments/results/<stamp>_<kind>_<rest>/) and classify them.

A run's configuration comes from, in order: ``meta.json["experiment"]`` (runs made since the
ablation framework), its ``config.yaml`` (every run ever saved has one), and only as a last resort
the tag in its folder name. Nothing is guessed beyond that: an unclassifiable run is skipped by the
comparison tables.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml

from marl_agents.evaluation.configurations import (
    CONFIGURATIONS,
    LLM_RAG,
    ExperimentConfiguration,
    classify_config_dict,
    sample_fingerprint,
)

logger = logging.getLogger(__name__)

RUN = re.compile(r"^(?P<stamp>\d{8}T\d{6}Z)_(?P<kind>[a-z]+)_(?P<rest>.*?)(?:_x\d+)?$")


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _float(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def _tag_configuration(tag: str) -> ExperimentConfiguration | None:
    """Fallback for runs without config.yaml: old tags were `<mode>[_norag]`.

    Only what the tag states is used: `full` / `llm_only` without `_norag` do not record whether
    RAG was on, so they stay unclassified rather than guessed.
    """
    tag = re.sub(r"_n\d+$", "", tag)
    if tag in CONFIGURATIONS:
        return CONFIGURATIONS[tag]
    if tag == "llm_only_norag":
        return CONFIGURATIONS["llm_only"]
    if tag == "full_norag":
        return CONFIGURATIONS["static_llm"]
    return None


@dataclass
class SavedRun:
    path: Path
    stamp: str
    kind: str
    rest: str
    metrics: dict[str, Any]
    meta: dict[str, Any]
    config: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def experiment(self) -> dict[str, Any]:
        exp = self.meta.get("experiment") or self.metrics.get("experiment")
        return exp if isinstance(exp, dict) else {}

    @property
    def task(self) -> str | None:
        """CodeReviewer task (cls / msg) or None."""
        if self.kind != "codereviewer":
            return None
        return str(self.metrics.get("task") or self.meta.get("task") or self.rest.split("_")[0])

    @property
    def split(self) -> str | None:
        split = self.meta.get("split") or self.experiment.get("split")
        if split:
            return str(split)
        parts = self.rest.split("_")
        if self.kind == "codereviewer" and len(parts) > 1:
            return parts[1]
        if self.kind == "hunkrisk" and len(parts) > 1:
            return parts[1]
        return None

    @cached_property
    def configuration(self) -> ExperimentConfiguration | None:
        stored = self.experiment.get("configuration")
        if isinstance(stored, dict) and stored.get("key"):
            key = stored["key"]
            return CONFIGURATIONS.get(key) or (LLM_RAG if key == LLM_RAG.key else None)
        from_config = classify_config_dict(self.config)
        if from_config is not None:
            return from_config
        tag = self.rest
        if self.kind == "codereviewer":
            tag = self.rest.split("_", 2)[-1] if self.rest.count("_") >= 2 else self.rest
        return _tag_configuration(tag)

    @property
    def model(self) -> str | None:
        exp_llm = self.experiment.get("llm")
        if isinstance(exp_llm, dict):
            return exp_llm.get("model")
        if self.configuration is not None and not self.configuration.llm:
            return None
        return self.meta.get("llm_model") or (self.config.get("llm") or {}).get("model")

    @property
    def provider(self) -> str | None:
        exp_llm = self.experiment.get("llm")
        if isinstance(exp_llm, dict):
            return exp_llm.get("provider")
        if self.configuration is not None and not self.configuration.llm:
            return None
        return self.meta.get("llm_provider") or (self.config.get("llm") or {}).get("provider")

    def setting(self, section: str, key: str) -> Any:
        """A value from the run's config.yaml (None when not recorded)."""
        sec = self.config.get(section)
        return sec.get(key) if isinstance(sec, dict) else None

    @property
    def temperature(self) -> float | None:
        exp_llm = self.experiment.get("llm")
        if isinstance(exp_llm, dict):
            return _float(exp_llm.get("temperature"))
        if self.configuration is None or not self.configuration.llm:
            return None
        return _float(self.setting("llm", "temperature"))

    @property
    def confidence_threshold(self) -> float | None:
        value = self.experiment.get("confidence_threshold")
        return _float(value if value is not None else self.setting("review", "min_confidence"))

    @property
    def sample_ids(self) -> list[str]:
        ids = self.meta.get("sample_ids")
        return [str(x) for x in ids] if isinstance(ids, list) else []

    @property
    def fingerprint(self) -> str | None:
        stored = self.experiment.get("sample_fingerprint")
        if stored:
            return str(stored)
        return sample_fingerprint(self.sample_ids) if self.sample_ids else None

    @property
    def group_id(self) -> str | None:
        gid = self.experiment.get("group_id")
        return str(gid) if gid else None

    @property
    def aborted(self) -> bool:
        return (self.path / "ABORTED.txt").exists()

    def predictions(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        path = self.path / "predictions.jsonl"
        if not path.is_file():
            return out
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        logger.warning("unreadable prediction line in %s", path)
        return out


def load_run(path: Path) -> SavedRun | None:
    match = RUN.match(path.name)
    if not match or not (path / "metrics.json").is_file():
        return None
    config: dict[str, Any] = {}
    cfg_path = path / "config.yaml"
    if cfg_path.is_file():
        try:
            loaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
            config = loaded if isinstance(loaded, dict) else {}
        except (OSError, yaml.YAMLError):
            config = {}
    return SavedRun(
        path=path,
        stamp=match["stamp"],
        kind=match["kind"],
        rest=match["rest"],
        metrics=read_json(path / "metrics.json"),
        meta=read_json(path / "meta.json"),
        config=config,
    )


def load_runs(results_dir: Path) -> list[SavedRun]:
    """All complete runs, oldest first (folder names start with a UTC timestamp)."""
    if not results_dir.is_dir():
        return []
    runs = []
    for d in sorted(p for p in results_dir.iterdir() if p.is_dir()):
        run = load_run(d)
        if run is not None and not run.aborted:
            runs.append(run)
    return runs
