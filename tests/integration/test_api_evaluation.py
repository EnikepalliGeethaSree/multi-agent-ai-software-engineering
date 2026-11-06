"""Evaluation API (baseline comparison, run configurations) and the CLI's configuration flag."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from marl_agents.api import create_app
from marl_agents.cli import main
from marl_agents.config import Settings


def _run(root: Path, name: str, metrics: dict, meta: dict, config: dict | None) -> None:  # type: ignore[type-arg]
    d = root / name
    d.mkdir(parents=True)
    (d / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    if config is not None:
        (d / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")


@pytest.fixture
def client(settings: Settings, tmp_path: Path):  # type: ignore[no-untyped-def]
    results = tmp_path / "results"
    det = {"expected": 17, "matched": 16, "tp": 13, "fp": 0, "fn": 1, "recall": 16 / 17}
    # a run saved before the ablation framework (config.yaml only) ...
    _run(results, "20260101T000000Z_planted_full", {"detection": det},
         {"llm_provider": "groq", "llm_model": "m"},
         {"review": {"mode": "full"}, "rag": {"enabled": True}, "llm": {"provider": "groq"}})  # fmt: skip
    # ... and one with the experiment block
    exp = {"configuration": {"key": "static_only"}, "sample_count": 17, "n_evaluated": 17,
           "n_failed": 0, "group_id": "abl-1", "repeat": 1}  # fmt: skip
    _run(results, "20260102T000000Z_planted_static_only", {"detection": det, "experiment": exp},
         {"experiment": exp}, {"review": {"mode": "static_only"}, "rag": {"enabled": True}})  # fmt: skip
    app = create_app(settings, tmp_path / "jobs", results, tmp_path / "dist")
    with TestClient(app) as c:
        yield c


def test_experiments_carry_their_configuration(client: TestClient) -> None:
    runs = {r["name"]: r for r in client.get("/api/experiments").json()}
    old = runs["20260101T000000Z_planted_full"]["experiment"]
    assert old["configuration"]["key"] == "static_llm_rag" and old["recorded"] is False
    assert old["configuration"]["rag"] is True and old["model"] == "m"
    new = runs["20260102T000000Z_planted_static_only"]["experiment"]
    assert new["configuration"]["label"] == "Static Only" and new["configuration"]["rag"] is False
    assert new["group_id"] == "abl-1" and new["recorded"] is True and new["model"] is None


def test_evaluation_summary_endpoint(client: TestClient) -> None:
    body = client.get("/api/evaluation/summary").json()
    rows = {r["configuration"]["key"]: r for r in body["master"]["rows"]}
    assert rows["static_only"]["values"]["planted_recall"] == pytest.approx(16 / 17)
    assert rows["llm_only"]["status"] == "not_run"
    planted = next(t for t in body["tables"] if t["id"] == "planted")
    d = next(r for r in planted["rows"] if r["configuration"]["key"] == "static_llm_rag")
    assert d["model"] == "m" and d["run_ids"] == ["20260101T000000Z_planted_full"]
    assert {x["key"] for x in body["definitions"]} >= {"precision", "recall", "f1", "roc_auc"}
    assert any("not system-level" in s for s in body["scope"])


def test_cli_rejects_a_configuration_that_contradicts_mode(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["eval", "planted", "--configuration", "static_llm_rag", "--no-rag"]) == 2
    assert main(["eval", "planted", "--configuration", "llm_only", "--mode", "full"]) == 2
    assert "conflicts" in capsys.readouterr().err


def test_cli_rejects_unknown_ablation_configuration(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["eval", "ablation", "--configurations", "static_only,magic"]) == 2
    assert "unknown configuration" in capsys.readouterr().err
