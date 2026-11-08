"""Persist every experiment run so each reported number is traceable and reproducible.

experiments/results/<timestamp>_<name>/
    config.yaml        full settings used
    meta.json          git commit, versions, dataset/split/seed, sample ids, timings
    predictions.jsonl  raw per-sample outputs
    errors.jsonl       per-sample failures (never silently dropped)
    metrics.json       computed metrics
    summary.md         human-readable table
"""

from __future__ import annotations

import json
import platform
import subprocess
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import yaml

from marl_agents.config import PROJECT_ROOT, Settings

_PACKAGES = [
    "marl-agents",
    "pydantic",
    "ruff",
    "radon",
    "chromadb",
    "openai",
    "sentence-transformers",
]


# Evaluation output, not source: a run's own new folder must not mark its code as uncommitted.
OUTPUT_DIRS = ("experiments/results/", "experiments/evaluation_summary/")


def source_changes(porcelain: str) -> list[str]:
    """Changed paths from `git status --porcelain`, leaving out evaluation output folders."""
    paths = []
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].split(" -> ")[-1].strip().strip('"')
        if not path.startswith(OUTPUT_DIRS):
            paths.append(path)
    return paths


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        commit = out.stdout.strip()
        if out.returncode != 0 or not commit:
            return "uncommitted"
        porcelain = subprocess.run(
            ["git", "status", "--porcelain"],  # noqa: S607
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout
        return commit + ("-dirty" if source_changes(porcelain) else "")
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for pkg in _PACKAGES:
        try:
            versions[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            continue
    return versions


class RunRecorder:
    def __init__(self, name: str, settings: Settings, base_dir: Path | None = None) -> None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        root = base_dir or PROJECT_ROOT / "experiments" / "results"
        self.dir = root / f"{stamp}_{name}"
        copy = 2
        while self.dir.exists():  # never overwrite a previous run (same name, same second)
            self.dir = root / f"{stamp}_{name}_x{copy}"
            copy += 1
        self.dir.mkdir(parents=True)
        self.name = name
        self._pred = (self.dir / "predictions.jsonl").open("w", encoding="utf-8")
        self._err = (self.dir / "errors.jsonl").open("w", encoding="utf-8")
        self.n_errors = 0
        (self.dir / "config.yaml").write_text(
            yaml.safe_dump(json.loads(settings.model_dump_json()), sort_keys=False),
            encoding="utf-8",
        )
        self.meta: dict[str, Any] = {
            "name": name,
            "started_at": datetime.now(UTC).isoformat(),
            "git_commit": git_commit(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "packages": package_versions(),
        }

    def prediction(self, record: dict[str, Any]) -> None:
        self._pred.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def error(self, sample_id: str, message: str) -> None:
        self.n_errors += 1
        self._err.write(json.dumps({"sample_id": sample_id, "error": message}) + "\n")

    def finish(
        self,
        metrics: dict[str, Any],
        summary_md: str,
        experiment: dict[str, Any] | None = None,
        **meta: Any,
    ) -> Path:
        """Write meta, metrics and summary. `experiment` (see `configurations.experiment_metadata`)
        is stored in both meta.json and metrics.json so every number carries its configuration."""
        self._pred.close()
        self._err.close()
        self.meta.update(meta)
        if experiment is not None:
            self.meta["experiment"] = experiment
            metrics = {**metrics, "experiment": experiment}
        self.meta["finished_at"] = datetime.now(UTC).isoformat()
        self.meta["errors"] = self.n_errors
        (self.dir / "meta.json").write_text(
            json.dumps(self.meta, indent=2, default=str), encoding="utf-8"
        )
        (self.dir / "metrics.json").write_text(
            json.dumps(metrics, indent=2, default=str), encoding="utf-8"
        )
        (self.dir / "summary.md").write_text(summary_md, encoding="utf-8")
        return self.dir
